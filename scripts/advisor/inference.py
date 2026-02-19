"""
关系顾问推理模块

功能：
- 加载 QLoRA 微调后的 LoRA 适配器进行本地推理
- 支持三种 Agent 类型（neutral/supportive/psychoanalytic）的专用系统提示词
- 4-bit 量化推理（BitsAndBytes），显存占用约 6-8GB
- 支持交互式对话模式和批量推理模式
- 推理完成后自动卸载模型释放显存（auto_unload）

处理流程：
1. 加载基座模型（Qwen3-8B）+ BitsAndBytes 4-bit 量化
2. 加载 LoRA 适配器（从训练输出目录）
3. 构建 prompt（system + user 对话 + 可选的 safe_context）
4. 调用 model.generate() 生成分析文本
5. 解析生成结果，提取分析内容

输入：
- 对话文本（格式化的多模态对话）
- Agent 类型（neutral/supportive/psychoanalytic）
- 安全上下文（可选，来自 SafetyLayer 处理后的云端分析要点）

输出：
- 分析文本（本地模型生成的关系分析）

依赖：
- transformers: 模型加载和推理
- peft: LoRA 适配器加载
- bitsandbytes: 4-bit 量化
- torch: GPU 推理

使用示例：
    from scripts.advisor.inference import AdvisorInference
    
    inference = AdvisorInference(agent_type='neutral')
    result = inference.analyze("ME: 今天好累\\nOTHER: 哦")
    print(result)
    inference.unload()  # 释放显存

性能参考（RTX 5070 Ti 16GB）：
- 模型加载时间：约 10-15 秒
- 推理速度：约 30-50 tokens/秒
- 显存占用：约 6-8GB（4-bit 量化）

注意事项：
- 推理前确保 GPU 显存已释放（其他模型已卸载）
- auto_unload=True 时推理完成后自动卸载，适合单次推理场景
- 批量推理建议设置 auto_unload=False，手动调用 unload()

作者：forcifer
更新于：2026-02-15
"""

import gc
import json
import re
from pathlib import Path
from typing import Optional, Union

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


# Agent 类型的系统提示词
SYSTEM_PROMPTS = {
    'neutral': """你是一位专业的关系顾问，擅长分析情侣/伴侣之间的对话，提供客观、专业的评价和建议。
你的分析应该保持中立，不偏袒任何一方，对双方的问题都要指出。""",

    'supportive': """你是一位支持性的关系顾问，你的首要任务是理解和支持用户（ME）的感受。
你会首先验证用户的情感体验，从用户的角度理解问题，同时保持基本的客观性。

请按以下格式输出分析：

【情感验证】（首先认可 ME 的感受）

【关系状态】（一句话概括）

【对话分析】
- 你的感受是合理的，因为：...
- OTHER 可能的想法：...

【支持性建议】
- 如何照顾自己的情绪：...
- 如何与 OTHER 沟通：...""",

    'psychoanalytic': """你是一位精神分析取向的关系顾问，精通客体关系理论和拉康派精神分析。
你会分析双方的依附风格、防御机制、欲望结构和无意识动态。

请按以下格式输出分析：

【关系动力学】（一句话概括无意识层面的互动）

【依附风格分析】
- ME 的依附风格：（安全型/焦虑型/回避型/混乱型）
- OTHER 的依附风格：...
- 依附互动模式：...

【防御机制识别】
- ME 使用的防御机制：...
- OTHER 使用的防御机制：...

【拉康三界分析】
- 想象界：...
- 象征界：...
- 实在界：...

【深层建议】
- 需要觉察的无意识模式：...
- 可能的成长方向：..."""
}


