"""v1.6 A6 (D-08): scene_built event carries a reason field.

The second scene_built is not a duplicate log entry; it is repair-triggered
rebuild (repair re-emits a draft or rollback reverts the plan). This is by
design (13 shots rebuild in 1.6s); the gap was observability. The reason is
read from existing driver state (_rebuild_in_place + _just_rolled_back); no
new state is added.
"""

from __future__ import annotations

import json

from block_director.contracts.audit import (
    SCENE_BUILT_REASONS,
    scene_built_reason,
)
from block_director.contracts.audit import AuditResult
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from test_driver_builder import RecordingBuilder
from test_repair_rollback import (
    DraftRepairTransport,
    RepairingTransport,
    TrivialBuilder,
    _driver as _rollback_driver,
    _registry,
    failing,
)

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def test_scene_built_reason_contract():
    """纯函数：三种输入组合 → 三个闭集取值。"""
    assert scene_built_reason(rebuild_in_place=False, just_rolled_back=False) == "initial"
    assert scene_built_reason(rebuild_in_place=True, just_rolled_back=False) == "repair_rebuild"
    assert scene_built_reason(rebuild_in_place=True, just_rolled_back=True) == "rollback_rebuild"
    assert set(SCENE_BUILT_REASONS) == {"initial", "repair_rebuild", "rollback_rebuild"}


def test_initial_build_records_reason_initial(tmp_path):
    """首次构建 → reason=initial。"""
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit, script=SCRIPT,
        builder=RecordingBuilder(), thread_factory=InlineThread)
    driver.run_to_completion()
    records = [json.loads(line) for line in
               audit.audit_path.read_text(encoding="utf-8").splitlines()]
    built = [r for r in records if r["kind"] == "scene_built"]
    assert len(built) == 1, "首次构建只有一条 scene_built"
    assert built[0]["data"]["reason"] == "initial"


def test_repair_rebuild_records_reason_repair_rebuild(tmp_path):
    """修复重提草案 → _needs_rebuild → 重建 → reason=repair_rebuild。"""
    audit = AuditLogger(directory=tmp_path)
    transport = DraftRepairTransport()
    # Second result must be a genuine pass (passed=True), not failing([]): failing()
    # hardcodes passed=False which causes another repair turn and a third build.
    driver = _rollback_driver(transport, [failing(["R003"]), AuditResult(passed=True)],
                              builder=TrivialBuilder())
    driver.audit = audit
    driver.run_to_completion()
    records = [json.loads(line) for line in
               audit.audit_path.read_text(encoding="utf-8").splitlines()]
    built = [r for r in records if r["kind"] == "scene_built"]
    assert len(built) == 2, "修复改了计划 → 重建 → 两条 scene_built"
    assert built[0]["data"]["reason"] == "initial"
    assert built[1]["data"]["reason"] == "repair_rebuild"


def test_rollback_rebuild_records_reason_rollback_rebuild(tmp_path):
    """修复引入新违规 → 回滚 → _just_rolled_back → 重建 → reason=rollback_rebuild。"""
    audit = AuditLogger(directory=tmp_path)
    transport = RepairingTransport()
    driver = _rollback_driver(transport, [
        failing(["R003"]),
        failing(["R003", "R001"]),  # 修复后多了 R001 → 回滚
        failing(["R003"]),
    ], builder=TrivialBuilder())
    driver.audit = audit
    driver.run_to_completion()
    records = [json.loads(line) for line in
               audit.audit_path.read_text(encoding="utf-8").splitlines()]
    built = [r for r in records if r["kind"] == "scene_built"]
    assert len(built) == 2, "回滚重建 → 两条 scene_built"
    assert built[0]["data"]["reason"] == "initial"
    assert built[1]["data"]["reason"] == "rollback_rebuild"
    kinds = [r["kind"] for r in records]
    assert "repair_rolled_back" in kinds


def test_builder_summary_cannot_overwrite_reason_or_duration(tmp_path):
    """构建摘要即使恰好有 reason/duration_s 键，也不得覆盖事件自己的字段。"""
    audit = AuditLogger(directory=tmp_path)
    builder = RecordingBuilder(summary={
        "shots": 2, "reason": "builder_reason", "duration_s": 999.0})
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit, script=SCRIPT,
        builder=builder, thread_factory=InlineThread)
    driver.run_to_completion()
    records = [json.loads(line) for line in
               audit.audit_path.read_text(encoding="utf-8").splitlines()]
    built = [r for r in records if r["kind"] == "scene_built"]
    assert len(built) == 1
    assert built[0]["data"]["reason"] == "initial", "事件 reason 不被构建摘要覆盖"
    assert built[0]["data"]["duration_s"] != 999.0, "事件 duration_s 不被构建摘要覆盖"
    assert built[0]["data"]["shots"] == 2, "构建摘要的其他字段照常传递"
