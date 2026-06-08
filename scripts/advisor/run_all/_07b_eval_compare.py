#!/usr/bin/env python3
"""
Strategy B 模型评估对比脚本

功能：
- 对比两个 LoRA 模型在测试集上的推理质量
- 评估字段完整性（【】字段数量）、生成长度、ROUGE-L 相似度
- 定性抽样展示对比结果
- 输出评估报告 JSON

对比模型：
- HF seq_len=1664: 标准 HuggingFace 训练的 LoRA 模型
- Unsloth seq_len=4096: Unsloth 加速训练的 LoRA 模型

评估维度：
1. 字段完整性：生成文本包含多少个【】字段（目标 ≥13）
2. 生成长度：平均字符数
3. ROUGE-L F1：与 ground truth 的字符级最长公共子序列相似度
4. 定性抽样：打印前 3 条对比

处理流程：
1. 加载测试集（splits_deanon/test.jsonl）
2. 依次加载两个 LoRA 模型进行推理（每次加载/卸载，节省显存）
3. 计算评估指标
4. 打印对比表和定性抽样
5. 保存完整评估结果 JSON

输入：
- advisor_out/training/splits_deanon/test.jsonl: 测试集
- advisor_out/models/relationship_advisor_neutral_deanon/: HF 模型
- advisor_out/models/relationship_advisor_neutral_deanon_unsloth/: Unsloth 模型

输出：
- advisor_out/comparison/eval_strategyB_compare.json: 评估结果
  * 包含：metrics（两个模型的指标）、samples（所有样本的预测结果）

依赖：
- torch, transformers, peft: 模型加载和推理
- tqdm: 进度条

使用示例：
    # 完整评估
    conda run -n wechatDHA python scripts/advisor/run_all/_07b_eval_compare.py

    # 限制测试样本数（调试用）
    python scripts/advisor/run_all/_07b_eval_compare.py --limit 10

    # 自定义模型路径
    python scripts/advisor/run_all/_07b_eval_compare.py \\
        --model-a path/to/model_a --model-b path/to/model_b

性能参考（RTX 5070 Ti 16GB）：
- 每个模型推理：约 5-10 分钟（50 条测试数据）
- 显存占用：约 8 GB（4-bit 量化，每次只加载一个模型）

注意事项：
- 需要约 8GB 显存，每个模型依次加载/卸载
- 低温度（0.1）保证推理结果可重复
- ROUGE-L 基于字符级 LCS，限制最大 5000 字符避免 OOM

作者：[Author]
更新于：2026-02-15
"""

import argparse
import gc
import json
import os
import re
import sys
from pathlib import Path

os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from tqdm import tqdm


# ── 评估辅助函数 ──────────────────────────────────

FIELD_PATTERN = re.compile(r'【(.+?)】')
EXPECTED_FIELDS = [
    '关系状态', '沟通质量', '情绪平衡', '问题', '建议', '批评',
    '时间模式', '冲突根源', '多模态信号', '修复尝试', '人格动态', '风险等级', '评价',
]


def count_fields(text: str) -> int:
    """统计文本中【】字段数"""
    return len(set(FIELD_PATTERN.findall(text)))


def rouge_l_f1(reference: str, hypothesis: str) -> float:
    """简单 ROUGE-L (基于字符 LCS)"""
    if not reference or not hypothesis:
        return 0.0
    ref = list(reference)
    hyp = list(hypothesis)
    m, n = len(ref), len(hyp)
    # LCS DP (限制长度避免 OOM)
    if m > 5000:
        ref = ref[:5000]
        m = 5000
    if n > 5000:
        hyp = hyp[:5000]
        n = 5000
    dp = [[0] * (n + 1) for _ in range(2)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i % 2][j] = dp[(i - 1) % 2][j - 1] + 1
            else:
                dp[i % 2][j] = max(dp[(i - 1) % 2][j], dp[i % 2][j - 1])
    lcs = dp[m % 2][n]
    if lcs == 0:
        return 0.0
    precision = lcs / n
    recall = lcs / m
    return 2 * precision * recall / (precision + recall)


def load_test_set(path: str) -> list[dict]:
    """加载测试集，返回 [{user_text, reference}]"""
    samples = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            msgs = data.get('messages', [])
            user_text = ''
            reference = ''
            system_prompt = ''
            for msg in msgs:
                if msg['role'] == 'system':
                    system_prompt = msg['content']
                elif msg['role'] == 'user':
                    user_text = msg['content']
                elif msg['role'] == 'assistant':
                    reference = msg['content']
            samples.append({
                'system': system_prompt,
                'user': user_text,
                'reference': reference,
            })
    return samples


def run_inference(
    base_model_path: str,
    lora_path: str,
    samples: list[dict],
    max_new_tokens: int = 1024,
    temperature: float = 0.1,  # 低温度保证可重复性
) -> list[str]:
    """加载模型 + LoRA，在 samples 上推理，返回生成列表"""
    print(f"\n加载基座模型: {base_model_path}")
    print(f"加载 LoRA: {lora_path}")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type='nf4',
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        base_model_path,
        quantization_config=bnb_config,
        device_map='auto',
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )

    tokenizer = AutoTokenizer.from_pretrained(
        base_model_path,
        trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 加载 LoRA
    lora_dir = Path(lora_path)
    if lora_dir.exists() and (lora_dir / 'adapter_config.json').exists():
        model = PeftModel.from_pretrained(model, str(lora_dir))
        print("LoRA 加载完成")
    else:
        print(f"警告：LoRA 不存在 ({lora_path})，使用基座模型")

    model.eval()

    results = []
    for sample in tqdm(samples, desc=f"推理 ({Path(lora_path).name})"):
        messages = [
            {'role': 'system', 'content': sample['system']},
            {'role': 'user', 'content': sample['user']},
        ]
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
        )
        inputs = tokenizer(text, return_tensors='pt').to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=0.9,
                do_sample=True if temperature > 0 else False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        generated = outputs[0][inputs['input_ids'].shape[1]:]
        result = tokenizer.decode(generated, skip_special_tokens=True).strip()
        results.append(result)

    # 卸载
    del model
    del tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    print("模型已卸载")

    return results


