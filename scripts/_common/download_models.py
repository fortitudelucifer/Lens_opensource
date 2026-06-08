#!/usr/bin/env python3
"""
wechatDHA 模型下载器 - 统一下载所有流水线所需模型

支持的模型:
1. MiniCPM-V 4.5 Abliterated int8 - NSFW专家 (~10GB, VRAM ~9GB)
2. Pixtral 12B GGUF Q5_K_M - 文档专家 (~9.5GB)
3. NSFW Triage 分类器 (~350MB)
4. Qwen2.5-VL-7B Abliterated - Gore专家 (~15GB)

适用于 RTX 5070 Ti (16GB VRAM)
默认连接 HuggingFace 官网，支持环境变量中的代理设置

用法:
    python scripts/_common/download_models.py              # 下载全部
    python scripts/_common/download_models.py --nsfw       # 仅NSFW相关
    python scripts/_common/download_models.py --doc        # 仅文档专家
    python scripts/_common/download_models.py --triage     # 仅分类器
    python scripts/_common/download_models.py --gore       # 仅Gore专家
"""

import os
import sys
import argparse
import requests
from pathlib import Path
from tqdm import tqdm

# 检查 huggingface_hub 是否安装
try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("正在安装 huggingface_hub...")
    os.system(f"{sys.executable} -m pip install huggingface_hub -q")
    from huggingface_hub import snapshot_download

# ============================================================
# 配置
# ============================================================
MODELS_DIR = "/data/models"
HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co")

# ============================================================
# MiniCPM-V 4.5 Abliterated int8 文件清单 (手动下载)
# ============================================================
MINICPM_ABLITERATED_FILES = [
    ("model-00001-of-00003.safetensors", 4.95 * 1024**3),
    ("model-00002-of-00003.safetensors", 4.95 * 1024**3),
    ("model-00003-of-00003.safetensors", 118 * 1024**2),
    ("config.json", None),
    ("model.safetensors.index.json", None),
    ("tokenizer.json", None),
    ("tokenizer_config.json", None),
    ("generation_config.json", None),
    ("preprocessor_config.json", None),
    ("special_tokens_map.json", None),
    ("merges.txt", None),
    ("vocab.json", None),
    ("configuration_minicpm.py", None),
    ("modeling_minicpmv.py", None),
    ("modeling_navit_siglip.py", None),
    ("image_processing_minicpmv.py", None),
    ("processing_minicpmv.py", None),
    ("resampler.py", None),
    ("tokenization_minicpmv_fast.py", None),
]

# Pixtral GGUF 文件清单 (手动下载)
PIXTRAL_FILES = [
    ("Pixtral-12B-2409-Q5_K_M.gguf", 8.82 * 1024**3),
    ("mmproj-Pixtral-12B-2409-Q8_0.gguf", 0.6 * 1024**3),
]

# huggingface_hub snapshot 下载的模型
HF_MODELS = {
    "triage": {
        "repo_id": "Falconsai/nsfw_image_detection",
        "local_dir": f"{MODELS_DIR}/nsfw-classifier",
        "description": "NSFW Triage 分类器 (~350MB)"
    },
    "gore": {
        "repo_id": "huihui-ai/Qwen2.5-VL-7B-Instruct-abliterated",
        "local_dir": f"{MODELS_DIR}/qwen2.5-vl-abliterated",
        "description": "Gore/暴力分析专家 (~15GB)"
    }
}


# ============================================================
# 下载函数
# ============================================================
def download_file(url: str, save_path: str, expected_size: int = None) -> bool:
    """下载单个文件，带进度条，支持断点续传"""
    try:
        # 1. 检查是否完全同步
        if os.path.exists(save_path):
            existing_size = os.path.getsize(save_path)
            if expected_size and abs(existing_size - expected_size) < 1024 * 1024:
                print(f"  ✅ 已跳过 (完整): {os.path.basename(save_path)}")
                return True
        
        # 2. 准备请求头 (断点续传)
        headers = {}
        initial_pos = 0
        if os.path.exists(save_path):
            initial_pos = os.path.getsize(save_path)
            headers['Range'] = f'bytes={initial_pos}-'

        response = requests.get(url, headers=headers, stream=True, timeout=60)
        
        # 3. 处理 HTTP 416 (Requested Range Not Satisfiable)
        if response.status_code == 416:
            print(f"  ✅ 检查完成 (已是最新): {os.path.basename(save_path)}")
            return True
            
        if response.status_code not in [200, 206]:
            print(f"  ❌ 下载失败: HTTP {response.status_code} - {url}")
            return False
        
        # 获取总大小
        content_length = response.headers.get('content-length')
        if content_length:
            total_size = int(content_length) + initial_pos
        else:
            total_size = initial_pos
            
        # 4. 执行下载
        mode = 'ab' if initial_pos > 0 and response.status_code == 206 else 'wb'
        actual_pos = initial_pos if mode == 'ab' else 0
        
        filename = os.path.basename(save_path)
        with open(save_path, mode) as f:
            with tqdm(total=total_size, initial=actual_pos, unit='B', 
                      unit_scale=True, unit_divisor=1024,
                      desc=f"  📥 {filename[:30]}", leave=True) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
        
        return True
        
    except Exception as e:
        print(f"  ❌ 下载错误: {e}")
        return False


