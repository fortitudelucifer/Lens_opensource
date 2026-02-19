#!/usr/bin/env python3
"""
反匿名化训练数据脚本（Strategy B）

功能：
- 将训练数据中的匿名标记还原为真实信息
- ME/OTHER → 真实姓名（从 anonymization.yaml 读取）
- [PERSON_N] → 真实姓名（从 identity_map.json 读取）
- 第X天 → YYYY-MM-DD 真实日期（基于 DAY1 基准日计算）
- OTHERHER 残留修复
- 地名反向映射（匿名地名 → 真实地名）
- 修复 chunks 的 start_time/end_time 字段
- 支持反匿名化 MoA 分析文件（递归处理嵌套字段）

处理流程：
1. 加载映射表：
   a. identity_map.json: [PERSON_N] → 真实姓名
   b. anonymization.yaml: ME/OTHER 主要姓名 + 地名映射
2. 构建完整反向映射表（长匹配优先）
3. 修复 chunks 的时间字段（从 conversation_text 提取）
4. 对训练数据/分析数据应用反匿名化：
   a. OTHERHER → 真实姓名（双重替换残留）
   b. [PERSON_N] → 真实姓名
   c. 第X天 → YYYY-MM-DD
   d. ME:/OTHER: speaker 标记 → 真实姓名:
   e. 独立出现的 ME/OTHER → 真实姓名
   f. 匿名地名 → 真实地名
5. 输出反匿名化后的数据

三种运行模式：
- 默认模式：反匿名化训练数据
- --deanon-analysis：反匿名化 MoA 分析文件
- --fix-chunks-only：只修复 chunks 时间字段

输入：
- local_secrets/identity_map.json: 实体映射表
- configs/anonymization.yaml: 匿名化配置
- advisor_out/chunks/conversation_chunks.jsonl: 对话片段
- advisor_out/training/advisor_training_neutral.jsonl: 训练数据
- advisor_out/analysis/fused_analysis_neutral_moa.jsonl: MoA 分析数据

输出：
- advisor_out/training/advisor_training_neutral_deanon.jsonl: 反匿名化训练数据
- advisor_out/analysis/fused_analysis_neutral_moa_deanon.jsonl: 反匿名化分析数据

依赖：
- PyYAML: YAML 配置解析
- local_secrets/identity_map.json: 实体映射（敏感文件）

使用示例：
    # 反匿名化 MoA 分析文件（推荐先执行）
    python scripts/advisor/run_all/_05c_deanonymize_training.py --deanon-analysis

    # 反匿名化训练数据
    python scripts/advisor/run_all/_05c_deanonymize_training.py

    # 只统计不写入
    python scripts/advisor/run_all/_05c_deanonymize_training.py --dry-run

    # 只修复 chunks 时间字段
    python scripts/advisor/run_all/_05c_deanonymize_training.py --fix-chunks-only

注意事项：
- identity_map.json 为敏感文件，存放在 local_secrets/ 目录
- DAY1 基准日为 2025-06-07（第1天 = 2025-06-07）
- 地名映射存在双向对（如CITY_A↔CITY_B），按匿名化执行顺序优先匹配
- 反匿名化后的数据用于 Strategy B 全量训练

作者：forcifer
更新于：2026-02-15
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# ── 默认路径 ──────────────────────────────────────────────────
IDENTITY_MAP_PATH = PROJECT_ROOT / "local_secrets" / "identity_map.json"
ANON_CONFIG_PATH = PROJECT_ROOT / "configs" / "anonymization.yaml"
CHUNKS_PATH = PROJECT_ROOT / "advisor_out" / "chunks" / "conversation_chunks.jsonl"
TRAINING_PATH = PROJECT_ROOT / "advisor_out" / "training" / "advisor_training_neutral.jsonl"
OUTPUT_TRAINING_PATH = PROJECT_ROOT / "advisor_out" / "training" / "advisor_training_neutral_deanon.jsonl"
ANALYSIS_PATH = PROJECT_ROOT / "advisor_out" / "analysis" / "fused_analysis_neutral_moa.jsonl"
OUTPUT_ANALYSIS_PATH = PROJECT_ROOT / "advisor_out" / "analysis" / "fused_analysis_neutral_moa_deanon.jsonl"
OUTPUT_CHUNKS_PATH = CHUNKS_PATH  # 原地修复

# 从 conversation_text 提取天数和时间的正则
_TIME_PATTERN = re.compile(r'\[第(\d+)天\s*(\d{4}-\d{2}-\d{2})?\s*(\d{2}:\d{2})\]')

# 第1天 = 2025-06-07 (day_index=0, ts_relative="第1天")
DAY1_DATE = datetime(2025, 6, 7)


def day_to_date(day_num: int) -> str:
    """将第N天转换为 YYYY-MM-DD 格式的真实日期"""
    real_date = DAY1_DATE + timedelta(days=day_num - 1)
    return real_date.strftime('%Y-%m-%d')


def convert_day_references(text: str) -> tuple[str, int]:
    """
    将文本中所有 '第X天' 引用转换为真实日期
    
    处理场景:
    1. 时间标记: [第108天 13:03] → [2025-09-22 13:03]
    2. 分析引用: 第108天到第110天 → 2025-09-22到2025-09-24
    3. 独立引用: 第108天 → 2025-09-22
    
    Returns:
        (converted_text, replacement_count)
    """
    count = 0
    
    # Pattern 0: [第X天 YYYY-MM-DD HH:MM] — day ref + embedded real date
    # Strip 第X天, keep the real date: [第38天 2025-07-14 22:29] → [2025-07-14 22:29]
    def replace_day_with_date(m):
        nonlocal count
        count += 1
        real_date = m.group(2)
        time_str = m.group(3)
        return f'[{real_date} {time_str}]'
    text = re.sub(r'\[第(\d+)天\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\]', replace_day_with_date, text)
    
    # Pattern 1: [第X天 HH:MM] 时间标记 (bracketed, no embedded date)
    def replace_time_marker(m):
        nonlocal count
        count += 1
        day_num = int(m.group(1))
        time_str = m.group(2)
        return f'[{day_to_date(day_num)} {time_str}]'
    text = re.sub(r'\[第(\d+)天\s+(\d{2}:\d{2})\]', replace_time_marker, text)
    
    # Pattern 1b: 第X天HH:MM (no space, no brackets — common in analysis text)
    # e.g. "第109天22:14" → "2025-09-23 22:14"
    def replace_day_time_nospace(m):
        nonlocal count
        count += 1
        day_num = int(m.group(1))
        time_str = m.group(2)
        return f'{day_to_date(day_num)} {time_str}'
    text = re.sub(r'第(\d+)天(\d{2}:\d{2})', replace_day_time_nospace, text)
    
    # Pattern 2: 第X天 (standalone reference in analysis text)
    def replace_day_ref(m):
        nonlocal count
        count += 1
        day_num = int(m.group(1))
        return day_to_date(day_num)
    text = re.sub(r'第(\d+)天', replace_day_ref, text)
    
    return text, count


def load_identity_map(path: Path) -> dict[str, str]:
    """加载 identity_map.json，构建 [PERSON_N] → 真实姓名 的反向映射"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    entity_map = data.get("entity_map", {})
    # entity_map: {"person:杨丽现": "[PERSON_1]", ...}
    # 反向: {"[PERSON_1]": "杨丽现", ...}
    reverse = {}
    for key, placeholder in entity_map.items():
        # key format: "person:杨丽现"
        real_name = key.split(":", 1)[-1] if ":" in key else key
        reverse[placeholder] = real_name
    return reverse


