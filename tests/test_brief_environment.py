"""v1.6 C1（FR-A1）：SceneBrief.environment 闭集契约与 Stage S schema。"""

from __future__ import annotations

from block_director.contracts.brief import (
    ENVIRONMENT_KEYS,
    SPACE_DIRECTIONS,
    SPACE_DISTANCES,
    SPACE_SIZES,
    SceneBrief,
)
from block_director.layer1_input import parse_text
from block_director.layer5_orchestrator.tool_schema import validate_args
from block_director.layer5_orchestrator.understand import (
    EMIT_BRIEF_TOOL_PARAMETERS,
    deterministic_brief,
    render_brief_block,
)


def _entry(**overrides):
    entry = {"label": "拱廊拱顶", "direction": "above", "distance": "near",
             "size": "l", "mood": "蓝绿色铸钢雕花铁艺"}
    entry.update(overrides)
    return entry


# --------------------------------------------------------------------------- #
# 闭集常量
# --------------------------------------------------------------------------- #
def test_closed_sets_are_exactly_the_spec_values():
    assert SPACE_DIRECTIONS == ("front", "back", "left", "right", "above",
                                "ground")
    assert SPACE_DISTANCES == ("near", "mid", "far")
    assert SPACE_SIZES == ("s", "m", "l")
    assert ENVIRONMENT_KEYS == ("label", "direction", "distance", "size",
                                "mood")


# --------------------------------------------------------------------------- #
# 校验：闭集外只报问题，绝不猜
# --------------------------------------------------------------------------- #
def test_valid_environment_validates_clean():
    brief = SceneBrief.from_dict({"environment": [_entry()]})
    assert brief.validate() == []


def test_each_invalid_closed_field_is_reported():
    for key, value in (("direction", "画面后方"), ("distance", "遥远"),
                       ("size", "xl")):
        brief = SceneBrief.from_dict({"environment": [_entry(**{key: value})]})
        problems = brief.validate()
        assert any(f"environment[1].{key}" in problem
                   and repr(value) in problem for problem in problems), \
            (key, problems)


def test_missing_required_fields_are_reported_and_never_filled_in():
    brief = SceneBrief.from_dict({"environment": [{"label": "拱廊拱顶"}]})
    problems = brief.validate()
    assert any("environment[1] 缺少字段" in problem for problem in problems)
    # 只报告、不猜：条目保持原样，没有补值
    assert brief.environment[0].get("direction") is None
    assert brief.environment[0].get("distance") is None
    assert brief.environment[0].get("size") is None


def test_mood_is_free_text_and_never_validated():
    for mood in ("", "蓝绿色铸钢雕花铁艺", "潮湿、有海腥味，丁达尔光"):
        brief = SceneBrief.from_dict({"environment": [_entry(mood=mood)]})
        assert not any("mood" in problem for problem in brief.validate()), mood


# --------------------------------------------------------------------------- #
# serde 容错与往返
# --------------------------------------------------------------------------- #
def test_serde_round_trip_preserves_environment():
    brief = SceneBrief.from_dict({"environment": [_entry()]})
    assert SceneBrief.from_dict(brief.to_dict()) == brief


def test_from_dict_drops_non_dict_entries():
    brief = SceneBrief.from_dict(
        {"environment": [_entry(), "垃圾", None, 3]})
    assert brief.environment == [_entry()]


def test_a_brief_with_only_environment_is_not_empty_and_is_rendered():
    brief = SceneBrief.from_dict({"environment": [_entry()]})
    assert not brief.is_empty
    block = render_brief_block(brief)
    assert "环境：拱廊拱顶" in block
    assert "above / near / l" in block
    assert "蓝绿色铸钢雕花铁艺" in block


# --------------------------------------------------------------------------- #
# Stage S schema：enum 与闭集元组同源（不抄第二份）
# --------------------------------------------------------------------------- #
def _env_props():
    return EMIT_BRIEF_TOOL_PARAMETERS["properties"]["environment"]["items"][
        "properties"]


def test_schema_enums_import_the_same_tuples():
    props = _env_props()
    assert props["direction"]["enum"] == list(SPACE_DIRECTIONS)
    assert props["distance"]["enum"] == list(SPACE_DISTANCES)
    assert props["size"]["enum"] == list(SPACE_SIZES)
    assert "enum" not in props["mood"]            # mood 是自由文本


def test_schema_requires_the_closed_set_fields():
    items = EMIT_BRIEF_TOOL_PARAMETERS["properties"]["environment"]["items"]
    assert items["required"] == ["label", "direction", "distance", "size"]
    assert items["additionalProperties"] is False


def test_schema_accepts_a_valid_entry_and_rejects_out_of_set():
    assert validate_args(EMIT_BRIEF_TOOL_PARAMETERS,
                         {"environment": [_entry()]}) == []
    for key, value in (("direction", "画面后方"), ("distance", "遥远"),
                       ("size", "xl")):
        problems = validate_args(
            EMIT_BRIEF_TOOL_PARAMETERS,
            {"environment": [_entry(**{key: value})]})
        assert problems, (key, problems)


# --------------------------------------------------------------------------- #
# 确定性降级：environment 留空 + 说明，绝不编造
# --------------------------------------------------------------------------- #
def test_deterministic_brief_without_a_script_leaves_environment_empty():
    brief = deterministic_brief(None, ["米迦尔", "伊恩"])
    assert brief.environment == []
    assert any("environment 留空" in note for note in brief.notes)


def test_deterministic_brief_with_a_shotlist_leaves_environment_empty():
    parsed = parse_text(
        "节点1：码头\n镜号：1\n拍摄距离：中景\n角色：米迦尔、伊恩\n"
        "预估时长：4秒\n米迦尔：\"交给我吧。\"\n伊恩：\"小心一点。\"",
        title="码头")
    brief = deterministic_brief(parsed, ["米迦尔", "伊恩"])
    assert brief.environment == []
    assert any("environment 留空" in note for note in brief.notes)
