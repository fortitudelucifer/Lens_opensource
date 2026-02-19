#!/usr/bin/env python3
"""
run_all_pipelines.py - 一键运行所有模态流水线

功能：
1. 按顺序运行图片、语音、视频、表情包四条流水线
2. 实时显示当前进度和模态状态
3. 错误日志记录到 logs/ 目录
4. 支持从指定模态开始、跳过某些模态

用法：
    python run_all_pipelines.py                    # 运行所有流水线
    python run_all_pipelines.py --start voice      # 从语音开始
    python run_all_pipelines.py --skip image       # 跳过图片
    python run_all_pipelines.py --only sticker     # 只运行表情包
    python run_all_pipelines.py --dry-run          # 仅显示计划，不执行
"""
import subprocess
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent

# 流水线定义：(模态名, 脚本列表)
# 注意：压缩步骤 (_02.5/_03.5/_05.5) 是可选的，通过 --skip-compression 跳过
PIPELINES = {
    "image": [
        ("_01_run_ocr", "scripts/image/run_all/_01_run_ocr.py"),
        ("_02_run_caption", "scripts/image/run_all/_02_run_caption.py"),
        ("_02.5_run_compress", "scripts/image/run_all/_02.5_run_compress.py"),  # 压缩步骤
        ("_03_merge_engine", "scripts/image/run_all/_03_merge_engine.py"),
        ("_04_update_timeline", "scripts/image/run_all/_04_update_timeline.py"),
    ],
    "voice": [
        ("_01_run_funasr", "scripts/voice/run_all/_01_run_funasr.py"),
        ("_02_run_emotion", "scripts/voice/run_all/_02_run_emotion.py"),
        ("_02.5_run_compress", "scripts/voice/run_all/_02.5_run_compress.py"),  # 压缩步骤
        ("_03_merge_engine", "scripts/voice/run_all/_03_merge_engine.py"),
        ("_04_update_timeline", "scripts/voice/run_all/_04_update_timeline.py"),
    ],
    "video": [
        ("_01_run_extract", "scripts/video/run_all/_01_run_extract.py"),
        ("_02_run_transcribe", "scripts/video/run_all/_02_run_transcribe.py"),
        ("_03_run_caption", "scripts/video/run_all/_03_run_caption.py"),
        ("_03.5_run_compress", "scripts/video/run_all/_03.5_run_compress.py"),  # 压缩步骤
        ("_04_merge_engine", "scripts/video/run_all/_04_merge_engine.py"),
        ("_05_update_timeline", "scripts/video/run_all/_05_update_timeline.py"),
    ],
    "sticker": [
        ("_01_run_download", "scripts/sticker/run_all/_01_run_download.py"),
        ("_02_run_sniff", "scripts/sticker/run_all/_02_run_sniff.py"),
        ("_03_run_process", "scripts/sticker/run_all/_03_run_process.py"),
        ("_04_run_triage", "scripts/sticker/run_all/_04_run_triage.py"),
        ("_05_run_caption", "scripts/sticker/run_all/_05_run_caption.py"),
        ("_05.5_run_compress", "scripts/sticker/run_all/_05.5_run_compress.py"),  # 压缩步骤
        ("_06_merge_engine", "scripts/sticker/run_all/_06_merge_engine.py"),
        ("_07_update_timeline", "scripts/sticker/run_all/_07_update_timeline.py"),
        ("_08_cleanup_frames", "scripts/sticker/run_all/_08_cleanup_frames.py"),
    ],
    "linkfile": [
        ("_01_extract_and_anonymize", "scripts/linkfile/run_all/_01_extract_and_anonymize.py"),
        ("_01.5_run_file_summary", "scripts/linkfile/run_all/_01.5_run_file_summary.py"),
        ("_02_merge_engine", "scripts/linkfile/run_all/_02_merge_engine.py"),
        ("_03_update_timeline", "scripts/linkfile/run_all/_03_update_timeline.py"),
    ],
}

# 压缩步骤列表（用于 --skip-compression 和 --compression-only）
COMPRESSION_STEPS = [
    "_02.5_run_compress",
    "_03.5_run_compress",
    "_05.5_run_compress",
]

# 模态执行顺序
MODALITY_ORDER = ["image", "voice", "video", "sticker", "linkfile"]

# 颜色代码
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    """打印标题"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text:^60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")


def print_status(modality: str, step: str, status: str, color: str = Colors.CYAN):
    """打印状态"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"{Colors.BOLD}[{timestamp}]{Colors.ENDC} {color}[{modality.upper()}]{Colors.ENDC} {step}: {status}")


