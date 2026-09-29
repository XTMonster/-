"""顶层包契约：导出面稳定 + 不依赖 bpy（可在 Blender 内外通用）。"""

from __future__ import annotations

import sys


def test_contracts_import_from_top_level():
    from block_director import contracts

    for name in ("AppConfig", "ChatPayload", "LLMTransport", "Card",
                 "HealthStatus", "ErrorCode", "Purpose"):
        assert hasattr(contracts, name), f"contracts 缺少导出: {name}"


def test_contracts_do_not_import_bpy():
    """契约层必须与 Blender 解耦（§2.4 设计红线）。"""
    import block_director.contracts  # noqa: F401  确保已加载

    assert "bpy" not in sys.modules, "契约层不得引入 bpy"


def test_version_is_consistent_with_contract():
    import block_director

    assert block_director.__version__ == block_director.CONTRACT_VERSION
    assert block_director.__version__ == "1.3.0"
