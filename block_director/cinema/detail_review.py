"""逐镜细排审核判定（Ticket 06，纯层，不 import bpy）。

细排阶段不改变冻结空间：逐镜审核 = 无空间漂移 error + 无粗排硬伤 error +
构图分严格高于门槛。全镜 ok 才允许序列回放与 final gate。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from block_director.cinema.detail_blocking import (
    identity_freeze_review,
    spatial_drift_review,
)
from block_director.contracts.quality import (
    COMPOSITION_PASS_SCORE,
    composition_decision,
)


def detail_review_verdict(
    *,
    detail_shots: List[Mapping[str, Any]],
    blockout_report: Mapping[str, Any],
    baseline: Mapping[str, Any],
    plan: Any = None,
) -> Dict[str, Any]:
    """逐镜细排审核，返回 ``{per_shot, all_ok, reasons}``。"""
    per_shot: Dict[str, Dict[str, Any]] = {}
    drift_findings = spatial_drift_review(detail_shots, baseline)
    identity_findings = identity_freeze_review(
        detail_shots=detail_shots, plan=plan) if plan is not None else []
    findings = list(blockout_report.get("findings") or [])
    checks = list(blockout_report.get("checks") or [])
    reasons: List[str] = []

    for shot in detail_shots:
        shot_id = str(shot.get("shot_id") or "")
        drift = [f for f in drift_findings
                 if str(f.get("shot_id") or "") == shot_id
                 and f.get("severity") == "error"]
        identity = [f for f in identity_findings
                    if str(f.get("shot_id") or "") == shot_id]
        errors = [f for f in findings
                  if str(f.get("shot_id") or "") == shot_id
                  and f.get("severity") == "error"]
        composition = next((c for c in checks
                            if str(c.get("shot_id") or "") == shot_id
                            and c.get("check_id") == "composition"), None)
        comp_actual = composition.get("actual") \
            if isinstance(composition, Mapping) else None
        empty_evidence = any(
            str(check.get("check_id") or "") == "empty_shot"
            and str(check.get("shot_id") or "") == shot_id
            and str(check.get("verdict") or "") in {"pass", "exempt"}
            for check in checks
        )
        composition_result = composition_decision(
            comp_actual,
            empty_shot_declared=empty_evidence,
            empty_shot_evidence=empty_evidence,
        )
        ok = (not drift and not identity and not errors
              and composition_result["status"] in {"pass", "exempt"})
        per_shot[shot_id] = {
            "ok": ok,
            "drift": len(drift),
            "identity": len(identity),
            "errors": len(errors),
            "composition": comp_actual,
            "composition_status": composition_result["status"],
            "composition_reason": composition_result["reason"],
            "composition_warning": composition_result["status"] not in {
                "pass", "exempt"},
        }
        if not ok:
            reasons.append(
                f"{shot_id}：细排未通过（drift={len(drift)}，"
                f"identity={len(identity)}，errors={len(errors)}，"
                f"composition={comp_actual}）")
    return {"per_shot": per_shot,
            "all_ok": all(v["ok"] for v in per_shot.values()),
            "reasons": reasons}


__all__ = ["detail_review_verdict", "COMPOSITION_PASS_SCORE"]
