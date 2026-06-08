"""
base.py
来源适配器抽象基类

定义 SourceAdapter ABC，所有具体适配器（微信、Telegram、WhatsApp、通用 CSV/JSONL）
均需继承此基类并实现 parse() 和 supported_source_type() 抽象方法。

Requirements: 3.1, 3.4, 3.5
"""

from abc import ABC, abstractmethod
from typing import Iterator
from pathlib import Path


class SourceAdapter(ABC):
    """来源适配器抽象基类"""

    @abstractmethod
    def supported_source_type(self) -> str:
        """返回此适配器支持的 source_type 标识"""
        ...

    @abstractmethod
    def parse(self, input_path: Path, manifest: 'SourceManifest') -> Iterator[dict]:
        """解析输入文件，逐条产出标准消息字典"""
        ...

    def validate_input(self, input_path: Path) -> list[str]:
        """校验输入文件，返回错误列表（空列表表示校验通过）"""
        errors = []
        if not input_path.exists():
            errors.append(f"输入路径不存在: {input_path}")
        return errors

    def detect_media_files(self, input_path: Path) -> list[Path]:
        """检测输入中关联的媒体文件路径列表"""
        return []

    def describe(self) -> dict:
        """返回适配器说明信息（用于 --show-adapters）"""
        return {
            "source_type": self.supported_source_type(),
            "description": self.__class__.__doc__ or "",
            "expected_files": [],
            "field_mapping_example": {},
        }
