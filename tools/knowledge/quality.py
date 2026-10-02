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
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.holdout_score import load_graph, load_holdout, score_entries  # noqa: E402

PASS, FAIL, NA = "pass", "fail", "not_measured"

#: §4.1b 的 Q5 第一步：夹具里带 `expect_movements` 的条目下界。不足时 Q5 记
#: `not_measured`（**不得判通过**）——它的分母是"真实模型跑出来的同 q 镜头数"，
#: 夹具没有这条标注就无从 join。
MIN_Q5_FIXTURE_ITEMS = 30

#: `ShotContract.constraint_query()` / `shot_constraint_query()` 真正会产出的键。
#: 只有 `q` 的键**全部**落在这里的条目才可能与真实运行的计划镜头 join 上——
#: 这是 §4.1b 的 Q5 join 判据（"键值对集合相等"）的直接推论。
PLAN_QUERY_KEYS: Tuple[str, ...] = ("景别", "镜头", "运镜", "动作", "特效", "对白")


def _normalise_query_pairs(text: str) -> frozenset:
    """`键=值；键=值` → 归一化后的 `{(键, 值)}` 集合。

    归一化口径与 §4.1b 的 Q5 行逐字对应：**去空格 / 全半角 / 别名**。
    `VALUE_ALIASES` 是索引侧唯一那份别名表（`static` → `固定`、`甩镜` → `whip_pan`），
    两边都用它，join 才不会因为一边写引擎名、一边写中文别名而永远错开。
    """
    from block_director.knowledge.hypergraph import VALUE_ALIASES  # noqa: PLC0415

    pairs = set()
    for chunk in str(text or "").replace(";", "；").split("；"):
        if "=" not in chunk:
            continue
        key, _, raw = chunk.partition("=")
        key = unicodedata.normalize("NFKC", key).strip()
        value = unicodedata.normalize("NFKC", raw).strip().replace(" ", "")
        if not key or not value:
            continue
        pairs.add((key, VALUE_ALIASES.get(value, value)))
    return frozenset(pairs)


class _ShotView:
    """`shots.json` 的一条记录 → `shot_constraint_query()` 吃的那个形状。

    字段来源（`delivery/manifest.py::_movements_payload` 定死）：
    `shot_type` 是景别、`camera.lens` 是计划排的焦距、`movements[].kind` 是引擎运镜名、
    `action_types[]` 是动作类型、`dialogue_ids[]` 非空即"这一镜有对白"。
    **不在这里重写契约串**——一律交给同一个生产者
    （`layer5_orchestrator/scene_contract.py::shot_constraint_query`），
    否则量的是"复刻的查询"而不是"真实发出的查询"。
    """

    def __init__(self, record: Dict[str, Any]) -> None:
        camera = (record or {}).get("camera") or {}
        movements = []
        for raw in (record or {}).get("movements") or []:
            kind = (raw.get("kind") or raw.get("type")) if isinstance(raw, dict) else raw
            if kind:
                movements.append({"type": str(kind)})
        self.shot_type = str((record or {}).get("shot_type") or "")
        self.camera: Dict[str, Any] = {"lens": camera.get("lens"),
                                       "movements": movements}
        self.actions = [{"action_type": str(item)}
                        for item in ((record or {}).get("action_types") or [])]
        self.vfx = list((record or {}).get("vfx") or [])
        self.dialogues = [{}] if (record or {}).get("dialogue_ids") else []


def plan_query_of_shot(record: Dict[str, Any]) -> str:
    """一条 `shots.json` 记录 → 这一镜真实发出的契约串。"""
    from block_director.layer5_orchestrator.scene_contract import (  # noqa: PLC0415
        shot_constraint_query,
    )

    return shot_constraint_query(_ShotView(record))


