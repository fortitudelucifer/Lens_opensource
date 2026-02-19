# -*- coding: utf-8 -*-
"""
完整匿名化流程（L1 → L2 转换）

说明：
    - L1（本地训练）：不需要匿名化，直接使用原始数据 + SFT 精简
    - L2（云端训练）：需要完整匿名化（名字替换、地名映射、时间偏移）+ SFT 精简
    - 此脚本用于生成 L1 和 L2 两种训练数据

自动化执行以下步骤：
1. PII 扫描（规则检测，可选）
2. L2 匿名化（名字替换、地名映射、时间偏移）
3. SFT 字段精简（L1 和 L2）

用法：
    # 完整流程（PII 扫描 + L2 匿名化 + L1/L2 SFT 精简）
    python scripts/compression/run_full_anonymization.py --full
    
    # 仅 L2 匿名化和精简（使用现有配置）
    python scripts/compression/run_full_anonymization.py --anonymize
    
    # 仅生成 L1 SFT（不匿名化，直接从原始数据精简）
    python scripts/compression/run_full_anonymization.py --l1-only
    
    # 仅 PII 扫描（生成报告，不做匿名化）
    python scripts/compression/run_full_anonymization.py --scan-only --suggest
    
    # 验证匿名化效果
    python scripts/compression/run_full_anonymization.py --verify
"""

import argparse
import subprocess
import sys
import json
from pathlib import Path


