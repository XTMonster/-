"""交付失败清单的纯内容组装（缺陷 D / T8，U1）。

单镜连续无新高被记为 ``failed`` 后，收尾交付不能假装这镜通过：纯层按
``terminal_shots`` 折出 ``failures[]``（镜号 / 最高分 / 无新高轮数 / 原因），
README 用同源数据渲染失败段；``renderable_shot_ids`` 只跳过已有导出文件的镜。
failed 镜仍渲染最佳版本，并同时进入 ``delivered_shots``、排除在
``passed_shots`` 之外（D3：不造假通过，构图分必须严格高于 80）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ..contracts.quality import (
    COMPOSITION_PASS_SCORE,
    COMPOSITION_PASS_TEXT,
    composition_decision,
)

#: 失败清单载荷的 schema 版本（与 runtime_world / spatial 快照同风格）。
FAILURES_SCHEMA = "delivery-failures/v1"

#: 门槛说明文案里的阈值。真实门槛单一真源在
#: ``contracts/quality.py`` 的 ``COMPOSITION_PASS_SCORE``；这里只引用
#: 契约导出的文本用于 README 说明，不定义第二个门。
PASS_SCORE_TEXT = COMPOSITION_PASS_TEXT

#: 这些终态都表示"盘上可以留下尽力产物，但审核身份绝不算 pass"。
#: ``finished`` 由模型 ``finish_shot`` 声明产生；``unverified``/``unfinished``
#: 是审核或墙钟收尾没有形成通过结论。它们单列 ``pending_review``，不混入
#: 真正的 ``failed`` 清单，也绝不进入 ``passed_shots``。
PENDING_REVIEW_STATUSES = ("finished", "unverified", "unfinished")


def build_failures_payload(
    *,
    terminal_shots: Mapping[str, str],
    best_scores: Optional[Mapping[str, Mapping[str, Any]]] = None,
    no_gain: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """从终态表折出失败清单（确定性排序，只收 ``failed``）。

    - ``terminal_shots``：镜号 → 终态（``failed`` 才进清单）；
    - ``best_scores``：镜号 → ``{"score": ...}``（回溯阶段的最高分）；
    - ``no_gain``：镜号 → 连续无新高轮数（>= 3 触发 fail）。

    已过镜 / 已降级 / 未审核镜绝不进 ``failures[]``；没有任何 failed 镜时
    返回 ``{"schema_version": ..., "failures": []}``（零形状差）。
    """
    best_scores = best_scores or {}
    no_gain = no_gain or {}
    failures: List[Dict[str, Any]] = []
    pending_review: List[Dict[str, Any]] = []
    for shot_id in sorted(str(k) for k in terminal_shots):
        status = str(terminal_shots[shot_id])
        if status in PENDING_REVIEW_STATUSES:
            best = dict(best_scores.get(shot_id) or {})
            best_score = float(best.get("score") or 0.0)
            pending_review.append({
                "shot_id": shot_id,
                "status": status,
                "best_score": best_score,
                "no_gain_rounds": int(no_gain.get(shot_id, 0) or 0),
                "reason": {
                    "finished": "模型声明完成，但审核未通过；需复核，不能计入通过镜头",
                    "unverified": "该镜未完成审核；需复核，不能计入通过镜头",
                    "unfinished": "该镜未形成通过终态（墙钟/预算收尾）；需复核，不能计入通过镜头",
                }[status],
            })
            continue
        if status != "failed":
            continue
        best = dict(best_scores.get(shot_id) or {})
        best_score = float(best.get("score") or 0.0)
        rounds = int(no_gain.get(shot_id, 0) or 0)
        #: 文案必须与数字一致：best > 门槛说明该镜**曾过线**但最终终态仍为
        #: failed（如过线版带硬性违规未被采用，或过线后版本被后续审核否决
        #: 且未保持）——不许再写"未达到 80 分门槛"这种与数字矛盾的话。
        if composition_decision(best_score)["status"] == "pass":
            reason = (
                f"连续 {rounds} 轮无新高（最高分 {best_score:.1f}，曾过线"
                f"但未以通过终态保持），按 D2 记为失败继续")
        else:
            reason = (
                f"连续 {rounds} 轮无新高（最高分 {best_score:.1f}），"
                f"未达到严格高于 {PASS_SCORE_TEXT} 分的门槛，按 D2 记为失败继续")
        failures.append({
            "shot_id": shot_id,
            "best_score": best_score,
            "no_gain_rounds": rounds,
            "reason": reason,
        })
    payload: Dict[str, Any] = {
        "schema_version": FAILURES_SCHEMA,
        "failures": failures,
    }
    if pending_review:
        payload["pending_review"] = pending_review
    return payload


def render_failures_markdown(
    failures: Sequence[Mapping[str, Any]],
) -> str:
    """README 失败清单段；空清单渲染空串（零行为差，不发明段落）。"""
    items = list(failures)
    if not items:
        return ""
    lines = [
        "## 失败清单",
        "",
        "以下镜头未通过构图门槛（其最佳版本已尽力产出并标记 failed，"
        "不视为已过镜）：",
        "",
        f"- 门槛：单镜审核分必须严格高于 {PASS_SCORE_TEXT} 分才计入已过镜成片；"
        "回溯 3 轮无新高即记为失败并继续下一镜（D2）；失败镜照常产出"
        "最佳版本参考视频，但绝不伪装成通过。",
        "",
        "| 镜头 | 最高分 | 无新高轮数 | 原因 |",
        "| --- | ---: | ---: | --- |",
    ]
    for item in items:
        lines.append(
            f"| {item.get('shot_id')} | "
            f"{float(item.get('best_score') or 0.0):.1f} "
            f"| {int(item.get('no_gain_rounds') or 0)} "
            f"| {item.get('reason') or ''} |")
    lines.append("")
    return "\n".join(lines)


def render_pending_review_markdown(
    pending_review: Sequence[Mapping[str, Any]],
) -> str:
    """README 待复核段：流程结束但质量未通过，不能计入已过镜。"""
    items = list(pending_review)
    if not items:
        return ""
    lines = [
        "## 待复核镜头（质量未通过）",
        "",
        "以下镜头已有流程终态，但审核未形成通过结论；可出片供审阅，"
        "但不视为已过镜，也不得进入通过集合。",
        "",
        "| 镜头 | 终态 | 最高分 | 原因 |",
        "| --- | --- | ---: | --- |",
    ]
    for item in items:
        lines.append(
            f"| {item.get('shot_id')} | {item.get('status') or 'unknown'} "
            f"| {float(item.get('best_score') or 0.0):.1f} "
            f"| {item.get('reason') or ''} |")
    lines.append("")
    return "\n".join(lines)


def renderable_shot_ids(
    all_ids: Iterable[str],
    *,
    delivered: Iterable[str] = (),
    failed_ids: Iterable[str] = (),
) -> List[str]:
    """成片渲染集合：只排除已交付镜；failed 镜**照常渲染**最佳版本
    （U6/U1：白模预演视频一定要生成），其失败身份由交付报告的
    ``failed`` 标记与失败清单保留，不视为已过镜。"""
    delivered = {str(s) for s in delivered}
    return [str(shot_id) for shot_id in all_ids
            if str(shot_id) not in delivered]


def delivered_shot_ids(report_shots: Iterable[Mapping[str, Any]]) -> List[str]:
    """从交付报告折出**已有导出文件**的镜：``video`` 非空即算。

    这里只回答"盘上有没有片"，不回答"是否通过"：failed 镜也会照常产出
    最佳版本 mp4，必须写入断点，否则 resume 会重复渲染且账本与磁盘不一致。
    是否通过由 :func:`passed_shot_ids` 从同一份报告另行派生。
    """
    seen: set[str] = set()
    delivered: List[str] = []
    for item in report_shots or []:
        if not isinstance(item, dict):
            continue
        video = item.get("video")
        if not video:
            continue
        shot_id = str(item.get("shot_id") or "")
        if shot_id and shot_id not in seen:
            seen.add(shot_id)
            delivered.append(shot_id)
    return delivered


def passed_shot_ids(report_shots: Iterable[Mapping[str, Any]]) -> List[str]:
    """从交付报告折出**既已出片、又未标 failed** 的镜头。

    这是 ``delivered_shots`` 的通过子集，用于对外报告"多少镜真正过门"；
    它不替代断点的 ``delivered_shots``，也不改变"构图分严格高于 80"
    这一失败门槛。
    """
    passed: List[str] = []
    for item in report_shots or []:
        if not isinstance(item, dict):
            continue
        if (not item.get("video") or bool(item.get("failed"))
                or bool(item.get("pending_review"))):
            continue
        shot_id = str(item.get("shot_id") or "")
        if shot_id:
            passed.append(shot_id)
    return passed


def pending_review_shot_ids(
    report_shots: Iterable[Mapping[str, Any]],
) -> List[str]:
    """从交付报告折出需复核镜头（即使该镜没有 mp4 也照样报告）。"""
    pending: List[str] = []
    for item in report_shots or []:
        if not isinstance(item, dict) or not item.get("pending_review"):
            continue
        shot_id = str(item.get("shot_id") or "")
        if shot_id:
            pending.append(shot_id)
    return pending