def q5_run_join(entries: List[Dict[str, Any]], shots_path) -> Dict[str, Any]:
    """Q5 的**第二步**：把入库计划的逐镜查询与 held-out 的 `q` join 起来。

    §4.1b 的 Q5 行写死了 join 判据：**键值对集合相等**。这里同时报三个数：

    * `denominator`——按**规格的相等判据**匹配到的镜头数（这是 Q5 的分母）；
    * `subset_denominator`——把判据放宽成"本条 `q` ⊆ 本镜查询"时的镜头数
      （**只作诊断**，不是判据：它回答"如果改 join 关系能救回多少"）；
    * `plan_queries`——真实发出的契约串的去重清单，用来证明"不是没跑对，"
      "是两边根本不在同一个键空间里"。
    """
    if not shots_path or not Path(shots_path).is_file():
        return {"status": NA, "denominator": 0, "subset_denominator": 0,
                "numerator": 0, "plan_queries": [],
                "note": "没有 --shots：Q5 的运行侧 join 没有输入（§4.1b 第二步）"}
    payload = json.loads(Path(shots_path).read_text(encoding="utf-8"))
    shots = payload.get("shots") if isinstance(payload, dict) else payload
    shots = shots or []

    from block_director.knowledge.hypergraph import VALUE_ALIASES  # noqa: PLC0415

    wanted = {}
    for entry in entries:
        values = [str(v) for v in (entry.get("expect_movements") or []) if str(v)]
        if not values:
            continue
        wanted[str(entry.get("id"))] = (
            _normalise_query_pairs(entry.get("q")),
            {VALUE_ALIASES.get(value, value) for value in values})

    numerator = denominator = subset_denominator = 0
    queries: List[str] = []
    matched: List[Dict[str, Any]] = []
    for record in shots:
        query = plan_query_of_shot(record)
        if query:
            queries.append(query)
        applied = {VALUE_ALIASES.get(str(m.get("kind") or m.get("type") or ""), "")
                   for m in (record.get("movements") or []) if isinstance(m, dict)}
        applied.discard("")
        if not applied:
            #: 一条运镜都没排 = 引擎的机位是**锁死**的。词表里这件事的说法就是
            #: `固定`（`static` 是它的别名）。不补这一条，"这一镜没写运镜"会被
            #: 当成"没有任何运镜产出"，于是**作者期望 `固定` 的条目永远不可能命中**
            #: ——而那恰好是 `SHOT_PATTERN` 那批（景别×镜头）最典型的形状。
            applied = {VALUE_ALIASES.get("固定", "固定")}
        mine = _normalise_query_pairs(query)
        for ident, (expected_pairs, expected_moves) in wanted.items():
            if not expected_pairs:
                continue
            if expected_pairs == mine:
                denominator += 1
                if applied & expected_moves:
                    numerator += 1
                matched.append({"shot_id": record.get("shot_id"), "entry": ident,
                                "query": query, "mode": "equal"})
            elif expected_pairs <= mine:
                subset_denominator += 1
    value = round(numerator / denominator, 4) if denominator else None
    detail: Dict[str, Any] = {
        "status": NA, "numerator": numerator, "denominator": denominator,
        "subset_denominator": subset_denominator, "value": value, "line": 0.80,
        "plan_queries": sorted(set(queries)), "matched_shots": matched[:20],
        "fixture_entries": len(wanted)}
    if denominator == 0:
        detail["note"] = (
            f"运行侧 join 按 §4.1b 的『键值对集合相等』匹配到 0 个镜头"
            f"（放宽成子集也只有 {subset_denominator} 个）：Q5 的分母为 0，"
            f"按 §4.1b 硬规则 1 如实记 not_measured。真实发出的契约串见 "
            f"plan_queries（{len(set(queries))} 条去重）")
    elif value is not None and value >= 0.80:
        detail["status"] = PASS
        detail["note"] = f"计划采纳率 {numerator}/{denominator}"
    else:
        detail["status"] = FAIL
        detail["note"] = f"计划采纳率 {numerator}/{denominator} < 0.80"
    return detail


