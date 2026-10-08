"""v1.6 卡 E1 / TDD §3.3：元素登记表 DTO 与纯构建器（FR-A2）。

关键判据：确定性（两跑逐字节相同）、by_id、serde 往返、first_shot 按镜序
扫描、登记表与 ``shots.json`` 的 ``elements_in_frame``（道具 + 环境件，
角色不混入）、角色颜色只读 cast 调色板分配。
"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.cast import DEFAULT_COLORS
from block_director.contracts.elements import (
    CHARACTER_SHAPE,
    ELEMENT_KINDS,
    Element,
    ElementRegistry,
    build_registry,
    shot_element_ids,
)
from block_director.contracts.plan import Plan
from block_director.delivery.manifest import build_manifest


def _plan() -> Plan:
    """三镜：shot_001 用银币 + 大门，shot_002 再用银币，shot_003 只用背景墙。"""
    return Plan.from_dict({
        "scene_heading": "INT. 码头 - 日",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立",
             "shot_type": "LS", "duration_frames": 48,
             "characters": ["char_001", "char_002"],
             "actions": [{"character_id": "char_001", "action_type": "pick_up",
                          "start_frame": 1, "end_frame": 48,
                          "params": {"prop": "prop_01"}}],
             "beats": [{"t": 0.5, "subject": "char_002", "verb": "walk_to",
                        "target": "大门"}]},
            {"shot_id": "shot_002", "order": 2, "intent": "反应",
             "shot_type": "CU", "duration_frames": 48,
             "characters": ["char_002"],
             "actions": [{"character_id": "char_002", "action_type": "place_prop",
                          "start_frame": 1, "end_frame": 48,
                          "params": {"prop": "prop_01"}}]},
            {"shot_id": "shot_003", "order": 3, "intent": "收尾",
             "shot_type": "MS", "duration_frames": 48,
             "characters": ["char_001"],
             "beats": [{"t": 0.5, "subject": "char_001", "verb": "walk_to",
                        "target": "背景墙"}]},
        ]})


PROPS = [{"id": "prop_01", "label": "银币", "color": "#C0A060",
          "shape": "sphere"}]
ENVIRONMENT = [{"label": "大门", "direction": "front"},
               {"id": "env_back_1", "label": "背景墙"}]
CAST = [{"id": "char_001", "name": "周野", "color": "#FF6B6B"},
        {"id": "char_002", "name": "林可", "color": "#6BC5FF"}]


def _registry() -> ElementRegistry:
    return build_registry(_plan(), cast=CAST, props=PROPS,
                          environment=ENVIRONMENT)


def test_element_kind_closed_set_and_character_shape_fixed():
    with pytest.raises(ValueError):
        Element(id="x", kind="vfx", label="x", color_hex="#000000")
    assert ELEMENT_KINDS == ("character", "prop", "environment")
    element = Element(id="c", kind="character", label="c", color_hex="#AABBCC",
                      shape="box")
    assert element.shape == CHARACTER_SHAPE == "capsule_q"
    assert element.to_dict()["shape"] == "capsule_q"


def test_by_id_maps_and_rejects_duplicate_ids():
    registry = _registry()
    by_id = registry.by_id()
    assert set(by_id) == {"char_001", "char_002", "prop_01",
                          "env_front_1", "env_back_1"}
    assert by_id["prop_01"].kind == "prop"
    duplicated = ElementRegistry(elements=[
        Element(id="dup", kind="prop", label="a", color_hex="#000000"),
        Element(id="dup", kind="prop", label="b", color_hex="#111111")])
    with pytest.raises(ValueError):
        duplicated.by_id()


def test_serde_round_trip_preserves_every_field():
    registry = _registry()
    payload = registry.to_dict()
    restored = ElementRegistry.from_dict(payload)
    #: 序列化契约是"按 id 排序的字典形"；内部列表顺序不参与往返判据。
    assert restored.by_id() == registry.by_id()
    assert restored.to_dict() == payload
    # JSON 往返（文件形态）也逐字段一致。
    assert ElementRegistry.from_dict(
        json.loads(json.dumps(payload, ensure_ascii=False))).to_dict() == payload


def test_to_dict_sorts_by_id_so_two_builds_are_byte_identical():
    first = json.dumps(_registry().to_dict(), ensure_ascii=False, indent=2)
    second = json.dumps(_registry().to_dict(), ensure_ascii=False, indent=2)
    assert first == second
    ids = [item["id"] for item in _registry().to_dict()["elements"]]
    assert ids == sorted(ids)
    # 乱序构造的登记表序列化后也必须按 id 归位。
    shuffled = ElementRegistry(elements=[
        Element(id="b", kind="prop", label="b", color_hex="#000000"),
        Element(id="a", kind="prop", label="a", color_hex="#111111")])
    assert [item["id"] for item in shuffled.to_dict()["elements"]] == ["a", "b"]


def test_first_shot_is_scanned_in_shot_order():
    by_id = _registry().by_id()
    assert by_id["char_001"].first_shot == "shot_001"
    assert by_id["char_002"].first_shot == "shot_001"
    assert by_id["prop_01"].first_shot == "shot_001"
    assert by_id["env_front_1"].first_shot == "shot_001"
    assert by_id["env_back_1"].first_shot == "shot_003"


def test_character_palette_fallback_matches_existing_allocation():
    """没有 cast 时按 DEFAULT_COLORS 首次出现顺序分配——与 SceneSpec.from_plan 同源。"""
    registry = build_registry(_plan(), props=PROPS, environment=ENVIRONMENT)
    by_id = registry.by_id()
    assert by_id["char_001"].color_hex == DEFAULT_COLORS[0]
    assert by_id["char_002"].color_hex == DEFAULT_COLORS[1]
    assert by_id["char_001"].label == "char_001"
    assert by_id["char_001"].shape == "capsule_q"


def test_cast_colors_and_names_are_read_not_rewritten():
    by_id = _registry().by_id()
    assert by_id["char_001"].color_hex == "#FF6B6B"
    assert by_id["char_002"].color_hex == "#6BC5FF"
    assert by_id["char_001"].label == "周野"
    assert by_id["char_002"].label == "林可"


def test_prop_and_environment_fields_are_registered():
    by_id = _registry().by_id()
    assert by_id["prop_01"].color_hex == "#C0A060"
    assert by_id["prop_01"].shape == "sphere"
    assert by_id["prop_01"].label == "银币"
    assert by_id["env_front_1"].color_hex == "#808080"
    assert by_id["env_front_1"].label == "大门"
    assert by_id["env_front_1"].shape == ""
    assert by_id["env_back_1"].label == "背景墙"


def test_float_colors_are_converted_and_missing_prop_color_is_the_model_grey():
    registry = build_registry(_plan(), props=[
        {"id": "p1", "color": (0.0, 0.5, 1.0)},
        {"id": "p2"}])
    by_id = registry.by_id()
    assert by_id["p1"].color_hex == "#0080FF"
    # 只读复制 scene_executor.DEFAULT_PROP_COLOR (0.7, 0.66, 0.6)。
    assert by_id["p2"].color_hex == "#B2A899"
    assert by_id["p2"].label == "p2"


def test_elements_in_frame_is_props_plus_environment_without_characters():
    registry = _registry()
    assert shot_element_ids(_plan().shots[0], registry) == \
        ["prop_01", "env_front_1"]
    assert shot_element_ids(_plan().shots[1], registry) == ["prop_01"]
    assert shot_element_ids(_plan().shots[2], registry) == ["env_back_1"]


def test_shots_json_carries_per_shot_elements_in_frame():
    manifest = build_manifest(_plan(), generated_at="t", registry=_registry())
    assert [shot["elements_in_frame"] for shot in manifest["shots"]] == \
        [["prop_01", "env_front_1"], ["prop_01"], ["env_back_1"]]
    assert manifest["shots"][0]["characters"] == ["char_001", "char_002"]
    # 无登记表（旧调用方）：字段仍在，只是没有可登记的成员。
    legacy = build_manifest(_plan(), generated_at="t")
    assert all(shot["elements_in_frame"] == []
               for shot in legacy["shots"])


def test_builder_refuses_malformed_props_instead_of_skipping():
    with pytest.raises(ValueError):
        build_registry(_plan(), props=[{"label": "缺 id"}])
    with pytest.raises(ValueError):
        build_registry(_plan(), props=["not-a-dict"])


def test_empty_plan_and_empty_inputs_give_empty_registry():
    empty = build_registry(Plan.from_dict({"shots": []}))
    assert empty.elements == [] and empty.to_dict() == {"elements": []}
