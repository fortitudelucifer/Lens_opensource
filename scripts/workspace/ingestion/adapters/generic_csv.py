"""
generic_csv.py
通用 CSV 适配器

根据 Source_Manifest 中的 field_mapping 配置将 CSV 列名映射为 Canonical Schema 字段名。
支持三种映射语法：
- 直接映射：source_field: target_field
- 常量值：_const:value: target_field（所有记录使用此值）
- 默认值：_default:value: target_field（仅源字段缺失时使用）

模块级函数 apply_field_mapping() 和 validate_field_mapping() 可被 generic_jsonl 复用。

Requirements: 7.1, 7.3, 7.4
"""

import csv
import logging
from pathlib import Path
from typing import Iterator

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.manifest import SourceManifest
from scripts.workspace.ingestion.schema import REQUIRED_FIELDS

logger = logging.getLogger(__name__)


def apply_field_mapping(row: dict, field_mapping: dict) -> dict:
    """根据 field_mapping 配置将源数据行映射为目标字段字典。

    映射语法：
    - source_field: target_field        → 直接映射
    - _const:value: target_field        → 常量值
    - _default:value: target_field      → 默认值（源字段缺失时使用）

    Args:
        row: 源数据行（dict）
        field_mapping: {source_key: target_field} 映射配置

    Returns:
        映射后的目标字段字典
    """
    result = {}
    defaults = {}  # target_field → default_value

    # 第一遍：处理直接映射和常量值，收集默认值
    for source_key, target_field in field_mapping.items():
        if source_key.startswith("_const:"):
            value = source_key[len("_const:"):]
            result[target_field] = value
        elif source_key.startswith("_default:"):
            default_value = source_key[len("_default:"):]
            defaults[target_field] = default_value
        else:
            # 直接映射：源字段存在且非空时使用
            if source_key in row and row[source_key] is not None and row[source_key] != "":
                result[target_field] = row[source_key]

    # 第二遍：填充默认值（仅当目标字段未被直接映射或常量覆盖时）
    for target_field, default_value in defaults.items():
        if target_field not in result:
            result[target_field] = default_value

    return result


def validate_field_mapping(field_mapping: dict) -> list[str]:
    """校验 field_mapping 是否覆盖所有 Canonical Schema 必填字段。

    必填字段中 msg_uid 由适配器自动生成（通过 _source_prefix），不需要用户映射。
    其余必填字段（ts, speaker, type, modality, text_raw）必须有映射或常量/默认值覆盖。

    Args:
        field_mapping: {source_key: target_field} 映射配置

    Returns:
        错误信息列表（空列表=通过）
    """
    errors: list[str] = []

    # 收集所有 target_field（包括 _const 和 _default 提供的）
    covered_targets = set()
    for source_key, target_field in field_mapping.items():
        covered_targets.add(target_field)

    # msg_uid 由适配器通过 _source_prefix 自动生成，不需要用户显式映射
    required_check = set(REQUIRED_FIELDS) - {"msg_uid"}

    missing = required_check - covered_targets
    if missing:
        for field_name in sorted(missing):
            errors.append(f"field_mapping 缺少必填字段映射: {field_name}")

    return errors


class GenericCSVAdapter(SourceAdapter):
    """通用 CSV 适配器

    通过 field_mapping 配置驱动，支持任意 CSV 格式的数据导入。
    """

    def supported_source_type(self) -> str:
        return "generic_csv"

    def parse(self, input_path: Path, manifest: SourceManifest) -> Iterator[dict]:
        """解析 CSV 文件，逐条产出标准消息字典。

        - 使用 csv.DictReader 读取
        - 根据 field_mapping 映射列名
        - 自动生成 msg_uid（{prefix}:{row_number}，1-based）
        - 类型转换：ts → int, type → int
        """
        field_mapping = manifest.field_mapping if manifest else {}

        # 提取 _source_prefix
        source_prefix = "CSV"
        for source_key, target_field in field_mapping.items():
            if target_field == "_source_prefix" and source_key.startswith("_const:"):
                source_prefix = source_key[len("_const:"):]
                break

        # 构建不含 _source_prefix 的映射（_source_prefix 是元配置，不是字段映射）
        effective_mapping = {
            k: v for k, v in field_mapping.items() if v != "_source_prefix"
        }

        participant_map = manifest.participant_map if manifest else {}

        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=1):
                record = apply_field_mapping(row, effective_mapping)

                # 生成 msg_uid
                record["msg_uid"] = f"{source_prefix}:{row_num}"

                # 应用 participant_map 映射 speaker
                if "speaker" in record and participant_map:
                    raw_speaker = record["speaker"]
                    if raw_speaker in participant_map:
                        record["speaker"] = participant_map[raw_speaker]
                    elif raw_speaker not in ("ME", "OTHER") and not raw_speaker.startswith("OTHER:"):
                        record["speaker"] = f"OTHER:{raw_speaker}"

                # 类型转换：ts → int
                if "ts" in record:
                    try:
                        record["ts"] = int(record["ts"])
                    except (ValueError, TypeError):
                        logger.warning(
                            "行 %d: ts 转换失败，值=%r", row_num, record.get("ts")
                        )
                        record["ts"] = 0

                # 类型转换：type → int
                if "type" in record:
                    try:
                        record["type"] = int(record["type"])
                    except (ValueError, TypeError):
                        logger.warning(
                            "行 %d: type 转换失败，值=%r", row_num, record.get("type")
                        )
                        record["type"] = 0

                # 类型转换：sub_type → int
                if "sub_type" in record:
                    try:
                        record["sub_type"] = int(record["sub_type"])
                    except (ValueError, TypeError):
                        record["sub_type"] = 0

                yield record

    def validate_input(self, input_path: Path) -> list[str]:
        errors = super().validate_input(input_path)
        if errors:
            return errors
        if input_path.is_file() and input_path.suffix.lower() != ".csv":
            errors.append(f"期望 CSV 文件，实际: {input_path}")
        return errors

    def describe(self) -> dict:
        return {
            "source_type": "generic_csv",
            "description": "通用 CSV 适配器，通过 field_mapping 配置映射任意 CSV 列名",
            "expected_files": ["*.csv (CSV 数据文件)"],
            "field_mapping_example": {
                "timestamp": "ts",
                "sender_name": "speaker",
                "content": "text_raw",
                "_const:text": "modality",
                "_const:1": "type",
                "_default:0": "sub_type",
                "_const:GEN": "_source_prefix",
            },
        }