def q5_movement_hit(entries: List[Dict[str, Any]], shots=None) -> Dict[str, Any]:
    """Q5 运镜命中（§4.1b 分两步判；本函数负责第一步与"缺什么"的如实记账）。

    §4.1b 原文：① 夹具侧：带 `expect_movements` 的条目 **≥ 30**（不足则 Q5 记
    `not_measured`，不得判过）；② 运行侧：实跑中与本条 `q` **等价**的计划镜头数
    **≥ 1** 才计入分母（join 键是 `q`，不是镜号）。

    实测（2026-10-02，2840 条 oracle）：**带 `expect_movements` 的条目是 0 条**——
    池通道的标注模板只写 `q/must/top1/never`，从来没写过这个字段（旧的
    `holdout_gen` 写过，换成池通道之后就没了）。所以 Q5 现在**测不到东西**；
    按 §4.1b 硬规则 1 这种"分母为 0"必须**明确记账**，绝不允许因为"报告里没这条"
    而看起来像通过了。

    补齐它要一次**独立标注**（判据是"这张卡描述的作者意图是什么运镜"，由换族模型
    或人来写）；把索引里的 movement 成员抄一遍是自证，§4.1b 硬规则 2 禁止。
    """
    expected = [entry for entry in entries if entry.get("expect_movements")]
    if len(expected) < MIN_Q5_FIXTURE_ITEMS:
        return {"id": "Q5", "status": NA,
                "numerator": len(expected), "denominator": 0, "line": 0.80,
                "note": (f"夹具里带 `expect_movements` 的条目 {len(expected)} < "
                         f"{MIN_Q5_FIXTURE_ITEMS}（§4.1b 第一步）：Q5 无法判定、"
                         f"不得判通过。池通道的标注模板不产这个字段，"
                         f"补齐要走一次独立标注（判据＝卡里描述的作者意图）")}
    run = q5_run_join(entries, shots)
    plan_shaped = sum(1 for entry in expected
                      if _normalise_query_pairs(entry.get("q"))
                      and {key for key, _value in _normalise_query_pairs(entry.get("q"))}
                      <= set(PLAN_QUERY_KEYS))
    #: `numerator` 一直是**夹具侧**的条数（"带 `expect_movements` 的条目有多少"），
    #: 运行侧的比值另开 `run_*` —— 这两个数是两件事，混用一个键会让"夹具够不够"
    #: 与"计划采纳率"看起来是同一个数（这正是 R54 之前 Q4 变成恒真式的老毛病）。
    metric = {"id": "Q5", "status": run["status"],
              "numerator": len(expected), "denominator": 0, "line": 0.80,
              "fixture_items": len(expected), "fixture_plan_shaped": plan_shaped,
              "run_numerator": run["numerator"],
              "run_denominator": run["denominator"],
              "run_value": run.get("value"),
              "run_subset_denominator": run.get("subset_denominator", 0),
              "plan_queries": run.get("plan_queries", []),
              "note": run.get("note", "")}
    if run["status"] == NA and run["denominator"] == 0 and not run.get("plan_queries"):
        metric["note"] = (
            f"夹具侧已够（{len(expected)} 条，其中计划形状 {plan_shaped} 条），"
            f"但运行侧的 join 需要一次真实模型运行的逐镜查询镜像："
            f"本工具还没接上（没给 --shots）")
    return metric


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
    """E3 硬门：经验边**不得**带 forbid（只有显式 lesson 可以）。

    **分母下界（2026-10-01 修）**：规格 §4.1b 与 §B.5 的 E3 行都写着
    "只有分子没有分母 = 空集通过；**分母为 0 → 失败**"。旧实现只看
    `offenders` 是否为空，于是索引里 `source_kind=experience` 一条都没有时
    （实测 2026-10-01：766 条边里 theory 762 / lesson 4 / **experience 0**）
    这条硬门**恒为 pass**——一个恒真的绿比一个诚实的红更危险，RK-13 会把
    "经验不越权"记成已达标。现在分母为 0 直接判 FAIL，并把 L2 层的真实条数
    写进 note（`lesson` 允许带 forbid，不参与分子）。
    """
    offenders: List[str] = []
    experience = 0
    for edge in graph.edges:
        if str(edge.source_kind) != "experience":
            continue
        experience += 1
        forbidden = [m for m in edge.members if str(m.role) == "forbid"]
        if forbidden:
            offenders.append(edge.edge_id)
    if experience == 0:
        return {"id": "E3", "status": FAIL,
                "numerator": 0, "denominator": 0, "value": None, "line": 0,
                "note": ("L2 经验层为空（`source_kind=experience` 0 条）：这条门"
                         "**测不到东西**，按 §4.1b 的分母下界判失败 —— "
                         "不得记成'经验不越权已达标'")}
    return {"id": "E3", "status": PASS if not offenders else FAIL,
            "numerator": len(offenders), "denominator": experience,
            "value": 0 if not offenders else None, "line": 0,
            "note": ("经验边（source_kind=experience）单独产生的 forbid 条数必须为 0"
                     if not offenders else f"越权的边：{offenders[:5]}")}


def e3_cases(cases_path: Optional[Path]) -> Dict[str, Any]:
    """L3 侧的 E3：案例**结构上**不能带约束；文件层面再核一遍。

    **空文件同样判失败**（2026-10-01）：`cases.jsonl` 存在但一行都没有时，
    `bad` 为空 → 旧实现判 PASS，而它的分母正是 0 —— 和 L2 侧的 E3 是同一种
    空集通过（§4.1b 硬规则 1）。"没有越权案例"与"没有案例可查"必须分开。
    """
    if cases_path is None or not Path(cases_path).is_file():
        return {"id": "E3_cases", "status": NA,
                "note": "没有 knowledge/cases.jsonl：L3 侧无证据"}
    rows = [json.loads(line) for line in Path(cases_path).read_text(
        encoding="utf-8").split("\n") if line.strip()]
    if not rows:
        return {"id": "E3_cases", "status": FAIL,
                "numerator": 0, "denominator": 0, "line": 0,
                "note": "cases.jsonl 存在但为空：分母为 0，按 §4.1b 判失败"
                        "（不得当成'没有越权案例'）"}
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
    metrics.append(q5_movement_hit(entries, shots))
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
