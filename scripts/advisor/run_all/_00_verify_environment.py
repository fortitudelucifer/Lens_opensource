#!/usr/bin/env python3
"""
关系顾问 Agent 训练环境验证脚本

功能：
- 验证关系顾问 Agent 的训练环境是否正确配置
- 检查 Python 依赖包（PyTorch、Transformers、PEFT、BitsAndBytes 等）
- 检查 CUDA 可用性和 GPU 信息
- 检查基座模型文件完整性（config.json、tokenizer、权重文件）
- 测试模型 4-bit 量化加载和简单推理

处理流程：
1. 检查 Python 依赖：逐一导入 8 个必需包，输出版本号
2. 检查 CUDA：验证 GPU 可用性、CUDA 版本、GPU 型号和显存
3. 检查基座模型：验证模型目录、配置文件、tokenizer、权重文件是否存在
4. 测试模型加载：使用 BitsAndBytes 4-bit NF4 量化加载模型，执行简单推理测试
5. 输出验证结果总结

输入：
- 无外部文件输入
- 依赖系统环境（CUDA、GPU 驱动）
- 依赖模型文件（/data/models/Qwen3-8B-Instruct/）

输出：
- 终端输出：各项检查的详细结果（✓ 通过 / ✗ 失败）
- 退出码：0（全部通过）或 1（部分失败）

依赖：
- torch: GPU 计算和模型加载
- transformers: 模型和 tokenizer 加载
- peft: LoRA 参数高效微调
- bitsandbytes: 4-bit/8-bit 量化支持
- trl: 强化学习训练
- datasets: 数据集加载
- accelerate: 分布式训练加速

使用示例：
    # 完整环境验证
    python scripts/advisor/run_all/_00_verify_environment.py

    # 验证通过后可继续执行后续训练流水线
    # python scripts/advisor/run_all/_01_extract_conversations.py

性能参考：
- 依赖检查：< 1 秒
- CUDA 检查：< 1 秒
- 模型加载测试：约 1-3 分钟（取决于磁盘速度和 GPU）
- 显存占用：约 5-6 GB（4-bit 量化 Qwen3-8B）

注意事项：
- 模型加载测试会占用 GPU 显存，测试完成后会自动清理
- 如果前三项检查未通过，将跳过模型加载测试
- 基座模型路径硬编码为 /data/models/Qwen3-8B-Instruct，如需修改请编辑脚本
- 建议在训练前先运行此脚本确认环境正确

作者：[Author]
更新于：2026-02-15
"""

import gc
import sys
from pathlib import Path


def check_dependencies():
    """
    检查 Python 依赖包是否已安装
    
    逐一导入 8 个必需的 Python 包，输出包名和版本号。
    任何一个包缺失都会导致后续训练流程无法运行。
    
    Returns:
        bool: 所有依赖包都已安装返回 True，否则返回 False
    
    Example:
        >>> ok = check_dependencies()
        >>> if not ok:
        ...     print("请先安装缺失的依赖包")
    """
    print("=" * 60)
    print("1. 检查 Python 依赖")
    print("=" * 60)
    
    required_packages = [
        ('torch', 'PyTorch'),
        ('transformers', 'Transformers'),
        ('peft', 'PEFT (Parameter-Efficient Fine-Tuning)'),
        ('bitsandbytes', 'BitsAndBytes (量化支持)'),
        ('trl', 'TRL (Transformer Reinforcement Learning)'),
        ('datasets', 'Datasets'),
        ('accelerate', 'Accelerate'),
        ('tqdm', 'tqdm (进度条)'),
    ]
    
    all_ok = True
    for package, name in required_packages:
        try:
            module = __import__(package)
            version = getattr(module, '__version__', 'unknown')
            print(f"  ✓ {name}: {version}")
        except ImportError:
            print(f"  ✗ {name}: 未安装")
            all_ok = False
    
    return all_ok


def check_cuda():
    """
    检查 CUDA 可用性和 GPU 信息
    
    验证 PyTorch 是否能检测到 CUDA，输出 CUDA 版本、GPU 数量、
    每个 GPU 的型号和显存大小。
    
    Returns:
        bool: CUDA 可用返回 True，否则返回 False
    
    Example:
        >>> ok = check_cuda()
        >>> # 输出示例：
        >>> # ✓ CUDA 可用
        >>> # - CUDA 版本: 12.4
        >>> # - GPU 0: NVIDIA RTX 5070 Ti (16.0 GB)
    """
    print("\n" + "=" * 60)
    print("2. 检查 CUDA")
    print("=" * 60)
    
    try:
        import torch
        
        if torch.cuda.is_available():
            print(f"  ✓ CUDA 可用")
            print(f"    - CUDA 版本: {torch.version.cuda}")
            print(f"    - GPU 数量: {torch.cuda.device_count()}")
            
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                total_mem = props.total_memory / (1024 ** 3)
                print(f"    - GPU {i}: {props.name} ({total_mem:.1f} GB)")
            
            return True
        else:
            print("  ✗ CUDA 不可用")
            return False
    except Exception as e:
        print(f"  ✗ CUDA 检查失败: {e}")
        return False


