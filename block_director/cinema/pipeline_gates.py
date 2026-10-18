"""白模预演完整流程：PipelineGate 状态机 + 粗排基准冻结（Ticket 03，纯层）。

纯层（不 import bpy）。把完整流程切成分阶段 gate，保证：

* 粗排 fail 不流过下一阶段（修正循环回退到 COARSE_REFERENCE_READY）；
* 基准未冻结禁止细排；
* 细排/序列未通过禁止 final；
* 冻结产物含指纹，冻结后机位/走位漂移 -> ``E_BLOCKOUT_APPROVAL_REQUIRED``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from block_director.contracts.audit import canonical_fingerprint
from block_director.contracts.blockout import (
    E_BLOCKOUT_APPROVAL_REQUIRED,
    approval_required_findings,
    camera_fingerprint,
    manifest_fingerprint,
)
from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)

COARSE_BASELINE_SCHEMA_VERSION = "coarse-baseline/v1"


class PipelinePhase:
    """完整流程的阶段常量（单一真源）。"""

    SCRIPT_UNDERSTOOD = "SCRIPT_UNDERSTOOD"
    COARSE_REFERENCE_READY = "COARSE_REFERENCE_READY"
    BLOCKOUT_BUILT = "BLOCKOUT_BUILT"
    COARSE_OBSERVED = "COARSE_OBSERVED"
    COARSE_APPROVED = "COARSE_APPROVED"
    BASELINE_FROZEN = "BASELINE_FROZEN"
    SHOT_TABLE_READY = "SHOT_TABLE_READY"
    DETAIL_BLOCKING = "DETAIL_BLOCKING"
    DETAIL_REVIEWED = "DETAIL_REVIEWED"
    SEQUENCE_REVIEWED = "SEQUENCE_REVIEWED"
    FINAL_EXPORTED = "FINAL_EXPORTED"


_PHASE_CHAIN = [
    PipelinePhase.SCRIPT_UNDERSTOOD,
    PipelinePhase.COARSE_REFERENCE_READY,
    PipelinePhase.BLOCKOUT_BUILT,
    PipelinePhase.COARSE_OBSERVED,
    PipelinePhase.COARSE_APPROVED,
    PipelinePhase.BASELINE_FROZEN,
    PipelinePhase.SHOT_TABLE_READY,
    PipelinePhase.DETAIL_BLOCKING,
    PipelinePhase.DETAIL_REVIEWED,
    PipelinePhase.SEQUENCE_REVIEWED,
    PipelinePhase.FINAL_EXPORTED,
]


def can_transition(current: str, target: str) -> bool:
    """状态机跃迁：主链每次前进一格；COARSE_OBSERVED 可回退修正。

    回退只允许 COARSE_OBSERVED -> COARSE_REFERENCE_READY（粗排 fail 进入
    修正循环）；其余回退、跳格、自环一律禁止。
    """
    if current == target:
        return False
    if (current == PipelinePhase.COARSE_OBSERVED
            and target == PipelinePhase.COARSE_REFERENCE_READY):
        return True
    try:
        idx = _PHASE_CHAIN.index(current)
    except ValueError:
        return False
    return (idx + 1 < len(_PHASE_CHAIN)
            and _PHASE_CHAIN[idx + 1] == target)


def coarse_gate(report: Mapping[str, Any]) -> Dict[str, Any]:
    """粗排 gate：BlockoutReport 无 error finding（硬伤）。

    构图/遮挡/出画等软指标按项目裁决保留为细排提示（T07），不阻塞粗排；
    verdict 是全 checks 口径，不作为粗排 gate 依据。
    """
    reasons: List[str] = []
    errors = [f for f in (report.get("findings") or [])
              if isinstance(f, Mapping) and f.get("severity") == "error"]
    if errors:
        reasons.append(f"粗排存在 {len(errors)} 条 error finding，未修正不进入细排")
    return {"passed": not reasons, "reasons": reasons}


def freeze_coarse_baseline(
    *,
    reference: Mapping[str, Any],
    manifest: Mapping[str, Any],
    report: Mapping[str, Any],
    approvals: Sequence[Mapping[str, Any]],
    approved_by: str,
    approved_at: str,
    checkpoint_id: str = "scene_01_blockout.blend",
) -> Dict[str, Any]:
    """粗排通过后冻结基准：reference+manifest+report+审批+指纹。"""
    approval = dict(approvals[-1]) if approvals else None
    return {
        "schema_version": COARSE_BASELINE_SCHEMA_VERSION,
        "state": "frozen",
        "checkpoint_id": str(checkpoint_id),
        "produced_at": str(approved_at),
        "approved_by": str(approved_by),
        "reference_fingerprint": coarse_reference_content_fingerprint(
            reference),
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "cameras_fingerprint": camera_fingerprint(manifest),
        "report_fingerprint": canonical_fingerprint(report),
        "approval": approval,
        "reference": dict(reference),
        "manifest": dict(manifest),
        "report": dict(report),
    }


def baseline_drift_findings(
    baseline: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """冻结后机位/走位漂移检查：复用审批必需 finding。

    冻结的 approval 记录与当前 manifest 的 cameras 指纹不一致 ->
    ``E_BLOCKOUT_APPROVAL_REQUIRED`` finding（不可静默改）。
    """
    approval = baseline.get("approval")
    if not isinstance(approval, Mapping):
        return [{
            "check_id": E_BLOCKOUT_APPROVAL_REQUIRED,
            "severity": "error",
            "message": "基准未含审批记录，机位/走位变更被阻塞",
        }]
    return list(approval_required_findings(approval, manifest))


def final_gate(
    *,
    coarse_pass: bool,
    baseline_frozen: bool,
    detail_results: Mapping[str, bool],
    sequence_verdict: str,
) -> Dict[str, Any]:
    """final gate：粗排过 + 冻结 + 逐镜细排全过 + 序列过，才允许导出 final。"""
    reasons: List[str] = []
    if not coarse_pass:
        reasons.append("粗排未通过")
    if not baseline_frozen:
        reasons.append("粗排基准未冻结")
    failed_shots = [sid for sid, ok in (detail_results or {}).items()
                    if not ok]
    if failed_shots:
        reasons.append(f"细排未全部通过：{failed_shots}")
    if sequence_verdict != "pass":
        reasons.append("序列审查未通过")
    return {"passed": not reasons, "reasons": reasons}


__all__ = [
    "PipelinePhase", "can_transition", "coarse_gate",
    "freeze_coarse_baseline", "baseline_drift_findings", "final_gate",
    "COARSE_BASELINE_SCHEMA_VERSION", "E_BLOCKOUT_APPROVAL_REQUIRED",
]
