from __future__ import annotations

import glob
import importlib
import json
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _CudaStub:
    class OutOfMemoryError(RuntimeError):
        pass

    @staticmethod
    def is_available() -> bool:
        return False

    @staticmethod
    def empty_cache() -> None:
        return None

    @staticmethod
    def synchronize() -> None:
        return None

    @staticmethod
    def memory_allocated(_device: int = 0) -> int:
        return 0

    @staticmethod
    def memory_reserved(_device: int = 0) -> int:
        return 0

    @staticmethod
    def get_device_name(_device: int = 0) -> str:
        return "cuda-unavailable"

    @staticmethod
    def get_device_properties(_device: int = 0):
        return types.SimpleNamespace(total_memory=0)


def install_torch_stub() -> None:
    if "torch" in sys.modules:
        return
    torch_stub = types.ModuleType("torch")
    torch_stub.cuda = _CudaStub()
    sys.modules["torch"] = torch_stub


def import_smoke() -> None:
    install_torch_stub()
    modules = [
        "scripts.advisor.analyzers",
        "scripts.advisor.schema_validator",
        "scripts.advisor.safety_layer",
        "scripts.advisor.model_router",
        "scripts.advisor.api.core.models",
        "scripts.advisor.api.routes.health",
        "scripts.advisor.api.routes.knowledge",
        "scripts.advisor.api.routes.models_routes",
        "scripts.advisor.api.routes.chat",
        "scripts.advisor.api.main",
    ]
    for module in modules:
        importlib.import_module(module)
        print(f"import ok: {module}")


def router_smoke() -> None:
    install_torch_stub()
    from scripts.advisor.router import ModelRouter

    router = ModelRouter()
    cases = [
        ({"complexity_score": 0.1}, "local_qwen3"),
        ({"complexity_score": 0.5}, "local_qwen3_thinking"),
        ({"complexity_score": 0.8}, "deepseek_reasoner"),
    ]
    for task, expected in cases:
        actual = router.route(task)
        if actual != expected:
            raise AssertionError(f"route({task}) returned {actual!r}, expected {expected!r}")
    budget_router = ModelRouter({"budget_limit_daily": 0.0})
    actual = budget_router.route({"complexity_score": 0.9})
    if actual != "local_qwen3":
        raise AssertionError(f"budget fallback returned {actual!r}")
    print("router smoke ok")


def validate_jsonl() -> None:
    patterns = [
        "advisor_out/knowledge/**/*.jsonl",
        "scripts/advisor/*_eval_set.jsonl",
    ]
    files: list[str] = []
    for pattern in patterns:
        files.extend(glob.glob(str(PROJECT_ROOT / pattern), recursive=True))
    if not files:
        raise AssertionError("no public JSONL files matched backend research CI patterns")
    records = 0
    for file_name in sorted(files):
        path = Path(file_name)
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                value = json.loads(stripped)
                if not isinstance(value, dict):
                    raise AssertionError(f"{path}:{line_number} is not a JSON object")
                records += 1
        print(f"jsonl ok: {path.relative_to(PROJECT_ROOT)}")
    if records == 0:
        raise AssertionError("public JSONL files contain no records")
    print(f"jsonl records ok: {records}")


def main() -> None:
    import_smoke()
    router_smoke()
    validate_jsonl()


if __name__ == "__main__":
    main()
