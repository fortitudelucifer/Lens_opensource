# -*- coding: utf-8 -*-
"""
SFT 数据优化器 - Token 级别优化

功能：
- 将 SFT 训练数据进行 token 级别优化
- msg_uid 简化（P1:8911054651869296902 → 1）
- 时间戳智能压缩（同天内 2025-06-07 14:54:03 → 14:54）
- 消息类型简化（中文 → 英文，如 "文本" → "text"）
- 保留所有语义字段（text_raw, sticker_intent, image_summary 等）

重要原则：
- 只压缩 ID 和时间戳，不删除任何语义信息！
- 所有语义字段（text_raw, summary, intent, emotion 等）完整保留
- 目标：减少 token 数，提高训练效率，不损失语义

优化策略：
1. ID 简化（节省 ~25 字符/条）：
   - 原始：msg_uid: "P1:8911054651869296902"
   - 优化：id: 1
   - 映射表：保存 original_uid → simple_id 映射（可选）

2. 时间戳智能压缩（节省 ~11 字符/条）：
   - 首条消息：完整格式 "YYYY-MM-DD HH:MM"（去掉秒）
   - 同一天内：仅保留 "HH:MM"
   - 跨天：恢复完整格式 "YYYY-MM-DD HH:MM"
   - 示例：
     * 2025-06-07 14:54:03 → 2025-06-07 14:54（首条）
     * 2025-06-07 15:30:12 → 15:30（同天）
     * 2025-06-08 09:00:00 → 2025-06-08 09:00（跨天）

3. 消息类型简化（节省 ~3 字符/条）：
   - 中文 → 英文：
     * "文本" → "text"
     * "图片" → "image"
     * "语音" → "voice"
     * "视频" → "video"
     * "表情包" → "sticker"
     * "小程序" → "miniprogram"
     * "链接" → "link"
     * "引用" → "quote"
     * "时间间隔" → "time_gap"

保留的语义字段（完整列表）：
- 文本：text_raw, merged_count
- 引用：text_raw, link_quote_text
- 表情包：sticker_summary, sticker_intent, sticker_ocr_text
- 图片：image_summary, image_intent, image_emotion_atmosphere, image_ocr_text
- 语音：voice_to_text, emotion_tags, emotion_desc
- 视频：video_summary, video_voice_to_text, video_emotion_tags, video_atmosphere, video_intent
- 链接/小程序：link_title, text_raw
- 文件：link_file_summary, text_raw
- 系统消息：text_raw, break_type
- 位置：location_label, location_poiname
- 名片：contact_nickname
- L2 额外字段：day_index, ts_relative

处理流程：
1. 加载配置文件（configs/sft_optimizer.yaml）
2. 读取输入文件（enriched_full_anonymized_l1_sft.jsonl 或 l2_sft.jsonl）
3. 逐条消息优化：
   a. msg_uid → id（生成简单 ID）
   b. time_local → time（智能压缩时间戳）
   c. msg_type → type（简化类型名）
   d. 保留所有其他字段（语义信息）
4. 保存优化结果到输出文件
5. 可选：保存 ID 映射表（original_uid → simple_id）
6. 输出统计信息（token 节省率、各项节省数）

输入：
- L1: timeline_out/enriched_full_anonymized_l1_sft.jsonl
- L2: timeline_out/enriched_full_anonymized_l2_sft.jsonl
- configs/sft_optimizer.yaml: 优化配置

输出：
- L1: timeline_out/agent_sft_l1.jsonl
- L2: timeline_out/agent_sft_l2.jsonl
- ID 映射表（可选）：id_mapping.jsonl

依赖：
- json: JSON 解析
- yaml: 配置解析
- tqdm: 进度条显示
- datetime: 时间戳处理

使用示例：
    # L1 本地训练
    python scripts/compression/sft_optimizer.py \
      --input timeline_out/enriched_full_anonymized_l1_sft.jsonl \
      --output timeline_out/agent_sft_l1.jsonl \
      --level l1
    
    # L2 云端训练
    python scripts/compression/sft_optimizer.py \
      --input timeline_out/enriched_full_anonymized_l2_sft.jsonl \
      --output timeline_out/agent_sft_l2.jsonl \
      --level l2
    
    # 保存 ID 映射表
    python scripts/compression/sft_optimizer.py \
      --input timeline_out/enriched_full_anonymized_l1_sft.jsonl \
      --output timeline_out/agent_sft_l1.jsonl \
      --level l1 \
      --id-mapping timeline_out/id_mapping.jsonl
    
    # Python API
    from scripts.compression.sft_optimizer import SFTOptimizer
    
    config = {
        'use_simple_id': True,
        'compress_time': True,
        'simplify_type': True
    }
    
    optimizer = SFTOptimizer(config, level='l1')
    stats = optimizer.optimize(
        "timeline_out/enriched_full_anonymized_l1_sft.jsonl",
        "timeline_out/agent_sft_l1.jsonl",
        id_mapping_path="timeline_out/id_mapping.jsonl"
    )
    
    print(f"Token 节省率: {stats['savings_rate']}%")
    print(f"ID 节省: {stats['id_savings']} 字符")
    print(f"时间戳节省: {stats['time_savings']} 字符")

配置示例（configs/sft_optimizer.yaml）：
    use_simple_id: true        # 启用 ID 简化
    compress_time: true        # 启用时间戳压缩
    simplify_type: true        # 启用类型简化

统计信息：
- total: 总消息数
- optimized: 成功优化的消息数
- original_tokens: 原始 token 数（字符数估算）
- optimized_tokens: 优化后 token 数
- id_savings: ID 简化节省的字符数
- time_savings: 时间戳压缩节省的字符数
- type_savings: 类型简化节省的字符数
- savings_rate: 总节省率（%）
- errors: 错误数

预期效果：
- 平均节省 ~30-40 字符/条消息
- Token 节省率 ~15-20%
- 不损失任何语义信息
- 提高训练效率，减少训练成本

作者：[Author]
更新于：2026-02-02
"""

