#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
两阶段 PII 检测 CLI

用法:
    # Phase 1: 扫描并生成确认人名列表
    python scripts/compression/two_stage_pii.py scan timeline_out/agent_sft_l1.jsonl
    
    # 人工审核待确认的候选词
    python scripts/compression/two_stage_pii.py review
    
    # 查看统计信息
    python scripts/compression/two_stage_pii.py stats
    
    # 测试匿名化效果
    python scripts/compression/two_stage_pii.py test "张三和李四约好明天见面"
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.compression.two_stage_pii.scanner import TwoStagePIIScanner


def cmd_scan(args):
    """执行 Phase 1 扫描"""
    scanner = TwoStagePIIScanner(
        confirmed_names_path=args.output,
        model_path=args.model,
    )
    
    candidates, result = scanner.run_phase1(
        input_path=args.input,
        output_path=args.output,
        batch_size=args.batch_size,
        show_progress=not args.quiet,
    )
    
    # 打印摘要
    print("\n" + "=" * 50)
    print("扫描摘要")
    print("=" * 50)
    print(f"输入文件: {args.input}")
    print(f"扫描消息数: {candidates.total_texts_scanned}")
    print(f"候选词总数: {len(candidates.candidates)}")
    print(f"真实人名: {len(result.real_names)}")
    print(f"待审核: {len(result.uncertain)}")
    print(f"输出文件: {args.output}")
    
    if result.uncertain:
        print(f"\n提示: 有 {len(result.uncertain)} 个候选词需要人工审核")
        print(f"运行 'python {__file__} review' 进行审核")


def cmd_review(args):
    """人工审核"""
    scanner = TwoStagePIIScanner(
        confirmed_names_path=args.config,
    )
    scanner.run_review(args.config)


def cmd_stats(args):
    """查看统计信息"""
    scanner = TwoStagePIIScanner(
        confirmed_names_path=args.config,
    )
    
    stats = scanner.get_statistics()
    
    if stats.get("status") == "not_initialized":
        print("尚未运行 Phase 1 扫描")
        print(f"运行 'python {__file__} scan <input_file>' 开始扫描")
        return
    
    print("=" * 50)
    print("两阶段 PII 统计信息")
    print("=" * 50)
    print(f"源文件: {stats.get('source_file', 'N/A')}")
    print(f"生成时间: {stats.get('generated_at', 'N/A')}")
    print(f"总人名数: {stats.get('total_names', 0)}")
    print("\n按类别统计:")
    for cat, count in stats.get("by_category", {}).items():
        print(f"  - {cat}: {count}")


def cmd_test(args):
    """测试匿名化效果"""
    scanner = TwoStagePIIScanner(
        confirmed_names_path=args.config,
    )
    
    text = args.text
    
    # 检测
    matches = scanner.detect(text)
    
    print("=" * 50)
    print("检测结果")
    print("=" * 50)
    print(f"原文: {text}")
    print(f"检测到 {len(matches)} 个人名:")
    for m in matches:
        print(f"  - '{m.value}' (位置: {m.start}-{m.end})")
    
    # 匿名化
    anonymized = scanner.anonymize(text)
    print(f"\n匿名化后: {anonymized}")


def cmd_export(args):
    """导出确认人名列表"""
    from scripts.compression.two_stage_pii.models import ConfirmedNames
    
    confirmed = ConfirmedNames.load(args.config)
    
    # 只导出真实人名
    real_names = [n for n in confirmed.names if n.category == "real_name"]
    
    if args.format == "txt":
        with open(args.output, 'w', encoding='utf-8') as f:
            for name in real_names:
                f.write(f"{name.text}\n")
    elif args.format == "json":
        import json
        data = [{"text": n.text, "frequency": n.frequency} for n in real_names]
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"导出 {len(real_names)} 个人名到: {args.output}")


def main():
    parser = argparse.ArgumentParser(
        description="两阶段 PII 检测工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # scan 命令
    scan_parser = subparsers.add_parser("scan", help="Phase 1: 扫描并生成确认人名列表")
    scan_parser.add_argument("input", help="输入文件路径 (JSONL)")
    scan_parser.add_argument(
        "-o", "--output",
        default="configs/confirmed_names.yaml",
        help="输出文件路径 (默认: configs/confirmed_names.yaml)",
    )
    scan_parser.add_argument(
        "-m", "--model",
        default="/data/models/Qwen2.5-7B-Instruct-AWQ",
        help="LLM 模型路径",
    )
    scan_parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=50,
        help="LLM 批处理大小 (默认: 50)",
    )
    scan_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="静默模式（不显示进度条）",
    )
    scan_parser.set_defaults(func=cmd_scan)
    
    # review 命令
    review_parser = subparsers.add_parser("review", help="人工审核待确认的候选词")
    review_parser.add_argument(
        "-c", "--config",
        default="configs/confirmed_names.yaml",
        help="确认人名列表路径",
    )
    review_parser.set_defaults(func=cmd_review)
    
    # stats 命令
    stats_parser = subparsers.add_parser("stats", help="查看统计信息")
    stats_parser.add_argument(
        "-c", "--config",
        default="configs/confirmed_names.yaml",
        help="确认人名列表路径",
    )
    stats_parser.set_defaults(func=cmd_stats)
    
    # test 命令
    test_parser = subparsers.add_parser("test", help="测试匿名化效果")
    test_parser.add_argument("text", help="要测试的文本")
    test_parser.add_argument(
        "-c", "--config",
        default="configs/confirmed_names.yaml",
        help="确认人名列表路径",
    )
    test_parser.set_defaults(func=cmd_test)
    
    # export 命令
    export_parser = subparsers.add_parser("export", help="导出确认人名列表")
    export_parser.add_argument(
        "-c", "--config",
        default="configs/confirmed_names.yaml",
        help="确认人名列表路径",
    )
    export_parser.add_argument(
        "-o", "--output",
        default="confirmed_names.txt",
        help="输出文件路径",
    )
    export_parser.add_argument(
        "-f", "--format",
        choices=["txt", "json"],
        default="txt",
        help="输出格式 (默认: txt)",
    )
    export_parser.set_defaults(func=cmd_export)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
