#!/usr/bin/env python3
"""
图片描述生成步骤（使用专家路由系统）

功能：
- 使用专家路由系统为图片生成描述
- 根据内容类型自动选择最合适的专家模型
- 支持 NSFW、Gore、文档、普通图片的专业化处理
- 智能显存管理，适配 16GB 显卡

处理流程：
1. 加载 QC 结果（image_qc_v1.jsonl）
2. 筛选需要描述的图片（VISUAL_ONLY, VISUAL_PRIMARY, HYBRID_*）
3. 对每张图片：
   a. 使用 Triage 分类器判断内容类型
   b. 路由到对应的专家模型
   c. 生成专业化描述
4. 输出描述结果

专家路由系统：
- TYPE_A_NSFW → NSFWExpert (双模型 Ensemble)
  * **模型 1**: MiniCPM-V 4.5 Abliterated (int8)
    - 无审查版本，诚实描述解剖学细节
    - 显存占用：~10GB
  * **模型 2**: qwen2.5-vl-7b-nsfw-caption-v3 (bfloat16)
    - 专业 NSFW 描述模型，详细且准确
    - 显存占用：~8GB
  * **Ensemble 策略**：
    - Serial: MiniCPM 优先，太短时补充 nsfw-v3
    - Fusion: 两个模型都生成，智能融合去重（推荐）
    - Parallel: 两个都生成，选择更详细的
    - Dynamic: 根据图片复杂度动态选择
  * **关键修复**: MiniCPM resampler 反量化修复（解决 int8 量化问题）
  
- TYPE_B_GORE → GoreExpert (Qwen2.5-VL Abliterated 4-bit)
  * 处理暴力、血腥内容
  * 显存占用：~8GB
  
- TYPE_C_NORMAL → CaptionExpert (Qwen2.5-VL Safe)
  * 处理普通图片（风景、人物、物品等）
  * 主力模型，覆盖大部分场景
  * 显存占用：~8GB
  
- TYPE_D_DOC → DocExpert (Pixtral 12B GGUF Q5_K_M)
  * 专门处理文档、截图、政治敏感内容
  * 使用 GGUF 量化，节省显存
  * 显存占用：~8.3GB

显存管理策略：
- 单次只加载一个专家模型（16GB 显卡约束）
- 模型按需加载/卸载
- 每处理 20 张图片主动清理显存
- 使用 gc.collect() + torch.cuda.empty_cache()
- 环境变量：PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

输入：
- artifacts/before_merge/image/image_qc_v1.jsonl: QC 结果（包含路由分类）
- raw/image/: 图片文件目录
- configs/caption.yaml: Caption 配置（模型路径、生成参数）

输出：
- artifacts/before_merge/image/image_caption_v1.jsonl: 描述结果
  * 包含：msg_uid, content_type, caption, model_used, generation_time

依赖：
- scripts/image/experts/expert_router.py: 专家路由器
- scripts/image/experts/nsfw_expert.py: NSFW 专家
- scripts/image/experts/gore_expert.py: Gore 专家
- scripts/image/experts/caption_expert.py: 普通图片专家
- scripts/image/experts/doc_expert.py: 文档专家
- transformers, torch, PIL

使用示例：
    # 完整运行
    python scripts/image/run_all/_02_run_caption.py
    
    # 测试模式（仅处理前 10 张）
    python scripts/image/run_all/_02_run_caption.py --sample 10

性能参考（RTX 5070 Ti 16GB）：
- 处理速度：~10-15 秒/张（取决于模型和图片复杂度）
- 显存占用：~10-13GB（峰值）
- Triage 分类：~1 秒/张
- 模型切换：~5-10 秒

注意事项：
- 确保先运行 _01_run_ocr.py 生成 QC 文件
- 16GB 显卡建议使用量化模型
- 长时间运行建议定期检查显存使用情况

作者：forcifer
更新于：2026-02-02
"""

import os
# Reduce CUDA memory fragmentation
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

import sys
import json
import yaml
import logging
import argparse
import gc
import torch
from pathlib import Path
from tqdm import tqdm
import transformers

# 确保 tqdm 输出到 stderr 以便实时显示
tqdm_kwargs = {"file": sys.stderr, "dynamic_ncols": True}