import json
import argparse
import unicodedata
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from tqdm import tqdm
import yaml


class SFTOptimizer:
    """SFT 数据优化器
    
    优化策略：
    1. msg_uid 简化：P1:8911054651869296902 → 1（节省 ~25 字符/条）
    2. 时间戳压缩：同天内 2025-06-07 14:54:03 → 14:54（节省 ~11 字符/条）
    3. 消息类型简化：中文 → 英文（节省 ~3 字符/条）
    4. Unicode 乱码清理：移除 U+FFFD 替换字符和无效字符
    
    重要：保留所有语义字段！
    - 文本：text_raw
    - 引用：text_raw, link_quote_text
    - 表情包：sticker_summary, sticker_intent, sticker_ocr_text
    - 图片：image_summary, image_intent, image_emotion_atmosphere
    - 语音：voice_to_text, emotion_tags, emotion_desc
    - 视频：video_summary, video_voice_to_text, video_emotion_tags
    - 链接/小程序：link_title, text_raw
    """
    
    # 需要清理乱码的文本字段列表
    TEXT_FIELDS = [
        'text_raw', 'image_summary', 'image_ocr_text', 'image_intent',
        'image_emotion_atmosphere', 'voice_to_text', 'emotion_desc',
        'video_summary', 'video_voice_to_text', 'video_atmosphere',
        'video_intent', 'sticker_summary', 'sticker_intent', 'sticker_ocr_text',
        'link_title', 'link_quote_text', 'link_file_summary',
        'location_label', 'location_poiname', 'contact_nickname'
    ]
    
    def __init__(self, config: dict, level: str = 'l1'):
        """
        初始化优化器
        
        Args:
            config: 配置字典
            level: 训练级别（l1 或 l2）
        """
        self.use_simple_id = config.get('use_simple_id', True)
        self.compress_time = config.get('compress_time', True)
        self.simplify_type = config.get('simplify_type', True)
        self.level = level
        
        # ID 映射表
        self.id_map = {}  # original_uid -> simple_id
        self.id_counter = 0
        
        # 时间戳压缩状态
        self.last_date = None
        
        # 统计信息
        self.stats = {
            'total': 0,
            'optimized': 0,
            'original_tokens': 0,
            'optimized_tokens': 0,
            'id_savings': 0,
            'time_savings': 0,
            'type_savings': 0,
            'unicode_cleaned': 0,  # 清理乱码的消息数
            'errors': 0
        }
    
    def _clean_unicode(self, text: str) -> str:
        """
        清理文本中的无效 Unicode 字符
        
        处理：
        - 替换字符（U+FFFD，显示为 �）
        - 控制字符（除了换行和制表符）
        - 私用区字符
        - 无效的代理对
        
        Args:
            text: 原始文本
        
        Returns:
            清理后的文本
        """
        if not text:
            return text
        
        original = text
        
        # 移除替换字符（U+FFFD，通常是编码错误导致的 �）
        text = text.replace('\ufffd', '')
        
        # 移除控制字符（保留换行、制表符、回车）
        cleaned_chars = []
        for c in text:
            category = unicodedata.category(c)
            # Cc = 控制字符，Cs = 代理对，Co = 私用区
            if category == 'Cc' and c not in '\n\t\r':
                continue
            if category in ('Cs', 'Co'):
                continue
            cleaned_chars.append(c)
        
        text = ''.join(cleaned_chars)
        
        # 统计清理次数
        if text != original:
            self.stats['unicode_cleaned'] += 1
        
        return text
    
    def _clean_all_text_fields(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        清理结果中所有文本字段的 Unicode 问题
        
        Args:
            result: 消息字典
        
        Returns:
            清理后的消息字典
        """
        for field in self.TEXT_FIELDS:
            if field in result and isinstance(result[field], str):
                cleaned = self._clean_unicode(result[field])
                if cleaned:
                    result[field] = cleaned
                else:
                    # 如果清理后为空，移除该字段
                    del result[field]
        
        return result
    
    def optimize(self, input_path: str, output_path: str, 
                 id_mapping_path: Optional[str] = None) -> Dict[str, Any]:
        """
        优化 SFT 数据
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            id_mapping_path: ID 映射表输出路径（可选）
        
        Returns:
            统计信息
        """
        input_file = Path(input_path)
        output_file = Path(output_path)
        
        if not input_file.exists():
            raise FileNotFoundError(f"输入文件不存在: {input_path}")
        
        # 统计行数
        with open(input_file, 'r', encoding='utf-8') as f:
            total_lines = sum(1 for _ in f)
        
        # 处理文件
        with open(input_file, 'r', encoding='utf-8') as fin, \
             open(output_file, 'w', encoding='utf-8') as fout:
            
            for line in tqdm(fin, total=total_lines, desc="优化 SFT 数据"):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    msg = json.loads(line)
                    optimized = self.optimize_message(msg)
                    
                    if optimized:
                        fout.write(json.dumps(optimized, ensure_ascii=False) + "\n")
                        self.stats['optimized'] += 1
                        
                except json.JSONDecodeError as e:
                    self.stats['errors'] += 1
                    print(f"[WARN] JSON 解析失败: {e}")
                except Exception as e:
                    self.stats['errors'] += 1
                    print(f"[WARN] 处理消息失败: {e}")
        
        # 保存 ID 映射表
        if id_mapping_path and self.id_map:
            self._save_id_mapping(id_mapping_path)
        
        # 计算节省率
        if self.stats['original_tokens'] > 0:
            self.stats['savings_rate'] = round(
                (self.stats['original_tokens'] - self.stats['optimized_tokens']) / 
                self.stats['original_tokens'] * 100, 2
            )
        
        return self.get_stats()
    
    def optimize_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        优化单条消息
        
        优化策略：
        1. msg_uid → id（简化 ID）
        2. time_local → time（压缩时间戳）
        3. msg_type → type（简化类型名）
        4. 保留所有其他字段（语义信息）
        
        Args:
            msg: 原始消息字典
        
        Returns:
            优化后的消息字典
        """
        self.stats['total'] += 1
        
        # 计算原始 token 数（粗略估算）
        original_str = json.dumps(msg, ensure_ascii=False)
        self.stats['original_tokens'] += len(original_str)
        
        result = {}
        
        # 1. ID 简化：msg_uid → id
        if self.use_simple_id and 'msg_uid' in msg:
            simple_id = self._generate_simple_id(msg['msg_uid'])
            result['id'] = simple_id
            self.stats['id_savings'] += len(msg['msg_uid']) - len(str(simple_id))
        elif 'msg_uid' in msg:
            result['msg_uid'] = msg['msg_uid']
        
        # 2. 时间戳压缩：time_local → time
        if self.compress_time and 'time_local' in msg:
            compressed_time = self._compress_timestamp(msg['time_local'])
            result['time'] = compressed_time
            self.stats['time_savings'] += len(msg['time_local']) - len(compressed_time)
        elif 'time_local' in msg:
            result['time_local'] = msg['time_local']
        
        # 3. 保留 speaker
        if 'speaker' in msg:
            result['speaker'] = msg['speaker']
        
        # 4. 消息类型简化：msg_type → type
        if 'msg_type' in msg:
            original_type = msg['msg_type']
            if self.simplify_type:
                simplified_type = self._simplify_msg_type(original_type)
                result['type'] = simplified_type
                self.stats['type_savings'] += len(original_type) - len(simplified_type)
            else:
                result['msg_type'] = original_type
        
        # 5. 保留所有其他语义字段（关键！）
        preserved_fields = {'msg_uid', 'time_local', 'speaker', 'msg_type'}
        for key, value in msg.items():
            if key not in preserved_fields:
                result[key] = value
        
        # 6. 清理 Unicode 乱码（U+FFFD 等）
        result = self._clean_all_text_fields(result)
        
        # 计算优化后 token 数
        optimized_str = json.dumps(result, ensure_ascii=False)
        self.stats['optimized_tokens'] += len(optimized_str)
        
        return result
    
    def _generate_simple_id(self, original_uid: str) -> int:
        """
        生成简单 ID
        
        Args:
            original_uid: 原始 msg_uid（如 P1:8911054651869296902）
        
        Returns:
            简单 ID（1, 2, 3...）
        """
        if original_uid not in self.id_map:
            self.id_counter += 1
            self.id_map[original_uid] = self.id_counter
        
        return self.id_map[original_uid]
    
    def _compress_timestamp(self, time_local: str) -> str:
        """
        智能压缩时间戳
        
        规则：
        - 首条消息：完整格式 "YYYY-MM-DD HH:MM"
        - 同一天内：仅保留 "HH:MM"
        - 跨天：恢复完整格式 "YYYY-MM-DD HH:MM"
        
        Args:
            time_local: 原始时间戳（如 "2025-06-07 14:54:03"）
        
        Returns:
            压缩后的时间戳
        """
        try:
            # 解析时间戳
            dt = datetime.strptime(time_local, '%Y-%m-%d %H:%M:%S')
            current_date = dt.date()
            
            # 首条消息或跨天：完整格式（去掉秒）
            if self.last_date is None or current_date != self.last_date:
                self.last_date = current_date
                return dt.strftime('%Y-%m-%d %H:%M')
            
            # 同一天内：仅保留时分，时间压缩
            return dt.strftime('%H:%M')
            
        except Exception as e:
            print(f"[WARN] 时间戳解析失败: {time_local}, {e}")
            return time_local
    
    def _simplify_msg_type(self, msg_type: str) -> str:
        """
        简化消息类型（中文 → 英文）
        
        Args:
            msg_type: 原始消息类型（如 "文本"、"图片"）
        
        Returns:
            简化后的类型（如 "text"、"image"）
        """
        type_map = {
            '文本': 'text',
            '图片': 'image',
            '语音': 'voice',
            '视频': 'video',
            '表情包': 'sticker',
            '位置': 'location',
            '名片': 'contact',
            '小程序': 'miniprogram',
            '链接': 'link',
            '文件': 'file',
            '引用': 'quote',
            '链接/文件': 'link',  # 默认映射到 link
            '时间间隔': 'time_gap',
            '系统消息': 'system'
        }
        
        return type_map.get(msg_type, msg_type.lower() if msg_type else 'unknown')
    
    def _save_id_mapping(self, output_path: str):
        """保存 ID 映射表"""
        mapping_data = [
            {'id': simple_id, 'original_uid': original_uid}
            for original_uid, simple_id in sorted(self.id_map.items(), key=lambda x: x[1])
        ]
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for item in mapping_data:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')
        
        print(f"[INFO] ID 映射表已保存到: {output_path}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.stats.copy()


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    path = Path(config_path)
    if not path.exists():
        print(f"[WARN] 配置文件不存在: {config_path}，使用默认配置")
        return {}
    
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="SFT 数据优化器")
    parser.add_argument('--input', '-i', required=True, help="输入文件路径")
    parser.add_argument('--output', '-o', required=True, help="输出文件路径")
    parser.add_argument('--level', '-l', choices=['l1', 'l2'], default='l1',
                        help="训练级别（l1=本地训练，l2=云端训练）")
    parser.add_argument('--config', '-c', default='configs/sft_optimizer.yaml',
                        help="配置文件路径")
    parser.add_argument('--id-mapping', help="ID 映射表输出路径（可选）")
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 创建优化器
    optimizer = SFTOptimizer(config, level=args.level)
    
    print(f"=== SFT 数据优化器 ===")
    print(f"输入: {args.input}")
    print(f"输出: {args.output}")
    print(f"级别: {args.level.upper()}")
    print(f"优化策略:")
    print(f"  - ID 简化: {config.get('use_simple_id', True)}")
    print(f"  - 时间戳压缩: {config.get('compress_time', True)}")
    print(f"  - 类型简化: {config.get('simplify_type', True)}")
    print(f"  - 保留所有语义字段: ✓")
    print(f"  - Unicode 乱码清理: ✓")
    print()
    
    # 执行优化
    stats = optimizer.optimize(
        args.input,
        args.output,
        id_mapping_path=args.id_mapping
    )
    
    # 打印统计
    print(f"\n=== 优化完成 ===")
    print(f"处理消息: {stats['optimized']}/{stats['total']}")
    print(f"错误数: {stats['errors']}")
    print(f"\nToken 统计:")
    print(f"  原始: {stats['original_tokens']:,} 字符")
    print(f"  优化后: {stats['optimized_tokens']:,} 字符")
    print(f"  节省: {stats['original_tokens'] - stats['optimized_tokens']:,} 字符 ({stats.get('savings_rate', 0)}%)")
    print(f"\n详细节省:")
    print(f"  ID 简化: {stats['id_savings']:,} 字符")
    print(f"  时间戳压缩: {stats['time_savings']:,} 字符")
    print(f"  类型简化: {stats['type_savings']:,} 字符")
    print(f"  Unicode 乱码清理: {stats['unicode_cleaned']} 条消息")
    print(f"\n输出文件: {args.output}")


if __name__ == '__main__':
    main()