def load_anon_config(path: Path) -> dict:
    """加载 anonymization.yaml"""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def build_reverse_mapping(identity_reverse: dict, anon_config: dict) -> dict[str, str]:
    """
    构建完整的反向映射表
    
    返回: {匿名标记: 真实文本} 的有序映射 (长匹配优先)
    """
    mapping = {}

    # 1. [PERSON_N] → 真实姓名
    mapping.update(identity_reverse)

    # 2. ME → 主要真实姓名 (第一个 me_name)
    me_names = anon_config.get("me_names", [])
    other_names = anon_config.get("other_names", [])
    me_primary = me_names[0] if me_names else "ME"
    other_primary = other_names[0] if other_names else "OTHER"

    # 注意: 不直接替换 "ME"/"OTHER" 因为它们出现在 speaker 标记中
    # 只替换对话文本中的引用，保留 "ME:" 和 "OTHER:" 前缀
    # 这里我们记录主要姓名，实际替换在 apply_deanonymization 中处理
    mapping["__ME_PRIMARY__"] = me_primary
    mapping["__OTHER_PRIMARY__"] = other_primary

    # 3. 地名反向映射 (如有)
    # location_mapping: {真实地名: 匿名后地名}
    # 反向: {匿名后地名: 真实地名}
    # 注意: 双向对如 {CITY_A:CITY_B, CITY_B:CITY_C} 中，CITY_B既是匿名结果又是真实名
    # 数据中出现的"CITY_B"实际是"CITY_A"被匿名后的结果，所以反向应为 {CITY_B:CITY_A}
    # 规则: 第一个注册的 anon→real 优先（匹配实际匿名化执行顺序）
    location_mapping = anon_config.get("location_mapping", {})
    location_reverse = {}
    for real, anon in location_mapping.items():
        if anon not in location_reverse:
            location_reverse[anon] = real
    mapping.update(location_reverse)

    return mapping


