"""实验运行器与报告（spec §15.2/15.3/15.5）。

run_experiment：逐任务逐臂跑判官 -> 评分 -> 聚合 delta -> 全量转录。
同一判官同一参数两次运行逐字节相同（确定性红线）。
```
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from tools.spatial_ruler_ab.arms import DEMO_ACTION_TOOL_SCHEMAS
from tools.spatial_ruler_ab.scoring import score_task


_ARMS = ("baseline", "ruler", "method", "ruler_method")

_ARM_PROMPT = {
    "baseline": lambda t: t.baseline_prompt,
    "ruler": lambda t: t.ruler_prompt,
    "method": lambda t: t.method_prompt,
    "ruler_method": lambda t: t.ruler_method_prompt,
}


def _arm_overall(arms: Dict[str, Dict[str, Any]], arm: str,
                 kind: str = "__all__") -> float:
    if kind == "__all__":
        return arms.get(arm, {}).get("overall", 0.0)
    return arms.get(arm, {}).get("by_kind", {}).get(kind, {}).get("overall", 0.0)


def _arm_ratio(arms: Dict[str, Dict[str, Any]], arm: str,
               kind: str = "__all__") -> float:
    """用整数计数算原始正确率（不 round），保证增量分解恒等式严格成立。"""
    if kind == "__all__":
        agg = arms.get(arm, {})
    else:
        agg = arms.get(arm, {}).get("by_kind", {}).get(kind, {})
    if not agg or not agg.get("total"):
        return 0.0
    return agg["correct"] / agg["total"]


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"total": len(rows), "correct": 0, "by_kind": {}}
    for r in rows:
        out["correct"] += 1 if r["correct"] else 0
        kind = r["kind"]
        bucket = out["by_kind"].setdefault(
            kind, {"total": 0, "correct": 0, "overall": 0.0})
        bucket["total"] += 1
        bucket["correct"] += 1 if r["correct"] else 0
    out["overall"] = round(out["correct"] / out["total"], 4) if out["total"] else 0.0
    for bucket in out["by_kind"].values():
        bucket["overall"] = round(bucket["correct"] / bucket["total"], 4) \
            if bucket["total"] else 0.0
    return out


def run_experiment(judge, battery, timestamp: str) -> Dict[str, Any]:
    """跑完整 2×2 实验；返回含 arms/delta/transcript 的报告 dict。"""
    rows: List[Dict[str, Any]] = []
    for task in battery:
        for arm in _ARMS:
            prompt = _ARM_PROMPT[arm](task)
            answer = judge.answer(task, prompt, arm)
            verdict = score_task(
                {"kind": task.kind, "ground_truth": task.ground_truth,
                 "schemas": DEMO_ACTION_TOOL_SCHEMAS}, answer)
            rows.append({
                "task_id": task.id,
                "arm": arm,
                "kind": task.kind,
                "scene_id": task.scene_id,
                "question": task.question,
                "prompt": prompt,
                "answer": answer,
                "correct": verdict["correct"],
                "detail": verdict["detail"],
            })

    arms = {arm: _aggregate([r for r in rows if r["arm"] == arm])
            for arm in _ARMS}
    def _by_kind_delta(high: str, low: str) -> Dict[str, float]:
        return {
            kind: (_arm_ratio(arms, high, kind)
                   - _arm_ratio(arms, low, kind))
            for kind in sorted(set(arms[high].get("by_kind", {}))
                               | set(arms[low].get("by_kind", {})))
        }

    delta = {
        # 读数增量：有读数 vs 无读数（都无数值方法基线）
        "ruler_vs_baseline": {
            "overall": _arm_ratio(arms, "ruler")
                       - _arm_ratio(arms, "baseline"),
            "by_kind": _by_kind_delta("ruler", "baseline"),
        },
        # 方法论增量：有方法 vs 无方法（都无数值）
        "method_vs_baseline": {
            "overall": _arm_ratio(arms, "method")
                       - _arm_ratio(arms, "baseline"),
            "by_kind": _by_kind_delta("method", "baseline"),
        },
        # 方法论+读数 vs 纯读数：方法在读数之上再加多少
        "ruler_method_vs_ruler": {
            "overall": _arm_ratio(arms, "ruler_method")
                       - _arm_ratio(arms, "ruler"),
            "by_kind": _by_kind_delta("ruler_method", "ruler"),
        },
        # 方法论+读数 vs 纯方法：读数在方法之上再加多少
        "ruler_method_vs_method": {
            "overall": _arm_ratio(arms, "ruler_method")
                       - _arm_ratio(arms, "method"),
            "by_kind": _by_kind_delta("ruler_method", "method"),
        },
        # 总增量
        "ruler_method_vs_baseline": {
            "overall": _arm_ratio(arms, "ruler_method")
                       - _arm_ratio(arms, "baseline"),
            "by_kind": _by_kind_delta("ruler_method", "baseline"),
        },
        # 交互增量 = 总 − 读数 − 方法
        "ruler_method_vs_sum": {
            "overall": (
                _arm_ratio(arms, "ruler_method")
                - _arm_ratio(arms, "ruler")
                - _arm_ratio(arms, "method")
                + _arm_ratio(arms, "baseline")),
            "by_kind": {
                kind: (
                    _arm_ratio(arms, "ruler_method", kind)
                    - _arm_ratio(arms, "ruler", kind)
                    - _arm_ratio(arms, "method", kind)
                    + _arm_ratio(arms, "baseline", kind))
                for kind in sorted(set(arms["ruler_method"].get("by_kind", {}))
                                   | set(arms["ruler"].get("by_kind", {}))
                                   | set(arms["method"].get("by_kind", {}))
                                   | set(arms["baseline"].get("by_kind", {})))
            },
        },
    }
    judge_info = {
        "name": getattr(judge, "name", "unknown"),
        "model": getattr(judge, "model", None),
        "evidence_grade": getattr(judge, "evidence_grade", "unknown"),
    }
    return {
        "timestamp": timestamp,
        "judge": judge_info,
        "arms": arms,
        "delta": delta,
        "transcript": rows,
    }


def build_report(judge, battery, timestamp: str) -> Dict[str, Any]:
    """与 run_experiment 同义：spec §15.5 模块名也叫 report。"""
    return run_experiment(judge, battery, timestamp)


def render_markdown(report: Dict[str, Any]) -> str:
    a = report["arms"]
    d = report["delta"]
    lines = [
        f"# 空间尺外挂 A/B 评测（{report['timestamp']}）",
        "",
        f"- 判官：`{report['judge']['name']}`"
        f"{(' / ' + str(report['judge']['model'])) if report['judge']['model'] else ''}"
        f"（evidence_grade=`{report['judge']['evidence_grade']}`）",
        f"- 基线臂总正确率：`{report['arms']['baseline']['overall']:.4f}`"
        f"（{a['baseline']['correct']}/{a['baseline']['total']}）",
        f"- 尺子臂总正确率：`{report['arms']['ruler']['overall']:.4f}`"
        f"（{a['ruler']['correct']}/{a['ruler']['total']}）",
        f"- 方法臂总正确率：`{a['method']['overall']:.4f}`"
        f"（{a['method']['correct']}/{a['method']['total']}）",
        f"- 方法+读数臂总正确率：`{a['ruler_method']['overall']:.4f}`"
        f"（{a['ruler_method']['correct']}/{a['ruler_method']['total']}）",
        "",
        "## 2×2 增量分解",
        "",
        f"- 读数增量（ruler − baseline）：`{d['ruler_vs_baseline']['overall']:+.4f}`",
        f"- 方法论增量（method − baseline）：`{d['method_vs_baseline']['overall']:+.4f}`",
        f"- 总增量（ruler_method − baseline）：`{d['ruler_method_vs_baseline']['overall']:+.4f}`",
        f"- 交互增量：`{d['ruler_method_vs_sum']['overall']:+.4f}`",
        f"- 读数之上的方法增量（ruler_method − ruler）："
        f"`{d['ruler_method_vs_ruler']['overall']:+.4f}`",
        f"- 方法之上的读数增量（ruler_method − method）："
        f"`{d['ruler_method_vs_method']['overall']:+.4f}`",
        "",
        "## 按任务族",
        "",
        "| 任务族 | 基线 | 尺子 | 方法 | 方法+尺子 | 读数增量 | 方法论增量 | 总增量 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    kinds = sorted(set(a["baseline"].get("by_kind", {}))
                   | set(a["ruler"].get("by_kind", {}))
                   | set(a["method"].get("by_kind", {}))
                   | set(a["ruler_method"].get("by_kind", {})))
    for kind in kinds:
        b = a["baseline"]["by_kind"].get(kind, {})
        r = a["ruler"]["by_kind"].get(kind, {})
        m = a["method"]["by_kind"].get(kind, {})
        rm = a["ruler_method"]["by_kind"].get(kind, {})
        lines.append(
            f"| {kind} | {b.get('overall', 0.0):.4f}"
            f"（{b.get('correct', 0)}/{b.get('total', 0)}）"
            f" | {r.get('overall', 0.0):.4f}"
            f"（{r.get('correct', 0)}/{r.get('total', 0)}）"
            f" | {m.get('overall', 0.0):.4f}"
            f"（{m.get('correct', 0)}/{m.get('total', 0)}）"
            f" | {rm.get('overall', 0.0):.4f}"
            f"（{rm.get('correct', 0)}/{rm.get('total', 0)}）"
            f" | {d['ruler_vs_baseline']['by_kind'].get(kind, 0.0):+.4f}"
            f" | {d['method_vs_baseline']['by_kind'].get(kind, 0.0):+.4f}"
            f" | {d['ruler_method_vs_baseline']['by_kind'].get(kind, 0.0):+.4f} |")
    lines.append("")
    if report["judge"]["evidence_grade"] == "plumbing":
        lines.append("> ⚠️ mock 判官只证明管线通，**不是**效果证据。")
        lines.append("> 真实结论只能来自 `--judge real`（evidence_grade=`ab_result`）。")
    return "\n".join(lines)


def write_report(report: Dict[str, Any], out_dir: Path) -> Dict[str, str]:
    """落盘 report.json / report.md / transcript.jsonl，返回三个路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    tsv_path = out_dir / "transcript.jsonl"
    json_path.write_text(
        json.dumps({k: v for k, v in report.items() if k != "transcript"},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    md_path.write_text(render_markdown(report) + "\n", encoding="utf-8")
    with tsv_path.open("w", encoding="utf-8") as fh:
        for row in report["transcript"]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"json": str(json_path), "md": str(md_path),
            "transcript": str(tsv_path)}


def default_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
