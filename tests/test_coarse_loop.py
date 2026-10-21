"""Ticket 05（纯层骨架）：粗排修正循环驱动器。

观察 -> 处方 -> 修改粗排参考 JSON -> 重建 -> 再观察；达到 gate 或显式
超轮阻塞，不改阈值、不吞错误、不降级。
"""

from __future__ import annotations

import copy

from block_director.cinema.coarse_loop import (
    DEFAULT_MAX_REVISIONS,
    run_coarse_revision_loop,
)
from block_director.layer5_orchestrator.coarse_agent import (
    OfflineFixtureCoarseProposalProvider,
)


def _reference(**overrides):
    doc = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "dock_fly_bomb",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.8, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": [-0.5, 5.5, 2.0],
            "target": [-0.2, 0.0, 0.8],
            "lens": 35.0, "fov_deg": 54.4, "movement": None,
            "provenance": "script_declaration", "resolved": True,
        }],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "飞扑建立空间", "characters": ["米迦尔"], "actions": [],
        }],
        "revisions": [],
        "notes": [],
    }
    doc.update(overrides)
    return doc


def _blocked_report(shot="shot_001", check="composition", actual=61.7,
                    finding_check="E_BLOCKOUT_EMPTY_WALL"):
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "abc", "verdict": "fail",
        "findings": [{
            "check_id": finding_check, "shot_id": shot,
            "severity": "error", "message": "空墙",
        }],
        "checks": [{
            "check_id": check, "shot_id": shot, "actual": actual,
            "threshold": 80.0, "verdict": "fail",
        }],
        "notes": [],
    }


def _pass_report():
    return {"schema_version": "blockout-report/v1",
            "manifest_fingerprint": "abc", "verdict": "pass",
            "findings": [],
            "checks": [{
                "check_id": "composition", "shot_id": "shot_001",
                "actual": 82.0, "threshold": 80.0, "verdict": "pass",
            }],
            "notes": []}


def test_loop_approves_when_first_observation_passes():
    calls = []
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda ref: calls.append("observe") or _pass_report(),
        rebuild=lambda ref: calls.append("rebuild"),
        max_revisions=3)
    assert outcome["status"] == "approved"
    assert calls == ["observe"]  #: 一次通过不重建
    assert outcome["rounds"] == []


def test_loop_converges_fail_first_then_pass():
    sequence = iter([_blocked_report(), _pass_report()])
    rebuild_calls = []
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda ref: next(sequence),
        rebuild=lambda ref: rebuild_calls.append(copy.deepcopy(ref)),
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=3)
    assert outcome["status"] == "approved"
    assert len(outcome["rounds"]) == 1
    assert len(rebuild_calls) == 1
    #: 处方确实改到参考 JSON：round1 后 camera target 指向主体质心
    assert len(outcome["reference"]["revisions"]) == 1


def test_loop_blocks_when_agent_proposal_channel_is_unavailable():
    """A failing coarse observation must be revised by the agent brain.

    The deterministic prescription builder is a program-side validator and
    fallback used by focused unit tests, never an invisible replacement for
    the agent decision.  Without an injected proposal provider the loop must
    stop with a named blocked reason instead of silently iterating to pass.
    """
    calls = []
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _ref: calls.append("observe") or _blocked_report(),
        rebuild=lambda _ref: calls.append("rebuild"),
        max_revisions=3,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "agent_proposal_unavailable"
    assert "Agent" in outcome["blocked_reason"]
    assert "provider" in outcome["blocked_reason"].lower()
    assert calls == ["observe"]
    assert len(outcome["rounds"]) == 1
    assert outcome["rounds"][0]["provider_kind"] == ""


def test_loop_blocks_when_max_revisions_reached_without_pass():
    calls = []
    #: E_SUBJECT_AREA_OVERFLOW 硬伤处方每次把相机拉远 15%，每轮都有实质
    #: 变化 -> 不触发不可收敛短路，真正走满轮数上限（超轮阻塞不降级）。
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda ref: calls.append("o") or _blocked_report(
            finding_check="E_SUBJECT_AREA_OVERFLOW"),
        rebuild=lambda ref: calls.append("r"),
        restore_best=lambda ref: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=3)
    assert outcome["status"] == "blocked"
    assert outcome["blocked_reason"] != ""
    assert "上限" in outcome["blocked_reason"] or "3" in outcome["blocked_reason"]
    #: 不降级通过：即使超轮也不把 fail 当 pass
    assert outcome["report"]["verdict"] == "fail"