def extract_time_range(conversation_text: str) -> tuple[str, str]:
    """
    从 conversation_text 提取时间范围
    
    Returns:
        (start_time, end_time) — 格式: "第N天 HH:MM"
    """
    matches = _TIME_PATTERN.findall(conversation_text)
    if not matches:
        return "", ""

    first = matches[0]  # (day, date_or_empty, time)
    last = matches[-1]

    def fmt(m):
        day, date_str, time_str = m
        if date_str:
            return f"第{day}天 {date_str} {time_str}"
        return f"第{day}天 {time_str}"

    return fmt(first), fmt(last)


def fix_chunk_times(chunks: list[dict]) -> tuple[list[dict], int]:
    """
    修复 chunks 的 start_time/end_time
    
    Returns:
        (fixed_chunks, fix_count)
    """
    fixed = 0
    for chunk in chunks:
        text = chunk.get("conversation_text", "")
        new_start, new_end = extract_time_range(text)
        old_start = chunk.get("start_time", "")
        old_end = chunk.get("end_time", "")

        # 只在新值比旧值更完整时替换 (新值包含天数信息)
        if new_start and (not old_start or "第" not in str(old_start)):
            chunk["start_time"] = new_start
            fixed += 1
        if new_end and (not old_end or "第" not in str(old_end)):
            chunk["end_time"] = new_end
    return chunks, fixed


