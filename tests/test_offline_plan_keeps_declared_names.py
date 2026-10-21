"""离线替身必须对齐真实 agent 的角色行为（2026-10-21 实测缺陷）。

真实 DeepSeek 跑（docs/evidence/20261021-deepseek-real-run/）直接读剧本
散文，把角色锚名（米迦尔/伊恩/偷盗者）写进计划，粗排 gate 通过。离线
确定性替身此前把角色名映射成 ``char_NNN`` 再丢弃映射，或者（真实剧本
的镜头没有「角色」字段、角色只在主体动作散文里）产出全片无主体的计划：

* ``E_PLAN_CAST_DROP``：计划里的 ``char_001`` 没有一个能对应角色锚名；
* ``E_PLAN_NO_SUBJECT``：计划全片没有任何角色/拍对象/道具主体。

本测试钉住"离线替身与 agent 同一行为"：解析层从散文识别角色锚声明名，
``shots_from_declarations`` 直写角色名（不再映射成 ``char_NNN``）。
"""

from __future__ import annotations

import json
from pathlib import Path

from block_director.contracts.enums import MessageRole, Purpose
from block_director.contracts.messages import ChatPayload, Message
from block_director.delivery.coarse_gate import plan_integrity_findings
from block_director.layer1_input import parse_script
from block_director.layer5_orchestrator.offline import (
    OfflineTransport,
    demo_plan_dict,
    shots_from_declarations,
)

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "work" / "node123_real.md"


def test_real_script_declarations_carry_prose_roles():
    """逐镜声明要能读出散文里的角色锚名（agent 能做的，替身也要能）。"""
    script = parse_script(REAL)
    shots = list(script.declared_shots)
    assert shots[0].characters == ["米迦尔", "伊恩", "偷盗者"], (
        f"镜头 1 主体动作提到三人，实际 {shots[0].characters}")
    # 镜头 2 的台词说话人是米迦尔，构图里伊恩与远处偷盗者同框
    assert "米迦尔" in shots[1].characters
    assert "伊恩" in shots[1].characters
    # 镜头 3 是过米迦尔肩的伊恩正反打
    assert "伊恩" in shots[2].characters
    assert "米迦尔" in shots[2].characters


def test_shots_from_declarations_keeps_real_names():
    """离线计划直写角色锚名，与真实 agent 的计划一致，不再映射 char_NNN。"""
    script = parse_script(REAL)
    plan = demo_plan_dict(REAL.read_text(encoding="utf-8"),
                          declarations=script.declared_shots)
    all_chars = [c for shot in plan["shots"] for c in shot["characters"]]
    assert "米迦尔" in all_chars
    assert "伊恩" in all_chars
    assert "偷盗者" in all_chars
    assert not any(c.startswith("char_") for c in all_chars), (
        "离线替身不得把角色名映射成 char_NNN 再丢弃映射")


def test_offline_plan_passes_cast_integrity_gate():
    """真实剧本的离线计划不得再被粗排门以 E_PLAN_CAST_DROP 误杀。"""
    script = parse_script(REAL)
    plan = demo_plan_dict(REAL.read_text(encoding="utf-8"),
                          declarations=script.declared_shots)
    findings = plan_integrity_findings(plan, parsed=script)
    assert findings == [], [f["message"] for f in findings]


def test_offline_drafts_follow_plan_character_names():
    """离线草案的动作角色要跟着计划的真实角色名走，不能引用 char_001。"""
    script = parse_script(REAL)
    plan = demo_plan_dict(REAL.read_text(encoding="utf-8"),
                          declarations=script.declared_shots)
    transport = OfflineTransport(plan=plan)
    draft = transport._draft_for(0)
    for action in draft.get("actions") or []:
        cid = action.get("character_id") or ""
        assert not cid.startswith("char_"), (
            f"离线草案动作引用内部 id {cid}，与计划真实角色名不一致")


def test_offline_editor_keeps_declared_shot_types_without_injected_plan():
    """B1 草案必须服从剧本声明的景别，而不是内置替身的 MLS/MCU。"""
    script = parse_script(REAL)
    transport = OfflineTransport(declarations=script.declared_shots)
    drafts = []
    for index in range(2):
        reply = transport.chat(ChatPayload(
            messages=[Message(role=MessageRole.USER, content="产出该镜草案")],
            purpose=Purpose.EDITOR,
            request_id=f"editor-{index}",
        ))
        drafts.append(json.loads(reply.tool_calls[0].function.arguments))
    assert [draft["shot_type"] for draft in drafts] == ["ELS", "MS"]


