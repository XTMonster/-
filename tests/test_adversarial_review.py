"""独立对抗性镜头审查纯层测试（SPEC_adversarial_review_agent_20261012.md）。

覆盖：
- 硬 finding（审核未通过 / 越轴）→ revise/escalate，绝不 pass；
- 安全区/九宫格偏差本身只能是 soft issue，不得单独制造硬失败；
- 主体完全不可见 → major revise；
- 同输入两次结果逐字一致（确定性、无 IO/网络/bpy）；
- 建议必须指向可调变量之一；
- to_dict/from_dict 可序列化往返；
- 纯层静态检查不含 bpy/网络库。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from block_director.layer5_orchestrator.adversarial_review import (
    AdversarialReview,
    ReviewIssue,
    review_shot,
)


ADJUSTABLE = (
    "camera distance",
    "lens",
    "target offset",
    "action timing",
    "subject placement",
)


def _ok_kwargs(**overrides):
    kwargs = dict(
        shot_id="s001",
        version=3,
        intent="MCU 正面注视镜头，情绪推进",
        audit_passed=True,
        audit_findings=[],
        framing={"shot_type": "MCU", "distance_m": 2.0, "lens_mm": 35.0},
        safe_area={"title_safe_violation": False, "action_safe_violation": False},
        thirds={"subject_near_third": True, "horizon_third": True},
        visible_ratio=0.85,
    )
    kwargs.update(overrides)
    return kwargs


def _issue_severities(review: AdversarialReview) -> list[str]:
    return [issue.severity for issue in review.issues]


def test_hard_audit_finding_revises_never_passes():
    """审核未通过（硬 finding）→ disposition 必须 revise/escalate。"""
    review = review_shot(**_ok_kwargs(
        audit_passed=False,
        audit_findings=["R003 越轴：角色 A 与 B 分置镜头两侧，视线相背"],
    ))
    assert review.disposition in ("revise", "escalate")
    assert "hard" in _issue_severities(review)


def test_axis_finding_escalates():
    """越轴（R001）→ escalate，且带明确证据与建议。"""
    review = review_shot(**_ok_kwargs(
        audit_findings=["R001 越轴：180 度线被跨"],
    ))
    assert review.disposition == "escalate"
    assert any("R001" in issue.evidence for issue in review.issues)


def test_safe_area_and_thirds_are_soft_reference_only():
    """安全区/九宫格偏差只产生 soft issue，不得把 pass 拉成 revise。"""
    review = review_shot(**_ok_kwargs(
        safe_area={"title_safe_violation": True, "action_safe_violation": True},
        thirds={"subject_near_third": False, "horizon_third": False,
                "deviation": 0.18},
    ))
    assert review.disposition == "pass"
    assert _issue_severities(review) and all(
        s == "soft" for s in _issue_severities(review))


def test_invisible_subject_is_major_revise():
    """主体完全不可见（visible_ratio <= 0.2）→ major revise。"""
    review = review_shot(**_ok_kwargs(visible_ratio=0.1))
    assert review.disposition == "revise"
    assert "major" in _issue_severities(review)


def test_deterministic_same_input_same_output():
    """同输入两次：repr 与 to_dict 逐字一致。"""
    kwargs = _ok_kwargs(
        audit_findings=["R003 越轴：角色 A 与 B 分置镜头两侧"],
        safe_area={"title_safe_violation": True, "action_safe_violation": False},
    )
    first = review_shot(**kwargs)
    second = review_shot(**kwargs)
    assert repr(first) == repr(second)
    assert first.to_dict() == second.to_dict()


def test_suggestions_target_adjustable_variables():
    """每个建议至少指向一个可调变量。"""
    review = review_shot(**_ok_kwargs(
        audit_passed=False,
        audit_findings=["R003 越轴：角色 A 与 B 分置镜头两侧"],
        visible_ratio=0.15,
    ))
    assert review.issues
    for issue in review.issues:
        assert any(word in issue.suggestion for word in ADJUSTABLE), (
            issue.suggestion)


def test_disposition_enum_and_serialization_roundtrip():
    """disposition 只在 {pass, revise, escalate}；to_dict/from_dict 往返一致。"""
    review = review_shot(**_ok_kwargs())
    assert review.disposition in ("pass", "revise", "escalate")
    restored = AdversarialReview.from_dict(review.to_dict())
    assert restored.to_dict() == review.to_dict()
    assert restored == review


def test_pure_layer_has_no_bpy_or_network_imports():
    """纯层文件不得 import bpy 或网络库。"""
    source = Path(__file__).resolve().parents[1] / "block_director" / \
        "layer5_orchestrator" / "adversarial_review.py"
    text = source.read_text(encoding="utf-8")
    assert "bpy" not in text
    for banned in ("import requests", "import urllib", "from requests",
                   "import aiohttp", "import socket"):
        assert banned not in text
