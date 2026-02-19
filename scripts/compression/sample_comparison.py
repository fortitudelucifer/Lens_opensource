# -*- coding: utf-8 -*-
"""
样本压缩对比脚本

从各模态抽取样本，展示压缩前后的对比
"""

import json
import random
from pathlib import Path
from typing import Dict, List, Any
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.compression.sticker_compressor import StickerCompressor
from scripts.compression.image_compressor import ImageCompressor
from scripts.compression.video_compressor import VideoCompressor
from scripts.compression.voice_compressor import VoiceCompressor


def load_jsonl(path: Path, limit: int = None) -> List[Dict]:
    """加载 JSONL 文件"""
    data = []
    if not path.exists():
        return data
    with open(path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            if line.strip():
                data.append(json.loads(line))
    return data


def print_separator(title: str):
    """打印分隔符"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_comparison(original: str, compressed: str, label: str = ""):
    """打印压缩对比"""
    orig_len = len(original) if original else 0
    comp_len = len(compressed) if compressed else 0
    ratio = orig_len / comp_len if comp_len > 0 else 0
    
    print(f"\n{label}")
    print(f"原始 ({orig_len} 字):")
    print(f"  {original[:500]}{'...' if len(original or '') > 500 else ''}")
    print(f"\n压缩后 ({comp_len} 字, 压缩比 {ratio:.1f}x):")
    print(f"  {compressed}")
    print("-" * 60)


def sample_stickers(n: int = 3):
    """抽样表情包压缩"""
    print_separator("表情包压缩样本")
    
    caption_path = Path("artifacts/before_merge/sticker/sticker_caption_v1.jsonl")
    data = load_jsonl(caption_path)
    
    if not data:
        print("没有找到表情包数据")
        return
    
    # 随机抽样
    samples = random.sample(data, min(n, len(data)))
    compressor = StickerCompressor()
    
    for i, item in enumerate(samples, 1):
        msg_uid = item.get("msg_uid", "unknown")
        caption = item.get("caption", "")
        ocr_text = item.get("full_text", "") or item.get("ocr_text", "")
        
        # 压缩
        result = compressor.compress(item)
        
        print(f"\n【样本 {i}】msg_uid: {msg_uid}")
        
        # 原始内容
        original = f"Caption: {caption}"
        if ocr_text:
            original += f"\nOCR: {ocr_text}"
        
        # 压缩结果
        compressed = result.get("sticker_summary", "")
        intent = result.get("sticker_intent", "")
        confidence = result.get("intent_confidence", 0)
        
        print(f"原始 ({len(caption)} 字):")
        print(f"  {caption[:300]}{'...' if len(caption) > 300 else ''}")
        if ocr_text:
            print(f"  OCR: {ocr_text}")
        
        print(f"\n压缩后:")
        print(f"  摘要: {compressed}")
        print(f"  意图: {intent} (置信度: {confidence:.2f})")
        print(f"  压缩比: {len(caption) / len(compressed) if compressed else 0:.1f}x")
        print("-" * 60)


def sample_images(n: int = 3):
    """抽样图片压缩"""
    print_separator("图片压缩样本")
    
    caption_path = Path("artifacts/before_merge/image/image_caption_v1.jsonl")
    ocr_path = Path("artifacts/before_merge/image/image_ocr_v1.jsonl")
    
    captions = load_jsonl(caption_path)
    ocr_data = {item["msg_uid"]: item for item in load_jsonl(ocr_path)}
    
    if not captions:
        print("没有找到图片数据")
        return
    
    # 随机抽样
    samples = random.sample(captions, min(n, len(captions)))
    compressor = ImageCompressor()
    
    for i, item in enumerate(samples, 1):
        msg_uid = item.get("msg_uid", "unknown")
        caption = item.get("caption", "")
        
        # 合并 OCR 数据
        if msg_uid in ocr_data:
            item["full_text"] = ocr_data[msg_uid].get("full_text", "")
        
        ocr_text = item.get("full_text", "")
        
        # 压缩
        result = compressor.compress(item)
        
        print(f"\n【样本 {i}】msg_uid: {msg_uid}")
        
        orig_len = len(caption) + len(ocr_text)
        print(f"原始 ({orig_len} 字):")
        print(f"  Caption: {caption[:200]}{'...' if len(caption) > 200 else ''}")
        if ocr_text:
            print(f"  OCR: {ocr_text[:100]}{'...' if len(ocr_text) > 100 else ''}")
        
        compressed = result.get("image_summary", "")
        print(f"\n压缩后 ({len(compressed)} 字):")
        print(f"  {compressed}")
        print(f"  压缩比: {orig_len / len(compressed) if compressed else 0:.1f}x")
        print("-" * 60)


def sample_videos(n: int = 2):
    """抽样视频压缩"""
    print_separator("视频压缩样本")
    
    caption_path = Path("artifacts/before_merge/video/video_caption_v1.jsonl")
    transcribe_path = Path("artifacts/before_merge/video/video_transcribe_v1.jsonl")
    
    captions = load_jsonl(caption_path)
    transcribes = {item["msg_uid"]: item for item in load_jsonl(transcribe_path)}
    
    if not captions:
        print("没有找到视频数据")
        return
    
    # 随机抽样
    samples = random.sample(captions, min(n, len(captions)))
    compressor = VideoCompressor()
    
    for i, item in enumerate(samples, 1):
        msg_uid = item.get("msg_uid", "unknown")
        
        # 合并转写数据
        if msg_uid in transcribes:
            item["transcription"] = transcribes[msg_uid].get("transcription", "")
            item["emotion_tags"] = transcribes[msg_uid].get("emotion_tags", [])
        
        # 获取原始内容
        keyframes = item.get("keyframe_captions", [])
        transcription = item.get("transcription", "")
        
        # 压缩
        result = compressor.compress(item)
        
        print(f"\n【样本 {i}】msg_uid: {msg_uid}")
        
        # 计算原始长度
        orig_len = sum(len(kf.get("caption", "")) for kf in keyframes) + len(transcription)
        
        print(f"原始 ({orig_len} 字, {len(keyframes)} 帧):")
        for j, kf in enumerate(keyframes[:3]):  # 只显示前3帧
            print(f"  帧{j}: {kf.get('caption', '')[:80]}...")
        if len(keyframes) > 3:
            print(f"  ... 还有 {len(keyframes) - 3} 帧")
        if transcription:
            trans_text = transcription if isinstance(transcription, str) else str(transcription)
            print(f"  转写: {trans_text[:100]}{'...' if len(trans_text) > 100 else ''}")
        
        compressed = result.get("video_summary", "")
        print(f"\n压缩后 ({len(compressed)} 字):")
        print(f"  {compressed}")
        print(f"  压缩比: {orig_len / len(compressed) if compressed else 0:.1f}x")
        print("-" * 60)


def sample_voices(n: int = 3):
    """抽样语音压缩"""
    print_separator("语音压缩样本")
    
    merged_path = Path("artifacts/before_merge/voice/voice_merged_v3.jsonl")
    data = load_jsonl(merged_path)
    
    if not data:
        print("没有找到语音数据")
        return
    
    # 随机抽样有 voice_analysis 的数据
    samples_with_analysis = [d for d in data if d.get("voice_analysis")]
    if not samples_with_analysis:
        # 如果没有 voice_analysis，就随机抽样
        samples_with_analysis = data
    samples = random.sample(samples_with_analysis, min(n, len(samples_with_analysis)))
    
    compressor = VoiceCompressor()
    
    for i, item in enumerate(samples, 1):
        msg_uid = item.get("msg_uid", item.get("file", "unknown"))
        punct_text = item.get("punct_text", "")
        emotion_tags = item.get("sensevoice", {}).get("emotion_tags", [])
        voice_analysis = item.get("voice_analysis", {})
        
        # 压缩
        result = compressor.compress(item)
        
        print(f"\n【样本 {i}】msg_uid: {msg_uid}")
        
        # 计算原始长度
        analysis_text = ""
        if voice_analysis:
            analysis_text = f"情绪: {voice_analysis.get('emotion_desc', '')} 潜台词: {voice_analysis.get('subtext', '')}"
        
        orig_len = len(punct_text) + len(analysis_text)
        print(f"原始 ({orig_len} 字):")
        print(f"  转写: {punct_text[:150]}{'...' if len(punct_text) > 150 else ''}")
        print(f"  情绪标签: {emotion_tags}")
        if voice_analysis:
            print(f"  分析: {analysis_text[:150]}{'...' if len(analysis_text) > 150 else ''}")
        
        compressed_analysis = result.get("analysis_summary", "") or ""
        print(f"\n压缩后:")
        print(f"  转写: (保留原文)")
        print(f"  情绪标签: {result.get('emotion_tags', emotion_tags)} (保留)")
        if compressed_analysis:
            print(f"  分析摘要: {compressed_analysis}")
        
        new_len = len(punct_text) + len(compressed_analysis)
        print(f"  压缩比: {orig_len / new_len if new_len else 1:.1f}x")
        print("-" * 60)


def main():
    """主函数"""
    print("\n" + "🔥" * 20)
    print("  语义压缩样本对比")
    print("🔥" * 20)
    
    # 设置随机种子以便复现
    random.seed(42)
    
    # 各模态抽样
    sample_stickers(3)
    sample_images(3)
    sample_videos(2)
    sample_voices(3)
    
    print("\n" + "=" * 80)
    print("  样本对比完成！")
    print("=" * 80)


if __name__ == "__main__":
    main()
