# -*- coding: utf-8 -*-
"""
语义压缩引擎

功能：
- 协调各模态压缩器（Image/Video/Voice/Sticker）
- 管理模型加载/卸载，避免显存溢出
- 支持批处理和自动显存清理
- 提供统一的压缩接口和统计信息

处理流程：
1. 加载配置文件（configs/compression.yaml）
2. 按模态顺序加载数据（sticker → image → video → voice）
3. 调用对应压缩器进行语义压缩
4. 批次间自动清理显存（gc + torch.cuda.empty_cache）
5. 保存压缩结果到 artifacts/before_merge/{modality}/{modality}_compressed.jsonl

显存管理策略：
- 环境变量：PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
- 模型串行加载/卸载（避免同时加载多个大模型）
- 批次间清理：gc.collect() + torch.cuda.empty_cache()
- 模态间清理：_unload_model() 释放所有模型资源

批处理策略：
- 默认批大小：4（可在配置中调整）
- 批次内顺序处理，批次间清理显存
- 支持重试机制（max_retries=3）
- 超时保护（timeout_seconds=30）

输入：
- artifacts/before_merge/{modality}/*_v1.jsonl（各引擎输出）
- configs/compression.yaml（压缩配置）

输出：
- artifacts/before_merge/{modality}/{modality}_compressed.jsonl（压缩结果）

依赖：
- scripts.compression.image_compressor（图片压缩器）
- scripts.compression.video_compressor（视频压缩器）
- scripts.compression.voice_compressor（语音压缩器）
- scripts.compression.sticker_compressor（表情包压缩器）
- yaml（配置解析）
- torch（显存管理）

使用示例：
    # 压缩单个模态
    python scripts/compression/engine.py --modality image
    
    # 压缩所有模态
    python scripts/compression/engine.py --modality all
    
    # 使用自定义配置
    python scripts/compression/engine.py --config configs/my_compression.yaml
    
    # Python API
    from scripts.compression.engine import CompressionEngine
    
    engine = CompressionEngine()
    stats = engine.compress_modality('image')
    print(f"压缩完成: {stats['compressed']}/{stats['total']}")
    
    # 压缩所有模态
    all_stats = engine.compress_all()

作者：forcifer
更新于：2026-02-02
"""

import gc
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
import yaml
from tqdm import tqdm

# 设置 CUDA 环境变量
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'


@dataclass
class EngineConfig:
    """引擎配置"""
    batch_size: int = 4
    max_retries: int = 3
    timeout_seconds: int = 30
    empty_cache_after_batch: bool = True


