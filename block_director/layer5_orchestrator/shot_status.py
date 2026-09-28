"""分镜列表的状态推导（执行文档 v1.2 §13.2 的"状态"列）。

纯计算：输入分镜计划与驱动器的审核历史，输出每个镜头的一行状态。放在
layer5（不依赖 bpy）是为了能在 pytest 里直接断言——UI 只负责画出来。

状态的优先级（从高到低）：失败 → 降级 → 已修复 → 已生成 → 待生成。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..contracts.audit import AuditResult
from ..contracts.plan import Plan

STATUS_PENDING = "待生成"
STATUS_GENERATED = "已生成"
STATUS_REPAIRED = "已修复"
STATUS_FAILED = "失败"
STATUS_DEGRADED = "降级"


def _intent_summary(intent: str, limit: int = 24) -> str:
    text = " ".join(str(intent or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def shot_statuses(plan: Optional[Plan],
                  audit_results: Sequence[AuditResult] = (),
                  *, built_shot_ids: Iterable[str] = (),
                  degraded: str = "") -> List[Dict[str, Any]]:
    """返回与 ``plan.shots`` 一一对应的状态行。"""
    if plan is None or not plan.shots:
        return []

    built = {str(shot_id) for shot_id in built_shot_ids}
    audits: Dict[str, List[AuditResult]] = {}
    for result in audit_results:
        audits.setdefault(str(result.target), []).append(result)

    rows: List[Dict[str, Any]] = []
    for shot in plan.shots:
        history = audits.get(shot.shot_id, [])
        failures = sum(1 for item in history if not item.passed)
        last = history[-1] if history else None

        if last is not None and not last.passed:
            status = STATUS_FAILED
        elif not history and degraded:
            status = STATUS_DEGRADED
        elif last is not None and last.passed and failures:
            status = STATUS_REPAIRED
        elif shot.shot_id in built or history:
            status = STATUS_GENERATED
        else:
            status = STATUS_PENDING

        rows.append({
            "shot_id": shot.shot_id,
            "status": status,
            "intent": _intent_summary(shot.intent),
            "shot_type": str(shot.shot_type),
            "duration_frames": shot.duration_frames,
            "seconds": round(max(int(shot.duration_frames), 1) / 24.0, 1),
            "audits": len(history),
            "failures": failures,
            "score": last.score if last is not None else None,
            "suggestions": list(last.suggestions) if last is not None else [],
            "passed": bool(last.passed) if last is not None else None,
        })
    return rows


def summary_line(rows: Sequence[Dict[str, Any]]) -> str:
    """一行汇总，给面板标题/日志用。"""
    if not rows:
        return "还没有分镜"
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    order = (STATUS_FAILED, STATUS_DEGRADED, STATUS_REPAIRED,
             STATUS_GENERATED, STATUS_PENDING)
    parts = [f"{key} {counts[key]}" for key in order if counts.get(key)]
    return f"共 {len(rows)} 镜：" + " / ".join(parts)