def evaluate(samples: list[dict], predictions: list[str], label: str) -> dict:
    """计算评估指标"""
    n = len(samples)
    field_counts = []
    rouge_scores = []
    gen_lengths = []

    for sample, pred in zip(samples, predictions):
        fc = count_fields(pred)
        field_counts.append(fc)
        rl = rouge_l_f1(sample['reference'], pred)
        rouge_scores.append(rl)
        gen_lengths.append(len(pred))

    metrics = {
        'label': label,
        'n': n,
        'avg_fields': sum(field_counts) / n,
        'fields_ge13': sum(1 for c in field_counts if c >= 13) / n * 100,
        'avg_rouge_l': sum(rouge_scores) / n,
        'avg_gen_len': sum(gen_lengths) / n,
        'min_gen_len': min(gen_lengths),
        'max_gen_len': max(gen_lengths),
    }
    return metrics


def print_comparison(metrics_a: dict, metrics_b: dict):
    """打印对比表"""
    print("\n" + "=" * 70)
    print("模型评估对比")
    print("=" * 70)
    fmt = "{:<25} {:>20} {:>20}"
    print(fmt.format("指标", metrics_a['label'], metrics_b['label']))
    print("-" * 70)
    print(fmt.format("样本数", str(metrics_a['n']), str(metrics_b['n'])))
    print(fmt.format("平均【】字段数", f"{metrics_a['avg_fields']:.1f}", f"{metrics_b['avg_fields']:.1f}"))
    print(fmt.format("≥13 字段占比", f"{metrics_a['fields_ge13']:.1f}%", f"{metrics_b['fields_ge13']:.1f}%"))
    print(fmt.format("平均 ROUGE-L", f"{metrics_a['avg_rouge_l']:.4f}", f"{metrics_b['avg_rouge_l']:.4f}"))
    print(fmt.format("平均生成长度(字符)", f"{metrics_a['avg_gen_len']:.0f}", f"{metrics_b['avg_gen_len']:.0f}"))
    print(fmt.format("最短/最长", f"{metrics_a['min_gen_len']}/{metrics_a['max_gen_len']}", f"{metrics_b['min_gen_len']}/{metrics_b['max_gen_len']}"))
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='策略B 模型评估对比')
    parser.add_argument('--test-data', type=str,
                        default=str(PROJECT_ROOT / 'advisor_out/training/splits_deanon/test.jsonl'),
                        help='测试集路径')
    parser.add_argument('--base-model', type=str, default='/data/models/Qwen3-8B-Instruct')
    parser.add_argument('--model-a', type=str,
                        default=str(PROJECT_ROOT / 'advisor_out/models/relationship_advisor_neutral_deanon'),
                        help='模型A: HF seq_len=1664')
    parser.add_argument('--model-b', type=str,
                        default=str(PROJECT_ROOT / 'advisor_out/models/relationship_advisor_neutral_deanon_unsloth'),
                        help='模型B: Unsloth seq_len=4096')
    parser.add_argument('--max-new-tokens', type=int, default=1024)
    parser.add_argument('--temperature', type=float, default=0.1)
    parser.add_argument('--output', type=str,
                        default=str(PROJECT_ROOT / 'advisor_out/comparison/eval_strategyB_compare.json'))
    parser.add_argument('--limit', type=int, default=None, help='限制测试样本数（调试用）')

    args = parser.parse_args()

    # 加载测试集
    samples = load_test_set(args.test_data)
    if args.limit:
        samples = samples[:args.limit]
    print(f"测试集: {len(samples)} 条样本")

    # 模型 A 推理
    preds_a = run_inference(args.base_model, args.model_a, samples,
                            max_new_tokens=args.max_new_tokens, temperature=args.temperature)

    # 模型 B 推理
    preds_b = run_inference(args.base_model, args.model_b, samples,
                            max_new_tokens=args.max_new_tokens, temperature=args.temperature)

    # 评估
    metrics_a = evaluate(samples, preds_a, 'HF-1664')
    metrics_b = evaluate(samples, preds_b, 'Unsloth-4096')

    print_comparison(metrics_a, metrics_b)

    # 定性抽样
    print("\n" + "=" * 70)
    print("定性抽样 (前3条)")
    print("=" * 70)
    for i in range(min(3, len(samples))):
        print(f"\n--- 样本 {i+1} ---")
        print(f"用户输入: {samples[i]['user'][:200]}...")
        print(f"\n[Ground Truth] ({count_fields(samples[i]['reference'])} fields, {len(samples[i]['reference'])} chars)")
        print(samples[i]['reference'][:500] + "...")
        print(f"\n[HF-1664] ({count_fields(preds_a[i])} fields, {len(preds_a[i])} chars)")
        print(preds_a[i][:500] + "...")
        print(f"\n[Unsloth-4096] ({count_fields(preds_b[i])} fields, {len(preds_b[i])} chars)")
        print(preds_b[i][:500] + "...")

    # 保存结果
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        'metrics': {'HF-1664': metrics_a, 'Unsloth-4096': metrics_b},
        'samples': [
            {
                'user': s['user'][:500],
                'reference': s['reference'],
                'pred_hf1664': preds_a[i],
                'pred_unsloth4096': preds_b[i],
            }
            for i, s in enumerate(samples)
        ]
    }
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {output_path}")


if __name__ == '__main__':
    main()
