#!/usr/bin/env python3
"""
训练数据过滤与划分脚本（Strategy A）

功能：
- 过滤不完整的训练样本（按【】字段数量阈值）
- 修正 OTHERHER → OTHER 残留 bug
- 按关系状态分层采样划分 train/val/test（80/10/10）
- 输出划分后的数据集和元信息

处理流程：
1. 加载训练数据（advisor_training_neutral.jsonl）
2. 过滤不完整样本：
   a. 统计 assistant 消息中的【】字段数量
   b. 低于阈值（默认 13 个）的样本被过滤
3. 修正 OTHERHER 残留（双重替换 bug）
4. 按关系状态分层采样划分：
   a. 提取每个样本的关系状态（健康期/甜蜜期/冲突期等）
   b. 在每个状态组内随机划分 80/10/10
   c. 保证每个状态在 train/val/test 中都有代表
5. 输出 train.jsonl / val.jsonl / test.jsonl + split_meta.json

输入：
- advisor_out/training/advisor_training_neutral.jsonl: 格式化后的训练数据

输出：
- advisor_out/training/splits/train.jsonl: 训练集（80%）
- advisor_out/training/splits/val.jsonl: 验证集（10%）
- advisor_out/training/splits/test.jsonl: 测试集（10%）
- advisor_out/training/splits/split_meta.json: 划分元信息（统计数据）

依赖：
- 无外部依赖，仅使用标准库

使用示例：
    # 默认过滤+划分
    python scripts/advisor/run_all/_05b_filter_split_training.py

    # 放宽过滤阈值
    python scripts/advisor/run_all/_05b_filter_split_training.py --min-fields 11

    # 只统计不写入
    python scripts/advisor/run_all/_05b_filter_split_training.py --dry-run

性能参考：
- 处理速度：< 1 秒（500 条数据）

注意事项：
- 完整的 neutral 分析应有 13 个【】字段
- OTHERHER 是匿名化过程中的已知 bug，此脚本自动修复
- 分层采样保证各关系状态在划分中均匀分布
- 随机种子默认 42，可通过 --seed 修改以获得不同划分

作者：forcifer
更新于：2026-02-15
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_INPUT = PROJECT_ROOT / "advisor_out" / "training" / "advisor_training_neutral.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "advisor_out" / "training" / "splits"

# 完整 neutral 分析应有 13 个【】字段
MIN_FIELDS_DEFAULT = 13


def count_bracket_fields(text: str) -> int:
    """统计【】字段数量"""
    return len(re.findall(r"【.+?】", text))


def fix_otherher(text: str) -> tuple[str, int]:
    """修正 OTHERHER → OTHER，返回 (修正后文本, 修正次数)"""
    count = text.count("OTHERHER")
    if count > 0:
        text = text.replace("OTHERHER", "OTHER")
    return text, count


def extract_relationship_status(text: str) -> str:
    """提取关系状态用于分层采样"""
    m = re.search(r"【关系状态】(\S+)", text)
    return m.group(1) if m else "未知"


def stratified_split(
    data: list[dict],
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 42,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    按关系状态分层采样划分 train/val/test
    """
    assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6

    rng = random.Random(seed)

    # 按关系状态分组
    groups: dict[str, list[dict]] = {}
    for d in data:
        asst = [m for m in d["messages"] if m["role"] == "assistant"]
        status = extract_relationship_status(asst[0]["content"]) if asst else "未知"
        groups.setdefault(status, []).append(d)

    train, val, test = [], [], []

    for status, items in groups.items():
        rng.shuffle(items)
        n = len(items)
        n_val = max(1, round(n * val_ratio))
        n_test = max(1, round(n * test_ratio))
        n_train = n - n_val - n_test

        # 如果组太小，至少保证 train 有样本
        if n_train < 1:
            n_train = max(1, n - 2)
            n_val = min(n_val, n - n_train)
            n_test = n - n_train - n_val

        train.extend(items[:n_train])
        val.extend(items[n_train : n_train + n_val])
        test.extend(items[n_train + n_val :])

    # 最终 shuffle
    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)

    return train, val, test


