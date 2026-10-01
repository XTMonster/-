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
    # 未知动作类型不在表里：返回空（不在这里判"动作类型是否合法"，
    # 那是 schema 的 enum 干的活）。
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
