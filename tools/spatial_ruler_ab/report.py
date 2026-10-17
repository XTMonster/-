"""实验运行器与报告（spec §15.2/15.3/15.5）。

run_experiment：逐任务逐臂跑判官 -> 评分 -> 聚合 delta -> 全量转录。
同一判官同一参数两次运行逐字节相同（确定性红线）。
```
"""
from __future__ import annotations

import json
import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from tools.spatial_ruler_ab.arms import DEMO_ACTION_TOOL_SCHEMAS
from tools.spatial_ruler_ab.tasks_new import (
    battery_fingerprint,
    build_new_tasks,
)
from tools.spatial_ruler_ab.scoring import score_task
from block_director.cinema.metric_registry import (
    LAYERS,
    LAYER_WEIGHTS_DEFAULT,
    METRICS_BY_NAME,
)


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


def _task_layer(task) -> str:
    """任务归属层：新任务用 payload.layer；既有任务按 kind 确定性映射。"""
    layer = getattr(task, "payload", {}).get("layer")
    if layer:
        return str(layer)
    if task.scene_id == "fight_01" or task.kind == "dynamic_facts":
        return "action"
    if task.kind in {"verdict", "estimate", "direction", "fix",
                     "prescription_verdict"}:
        return "geometry"
    if task.kind == "priority_order":
        # 跨层修复优先级任务归鲁棒性/工程层（SPEC §4.5 工程层口径）。
        return "robustness"
    return "unassigned"


def _merge_battery(battery: List[Any]) -> List[Any]:
    """幂等合并四类新任务：按 task.id 去重，使 CLI 与调用方都跑完整电池。"""
    seen = {t.id for t in battery}
    return list(battery) + [t for t in build_new_tasks() if t.id not in seen]


def _fingerprint(battery, judge) -> Dict[str, Any]:
    """运行指纹：任务集 sha256 + 指标 schema sha256 + 权重 + 场景版本。"""
    metric_payload = [{
        "name": spec.name, "severity": spec.severity,
        "target": spec.target, "gates": list(spec.links_to_gates),
        "layer": spec.layer,
    } for spec in sorted(METRICS_BY_NAME.values(), key=lambda s: s.name)]
    scenes = sorted({t.scene_id for t in battery})
    return {
        "task_set_sha256": hashlib.sha256(
            battery_fingerprint(battery).encode("utf-8")).hexdigest(),
        "metric_schema_sha256": hashlib.sha256(
            json.dumps(metric_payload, ensure_ascii=False,
                       sort_keys=True).encode("utf-8")).hexdigest(),
        "layer_weights": dict(LAYER_WEIGHTS_DEFAULT),
        "scenes_version": scenes,
        "schema": "spatial_ruler_ab/report+task11 v1",
        "judge": {
            "name": getattr(judge, "name", "unknown"),
            "model": getattr(judge, "model", None),
            "evidence_grade": getattr(judge, "evidence_grade", "unknown"),
        },
    }


