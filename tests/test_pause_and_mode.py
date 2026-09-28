"""§13.1 暂停/继续，以及 §7.1 的编排范式校验。"""

from __future__ import annotations

from block_director.contracts.config import AppConfig
from block_director.contracts.enums import OrchestrationMode
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


def make_driver():
    return PrevisDriver(transport=OfflineTransport(), audit=AuditLogger(),
                        script="INT. 房间 - 日\n", thread_factory=InlineThread)


# --------------------------------------------------------------------------- #
# 暂停
# --------------------------------------------------------------------------- #
def test_paused_driver_does_not_advance():
    driver = make_driver()
    driver.step()                       # IDLE → PLANNING
    state_before = driver.state
    steps_before = driver.snapshot()["steps"]

    driver.pause()
    for _ in range(5):
        assert driver.step() is True    # 仍然"活着"
    assert driver.state is state_before
    assert driver.snapshot()["steps"] == steps_before
    assert driver.snapshot()["paused"] is True


def test_resume_continues_the_run():
    driver = make_driver()
    driver.pause()
    driver.step()
    driver.resume()
    state = driver.run_to_completion()
    assert state is DriverState.DONE
    assert driver.snapshot()["paused"] is False


def test_pause_and_resume_are_audited():
    driver = make_driver()
    driver.step()
    driver.pause()
    driver.resume()
    kinds = [event.kind for event in driver.audit.recent(50)]
    assert "run_paused" in kinds and "run_resumed" in kinds


def test_pause_keeps_the_plan_that_was_already_built():
    """暂停不是取消：已经拿到的计划必须原样保留。"""
    driver = make_driver()
    driver.run_to_completion()
    plan = driver.plan.to_dict() if driver.plan else None
    driver.pause()
    driver.step()
    assert (driver.plan.to_dict() if driver.plan else None) == plan
    assert driver.state is DriverState.DONE


# --------------------------------------------------------------------------- #
# 编排范式
# --------------------------------------------------------------------------- #
def test_plan_structured_is_the_default_and_valid():
    config = AppConfig()
    assert config.orchestration.mode is OrchestrationMode.PLAN_STRUCTURED
    assert config.errors() == []


def test_react_only_is_refused_instead_of_silently_ignored():
    config = AppConfig()
    config.orchestration.mode = OrchestrationMode.REACT_ONLY
    problems = config.errors()
    assert problems and any(item.code == "CFG_013" for item in problems)
    assert "plan_structured" in problems[0].message
