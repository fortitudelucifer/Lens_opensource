#!/usr/bin/env python3
"""
NSFW 专家模块 (NSFW Expert Module)

功能：
- NSFW 内容详细分析（解剖学细节、动作描述）
- Ensemble 策略：MiniCPM-V 4.5 Abliterated + qwen2.5-vl-7b-nsfw-caption-v3
- 支持四种 Ensemble 模式：Serial、Parallel、Dynamic、Fusion

模型组合：
1. MiniCPM-V 4.5 Abliterated (int8)
   - 无审查版本，诚实描述解剖学细节
   - 修复 resampler 量化问题（反量化 Linear8bitLt 层）
   
2. qwen2.5-vl-7b-nsfw-caption-v3 (bfloat16)
   - 详细专业的 NSFW 描述
   - 补充细节和氛围描述

Ensemble 模式：
- Serial（串行）：MiniCPM 优先，输出太短时补充 nsfw-v3
- Parallel（并行）：两个都生成，选择更详细的
- Dynamic（动态）：MiniCPM 优先，太短则切换到 nsfw-v3
- Fusion（融合）：两个都生成，智能融合去重（推荐）

Fusion 融合策略：
1. 将两个描述拆分为句子
2. 识别相似/重复的句子（相似度 > 0.6）
3. 对于重复内容，保留更详细的版本
4. 合并所有独特的句子
5. 按逻辑顺序重组（场景→人物→动作→细节→氛围）

Resampler 量化修复：
- 问题：wavespeed 的 int8 模型中 resampler 的 attn.out_proj 和 kv_proj 被量化
- 根因：torch.nn.MultiheadAttention 内部直接调用 F.linear() 绕过了 bitsandbytes
- 解决：通过单位矩阵提取反量化后的权重，替换为普通 nn.Linear(float16)

显存管理：
- 两个模型互斥加载（16GB 5070 Ti 约束）
- 切换时自动卸载当前模型并清理显存

使用示例：
    from scripts.image.experts.nsfw_expert import NSFWExpert
    
    # Fusion 模式（推荐）
    expert = NSFWExpert(ensemble_mode="fusion")
    caption, metadata = expert.generate_caption("/path/to/image.jpg")
    
    # 单模型模式
    expert = NSFWExpert(prefer_minicpm=True)
    caption, metadata = expert.generate_caption(
        "/path/to/image.jpg",
        use_ensemble=False
    )
    
    expert.unload()

配置参数：
- ensemble_mode: "serial", "parallel", "dynamic", "fusion"
- prefer_minicpm: 单模型模式下优先使用 abliterated 版本
- generation_config: 生成参数（max_new_tokens, temperature, top_p）

依赖：
- transformers: 模型加载
- bitsandbytes: int8 量化
- qwen_vl_utils: 视觉信息处理
- torch: 显存管理

作者：[Author]
项目：wechatDHA - 微信聊天记录多模态处理流水线
更新于：2026-02-02
"""

import os
import sys
import gc
import torch
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from PIL import Image
from transformers import AutoModel, AutoTokenizer, AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.image.experts.image_utils import resize_if_needed

