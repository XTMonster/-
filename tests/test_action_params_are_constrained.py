"""计划/草案里的动作参数**必须受约束**——实测代价是整轮真实运行白跑。

2026-10-02 的一次真实模型运行（`docs/evidence/market4/` 之前那一次）：

```
MotionParamError: E_MOTION_001：body_tilt 不认识的姿态参数：amount；
允许的键是 angle_deg、angle、degrees、axis、toward
```

模型在草案里写了 `"action_type": "body_tilt", "params": {"amount": 15}`。
动作层**刻意**不静默取默认值（v1.4 BW-1）并在构建期报错——它是对的；
错在**上游放行**：`emit_shot_draft` 的 schema 把 `params` 声明成自由形状
（`{"type": "object"}`），于是这个拼写错误一路走到构建期，9 次调用、6 个镜头
全部白跑（终态 `ERROR`）。

现在键表在 `motion/model.py`（单一真源），schema 与校验都从它渲染：
**任何动作都不认识的键**在解析期就被 `tool_schema.validate_args` 挡住，
**这个动作不认识的键**在 `extract_draft` 里抛 `ValueError`（驱动器记
`draft_invalid` 并重试）。两层都不允许它走到构建期。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator import editor as ED  # noqa: E402
from block_director.layer5_orchestrator import tool_schema as TS  # noqa: E402
from block_director.motion import model as MM  # noqa: E402


def test_the_key_table_covers_every_action_type():
    """**完整性**：每个合法动作都要有键表，别漏一个（漏了就等于放行自由形状）。"""
    for kind in MM.ACTION_TYPES:
        assert kind in MM.ACTION_PARAMS, kind
        assert MM.ACTION_PARAMS[kind], kind


def test_draft_target_position_accepts_the_execution_domain():
    """``target_position`` 的 schema 与执行层同域：2D/3D 都合法，1 项/4 项拒绝。

    v4 真跑里模型写 2 项数组被 schema 判无效（minItems=3），而纯运动层明明收
    2–3 项——"执行接受、解析拒绝"的假 invalid 又一种。对齐到 2–3，不越界。
    """
    schema = ED.EMIT_SHOT_DRAFT_PARAMETERS
    action = {"character_id": "char_001", "action_type": "walk_to",
              "start_frame": 1, "end_frame": 24,
              "target_position": [1.0, 0.0]}
    draft = {"shot_id": "shot_006", "actions": [action]}
    assert TS.validate_args(schema, draft) == []
    action["target_position"] = [1.0, 0.0, 0.0]
    assert TS.validate_args(schema, draft) == []
    action["target_position"] = [1.0]
    assert TS.validate_args(schema, draft)
    action["target_position"] = [1.0, 0.0, 0.0, 0.0]
    assert TS.validate_args(schema, draft)
    # 纯运动层同域：2D 合法（测试不两边不一致地各自通过）。
    assert MM.action_param_problems(
        "walk_to", {"target_position": [1.0, 0.0]}) == []


def test_the_reported_defect_is_now_rejected_by_the_schema():
    """**复现原始故障**：`body_tilt` + `{"amount": 15}` 必须在解析期被挡。"""
    schema = ED.EMIT_SHOT_DRAFT_PARAMETERS
    draft = {"shot_id": "shot_006",
             "actions": [{"character_id": "char_001", "action_type": "body_tilt",
                          "start_frame": 80, "end_frame": 120,
                          "params": {"amount": 15}}]}
    problems = TS.validate_args(schema, draft)
    assert problems, "自由形状的 params 会把这个拼写错误放行到构建期"
    assert any("amount" in item for item in problems)
    # 正对照：合法参数键照常放行（别把校验做成"什么都拒"）。
    ok = {"shot_id": "shot_006",
          "actions": [{"character_id": "char_001", "action_type": "body_tilt",
                       "start_frame": 80, "end_frame": 120,
                       "params": {"angle_deg": 15, "axis": "x"}}]}
    assert TS.validate_args(schema, ok) == []


def test_a_key_that_another_action_uses_is_caught_exactly():
    """schema 只能挡"谁都不认识的键"；**逐动作**的精确检查在 `extract_draft`。

    `cycles` 是 `nod` 的合法键，但 `body_tilt` 不认识它——这种错必须也被抓住，
    否则它同样会在构建期炸掉。
    """
    assert MM.unknown_action_params("body_tilt", {"cycles": 2}) == ["cycles"]
    assert MM.unknown_action_params("nod", {"cycles": 2}) == []
    assert MM.unknown_action_params("walk_to", {"target_position": [0, 0, 1]}) == []
    # 未知动作类型不在表里：unknown_action_params 的契约仍是返回空——但
    # "动作类型本身是否合法"现在由 extract_draft 显式拒绝（r4 真跑
    # finger_snap 实证：上游 strict 是尽力而为，schema 的 enum 挡不住）。
    assert MM.unknown_action_params("no_such_action", {"whatever": 1}) == []


def test_extract_draft_refuses_a_bad_param_key_before_the_build():
    """**端到端的落点**：`extract_draft` 必须当场抛错（驱动器记 `draft_invalid`
    并重试），而不是把这个草案放行到场景构建期。

    这里复现的正是真实运行里那一条：`body_tilt` + `{"amount": 15}`。
    """
    import json

    from block_director.contracts.transport import ChatReply, FunctionCall, ToolCall

    def _reply(args):
        return ChatReply(tool_calls=[ToolCall(
            id="c1", function=FunctionCall(name="emit_shot_draft",
                                           arguments=json.dumps(args,
                                                                ensure_ascii=False)))])

    bad = {"shot_id": "shot_006",
           "actions": [{"character_id": "char_001", "action_type": "body_tilt",
                        "start_frame": 80, "end_frame": 120,
                        "params": {"amount": 15}}]}
    with pytest.raises(ValueError) as excinfo:
        ED.extract_draft(_reply(bad), "shot_006")
    assert "amount" in str(excinfo.value)

    # 正对照：合法参数的草案照常解析出来（别把路堵死）。
    good = {"shot_id": "shot_006",
            "actions": [{"character_id": "char_001", "action_type": "body_tilt",
                         "start_frame": 80, "end_frame": 120,
                         "params": {"angle_deg": 15}}]}
    draft = ED.extract_draft(_reply(good), "shot_006")
    assert draft.actions[0]["params"] == {"angle_deg": 15}


def test_extract_draft_refuses_an_unknown_action_type_before_the_build():
    """r4 真跑（run f9fedb5c133c）：模型输出 schema 外的
    ``action_type: finger_snap``，B1 解析层没有 kind 闭集守卫，放行进计划，
    构建期抛"未知动作类型"把 13 镜整轮打成 ERROR。必须在这里拦住。
    """
    import json

    from block_director.contracts.transport import ChatReply, FunctionCall, ToolCall

    def _reply(args):
        return ChatReply(tool_calls=[ToolCall(
            id="c1", function=FunctionCall(
                name="emit_shot_draft",
                arguments=json.dumps(args, ensure_ascii=False)))])

    bad = {"shot_id": "shot_001",
           "actions": [{"character_id": "char_001",
                        "action_type": "finger_snap",
                        "start_frame": 0, "end_frame": 30,
                        "params": {}}]}
    with pytest.raises(ValueError) as excinfo:
        ED.extract_draft(_reply(bad), "shot_001")
    assert "不在动作类型闭集内" in str(excinfo.value)
    assert "finger_snap" in str(excinfo.value)

    # 正对照：合法动作类型照常解析（别把路堵死）。
    good = {"shot_id": "shot_001",
            "actions": [{"character_id": "char_001",
                         "action_type": "walk_to",
                         "start_frame": 0, "end_frame": 30,
                         "params": {"speed": "walk"}}]}
    draft = ED.extract_draft(_reply(good), "shot_001")
    assert draft.actions[0]["action_type"] == "walk_to"


def test_extract_draft_refuses_a_non_object_action_item():
    """非对象动作条目在解析期抛确定性 ``ValueError``（驱动器记
    `draft_invalid`），而不是以 TypeError 逃逸 `except ValueError` 打死整轮。
    """
    import json

    from block_director.contracts.transport import ChatReply, FunctionCall, ToolCall

    def _reply(args):
        return ChatReply(tool_calls=[ToolCall(
            id="c1", function=FunctionCall(
                name="emit_shot_draft",
                arguments=json.dumps(args, ensure_ascii=False)))])

    for bad_item in ("finger_snap", 5):
        bad = {"shot_id": "shot_001",
               "actions": [{"character_id": "char_001",
                            "action_type": "walk_to",
                            "start_frame": 0, "end_frame": 30,
                            "params": {}},
                           bad_item]}
        with pytest.raises(ValueError) as excinfo:
            ED.extract_draft(_reply(bad), "shot_001")
        assert "类型应为对象" in str(excinfo.value)