# Suppress transformers logging
transformers.logging.set_verbosity_error()

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._common.path_utils import PATHS
from scripts.image.loader import get_image_path
from scripts.image.experts.expert_router import ExpertRouter

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_caption_config(config_path: Path = None) -> dict:
    """
    加载 caption.yaml 配置文件
    
    Args:
        config_path: 配置文件路径，默认为 configs/caption.yaml
    
    Returns:
        配置字典，包含：
        - models: 模型路径配置
        - experts: 各专家模型的生成参数
        - triage: Triage 分类器配置
    
    Example:
        >>> config = load_caption_config()
        >>> print(config['models']['qwen2_5_vl'])
    """
    if not config_path:
        config_path = PROJECT_ROOT / 'configs' / 'caption.yaml'
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main():
    """
    主函数：执行完整的图片描述生成流程
    
    流程：
    1. 解析命令行参数（--sample）
    2. 加载 QC 结果，筛选需要描述的图片
    3. 初始化专家路由器
    4. 批量处理图片：
       - Triage 分类
       - 路由到专家模型
       - 生成描述
       - 定期清理显存
    5. 输出统计信息
    
    命令行参数：
        --sample N: 仅处理前 N 张图片（测试用）
    
    输出统计：
        - 总处理数
        - 各类型分布（NSFW/Gore/Normal/Doc）
        - 错误数
    """
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='Generate captions using Expert Router')
    parser.add_argument('--sample', type=int, default=0, help='仅处理前N张图片（测试用）')
    args = parser.parse_args()
    
    # Paths
    before_merge = PATHS.get('artifacts', {}).get('image_before', f'{PROJECT_ROOT}/artifacts/before_merge/image')
    qc_file = os.path.join(before_merge, 'image_qc_v1.jsonl')
    output_file = os.path.join(before_merge, 'image_caption_v1.jsonl')
    raw_dir = PATHS.get('dirs', {}).get('raw', '/data/demo/raw')
    
    # Target classes that need caption
    target_classes = [
        'VISUAL_ONLY', 
        'VISUAL_PRIMARY', 
        'HYBRID_VISUAL_MAIN', 
        'HYBRID_TEXT_MAIN'  # Also caption text-heavy images for context
    ]
    
    if not os.path.exists(qc_file):
        logger.error(f"QC file not found: {qc_file}")
        logger.info("Please run _01_run_ocr.py first.")
        return
    
    # Load targets
    logger.info("Scanning for images to caption...")
    targets = []
    with open(qc_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if item.get('route_class') in target_classes:
                    targets.append(item)
            except json.JSONDecodeError:
                continue
    
    logger.info(f"Found {len(targets)} images to process.")
    
    if len(targets) == 0:
        logger.warning("No images found. Check if QC file contains route_class field.")
        return
    
    # 应用 sample 限制
    if args.sample > 0:
        targets = targets[:args.sample]
        logger.info(f"Sample mode: processing only {len(targets)} images")
    
    # Load configuration
    logger.info("Loading caption configuration...")
    config = load_caption_config()
    
    # Initialize Expert Router with config
    logger.info("Initializing Expert Router...")
    logger.info("  - TYPE_A_NSFW → NSFWExpert (Ensemble: MiniCPM-V 4.5 + nsfw-caption-v3)")
    logger.info("  - TYPE_B_GORE → GoreExpert (Qwen2.5-VL Abliterated)")
    logger.info("  - TYPE_C_NORMAL → CaptionExpert (Qwen2.5-VL Safe)")
    logger.info("  - TYPE_D_DOC → DocExpert (Pixtral 12B)")
    router = ExpertRouter(config=config)
    
    # Clear previous output
    if os.path.exists(output_file):
        os.remove(output_file)
    
    # Process images
    stats = {
        'total': 0,
        'TYPE_A_NSFW': 0,
        'TYPE_B_GORE': 0,
        'TYPE_C_NORMAL': 0,
        'TYPE_D_DOC': 0,
        'errors': 0
    }
    
    # 显存管理：每处理 N 张图片后主动清理
    CLEANUP_INTERVAL = 20  # 每 20 张图片清理一次
    
    for idx, item in enumerate(tqdm(targets, desc="图片描述", **tqdm_kwargs), 1):
        msg_uid = item.get('msg_uid')
        media_path = item.get('media_path')
        route_class = item.get('route_class', 'UNKNOWN')
        
        if not media_path:
            continue
            
        abs_path = get_image_path(media_path, raw_dir)
        
        # Get router features from OCR results
        router_features = {
            'text_area_ratio': item.get('text_area_ratio', 0),
            'ocr_text': item.get('ocr_text', '')
        }
        
        try:
            # Process through Expert Router
            result = router.process_image(
                msg_uid=msg_uid,
                image_path=abs_path,
                router_features=router_features,
                route_class=route_class
            )
            
            # Update stats
            stats['total'] += 1
            content_type = result.content_type
            if content_type in stats:
                stats[content_type] += 1
            
            # Check for errors
            if result.caption.startswith('[ERROR]'):
                stats['errors'] += 1
                logger.warning(f"{msg_uid}: {result.caption[:80]}...")
            
            # Convert to dict and write
            output_record = router.result_to_dict(result)
            
            # Write incrementally
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(output_record, ensure_ascii=False) + '\n')
                
        except Exception as e:
            stats['errors'] += 1
            logger.error(f"Error processing {msg_uid}: {e}")
        
        # 定期清理显存
        if idx % CLEANUP_INTERVAL == 0:
            logger.info(f"Processed {idx}/{len(targets)}, performing VRAM cleanup...")
            router._unload_all_experts()
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
    
    # Cleanup
    logger.info("Cleaning up resources...")
    router.cleanup()
    
    # Summary
    logger.info("=" * 60)
    logger.info("Captioning Complete!")
    logger.info("=" * 60)
    logger.info(f"  Total processed: {stats['total']}")
    logger.info(f"  TYPE_A_NSFW: {stats['TYPE_A_NSFW']}")
    logger.info(f"  TYPE_B_GORE: {stats['TYPE_B_GORE']}")
    logger.info(f"  TYPE_C_NORMAL: {stats['TYPE_C_NORMAL']}")
    logger.info(f"  TYPE_D_DOC: {stats['TYPE_D_DOC']}")
    logger.info(f"  Errors: {stats['errors']}")
    logger.info(f"  Output: {output_file}")


if __name__ == '__main__':
    main()
