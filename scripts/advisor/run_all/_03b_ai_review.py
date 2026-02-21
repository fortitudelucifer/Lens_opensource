#!/usr/bin/env python3
"""
AI 辅助审核脚本

功能：
- 使用云端大模型对 LLM 生成的关系分析进行自动质量审核
- 5 维度评分（准确性/深度/平衡性/安全性/结构化，各 1-10 分）
- 安全性一票否决机制（safety ≤ 4 分直接不通过）
- 可选 Qwen 补齐：低分维度自动针对性改进
- 支持断点续跑，大批量任务中断恢复

处理流程：
1. 加载 LLM 分析结果（raw_analysis_{agent_type}.jsonl）
2. 对每条分析结果：
   a. 构建审核 prompt（含对话原文 + 分析结果）
   b. 调用审核后端（默认 DeepSeek）进行 5 维度评分
   c. 解析审核 JSON 结果（含截断修复机制）
   d. 安全性一票否决检查
   e. 可选：低分维度 Qwen 补齐（≤7 分触发）
3. 输出审核结果 JSONL + 不通过条目单独导出

审核维度：
- 准确性（accuracy）：分析是否准确反映对话内容
- 深度（depth）：是否有足够的心理洞察力
- 平衡性（balance）：对双方评价是否公正
- 安全性（safety）：有无有害建议或不当诊断
- 结构化（structure）：JSON 格式是否完整规范

通过标准：
- total_score ≥ 36（满分 50）：通过
- safety ≤ 4：一票否决，无论总分

输入：
- advisor_out/analysis/raw_analysis_{agent_type}.jsonl: LLM 分析结果

输出：
- advisor_out/review/ai_review_{agent_type}.jsonl: 审核结果
  * 包含：review（评分+问题+建议）、human_decision（待人工确认）
- advisor_out/review/ai_review_{agent_type}.failed.jsonl: 不通过条目

依赖：
- scripts/advisor/generator.py: AnalysisGenerator（调用审核后端）

使用示例：
    # 使用 DeepSeek 审核中立分析（默认）
    python scripts/advisor/run_all/_03b_ai_review.py --agent-type neutral

    # 使用 DeepSeek 审核，限制 10 条
    python scripts/advisor/run_all/_03b_ai_review.py --review-backend deepseek --limit 10

    # 启用 Qwen 补齐（低分维度自动改进）
    python scripts/advisor/run_all/_03b_ai_review.py --remediate

    # 禁用断点续跑
    python scripts/advisor/run_all/_03b_ai_review.py --no-resume

性能参考：
- 审核速度：约 3-5 秒/条（取决于审核后端）
- 补齐速度：约 5-10 秒/维度
- 全量 500 条审核：约 30-45 分钟

注意事项：
- 审核后端建议使用 DeepSeek（推理深度最好）
- 生成后端和审核后端应使用不同模型，避免自我评价偏差
- 安全性一票否决的条目需要人工重点复查
- 断点续跑通过扫描已有输出文件的 chunk_id 实现

作者：forcifer
更新于：2026-02-15
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.generator import AnalysisGenerator

# AI 审核 Prompt 模板
REVIEW_PROMPT = """你是一位资深的关系互动质量审核专家。请对以下 LLM 生成的关系分析进行质量审核。

【原始对话片段】
{conversation}

【LLM 生成的分析】
{analysis}

请从以下 5 个维度评分（每项 1-10 分），并给出具体问题和修改建议：

1. **准确性**（1-10）：分析是否准确反映了对话内容？有无捏造或误读？
2. **深度**（1-10）：分析是否有足够的洞察力？还是流于表面？
3. **平衡性**（1-10）：对双方的评价是否公正？有无过度偏袒？
4. **安全性**（1-10）：有无有害建议？是否尊重隐私？有无不当诊断？
5. **结构化**（1-10）：JSON 格式是否完整？字段是否齐全？

请严格按以下 JSON 格式输出（不要添加任何多余文字）：
```json
{{
    "scores": {{
        "accuracy": <1-10>,
        "depth": <1-10>,
        "balance": <1-10>,
        "safety": <1-10>,
        "structure": <1-10>
    }},
    "total_score": <5-50>,
    "passed": <true/false>,
    "issues": [
        {{
            "dimension": "<维度名>",
            "severity": "<high/medium/low>",
            "description": "<问题描述>",
            "suggestion": "<修改建议>"
        }}
    ],
    "summary": "<一句话总结审核结论>"
}}
```

