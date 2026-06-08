"""
manifest.py
来源清单（Source Manifest）加载与校验

定义 SourceManifest dataclass，提供 YAML 加载和配置校验功能。

- load_manifest(path) -> SourceManifest: 加载并解析 source_manifest.yaml
- validate_manifest(manifest, registered_types) -> list[str]: 校验清单配置

Requirements: 2.1, 2.2, 2.3, 2.4

运行方式：
    python -m pytest tests/workspace/ingestion/test_manifest.py -v
"""

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import yaml


@dataclass
class SourceManifest:
    """来源清单配置"""

    # 必填字段
    source_type: str                          # 适配器类型标识
    input_paths: list[str]                    # 输入文件/目录路径

    # 可选字段
    participant_map: dict[str, str] = field(default_factory=dict)  # 名称 -> speaker
    timezone: str = "Asia/Shanghai"
    media_base_dir: Optional[str] = None      # 媒体文件基础目录
    field_mapping: dict[str, str] = field(default_factory=dict)   # 通用适配器字段映射
    workspace_name: Optional[str] = None


def load_manifest(path: Path) -> SourceManifest:
    """加载并校验 source_manifest.yaml

    Args:
        path: YAML 文件路径

    Returns:
        SourceManifest 实例

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 格式错误或缺少必填字段
        yaml.YAMLError: YAML 解析失败
    """
    if not path.exists():
        raise FileNotFoundError(f"source_manifest.yaml 不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(
            f"source_manifest.yaml 格式错误: 期望字典，实际为 {type(data).__name__}"
        )

    # 必填字段检查
    if "source_type" not in data:
        raise ValueError("source_manifest.yaml 缺少必填字段: source_type")
    if "input_paths" not in data:
        raise ValueError("source_manifest.yaml 缺少必填字段: input_paths")

    return SourceManifest(
        source_type=data["source_type"],
        input_paths=data["input_paths"],
        participant_map=data.get("participant_map", {}),
        timezone=data.get("timezone", "Asia/Shanghai"),
        media_base_dir=data.get("media_base_dir"),
        field_mapping=data.get("field_mapping", {}),
        workspace_name=data.get("workspace_name"),
    )


def validate_manifest(manifest: SourceManifest, registered_types: set[str]) -> list[str]:
    """校验清单配置，返回错误列表（空列表=通过）

    Args:
        manifest: 已加载的 SourceManifest 实例
        registered_types: 已注册的 source_type 集合

    Returns:
        错误信息列表
    """
    errors: list[str] = []

    # source_type 是否已注册
    if manifest.source_type not in registered_types:
        available = ", ".join(sorted(registered_types))
        errors.append(
            f"未知的 source_type: '{manifest.source_type}'，可用值: {available}"
        )

    # input_paths 不能为空
    if not manifest.input_paths:
        errors.append("input_paths 不能为空")

    return errors