def download_minicpm_abliterated() -> bool:
    """下载 MiniCPM-V 4.5 Abliterated int8 (NSFW专家主模型)"""
    print("\n" + "="*60)
    print("📦 MiniCPM-V 4.5 Abliterated int8 (NSFW Expert)")
    print("   来源: wavespeed/MiniCPM-V-4_5-abliterated-int8")
    print("="*60)
    
    local_dir = f"{MODELS_DIR}/minicpm-v-4.5-abliterated-int8"
    os.makedirs(local_dir, exist_ok=True)
    
    repo = "wavespeed/MiniCPM-V-4_5-abliterated-int8"
    success = True
    
    for filename, expected_size in MINICPM_ABLITERATED_FILES:
        url = f"{HF_ENDPOINT}/{repo}/resolve/main/{filename}"
        save_path = os.path.join(local_dir, filename)
        if not download_file(url, save_path, expected_size):
            success = False
    
    return success


def download_pixtral() -> bool:
    """下载 Pixtral 12B GGUF Q5_K_M (文档专家)"""
    print("\n" + "="*60)
    print("📦 Pixtral 12B GGUF Q5_K_M (Document Expert)")
    print("   来源: EnlistedGhost/Pixtral-12B-2409-GGUF")
    print("="*60)
    
    local_dir = f"{MODELS_DIR}/pixtral-12b-gguf"
    os.makedirs(local_dir, exist_ok=True)
    
    repo = "EnlistedGhost/Pixtral-12B-2409-GGUF"
    success = True
    
    for filename, expected_size in PIXTRAL_FILES:
        url = f"{HF_ENDPOINT}/{repo}/resolve/main/{filename}"
        save_path = os.path.join(local_dir, filename)
        if not download_file(url, save_path, expected_size):
            success = False
    
    return success


def download_hf_model(key: str) -> bool:
    """使用 huggingface_hub 下载模型"""
    if key not in HF_MODELS:
        print(f"❌ 未知模型: {key}")
        return False
    
    model = HF_MODELS[key]
    repo_id = model["repo_id"]
    local_dir = model["local_dir"]
    description = model["description"]
    
    print(f"\n{'='*60}")
    print(f"📦 {description}")
    print(f"   来源: {repo_id}")
    print('='*60)
    
    if os.path.exists(local_dir) and os.listdir(local_dir):
        print(f"  ✅ 目录已存在且非空，跳过下载")
        return True
    
    os.makedirs(local_dir, exist_ok=True)
    
    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=local_dir,
            resume_download=True,
            local_dir_use_symlinks=False
        )
        print(f"  ✅ 下载完成")
        return True
    except Exception as e:
        print(f"  ❌ 下载失败: {e}")
        return False


# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="wechatDHA 模型下载器")
    parser.add_argument("--nsfw", action="store_true", help="仅下载NSFW相关模型")
    parser.add_argument("--doc", action="store_true", help="仅下载文档专家模型")
    parser.add_argument("--triage", action="store_true", help="仅下载分类器模型")
    parser.add_argument("--gore", action="store_true", help="仅下载Gore专家模型")
    parser.add_argument("--all", action="store_true", help="下载全部模型 (默认)")
    args = parser.parse_args()
    
    # 如果没有指定任何选项，默认下载全部
    download_all = not any([args.nsfw, args.doc, args.triage, args.gore])
    
    print("🚀 wechatDHA 模型下载器")
    print(f"   目标目录: {MODELS_DIR}")
    print(f"   HF终点: {HF_ENDPOINT}")
    
    results = []
    
    # NSFW 相关
    if download_all or args.nsfw:
        results.append(("MiniCPM-V 4.5 Abliterated int8", download_minicpm_abliterated()))
        results.append(("NSFW Triage 分类器", download_hf_model("triage")))
        results.append(("NSFW Ensemble (MiniCPM-V-2.6)", download_hf_model("nsfw_ensemble")))
    
    # 文档专家
    if download_all or args.doc:
        results.append(("Pixtral 12B GGUF", download_pixtral()))
    
    # Gore 专家
    if download_all or args.gore:
        results.append(("Qwen2.5-VL Abliterated (Gore)", download_hf_model("gore")))
    
    # 仅分类器
    if args.triage and not download_all:
        if ("NSFW Triage 分类器", True) not in results and ("NSFW Triage 分类器", False) not in results:
            results.append(("NSFW Triage 分类器", download_hf_model("triage")))
    
    # 汇总
    print("\n" + "="*60)
    print("📊 下载结果汇总")
    print("="*60)
    for name, success in results:
        status = "✅" if success else "❌"
        print(f"  {status} {name}")
    
    # Ollama 提示
    print("\n" + "="*60)
    print("📝 额外配置提示:")
    print("   如需使用 Ollama 版 Pixtral: ollama pull pixtral:12b")
    print("="*60)
    
    all_success = all(s for _, s in results)
    if all_success:
        print("\n🎉 下载完成！")
    else:
        print("\n⚠️ 存在下载失败的文件，请检查网络或代理后重试。")
    
    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
