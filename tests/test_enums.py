"""§21.7 / §15.8 纯计算契约测试。"""

from __future__ import annotations

from block_director.contracts.enums import (
    DeliveryPreset,
    Engine,
    ErrorCode,
    MessageRole,
    resolve_engine_identifier,
    resolution_for,
)


def test_engine_identifier_mapping_4x_vs_5x():
    assert resolve_engine_identifier(Engine.EEVEE, (4, 2, 0)) == "BLENDER_EEVEE_NEXT"
    assert resolve_engine_identifier(Engine.EEVEE, (4, 5, 3)) == "BLENDER_EEVEE_NEXT"
    assert resolve_engine_identifier(Engine.EEVEE, (5, 2, 0)) == "BLENDER_EEVEE"
    assert resolve_engine_identifier(Engine.WORKBENCH, (5, 2, 0)) == "BLENDER_WORKBENCH"
    assert resolve_engine_identifier(Engine.CYCLES, (5, 2, 0)) == "CYCLES"


def test_resolution_presets():
    assert resolution_for(DeliveryPreset.HD16X9) == (1280, 720)
    assert resolution_for(DeliveryPreset.FHD16X9) == (1920, 1080)
    assert resolution_for(DeliveryPreset.SQUARE) == (1024, 1024)
    assert resolution_for(DeliveryPreset.VERTICAL) == (720, 1280)


def test_strenum_stringifies_to_value():
    assert str(MessageRole.ASSISTANT) == "assistant"
    assert MessageRole("tool") is MessageRole.TOOL
    assert ErrorCode.AXIS_001.value == "E_AXIS_001"
