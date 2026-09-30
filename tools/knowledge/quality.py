"""P14-5 的质量闭环：把 Q0–Q7 与 E1–E3 收进一份**可审计的证据**里。

分工（不重复造轮子）：

* **Q1–Q7** 由 :mod:`tools.holdout_score` 算（它读 held-out 与索引，判据写死），
  本模块只是**聚合**，不另写一套口径；
* **Q0**（构建门）由 `knowledge/hypergraph.manifest.json` 的四个计数与
  `knowledge/hypergraph.rejects.jsonl` 的**实际行数**对拍后判定——
  两边对不上就是账不对，判 fail；
* **E1/E2/E3**（§2.3b 经验层）：
  - **E3 经验越权率** 只读索引：`source_kind == "experience"` 的边**不得**带
    `forbid`（§2.3b 关键纪律 1；能带 forbid 的只有显式 `lesson`）。它**永远可判**；
  - **E1 经验引用相关性** 是"人工对返回的 cases 按 ≥4/5 打分"，agent 不能代替，
    没有人工打分时记 `not_measured`（**不得**判通过）；
  - **E2 经验采纳率** 需要一次真实运行的 `shots.json`（`movements[].source ∈
    {experience, lesson, case}` 的镜头数 / held-out 镜头数）。没给 `--shots` 就记
    `not_measured`；它是诊断量，**不设门**。

退出码：0 全过／1 有 fail／2 有 not_measured（§4.1b 硬规则 1：缺证据不得当通过）。

用法::

  python tools/knowledge/quality.py --run-id 20260930-060000
  python tools/knowledge/quality.py --cases knowledge/cases.jsonl --shots <run>/export/shots.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.holdout_score import load_graph, load_holdout, score_entries  # noqa: E402

PASS, FAIL, NA = "pass", "fail", "not_measured"


def q0_build_gate(manifest_path: Path, rejects_path: Path) -> Dict[str, Any]:
    """构建门：`rejects/raw <= 5%` 且 `processed == total`，且账目与 rejects 文件对得上。"""
    detail: Dict[str, Any] = {"source": str(manifest_path)}
    if not manifest_path.is_file():
        return {"id": "Q0", "status": NA, "note": "缺 hypergraph.manifest.json：构建门无证据"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = int(manifest.get("raw_edges") or 0)
    rejects = int(manifest.get("rejects") or 0)
    valid = int(manifest.get("valid_unique") or 0)
    duplicates = int(manifest.get("duplicates") or 0)
    detail.update({"raw_edges": raw, "valid_unique": valid,
                   "duplicates": duplicates, "rejects": rejects})
    if rejects_path.is_file():
        actual = sum(1 for line in rejects_path.read_text(encoding="utf-8").split("\n")
                     if line.strip())
        detail["rejects_file_lines"] = actual
        if actual != rejects:
            return {"id": "Q0", "status": FAIL,
                    "note": f"账不对：manifest 说 rejects={rejects}，"
                            f"rejects 文件实际 {actual} 行", **detail}
    if raw <= 0 or valid <= 0:
        return {"id": "Q0", "status": FAIL,
                "note": "分母为 0（raw_edges/valid_unique）：按 §4.1b 硬规则 1 判失败",
                **detail}
    # processed == total：manifest 顶层没有这两个键时，用 per-chunk 状态现算
    total = manifest.get("total_chunks")
    processed = manifest.get("processed_chunks")
    if processed is None or total is None:
        batches = manifest.get("batches") or []
        total = len(batches)
        processed = sum(1 for b in batches
                        if str(b.get("status") or "") in ("done", "rejected"))
    detail.update({"processed_chunks": processed, "total_chunks": total})
    ratio = rejects / raw
    detail["reject_ratio"] = round(ratio, 6)
    ok = ratio <= 0.05 and int(processed) == int(total) and int(total) > 0
    return {"id": "Q0", "status": PASS if ok else FAIL,
            "note": ("rejects/raw <= 5% 且 processed == total"
                     if ok else "构建门未过（rejects>5% 或 processed != total）"),
            **detail}


def e3_experience_override(graph) -> Dict[str, Any]:
    """E3 硬门：经验边**不得**带 forbid（只有显式 lesson 可以）。"""
    offenders: List[str] = []
    experience = 0
    for edge in graph.edges:
        if str(edge.source_kind) != "experience":
            continue
        experience += 1
        forbidden = [m for m in edge.members if str(m.role) == "forbid"]
        if forbidden:
            offenders.append(edge.edge_id)
    return {"id": "E3", "status": PASS if not offenders else FAIL,
            "numerator": len(offenders), "denominator": experience,
            "value": 0 if not offenders else None, "line": 0,
            "note": ("经验边（source_kind=experience）单独产生的 forbid 条数必须为 0"
                     if not offenders else f"越权的边：{offenders[:5]}")}


def e3_cases(cases_path: Optional[Path]) -> Dict[str, Any]:
    """L3 侧的 E3：案例**结构上**不能带约束；文件层面再核一遍。"""
    if cases_path is None or not Path(cases_path).is_file():
        return {"id": "E3_cases", "status": NA,
                "note": "没有 knowledge/cases.jsonl：L3 侧无证据"}
    rows = [json.loads(line) for line in Path(cases_path).read_text(
        encoding="utf-8").split("\n") if line.strip()]
    bad = [row.get("case_id") for row in rows
           if any(key in row for key in ("forbid", "forbids", "constraint"))]
    return {"id": "E3_cases", "status": PASS if not bad else FAIL,
            "numerator": len(bad), "denominator": len(rows),
            "line": 0, "note": ("L3 案例永不产出约束" if not bad
                                else f"带约束字段的案例：{bad[:5]}")}


def e2_adoption(shots_path: Optional[Path]) -> Dict[str, Any]:
    """E2 经验采纳率（诊断量，不设门）。"""
    if shots_path is None or not Path(shots_path).is_file():
        return {"id": "E2", "status": NA,
                "note": "没有 --shots：采纳率无法测量（诊断量，不设门）"}
    payload = json.loads(Path(shots_path).read_text(encoding="utf-8"))
    shots = payload.get("shots") if isinstance(payload, dict) else payload
    shots = shots or []
    adopted = 0
    for shot in shots:
        for movement in shot.get("movements") or []:
            if str(movement.get("source") or "") in ("experience", "lesson", "case"):
                adopted += 1
                break
    return {"id": "E2", "status": NA, "diagnostic": True,
            "numerator": adopted, "denominator": len(shots),
            "value": round(adopted / len(shots), 4) if shots else None,
            "note": f"命中人工期望的镜头数 / {len(shots)}（记录，不设门）"}


def e1_relevance(reviews_path: Optional[Path]) -> Dict[str, Any]:
    """E1 经验引用相关性（必须人工打分，agent 不能代替）。"""
    if reviews_path is None or not Path(reviews_path).is_file():
        return {"id": "E1", "status": NA,
                "note": "需要人工对返回的 cases 按 >=4/5 打分（§2.3b）；"
                        "没有 --e1-reviews 就不判——不得由 agent 代判"}
    rows = [json.loads(line) for line in Path(reviews_path).read_text(
        encoding="utf-8").split("\n") if line.strip()]
    scored = [row for row in rows if isinstance(row.get("score"), (int, float))]
    good = [row for row in scored if float(row["score"]) >= 4]
    if not scored:
        return {"id": "E1", "status": FAIL, "note": "打分文件为空：分母为 0 判失败"}
    value = len(good) / len(scored)
    return {"id": "E1", "status": PASS if value >= 0.70 else FAIL,
            "numerator": len(good), "denominator": len(scored),
            "value": round(value, 4), "line": 0.70}


def q4_build_gate(q_report: Dict[str, Any]) -> Dict[str, Any]:
    """§2.3 Q6b 前置①：标注的 required 边必须能在索引里逐条找到。

    这条判据**不能**由 Q1/Q2/Q4 代替：`score_entries` 把解析不到的 `must` 从
    required 分母里剔掉，于是"oracle 与索引不同构"只会让分母变好看，不会被报出来。
    按 §2.3（以及 §4.1b 硬规则 1）这里必须单独记账：分母为 0 判失败，
    有任何一条 required 边不存在也判失败。
    """
    total = int(q_report.get("must_total") or 0)
    unresolved = int(q_report.get("required_unresolved") or 0)
    if total <= 0:
        return {"id": "Q4_pre_required_edges_exist", "status": FAIL,
                "numerator": 0, "denominator": 0,
                "note": "must 总数为 0：按 §4.1b 硬规则 1 判失败"}
    return {
        "id": "Q4_pre_required_edges_exist", "status": FAIL if unresolved else PASS,
        "numerator": total - unresolved, "denominator": total,
        "value": round((total - unresolved) / total, 4),
        "line": 1.0,
        "note": (f"§2.3 Q6b 前置①：{unresolved}/{total} 条 must 在索引里找不到"
                 f"对应边（oracle 与索引不同构 → 索引构建失败）"
                 if unresolved else
                 f"§2.3 Q6b 前置①：{total} 条 must 全部能在索引里找到对应边"),
        "examples": q_report.get("unresolved_examples") or [],
    }


def build_report(*, run_id: str, holdout: Path, nodes: Path, edges: Path,
                 manifest: Path, rejects: Path, cases: Optional[Path],
                 shots: Optional[Path], e1_reviews: Optional[Path],
                 top_k: int, token_limit: int) -> Dict[str, Any]:
    graph = load_graph(ROOT / nodes, ROOT / edges)
    entries = load_holdout(ROOT / holdout)
    metrics: List[Dict[str, Any]] = [q0_build_gate(ROOT / manifest, ROOT / rejects)]

    if not entries:
        metrics.append({"id": "Q1-Q7", "status": NA,
                        "note": "held-out 为空：Q1–Q7 无法判定（不得判通过）"})
        q_report: Dict[str, Any] = {}
    else:
        q_report = score_entries(entries, graph, top_k=top_k,
                                 token_limit=token_limit)
        metrics.extend(q_report["metrics"])
        # §2.3 的 Q6b 前置①（构建期覆盖门）：标注的 required 边必须在索引里真的存在，
        # 否则"索引构建失败"。它是一条**独立于 Q1/Q4** 的判据：Q4 的分母会随不可解析
        # 的 must 一起缩小，所以只看 Q4 会漏掉"oracle 与索引不同构"这件事本身。
        metrics.append(q4_build_gate(q_report))

    metrics.append(e3_experience_override(graph))
    metrics.append(e3_cases(cases))
    metrics.append(e1_relevance(e1_reviews))
    metrics.append(e2_adoption(shots))

    statuses = {m["status"] for m in metrics}
    overall = FAIL if FAIL in statuses else (NA if NA in statuses else PASS)
    return {"run_id": run_id, "overall": overall,
            "holdout_entries": len(entries), "index_edges": len(graph.edges),
            "metrics": metrics,
            "q_summary": {k: v for k, v in q_report.items() if k != "metrics"}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-quality")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--nodes", default="knowledge/hypergraph.nodes.jsonl")
    parser.add_argument("--edges", default="knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--manifest", default="knowledge/hypergraph.manifest.json")
    parser.add_argument("--rejects", default="knowledge/hypergraph.rejects.jsonl")
    parser.add_argument("--cases", default="knowledge/cases.jsonl")
    parser.add_argument("--shots", default="")
    parser.add_argument("--e1-reviews", default="")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--token-limit", type=int, default=2000)
    parser.add_argument("--out", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    run_id = args.run_id or "adhoc"
    report = build_report(
        run_id=run_id, holdout=Path(args.holdout), nodes=Path(args.nodes),
        edges=Path(args.edges), manifest=Path(args.manifest),
        rejects=Path(args.rejects),
        cases=Path(args.cases) if args.cases else None,
        shots=Path(args.shots) if args.shots else None,
        e1_reviews=Path(args.e1_reviews) if args.e1_reviews else None,
        top_k=args.top_k, token_limit=args.token_limit)

    target = Path(args.out) if args.out else ROOT / "docs" / "evidence" / run_id / "knowledge_quality.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for metric in report["metrics"]:
            print(f"[{metric['status']:>13}] {metric['id']}: {metric.get('note', '')}")
        print(f"overall: {report['overall']}  -> {target}")
    return 0 if report["overall"] == PASS else (2 if report["overall"] == NA else 1)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
