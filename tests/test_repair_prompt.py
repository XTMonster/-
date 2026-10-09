"""v1.6 B4（FR-C5 / D-13）：修复提示注入告警数值证据与固定动作菜单；accept 留痕。

E-video P1-1 的教训：构图门判红后模型反复试仍不过，因为它拿到的是**分数**
不是证据。卡 B4 钉死：审核失败时把 ``GuardWarning[]``（带实测数值）注入修复
提示，每条一行「现象 + 实测 vs 区间 + 一个可选动作」，动作菜单固定四项
``move_camera / reframe / move_character / accept``；accept 必须落成
``guard_verdict`` 审计事件（shot_id / warning_type / accepted / reason /
fix_action）——绝不静默。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.audit import (  # noqa: E402
    AuditError,
    AuditResult,
    missing_event_fields,
)
from block_director.contracts.guard import (  # noqa: E402
    Confidence,
    GuardWarning,
    Severity,
)
from block_director.layer5_orchestrator import repair as R  # noqa: E402
from block_director.layer5_orchestrator.driver import default_registry  # noqa: E402


def _warning(kind="framing_too_tight", severity=Severity.WARNING,
             evidence=None, **extra):
    if evidence is None:
        evidence = {"head_height_ratio": 0.93,
                    "expected_range": [0.55, 0.75], "shot_type": "CU"}
    evidence.update(extra)
    return GuardWarning(
        shot_id="shot_002", frame_range=(1, 48), type=kind, subject="米迦尔",
        evidence=evidence, severity=severity, confidence=Confidence.HIGH,
        declared_intent="CU：面部特写",
        suggestion_hint="拉远相机或降焦段")


def _audit(*warnings):
    audit = AuditResult(
        passed=False, level="rule",
        errors=[AuditError(rule="COMPOSITION", message="构图分低")])
    audit.guard_warnings = list(warnings)
    return audit


def test_repair_prompt_carries_measured_numbers_and_the_fixed_menu():
    payload = R.build_repair_payload(_audit(_warning()), default_registry())
    system = payload.messages[0].content
    assert "framing_too_tight" in system
    assert "0.93" in system                       # 实测数值进提示
    assert "[0.55, 0.75]" in system               # 区间同框对照
    assert "取景过紧" in system                   # 现象文案
    for item in ("move_camera", "reframe", "move_character", "accept"):
        assert item in system, f"动作菜单缺 {item}"
    assert "guard_verdict" in system              # accept 的留痕契约被写出来


def test_headroom_warning_renders_measured_vs_band():
    warning = _warning(kind="headroom_off",
                       evidence={"headroom": -0.24,
                                 "expected_range": [0.03, 0.12]})
    line = R.guard_warning_line(warning)
    assert "headroom=-0.24" in line
    assert "[0.03, 0.12]" in line
    assert "头顶留白出区间" in line
    assert "move_camera" in line


def test_threshold_evidence_renders_as_measured_vs_limit():
    warning = _warning(kind="edge_clip",
                       evidence={"edge_clip": 0.34, "edge_clip_max": 0.10})
    line = R.guard_warning_line(warning)
    assert "edge_clip=0.34" in line
    assert "edge_clip_max=0.1" in line
    assert "reframe" in line


def test_info_warnings_do_not_disturb_the_repair_prompt():
    payload = R.build_repair_payload(
        _audit(_warning(kind="thirds_deviation", severity=Severity.INFO)),
        default_registry())
    system = payload.messages[0].content
    assert "视锥校验报出" not in system
    assert "guard_verdict" not in system
    assert "可选动作菜单" not in system


def test_an_audit_without_guard_warnings_builds_unchanged():
    """旧审计结果（没有 guard_warnings 属性）照常出提示，不注入任何告警段。"""
    audit = AuditResult(passed=False, level="rule",
                        errors=[AuditError(rule="COMPOSITION",
                                           message="构图分低")])
    system = R.build_repair_payload(audit, default_registry()).messages[0].content
    assert "guard_verdict" not in system
    assert "构图分低" in system


def test_accept_produces_a_guard_verdict_record():
    record = R.guard_verdict("shot_002", "framing_too_tight", accepted=True,
                             reason="导演刻意的大特写", fix_action="accept")
    assert record == {
        "shot_id": "shot_002",
        "warning_type": "framing_too_tight",
        "accepted": True,
        "reason": "导演刻意的大特写",
        "fix_action": "accept",
    }
    #: 与 audit.py 登记的事件契约逐键对拍（V16_EVENT_FIELDS["guard_verdict"]）。
    assert missing_event_fields("guard_verdict", record) == []


def test_a_reject_verdict_keeps_the_same_shape():
    record = R.guard_verdict("shot_004", "occlusion", accepted=False,
                             reason="已用 move_camera 换机位",
                             fix_action="move_camera")
    assert missing_event_fields("guard_verdict", record) == []
    assert record["accepted"] is False
    assert record["fix_action"] == "move_camera"


def test_parse_guard_accepts_turns_lines_into_records():
    text = ("我会先检查这一镜。\n"
            "ACCEPT framing_too_tight 这是刻意的面部大特写\n"
            "然后调用 check_composition 复核。")
    records = R.parse_guard_accepts(text, shot_id="shot_002")
    assert len(records) == 1
    assert records[0]["warning_type"] == "framing_too_tight"
    assert records[0]["accepted"] is True
    assert records[0]["fix_action"] == "accept"
    assert "面部大特写" in records[0]["reason"]
    assert missing_event_fields("guard_verdict", records[0]) == []


def test_a_malformed_accept_is_reported_not_silently_dropped():
    with pytest.raises(ValueError):
        R.parse_guard_accepts("ACCEPT", shot_id="shot_002")


def test_guard_verdict_refuses_an_empty_warning_type():
    with pytest.raises(ValueError):
        R.guard_verdict("shot_002", "   ", accepted=True, fix_action="accept")


def test_occlusion_suggests_moving_character_first():
    """v4 真跑：遮挡告警若建议先动机位，模型会把相机挪到主体背后并触发回滚
    风暴（455 次）。建议顺序改为先挪主体/遮挡者，机位是最后手段。"""
    for kind in ("occlusion", "subject_not_visible"):
        hint = R.GUARD_FIX_ACTION[kind]
        assert hint.startswith("move_character"), (kind, hint)
    behind = R.GUARD_FIX_ACTION["subject_behind_camera"]
    assert "reframe" in behind and "不要穿过主体" in behind