def test_offline_editor_uses_declared_names_without_injected_plan():
    """B1 的动作角色也必须来自声明，而不是泄漏内置 char_NNN。"""
    script = parse_script(REAL)
    transport = OfflineTransport(declarations=script.declared_shots)
    action_ids = []
    for index in range(2):
        reply = transport.chat(ChatPayload(
            messages=[Message(role=MessageRole.USER, content="产出该镜草案")],
            purpose=Purpose.EDITOR,
            request_id=f"editor-action-{index}",
        ))
        draft = json.loads(reply.tool_calls[0].function.arguments)
        action_ids.append(draft["actions"][0]["character_id"])
    assert action_ids == ["米迦尔", "伊恩"]


def test_offline_driver_keeps_declared_shot_types_after_b1(tmp_path):
    """阶段 B1 合并后，计划里的景别仍与剧本声明逐镜一致。"""
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger

    script = parse_script(REAL)
    transport = OfflineTransport(declarations=script.declared_shots)
    driver = PrevisDriver(
        transport=transport,
        audit=AuditLogger(directory=tmp_path),
        script="",
        parsed_script=script,
        limits=DriverLimits(),
        knowledge=None,
    )
    driver.run_to_completion(poll_interval=0.0, max_wall_s=30)
    assert driver.plan is not None
    assert [shot.shot_type for shot in driver.plan.shots[:2]] == ["ELS", "MS"]


def test_driver_pins_declared_shot_types_before_b1(tmp_path):
    """阶段 A 若漏掉声明景别，驱动器也要在 B1 前恢复声明优先级。"""
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger

    script = parse_script(REAL)
    plan = demo_plan_dict(REAL.read_text(encoding="utf-8"),
                          declarations=script.declared_shots)
    plan["shots"][0]["shot_type"] = "MLS"
    plan["shots"][1]["shot_type"] = "MCU"
    transport = OfflineTransport(plan=plan,
                                 declarations=script.declared_shots)
    driver = PrevisDriver(
        transport=transport,
        audit=AuditLogger(directory=tmp_path),
        script="",
        parsed_script=script,
        limits=DriverLimits(),
        knowledge=None,
    )
    driver.run_to_completion(poll_interval=0.0, max_wall_s=30)
    assert driver.plan is not None
    assert [str(shot.shot_type) for shot in driver.plan.shots[:2]] == [
        "ELS", "MS"]
    assert driver.snapshot()["compliance"]["ok"] is True


def test_driver_preserves_an_explicit_r015_break(tmp_path):
    """显式且有理由的景别破例仍可表达，不被声明 pin 静默抹掉。"""
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger

    script = parse_script(REAL)
    plan = demo_plan_dict(REAL.read_text(encoding="utf-8"),
                          declarations=script.declared_shots)
    plan["shots"][0]["shot_type"] = "CU"
    plan["shots"][0]["rule_justifications"] = [{
        "rule": "R015", "action": "break",
        "reason": "导演明确要求用特写交代银币细节",
    }]
    transport = OfflineTransport(plan=plan,
                                 declarations=script.declared_shots)
    driver = PrevisDriver(
        transport=transport,
        audit=AuditLogger(directory=tmp_path),
        script="",
        parsed_script=script,
        limits=DriverLimits(),
        knowledge=None,
    )
    driver.run_to_completion(poll_interval=0.0, max_wall_s=30)
    assert driver.plan is not None
    assert str(driver.plan.shots[0].shot_type) == "CU"
    report = driver.snapshot()["compliance"]
    assert report["ok"] is True
    r015 = [item for item in report["findings"]
            if item.get("rule") == "R015"
            and "拍摄距离" in str(item.get("message") or "")]
    assert len(r015) == 1
    assert r015[0]["severity"] == "warning"


def test_resume_ignores_a_reasonless_r015_break(tmp_path):
    """绕过阶段 A schema 的旧断点也不得用无理由破例改掉声明景别。"""
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
        ResumeState,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger

    script = parse_script(REAL)
    plan = demo_plan_dict(REAL.read_text(encoding="utf-8"),
                          declarations=script.declared_shots)
    plan["shots"][0]["shot_type"] = "CU"
    plan["shots"][0]["rule_justifications"] = [{
        "rule": "R015", "action": "break",
    }]
    driver = PrevisDriver(
        transport=OfflineTransport(declarations=script.declared_shots),
        audit=AuditLogger(directory=tmp_path),
        script="",
        parsed_script=script,
        limits=DriverLimits(),
        knowledge=None,
        resume_state=ResumeState(plan=plan, script=""),
    )
    assert driver.plan is not None
    assert str(driver.plan.shots[0].shot_type) == "ELS"