def apply_deanonymization(text: str, mapping: dict[str, str]) -> str:
    """
    对文本应用完整反匿名化
    
    替换规则:
    0. OTHERHER → 真实姓名 (双重替换残留)
    1. [PERSON_N] → 真实姓名
    2. 第X天 → YYYY-MM-DD 真实日期
    3. "ME:" (speaker标记) → "江泽东:" 
    4. "OTHER:" (speaker标记) → "刘双:"
    5. 分析文本中独立出现的 ME/OTHER → 真实姓名
    6. 地名反向映射
    """
    me_primary = mapping.get("__ME_PRIMARY__", "ME")
    other_primary = mapping.get("__OTHER_PRIMARY__", "OTHER")

    # Step 0: 修复 OTHERHER 残留 (必须在 OTHER 替换之前)
    text = text.replace("OTHERHER", other_primary)

    # Step 1: 替换 [PERSON_N]
    for placeholder, real_name in mapping.items():
        if placeholder.startswith("[PERSON_"):
            text = text.replace(placeholder, real_name)

    # Step 2: 日期转换 — 第X天 → YYYY-MM-DD
    text, _ = convert_day_references(text)

    # Step 3: 替换 speaker 标记中的 ME/OTHER
    # "ME:" → "江泽东:", "OTHER:" → "刘双:"
    text = re.sub(r'\bME:', f'{me_primary}:', text)
    text = re.sub(r'\bOTHER:', f'{other_primary}:', text)

    # Step 4: 替换分析文本中独立出现的 ME/OTHER
    # 使用 word boundary 避免误替换 (如 "SOME" 中的 "ME")
    # 中文语境: ME/OTHER 通常独立出现或前后接中文字符
    text = re.sub(r'(?<![A-Z])ME(?![A-Z_])', me_primary, text)
    text = re.sub(r'(?<![A-Z])OTHER(?![A-Z_])', other_primary, text)

    # Step 5: 地名反向
    for anon_loc, real_loc in mapping.items():
        if anon_loc.startswith("__") or anon_loc.startswith("[PERSON"):
            continue
        if anon_loc in text:
            text = text.replace(anon_loc, real_loc)

    return text


def deanonymize_training_data(
    training_data: list[dict],
    mapping: dict[str, str],
) -> tuple[list[dict], dict]:
    """
    反匿名化训练数据
    
    Returns:
        (deanonymized_data, stats)
    """
    stats = {
        "total": len(training_data),
        "person_replaced": 0,
        "me_replaced": 0,
        "other_replaced": 0,
        "day_replaced": 0,
        "otherher_replaced": 0,
        "location_replaced": 0,
    }

    result = []
    for d in training_data:
        new_d = {"messages": []}
        for m in d["messages"]:
            old_content = m["content"]
            new_content = apply_deanonymization(old_content, mapping)

            # 统计
            if new_content != old_content:
                if "[PERSON_" in old_content:
                    stats["person_replaced"] += 1
                if re.search(r'\bME[:\s]', old_content):
                    stats["me_replaced"] += 1
                if re.search(r'\bOTHER[:\s]', old_content):
                    stats["other_replaced"] += 1
                if re.search(r'第\d+天', old_content):
                    stats["day_replaced"] += 1
                if "OTHERHER" in old_content:
                    stats["otherher_replaced"] += 1

            new_d["messages"].append({
                "role": m["role"],
                "content": new_content,
            })
        result.append(new_d)

    return result, stats


