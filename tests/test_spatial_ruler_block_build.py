"""Ticket 03 验收第四项：硬发现阻断构建（除非已修复或显式豁免）。

计划级空间尺的处方先尽量自动落地（retime_shot / restore_cast），**仍然残留**
的 ERROR 级发现（对白装不下声明时长、角色无落点、全场时长不可恢复）不得静默
放行：``_step_building`` 必须停在构建前，审计留 ``ruler_blocked``，状态转
ERROR。可修复漂移（retime 落地）不产生残留发现，构建照常进行。
"""

from __future__ import annotations

import json

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread


class _Declared:
    """ParsedShotDeclaration 的最小替身（只带空间尺消费的字段）。"""

    def __init__(self, shot_number: int, declared_seconds):
        self.shot_number = shot_number
        self.declared_seconds = declared_seconds


class _Parsed:
    declared_total_seconds = None
    declared_shots = [_Declared(1, 3.5), _Declared(2, 4.0)]


class _ParsedTotalOnly:
    """只有全场声明的剧本：policy 对总漂移只报不自动重排（缺逐镜数据）。"""

    declared_total_seconds = 33.0
    declared_shots = []


class _Builder:
    def __init__(self):
        self.built: list = []

    def build(self, plan: Plan, brief=None):
        self.built.append(plan)
        return {"shots": 2, "characters": 0, "cameras": 1, "motions": 0,
                "keyframes": 0, "total_frames": 264}


def _plan(dialogue_end_frame: int = 0) -> Plan:
    plan = Plan(scene_heading="码头")
    dialogues = []
    if dialogue_end_frame:
        dialogues = [{"speaker": "甲", "text": "很长的台词。",
                      "start_frame": 1, "end_frame": dialogue_end_frame}]
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 168, dialogues=dialogues),
        ShotPlan("shot_002", "推进", "MS", 96),
    ]
    return plan


def _driver(plan: Plan, parsed, audit=None) -> PrevisDriver:
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit or AuditLogger(),
        script="INT. 码头 - 日\n\n甲说话。\n",
        parsed_script=parsed, builder=_Builder(),
        thread_factory=InlineThread)
    driver.plan = plan
    return driver


def test_unrepaired_hard_finding_blocks_build(tmp_path) -> None:
    """对白装不下 3.5s → 残留 SR002 ERROR → 不构建、状态 ERROR、留审计。"""
    audit = AuditLogger(directory=tmp_path)
    driver = _driver(_plan(dialogue_end_frame=150), _Parsed(), audit=audit)
    driver._step_building()
    assert driver.state is DriverState.ERROR
    assert "阻断构建" in driver.error
    assert driver.builder.built == []
    records = [line for line in audit.audit_path.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    kinds = [json.loads(line)["kind"] for line in records]
    assert "ruler_blocked" in kinds
    assert "run_failed" in kinds


def test_repairable_drift_still_builds() -> None:
    """retime 能落地（对白装得下 3.5s）→ 无残留硬发现 → 构建照常进行。"""
    driver = _driver(_plan(dialogue_end_frame=40), _Parsed())
    driver._step_building()
    assert driver.state is DriverState.FINISHING
    assert len(driver.builder.built) == 1
    assert driver.builder.built[0].shots[0].duration_frames == 84


def test_total_drift_is_waived_by_policy_and_does_not_block() -> None:
    """全场时长漂移（target='plan'）按 policy 显式豁免：ERROR 进 compliance，不阻断。"""
    driver = _driver(_plan(), _ParsedTotalOnly())
    driver._step_building()
    assert driver.state is DriverState.FINISHING
    assert len(driver.builder.built) == 1
    findings = (driver._compliance or {}).get("findings") or []
    assert any(item.get("rule") == "SR002" and item.get("severity") == "error"
               and item.get("target") == "plan" for item in findings)
