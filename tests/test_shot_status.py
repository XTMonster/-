"""§13.2 分镜状态推导的纯计算测试。"""

from __future__ import annotations

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Severity
from block_director.contracts.plan import Plan
from block_director.layer5_orchestrator.shot_status import (
    STATUS_DEGRADED,
    STATUS_FAILED,
    STATUS_GENERATED,
    STATUS_PENDING,
    STATUS_REPAIRED,
    shot_statuses,
    summary_line,
)


def plan_of(count: int = 3) -> Plan:
    return Plan.from_dict({"shots": [
        {"shot_id": f"shot_{index:03d}", "order": index,
         "intent": f"第 {index} 个镜头的意图说明，可能要截断一点点",
         "shot_type": "MS", "duration_frames": 48}
        for index in range(1, count + 1)]})


def failed(shot_id: str) -> AuditResult:
    return AuditResult(passed=False, target=shot_id, errors=[
        AuditError(rule="R001", code="E_AXIS_001", message="越轴",
                   severity=Severity.ERROR, target=shot_id,
                   suggestion="挪到同侧")])


def passed(shot_id: str, score: float = 82.0) -> AuditResult:
    return AuditResult(passed=True, target=shot_id, score=score,
                       suggestions=["构图良好"])


def test_planned_shots_start_as_pending():
    rows = shot_statuses(plan_of(), [])
    assert [row["status"] for row in rows] == [STATUS_PENDING] * 3
    assert rows[0]["seconds"] == 2.0
    assert rows[0]["audits"] == 0 and rows[0]["passed"] is None


def test_built_shots_are_generated():
    rows = shot_statuses(plan_of(), [], built_shot_ids={"shot_001", "shot_002"})
    assert [row["status"] for row in rows] == [STATUS_GENERATED,
                                               STATUS_GENERATED, STATUS_PENDING]


def test_audited_but_failed_shot_is_failed():
    rows = shot_statuses(plan_of(), [passed("shot_001"), failed("shot_002")])
    assert [row["status"] for row in rows] == [STATUS_GENERATED, STATUS_FAILED,
                                               STATUS_PENDING]
    assert rows[1]["failures"] == 1 and rows[1]["passed"] is False


def test_repaired_shot_is_marked_repaired():
    rows = shot_statuses(plan_of(),
                         [failed("shot_001"), passed("shot_001", 88.0)])
    assert rows[0]["status"] == STATUS_REPAIRED
    assert rows[0]["audits"] == 2 and rows[0]["failures"] == 1
    assert rows[0]["score"] == 88.0


def test_degraded_run_marks_unaudited_shots():
    rows = shot_statuses(plan_of(2), [passed("shot_001")],
                         degraded="预算耗尽")
    assert [row["status"] for row in rows] == [STATUS_GENERATED, STATUS_DEGRADED]


def test_failure_beats_degraded():
    """已经判失败的镜头不该被降级状态盖掉——失败是更精确的信息。"""
    rows = shot_statuses(plan_of(1), [failed("shot_001")], degraded="预算耗尽")
    assert rows[0]["status"] == STATUS_FAILED


def test_intent_is_truncated_for_the_table():
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "shot_type": "MS",
         "duration_frames": 48,
         "intent": "建立雨夜客厅的空间与两人的距离，同时交代窗外的雨势"}]})
    rows = shot_statuses(plan, [])
    assert len(rows[0]["intent"]) <= 24
    assert rows[0]["intent"].endswith("…")
    # 短意图不截断，也不该被硬塞省略号
    short = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "shot_type": "MS",
         "duration_frames": 48, "intent": "交代空间"}]})
    assert shot_statuses(short, [])[0]["intent"] == "交代空间"


def test_empty_plan_has_no_rows():
    assert shot_statuses(None) == []
    assert shot_statuses(Plan.from_dict({"shots": []})) == []
    assert summary_line([]) == "还没有分镜"


def test_summary_line_counts_every_status():
    rows = shot_statuses(plan_of(3), [passed("shot_001"), failed("shot_002")],
                         degraded="")
    line = summary_line(rows)
    assert "共 3 镜" in line and "失败 1" in line and "待生成 1" in line
