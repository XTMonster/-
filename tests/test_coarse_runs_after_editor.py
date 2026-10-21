"""Coarse blocking must run on the edited plan, not the planning placeholder."""

from __future__ import annotations

from block_director.layer5_orchestrator.driver import PrevisDriver, ResumeState
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread


SCRIPT = "INT. 咖啡馆 - 日\n\n小明与小华在桌边交谈。\n"

TWO_SHOT_PLAN = {
    "scene_heading": "INT. 咖啡馆 - 日",
    "continuity_notes": ["B1 必须先于粗排"],
    "shots": [
        {
            "shot_id": "shot_001",
            "order": 1,
            "intent": "建立人物关系",
            "intent_type": "铺垫",
            "shot_type": "MS",
            "duration_frames": 48,
            "characters": ["char_001", "char_002"],
            "dialogue_ids": [],
            "axis_note": "",
            "continuity_in": "",
            "prompt": "",
        },
        {
            "shot_id": "shot_002",
            "order": 2,
            "intent": "推进对话",
            "intent_type": "推进",
            "shot_type": "MCU",
            "duration_frames": 48,
            "characters": ["char_002"],
            "dialogue_ids": [],
            "axis_note": "",
            "continuity_in": "",
            "prompt": "",
        },
    ],
}


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        name="emit_plan",
        description="plan",
        parameters=EMIT_PLAN_TOOL_PARAMETERS,
        handler=lambda **kwargs: "计划已接收",
    )
    registry.add(
        name="emit_shot_draft",
        description="draft",
        parameters={"type": "object", "properties": {}},
        handler=lambda **kwargs: "草案已接收",
    )
    return registry


class RecordingBuilder:
    def __init__(self) -> None:
        self.built = []

    def build(self, plan, brief=None):
        self.built.append(plan)
        return {
            "shots": len(plan.shots),
            "characters": 2,
            "cameras": len(plan.shots),
            "motions": sum(len(shot.actions) for shot in plan.shots),
            "keyframes": 0,
            "total_frames": plan.total_frames,
            "warnings": [],
            "results": [],
        }


def test_coarse_gate_sees_b1_actions_on_first_run():
    gate_calls = []
    builder = RecordingBuilder()

    def coarse_gate(plan, brief=None):
        gate_calls.append(
            {
                shot.shot_id: [dict(action) for action in shot.actions]
                for shot in plan.shots
            }
        )
        return {
            "ready": True,
            "gates": {"coarse": "pass", "baseline": "frozen"},
        }

    driver = PrevisDriver(
        transport=OfflineTransport(plan=TWO_SHOT_PLAN),
        audit=AuditLogger(),
        script=SCRIPT,
        registry=_registry(),
        auditor=None,
        builder=builder,
        thread_factory=InlineThread,
        coarse_gate=coarse_gate,
    )

    assert driver.run_to_completion().value == "DONE"
    assert len(gate_calls) == 1
    assert gate_calls[0]["shot_001"][0]["action_type"] == "nod"
    assert gate_calls[0]["shot_002"][0]["action_type"] == "sit"
    assert len(builder.built) == 1


def test_resume_with_pending_drafts_finishes_editor_before_coarse():
    gate_calls = []

    def coarse_gate(plan, brief=None):
        gate_calls.append(plan)
        return {
            "ready": True,
            "gates": {"coarse": "pass", "baseline": "frozen"},
        }

    driver = PrevisDriver(
        transport=OfflineTransport(plan=TWO_SHOT_PLAN),
        audit=AuditLogger(),
        script=SCRIPT,
        registry=_registry(),
        auditor=None,
        builder=RecordingBuilder(),
        thread_factory=InlineThread,
        resume_state=ResumeState(
            run_id="resume-before-b1",
            plan=TWO_SHOT_PLAN,
            drafts={},
        ),
        coarse_gate=coarse_gate,
    )

    assert gate_calls == []
    assert driver.run_to_completion().value == "DONE"
    assert len(gate_calls) == 1
    assert gate_calls[0].shots[0].actions[0]["action_type"] == "nod"
    assert gate_calls[0].shots[1].actions[0]["action_type"] == "sit"