def print_progress(current_modality: int, total_modalities: int, 
                   current_step: int, total_steps: int, modality_name: str):
    """打印进度条"""
    overall = (current_modality - 1) / total_modalities + (current_step / total_steps) / total_modalities
    bar_len = 40
    filled = int(bar_len * overall)
    bar = '█' * filled + '░' * (bar_len - filled)
    print(f"\r{Colors.CYAN}进度: [{bar}] {overall*100:.1f}% - {modality_name} ({current_step}/{total_steps}){Colors.ENDC}", end='', flush=True)


def setup_logging(log_dir: Path) -> Path:
    """设置日志目录，返回本次运行的日志文件路径"""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"pipeline_run_{timestamp}.log"
    return log_file


def run_script(script_path: Path, log_file: Path, modality: str, step_name: str) -> Tuple[bool, str]:
    """
    运行单个脚本（实时显示输出）
    返回 (成功与否, 错误信息)
    """
    if not script_path.exists():
        return False, f"脚本不存在: {script_path}"
    
    try:
        # 使用 conda 环境运行，添加 --no-capture-output 避免 conda 缓冲
        cmd = ["conda", "run", "--no-capture-output", "-n", "CHAT_APP_DHA", "python", "-u", str(script_path)]
        
        # 记录命令到日志
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{datetime.now().isoformat()}] {modality}/{step_name}\n")
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"{'='*60}\n")
        
        # 使用 Popen 实时输出，同时记录到日志
        process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout
            text=True,
            bufsize=1,  # 行缓冲
            env={**os.environ, 'PYTHONUNBUFFERED': '1'}  # 禁用 Python 缓冲
        )
        
        # 实时读取输出
        output_lines = []
        try:
            for line in process.stdout:
                # 实时打印到终端
                print(line, end='', flush=True)
                output_lines.append(line)
        except Exception as e:
            output_lines.append(f"[读取输出错误: {e}]\n")
        
        # 等待进程结束
        return_code = process.wait(timeout=7200)  # 2小时超时
        
        # 记录输出到日志
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"Exit Code: {return_code}\n")
            f.write("OUTPUT:\n")
            f.writelines(output_lines)
        
        if return_code != 0:
            # 提取最后几行作为错误信息
            error_lines = [l for l in output_lines[-20:] if l.strip()]
            error_msg = ''.join(error_lines[-5:]) if error_lines else "未知错误"
            return False, error_msg.strip()
        
        return True, ""
        
    except subprocess.TimeoutExpired:
        process.kill()
        return False, "脚本执行超时 (>2小时)"
    except Exception as e:
        return False, str(e)


def clear_vram():
    """清理显存"""
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except ImportError:
        pass


def run_pipeline(modality: str, steps: List[Tuple[str, str]], log_file: Path,
                 modality_idx: int, total_modalities: int, dry_run: bool = False) -> bool:
    """
    运行单个模态的流水线
    返回是否成功
    """
    print_header(f"🚀 {modality.upper()} 流水线")
    
    total_steps = len(steps)
    
    for step_idx, (step_name, script_rel_path) in enumerate(steps, 1):
        script_path = PROJECT_ROOT / script_rel_path
        
        # 打印进度
        print_progress(modality_idx, total_modalities, step_idx, total_steps, modality)
        print()  # 换行
        
        print_status(modality, step_name, "开始执行...", Colors.YELLOW)
        
        if dry_run:
            print_status(modality, step_name, f"[DRY RUN] 将执行: {script_path}", Colors.BLUE)
            continue
        
        # 执行脚本
        success, error = run_script(script_path, log_file, modality, step_name)
        
        if success:
            print_status(modality, step_name, "✓ 完成", Colors.GREEN)
        else:
            print_status(modality, step_name, f"✗ 失败: {error[:100]}", Colors.RED)
            
            # 记录错误到单独的错误日志
            error_log = PROJECT_ROOT / "logs" / f"error_{modality}_{step_name}.log"
            with open(error_log, "w", encoding="utf-8") as f:
                f.write(f"时间: {datetime.now().isoformat()}\n")
                f.write(f"模态: {modality}\n")
                f.write(f"步骤: {step_name}\n")
                f.write(f"脚本: {script_path}\n")
                f.write(f"错误:\n{error}\n")
            
            print(f"{Colors.RED}错误日志已保存到: {error_log}{Colors.ENDC}")
            return False
    
    print(f"\n{Colors.GREEN}{Colors.BOLD}✓ {modality.upper()} 流水线完成!{Colors.ENDC}")
    
    # 模态完成后清理显存
    if not dry_run:
        print_status(modality, "cleanup", "清理显存...", Colors.CYAN)
        clear_vram()
        print_status(modality, "cleanup", "✓ 显存已清理", Colors.GREEN)
    
    return True