def write_jsonl(data: list[dict], path: Path):
    """写入 JSONL"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="过滤 + 划分训练数据 (Strategy A)")
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT))
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-fields", type=int, default=MIN_FIELDS_DEFAULT,
                        help=f"最少【】字段数 (默认 {MIN_FIELDS_DEFAULT})")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()

    # 加载
    with open(args.input, encoding="utf-8") as f:
        data = [json.loads(l) for l in f if l.strip()]
    print(f"加载: {len(data)} 条")

    # ── 1. 过滤不完整样本 ──────────────────────────────────────
    kept, dropped = [], []
    for d in data:
        asst = [m for m in d["messages"] if m["role"] == "assistant"]
        if not asst:
            dropped.append((d, 0, "no_assistant"))
            continue
        fc = count_bracket_fields(asst[0]["content"])
        if fc < args.min_fields:
            dropped.append((d, fc, f"fields={fc}"))
        else:
            kept.append(d)

    print(f"过滤: {len(dropped)} 条 (< {args.min_fields} 字段)")
    print(f"保留: {len(kept)} 条")

    # 过滤详情
    drop_reasons: dict[str, int] = {}
    for _, _, reason in dropped:
        drop_reasons[reason] = drop_reasons.get(reason, 0) + 1
    for reason, cnt in sorted(drop_reasons.items()):
        print(f"  {reason}: {cnt}")

    # ── 2. 修正 OTHERHER ──────────────────────────────────────
    total_fixes = 0
    fixed_samples = 0
    for d in kept:
        fixed_any = False
        for m in d["messages"]:
            new_content, n = fix_otherher(m["content"])
            if n > 0:
                m["content"] = new_content
                total_fixes += n
                fixed_any = True
        if fixed_any:
            fixed_samples += 1

    print(f"OTHERHER 修正: {fixed_samples} 条样本, {total_fixes} 处替换")

    # ── 3. 分层采样划分 ──────────────────────────────────────
    train, val, test = stratified_split(kept, seed=args.seed)

    # 统计关系状态分布
    def status_dist(subset):
        dist: dict[str, int] = {}
        for d in subset:
            asst = [m for m in d["messages"] if m["role"] == "assistant"]
            s = extract_relationship_status(asst[0]["content"]) if asst else "未知"
            dist[s] = dist.get(s, 0) + 1
        return dist

    print(f"\n划分结果:")
    print(f"  Train: {len(train)}")
    print(f"  Val:   {len(val)}")
    print(f"  Test:  {len(test)}")

    print(f"\n关系状态分布:")
    all_statuses = set()
    for subset in [train, val, test]:
        all_statuses.update(status_dist(subset).keys())

    print(f"  {'状态':<8} {'Train':>6} {'Val':>6} {'Test':>6} {'Total':>6}")
    train_d, val_d, test_d = status_dist(train), status_dist(val), status_dist(test)
    for s in sorted(all_statuses):
        t, v, te = train_d.get(s, 0), val_d.get(s, 0), test_d.get(s, 0)
        print(f"  {s:<8} {t:>6} {v:>6} {te:>6} {t+v+te:>6}")

    # ── 4. 写入 ──────────────────────────────────────────────
    if args.dry_run:
        print("\n[DRY RUN] 不写入文件")
        return

    out_dir = Path(args.output_dir)
    write_jsonl(train, out_dir / "train.jsonl")
    write_jsonl(val, out_dir / "val.jsonl")
    write_jsonl(test, out_dir / "test.jsonl")

    # 写入 meta 信息
    meta = {
        "source": str(args.input),
        "min_fields": args.min_fields,
        "seed": args.seed,
        "total_loaded": len(data),
        "total_dropped": len(dropped),
        "total_kept": len(kept),
        "otherher_fixed_samples": fixed_samples,
        "otherher_fixed_count": total_fixes,
        "train_size": len(train),
        "val_size": len(val),
        "test_size": len(test),
        "status_distribution": {
            "train": train_d,
            "val": val_d,
            "test": test_d,
        },
    }
    with open(out_dir / "split_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n写入完成:")
    print(f"  {out_dir / 'train.jsonl'}")
    print(f"  {out_dir / 'val.jsonl'}")
    print(f"  {out_dir / 'test.jsonl'}")
    print(f"  {out_dir / 'split_meta.json'}")


if __name__ == "__main__":
    main()
