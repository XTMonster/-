"""Ticket 05（纯层）：粗排修正循环在硬伤清空后必须继续修构图软指标。

final16b 真跑回归：粗排 gate 只看 error finding，构图 55–58 被当软指标
放行冻结；但细排 gate 要求构图分严格 >80（detail_review 单一真源）。
细排不重建空间，于是冻结时构图不足 = 细排永远 blocked = 白模视频永远
出不来。

本测试钉住循环契约：**硬伤清空后构图 fail 也必须让循环继续走处方收敛**，
不许在构图未达标时直接 approved 冻结（那是不降级的前提）；构图 fail+
处方产生实质位移时不得提前 blocked（未空转）。处方由调用方注入的
``report_loader`` 模拟"观察到的构图分随机位变化"。
"""

from __future__ import annotations

import copy

from block_director.cinema.coarse_loop import run_coarse_revision_loop
from block_director.layer5_orchestrator.coarse_agent import (
    OfflineFixtureCoarseProposalProvider,
)


def _reference():
    return {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "market",
        "characters": [
            {"name": "米迦尔", "position": {"x": 1.0653, "y": 1.8, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [{
            "shot_id": "shot_001", "position": [0.0, 7.66, 1.31],
            "target": [0.0, 1.8, 1.31], "lens": 85.0,
            "fov_deg": 20.0, "movement": None,
            "provenance": "script_declaration", "resolved": True,
        }],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 84,
            "intent": "手部特写", "characters": ["米迦尔"],
            "actions": [],
            "framing_target": {"kind": "character", "ref": "米迦尔",
                               "part": "hand", "anchor_offset": None},
        }],
        "revisions": [],
        "notes": [],
    }


def _soft_fail_report(actual: float):
    """硬伤全清、仅构图 fail 的观察报告（真实 final16b 形态）。"""
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "abc", "verdict": "fail",
        "findings": [],
        "checks": [{
            "check_id": "composition", "shot_id": "shot_001",
            "actual": actual, "threshold": 80.0, "verdict": "fail",
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


def test_hard_clear_but_composition_fail_still_converges_soft():
    """硬伤清空、构图仍 fail：循环必须继续走构图处方，不提前 approved。

    该镜 camera_intents[0] 沿视线推近后拟合成分 57→85；同时维持观察
    报告里无 error finding。循环应在构图达标后 approved，且 revisions
    里出现 distance/in 处方应用过（证明构图修整真的跑到了）。
    """
    import json

    def report_loader(reference):
        cam = reference["camera_intents"][0]
        distance = abs(cam["position"][1] - cam["target"][1])
        score = 57.0 + max(0.0, (5.86 - distance)) * 14.0
        if score > 80.0:
            return _pass_report()
        #: 构图 fail 时把距离差折算成处方能读懂的报告
        return _soft_fail_report(round(score, 1))

    def rebuild(reference):
        #: 处方应用已经写回 reference（纯层）；rebuild 只记录
        return None

    outcome = run_coarse_revision_loop(
        reference=_reference(),
        report_loader=report_loader,
        rebuild=rebuild,
            proposal_provider=OfflineFixtureCoarseProposalProvider(),
        max_revisions=10,
    )
    assert outcome["status"] == "approved", outcome.get("blocked_reason")
    assert outcome["report"]["verdict"] == "pass"
    #: 现在的实现会在硬伤清空、构图 fail 时直接 approved——本断言钉死这个
    #: 缺口：构图未达标不允许冻结（修复后这里必须成立）。
    applied_distance = []
    for revision in outcome["reference"].get("revisions") or []:
        for record in revision.get("prescriptions") or []:
            if record.get("applied") and record.get("component") == "distance":
                applied_distance.append(record)
    assert applied_distance, (
        "硬伤清空后构图 fail 必须继续应用构图处方收敛；"
        "当前实现直接 approved，白模视频会永远卡在细排。")
