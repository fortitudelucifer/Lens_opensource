"""
registry.py
适配器注册表，自动扫描 adapters/ 目录发现并注册所有 SourceAdapter 子类。

支持自动发现（discover）和手动注册（register），冲突检测确保同一 source_type 不会被多个适配器声明。

Requirements: 3.2, 3.3
"""

import importlib
import pkgutil

from scripts.workspace.ingestion.adapters.base import SourceAdapter


class AdapterRegistry:
    """适配器注册表，自动扫描 adapters/ 目录"""

    def __init__(self):
        self._adapters: dict[str, SourceAdapter] = {}

    def discover(self, adapters_package: str = "scripts.workspace.ingestion.adapters"):
        """扫描并注册所有适配器"""
        package = importlib.import_module(adapters_package)
        for _importer, modname, _ispkg in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{adapters_package}.{modname}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, SourceAdapter)
                    and attr is not SourceAdapter
                ):
                    instance = attr()
                    st = instance.supported_source_type()
                    if st in self._adapters:
                        raise RuntimeError(
                            f"source_type '{st}' 冲突: "
                            f"{self._adapters[st].__class__.__name__} vs {attr.__name__}"
                        )
                    self._adapters[st] = instance

    def register(self, adapter: SourceAdapter) -> None:
        """手动注册适配器"""
        st = adapter.supported_source_type()
        if st in self._adapters:
            raise RuntimeError(
                f"source_type '{st}' 冲突: "
                f"{self._adapters[st].__class__.__name__} vs {adapter.__class__.__name__}"
            )
        self._adapters[st] = adapter

    def get(self, source_type: str) -> SourceAdapter:
        """获取适配器，不存在则抛出 KeyError"""
        if source_type not in self._adapters:
            available = ", ".join(sorted(self._adapters.keys()))
            raise KeyError(
                f"未知的 source_type: '{source_type}'，可用值: {available}"
            )
        return self._adapters[source_type]

    def list_types(self) -> list[str]:
        """列出所有已注册的 source_type（排序）"""
        return sorted(self._adapters.keys())
