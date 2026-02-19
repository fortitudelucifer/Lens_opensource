#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
修复撤回消息的 speaker 字段和 text_raw 字段

问题：
1. speaker 问题：
   - "You recalled a message" 应该是 ME 撤回的，但被标记为 OTHER
   - "\"某人\" recalled a message" 应该是 OTHER 撤回的（这个是对的）

2. text_raw 问题（L2 匿名化）：
   - "\"OTHER [日期]\" recalled a message" 被错误匿名化为 "[日期]\" recalled a message"
   - 应该匿名化为 "\"OTHER\" recalled a message"

修复策略：
- 根据 text_raw 内容判断撤回消息的 speaker
- 修复 L2 文件中被错误匿名化的撤回消息
"""

import json
import re
import sys
from pathlib import Path
from tqdm import tqdm

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _common.path_utils import get_messages_path, get_timeline_out


def fix_recall_speaker(text_raw: str, current_speaker: str) -> str:
    """
    根据 text_raw 内容判断撤回消息的正确 speaker
    
    Args:
        text_raw: 消息文本
        current_speaker: 当前的 speaker
    
    Returns:
        修正后的 speaker
    """
    if not text_raw:
        return current_speaker
    
    # "You recalled a message" 或 "你撤回了一条消息" 表示我撤回的
    if 'You recalled' in text_raw or '你撤回' in text_raw:
        return "ME"
    
    # "\"某人\" recalled a message" 或 "\"某人\" 撤回了一条消息" 表示对方撤回的
    if ('recalled a message' in text_raw or '撤回了一条消息' in text_raw) and ('\"' in text_raw or '"' in text_raw):
        return "OTHER"
    
    # 其他情况保持不变
    return current_speaker


def fix_recall_text_raw(text_raw: str, fix_nickname: bool = False) -> str:
    """
    修复被错误匿名化的撤回消息 text_raw
    
    例如：
    - "[日期]\" recalled a message" -> "OTHER recalled a message"
    - "\"OTHER [日期]\" recalled a message" -> "OTHER recalled a message"
    - "\"CONTACT_USERNAME\" recalled a message" -> "OTHER recalled a message" (当 fix_nickname=True)
    
    Args:
        text_raw: 消息文本
        fix_nickname: 是否修复昵称（L1 SFT 需要）
    
    Returns:
        修正后的文本
    """
    if not text_raw:
        return text_raw
    
    # 检测被错误匿名化的模式
    # 模式1: [日期]" recalled a message
    if '[日期]' in text_raw and 'recalled a message' in text_raw.lower():
        return 'OTHER recalled a message'
    
    # 模式2: \"OTHER [日期]\" recalled a message
    if 'OTHER' in text_raw and '[日期]' in text_raw and 'recalled a message' in text_raw.lower():
        return 'OTHER recalled a message'
    
    # 模式3: [日期] 撤回了一条消息
    if '[日期]' in text_raw and '撤回了一条消息' in text_raw:
        return 'OTHER 撤回了一条消息'
    
    # 模式4: 修复昵称（L1 SFT 需要）
    if fix_nickname:
        import re
        # "You recalled" 或 "你撤回" 是我撤回的，保持不变
        if 'You recalled' in text_raw or '你撤回' in text_raw:
            return text_raw
        
        # 英文格式：\"昵称\" recalled a message 或 "昵称" recalled a message
        # 替换为：OTHER recalled a message（不带引号和反斜杠）
        en_pattern = r'\\?"([^"]+)\\?"\s*recalled a message'
        en_match = re.search(en_pattern, text_raw)
        if en_match:
            nickname = en_match.group(1)
            # 如果昵称不是 OTHER，则替换
            if nickname != 'OTHER':
                return 'OTHER recalled a message'
        
        # 中文格式：\"昵称\" 撤回了一条消息
        # 替换为：OTHER 撤回了一条消息（不带引号和反斜杠）
        cn_pattern = r'\\?"([^"]+)\\?"\s*撤回了一条消息'
        cn_match = re.search(cn_pattern, text_raw)
        if cn_match:
            nickname = cn_match.group(1)
            if nickname != 'OTHER':
                return 'OTHER 撤回了一条消息'
    
    return text_raw


def is_recall_message(text_raw: str) -> bool:
    """判断是否是撤回消息"""
    if not text_raw:
        return False
    return ('recalled' in text_raw.lower() or 
            '撤回' in text_raw)


def fix_raw_file(raw_path: Path) -> dict:
    """
    修复 raw 文件中的撤回消息 speaker
    
    Returns:
        统计信息
    """
    print(f"读取文件: {raw_path}")
    with open(raw_path, 'r', encoding='utf-8') as f:
        messages = [json.loads(line) for line in f]
    
    print(f"总消息数: {len(messages)}")
    
    # 修复撤回消息
    fixed_count = 0
    for msg in tqdm(messages, desc="修复撤回消息"):
        if msg.get('type') in [0, 10000]:  # 系统消息
            text_raw = msg.get('text_raw', '')
            if is_recall_message(text_raw):
                old_speaker = msg.get('speaker')
                new_speaker = fix_recall_speaker(text_raw, old_speaker)
                if old_speaker != new_speaker:
                    msg['speaker'] = new_speaker
                    fixed_count += 1
    
    print(f"修复了 {fixed_count} 条撤回消息")
    
    # 写回文件
    print(f"写入文件: {raw_path}")
    with open(raw_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    
    return {
        'total': len(messages),
        'fixed': fixed_count
    }


def fix_timeline_file(timeline_path: Path, fix_text_raw: bool = False, fix_nickname: bool = False) -> dict:
    """
    修复 timeline 文件中的撤回消息 speaker 和 text_raw
    
    Args:
        timeline_path: 文件路径
        fix_text_raw: 是否修复 text_raw（仅 L2 文件需要）
        fix_nickname: 是否修复昵称（L1 SFT 需要）
    
    Returns:
        统计信息
    """
    if not timeline_path.exists():
        print(f"文件不存在，跳过: {timeline_path}")
        return {'total': 0, 'fixed_speaker': 0, 'fixed_text': 0, 'fixed_nickname': 0}
    
    print(f"\n读取文件: {timeline_path}")
    with open(timeline_path, 'r', encoding='utf-8') as f:
        messages = [json.loads(line) for line in f]
    
    print(f"总消息数: {len(messages)}")
    
    # 修复撤回消息
    fixed_speaker_count = 0
    fixed_text_count = 0
    fixed_nickname_count = 0
    
    for msg in tqdm(messages, desc="修复撤回消息"):
        # SFT 文件中没有 modality 字段，使用 msg_type 判断
        is_system = msg.get('msg_type') == '系统消息' or msg.get('modality') == 'system'
        text_raw = msg.get('text_raw', '')
        
        if is_system or is_recall_message(text_raw):
            if is_recall_message(text_raw):
                # 修复 speaker
                old_speaker = msg.get('speaker')
                new_speaker = fix_recall_speaker(text_raw, old_speaker)
                if old_speaker != new_speaker:
                    msg['speaker'] = new_speaker
                    fixed_speaker_count += 1
                
                # 修复 text_raw（L2 文件或 L1 SFT 昵称）
                if fix_text_raw or fix_nickname:
                    new_text = fix_recall_text_raw(text_raw, fix_nickname=fix_nickname)
                    if new_text != text_raw:
                        msg['text_raw'] = new_text
                        if fix_nickname and '[日期]' not in text_raw:
                            fixed_nickname_count += 1
                        else:
                            fixed_text_count += 1
    
    print(f"修复了 {fixed_speaker_count} 条 speaker，{fixed_text_count} 条 text_raw，{fixed_nickname_count} 条昵称")
    
    # 写回文件
    print(f"写入文件: {timeline_path}")
    with open(timeline_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    
    return {
        'total': len(messages),
        'fixed_speaker': fixed_speaker_count,
        'fixed_text': fixed_text_count,
        'fixed_nickname': fixed_nickname_count
    }


def main():
    print("=" * 80)
    print("修复撤回消息的 speaker 和 text_raw 字段")
    print("=" * 80)
    
    # 1. 修复 raw 文件
    print("\n【步骤 1】修复 raw/P1_messages_raw.jsonl")
    print("-" * 80)
    raw_path = get_messages_path()
    raw_stats = fix_raw_file(raw_path)
    
    # 2. 修复 timeline 文件
    timeline_dir = get_timeline_out()
    
    # 不需要修复 text_raw 的文件（原始数据或 L1）
    l1_files = [
        'enriched_full.jsonl',
        'enriched_full_processed.jsonl',
    ]
    
    # 需要修复 text_raw 的文件（L2 匿名化后）
    l2_files = [
        'enriched_full_anonymized_l2.jsonl',
        'enriched_full_anonymized_l2_sft.jsonl',
    ]
    
    # L1 SFT 文件（修复 speaker 和昵称）
    l1_sft_files = [
        'enriched_full_anonymized_l1_sft.jsonl',
    ]
    
    all_stats = {}
    
    # 修复 L1 文件（只修复 speaker）
    for i, filename in enumerate(l1_files, 1):
        print(f"\n【步骤 2.{i}】修复 {filename}")
        print("-" * 80)
        stats = fix_timeline_file(timeline_dir / filename, fix_text_raw=False)
        all_stats[filename] = stats
    
    # 修复 L2 文件（修复 speaker 和 text_raw）
    for i, filename in enumerate(l2_files, len(l1_files) + 1):
        print(f"\n【步骤 2.{i}】修复 {filename}")
        print("-" * 80)
        stats = fix_timeline_file(timeline_dir / filename, fix_text_raw=True)
        all_stats[filename] = stats
    
    # 修复 L1 SFT 文件（修复 speaker 和昵称）
    for i, filename in enumerate(l1_sft_files, len(l1_files) + len(l2_files) + 1):
        print(f"\n【步骤 2.{i}】修复 {filename}")
        print("-" * 80)
        stats = fix_timeline_file(timeline_dir / filename, fix_text_raw=False, fix_nickname=True)
        all_stats[filename] = stats
    
    # 打印总结
    print("\n" + "=" * 80)
    print("修复完成")
    print("=" * 80)
    print(f"\nraw/P1_messages_raw.jsonl:")
    print(f"  总消息数: {raw_stats['total']}")
    print(f"  修复 speaker: {raw_stats['fixed']}")
    
    for filename, stats in all_stats.items():
        if stats['total'] > 0:
            print(f"\n{filename}:")
            print(f"  总消息数: {stats['total']}")
            print(f"  修复 speaker: {stats['fixed_speaker']}")
            if 'fixed_text' in stats and stats['fixed_text'] > 0:
                print(f"  修复 text_raw: {stats['fixed_text']}")
            if 'fixed_nickname' in stats and stats['fixed_nickname'] > 0:
                print(f"  修复昵称: {stats['fixed_nickname']}")
    
    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