def deanonymize_analysis_data(
    analysis_data: list[dict],
    mapping: dict[str, str],
) -> tuple[list[dict], dict]:
    """
    反匿名化 MoA 分析文件
    
    处理字段:
    - conversation: 对话文本 (含 [第X天 HH:MM] ME: OTHER:)
    - analysis_features: 分析结果 dict (各字段值含 第X天, ME, OTHER)
    - DeepSeek_raw/GLM_raw: 原始分析 (如存在)
    
    Returns:
        (deanonymized_data, stats)
    """
    stats = {
        "total": len(analysis_data),
        "conversation_deanon": 0,
        "analysis_deanon": 0,
        "day_conversions": 0,
        "otherher_fixed": 0,
    }

    result = []
    for d in analysis_data:
        new_d = dict(d)  # shallow copy

        # 1. 反匿名化 conversation
        conv = d.get("conversation", "")
        if conv:
            old_conv = conv
            new_conv = apply_deanonymization(conv, mapping)
            if new_conv != old_conv:
                stats["conversation_deanon"] += 1
                if re.search(r'第\d+天', old_conv):
                    stats["day_conversions"] += 1
                if "OTHERHER" in old_conv:
                    stats["otherher_fixed"] += 1
            new_d["conversation"] = new_conv

        # 2. 反匿名化 analysis_features (递归处理任意嵌套深度)
        af = d.get("analysis_features", {})
        if isinstance(af, dict):
            changed_flag = [False]

            def _deanon_recursive(obj):
                """递归反匿名化任意嵌套的 dict/list/str"""
                if isinstance(obj, str):
                    new_obj = apply_deanonymization(obj, mapping)
                    if new_obj != obj:
                        changed_flag[0] = True
                    return new_obj
                elif isinstance(obj, dict):
                    return {k: _deanon_recursive(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [_deanon_recursive(item) for item in obj]
                else:
                    return obj

            new_af = _deanon_recursive(af)
            if changed_flag[0]:
                stats["analysis_deanon"] += 1
            new_d["analysis_features"] = new_af

        # 3. 反匿名化 DeepSeek_raw / GLM_raw (if present, string fields)
        for raw_key in ("DeepSeek_raw", "GLM_raw"):
            raw_val = d.get(raw_key, "")
            if raw_val and isinstance(raw_val, str):
                new_d[raw_key] = apply_deanonymization(raw_val, mapping)

        result.append(new_d)

    return result, stats


def write_jsonl(data: list[dict], path: Path):
    """写入 JSONL"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description="策略B: 反匿名化训练数据 + 数据修复")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--fix-chunks-only", action="store_true", help="只修复 chunks 不做反匿名化")
    parser.add_argument("--deanon-analysis", action="store_true",
                        help="反匿名化 MoA 分析文件 (fused_analysis_neutral_moa.jsonl)")
    parser.add_argument("--identity-map", type=str, default=str(IDENTITY_MAP_PATH))
    parser.add_argument("--anon-config", type=str, default=str(ANON_CONFIG_PATH))
    parser.add_argument("--chunks", type=str, default=str(CHUNKS_PATH))
    parser.add_argument("--training", type=str, default=str(TRAINING_PATH))
    parser.add_argument("--output", type=str, default=str(OUTPUT_TRAINING_PATH))
    parser.add_argument("--analysis-input", type=str, default=str(ANALYSIS_PATH))
    parser.add_argument("--analysis-output", type=str, default=str(OUTPUT_ANALYSIS_PATH))
    args = parser.parse_args()

    print("=" * 60)
    print("策略B: 完整反匿名化 (姓名+日期+地名+OTHERHER)")
    print("=" * 60)

    # ── 1. 加载映射表 ──────────────────────────────────────────
    print("\n[1] 加载映射表...")
    identity_reverse = load_identity_map(Path(args.identity_map))
    anon_config = load_anon_config(Path(args.anon_config))
    mapping = build_reverse_mapping(identity_reverse, anon_config)

    me_primary = mapping["__ME_PRIMARY__"]
    other_primary = mapping["__OTHER_PRIMARY__"]
    person_count = sum(1 for k in mapping if k.startswith("[PERSON_"))
    loc_count = sum(1 for k in mapping if not k.startswith(('__', '[PERSON')))
    print(f"  ME → {me_primary}")
    print(f"  OTHER → {other_primary}")
    print(f"  [PERSON_N] 映射: {person_count} 个")
    print(f"  地名映射: {loc_count} 个")
    print(f"  DAY1 基准日: {DAY1_DATE.strftime('%Y-%m-%d')} (第1天)")

    # ── 模式: 反匿名化 MoA 分析 ─────────────────────────────
    if args.deanon_analysis:
        print("\n" + "=" * 60)
        print("模式: 反匿名化 MoA 分析文件")
        print("=" * 60)

        print(f"\n[2] 加载分析文件: {args.analysis_input}")
        with open(args.analysis_input, 'r', encoding='utf-8') as f:
            analysis_data = [json.loads(l) for l in f if l.strip()]
        print(f"  加载: {len(analysis_data)} 条")

        print("\n[3] 反匿名化分析数据...")
        deanon_analysis, astats = deanonymize_analysis_data(analysis_data, mapping)
        print(f"  conversation 反匿名化: {astats['conversation_deanon']}/{astats['total']}")
        print(f"  analysis_features 反匿名化: {astats['analysis_deanon']}/{astats['total']}")
        print(f"  日期转换: {astats['day_conversions']} 条含第X天")
        print(f"  OTHERHER 修复: {astats['otherher_fixed']} 条")

        if args.dry_run:
            print("\n  [DRY RUN] 不写入文件")
            # 展示样本
            if deanon_analysis:
                orig = analysis_data[0]
                deanon = deanon_analysis[0]
                print("\n  === 样本对比 (第1条 conversation) ===")
                print(f"  原: {str(orig.get('conversation',''))[:200]}...")
                print(f"  新: {str(deanon.get('conversation',''))[:200]}...")
                print("\n  === 样本对比 (第1条 analysis_features.emotional_balance) ===")
                orig_af = orig.get('analysis_features', {})
                new_af = deanon.get('analysis_features', {})
                print(f"  原: {str(orig_af.get('emotional_balance',''))[:200]}...")
                print(f"  新: {str(new_af.get('emotional_balance',''))[:200]}...")
        else:
            output_path = Path(args.analysis_output)
            write_jsonl(deanon_analysis, output_path)
            print(f"\n  ✅ 已保存: {output_path}")
            print(f"  文件大小: {output_path.stat().st_size / 1024:.1f} KB")

        print("\n" + "=" * 60)
        print("完成! 下一步:")
        print("  1. python _05_format_training_data.py --source moa --input <deanon分析文件>")
        print("  2. python _05c_deanonymize_training.py  (反匿名化训练数据)")
        print("=" * 60)
        return

    # ── 模式: 修复 chunks ──────────────────────────────────────
    print("\n[2] 修复 chunks start_time/end_time...")
    with open(args.chunks, 'r', encoding='utf-8') as f:
        chunks = [json.loads(l) for l in f if l.strip()]

    chunks, fix_count = fix_chunk_times(chunks)
    print(f"  修复了 {fix_count}/{len(chunks)} 个 chunks 的时间字段")

    # 验证
    empty_start = sum(1 for c in chunks if not c.get("start_time"))
    empty_end = sum(1 for c in chunks if not c.get("end_time"))
    print(f"  修复后: 空 start_time={empty_start}, 空 end_time={empty_end}")

    if not args.dry_run:
        write_jsonl(chunks, Path(args.chunks))
        print(f"  ✅ 已更新: {args.chunks}")

    if args.fix_chunks_only:
        print("\n只修复 chunks 模式，跳过反匿名化")
        return

    # ── 模式: 反匿名化训练数据 ────────────────────────────────
    print("\n[3] 反匿名化训练数据...")
    with open(args.training, 'r', encoding='utf-8') as f:
        training_data = [json.loads(l) for l in f if l.strip()]

    deanon_data, stats = deanonymize_training_data(training_data, mapping)
    print(f"  总样本: {stats['total']}")
    print(f"  ME→{me_primary} 替换: {stats['me_replaced']} 样本")
    print(f"  OTHER→{other_primary} 替换: {stats['other_replaced']} 样本")
    print(f"  [PERSON_N] 替换: {stats['person_replaced']} 样本")
    print(f"  第X天→日期 替换: {stats['day_replaced']} 样本")
    print(f"  OTHERHER 修复: {stats['otherher_replaced']} 样本")

    # ── 保存 ────────────────────────────────────────────────
    print("\n[4] 保存反匿名化训练数据...")
    if args.dry_run:
        print("  [DRY RUN] 不写入文件")
        # 展示样本
        print("\n  === 样本对比 (第1条) ===")
        orig = training_data[0]["messages"]
        deanon = deanon_data[0]["messages"]
        for o, d in zip(orig, deanon):
            print(f"  [{o['role']}] 原: {o['content'][:100]}...")
            print(f"  [{d['role']}] 新: {d['content'][:100]}...")
    else:
        output_path = Path(args.output)
        write_jsonl(deanon_data, output_path)
        print(f"  ✅ 已保存: {output_path}")
        print(f"  文件大小: {output_path.stat().st_size / 1024:.1f} KB")

    print("\n" + "=" * 60)
    print("完成! 下一步: 运行 _05b_filter_split_training.py 重新过滤+划分")
    print("=" * 60)


if __name__ == "__main__":
    main()
