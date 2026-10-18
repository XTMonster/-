"""粗排修正循环驱动器（Ticket 05 纯层骨架，不 import bpy）。

``observe -> coarse gate -> fail(处方) -> 修改粗排参考 JSON -> rebuild ->
re-observe``，直到 gate 通过或显式超轮阻塞。bpy 的重建/渲染由调用方经
``rebuild`` 回调注入，循环本身纯层可测。
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Mapping

from block_director.cinema.coarse_revision import (
    apply_coarse_prescriptions,
    build_coarse_prescriptions,
)
from block_director.cinema.pipeline_gates import coarse_gate

DEFAULT_MAX_REVISIONS = 3


def run_coarse_revision_loop(
    *,
    reference: Mapping[str, Any],
    report_loader: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    rebuild: Callable[[Mapping[str, Any]], None],
    max_revisions: int = DEFAULT_MAX_REVISIONS,
    fps: int = 24,
) -> Dict[str, Any]:
    """跑粗排修正循环，返回 outcome。

    ``outcome`` 键：``status``（approved / blocked）、``reference``（当前参考
    JSON）、``report``（最新报告）、``rounds``（每轮
    ``{round_no, report, prescriptions}``）、``blocked_reason``（blocked 时）。

    循环契约：

    * 每轮先 ``report_loader(reference)`` 观察；
    * ``coarse_gate`` 通过 -> approved（不再重建）；
    * 不通过且未超轮 -> ``build_coarse_prescriptions`` + ``apply``（只改参考
      JSON）-> ``rebuild(reference)`` 重建 -> 下一轮；
    * 超轮仍未通过 -> blocked（不降级通过）。
    """
    current = copy.deepcopy(reference)
    rounds: List[Dict[str, Any]] = []
    for round_no in range(1, max_revisions + 1):
        report = dict(report_loader(current))
        gate = coarse_gate(report)
        if gate["passed"]:
            return {
                "status": "approved",
                "reference": current,
                "report": report,
                "rounds": rounds,
                "blocked_reason": "",
            }
        if round_no >= max_revisions:
            return {
                "status": "blocked",
                "reference": current,
                "report": report,
                "rounds": rounds,
                "blocked_reason": (
                    f"达到修正轮数上限（{max_revisions} 轮）仍未通过粗排 gate："
                    + "；".join(gate["reasons"] or ["存在 error finding"])),
            }
        prescriptions = build_coarse_prescriptions(
            report=report, reference=current, only_hard=True)
        current, records = apply_coarse_prescriptions(
            current, prescriptions,
            revision_id=f"coarse-round-{round_no}", round_no=round_no)
        rounds.append({
            "round_no": round_no,
            "report": report,
            "prescriptions": records,
            "applied_count": sum(1 for r in records if r["applied"]),
        })
        rebuild(current)
    return {
        "status": "blocked",
        "reference": current,
        "report": report,
        "rounds": rounds,
        "blocked_reason": "粗排修正循环异常退出（不应到达）",
    }


__all__ = ["run_coarse_revision_loop", "DEFAULT_MAX_REVISIONS"]
