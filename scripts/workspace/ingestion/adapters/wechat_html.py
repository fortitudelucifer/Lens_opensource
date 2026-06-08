"""
wechat_html.py
微信 HTML+CSV 导出适配器

复用 extract_html_to_jsonl.py 的核心逻辑（HTML 解析、CSV 元数据、类型映射），
将微信导出数据转换为 Canonical Schema 格式。

- 支持目录输入（自动查找 HTML+CSV）和直接 HTML 文件输入
- 消息类型映射：type → modality
- msg_uid 格式：P1:{MsgSvrID}
- 媒体路径标准化

Requirements: 4.1, 4.2, 4.3, 4.4
"""

from pathlib import Path
from typing import Iterator

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.manifest import SourceManifest


class WeChatAdapter(SourceAdapter):
    """微信 HTML+CSV 导出适配器"""

    def supported_source_type(self) -> str:
        return "wechat_html"

    def parse(self, input_path: Path, manifest: SourceManifest) -> Iterator[dict]:
        """
        解析微信导出文件。
        input_path 可以是：
        - HTML 文件路径
        - 包含 HTML+CSV 的目录路径
        """
        # 从现有模块导入核心函数（避免重复代码）
        from scripts.extract.extract_html_to_jsonl import (
            extract_chatmessages_array,
            load_csv_metadata,
            normalize_message,
            find_export_files,
        )

        if input_path.is_dir():
            html_path, csv_path = find_export_files(input_path)
        else:
            html_path = input_path
            # 尝试在同目录下查找 CSV 文件
            csv_path = None
            for f in html_path.parent.glob("*.csv"):
                csv_path = f
                break

        # 从 HTML 提取 chatMessages 数组
        html_messages = extract_chatmessages_array(html_path)

        # 加载 CSV 元数据（可选）
        csv_meta = {}
        if csv_path and csv_path.exists():
            csv_meta = load_csv_metadata(csv_path)

        # 从 participant_map 构建 me_names 集合
        me_names = set()
        if manifest and manifest.participant_map:
            for name, speaker in manifest.participant_map.items():
                if speaker == "ME":
                    me_names.add(name)

        # 逐条标准化消息
        for seq, msg in enumerate(html_messages):
            record = normalize_message(msg, seq, csv_meta, me_names)
            yield record

    def validate_input(self, input_path: Path) -> list[str]:
        """校验输入：目录需包含 HTML 文件，文件需为 .html 后缀"""
        errors = super().validate_input(input_path)
        if errors:
            return errors

        if input_path.is_dir():
            html_files = list(input_path.glob("*.html"))
            if not html_files:
                errors.append(f"目录中未找到 HTML 文件: {input_path}")
        elif not input_path.suffix.lower() == ".html":
            errors.append(f"期望 HTML 文件，实际: {input_path}")

        return errors

    def detect_media_files(self, input_path: Path) -> list[Path]:
        """检测输入目录中的媒体文件"""
        base_dir = input_path if input_path.is_dir() else input_path.parent
        media_files = []
        for pattern in [
            "image/**/*",
            "voice/**/*",
            "video/**/*",
            "sticker/**/*",
            "file/**/*",
        ]:
            media_files.extend(base_dir.glob(pattern))
        return [f for f in media_files if f.is_file()]

    def describe(self) -> dict:
        return {
            "source_type": "wechat_html",
            "description": "微信 HTML+CSV 导出适配器（复用 extract_html_to_jsonl.py）",
            "expected_files": [
                "*.html (微信导出 HTML)",
                "*.csv (微信导出 CSV, 可选)",
            ],
            "field_mapping_example": {},
        }