def test_loop_blocks_immediately_when_prescriptions_are_noop():
    """R2-F6：处方全部零变化（如 target 已指向质心）-> 不可收敛，立刻 blocked。

    真跑 round2 的 empty_wall 处方 before==after 仍空转到轮数上限。修正循环
    必须把'处方应用后无实质变化'判定为不可收敛，提前阻塞并如实说明，
    不再把修正预算耗在无效果的重建上。
    """
    #: camera target 已经指向主体质心（米迦尔脚底 z=0 -> 质心 z=0.9）
    ref = _reference(camera_intents=[{
        "shot_id": "shot_001",
        "position": [-0.5, 5.5, 2.0],
        "target": [-0.8, 0.0, 0.9],
        "lens": 35.0, "fov_deg": 54.4, "movement": None,
        "provenance": "script_declaration", "resolved": True,
    }])
    calls = []
    outcome = run_coarse_revision_loop(
        reference=ref,
        report_loader=lambda _ref: calls.append("o") or _blocked_report(),
        rebuild=lambda _ref: calls.append("r"),
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=3)
    assert outcome["status"] == "blocked"
    assert "零变化" in outcome["blocked_reason"] \
        or "不可收敛" in outcome["blocked_reason"] \
        or "无实质" in outcome["blocked_reason"]
    #: 第一轮观察后尝试一次处方，应用判定零变化后立即 blocked，不重建、
    #: 不空转满 3 轮
    assert calls.count("o") == 1
    assert calls.count("r") == 0


def test_loop_never_guesses_without_prescription_source():
    """无 error finding 且 checks 全 pass -> 直接 approved，不产处方。"""
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda ref: _pass_report(),
        rebuild=lambda ref: None,
        max_revisions=2)
    assert outcome["status"] == "approved"
    assert outcome["reference"]["revisions"] == []


def test_loop_blocked_rounds_match_max_revisions():
    """T3：超轮阻塞时，阻塞那一轮的观察也必须计进 rounds——报告轮数与
    blocked_reason 里“达到 N 轮上限”一致，不再出现“rounds 只有 2 条却
    提示 3 轮上限”的账实不符（final12 实测 root cause 之一）。"""
    calls = []
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda ref: calls.append("o") or _blocked_report(
            finding_check="E_SUBJECT_AREA_OVERFLOW"),
        rebuild=lambda ref: calls.append("r"),
        restore_best=lambda ref: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=3)
    assert outcome["status"] == "blocked"
    assert "上限" in outcome["blocked_reason"]
    #: 3 次预算观察、2 次候选重建（最后一轮阻塞不重建）和 2 次回滚确认；
    #: 回滚确认不计入 max_revisions，rounds 仍必须 3 条。
    assert calls.count("o") == 5
    assert calls.count("r") == 2
    assert len(outcome["rounds"]) == 3
    assert [r["round_no"] for r in outcome["rounds"]] == [1, 2, 3]
    #: 阻塞轮的 report 必须留痕（该轮确实验到 fail）
    assert outcome["rounds"][-1]["report"]["verdict"] == "fail"
    assert outcome["rounds"][-1]["prescriptions"] == []


def test_default_revision_limit_is_exactly_fifty_rounds():
    """The product ceiling is 50 observations, with the last one non-mutating."""
    assert DEFAULT_MAX_REVISIONS == 50
    calls = []
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda ref: calls.append("o") or _blocked_report(
            finding_check="E_SUBJECT_AREA_OVERFLOW"),
        rebuild=lambda ref: calls.append("r"),
        restore_best=lambda ref: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        no_gain_limit=100,
    )

    assert outcome["status"] == "blocked"
    assert outcome["blocked_code"] == "max_revisions_reached"
    assert "50" in outcome["blocked_reason"]
    #: 50 次预算观察 + 49 次回滚后的 best 再观察；回滚确认不消耗预算。
    assert calls.count("o") == 99
    assert calls.count("r") == 49
    assert len(outcome["rounds"]) == 50
    assert outcome["rounds"][-1]["prescriptions"] == []


