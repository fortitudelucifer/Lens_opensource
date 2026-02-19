#!/usr/bin/env python3
"""
逐后端单 chunk 探测脚本 —— 验证各代理商 API 可用性
用法: source .env.advisor && conda run -n CHAT_APP_DHA python -m scripts.advisor.test_backends
"""
import os, sys, time, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.advisor.generator import AnalysisGenerator

TEST_PROMPT = "请用一句话回答：1+1等于几？只回答数字和简短解释即可。"

BACKENDS = [
    "DeepSeek", "deepseek", "openai", "Kimi",
    "kimi", "Qwen", "qwen_cloud", "glm",
]

def test_single_backend(backend: str) -> dict:
    """测试单个后端是否可达"""
    try:
        gen = AnalysisGenerator({
            "backend": backend,
            "max_tokens": 256,
            "rate_limit_delay": 1.0,
        })
        model = gen.model
        base_url = gen.base_url or "(默认)"
        print(f"  模型: {model}")
        print(f"  地址: {base_url}")

        t0 = time.time()
        resp = gen._call_api(TEST_PROMPT)
        elapsed = time.time() - t0

        if resp:
            preview = resp.strip()[:120].replace("\n", " ")
            print(f"  ✅ 成功 ({elapsed:.1f}s): {preview}")
            return {"backend": backend, "model": model, "status": "ok", "time": round(elapsed, 1), "preview": preview}
        else:
            print(f"  ❌ 返回空")
            return {"backend": backend, "model": model, "status": "empty", "time": round(elapsed, 1)}
    except Exception as e:
        err = str(e)[:200]
        print(f"  ❌ 异常: {err}")
        return {"backend": backend, "model": model if 'model' in dir() else "?", "status": "error", "error": err}


def main():
    print("=" * 60)
    print("逐后端 API 可用性探测")
    print("=" * 60)

    results = []
    for backend in BACKENDS:
        print(f"\n── {backend} ──")
        prefix = AnalysisGenerator._ENV_PREFIX.get(backend, "")
        key = os.environ.get(f"{prefix}_API_KEY", "")
        if not key or key == "not-needed":
            print("  ⏭️  未配置 API Key，跳过")
            results.append({"backend": backend, "status": "skipped"})
            continue
        result = test_single_backend(backend)
        results.append(result)
        time.sleep(2)  # 避免代理限速

    print("\n" + "=" * 60)
    print("汇总:")
    print("=" * 60)
    for r in results:
        icon = {"ok": "✅", "skipped": "⏭️"}.get(r["status"], "❌")
        t = f" ({r.get('time', '?')}s)" if r.get("time") else ""
        print(f"  {icon} {r['backend']:12s} — {r['status']}{t}")

    # 保存结果
    out_path = PROJECT_ROOT / "advisor_out" / "backend_test_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存到: {out_path}")


if __name__ == "__main__":
    main()
