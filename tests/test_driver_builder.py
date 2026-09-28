"""§7.1 阶段 B2：驱动器 → 场景构建器的接线测试（用假构建器，不依赖 bpy）。"""

from __future__ import annotations

import json

from block_director.contracts.plan import Plan
from block_director.layer5_orchestrator.builder import SceneBuilder
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread, ScriptedTransport

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


class RecordingBuilder:
    def __init__(self, summary=None, error=None):
        self.built: list = []
        self._summary = summary or {"shots": 2, "characters": 2, "cameras": 2,
                                    "motions": 1, "keyframes": 120,
                                    "total_frames": 216}
        self._error = error

    def build(self, plan: Plan):
        self.built.append(plan)
        if self._error:
            raise self._error
        return dict(self._summary)


def _driver(builder=None, audit=None, **kwargs):
    return PrevisDriver(transport=OfflineTransport(),
                        audit=audit or AuditLogger(),
                        script=SCRIPT, builder=builder,
                        thread_factory=InlineThread, **kwargs)


def test_fake_builder_satisfies_protocol():
    assert isinstance(RecordingBuilder(), SceneBuilder)


def test_builder_is_invoked_and_state_passes_through_building():
    builder = RecordingBuilder()
    driver = _driver(builder)
    seen: list = []
    driver.add_observer(lambda event: seen.append(event.state.value))

    state = driver.run_to_completion()

    assert state is DriverState.DONE
    assert len(builder.built) == 1
    assert isinstance(builder.built[0], Plan)
    assert len(builder.built[0].shots) == 2
    assert "BUILDING" in seen
    assert driver.snapshot()["built"] is True
    assert driver.snapshot()["build"]["total_frames"] == 216


def test_build_summary_is_audited(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    driver = _driver(RecordingBuilder(), audit=audit)
    driver.run_to_completion()
    records = [json.loads(line) for line in
               audit.audit_path.read_text(encoding="utf-8").splitlines()]
    built = [r for r in records if r["kind"] == "scene_built"]
    assert len(built) == 1
    assert built[0]["data"]["cameras"] == 2
    assert records[-1]["kind"] == "run_finished"
    assert records[-1]["data"]["built"] is True


def test_without_builder_the_run_still_finishes():
    driver = _driver()
    state = driver.run_to_completion()
    assert state is DriverState.DONE
    assert driver.snapshot()["built"] is False


def test_builder_failure_is_reported_and_degrades():
    driver = _driver(RecordingBuilder(error=RuntimeError("no bpy context")))
    state = driver.run_to_completion()
    assert state is DriverState.ERROR
    assert "场景构建失败" in driver.error
    assert "no bpy context" in driver.error


def test_builder_receives_the_parsed_plan_not_raw_json():
    """构建器拿到的是已解析的对象，不是 LLM 的原始参数。"""
    builder = RecordingBuilder()
    driver = _driver(builder)
    driver.run_to_completion()
    shot = builder.built[0].shots[0]
    assert shot.shot_id == "shot_001"
    assert shot.shot_type.value == "MLS"
    assert shot.duration_frames == 96


def test_plan_can_carry_actions():
    payload = {
        "shots": [{
            "shot_id": "shot_001", "order": 1, "intent": "走进画面",
            "shot_type": "MS", "duration_frames": 48,
            "characters": ["char_001"],
            "actions": [{"character_id": "char_001", "action_type": "walk_to",
                         "start_frame": 1, "end_frame": 40,
                         "params": {"target_position": [2.0, 0.0, 0.0]}}],
        }]
    }
    builder = RecordingBuilder()
    driver = PrevisDriver(transport=ScriptedTransport([payload]),
                          audit=AuditLogger(), script=SCRIPT, builder=builder,
                          thread_factory=InlineThread,
                          limits=DriverLimits(plan_attempts=1))
    assert driver.run_to_completion() is DriverState.DONE
    actions = builder.built[0].shots[0].actions
    assert actions[0]["action_type"] == "walk_to"
    assert actions[0]["params"]["target_position"] == [2.0, 0.0, 0.0]
