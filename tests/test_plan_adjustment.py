"""G2 #8（用户 2026-10-11 裁决）：计划阶段“边做边改”——调整到上限后不整轮
作废，用剧本声明确定性补齐缺镜，已通过的模型分块原样保留。
"""

from __future__ import annotations

from block_director.contracts.audit import missing_event_fields
from block_director.contracts.plan import ShotPlan
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer6_audit.audit_logger import AuditLogger


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class NoopTransport:
    def chat(self, payload, timeout=120.0):  # 兜底不发起任何调用
        raise AssertionError("兜底补齐不应再调用模型")

    def cancel(self, request_id):
        return None


class Declaration:
    def __init__(self, number, characters=(), shot_type="MS",
                 declared_seconds=2.0):
        self.shot_number = number
        self.characters = list(characters)
        self.shot_type = shot_type
        self.declared_seconds = declared_seconds


def _driver(declarations, accepted):
    driver = PrevisDriver(transport=NoopTransport(), audit=AuditLogger(),
                          script="INT. 市场 - 日\n\n人群熙攘。\n",
                          thread_factory=InlineThread)

    class Parsed:
        def __init__(self, shots):
            self.declared_shots = shots

    driver.parsed_script = Parsed(declarations)
    driver._plan_shots = [ShotPlan.from_dict(shot) for shot in accepted]
    driver._plan_head = {}
    return driver


def test_default_plan_attempts_is_three():
    assert DriverLimits().plan_attempts == 3


def test_fallback_preserves_accepted_chunks_and_fills_only_the_missing():
    declarations = [Declaration(i, characters=["米迦尔"] if i % 2 else [],
                                shot_type="MS", declared_seconds=2.0)
                    for i in range(1, 31)]
    accepted = [{"shot_id": f"shot_{index:03d}", "order": index,
                 "intent": f"模型镜头{index}", "shot_type": "MS",
                 "duration_frames": 48} for index in range(1, 25)]
    driver = _driver(declarations, accepted)

    filled = driver._complete_plan_with_deterministic_fill()

    assert filled == 6
    assert len(driver.plan.shots) == 30
    assert driver.plan.shots[0].intent == "模型镜头1"
    assert driver.plan.shots[23].intent == "模型镜头24"
    assert driver.plan.shots[24].intent.startswith("镜号25")
    assert driver.plan.shots[29].intent.startswith("镜号30")


def test_complete_plan_is_not_reported_as_a_zero_shot_fill():
    """A complete plan is not an adjustment and must not re-enter the gate.

    Real r2 exposed the failure shape: every failed plan attempt left
    ``_plan_failures`` exhausted.  The deterministic fill then reported
    ``filled=0`` for the already complete plan, so the driver repeatedly fed
    the same plan back into the coarse gate instead of asking the model again
    or failing honestly.
    """
    declarations = [
        Declaration(1, characters=["米迦尔"], shot_type="MS"),
        Declaration(2, characters=["伊恩"], shot_type="MCU"),
    ]
    accepted = [
        {"shot_id": "shot_001", "order": 1, "intent": "模型镜头一",
         "shot_type": "MS", "duration_frames": 48,
         "characters": ["米迦尔"]},
        {"shot_id": "shot_002", "order": 2, "intent": "模型镜头二",
         "shot_type": "MCU", "duration_frames": 48,
         "characters": ["伊恩"]},
    ]
    driver = _driver(declarations, accepted)

    assert driver._complete_plan_with_deterministic_fill() is None


def test_plan_adjusted_event_fields_are_registered():
    data = {"filled_shots": 6, "attempts": 3, "problem": "x"}
    assert missing_event_fields("plan_adjusted", data) == []
    assert missing_event_fields("plan_adjusted", {}) == [
        "filled_shots", "attempts", "problem"]