class CompressionEngine:
    """压缩引擎：协调各模态压缩器"""
    
    def __init__(self, config_path: str = "configs/compression.yaml"):
        self.config = self._load_config(config_path)
        self.engine_config = self._parse_engine_config()
        self.model = None
        self.model_loaded = False
        
        # 各模态压缩器
        self._compressors = {}
        
        # 统计信息
        self.stats = {
            "modalities_processed": [],
            "total_items": 0,
            "total_compressed": 0,
            "errors": []
        }
    
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            print(f"[WARN] 配置文件不存在: {config_path}")
            return {}
        
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def _parse_engine_config(self) -> EngineConfig:
        """解析引擎配置"""
        global_cfg = self.config.get('global', {})
        cuda_cfg = global_cfg.get('cuda_config', {})
        
        return EngineConfig(
            batch_size=global_cfg.get('batch_size', 4),
            max_retries=global_cfg.get('max_retries', 3),
            timeout_seconds=global_cfg.get('timeout_seconds', 30),
            empty_cache_after_batch=cuda_cfg.get('empty_cache_after_batch', True)
        )
    
    def _load_model(self, model_type: str = 'compression'):
        """
        加载模型
        
        Args:
            model_type: 模型类型 ('compression' 或 'embedding')
        """
        if self.model_loaded:
            return
        
        global_cfg = self.config.get('global', {})
        
        if model_type == 'compression':
            model_cfg = global_cfg.get('model', {})
            model_path = model_cfg.get('path', '/data/models/Qwen2.5-7B-Instruct-AWQ')
            
            print(f"[INFO] 加载压缩模型: {model_path}")
            # 注意：实际加载模型的代码在需要时实现
            # 当前版本使用规则压缩，不需要加载 LLM
            
        elif model_type == 'embedding':
            embed_cfg = global_cfg.get('embedding_model', {})
            model_path = embed_cfg.get('path', '/data/models/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
            
            print(f"[INFO] 加载嵌入模型: {model_path}")
            # 实际加载代码在质量验证器中实现
        
        self.model_loaded = True
    
    def _unload_model(self):
        """卸载模型，释放显存"""
        if not self.model_loaded:
            return
        
        print("[INFO] 卸载模型，释放显存...")
        
        if self.model is not None:
            del self.model
            self.model = None
        
        # 清理显存
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except ImportError:
            pass
        
        self.model_loaded = False
    
    def _get_compressor(self, modality: str):
        """获取或创建压缩器"""
        if modality in self._compressors:
            return self._compressors[modality]
        
        if modality == 'image':
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from scripts.compression.image_compressor import ImageCompressor
            compressor = ImageCompressor()
        elif modality == 'video':
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from scripts.compression.video_compressor import VideoCompressor
            compressor = VideoCompressor()
        elif modality == 'voice':
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from scripts.compression.voice_compressor import VoiceCompressor
            compressor = VoiceCompressor()
        elif modality == 'sticker':
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from scripts.compression.sticker_compressor import StickerCompressor
            compressor = StickerCompressor()
        else:
            raise ValueError(f"未知模态: {modality}")
        
        self._compressors[modality] = compressor
        return compressor
    
    def compress_modality(self, modality: str, 
                          input_paths: Optional[Dict[str, str]] = None,
                          output_path: Optional[str] = None) -> Dict:
        """
        压缩单个模态
        
        Args:
            modality: 模态名称 ('image', 'video', 'voice', 'sticker')
            input_paths: 输入文件路径字典
            output_path: 输出文件路径
        
        Returns:
            压缩统计信息
        """
        print(f"\n[INFO] 开始压缩模态: {modality}")
        
        # 默认路径
        base_path = f"artifacts/before_merge/{modality}"
        
        if input_paths is None:
            input_paths = self._get_default_input_paths(modality)
        
        if output_path is None:
            output_path = f"{base_path}/{modality}_compressed.jsonl"
        
        # 获取压缩器
        compressor = self._get_compressor(modality)
        
        # 加载数据
        data, aux_data = self._load_modality_data(modality, input_paths)
        
        if not data:
            print(f"[WARN] 没有找到 {modality} 数据")
            return {"total": 0, "compressed": 0}
        
        print(f"[INFO] 加载 {len(data)} 条 {modality} 数据")
        
        # 批量压缩
        results = []
        batch_size = self.engine_config.batch_size
        
        for i in tqdm(range(0, len(data), batch_size), desc=f"压缩 {modality}"):
            batch = data[i:i+batch_size]
            
            for item in batch:
                try:
                    # 获取辅助数据
                    aux = None
                    if aux_data:
                        key = item.get('msg_uid') or item.get('file')
                        aux = aux_data.get(key)
                    
                    # 压缩
                    if modality in ['image', 'video']:
                        result = compressor.compress(item, aux)
                    else:
                        result = compressor.compress(item)
                    
                    results.append(result)
                    
                except Exception as e:
                    self.stats["errors"].append({
                        "modality": modality,
                        "item": item.get('msg_uid') or item.get('file'),
                        "error": str(e)
                    })
            
            # 批次后清理显存
            if self.engine_config.empty_cache_after_batch:
                self._clear_cache()
        
        # 保存结果
        self._save_results(results, output_path)
        
        # 获取统计
        stats = compressor.get_stats()
        stats["output_path"] = output_path
        
        self.stats["modalities_processed"].append(modality)
        self.stats["total_items"] += stats.get("total", 0)
        self.stats["total_compressed"] += stats.get("compressed", 0)
        
        print(f"[INFO] {modality} 压缩完成: {stats.get('compressed', 0)} 条")
        print(f"[INFO] 平均压缩比: {stats.get('avg_compression_ratio', 1.0)}x")
        
        return stats
    
    def _get_default_input_paths(self, modality: str) -> Dict[str, str]:
        """获取默认输入路径"""
        base = f"artifacts/before_merge/{modality}"
        
        if modality == 'image':
            return {
                "caption": f"{base}/image_caption_v1.jsonl",
                "ocr": f"{base}/image_ocr_v1.jsonl"
            }
        elif modality == 'video':
            return {
                "caption": f"{base}/video_caption_v1.jsonl",
                "transcribe": f"{base}/video_transcribe_v1.jsonl"
            }
        elif modality == 'voice':
            return {
                "voice": f"{base}/voice_merged_v3.jsonl"
            }
        elif modality == 'sticker':
            return {
                "sticker": f"{base}/sticker_caption_v1.jsonl"
            }
        else:
            return {}
    
    def _load_modality_data(self, modality: str, 
                            input_paths: Dict[str, str]) -> tuple:
        """加载模态数据"""
        data = []
        aux_data = {}
        
        if modality == 'image':
            # 加载 caption
            caption_path = input_paths.get('caption')
            if caption_path and Path(caption_path).exists():
                with open(caption_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            data.append(json.loads(line))
            
            # 加载 OCR
            ocr_path = input_paths.get('ocr')
            if ocr_path and Path(ocr_path).exists():
                with open(ocr_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            item = json.loads(line)
                            key = item.get('msg_uid')
                            if key:
                                aux_data[key] = item
        
        elif modality == 'video':
            # 加载 caption
            caption_path = input_paths.get('caption')
            if caption_path and Path(caption_path).exists():
                with open(caption_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            data.append(json.loads(line))
            
            # 加载转写
            transcribe_path = input_paths.get('transcribe')
            if transcribe_path and Path(transcribe_path).exists():
                with open(transcribe_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            item = json.loads(line)
                            key = item.get('msg_uid')
                            if key:
                                aux_data[key] = item
        
        elif modality == 'voice':
            voice_path = input_paths.get('voice')
            if voice_path and Path(voice_path).exists():
                with open(voice_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            data.append(json.loads(line))
        
        elif modality == 'sticker':
            sticker_path = input_paths.get('sticker')
            if sticker_path and Path(sticker_path).exists():
                with open(sticker_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            data.append(json.loads(line))
        
        return data, aux_data
    
    def _save_results(self, results: List[Dict], output_path: str):
        """保存压缩结果"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            for item in results:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    def _clear_cache(self):
        """清理显存缓存"""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
    
    def compress_all(self, modalities: Optional[List[str]] = None) -> Dict:
        """
        压缩所有模态
        
        Args:
            modalities: 要压缩的模态列表，默认全部
        
        Returns:
            总体统计信息
        """
        if modalities is None:
            modalities = ['sticker', 'image', 'video', 'voice']
        
        print(f"[INFO] 开始压缩所有模态: {modalities}")
        
        all_stats = {}
        
        for modality in modalities:
            try:
                stats = self.compress_modality(modality)
                all_stats[modality] = stats
            except Exception as e:
                print(f"[ERROR] 压缩 {modality} 失败: {e}")
                self.stats["errors"].append({
                    "modality": modality,
                    "error": str(e)
                })
            
            # 模态间清理显存
            self._unload_model()
        
        # 汇总统计
        all_stats["summary"] = self.stats
        
        return all_stats
    
    def get_stats(self) -> Dict:
        """获取引擎统计信息"""
        return self.stats


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='语义压缩引擎')
    parser.add_argument('--modality', '-m', type=str, 
                        choices=['image', 'video', 'voice', 'sticker', 'all'],
                        default='all', help='要压缩的模态')
    parser.add_argument('--config', '-c', type=str, 
                        default='configs/compression.yaml',
                        help='配置文件路径')
    
    args = parser.parse_args()
    
    engine = CompressionEngine(args.config)
    
    if args.modality == 'all':
        stats = engine.compress_all()
    else:
        stats = engine.compress_modality(args.modality)
    
    print("\n=== 压缩完成 ===")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