def test_lower_candidate_restores_the_best_reference_and_report():
    """A failed experiment must not replace the best coarse world."""
    initial = _reference()
    expected_best = copy.deepcopy(initial)

    def observe(ref):
        score = 70.0 if not ref.get("revisions") else 50.0
        return _blocked_report(
            check="composition",
            actual=score,
            finding_check="E_SUBJECT_AREA_OVERFLOW",
        )

    outcome = run_coarse_revision_loop(
        reference=initial,
        report_loader=observe,
        rebuild=lambda _ref: None,
        restore_best=lambda _ref: None,
        proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=5,
    )

    assert outcome["status"] == "blocked"
    assert outcome["reference"] == expected_best
    assert outcome["report"]["checks"][0]["actual"] == 70.0
    assert outcome["latest_report"]["checks"][0]["actual"] == 50.0
    assert outcome["rollback_count"] >= 1


def test_failed_loop_blocks_without_agent_provider():
    """粗排修正是 Agent 提案，不得由循环偷偷调用确定性处方器冒充。"""
    from block_director.cinema import coarse_loop

    from block_director.cinema import coarse_loop

    assert not hasattr(coarse_loop, "build_coarse_prescriptions")

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _ref: _blocked_report(),
        rebuild=lambda _ref: None,
        max_revisions=3,
    )

    assert outcome["status"] == "blocked"
    assert "Agent" in outcome["blocked_reason"]
    assert "provider" in outcome["blocked_reason"].lower()


def test_loop_calls_agent_provider_with_observation_and_applies_proposal():
    requests = []

    def provider(request):
        requests.append(request)
        return {
            "schema_version": "coarse-proposal/v1",
            "provider_kind": "test_agent",
            "reason": "角色落位偏离主体参考",
            "prescriptions": [{
                "prescription_id": "agent_push_in",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": -0.5, "y": 4.9, "z": 2.0},
                    "target": {"x": -0.2, "y": 0.0, "z": 0.8},
                },
                "reason": "构图读数低于阈值",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    sequence = iter([_blocked_report(), _pass_report()])
    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=lambda _ref: next(sequence),
        rebuild=lambda _ref: None,
        proposal_provider=provider,
        knowledge_context="硬约束：主体应在三分线内",
        max_revisions=2,
    )

    assert outcome["status"] == "approved"
    assert len(requests) == 1
    assert requests[0].round_no == 1
    assert requests[0].knowledge_context == "硬约束：主体应在三分线内"
    assert requests[0].report["verdict"] == "fail"
    assert outcome["rounds"][0]["provider_kind"] == "test_agent"
    assert outcome["rounds"][0]["proposal"]["reason"] == "角色落位偏离主体参考"
    assert outcome["rounds"][0]["prescriptions"][0]["applied"] is True
    assert outcome["reference"]["revisions"][0]["prescriptions"][0][
        "prescription_id"] == "agent_push_in"


def test_agent_after_rollback_sees_the_physical_best_reference():
    requests = []

    def observe(reference):
        position = reference["camera_intents"][0]["position"]
        score = 50.0 if abs(position[1] - 2.7) < 1e-6 else 70.0
        return _blocked_report(
            check="composition",
            actual=score,
            finding_check="E_SUBJECT_AREA_OVERFLOW",
        )

    def provider(request):
        requests.append(copy.deepcopy(request.reference))
        return {
            "schema_version": "coarse-proposal/v1",
            "provider_kind": "test_agent",
            "reason": "测试回滚后的真实状态",
            "prescriptions": [{
                "prescription_id": "agent_push_in",
                "scope": "camera",
                "shot_id": "shot_001",
                "entity": "cam_shot_001",
                "component": "distance",
                "target_value": {
                    "position": {"x": -0.5, "y": 2.7, "z": 2.0},
                    "target": {"x": -0.2, "y": 0.0, "z": 0.8},
                },
                "reason": "构图读数低于阈值",
                "evidence_refs": ["composition:shot_001"],
            }],
        }

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=observe,
        rebuild=lambda _reference: None,
        restore_best=lambda _reference: None,
        proposal_provider=provider,
        max_revisions=4,
        no_gain_limit=3,
    )

    assert outcome["status"] == "blocked"
    assert len(requests) >= 2, outcome["rounds"]
    assert requests[1]["camera_intents"][0]["position"] == [
        -0.5, 5.5, 2.0,
    ]
