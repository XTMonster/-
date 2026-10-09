"""动作参数的**取值**也必须在解析期查（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long2/`）：把动作
参数表写进提示词之后，草案从 **2 条有效变成 61 条有效**——然后整轮死在构建期：

    MotionParamError: E_MOTION_001：body_tilt 的 axis 只能是 x / y（当前 'forward'）

`axis` 是闭集、`angle_deg` 必须是数字，这些**在解析期就能问**。留到构建期的代价
不是"这一镜少一个动作"，而是**整轮 ERROR**：64 镜的计划与 64 条草案一起作废。
这与本项目已经付过两次代价的"键不认识"完全同一个形状（见
`tests/test_action_params_are_constrained.py` 的抬头）。

判据与构建期**同源**：`body_tilt` 直接调它自己的正规化函数，`speed` 直接读构建期
用的 `_SPEED_RATE`。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator import editor as E  # noqa: E402
from block_director.motion import model as M  # noqa: E402


def test_closed_value_keys_are_rejected_at_parse_time():
    assert M.action_param_problems("body_tilt", {"axis": "forward"})
    assert M.action_param_problems("body_tilt", {"axis": "x"}) == []
    assert M.action_param_problems("body_tilt", {"toward": "left"}) == []
    assert M.action_param_problems("body_tilt", {"toward": "左上"})   # 无法理解
    assert M.action_param_problems("walk_to", {"speed": "sprint"})
    assert M.action_param_problems("walk_to", {"speed": "run"}) == []
    #: 未知键仍然优先报"键不认识"（不把两件事混成一条）。
    problems = M.action_param_problems("nod", {"cycles": 2, "degrees": 10})
    assert any("不认识的参数" in item for item in problems)


def test_non_numeric_values_are_rejected_at_parse_time():
    assert M.action_param_problems("nod", {"cycles": "两下"})
    assert M.action_param_problems("stand", {"drop": "30cm"})
    assert M.action_param_problems("stand", {"drop": 0.2}) == []
    #: 坐标（数组）与自由字符串不受数值检查影响。
    assert M.action_param_problems("walk_to", {"target_position": [0, 0, 1]}) == []
    assert M.action_param_problems("walk_to", {"to": [1, 0, 0]}) == []


def test_coordinate_keys_are_rejected_when_they_are_not_coordinates():
    """2026-10-07 实测（长剧本那一跑）：`enter_from.from = 'screen_left'` 一路走到构建期，

        ValueError: could not convert string to float: 's'

    整轮 64 镜一起 ERROR（`docs/evidence/20261007-v15-long/` 的 `blender.log` 里有
    完整 traceback：`motion/model.py::_walk_root` → `float(source[0])`）。坐标**不是**
    自由文本，所以这条必须在解析期挡下来——判据与构建期同源（`[x, y]` / `[x, y, z]`）。
    """
    assert M.coordinate_problems("enter_from", "from", "screen_left")
    assert M.action_param_problems(
        "enter_from", {"from": "screen_left", "to": [1.0, 0.0, 0.0]})
    #: 长度不对 / 分量不是数字，同样在解析期挡。
    assert M.action_param_problems("walk_to", {"target_position": [1]})
    assert M.action_param_problems("walk_to", {"to": ["s", 0, 0]})
    assert M.action_param_problems("walk_to", {"from": 3})
    #: 合法形状一个都不许误伤（二维与三维都收）。
    assert M.action_param_problems("walk_to", {"from": [0, 0], "to": [1, 0]}) == []
    assert M.action_param_problems("walk_to", {"from": [0, 0, 0]}) == []
    assert M.action_param_problems("walk_to", {"from_": [0.5, -1.5, 2.0]}) == []
    #: 自由字符串的键（`prop`）照旧不查坐标。
    assert M.action_param_problems("hand_to", {"prop": "钱袋"}) == []


def test_prop_toward_is_validated_with_the_execution_domain():
    """prop 类 ``toward`` 的判据必须与构建期同源（`_axis_from_toward`）。

    v3 真跑里 GLM 写的方向词（toward='left'）在**执行层合法**，却在此前的
    "必须是数字"分支被误拒 ⇒ 产生假 draft_invalid。修法不是放宽，而是让解析
    期与执行期用同一个函数判域：合法的放行，仍然非法的照旧拒。
    """
    assert M.action_param_problems(
        "hand_to", {"prop": "钱袋", "toward": "left"}) == []
    assert M.action_param_problems(
        "place_prop", {"prop": "箱子", "toward": [1.0, 0.0, 0.0]}) == []
    assert M.action_param_problems(
        "pick_up", {"prop": "钱袋", "toward": "side"}) == []
    # 执行层无法理解的值仍然拒绝（`camera` 不是方向词闭集成员）。
    assert M.action_param_problems(
        "hand_to", {"prop": "钱袋", "toward": "camera"})
    assert M.action_param_problems(
        "hand_to", {"prop": "钱袋", "toward": 3})


def test_the_draft_extractor_rejects_a_string_coordinate():
    """`extract_draft` 必须在解析期挡住它——构建期整轮 ERROR 的代价见上一条。"""
    from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall

    args = {"shot_id": "shot_041", "shot_type": "MS",
            "actions": [{"character_id": "char_001", "action_type": "enter_from",
                         "start_frame": 1, "end_frame": 24,
                         "params": {"from": "screen_left",
                                    "to": [6.4, -6.6, 4.5]}}],
            "dialogues": [], "camera": {}, "gaze": [], "vfx": [], "prompt": ""}
    call = ToolCall(id="c1", function=FunctionCall(name=E.EDITOR_TOOL_NAME,
                                                   arguments=_json(args)))
    reply = ChatReply(content=None, tool_calls=[call])
    with pytest.raises(ValueError) as excinfo:
        E.extract_draft(reply, "shot_041")
    assert "from" in str(excinfo.value)


def test_the_draft_extractor_reports_values_not_just_keys():
    """`extract_draft` 必须把这条挡在解析期（否则构建期整轮 ERROR）。"""
    from block_director.contracts.enums import MessageRole, ToolChoice
    from block_director.contracts.messages import (
        ChatReply,
        FunctionCall,
        Message,
        ToolCall,
    )

    args = {"shot_id": "shot_001", "shot_type": "MS",
            "actions": [{"character_id": "char_001", "action_type": "body_tilt",
                         "start_frame": 1, "end_frame": 24,
                         "params": {"axis": "forward", "angle_deg": 10}}],
            "dialogues": [], "camera": {}, "gaze": [], "vfx": [], "prompt": ""}
    call = ToolCall(id="c1", function=FunctionCall(name=E.EDITOR_TOOL_NAME,
                                                   arguments=_json(args)))
    reply = ChatReply(content=None, tool_calls=[call])
    try:
        E.extract_draft(reply, "shot_001")
    except ValueError as exc:
        assert "axis" in str(exc) and "x / y" in str(exc), str(exc)
    else:                                     # pragma: no cover - 失败即用例红
        raise AssertionError("axis='forward' 必须被判无效（构建期会整轮 ERROR）")


def test_the_prompt_tells_the_model_the_closed_values():
    table = E.render_action_params()
    for key, values in M.action_param_domains().items():
        assert key in table
        for value in values:
            assert value in table, f"{key}={value} 没告诉模型"


def _json(payload) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)