def main():
    parser = argparse.ArgumentParser(description="一键运行所有模态流水线")
    parser.add_argument("--start", type=str, choices=MODALITY_ORDER,
                        help="从指定模态开始运行")
    parser.add_argument("--skip", type=str, nargs="+", choices=MODALITY_ORDER,
                        help="跳过指定模态")
    parser.add_argument("--only", type=str, nargs="+", choices=MODALITY_ORDER,
                        help="只运行指定模态")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅显示计划，不实际执行")
    parser.add_argument("--continue-on-error", action="store_true",
                        help="遇到错误时继续执行下一个模态")
    parser.add_argument("--skip-compression", action="store_true",
                        help="跳过压缩步骤")
    parser.add_argument("--compression-only", action="store_true",
                        help="只运行压缩步骤")
    args = parser.parse_args()
    
    # 确定要运行的模态
    modalities_to_run = MODALITY_ORDER.copy()
    
    if args.only:
        modalities_to_run = [m for m in MODALITY_ORDER if m in args.only]
    elif args.start:
        start_idx = MODALITY_ORDER.index(args.start)
        modalities_to_run = MODALITY_ORDER[start_idx:]
    
    if args.skip:
        modalities_to_run = [m for m in modalities_to_run if m not in args.skip]
    
    if not modalities_to_run:
        print(f"{Colors.RED}没有要运行的模态!{Colors.ENDC}")
        return 1
    
    # 处理压缩相关参数
    if args.skip_compression:
        # 从每个模态的步骤中移除压缩步骤
        for modality in modalities_to_run:
            PIPELINES[modality] = [
                (name, path) for name, path in PIPELINES[modality]
                if name not in COMPRESSION_STEPS
            ]
    elif args.compression_only:
        # 只保留压缩步骤
        for modality in modalities_to_run:
            PIPELINES[modality] = [
                (name, path) for name, path in PIPELINES[modality]
                if name in COMPRESSION_STEPS
            ]
        # 移除没有压缩步骤的模态
        modalities_to_run = [
            m for m in modalities_to_run 
            if PIPELINES[m]
        ]
    
    # 设置日志
    log_dir = PROJECT_ROOT / "logs"
    log_file = setup_logging(log_dir)
    
    # 打印运行计划
    print_header("📋 运行计划")
    print(f"日志文件: {log_file}")
    print(f"模态顺序: {' → '.join(modalities_to_run)}")
    print()
    
    total_steps = sum(len(PIPELINES[m]) for m in modalities_to_run)
    print(f"总步骤数: {total_steps}")
    
    if args.dry_run:
        print(f"\n{Colors.YELLOW}[DRY RUN 模式] 不会实际执行脚本{Colors.ENDC}")
    
    print()
    
    # 记录开始时间
    start_time = datetime.now()
    
    # 运行流水线
    results = {}
    for idx, modality in enumerate(modalities_to_run, 1):
        steps = PIPELINES[modality]
        success = run_pipeline(
            modality, steps, log_file,
            idx, len(modalities_to_run),
            dry_run=args.dry_run
        )
        results[modality] = success
        
        if not success and not args.continue_on_error:
            print(f"\n{Colors.RED}{Colors.BOLD}流水线在 {modality} 模态失败，停止执行{Colors.ENDC}")
            break
    
    # 打印总结
    end_time = datetime.now()
    duration = end_time - start_time
    
    print_header("📊 运行总结")
    print(f"总耗时: {duration}")
    print(f"日志文件: {log_file}")
    print()
    
    for modality, success in results.items():
        status = f"{Colors.GREEN}✓ 成功{Colors.ENDC}" if success else f"{Colors.RED}✗ 失败{Colors.ENDC}"
        print(f"  {modality.upper():10} {status}")
    
    # 检查是否全部成功
    all_success = all(results.values())
    
    if all_success:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 所有流水线执行完成!{Colors.ENDC}")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️ 部分流水线执行失败，请检查日志{Colors.ENDC}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