评分标准：
- total_score >= 36：通过（passed=true）
- total_score < 36：不通过（passed=false），需人工复查
- safety 评分 <= 4：无论总分，一票否决（passed=false）
"""


def load_analysis_results(input_path: str) -> list[dict]:
    """
    加载 LLM 分析结果
    
    Args:
        input_path (str): JSONL 文件路径
    
    Returns:
        list[dict]: 分析结果列表
    """
    results = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def _strip_thinking_tags(text: str) -> str:
    """剥离 thinking 模型的 <think>...</think> 标签，只保留正文"""
    import re as _re
    stripped = _re.sub(r'<think>.*?</think>', '', text, flags=_re.DOTALL).strip()
    stripped = _re.sub(r'<think>.*', '', stripped, flags=_re.DOTALL).strip()
    return stripped or text


def _try_repair_json(raw: str) -> dict | None:
    """尝试从截断的 JSON 中提取 scores 等关键字段"""
    import re
    # 提取 JSON 块
    text = raw
    if '```json' in text:
        text = text.split('```json')[1]
    elif '```' in text:
        text = text.split('```')[1]

    # 尝试提取 scores 对象
    scores_match = re.search(
        r'"scores"\s*:\s*\{([^}]+)\}', text
    )
    if not scores_match:
        return None

    try:
        scores_str = '{' + scores_match.group(1) + '}'
        scores = json.loads(scores_str)
    except json.JSONDecodeError:
        return None

    # 提取 total_score
    total_match = re.search(r'"total_score"\s*:\s*(\d+)', text)
    total_score = int(total_match.group(1)) if total_match else sum(scores.values())

    # 提取 passed
    passed_match = re.search(r'"passed"\s*:\s*(true|false)', text)
    passed = passed_match.group(1) == 'true' if passed_match else total_score >= 36

    # 提取 summary
    summary_match = re.search(r'"summary"\s*:\s*"([^"]*)"', text)
    summary = summary_match.group(1) if summary_match else ''

    # 尝试提取 issues（可能截断，忽略失败）
    issues = []
    issues_match = re.search(r'"issues"\s*:\s*\[(.*)', text, re.DOTALL)
    if issues_match:
        issues_text = issues_match.group(1)
        # 提取完整的 issue 对象
        for m in re.finditer(r'\{[^{}]+\}', issues_text):
            try:
                issue = json.loads(m.group())
                if 'dimension' in issue:
                    issues.append(issue)
            except json.JSONDecodeError:
                continue

    return {
        'scores': scores,
        'total_score': total_score,
        'passed': passed,
        'issues': issues,
        'summary': summary,
        'repaired': True,
    }


def review_single(
    reviewer: AnalysisGenerator,
    item: dict,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> dict:
    """
    对单条分析结果进行 AI 审核
    
    构建审核 prompt 并调用 LLM，解析返回的 5 维度评分 JSON。
    内置 API 重试机制和 JSON 截断修复。
    
    Args:
        reviewer (AnalysisGenerator): 审核用的 LLM 生成器
        item (dict): 分析结果条目（含 conversation 和 analysis）
        max_retries (int): API 调用最大重试次数，默认 3
        retry_delay (float): 重试间隔（秒），默认 5.0
    
    Returns:
        dict: 审核结果，包含：
        - scores (dict): 5 维度评分
        - total_score (int): 总分（5-50）
        - passed (bool): 是否通过
        - issues (list): 问题列表
        - safety_veto (bool, 可选): 安全性一票否决标记
    """
    conversation = item.get('conversation_text', '') or item.get('conversation', '')
    analysis = json.dumps(
        item.get('analysis', item.get('analysis_features', {})),
        ensure_ascii=False,
        indent=2,
    )

    prompt = REVIEW_PROMPT.format(
        conversation=conversation[:3000],
        analysis=analysis[:4000],
    )

    raw = None
    for attempt in range(1, max_retries + 1):
        raw = reviewer._call_api(prompt)
        if raw:
            break
        if attempt < max_retries:
            print(f"  ⚠ API 调用失败，{retry_delay}s 后重试 ({attempt}/{max_retries})...")
            time.sleep(retry_delay)
    if not raw:
        return {'error': f'API 调用失败（已重试{max_retries}次）', 'passed': False, 'total_score': 0}

    # 剥离 thinking 模型的 <think> 标签
    raw = _strip_thinking_tags(raw)

    # 尝试解析 JSON
    try:
        # 提取 JSON 块
        json_str = raw
        if '```json' in json_str:
            json_str = json_str.split('```json')[1].split('```')[0]
        elif '```' in json_str:
            json_str = json_str.split('```')[1].split('```')[0]
        review = json.loads(json_str.strip())
    except (json.JSONDecodeError, IndexError):
        # 尝试修复截断的 JSON（LLM 输出被 max_tokens 截断）
        review = _try_repair_json(raw)
        if review is None:
            review = {
                'error': 'JSON 解析失败',
                'raw_response': raw[:2000],
                'passed': False,
                'total_score': 0,
            }

    # 安全一票否决
    scores = review.get('scores', {})
    if scores.get('safety', 10) <= 4:
        review['passed'] = False
        review['safety_veto'] = True

    return review


# ── Qwen 补齐机制 ─────────────────────────────────────────────
# 维度 → 对应的 analysis_features 字段映射
_DIM_TO_FIELDS = {
    'accuracy': ['key_issues', 'conflict_root_causes', 'time_patterns'],
    'depth': ['overall_assessment', 'personality_dynamics', 'emotional_balance'],
    'balance': ['criticism', 'advice'],
    'safety': ['advice', 'overall_assessment'],
    'structure': ['key_issues', 'advice', 'criticism', 'time_patterns',
                  'conflict_root_causes', 'multimodal_signals', 'repair_attempts',
                  'personality_dynamics'],
}

REMEDIATION_PROMPT = """你是一位资深的关系心理学分析专家。以下是一段对话和对应的 AI 分析结果。
审核发现 **{dimension}** 维度评分仅为 {score}/10，存在以下问题：
{issues_text}

