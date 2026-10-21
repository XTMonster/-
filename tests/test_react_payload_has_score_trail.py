"""缺陷 B（T6）：ReAct 载荷注入分数轨迹与最高分版本摘要。"""

from __future__ import annotations

from block_director.contracts.audit import AuditResult
from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.control_tools import register_control_tools
from block_director.layer5_orchestrator.react import build_react_payload
from block_director.layer5_orchestrator.tool_registry import ToolRegistry


def _shot():
    return ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "右手特写",
        "shot_type": "CU", "duration_frames": 84,
        "characters": ["char_001"],
    })


def _registry():
    registry = ToolRegistry()
    register_control_tools(registry)
    return registry


def _audit(score=55.0):
    return AuditResult(passed=False, target="shot_001", score=score)


def _trail():
    return [
        {"version": 1, "score": 55.0, "summary": "setup_camera 收紧景别"},
        {"version": 2, "score": 62.0, "summary": "move_character 左移"},
        {"version": 3, "score": 55.0, "summary": "reframe 最紧"},
    ]


def test_payload_injects_score_trail_and_best_summary():
    payload = build_react_payload(_shot(), _audit(), registry=_registry(),
                                  score_trail=_trail())
    system_text = payload.messages[0].content
    assert "分数轨迹" in system_text
    assert "版本 2" in system_text and "62.0" in system_text
    assert "最高分" in system_text and "62.0" in system_text
    assert "没升" in system_text or "未升" in system_text


def test_payload_without_trail_keeps_old_shape():
    payload = build_react_payload(_shot(), _audit(), registry=_registry(),
                                  score_trail=None)
    system_text = payload.messages[0].content
    assert "分数轨迹" not in system_text
    assert "请精修镜头 shot_001" in payload.messages[1].content
