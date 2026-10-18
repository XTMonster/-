"""逐镜细排审核判定（Ticket 06，纯层，不 import bpy）。

细排阶段不改变冻结空间：逐镜审核 = 无空间漂移 error + 无粗排硬伤 error +
构图可测（软指标记录 warning 不阻塞，按项目裁决 T07）。全镜 ok 才允许
序列回放与 final gate。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from block_director.cinema.detail_blocking import spatial_drift_review

COMPOSITION_PASS_SCORE = 80.0


def detail_review_verdict(
    *,
    detail_shots: List[Mapping[str, Any]],
    blockout_report: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    """逐镜细排审核，返回 ``{per_shot, all_ok, reasons}``。"""
    per_shot: Dict[str, Dict[str, Any]] = {}
    drift_findings = spatial_drift_review(detail_shots, baseline)
    findings = list(blockout_report.get("findings") or [])
    checks = list(blockout_report.get("checks") or [])
    reasons: List[str] = []

    for shot in detail_shots:
        shot_id = str(shot.get("shot_id") or "")
        drift = [f for f in drift_findings
                 if str(f.get("shot_id") or "") == shot_id
                 and f.get("severity") == "error"]
        errors = [f for f in findings
                  if str(f.get("shot_id") or "") == shot_id
                  and f.get("severity") == "error"]
        composition = next((c for c in checks
                            if str(c.get("shot_id") or "") == shot_id
                            and c.get("check_id") == "composition"), None)
        comp_actual = composition.get("actual") \
            if isinstance(composition, Mapping) else None
        ok = (not drift and not errors and comp_actual is not None)
        per_shot[shot_id] = {
            "ok": ok,
            "drift": len(drift),
            "errors": len(errors),
            "composition": comp_actual,
            "composition_warning": (
                comp_actual is not None
                and float(comp_actual) < COMPOSITION_PASS_SCORE),
        }
        if not ok:
            reasons.append(
                f"{shot_id}：细排未通过（drift={len(drift)}，"
                f"errors={len(errors)}，composition={comp_actual}）")
    return {"per_shot": per_shot,
            "all_ok": all(v["ok"] for v in per_shot.values()),
            "reasons": reasons}


__all__ = ["detail_review_verdict", "COMPOSITION_PASS_SCORE"]