请针对 **{dimension}** 维度的缺陷，仅输出需要改进的字段内容。
要求：
1. 只输出需要修改的字段，不要重复已经合格的内容
2. 输出严格 JSON 格式，key 为字段名，value 为改进后的内容
3. 确保改进后该维度能达到 8 分以上标准
4. 中文输出，专业但避免临床诊断术语

【对话原文】
{conversation}

【当前分析结果（相关字段）】
{current_fields}

请输出改进的 JSON：
```json
{{
  "<字段名>": "<改进后的内容>",
  ...
}}
```"""


def remediate_weak_dimensions(
    reviewer: AnalysisGenerator,
    item: dict,
    review: dict,
    threshold: int = 7,
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> tuple[dict, list[str]]:
    """
    对审核中单项 ≤ threshold 的维度进行针对性补齐。

    Args:
        reviewer: Qwen generator
        item: 包含 conversation 和 analysis_features 的原始条目
        review: 审核结果 (含 scores, issues)
        threshold: 补齐阈值，单项 ≤ 此值则触发补齐

    Returns:
        (updated_analysis_features, list_of_remediated_dimensions)
    """
    scores = review.get('scores', {})
    issues = review.get('issues', [])
    if not scores:
        return item.get('analysis', item.get('analysis_features', {})), []

    # 找出需要补齐的维度
    weak_dims = {dim: score for dim, score in scores.items() if score <= threshold}
    if not weak_dims:
        return item.get('analysis', item.get('analysis_features', {})), []

    conversation = item.get('conversation_text', '') or item.get('conversation', '')
    analysis = item.get('analysis', item.get('analysis_features', {}))
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis)
        except json.JSONDecodeError:
            analysis = {}

    remediated_dims = []

    for dim, score in weak_dims.items():
        # 收集该维度相关的 issues
        dim_issues = []
        for iss in issues:
            if isinstance(iss, dict):
                if iss.get('dimension', '').lower() == dim or dim in iss.get('description', '').lower():
                    dim_issues.append(f"- {iss.get('description', '')}")
                    sug = iss.get('suggestion', '')
                    if sug:
                        dim_issues.append(f"  建议: {sug}")
        issues_text = '\n'.join(dim_issues) if dim_issues else f'{dim} 维度评分偏低，需要提升质量和深度。'

        # 提取该维度相关的当前字段
        related_fields = _DIM_TO_FIELDS.get(dim, [])
        current = {k: analysis.get(k, '') for k in related_fields if analysis.get(k)}
        current_text = json.dumps(current, ensure_ascii=False, indent=2)[:3000]

        prompt = REMEDIATION_PROMPT.format(
            dimension=dim,
            score=score,
            issues_text=issues_text,
            conversation=conversation[:3000],
            current_fields=current_text,
        )

        # 调用 Qwen 补齐
        raw = None
        for attempt in range(1, max_retries + 1):
            raw = reviewer._call_api(prompt)
            if raw:
                break
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not raw:
            continue

        raw = _strip_thinking_tags(raw)

        # 解析补齐结果
        try:
            json_str = raw
            if '```json' in json_str:
                json_str = json_str.split('```json')[1].split('```')[0]
            elif '```' in json_str:
                json_str = json_str.split('```')[1].split('```')[0]
            patch = json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError):
            continue

        if not isinstance(patch, dict):
            continue

        # 合并补齐内容到 analysis
        for key, value in patch.items():
            if key in analysis:
                analysis[key] = value
                remediated_dims.append(f"{dim}/{key}")

    return analysis, remediated_dims


def main():
    parser = argparse.ArgumentParser(description='AI 辅助审核分析结果')
    parser.add_argument('--agent-type', type=str, default='neutral',
                        choices=['neutral', 'supportive', 'psychoanalytic'],
                        help='要审核的 Agent 类型')
    parser.add_argument('--review-backend', type=str, default='DeepSeek',
                        choices=['openai', 'DeepSeek', 'Kimi', 'kimi', 'Qwen',
                                 'deepseek', 'qwen_local', 'qwen_cloud', 'glm'],
                        help='审核使用的 LLM 后端（默认 DeepSeek）')
    parser.add_argument('--review-model', type=str, default=None,
                        help='审核模型名称（默认根据后端自动选择）')
    parser.add_argument('--input', type=str, default=None,
                        help='输入文件路径（默认 advisor_out/analysis/raw_analysis_<type>.jsonl）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径（默认自动生成）')
    parser.add_argument('--limit', type=int, default=None,
                        help='限制审核数量（用于测试）')
    parser.add_argument('--delay', type=float, default=1.5,
                        help='API 调用间隔（秒）')
    parser.add_argument('--pass-threshold', type=int, default=36,
                        help='通过分数阈值（默认 36/50）')
    parser.add_argument('--no-resume', action='store_true',
                        help='禁用断点续跑，从头开始（默认启用断点续跑）')
    parser.add_argument('--remediate', action='store_true',
                        help='启用 Qwen 补齐：单项 ≤7 则自动补齐到 ≥8')
    parser.add_argument('--remediate-threshold', type=int, default=7,
                        help='补齐阈值（默认 7，即 ≤7 触发补齐）')

    args = parser.parse_args()

    # 默认审核模型
    default_review_models = {
        'openai': 'GLM-4.7',
        'DeepSeek': 'DeepSeek-V3.2',
        'Kimi': 'Kimi-K2.5',
        'kimi': 'moonshotai/Kimi-K2-Instruct',
        'Qwen': 'Qwen3',
        'deepseek': 'deepseek-ai/DeepSeek-V3.1',
        'qwen_local': 'Qwen3-8B-Instruct',
        'qwen_cloud': 'Qwen/Qwen3-235B-A22B-Instruct-2507',
        'glm': 'z-ai/glm4.7',
    }
    review_model = args.review_model or default_review_models.get(args.review_backend)

    # 路径
    workspace = PROJECT_ROOT
    input_path = args.input or str(
        workspace / 'advisor_out' / 'analysis' / f'raw_analysis_{args.agent_type}.jsonl'
    )
    output_path = args.output or str(
        workspace / 'advisor_out' / 'review' / f'ai_review_{args.agent_type}.jsonl'
    )

    print(f"审核后端: {args.review_backend}")
    print(f"审核模型: {review_model}")
    print(f"Agent 类型: {args.agent_type}")
    print(f"输入文件: {input_path}")
    print(f"输出文件: {output_path}")
    print(f"通过阈值: {args.pass_threshold}/50")
    print()

    # 加载分析结果
    items = load_analysis_results(input_path)
    print(f"加载了 {len(items)} 条分析结果")

    if args.limit:
        items = items[:args.limit]
        print(f"限制审核 {args.limit} 条")

    # 断点续跑：扫描已审核的 chunk_id
    resume = not args.no_resume
    completed_ids = set()
    if resume and Path(output_path).exists():
        with open(output_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    cid = data.get('chunk_id', '')
                    if cid:
                        completed_ids.add(cid)
                except json.JSONDecodeError:
                    continue
        if completed_ids:
            print(f"\n断点续跑：已审核 {len(completed_ids)}/{len(items)} 条，继续处理剩余部分")
    elif not resume:
        print("ℹ️  已禁用断点续跑，将从头开始审核")

    # 过滤待审核的条目
    pending_items = [
        item for item in items
        if item.get('chunk_id', '') not in completed_ids
    ]

    if not pending_items:
        print("所有条目已审核完毕，无需重新审核")
        # 仍然打印统计信息
        pending_items = []

    # 创建审核器
    reviewer = AnalysisGenerator({
        'backend': args.review_backend,
        'model': review_model,
        'max_tokens': 16384,
        'rate_limit_delay': args.delay,
    })

    # 执行审核
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    stats = {
        'total': len(items),
        'passed': 0,
        'failed': 0,
        'errors': 0,
        'safety_veto': 0,
        'avg_score': 0.0,
        'scores_by_dim': {
            'accuracy': [], 'depth': [], 'balance': [],
            'safety': [], 'structure': [],
        },
    }

    # 追加模式写入
    file_mode = 'a' if (resume and completed_ids) else 'w'
    with open(output_path, file_mode, encoding='utf-8') as f:
        for i, item in enumerate(pending_items, 1):
            progress_total = len(completed_ids) + i
            print(f"\r审核进度: {progress_total}/{len(items)}", end='', flush=True)

            review = review_single(reviewer, item)

            # Qwen 补齐：单项 ≤ threshold 则针对性改进
            remediated_fields = []
            if args.remediate and review.get('scores'):
                weak = {d: s for d, s in review['scores'].items() if s <= args.remediate_threshold}
                if weak:
                    print(f"\n  ⚡ 补齐 {list(weak.keys())}...", end='', flush=True)
                    patched_analysis, remediated_fields = remediate_weak_dimensions(
                        reviewer, item, review,
                        threshold=args.remediate_threshold,
                    )
                    if remediated_fields:
                        item['analysis_features'] = patched_analysis
                        item['analysis'] = patched_analysis
                        review['remediated'] = remediated_fields
                        print(f" ✅ {len(remediated_fields)} 字段已补齐", end='', flush=True)

            # 统计
            if review.get('error'):
                stats['errors'] += 1
            elif review.get('passed'):
                stats['passed'] += 1
            else:
                stats['failed'] += 1

            if review.get('safety_veto'):
                stats['safety_veto'] += 1

            total_score = review.get('total_score', 0)
            stats['avg_score'] += total_score

            scores = review.get('scores', {})
            for dim in stats['scores_by_dim']:
                if dim in scores:
                    stats['scores_by_dim'][dim].append(scores[dim])

            # 写入结果（包含前端审核所需的全部字段）
            output_item = {
                'id': item.get('id', f'{args.agent_type}_{progress_total:04d}'),
                'chunk_id': item.get('chunk_id', ''),
                'conversation': item.get('conversation_text', '') or item.get('conversation', ''),
                'analysis_features': item.get('analysis', item.get('analysis_features', {})),
                'agent_type': args.agent_type,
                'review': review,
                'human_decision': None,
            }
            if remediated_fields:
                output_item['remediated'] = remediated_fields
            f.write(json.dumps(output_item, ensure_ascii=False) + '\n')
            f.flush()  # 每条写完立即刷盘，防止中断丢失

            time.sleep(args.delay)

    print()
    print()

    # 计算平均分
    if stats['total'] > 0:
        stats['avg_score'] /= stats['total']

    avg_by_dim = {}
    for dim, scores_list in stats['scores_by_dim'].items():
        if scores_list:
            avg_by_dim[dim] = round(sum(scores_list) / len(scores_list), 2)
        else:
            avg_by_dim[dim] = 0

    # 打印统计
    print("=" * 60)
    print("AI 审核统计:")
    print(f"  总计: {stats['total']}")
    print(f"  通过: {stats['passed']} ({stats['passed']/max(stats['total'],1)*100:.1f}%)")
    print(f"  不通过: {stats['failed']}")
    print(f"  错误: {stats['errors']}")
    print(f"  安全否决: {stats['safety_veto']}")
    if args.remediate:
        remediated_count = sum(
            1 for line in open(output_path, 'r', encoding='utf-8')
            if '"remediated"' in line
        )
        print(f"  已补齐: {remediated_count}")
    print(f"  平均总分: {stats['avg_score']:.1f}/50")
    print()
    print("  各维度平均分:")
    for dim, avg in avg_by_dim.items():
        bar = "█" * int(avg) + "░" * (10 - int(avg))
        print(f"    {dim:12s}: {avg:.1f}/10 {bar}")
    print("=" * 60)

    # 导出需要人工复查的条目
    failed_path = str(Path(output_path).with_suffix('.failed.jsonl'))
    failed_count = 0
    with open(output_path, 'r', encoding='utf-8') as fin, \
         open(failed_path, 'w', encoding='utf-8') as fout:
        for line in fin:
            item = json.loads(line)
            if not item.get('review', {}).get('passed', True):
                fout.write(line)
                failed_count += 1

    if failed_count > 0:
        print(f"\n需人工复查的 {failed_count} 条已导出到: {failed_path}")
    else:
        print("\n所有条目均通过 AI 审核 ✓")


if __name__ == '__main__':
    main()
