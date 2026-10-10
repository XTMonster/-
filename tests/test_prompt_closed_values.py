"""G8-PA（dispatch-key: g8pa_closed_values）：闭集字段的合法取值必须由常量渲染进提示。

现场：r3（run_id 39af4e810b95）两次 ``plan_invalid``——``environment.light`` 的
``time_of_day/mood/key_direction`` 被写成中文句子、``intent_type`` 被写成带字段名
前缀的值；r2 的 ``emit_shot_draft`` 把 ``composition.rule/subject_position``、
``beats[].pace/face_to/curve`` 写成 schema 外的值。根因已核：DeepSeek beta 的
``strict`` 是尽力而为、不是约束解码，schema 挡不住的地方要由提示把取值**逐字列出**。

本文件钉三件事：
① 计划/草案/修复/精修四个提示都渲染全部合法值，且渲染出的列表与常量**逐字相等**；
② 四个提示里都不出现 `intent:` 前缀示例；
③ 常量漂移（monkeypatch）时提示跟着变（单一真源，不是抄的第二份）。

红线：schema / enums / validator / threshold 一个字不动，只动提示渲染。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.audit import AuditError, AuditResult  # noqa: E402
from block_director.contracts.beats import (  # noqa: E402
    COMPOSITION_RULES,
    FACE_TO_VALUES,
    KEY_DIRECTION_VALUES,
    LIGHT_MOOD_VALUES,
    PACE_VALUES,
    SUBJECT_POSITIONS,
    TIME_OF_DAY_VALUES,
)
from block_director.contracts.enums import ShotType  # noqa: E402
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.contracts.rhythm import CURVE_VALUES  # noqa: E402
from block_director.knowledge.hypergraph import VALUE_DOMAINS  # noqa: E402
from block_director.layer5_orchestrator import editor as E  # noqa: E402
from block_director.layer5_orchestrator import planner as P  # noqa: E402
from block_director.layer5_orchestrator import react as REA  # noqa: E402
from block_director.layer5_orchestrator import repair as REP  # noqa: E402
from block_director.layer5_orchestrator.driver import default_registry  # noqa: E402

INTENT_VALUES = tuple(VALUE_DOMAINS["intent"])

PLAN_FIELDS = (
    ("intent_type", INTENT_VALUES),
    ("environment.light.time_of_day", TIME_OF_DAY_VALUES),
    ("environment.light.mood", LIGHT_MOOD_VALUES),
    ("environment.light.key_direction", KEY_DIRECTION_VALUES),
)

SHOT_FIELDS = (
    ("composition.rule", COMPOSITION_RULES),
    ("composition.subject_position", SUBJECT_POSITIONS),
    ("beats[].pace", PACE_VALUES),
    ("beats[].face_to", FACE_TO_VALUES),
    ("beats[].curve", CURVE_VALUES),
)


def _line_with(block: str, field: str) -> str:
    return next(line for line in block.splitlines()
                if f"`{field}`" in line)


def _value_list(line: str) -> str:
    """取闭集行冒号之后的取值段（去掉行尾括注，如 face_to 的"角色 id 也合法"）。"""
    return line.split("：", 1)[1].split("（", 1)[0].strip()


def _shot() -> ShotPlan:
    return ShotPlan(shot_id="shot_001", intent="推进",
                    shot_type=ShotType.MS, duration_frames=48,
                    characters=["char_001"])


def _audit() -> AuditResult:
    return AuditResult(passed=False, target="shot_001", errors=[
        AuditError(rule="R001", code="E_AXIS_001", message="越轴",
                   target="shot_001")])


# --------------------------------------------------------------------------- #
# ① 每个字段的渲染列表与常量逐字相等，且每个值都出现在四个提示里
# --------------------------------------------------------------------------- #
def test_plan_renderer_lists_each_field_exactly_equal_to_its_constant():
    block = P.render_plan_closed_sets()
    for field, values in PLAN_FIELDS:
        line = _line_with(block, field)
        assert _value_list(line) == "、".join(f"`{v}`" for v in values), \
            (field, line)


def test_shot_renderer_lists_each_field_exactly_equal_to_its_constant():
    block = E.render_closed_sets()
    for field, values in SHOT_FIELDS:
        line = _line_with(block, field)
        assert _value_list(line) == "、".join(f"`{v}`" for v in values), \
            (field, line)


def test_the_plan_prompt_renders_every_closed_set_value():
    system = P.build_plan_payload("INT. 房间 - 日", None).messages[0].content
    assert "{closed_sets}" not in system
    assert P.render_plan_closed_sets() in system
    for _, values in PLAN_FIELDS:
        for value in values:
            assert f"`{value}`" in system, value
    #: 描述性灯光写法必须被指向既有自由文本字段（schema 没有灯光专用自由文本，
    #: 本轮不新增 schema 字段——见 planner.render_plan_closed_sets 的说明）。
    assert "描述性的灯光写法" in system and "`prompt`" in system


def test_the_editor_prompt_renders_every_closed_set_value():
    shot = _shot()
    system = E.build_editor_payload(shot, Plan(shots=[shot])).messages[0].content
    assert "{closed_sets}" not in system
    assert E.render_closed_sets() in system
    for _, values in SHOT_FIELDS:
        for value in values:
            assert f"`{value}`" in system, value


def test_the_repair_prompt_renders_every_closed_set_value_and_action_keys():
    system = REP.build_repair_payload(
        _audit(), default_registry(), shot_id="shot_001",
        roster=["char_001"]).messages[0].content
    assert "{closed_sets}" not in system
    assert E.render_closed_sets() in system
    for _, values in SHOT_FIELDS:
        for value in values:
            assert f"`{value}`" in system, value
    #: 动作参数表必须与编辑器同一份（重提草案最常见的动作就是它）。
    assert E.render_action_params() in system


def test_the_react_prompt_renders_every_closed_set_value_and_action_keys():
    shot = _shot()
    system = REA.build_react_payload(
        shot, _audit(), registry=default_registry()).messages[0].content
    assert "{closed_sets}" not in system
    assert "{action_params}" not in system
    assert E.render_closed_sets() in system
    for _, values in SHOT_FIELDS:
        for value in values:
            assert f"`{value}`" in system, value
    #: r2 里 ReAct 重提草案也会写错表外键——与编辑器共用同一张参数表。
    assert E.render_action_params() in system


# --------------------------------------------------------------------------- #
# ② 提示里不得出现 `intent:` 前缀示例（r3 的真实现场值）
# --------------------------------------------------------------------------- #
def test_no_intent_prefix_example_appears_in_any_prompt():
    shot = _shot()
    prompts = [
        P.build_plan_payload("INT. 房间 - 日", None).messages[0].content,
        E.build_editor_payload(shot, Plan(shots=[shot])).messages[0].content,
        REP.build_repair_payload(
            _audit(), default_registry(), shot_id="shot_001"
        ).messages[0].content,
        REA.build_react_payload(
            shot, _audit(), registry=default_registry()).messages[0].content,
    ]
    for prompt in prompts:
        assert "intent:" not in prompt
        assert "intent:留白" not in prompt


# --------------------------------------------------------------------------- #
# ③ 漂移测试：常量变了，提示跟着变（同一份真源，不是抄的第二份）
# --------------------------------------------------------------------------- #
def test_the_plan_prompt_follows_an_extended_intent_constant(monkeypatch):
    monkeypatch.setattr(P, "INTENT_VALUES", tuple(INTENT_VALUES) + ("新意图",))
    assert "`新意图`" in P.render_plan_closed_sets()
    system = P.build_plan_payload("INT. 房间 - 日", None).messages[0].content
    assert "`新意图`" in system


def test_the_shot_prompts_follow_an_extended_composition_constant(monkeypatch):
    monkeypatch.setattr(
        E, "COMPOSITION_RULES", tuple(COMPOSITION_RULES) + ("new_rule",))
    assert "`new_rule`" in E.render_closed_sets()
    shot = _shot()
    editor_system = E.build_editor_payload(
        shot, Plan(shots=[shot])).messages[0].content
    repair_system = REP.build_repair_payload(
        _audit(), default_registry(), shot_id="shot_001"
    ).messages[0].content
    react_system = REA.build_react_payload(
        shot, _audit(), registry=default_registry()).messages[0].content
    for system in (editor_system, repair_system, react_system):
        assert "`new_rule`" in system
