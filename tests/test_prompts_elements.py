"""v1.6 卡 E1 / FR-A4：prompts.md 的"元素表"头 + 表外名字对拍。

同源纪律：表头与逐镜"元素"行都从同一份 ElementRegistry 渲染（稳定 token），
引用表外名字判 error（交付装配点据此拒绝导出）。
"""

from __future__ import annotations

from block_director.contracts.elements import (
    Element,
    ElementRegistry,
    build_registry,
)
from block_director.contracts.plan import Plan
from block_director.delivery.prompts import (
    render_element_table,
    render_prompt_sheet,
    unknown_prompt_names,
)


def _plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "INT. 码头 - 日",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立",
             "shot_type": "LS", "duration_frames": 48,
             "characters": ["char_001", "char_002"],
             "actions": [{"character_id": "char_001", "action_type": "pick_up",
                          "start_frame": 1, "end_frame": 48,
                          "params": {"prop": "prop_01"}}]},
            {"shot_id": "shot_002", "order": 2, "intent": "反应",
             "shot_type": "CU", "duration_frames": 48,
             "characters": ["char_002"]},
        ]})


def _registry() -> ElementRegistry:
    return build_registry(
        _plan(),
        cast=[{"id": "char_001", "name": "周野", "color": "#FF6B6B"},
              {"id": "char_002", "name": "林可", "color": "#6BC5FF"}],
        props=[{"id": "prop_01", "label": "银币", "color": "#C0A060",
                "shape": "sphere"}],
        environment=[{"label": "大门", "direction": "front"}])


def test_registry_none_keeps_legacy_output_byte_identical():
    """不传登记表 = 旧输出；表头与元素行都不出现。"""
    text = render_prompt_sheet(_plan())
    assert "元素表" not in text
    assert "**元素**" not in text


def test_header_table_renders_every_registered_element():
    text = render_prompt_sheet(_plan(), registry=_registry())
    assert text.count("## 元素表") == 1
    for token in ("char_001", "周野", "#FF6B6B", "capsule_q", "shot_001",
                  "prop_01", "银币", "#C0A060", "sphere",
                  "env_front_1", "大门", "#808080"):
        assert token in text, token


def test_per_shot_element_line_uses_registry_labels():
    text = render_prompt_sheet(_plan(), registry=_registry())
    assert "**元素**：银币" in text
    # shot_002 没引用道具/环境件：不出现空的元素行。
    assert text.count("**元素**") == 1


def test_element_table_empty_registry_renders_nothing():
    assert render_element_table(ElementRegistry()) == ""


def test_out_of_registry_name_is_reported():
    plan = _plan()
    plan.shots[0].characters = ["char_001", "char_mystery"]
    registry = _registry()
    text = render_prompt_sheet(plan, registry=registry)
    assert unknown_prompt_names(text, registry) == ["char_mystery"]


def test_in_registry_names_pass_and_duplicates_are_deduplicated():
    plan = _plan()
    text = render_prompt_sheet(plan, registry=_registry())
    assert unknown_prompt_names(text, _registry()) == []
    # 同名引用两次也只报一次，且报错顺序稳定（字典序）。
    assert unknown_prompt_names(
        "**出场角色**：b、a\n**出场角色**：b", _registry()) == ["a", "b"]


def test_free_text_prompt_is_not_nlp_scanned_but_structured_lines_are():
    """对拍只读结构化引用行：Prompt 自由文本不做 NLP 推断（机制如实声明）。"""
    text = render_prompt_sheet(_plan(), registry=_registry())
    assert unknown_prompt_names(text, _registry()) == []
    poisoned = text + "\n**出场角色**：char_ghost"
    assert unknown_prompt_names(poisoned, _registry()) == ["char_ghost"]


def test_registry_names_are_matched_by_id_or_label():
    registry = ElementRegistry(elements=[
        Element(id="e1", kind="environment", label="大门", color_hex="#808080")])
    assert unknown_prompt_names("**元素**：大门", registry) == []
    assert unknown_prompt_names("**元素**：e1", registry) == []
    assert unknown_prompt_names("**元素**：别的门", registry) == ["别的门"]