class AdvisorInference:
    """关系顾问推理类"""
    
    def __init__(
        self,
        agent_type: str = 'neutral',
        model_dir: Optional[str] = None,
        base_model: str = '/data/models/Qwen3-8B-Instruct',
        quantization: str = '4bit',
        device_map: str = 'auto',
    ):
        """
        初始化推理器
        
        Args:
            agent_type: Agent 类型 (neutral/supportive/psychoanalytic)
            model_dir: LoRA 模型目录（默认自动生成）
            base_model: 基座模型路径
            quantization: 量化方式 (4bit/8bit/none)
            device_map: 设备映射
        """
        self.agent_type = agent_type
        self.base_model = base_model
        self.quantization = quantization
        self.device_map = device_map
        
        # 模型目录（优先 Unsloth deanon → HF deanon → 旧版无 deanon）
        if model_dir is None:
            candidates = [
                Path('advisor_out/models') / f'relationship_advisor_{agent_type}_deanon_unsloth',
                Path('advisor_out/models') / f'relationship_advisor_{agent_type}_deanon',
                Path('advisor_out/models') / f'relationship_advisor_{agent_type}',
            ]
            self.model_dir = next(
                (p for p in candidates if (p / 'adapter_config.json').exists()),
                candidates[-1],
            )
        else:
            self.model_dir = Path(model_dir)
        
        # 系统提示词
        self.system_prompt = SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS['neutral'])
        
        self.model = None
        self.tokenizer = None
        self._loaded = False
    
    def load_model(self):
        """加载模型"""
        if self._loaded:
            return
        
        print(f"加载基座模型: {self.base_model}")
        print(f"加载 LoRA 权重: {self.model_dir}")
        
        # 量化配置
        if self.quantization == '4bit':
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type='nf4',
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
        elif self.quantization == '8bit':
            bnb_config = BitsAndBytesConfig(
                load_in_8bit=True,
            )
        else:
            bnb_config = None
        
        # 加载基座模型
        self.model = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            quantization_config=bnb_config,
            device_map=self.device_map,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
        )
        
        # 加载 tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.base_model,
            trust_remote_code=True,
        )
        
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        # 加载 LoRA 权重（如果存在）
        if self.model_dir.exists() and (self.model_dir / 'adapter_config.json').exists():
            print("加载 LoRA 权重...")
            self.model = PeftModel.from_pretrained(
                self.model,
                str(self.model_dir),
            )
            print("LoRA 权重加载完成")
        else:
            print(f"警告：LoRA 权重不存在 ({self.model_dir})，使用基座模型")
        
        self._loaded = True
        print("模型加载完成")
    
    def unload_model(self):
        """卸载模型释放显存"""
        if self.model is not None:
            del self.model
            self.model = None
        
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        
        self._loaded = False
        
        gc.collect()
        torch.cuda.empty_cache()
        
        print("模型已卸载，显存已释放")

    def analyze(
        self,
        conversation: str,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_new_tokens: int = 1024,
    ) -> str:
        """
        分析对话
        
        Args:
            conversation: 对话文本（格式：ME: xxx\nOTHER: xxx）
            temperature: 生成温度
            top_p: Top-p 采样
            max_new_tokens: 最大生成 token 数
        
        Returns:
            分析结果文本
        """
        if not self._loaded:
            self.load_model()
        
        # 构建消息
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': f"请分析以下对话：\n\n{conversation}"},
        ]
        
        # 应用 chat template
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        
        # Tokenize
        inputs = self.tokenizer(text, return_tensors='pt').to(self.model.device)
        
        # 生成
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=True,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        
        # 解码
        generated = outputs[0][inputs['input_ids'].shape[1]:]
        result = self.tokenizer.decode(generated, skip_special_tokens=True)
        
        # 清理 Qwen3 空 <think> 标签
        result = re.sub(r'<think>\s*</think>\s*', '', result)
        
        return result.strip()
    
    def analyze_batch(
        self,
        conversations: list[str],
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_new_tokens: int = 1024,
        show_progress: bool = True,
    ) -> list[str]:
        """
        批量分析对话
        
        Args:
            conversations: 对话文本列表
            temperature: 生成温度
            top_p: Top-p 采样
            max_new_tokens: 最大生成 token 数
            show_progress: 是否显示进度条
        
        Returns:
            分析结果列表
        """
        from tqdm import tqdm
        
        if not self._loaded:
            self.load_model()
        
        results = []
        iterator = tqdm(conversations, desc='分析对话') if show_progress else conversations
        
        for conv in iterator:
            try:
                result = self.analyze(
                    conv,
                    temperature=temperature,
                    top_p=top_p,
                    max_new_tokens=max_new_tokens,
                )
                results.append(result)
            except Exception as e:
                print(f"分析出错: {e}")
                results.append(f"[分析失败: {e}]")
        
        return results
    
    def analyze_from_file(
        self,
        input_path: str,
        output_path: str,
        temperature: float = 0.7,
        top_p: float = 0.9,
        max_new_tokens: int = 1024,
    ):
        """
        从文件读取对话并分析
        
        Args:
            input_path: 输入文件路径（JSONL 格式，每行包含 conversation_text 字段）
            output_path: 输出文件路径
            temperature: 生成温度
            top_p: Top-p 采样
            max_new_tokens: 最大生成 token 数
        """
        from tqdm import tqdm
        
        if not self._loaded:
            self.load_model()
        
        # 读取输入
        conversations = []
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    conversations.append(data)
        
        print(f"读取了 {len(conversations)} 个对话")
        
        # 分析并写入输出
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for data in tqdm(conversations, desc='分析对话'):
                conv_text = data.get('conversation_text', '')
                
                try:
                    analysis = self.analyze(
                        conv_text,
                        temperature=temperature,
                        top_p=top_p,
                        max_new_tokens=max_new_tokens,
                    )
                except Exception as e:
                    print(f"分析出错: {e}")
                    analysis = f"[分析失败: {e}]"
                
                # 添加分析结果
                result = {
                    **data,
                    'analysis': analysis,
                    'agent_type': self.agent_type,
                }
                
                f.write(json.dumps(result, ensure_ascii=False) + '\n')
        
        print(f"结果已保存到: {output_path}")
    
    def __enter__(self):
        """上下文管理器入口"""
        self.load_model()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.unload_model()
        return False