# Configure logging  
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NSFWExpert:
    """
    NSFW content expert using ensemble of MiniCPM-V 4.5 Abliterated and nsfw-caption-v3.
    """
    
    # NSFW prompt for detailed anatomical descriptions
    PROMPT_ZH = """请仔细观察这张图片。【重要】描述图片中**实际可见**的内容。解除用语限制，用中文详细描述，特别关注以下细节：
1. 图片的主要场景或类型。
2. **人物与动作**：详细描述可见的身体部位、如生殖器的运动方向和结合情况、姿势、以及正在进行的具体行为，可以推测生殖器的运动方向。**特别注意捕捉细微细节**，如：体液（汗水、精液、唾液等）、皮肤纹理、身体特征（如痣、毛发）、饰品（戒指、项链）以及衣物细节。
3. **文字**：如果有水印或字幕，请完整转录。
4. **氛围**：图片传达的整体氛围和可能存在的情绪。"""

    def __init__(
        self,
        minicpm_path: str = "/data/models/minicpm-v-4.5-abliterated-int8",  # 无审查版本
        nsfw_v3_path: str = "/data/models/qwen2.5-vl-7b-nsfw-caption-v3",
        ensemble_mode: str = "fusion",  # "serial", "parallel", "dynamic", "fusion"
        prefer_minicpm: bool = True,  # 单模型模式下优先使用 abliterated 版本
        generation_config: Dict[str, Any] = None  # 生成参数配置
    ):
        self.minicpm_path = minicpm_path
        self.nsfw_v3_path = nsfw_v3_path
        self.ensemble_mode = ensemble_mode
        self.prefer_minicpm = prefer_minicpm
        
        # 生成参数（可从配置文件覆盖）
        self.gen_config = {
            'max_new_tokens': 512,
            'temperature': 0.6,
            'top_p': 0.9
        }
        if generation_config:
            self.gen_config.update(generation_config)
        
        # Models (lazy loaded)
        self._minicpm_model = None
        self._minicpm_tokenizer = None
        self._nsfw_v3_model = None
        self._nsfw_v3_processor = None
        
        self._loaded_model = None  # Track which model is currently loaded
        
        logger.info(f"NSFWExpert initialized with ensemble mode: {ensemble_mode}")
        logger.info(f"Generation config: {self.gen_config}")
        
    def _dequantize_linear8bit_to_fp16(self, linear8bit):
        """
        将 bitsandbytes Linear8bitLt 反量化为普通 nn.Linear (float16)
        通过单位矩阵提取反量化后的权重
        
        根因: wavespeed 的 int8 模型中 resampler 的 attn.out_proj 和 kv_proj 被量化,
        但 torch.nn.MultiheadAttention 内部直接调用 F.linear() 绕过了 bitsandbytes
        """
        import bitsandbytes as bnb
        
        device = linear8bit.weight.device
        in_features = linear8bit.in_features
        out_features = linear8bit.out_features
        has_bias = linear8bit.bias is not None
        
        # 创建新的普通 Linear 层
        new_linear = torch.nn.Linear(
            in_features,
            out_features,
            bias=has_bias,
            device='cpu',
            dtype=torch.float16
        )
        
        # 通过单位矩阵提取反量化后的权重
        with torch.no_grad():
            identity = torch.eye(in_features, dtype=torch.float16, device=device)
            output = linear8bit(identity)
            
            if has_bias:
                weight_t = output - linear8bit.bias
            else:
                weight_t = output
            
            new_linear.weight.data = weight_t.T.cpu()
            
            if has_bias:
                new_linear.bias.data = linear8bit.bias.cpu().to(torch.float16)
        
        return new_linear.to(device)
    
    def _fix_resampler_quantization(self, model):
        """
        修复 resampler 中被错误量化的层
        将 Linear8bitLt 替换为普通的 nn.Linear(float16)
        """
        import bitsandbytes as bnb
        
        dequantized_count = 0
        
        # 1. 反量化 resampler.attn.out_proj
        if hasattr(model.resampler, 'attn') and hasattr(model.resampler.attn, 'out_proj'):
            out_proj = model.resampler.attn.out_proj
            if isinstance(out_proj, bnb.nn.Linear8bitLt):
                logger.info("  Dequantizing resampler.attn.out_proj...")
                model.resampler.attn.out_proj = self._dequantize_linear8bit_to_fp16(out_proj)
                dequantized_count += 1
        
        # 2. 反量化 resampler.kv_proj
        if hasattr(model.resampler, 'kv_proj'):
            kv_proj = model.resampler.kv_proj
            if isinstance(kv_proj, bnb.nn.Linear8bitLt):
                logger.info("  Dequantizing resampler.kv_proj...")
                model.resampler.kv_proj = self._dequantize_linear8bit_to_fp16(kv_proj)
                dequantized_count += 1
        
        if dequantized_count > 0:
            logger.info(f"  ✅ Dequantized {dequantized_count} layers in resampler")
        
        return model
    
    def _load_minicpm(self):
        """Load MiniCPM-V 4.5 Abliterated int8 with resampler fix"""
        if self._minicpm_model is not None:
            return
            
        # Unload other model first if needed
        self._unload_nsfw_v3()
        
        # 强制清理显存，为 MiniCPM 腾出空间
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        logger.info(f"Loading MiniCPM-V 4.5 Abliterated from {self.minicpm_path}...")
        
        # 使用 device_map="auto" 直接加载到 CUDA（bitsandbytes int8 需要 CUDA）
        self._minicpm_model = AutoModel.from_pretrained(
            self.minicpm_path,
            device_map="auto",
            trust_remote_code=True,
        )
        logger.info("MiniCPM model loaded successfully")
        
        self._minicpm_model = self._minicpm_model.eval()
        
        # 关键修复: 反量化 resampler 中被错误量化的层
        logger.info("Applying resampler quantization fix...")
        self._minicpm_model = self._fix_resampler_quantization(self._minicpm_model)
        
        self._minicpm_tokenizer = AutoTokenizer.from_pretrained(
            self.minicpm_path,
            trust_remote_code=True
        )
        
        self._loaded_model = "minicpm"
        
        logger.info("MiniCPM-V 4.5 Abliterated loaded successfully.")
    
    def _load_nsfw_v3(self):
        """Load nsfw-caption-v3 with bfloat16"""
        if self._nsfw_v3_model is not None:
            return
            
        # Unload other model first if needed
        self._unload_minicpm()
        
        # 强制清理显存
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        
        logger.info(f"Loading nsfw-caption-v3 from {self.nsfw_v3_path}...")
        
        self._nsfw_v3_model = AutoModelForImageTextToText.from_pretrained(
            self.nsfw_v3_path,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            trust_remote_code=True
        )
        self._nsfw_v3_processor = AutoProcessor.from_pretrained(
            self.nsfw_v3_path,
            trust_remote_code=True
        )
        self._loaded_model = "nsfw_v3"
        
        logger.info("nsfw-caption-v3 loaded.")
    
    def _unload_minicpm(self):
        """Unload MiniCPM"""
        if self._minicpm_model is not None:
            del self._minicpm_model
            del self._minicpm_tokenizer
            self._minicpm_model = None
            self._minicpm_tokenizer = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("MiniCPM-V 4.5 Abliterated unloaded.")
            
    def _unload_nsfw_v3(self):
        """Unload nsfw-v3"""
        if self._nsfw_v3_model is not None:
            del self._nsfw_v3_model
            del self._nsfw_v3_processor
            self._nsfw_v3_model = None
            self._nsfw_v3_processor = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("nsfw-caption-v3 unloaded.")
            
    def _generate_with_minicpm(self, image_path: str) -> str:
        """Generate caption using MiniCPM-V 4.5 Abliterated (按官方示例)"""
        self._load_minicpm()
        
        # 预处理：缩放大图以避免OOM
        image = resize_if_needed(image_path)
        question = self.PROMPT_ZH
        msgs = [{'role': 'user', 'content': [image, question]}]
        
        # 按官方示例调用
        answer = self._minicpm_model.chat(
            msgs=msgs,
            tokenizer=self._minicpm_tokenizer,
            enable_thinking=False,
            stream=False,
            sampling=True,
            temperature=self.gen_config['temperature'],
            max_new_tokens=self.gen_config['max_new_tokens'],
        )
        return answer
        
    def _generate_with_nsfw_v3(self, image_path: str) -> str:
        """Generate caption using nsfw-caption-v3"""
        self._load_nsfw_v3()
        
        # 预处理：缩放大图以避免OOM
        img = resize_if_needed(image_path)
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": img},
                    {"type": "text", "text": self.PROMPT_ZH},
                ],
            }
        ]
        
        text = self._nsfw_v3_processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self._nsfw_v3_processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self._nsfw_v3_model.device)
        
        with torch.no_grad():
            generated_ids = self._nsfw_v3_model.generate(
                **inputs,
                max_new_tokens=self.gen_config['max_new_tokens'],
                temperature=self.gen_config['temperature'],
                top_p=self.gen_config['top_p']
            )
            
        generated_ids_trimmed = [
            out_ids[len(in_ids):] 
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self._nsfw_v3_processor.batch_decode(
            generated_ids_trimmed, 
            skip_special_tokens=True, 
            clean_up_tokenization_spaces=False
        )
        
        return output_text[0]
    
    def _extract_sentences(self, text: str) -> List[str]:
        """将文本拆分为句子列表"""
        import re
        # 按中文句号、问号、感叹号、换行分割
        sentences = re.split(r'[。！？\n]+', text)
        # 清理空白和过短的句子
        return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 5]
    
    def _sentence_similarity(self, s1: str, s2: str) -> float:
        """计算两个句子的相似度（基于字符重叠）"""
        if not s1 or not s2:
            return 0.0
        # 使用字符级别的 Jaccard 相似度
        set1 = set(s1)
        set2 = set(s2)
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0
    
    def _fuse_captions(self, caption_minicpm: str, caption_nsfw_v3: str) -> str:
        """
        智能融合两个模型的描述：去除重复，有机整合独特信息。
        
        融合策略：
        1. 将两个描述拆分为句子
        2. 识别相似/重复的句子（相似度 > 0.6）
        3. 对于重复内容，保留更详细的版本
        4. 合并所有独特的句子
        5. 按逻辑顺序重组（场景→人物→动作→细节→氛围）
        """
        # 拆分句子
        sentences_a = self._extract_sentences(caption_minicpm)
        sentences_b = self._extract_sentences(caption_nsfw_v3)
        
        # 标记已使用的句子
        used_b = [False] * len(sentences_b)
        
        # 收集最终句子
        final_sentences = []
        
        # 遍历 A 的句子，找出与 B 重复的
        for sa in sentences_a:
            best_match_idx = -1
            best_similarity = 0.0
            
            for i, sb in enumerate(sentences_b):
                if used_b[i]:
                    continue
                sim = self._sentence_similarity(sa, sb)
                if sim > best_similarity:
                    best_similarity = sim
                    best_match_idx = i
            
            if best_similarity > 0.6 and best_match_idx >= 0:
                # 找到相似句子，保留更长/更详细的
                sb = sentences_b[best_match_idx]
                used_b[best_match_idx] = True
                if len(sb) > len(sa):
                    final_sentences.append(sb)
                else:
                    final_sentences.append(sa)
            else:
                # A 的独特句子
                final_sentences.append(sa)
        
        # 添加 B 中未被匹配的独特句子
        for i, sb in enumerate(sentences_b):
            if not used_b[i]:
                final_sentences.append(sb)
        
        # 按内容类型排序（简单启发式）
        def sort_key(s):
            # 场景类型优先
            if any(kw in s for kw in ['场景', '类型', '图片显示', '画面中', '这是']):
                return 0
            # 人物描述
            elif any(kw in s for kw in ['女性', '男性', '人物', '她的', '他的']):
                return 1
            # 动作描述
            elif any(kw in s for kw in ['正在', '进行', '动作', '姿势', '运动', '插入', '抽动']):
                return 2
            # 细节描述
            elif any(kw in s for kw in ['可以看到', '细节', '体液', '皮肤', '毛发', '精液']):
                return 3
            # 文字/水印
            elif any(kw in s for kw in ['文字', '水印', '字幕']):
                return 4
            # 氛围/情绪
            elif any(kw in s for kw in ['氛围', '情绪', '感觉', '整体']):
                return 5
            else:
                return 3  # 默认放在细节部分
        
        final_sentences.sort(key=sort_key)
        
        # 组合成最终描述
        fused = '。'.join(final_sentences)
        if not fused.endswith('。'):
            fused += '。'
        
        return fused
    
    def generate_caption(
        self, 
        image_path: str,
        use_ensemble: bool = True
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate NSFW caption using ensemble strategy.
        
        Args:
            image_path: Path to image
            use_ensemble: If True, use ensemble strategy; otherwise use primary model only
            
        Returns:
            Tuple of (caption, metadata)
        """
        try:
            if not use_ensemble:
                # 单模型模式
                if self.prefer_minicpm:
                    caption = self._generate_with_minicpm(image_path)
                    model_used = "minicpm-v-4.5-abliterated-int8"
                else:
                    caption = self._generate_with_nsfw_v3(image_path)
                    model_used = "nsfw-caption-v3"
                    
                metadata = {
                    "model": model_used,
                    "expert_type": "nsfw",
                    "ensemble_mode": "single",
                    "ensemble_used": False
                }
                return caption, metadata
            
            if self.ensemble_mode == "serial":
                # Serial 模式: MiniCPM 优先，仅当太短时补充 nsfw-v3
                caption = self._generate_with_minicpm(image_path)
                model_used = "minicpm-v-4.5-abliterated-int8"
                ensemble_used = False
                
                # 如果 MiniCPM 输出太短，用 nsfw-v3 补充
                if len(caption) < 150:
                    logger.info("MiniCPM output too short, supplementing with nsfw-v3...")
                    caption_v3 = self._generate_with_nsfw_v3(image_path)
                    caption = self._fuse_captions(caption, caption_v3)
                    model_used = "ensemble"
                    ensemble_used = True
                    
                metadata = {
                    "model": model_used,
                    "expert_type": "nsfw",
                    "ensemble_mode": "serial",
                    "ensemble_used": ensemble_used
                }
                return caption, metadata
                
            elif self.ensemble_mode == "fusion":
                # Fusion 模式: 两个模型都生成，有机融合结果
                logger.info("Fusion mode: generating with both models...")
                
                caption_minicpm = self._generate_with_minicpm(image_path)
                logger.info(f"  MiniCPM: {len(caption_minicpm)} chars")
                
                caption_nsfw_v3 = self._generate_with_nsfw_v3(image_path)
                logger.info(f"  nsfw-v3: {len(caption_nsfw_v3)} chars")
                
                # 有机融合两个描述
                caption = self._fuse_captions(caption_minicpm, caption_nsfw_v3)
                
                metadata = {
                    "model": "ensemble-fusion",
                    "expert_type": "nsfw",
                    "ensemble_mode": "fusion",
                    "ensemble_used": True,
                    "minicpm_len": len(caption_minicpm),
                    "nsfw_v3_len": len(caption_nsfw_v3),
                    "fused_len": len(caption)
                }
                return caption, metadata
                
            elif self.ensemble_mode == "parallel":
                # Parallel 模式: 两个都生成，选择更详细的
                caption_minicpm = self._generate_with_minicpm(image_path)
                caption_nsfw_v3 = self._generate_with_nsfw_v3(image_path)
                
                if len(caption_nsfw_v3) > len(caption_minicpm):
                    caption = caption_nsfw_v3
                    model_used = "nsfw-caption-v3"
                else:
                    caption = caption_minicpm
                    model_used = "minicpm-v-4.5-abliterated-int8"
                    
                metadata = {
                    "model": model_used,
                    "expert_type": "nsfw",
                    "ensemble_mode": "parallel",
                    "ensemble_used": True,
                    "minicpm_len": len(caption_minicpm),
                    "nsfw_v3_len": len(caption_nsfw_v3)
                }
                return caption, metadata
                
            else:  # dynamic
                # Dynamic 模式: MiniCPM 优先，太短则切换
                caption = self._generate_with_minicpm(image_path)
                model_used = "minicpm-v-4.5-abliterated-int8"
                
                if len(caption) < 100:
                    caption = self._generate_with_nsfw_v3(image_path)
                    model_used = "nsfw-caption-v3"
                    
                metadata = {
                    "model": model_used,
                    "expert_type": "nsfw",
                    "ensemble_mode": "dynamic",
                    "ensemble_used": model_used == "nsfw-caption-v3"
                }
                return caption, metadata
                
        except Exception as e:
            logger.error(f"Error generating NSFW caption for {image_path}: {e}")
            raise  # 不再返回 [ERROR]，直接抛出异常让上层处理
    
    def unload(self):
        """Unload all models"""
        self._unload_minicpm()
        self._unload_nsfw_v3()
        self._loaded_model = None


# === Test ===
if __name__ == '__main__':
    print("Testing NSFWExpert...")
    expert = NSFWExpert(ensemble_mode="serial", prefer_minicpm=True)
    
    test_path = "/data/demo/raw/image/test.jpg"
    
    if os.path.exists(test_path):
        caption, meta = expert.generate_caption(test_path, use_ensemble=False)
        print(f"\nCaption:\n{caption}")
        print(f"\nMetadata: {meta}")
    else:
        print(f"Test image not found: {test_path}")
        
    expert.unload()
    print("\nTest complete.")
