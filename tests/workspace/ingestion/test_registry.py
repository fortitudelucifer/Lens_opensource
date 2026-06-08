"""
test_registry.py
AdapterRegistry 单元测试 + 属性测试

Property 16: 未注册 source_type 错误信息
Validates: Requirements 2.4
"""

import pytest
from pathlib import Path
from typing import Iterator

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from scripts.workspace.ingestion.adapters.base import SourceAdapter
from scripts.workspace.ingestion.registry import AdapterRegistry


# ---------------------------------------------------------------------------
# 测试用 Adapter 桩
# ---------------------------------------------------------------------------

class FakeAdapterA(SourceAdapter):
    """测试适配器 A"""

    def supported_source_type(self) -> str:
        return "fake_a"

    def parse(self, input_path: Path, manifest=None) -> Iterator[dict]:
        yield {}


class FakeAdapterB(SourceAdapter):
    """测试适配器 B"""

    def supported_source_type(self) -> str:
        return "fake_b"

    def parse(self, input_path: Path, manifest=None) -> Iterator[dict]:
        yield {}


class ConflictAdapter(SourceAdapter):
    """与 FakeAdapterA 声明相同 source_type 的冲突适配器"""

    def supported_source_type(self) -> str:
        return "fake_a"

    def parse(self, input_path: Path, manifest=None) -> Iterator[dict]:
        yield {}


# ---------------------------------------------------------------------------
# 单元测试
# ---------------------------------------------------------------------------

class TestAdapterRegistry:
    """AdapterRegistry 基本功能测试"""

    def test_register_and_get(self):
        """手动注册后可通过 get() 获取"""
        registry = AdapterRegistry()
        adapter = FakeAdapterA()
        registry.register(adapter)
        assert registry.get("fake_a") is adapter

    def test_register_multiple(self):
        """注册多个不同 source_type 的适配器"""
        registry = AdapterRegistry()
        registry.register(FakeAdapterA())
        registry.register(FakeAdapterB())
        assert registry.list_types() == ["fake_a", "fake_b"]

    def test_list_types_sorted(self):
        """list_types 返回排序后的列表"""
        registry = AdapterRegistry()
        registry.register(FakeAdapterB())
        registry.register(FakeAdapterA())
        assert registry.list_types() == ["fake_a", "fake_b"]

    def test_list_types_empty(self):
        """空注册表返回空列表"""
        registry = AdapterRegistry()
        assert registry.list_types() == []

    def test_get_unknown_raises_key_error(self):
        """获取未注册的 source_type 抛出 KeyError"""
        registry = AdapterRegistry()
        registry.register(FakeAdapterA())
        with pytest.raises(KeyError, match="未知的 source_type"):
            registry.get("nonexistent")

    def test_get_unknown_lists_available(self):
        """KeyError 消息中包含所有已注册的 source_type"""
        registry = AdapterRegistry()
        registry.register(FakeAdapterA())
        registry.register(FakeAdapterB())
        with pytest.raises(KeyError) as exc_info:
            registry.get("nonexistent")
        msg = str(exc_info.value)
        assert "fake_a" in msg
        assert "fake_b" in msg

    def test_register_conflict_raises_runtime_error(self):
        """注册相同 source_type 的适配器抛出 RuntimeError"""
        registry = AdapterRegistry()
        registry.register(FakeAdapterA())
        with pytest.raises(RuntimeError, match="冲突"):
            registry.register(ConflictAdapter())

    def test_conflict_error_includes_class_names(self):
        """冲突错误信息包含两个适配器的类名"""
        registry = AdapterRegistry()
        registry.register(FakeAdapterA())
        with pytest.raises(RuntimeError) as exc_info:
            registry.register(ConflictAdapter())
        msg = str(exc_info.value)
        assert "FakeAdapterA" in msg
        assert "ConflictAdapter" in msg

    def test_get_from_empty_registry(self):
        """空注册表中获取任何 source_type 都抛出 KeyError"""
        registry = AdapterRegistry()
        with pytest.raises(KeyError, match="可用值:"):
            registry.get("anything")


# ---------------------------------------------------------------------------
# 属性测试
# ---------------------------------------------------------------------------

class TestProperty16UnregisteredSourceType:
    """
    Property 16: 未注册 source_type 错误信息
    Feature: universal-ingestion, Property 16: 未注册 source_type 错误信息

    **Validates: Requirements 2.4**
    """

    @given(
        registered_types=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
                min_size=1,
                max_size=15,
            ),
            min_size=1,
            max_size=5,
            unique=True,
        ),
        unknown_type=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
            min_size=1,
            max_size=15,
        ),
    )
    @settings(max_examples=200)
    def test_unknown_type_error_lists_all_registered(self, registered_types, unknown_type):
        """未注册的 source_type 抛出 KeyError，且错误信息包含所有已注册类型"""
        assume(unknown_type not in registered_types)

        # Build registry with dynamic adapters
        registry = AdapterRegistry()
        for st_name in registered_types:
            adapter = type(
                f"Adapter_{st_name}",
                (SourceAdapter,),
                {
                    "supported_source_type": lambda self, n=st_name: n,
                    "parse": lambda self, input_path, manifest=None: iter([]),
                },
            )()
            registry.register(adapter)

        with pytest.raises(KeyError) as exc_info:
            registry.get(unknown_type)

        error_msg = str(exc_info.value)
        for rt in registered_types:
            assert rt in error_msg, f"已注册类型 '{rt}' 未出现在错误信息中"