def run_command(cmd: list, desc: str) -> bool:
    """运行命令"""
    print(f"\n{'='*60}")
    print(f"[STEP] {desc}")
    print(f"{'='*60}")
    print(f"[CMD] {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode != 0:
        print(f"[ERROR] {desc} 失败")
        return False
    
    return True


def verify_anonymization():
    """验证匿名化效果"""
    print("\n" + "="*60)
    print("[VERIFY] 验证匿名化效果")
    print("="*60)
    
    # 导入模块
    sys.path.insert(0, '.')
    from scripts.compression.privacy_shield import PrivacyShield
    
    shield = PrivacyShield()
    
    # 获取配置中的名字
    me_names = shield.anon_config.get('me_names', [])
    other_names = shield.anon_config.get('other_names', [])
    exclude_patterns = shield.anon_config.get('exclude_patterns', [])
    
    print(f"\n配置中的 ME 名字: {me_names}")
    print(f"配置中的 OTHER 名字: {other_names}")
    print(f"排除列表: {exclude_patterns}")
    
    # 检查匿名化后的文件
    l1_file = 'timeline_out/enriched_full_anonymized_l1.jsonl'
    l2_file = 'timeline_out/enriched_full_anonymized_l2.jsonl'
    
    for output_file, level in [(l1_file, 'L1'), (l2_file, 'L2')]:
        if not Path(output_file).exists():
            print(f"\n[WARN] {level} 文件不存在: {output_file}")
            continue
        
        print(f"\n=== 检查 {level} 匿名化结果 ===")
        
        # 检查是否有名字未被替换
        missed_names = {name: 0 for name in me_names + other_names}
        total_checked = 0
        
        with open(output_file, 'r', encoding='utf-8') as f:
            for line in f:
                msg = json.loads(line)
                total_checked += 1
                
                # 检查所有文本字段
                text_fields = ['text_raw', 'voice_to_text', 'image_summary', 'video_summary',
                              'sticker_summary', 'link_quote_text', 'quote_text',
                              'image_caption', 'image_ocr_text', 'video_voice_to_text',
                              'sticker_caption', 'sticker_ocr_text']
                
                for field in text_fields:
                    text = msg.get(field, '')
                    if not text:
                        continue
                    
                    for name in me_names + other_names:
                        if name in text:
                            # 检查是否在排除上下文中
                            is_excluded = False
                            for exclude in exclude_patterns:
                                if exclude in text:
                                    is_excluded = True
                                    break
                            
                            if not is_excluded:
                                missed_names[name] += 1
        
        print(f"检查了 {total_checked} 条消息")
        
        # 报告遗漏
        has_missed = False
        for name, count in missed_names.items():
            if count > 0:
                has_missed = True
                print(f"[WARN] 名字 '{name}' 出现 {count} 次未被替换")
        
        if not has_missed:
            print(f"[OK] {level} 所有配置的名字都已正确处理")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='完整匿名化流程（L1 → L2 转换）')
    parser.add_argument('--full', action='store_true', 
                        help='完整流程（PII 扫描 + L2 匿名化 + L1/L2 SFT 精简）')
    parser.add_argument('--anonymize', action='store_true',
                        help='仅 L2 匿名化和精简（使用现有配置）')
    parser.add_argument('--l1-only', action='store_true',
                        help='仅生成 L1 SFT（不匿名化，直接从原始数据精简）')
    parser.add_argument('--scan-only', action='store_true',
                        help='仅 PII 扫描（生成报告）')
    parser.add_argument('--verify', action='store_true',
                        help='验证匿名化效果')
    parser.add_argument('--suggest', action='store_true',
                        help='建议需要添加的名字')
    
    args = parser.parse_args()
    
    if not any([args.full, args.anonymize, args.l1_only, args.scan_only, args.verify]):
        print("请指定 --full, --anonymize, --l1-only, --scan-only 或 --verify")
        print("")
        print("说明：")
        print("  --full: 完整流程（PII 扫描 + L2 匿名化 + L1/L2 SFT 精简）")
        print("  --anonymize: 仅 L2 匿名化和精简")
        print("  --l1-only: 仅生成 L1 SFT（不匿名化）")
        print("  --scan-only: 仅 PII 扫描")
        print("  --verify: 验证匿名化效果")
        print("")
        parser.print_help()
        return
    
    python = sys.executable
    
    # 验证模式
    if args.verify:
        verify_anonymization()
        return
    
    # Step 1: PII 扫描
    if args.full or args.scan_only:
        scan_cmd = [
            python, "scripts/compression/pii_detector.py",
            "--scan"
        ]
        
        if args.suggest:
            scan_cmd.append("--suggest")
        
        if not run_command(scan_cmd, "PII 扫描"):
            return
        
        if args.scan_only:
            print("\n[INFO] 扫描完成，请审核 artifacts/detected_pii.yaml")
            print("[INFO] 确认后更新 configs/anonymization.yaml")
            return
    
    # Step 2: L2 匿名化（仅当需要 L2 时）
    if args.full or args.anonymize:
        anon_cmd = [
            python, "scripts/timeline/run_anonymization.py",
            "--level", "l2"  # 只做 L2 匿名化
        ]
        
        if not run_command(anon_cmd, "L2 匿名化"):
            return
    
    # Step 3: SFT 字段精简
    if args.full or args.anonymize:
        # L1: 从原始数据直接精简（不匿名化）
        trim_l1_cmd = [
            python, "scripts/compression/sft_trimmer.py",
            "--l1"
        ]
        if not run_command(trim_l1_cmd, "L1 SFT 字段精简（无匿名化）"):
            return
        
        # L2: 从匿名化后的数据精简
        trim_l2_cmd = [
            python, "scripts/compression/sft_trimmer.py",
            "--l2"
        ]
        if not run_command(trim_l2_cmd, "L2 SFT 字段精简"):
            return
    
    # 仅 L1 模式
    if args.l1_only:
        trim_l1_cmd = [
            python, "scripts/compression/sft_trimmer.py",
            "--l1"
        ]
        if not run_command(trim_l1_cmd, "L1 SFT 字段精简（无匿名化）"):
            return
    
    # Step 4: 验证（仅 full 模式）
    if args.full:
        print("\n" + "="*60)
        print("[STEP] 验证匿名化效果")
        print("="*60)
        # 验证 L2 输出
        l2_file = 'timeline_out/enriched_full_anonymized_l2.jsonl'
        if Path(l2_file).exists():
            verify_cmd = [
                python, "-c",
                f"import json; f=open('{l2_file}'); lines=f.readlines()[:5]; "
                f"[print(json.loads(l).get('text_raw','')[:80]) for l in lines]"
            ]
            subprocess.run(verify_cmd)
    
    print("\n" + "="*60)
    print("[DONE] 处理完成")
    print("="*60)
    print("\n输出文件：")
    print("  - timeline_out/enriched_full_anonymized_l1_sft.jsonl (L1 本地训练，无匿名化)")
    if args.full or args.anonymize:
        print("  - timeline_out/enriched_full_anonymized_l2.jsonl (L2 匿名化完整)")
        print("  - timeline_out/enriched_full_anonymized_l2_sft.jsonl (L2 云端训练)")
    print("")
    print("说明：")
    print("  L1: 本地训练用，保留原始数据，仅字段精简")
    print("  L2: 云端训练用，完整匿名化（名字→ME/OTHER，地名映射，时间偏移）")


if __name__ == '__main__':
    main()