def _layer_scores(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """六层分：每层每臂 {correct,total,score}；无任务的层 score=None。"""
    out: Dict[str, Any] = {}
    for layer in LAYERS:
        layer_rows = [r for r in rows if r["task_layer"] == layer]
        out[layer] = {}
        for arm in _ARMS:
            arm_rows = [r for r in layer_rows if r["arm"] == arm]
            total = len(arm_rows)
            correct = sum(1 for r in arm_rows if r["correct"])
            out[layer][arm] = {
                "total": total, "correct": correct,
                "score": round(correct / total * 100.0, 2) if total else None,
            }
    return out


def _hard_gates(battery) -> Dict[str, Any]:
    """H1–H6：任务 payload.gates + 层级 gate_probe_evidence 聚合触发/不触发。"""
    from tools.spatial_ruler_ab.tasks_new import gate_probe_evidence
    evidence = gate_probe_evidence()
    gates: Dict[str, Any] = {}
    for gate in ("H1", "H2", "H3", "H4", "H5", "H6"):
        hits = [(t.id, reason)
                for t in battery
                for gate_id, reason in (t.payload.get("gates") or {}).items()
                if gate_id == gate]
        ev = [e for e in evidence if e["gate"] == gate]
        layer_hits = [(f"layer:{e['source_metric']}/{e['state']}", e["reason"])
                      for e in ev if e["triggered"]]
        not_ev = [e for e in ev if not e["triggered"]]
        all_hits = hits + layer_hits
        gates[gate] = {
            "triggered": bool(all_hits),
            "tasks": sorted({tid for tid, _ in all_hits}),
            "reasons": sorted({reason for _, reason in all_hits if reason}),
            "not_triggered_tasks": sorted(
                {f"layer:{e['source_metric']}/{e['state']}" for e in not_ev}),
        }
    return gates


def _three_questions(arms: Dict[str, Dict[str, Any]],
                     delta: Dict[str, Any]) -> Dict[str, Any]:
    """按指标回答三问：提升 / 牺牲 / 相邻镜头破坏。"""
    kinds = sorted(set(arms["baseline"].get("by_kind", {}))
                   | set(arms["ruler_method"].get("by_kind", {})))
    out: Dict[str, Any] = {}
    for kind in kinds:
        d = delta["ruler_method_vs_baseline"]["by_kind"].get(kind, 0.0)
        seq_family = kind in {"continuity_verdict", "robustness_verdict",
                              "dynamic_facts"}
        out[kind] = {
            "improved": d > 1e-9,
            "sacrificed": d < -1e-9,
            "adjacent_damage": bool(d < -1e-9) if seq_family else None,
        }
    return out


def _ci(delta: Dict[str, Any], arms: Dict[str, Dict[str, Any]],
        judge) -> Dict[str, Any]:
    """四臂 delta 的 95% 正态近似置信区间；mock 判官不计算。"""
    if getattr(judge, "evidence_grade", "") != "ab_result":
        return {"value": None, "only_for_real_judge": True}
    out: Dict[str, Any] = {}
    for name, block in delta.items():
        p_rm = block["overall"]
        p_b = _arm_ratio(arms, "baseline")
        n_rm = arms["ruler_method"].get("total", 0)
        n_b = arms["baseline"].get("total", 0)
        if n_rm == 0 or n_b == 0:
            out[name] = {"delta": p_rm - p_b, "ci95": None}
            continue
        se = math.sqrt(max(p_rm * (1 - p_rm) / n_rm, 0.0)
                       + max(p_b * (1 - p_b) / n_b, 0.0))
        diff = p_rm - p_b
        out[name] = {
            "delta": round(diff, 4),
            "ci95": [round(diff - 1.96 * se, 4),
                     round(diff + 1.96 * se, 4)] if se > 0 else None,
        }
    return {"value": out, "only_for_real_judge": True}


def _uncovered(rows: List[Dict[str, Any]], battery) -> Dict[str, Any]:
    """未覆盖层、低置信任务与跨层任务清单。"""
    covered = {r["task_layer"] for r in rows}
    uncovered_layers = [layer for layer in LAYERS if layer not in covered]
    low_conf = [{
        "task_id": t.id,
        "kind": t.kind,
        "confidence": t.ground_truth.get("confidence"),
    } for t in battery
        if isinstance(t.ground_truth, dict)
        and isinstance(t.ground_truth.get("confidence"), (int, float))
        and t.ground_truth["confidence"] < 1.0]
    cross_layer = [t.id for t in battery
                   if t.payload.get("cross_layer")]
    return {
        "layers_without_tasks": uncovered_layers,
        "low_confidence_tasks": low_conf,
        "cross_layer_tasks": cross_layer,
    }


def _confidence(battery) -> Dict[str, Any]:
    """低置信与需人工复核任务清单（SPEC §10）。"""
    low = [{
        "task_id": t.id,
        "kind": t.kind,
        "confidence": t.ground_truth.get("confidence"),
    } for t in battery
        if isinstance(t.ground_truth, dict)
        and isinstance(t.ground_truth.get("confidence"), (int, float))
        and t.ground_truth["confidence"] < 1.0]
    manual = [t.id for t in battery
              if t.payload.get("sample_state") == "ambiguous"
              or t.payload.get("gates")]
    return {
        "low_confidence_tasks": low,
        "manual_review_required": sorted(set(manual)),
    }


def _raw_measurements(battery) -> Dict[str, Any]:
    """每镜每帧原始测量与证据引用（SPEC §10）。"""
    records = []
    for t in battery:
        meas = t.payload.get("measurements") or []
        records.append({
            "task_id": t.id,
            "kind": t.kind,
            "layer": _task_layer(t),
            "evidence_ref": t.payload.get("evidence_ref"),
            "measurements": meas,
            "prompt_embedded": not meas,
        })
    return {"tasks": len(records), "records": records}


def _poison_rejected(task, answer) -> bool:
    """污染任务判定：answer 未跟从 poison_wrong 即为拒绝（留痕）。"""
    wrong = task.payload.get("poison_wrong")
    if wrong is None:
        return False
    if isinstance(wrong, dict):
        return not all(answer.get(k) == v for k, v in wrong.items())
    if isinstance(wrong, list):
        return list(answer.get("priority") or []) != [str(x) for x in wrong]
    return True


def _bad_repaired(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """bad→repaired 分量变化：bad 样例任务在每臂的正确率（模拟修复采纳）。"""
    out: Dict[str, Any] = {}
    for arm in _ARMS:
        # 真实 bad 样例的修复采纳用 transcript 中 bad 状态任务计数：
        bad_rows = [r for r in rows
                    if r["arm"] == arm and r["kind"] == "fix"]
        total = len(bad_rows)
        correct = sum(1 for r in bad_rows if r["correct"])
        out[arm] = {
            "fix_total": total,
            "fix_correct": correct,
            "repair_rate": round(correct / total, 4) if total else None,
        }
    return out


def _accept_reject(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """agent 回答与处方接受/拒绝：prescription_verdict 任务的 accept 对拍。"""
    out: Dict[str, Any] = {}
    for arm in _ARMS:
        rows_arm = [r for r in rows
                    if r["arm"] == arm and r["kind"] == "prescription_verdict"]
        total = len(rows_arm)
        accepted = sum(1 for r in rows_arm
                       if r.get("answer", {}).get("accept") is True)
        rejected = sum(1 for r in rows_arm
                       if r.get("answer", {}).get("accept") is False)
        out[arm] = {
            "total": total, "accepted": accepted, "rejected": rejected,
            "correct": sum(1 for r in rows_arm if r["correct"]),
        }
    return out


def _prescriptions(rows: List[Dict[str, Any]],
                   battery: List[Any]) -> Dict[str, Any]:
    """处方任务明细：分量 / agent 接受 / 对拍 / 是否下毒。"""
    by_id = {t.id: t for t in battery}
    out: Dict[str, Any] = {}
    for arm in _ARMS:
        rows_arm = [r for r in rows
                    if r["arm"] == arm and r["kind"] == "prescription_verdict"]
        out[arm] = [{
            "task_id": r["task_id"],
            "component": by_id[r["task_id"]].payload.get("component")
            if r["task_id"] in by_id else None,
            "accept": r.get("answer", {}).get("accept"),
            "correct": r["correct"],
            "poisoned": bool(r.get("poisoned")),
        } for r in rows_arm]
    return out


def _fight_section(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """打斗样例动作层独立小节（fight_01 场景的 action 层任务）。"""
    out: Dict[str, Any] = {}
    fight_rows = [r for r in rows
                  if r["scene_id"] == "fight_01"
                  and r["task_layer"] in ("action", "unassigned")]
    for arm in _ARMS:
        arm_rows = [r for r in fight_rows if r["arm"] == arm]
        total = len(arm_rows)
        correct = sum(1 for r in arm_rows if r["correct"])
        out[arm] = {
            "total": total, "correct": correct,
            "score": round(correct / total * 100.0, 2) if total else None,
        }
    return out


def run_experiment(judge, battery, timestamp: str) -> Dict[str, Any]:
    """跑完整 2×2 实验；返回含 arms/delta/transcript 的报告 dict。"""
    battery = _merge_battery(battery)
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
                "task_layer": _task_layer(task),
                "poisoned": bool(task.payload.get("poisoned")),
                "poison_rejected": _poison_rejected(task, answer),
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
        "fingerprint": _fingerprint(battery, judge),
        "layer_scores": _layer_scores(rows),
        "hard_gates": _hard_gates(battery),
        "three_questions": _three_questions(arms, delta),
        "ci": _ci(delta, arms, judge),
        "uncovered": _uncovered(rows, battery),
        "confidence": _confidence(battery),
        "raw_measurements": _raw_measurements(battery),
        "bad_repaired": _bad_repaired(rows),
        "accept_reject": _accept_reject(rows),
        "prescriptions": _prescriptions(rows, battery),
        "fight_section": _fight_section(rows),
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

    fp = report.get("fingerprint", {})
    lines.append("## 运行指纹")
    lines.append("")
    lines.append(f"- task_set_sha256：`{fp.get('task_set_sha256', '')}`")
    lines.append(f"- metric_schema_sha256：`{fp.get('metric_schema_sha256', '')}`")
    lines.append(f"- 层权重：`{fp.get('layer_weights', {})}`")
    lines.append(f"- 场景集版本：`{fp.get('scenes_version', [])}`")
    lines.append(f"- 报告 schema：`{fp.get('schema', '')}`")
    lines.append("")

    ls = report.get("layer_scores", {})
    lines.append("## 六层分")
    lines.append("")
    lines.append("| 层 | 基线 | 尺子 | 方法 | 方法+尺子 |")
    lines.append("|---|---|---|---|---|")
    for layer, arms_scores in ls.items():
        cells = []
        for arm in ("baseline", "ruler", "method", "ruler_method"):
            s = arms_scores.get(arm, {})
            score = s.get("score")
            cell = f"{score:.2f}" if score is not None else "（无任务）"
            cells.append(cell)
        lines.append(f"| {layer} | " + " | ".join(cells) + " |")
    lines.append("")

    hg = report.get("hard_gates", {})
    lines.append("## 硬门（H1–H6）触发理由")
    lines.append("")
    for gate, info in hg.items():
        if info["triggered"]:
            lines.append(f"- **{gate} 触发**：任务 {info['tasks']}；理由："
                         f"{'；'.join(info['reasons'])}；"
                         f"不触发样例 {info.get('not_triggered_tasks', [])}")
        else:
            lines.append(f"- {gate}：未触发"
                         f"（无评测任务覆盖该硬门）；"
                         f"不触发样例 {info.get('not_triggered_tasks', [])}")
    lines.append("")

    br = report.get("bad_repaired", {})
    lines.append("## bad → repaired（修复采纳率，mock=plumbing 演示）")
    lines.append("")
    for arm, info in br.items():
        rate = info.get("repair_rate")
        rate_s = f"{rate:.4f}" if rate is not None else "（无 fix 任务）"
        lines.append(f"- {arm}：fix 正确 {info['fix_correct']}/{info['fix_total']}"
                     f" = {rate_s}")
    lines.append("")

    ar = report.get("accept_reject", {})
    lines.append("## agent 对处方的接受/拒绝")
    lines.append("")
    for arm, info in ar.items():
        lines.append(f"- {arm}：接受 {info['accepted']} / 拒绝 {info['rejected']}"
                     f" / 对拍正确 {info['correct']} / {info['total']}")
    lines.append("")

    tq = report.get("three_questions", {})
    lines.append("## 三问：提升 / 牺牲 / 相邻镜头破坏")
    lines.append("")
    for kind, verdict in tq.items():
        lines.append(f"- {kind}：提升={verdict['improved']}，"
                     f"牺牲={verdict['sacrificed']}，"
                     f"相邻破坏={verdict['adjacent_damage']}")
    lines.append("")

    uc = report.get("uncovered", {})
    lines.append("## 未覆盖与低置信项")
    lines.append("")
    lines.append(f"- 无任务的层：{uc.get('layers_without_tasks', [])}")
    lines.append(f"- 低置信任务：{uc.get('low_confidence_tasks', [])}")
    lines.append(f"- 跨层任务（不并入六层分）："
                 f"{uc.get('cross_layer_tasks', [])}")
    lines.append("")

    conf = report.get("confidence", {})
    lines.append("## 置信度与人工复核")
    lines.append("")
    lines.append(f"- 低置信任务数：{len(conf.get('low_confidence_tasks', []))}")
    for item in conf.get("low_confidence_tasks", []):
        lines.append(f"  - {item['task_id']}（confidence={item.get('confidence')}）")
    lines.append(f"- 需人工复核：{conf.get('manual_review_required', [])}")
    lines.append("")

    rm = report.get("raw_measurements", {})
    lines.append("## 每镜每帧原始测量与证据引用")
    lines.append("")
    lines.append(f"- 覆盖任务数：{rm.get('tasks', 0)}")
    for rec in rm.get("records", []):
        meas = rec.get("measurements") or []
        if not meas:
            continue
        bits = []
        for m in meas:
            if "severity_level" in m:
                bits.append(f"{m['metric']}={m['severity_level']}")
            else:
                bits.append(
                    f"{m['metric']}={m['raw_value']}(目标 {m['target']},"
                    f"置信 {m['confidence']})")
        lines.append(
            f"- {rec['task_id']}（{rec['kind']}，层 {rec['layer']}）"
            f" 证据引用={rec.get('evidence_ref')}；"
            f"测量 {len(meas)} 条：" + "；".join(bits))
    lines.append("")

    fs = report.get("fight_section", {})
    lines.append("## 打斗样例动作层独立小节（不并入总分）")
    lines.append("")
    for arm, info in fs.items():
        score = info.get("score")
        score_s = f"{score:.2f}" if score is not None else "（无任务）"
        lines.append(f"- {arm}：{info['correct']}/{info['total']} = {score_s}")
    lines.append("")

    poison_rows = [r for r in report.get("transcript", [])
                   if r.get("poisoned")]
    if poison_rows:
        lines.append("## 污染判词留痕")
        lines.append("")
        for row in poison_rows:
            lines.append(
                f"- {row['task_id']} [{row['arm']}] "
                f"poison_rejected={row.get('poison_rejected')}，"
                f"正确={row['correct']}")
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