def check_base_model():
    """
    检查基座模型文件是否完整
    
    验证 Qwen3-8B-Instruct 模型目录是否存在，以及关键文件
    （config.json、tokenizer.json、tokenizer_config.json、权重文件）
    是否齐全。支持 safetensors 和 bin 两种权重格式。
    
    Returns:
        bool: 模型文件完整返回 True，否则返回 False
    
    Example:
        >>> ok = check_base_model()
        >>> # 输出示例：
        >>> # ✓ 模型目录存在: /data/models/Qwen3-8B-Instruct
        >>> # ✓ config.json
        >>> # ✓ 模型权重: 4 个 safetensors 文件
    """
    print("\n" + "=" * 60)
    print("3. 检查基座模型")
    print("=" * 60)
    
    model_path = Path('/data/models/Qwen3-8B-Instruct')
    
    if model_path.exists():
        print(f"  ✓ 模型目录存在: {model_path}")
        
        # 检查关键文件
        key_files = [
            'config.json',
            'tokenizer.json',
            'tokenizer_config.json',
        ]
        
        # 检查模型权重文件（可能是 safetensors 或 bin）
        safetensors_files = list(model_path.glob('*.safetensors'))
        bin_files = list(model_path.glob('*.bin'))
        
        all_ok = True
        for f in key_files:
            if (model_path / f).exists():
                print(f"    ✓ {f}")
            else:
                print(f"    ✗ {f} 不存在")
                all_ok = False
        
        if safetensors_files:
            print(f"    ✓ 模型权重: {len(safetensors_files)} 个 safetensors 文件")
        elif bin_files:
            print(f"    ✓ 模型权重: {len(bin_files)} 个 bin 文件")
        else:
            print("    ✗ 未找到模型权重文件")
            all_ok = False
        
        return all_ok
    else:
        print(f"  ✗ 模型目录不存在: {model_path}")
        print("    请下载 Qwen2.5-7B-Instruct 模型到 /data/models/")
        return False


def test_model_loading():
    """
    测试模型 4-bit 量化加载和简单推理
    
    使用 BitsAndBytes NF4 量化配置加载 Qwen3-8B-Instruct 模型，
    执行一次简单的文本生成推理，验证模型可以正常工作。
    测试完成后自动清理模型和显存。
    
    量化配置：
    - load_in_4bit: True
    - bnb_4bit_quant_type: nf4
    - bnb_4bit_compute_dtype: bfloat16
    - bnb_4bit_use_double_quant: True
    
    Returns:
        bool: 模型加载和推理成功返回 True，否则返回 False
    
    Example:
        >>> ok = test_model_loading()
        >>> # 输出示例：
        >>> # ✓ 模型加载成功
        >>> # - 参数量: 8.03B
        >>> # - 显存使用: 5.12 GB
    """
    print("\n" + "=" * 60)
    print("4. 测试模型加载（4-bit 量化）")
    print("=" * 60)
    
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        
        model_path = '/data/models/Qwen3-8B-Instruct'
        
        print("  加载 tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            trust_remote_code=True,
        )
        print(f"    ✓ Tokenizer 加载成功，词表大小: {len(tokenizer)}")
        
        print("  配置 4-bit 量化...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type='nf4',
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        
        print("  加载模型（这可能需要几分钟）...")
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=bnb_config,
            device_map='auto',
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
        )
        
        # 获取模型信息
        total_params = sum(p.numel() for p in model.parameters())
        print(f"    ✓ 模型加载成功")
        print(f"    - 参数量: {total_params / 1e9:.2f}B")
        print(f"    - 设备: {next(model.parameters()).device}")
        
        # 测试简单推理
        print("  测试简单推理...")
        test_input = "你好"
        inputs = tokenizer(test_input, return_tensors='pt').to(model.device)
        
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=20,
                do_sample=False,
            )
        
        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        print(f"    ✓ 推理测试成功")
        print(f"    - 输入: {test_input}")
        print(f"    - 输出: {response[:100]}...")
        
        # 显存使用
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / (1024 ** 3)
            reserved = torch.cuda.memory_reserved() / (1024 ** 3)
            print(f"    - 显存使用: {allocated:.2f} GB (已分配) / {reserved:.2f} GB (已预留)")
        
        # 清理
        print("  清理模型...")
        del model
        del tokenizer
        gc.collect()
        torch.cuda.empty_cache()
        print("    ✓ 清理完成")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 模型加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """
    主函数：按顺序执行 4 项环境验证
    
    执行顺序：
    1. 检查 Python 依赖包
    2. 检查 CUDA 可用性
    3. 检查基座模型文件
    4. 测试模型加载（仅当前 3 项全部通过时执行）
    
    Returns:
        int: 退出码，0 表示全部通过，1 表示部分失败
    """
    print("\n" + "=" * 60)
    print("关系顾问 Agent 环境验证")
    print("=" * 60 + "\n")
    
    results = {}
    
    # 1. 检查依赖
    results['dependencies'] = check_dependencies()
    
    # 2. 检查 CUDA
    results['cuda'] = check_cuda()
    
    # 3. 检查基座模型
    results['base_model'] = check_base_model()
    
    # 4. 测试模型加载（仅当前面检查都通过时）
    if all([results['dependencies'], results['cuda'], results['base_model']]):
        results['model_loading'] = test_model_loading()
    else:
        print("\n" + "=" * 60)
        print("4. 测试模型加载（跳过）")
        print("=" * 60)
        print("  ⚠ 由于前面的检查未通过，跳过模型加载测试")
        results['model_loading'] = False
    
    # 总结
    print("\n" + "=" * 60)
    print("验证结果总结")
    print("=" * 60)
    
    all_passed = True
    for check, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {check}: {status}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 所有检查通过！环境配置正确，可以开始训练。")
        return 0
    else:
        print("⚠ 部分检查未通过，请根据上述信息修复问题。")
        return 1


if __name__ == '__main__':
    sys.exit(main())
