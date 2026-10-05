"""P8：把 LightRAG 适配器**注册进路由表**，且**默认关**（环境变量门控）。

为什么默认关：产品现行的默认路径是 `hybrid`（BM25）。LightRAG 那条路要用 sidecar，
而 sidecar 不是永远开着——所以注册必须**显式打开**，否则一次误启就让默认检索依赖
一个可能不在的服务。

两条纪律：

* **默认关**：环境变量不设／为假 ⇒ 一个工厂都不注册，行为与今天逐字一致；
* **注册的是工厂**（`(index_dir) -> adapter`），不是已建好的适配器——契约要求惰性构造，
  别在 import 期就去连 sidecar。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import cases as kb_cases  # noqa: E402
from block_director.knowledge import lightrag_adapter as la  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_registry():
    kb_cases.reset_lightrag_adapters()
    yield
    kb_cases.reset_lightrag_adapters()


def test_it_registers_nothing_by_default(monkeypatch):
    monkeypatch.delenv(la.ENABLE_ENV, raising=False)
    assert la.register_if_enabled() is False
    assert kb_cases._ADAPTER_FACTORIES == []


def test_a_falsey_value_keeps_it_off(monkeypatch):
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv(la.ENABLE_ENV, value)
        assert la.register_if_enabled() is False, value
        assert kb_cases._ADAPTER_FACTORIES == [], value


def test_an_explicit_on_registers_the_factory_not_an_instance(monkeypatch):
    monkeypatch.setenv(la.ENABLE_ENV, "1")
    assert la.register_if_enabled() is True
    assert len(kb_cases._ADAPTER_FACTORIES) == 1
    factory = kb_cases._ADAPTER_FACTORIES[0]
    assert callable(factory)
    adapter = factory(pathlib.Path("."))
    assert isinstance(adapter, la.LightRAGAdapter)


def test_registering_twice_does_not_duplicate(monkeypatch):
    monkeypatch.setenv(la.ENABLE_ENV, "1")
    assert la.register_if_enabled() is True
    assert la.register_if_enabled() is True
    assert len(kb_cases._ADAPTER_FACTORIES) == 1
