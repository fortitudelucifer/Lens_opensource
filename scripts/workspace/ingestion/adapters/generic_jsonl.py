"""
generic_jsonl.py
通用 JSONL 适配器

根据 Source_Manifest 中的 field_mapping 配置将 JSON 键名映射为 Canonical Schema 字段名。
复用 generic_csv 模块的 apply_field_mapping() 和 validate_field_mapping() 函数。

支持三种映射语法（同 CSV 适配器）：
- 直接映射：source_field: target_field
- 常量值：_const:value: target_field（所有记录使用此值）
- 默认值：_default:value: target_field（仅源字段缺失时使用）

Requirements: 7.2, 7.3, 7.4
"""

import json
import logging
from pathlib import Path
from typing import Iterator

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.adapters.generic_csv import (
    apply_field_mapping,
    validate_field_mapping,
)
from scripts.workspace.ingestion.manifest import SourceManifest

logger = logging.getLogger(__name__)


class GenericJSONLAdapter(SourceAdapter):
    """通用 JSONL 适配器

    通过 field_mapping 配置驱动，支持任意 JSONL 格式的数据导入。
    """

    def supported_source_type(self) -> str:
        return "generic_jsonl"

    def parse(self, input_path: Path, manifest: SourceManifest) -> Iterator[dict]:
        """解析 JSONL 文件，逐条产出标准消息字典。

        - 逐行读取，json.loads() 解析
        - 根据 field_mapping 映射键名
        - 自动生成 msg_uid（{prefix}:{row_number}，1-based）
        - 类型转换：ts → int, type → int, sub_type → int
        - 跳过空行，JSON 解析错误记录警告
        """
        field_mapping = manifest.field_mapping if manifest else {}

        # 提取 _source_prefix
        source_prefix = "JSONL"
        for source_key, target_field in field_mapping.items():
            if target_field == "_source_prefix" and source_key.startswith("_const:"):
                source_prefix = source_key[len("_const:"):]
                break

        # 构建不含 _source_prefix 的映射
        effective_mapping = {
            k: v for k, v in field_mapping.items() if v != "_source_prefix"
        }

        participant_map = manifest.participant_map if manifest else {}

        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            row_num = 0
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue

                row_num += 1
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError as e:
                    logger.warning("行 %d: JSON 解析失败: %s", row_num, e)
                    continue

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
        if input_path.is_file() and input_path.suffix.lower() != ".jsonl":
            errors.append(f"期望 JSONL 文件，实际: {input_path}")
        return errors

    def describe(self) -> dict:
        return {
            "source_type": "generic_jsonl",
            "description": "通用 JSONL 适配器，通过 field_mapping 配置映射任意 JSONL 键名",
            "expected_files": ["*.jsonl (JSONL 数据文件)"],
            "field_mapping_example": {
                "send_time": "ts",
                "sender_name": "speaker",
                "content": "text_raw",
                "msg_type": "type",
                "_const:WXWORK": "_source_prefix",
                "_default:text": "modality",
            },
        }
