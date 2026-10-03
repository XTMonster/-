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
  python tools/knowledge/quality.py --cases knowledge/cases.jsonl \
      --shots <run>/export/shots.json --audit-log <run>/audit_log.jsonl

Q5 的运行侧**只认 `audit_log.jsonl` 里真实发出的逐镜查询**（§4.1b 硬规则 2；
见 :mod:`tools.knowledge.run_evidence`）：`shots.json` 的字段是收尾快照，
与"这一镜检索时发的是什么串"不是同一时刻，重推出来的串只作漂移诊断。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import (  # noqa: E402
    manifest_fingerprint,
    read_cases,
)
from block_director.knowledge.hypergraph import (  # noqa: E402
    manifest_fingerprint as hypergraph_manifest_fingerprint,
)
from tools.knowledge.run_evidence import (  # noqa: E402
    normalise_query_pairs,
    run_query_mirror,
)
from tools.knowledge.corpus_gates import (  # noqa: E402
    DEFAULT_CARDS_DIR,
    DEFAULT_REPORT,
    corpus_metrics,
)
from tools.holdout_score import load_graph, load_holdout, score_entries  # noqa: E402

PASS, FAIL, NA = "pass", "fail", "not_measured"

#: §4.1b 的 Q5 第一步：夹具里带 `expect_movements` 的条目下界。不足时 Q5 记
#: `not_measured`（**不得判通过**）——它的分母是"真实模型跑出来的同 q 镜头数"，
#: 夹具没有这条标注就无从 join。
MIN_Q5_FIXTURE_ITEMS = 30

#: §4.1b 的 E1 行：「判分样本 ≥ 1200（R50）」。链上喂的是**一次真实运行**的回返
#: 案例（6 镜 × top-3 = 18），所以这个下界当前**够不到**——报告必须把差多少写出来，
#: 让人一眼看出 3/18 不是有统计效力的 0.1667。**它不改判据、不改状态**：E1 的分母是
#: 18 不是 0，按 §4.1b 硬规则 1 该判失败就判失败。
E1_SAMPLE_FLOOR = 1200

#: `ShotContract.constraint_query()` / `shot_constraint_query()` 真正会产出的键。
#: 只有 `q` 的键**全部**落在这里的条目才可能与真实运行的计划镜头 join 上——
#: 这是 §4.1b 的 Q5 join 判据（"键值对集合相等"）的直接推论。
#: v1.5 §2.3d T3 加入 `意图`：它是**计划决策**（`ShotPlan.intent_type`，12 值闭集
#: 由 `emit_plan` 的 enum 保证），因此逐镜检索真的会发出 `意图=`。这一条同时
#: 让 Q5 的 join 空间从"只含 SHOT_PATTERN"扩到 **INTENT_PACK**——实测 oracle 里
#: 有 176 条条目的 `q` 正好是 `意图/景别/运镜`，那是唯一与引擎可表达空间重合的一族。
PLAN_QUERY_KEYS: Tuple[str, ...] = ("景别", "意图", "镜头", "运镜", "动作", "特效",
                                    "对白")


def _normalise_query_pairs(text: str) -> frozenset:
    """`键=值；键=值` → 归一化后的 `{(键, 值)}` 集合。

    归一化口径与 §4.1b 的 Q5 行逐字对应：**去空格 / 全半角 / 别名**。
    `VALUE_ALIASES` 是索引侧唯一那份别名表（`static` → `固定`、`甩镜` → `whip_pan`），
    两边都用它，join 才不会因为一边写引擎名、一边写中文别名而永远错开。

    **单一真源**：实现搬到了 :mod:`tools.knowledge.run_evidence`
    （运行侧证据的通道模块），这里保留同名入口——`work/` 下的探针与既有用例
    都按这个名字调用，两处各写一份正是"别名表漂移"的老毛病。
    """
    return normalise_query_pairs(text)


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
        self.intent_type = str((record or {}).get("intent_type") or "")
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


def run_evidence_is_stale(payload: Any, *, manifest_path=None,
                          cases_path=None) -> List[str]:
    """这份真实运行证据**能不能证明它量的是当前这一代索引**？返回不能的理由。

    为什么需要这一条（2026-10-03 实测）：Q5 的运行侧要拿一份真实模型运行的
    `shots.json` 与 held-out 的 `q` join。盘上那份 `docs/evidence/20261002_real/`
    属于**旧索引那一代**（`knowledge.cases_index_fingerprint` 与现行
    `knowledge/cases.manifest.json` 对不上），拿它 join 新 oracle 就是 §24.1
    修掉的"过期证据被当成现行证据"的同一形状。所以判据里必须包含"这份运行是
    哪一代索引跑的"：

    * `shots.json` 顶层必须有 `knowledge` 块（`driver.py` 的
      `BLOCKDIRECTOR_RESULT.knowledge`，由 `KnowledgeRetriever.describe()` 产出）；
    * `knowledge.hypergraph_fingerprint` 必须非空且等于
      `knowledge/hypergraph.manifest.json` 的 `fingerprint`（Q5 的 join 只落在
      超图索引这一侧，所以这一条是**硬要求**）；
    * 若这次运行确实装了案例层（`knowledge.cases_backend != "off"`），
      `knowledge.cases_index_fingerprint` 也必须非空且等于当前案例索引指纹。

    任一条不满足 ⇒ 返回理由 ⇒ 调用方记 `not_measured` ＋ `stale_evidence: true`
    （**永不判过**），并把算出来的数一并报出来。
    """
    if not isinstance(payload, dict):
        return ["shots.json 不是对象：读不出运行期索引指纹，无法证明代际"]
    info = payload.get("knowledge")
    if not isinstance(info, dict):
        return ["shots.json 顶层没有 knowledge 块（driver.py 的运行结果字段）："
                "无法证明这份运行是拿哪一代索引跑的"]
    reasons: List[str] = []

    recorded = str(info.get("hypergraph_fingerprint") or "")
    live = (hypergraph_manifest_fingerprint(Path(manifest_path).parent)
            if manifest_path else "")
    if not recorded:
        reasons.append("运行证据里没有 knowledge.hypergraph_fingerprint"
                       "（该字段 2026-10-03 才加上）：无法证明它量的是这一代超图索引")
    elif not live:
        reasons.append(f"读不到 {manifest_path} 的 fingerprint："
                       f"无法证明运行证据与当前索引同代")
    elif recorded != live:
        reasons.append(f"运行证据的超图指纹 {recorded[:12]}… 不等于当前索引的 "
                       f"{live[:12]}…：那是上一代索引跑出来的证据")

    #: 案例层**可以**是用户显式关掉的（`cases_backend=off`，§2.3b）——那种情况
    #: 它本来就没有指纹，不是"过期"。只要这次运行装了案例层，指纹就必须对上。
    if str(info.get("cases_backend") or "") != "off":
        recorded_cases = str(info.get("cases_index_fingerprint") or "")
        live_cases = (manifest_fingerprint(Path(cases_path).parent)
                      if cases_path else "")
        if not recorded_cases:
            reasons.append("运行证据里没有 knowledge.cases_index_fingerprint："
                           "无法证明它量的是这一代案例索引")
        elif recorded_cases != live_cases:
            reasons.append(f"运行证据的案例指纹 {recorded_cases[:12]}… 不等于当前"
                           f"案例索引的 {live_cases[:12]}…：那是上一代语料")
    return reasons


def q5_query_drift(shots: List[Dict[str, Any]],
                   emitted: Dict[str, Any]) -> List[Dict[str, str]]:
    """`shots.json` 重推串 vs **真实发出**串的漂移（**诊断，不是判据**）。

    为什么值得单独报（2026-10-03 实测）：逐镜检索发生在这一镜 editor 调用**之前**，
    而 `shots.json` 是收尾时的快照——`b4626c726435` 一跑 6 镜里 2 镜两条串不同
    （`shot_001` 发出 `景别=MCU`，导出后重推带上 `镜头/运镜/特效`）。漂移本身是
    产物的一部分：它说明"计划最终长什么样"与"这一镜检索时看到的是什么"不是同一件
    事，而这正是不能用重推串当 join 键的理由。
    """
    drift: List[Dict[str, str]] = []
    for record in shots or []:
        if not isinstance(record, dict):
            continue
        shot_id = str(record.get("shot_id") or "")
        mine = emitted.get(shot_id)
        queries = [mine] if isinstance(mine, str) else list(mine or [])
        if not queries:
            continue
        derived = plan_query_of_shot(record)
        emitted_pairs = {_normalise_query_pairs(query) for query in queries}
        if _normalise_query_pairs(derived) in emitted_pairs:
            continue
        drift.append({"shot_id": shot_id, "emitted": "；".join(queries),
                      "derived": derived})
    return drift


def _applied_movements(record: Dict[str, Any]) -> set:
    """这一镜**最后排上的**运镜（别名已归一）。

    一条运镜都没排 = 机位锁死，词表里的说法就是 `固定`（`static` 是它的别名）——
    不补这一条，"这一镜没写运镜"会被当成"没有任何运镜产出"，于是作者期望
    `固定` 的条目永远不可能命中。
    """
    from block_director.knowledge.hypergraph import VALUE_ALIASES  # noqa: PLC0415

    applied = {VALUE_ALIASES.get(str(item.get("kind") or item.get("type") or ""),
                                 str(item.get("kind") or item.get("type") or ""))
               for item in (record.get("movements") or []) if isinstance(item, dict)}
    applied.discard("")
    if not applied:
        applied = {VALUE_ALIASES.get("固定", "固定")}
    return applied


def q5_retrieval_join(entries: List[Dict[str, Any]], mirror: Dict[str, Any],
                      shots, graph) -> Dict[str, Any]:
    """Q5 的**实读数**（诊断，不参与门）：按"这一镜真的召回了哪条边"对齐。

    为什么单列这一条（2026-10-03 实测）：§4.1b 的 Q5 join 是"发出的查询串与本条
    `q` 的**键值对集合相等**"。而真实发出的串的键集由**计划**决定、标注者的 `q`
    由**卡片**决定，两边几乎不可能相等——64 镜那一跑的 64 条发出串与 4539 条 `q`
    一条都不相等（分母 0），于是这条判据**量不到任何东西**，只剩"结构性不可达"。

    这一条把对齐键换成"本条目的 `must[0]` 边**真的被这一镜检索到了**"：分子/分母
    的**语义一个字没改**（这一镜的运镜是否落在作者期望集合里），门限也没动
    （0.80），换的只是**对齐键**。实测可达性：6 镜那一跑 13 对、64 镜那一跑 31 对。

    **只作诊断**，因为样本会被单条条目主导（实测 64 镜那跑的 31 对里 8 对来自
    同一条 `hq_1057`）——所以 `by_entry` 一并报出来，谁都不许把那个比值读成
    有代表性的总体比例。`status` 恒为 `not_measured`：它还不是门。
    """
    from tools.holdout_score import spec_to_norm_key  # noqa: PLC0415

    detail: Dict[str, Any] = {
        "id": "Q5_retrieval_join", "status": NA, "numerator": 0,
        "denominator": 0, "value": None, "line": 0.80, "matched_pairs": 0,
        "by_entry": {}, "examples": [],
        "note": ("按『这一镜检索到了该条目的 `must[0]` 边』对齐的实读数；"
                 "**不参与门**。§4.1b 的 Q5 join（逐字相等）另见同一份 detail "
                 "的 numerator/denominator"),
    }
    if graph is None:
        detail["note"] = "没有索引图：实读数无法把 `must[0]` 解析成边 id"
        return detail
    if str(mirror.get("status")) != "ok":
        detail["note"] = ("审计日志里没有可用的逐镜检索事件：实读数没有输入"
                          "（与 Q5 join 的 not_measured 同源）")
        return detail
    by_norm = {edge.norm_key: edge for edge in graph.edges}
    expected: Dict[str, set] = {}
    edge_of: Dict[str, str] = {}
    for entry in entries:
        values = {str(value) for value in (entry.get("expect_movements") or [])
                  if str(value)}
        if not values:
            continue
        spec = (entry.get("must") or [None])[0]
        edge = by_norm.get(spec_to_norm_key(spec, graph)) if spec else None
        if edge is None:
            continue
        ident = str(entry.get("id"))
        expected[ident] = values
        edge_of[ident] = edge.edge_id
    if not edge_of:
        detail["note"] = ("夹具里没有『带 expect_movements 且 must[0] 能在索引里解析』"
                          "的条目：实读数没有可对齐的对象")
        return detail
    recalled = mirror.get("edges") or {}
    records = shots if isinstance(shots, list) else []
    applied = {str(record.get("shot_id") or ""): _applied_movements(record)
               for record in records if isinstance(record, dict)}
    numerator = denominator = 0
    by_entry: Dict[str, List[int]] = {}
    examples: List[Dict[str, Any]] = []
    for shot_id, record in applied.items():
        hit_edges = set(recalled.get(shot_id) or [])
        if not hit_edges:
            continue
        for ident, edge_id in edge_of.items():
            if edge_id not in hit_edges:
                continue
            denominator += 1
            hit = bool(applied[shot_id] & expected[ident])
            numerator += int(hit)
            bucket = by_entry.setdefault(ident, [0, 0])
            bucket[0] += 1
            bucket[1] += int(hit)
            if len(examples) < 12:
                examples.append({"shot_id": shot_id, "entry": ident,
                                 "edge_id": edge_id,
                                 "expected": sorted(expected[ident]),
                                 "applied": sorted(applied[shot_id]),
                                 "hit": hit})
    detail.update({
        "status": NA, "numerator": numerator, "denominator": denominator,
        "value": round(numerator / denominator, 4) if denominator else None,
        "matched_pairs": denominator, "examples": examples,
        "by_entry": {key: {"shots": value[0], "hits": value[1]}
                     for key, value in sorted(by_entry.items())},
        "entries_with_expectations": len(edge_of),
    })
    if not denominator:
        detail["note"] = ("这一跑没有任何一镜检索到带期望的那几条边：实读数为 0/0"
                          "（**不得**读成 0% 采纳率）")
    return detail


def q5_run_join(entries: List[Dict[str, Any]], shots_path, *,
                audit_path=None, run_id: str = "",
                manifest_path=None, cases_path=None,
                graph=None) -> Dict[str, Any]:
    """Q5 的**第二步**：把这一跑**真实发出**的逐镜查询与 held-out 的 `q` join 起来。

    判据（§4.1b 的 Q5 行）一个字没动：`SceneContract` 查询串与本条 `q` 的
    **键值对集合相等**（值经去空格 / 全半角 / 别名归一）。变的是**读哪一条串**：

    * `emitted`（**join 键**）＝ `audit_log.jsonl` 的 `retrieval_call.data.query`
      ——硬规则 2（禁止自证）允许回答"运行期到底发了什么"的通道只有实际发出的
      prompt 与 audit_log 的逐次事件；
    * `derived`（**只作诊断**）＝ 从 `shots.json` 用 `shot_constraint_query()` 重推
      的串。`shots.json` 是被测实现自己写的收尾快照，而且**不是同一时刻**：
      2026-10-03 那一跑 6 镜里 2 镜两条串不同（见 :mod:`tools.knowledge.run_evidence`
      抬头）。拿它当 join 键 = 量另一次运行。

    另外报一份**实读数**（诊断，不参与门）：:func:`q5_retrieval_join` ——
    把对齐键从"发出的查询串"换成"这一镜真的召回的那条边"。为什么必须有一条
    这样的读数见那个函数的抬头（一句话：按字符串相等对齐时，分母**结构性**为 0，
    判据量不到任何东西）。

    分母为 0 时按**硬规则 1 判 fail**（夹具侧 <30 那一档仍按 §4.1b 第一步记
    `not_measured`——两条规范原文分开执行，见 :func:`q5_movement_hit`）。
    """
    if not shots_path or not Path(shots_path).is_file():
        return {"status": NA, "channel": "absent", "denominator": 0,
                "subset_denominator": 0, "numerator": 0, "plan_queries": [],
                "emitted_queries": {}, "drift": [], "run_ids": [],
                "note": "没有 --shots：Q5 的运行侧 join 没有输入（§4.1b 第二步）"}
    payload = json.loads(Path(shots_path).read_text(encoding="utf-8"))
    #: 代际判定**先于**算术：算出来的数只有在"这份运行属于当前这一代索引"时才
    #: 是证据。过期的照样把数报出来（信息量保留），但状态记 `not_measured`。
    stale = run_evidence_is_stale(payload, manifest_path=manifest_path,
                                  cases_path=cases_path)
    shots = payload.get("shots") if isinstance(payload, dict) else payload
    shots = shots or []
    mirror = run_query_mirror(audit_path, run_id=run_id)

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
    matched: List[Dict[str, Any]] = []
    without_query: List[str] = []
    derived_queries = [plan_query_of_shot(record) for record in shots
                       if isinstance(record, dict)]
    emitted = dict(mirror.get("queries") or {})
    drift = q5_query_drift(shots, emitted) if mirror["status"] == "ok" else []
    if mirror["status"] == "ok":
        for record in shots:
            if not isinstance(record, dict):
                continue
            shot_id = str(record.get("shot_id") or "")
            queries = list(emitted.get(shot_id) or [])
            if not queries:
                without_query.append(shot_id)
                continue
            #: 取值侧用 `(值, 值)` 兜底，**不是** `(值, "")`：`VALUE_ALIASES` 是一张
            #: **部分**别名表（20 条：`static`→`固定`、`中景`→`MS`…），引擎自己的
            #: 名字（`dolly_in`／`follow_subject`…）不在表里。旧写法把不在表里的取值
            #: 一律折成空串再丢掉，于是**每一镜都被当成"锁死"**（`固定`）——作者期望
            #: `固定` 的条目会被 `dolly_in` 的镜头骗成命中，期望 `dolly_in` 的反而
            #: 恒不命中。这是分子上的真实缺陷，2026-10-03 写通道用例时抓到。
            #: 一条运镜都没排 = 引擎的机位是**锁死**的（`固定`）——判据与
            #: `_applied_movements` 同源，实读数用的是同一个函数，两处不许漂。
            applied = _applied_movements(record)
            mine = [_normalise_query_pairs(query) for query in queries]
            for ident, (expected_pairs, expected_moves) in wanted.items():
                if not expected_pairs:
                    continue
                if expected_pairs in mine:
                    denominator += 1
                    if applied & expected_moves:
                        numerator += 1
                    matched.append({
                        "shot_id": shot_id, "entry": ident, "mode": "equal",
                        "query": queries[mine.index(expected_pairs)],
                        "channel": "audit"})
                elif any(expected_pairs <= pairs for pairs in mine):
                    subset_denominator += 1
    value = round(numerator / denominator, 4) if denominator else None
    retrieval = q5_retrieval_join(entries, mirror, shots, graph)
    detail: Dict[str, Any] = {
        "status": NA, "numerator": numerator, "denominator": denominator,
        "subset_denominator": subset_denominator, "value": value, "line": 0.80,
        #: 诊断：按"检索结果"对齐的实读数（不参与 status）。
        "retrieval_join": retrieval,
        "channel": "audit" if mirror["status"] == "ok" else "absent",
        "emitted_queries": emitted,
        "plan_queries": sorted({query for query in derived_queries if query}),
        "drift": drift, "shots_without_emitted_query": without_query,
        "run_ids": list(mirror.get("run_ids") or []),
        "audit": str(audit_path or ""),
        "audit_events": int(mirror.get("events") or 0),
        "audit_shot_events": int(mirror.get("shot_events") or 0),
        "audit_note": str(mirror.get("note") or ""),
        "matched_shots": matched[:20],
        "fixture_entries": len(wanted), "evidence": str(shots_path),
        "evidence_fingerprints": (
            {"hypergraph": str((payload.get("knowledge") or {}).get(
                "hypergraph_fingerprint") or ""),
             "cases": str((payload.get("knowledge") or {}).get(
                 "cases_index_fingerprint") or "")}
            if isinstance(payload, dict) else {})}
    if stale:
        detail["stale_evidence"] = True
        detail["note"] = ("这份运行证据与当前索引脱钩（历史记录，不得当成通过）："
                          + "；".join(stale))
    elif mirror["status"] != "ok":
        detail["note"] = ("Q5 的运行侧没有可用的**真实发出**查询（§4.1b 硬规则 2）："
                          + (detail["audit_note"] or "审计日志缺失"))
    elif denominator == 0:
        detail["status"] = FAIL
        detail["note"] = (
            f"这一跑真的发过逐镜查询（shot scope {detail['audit_shot_events']} 条），"
            f"但按 §4.1b 的『键值对集合相等』与 held-out 的 `q` 匹配到 0 条"
            f"（放宽成子集也只有 {subset_denominator} 条）：分母为 0，"
            f"按 §4.1b 硬规则 1 判失败（不得记 not_measured）。"
            f"真实发出的契约串见 emitted_queries；重推串与它的漂移见 drift"
            f"（{len(drift)} 镜）")
    elif value is not None and value >= 0.80:
        detail["status"] = PASS
        detail["note"] = f"计划采纳率 {numerator}/{denominator}"
    else:
        detail["status"] = FAIL
        detail["note"] = f"计划采纳率 {numerator}/{denominator} < 0.80"
    return detail


def q5_movement_hit(entries: List[Dict[str, Any]], shots=None, *,
                    audit_path=None, run_id: str = "",
                    manifest_path=None, cases_path=None,
                    graph=None) -> Dict[str, Any]:
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
                "fixture_items": len(expected), "fixture_plan_shaped": 0,
                "note": (f"夹具里带 `expect_movements` 的条目 {len(expected)} < "
                         f"{MIN_Q5_FIXTURE_ITEMS}（§4.1b 第一步）：Q5 无法判定、"
                         f"不得判通过。池通道的标注模板不产这个字段，"
                         f"补齐要走一次独立标注（判据＝卡里描述的作者意图）")}
    run = q5_run_join(entries, shots, audit_path=audit_path, run_id=run_id,
                      manifest_path=manifest_path, cases_path=cases_path,
                      graph=graph)
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
              #: 诊断（不参与 status）：按"这一镜真的召回了哪条边"对齐的实读数。
              #: 它比逐字相等的 join 可达得多，但样本会被单条条目主导 ⇒ 只报。
              "run_retrieval_join": run.get("retrieval_join", {}),
              "run_stale_evidence": bool(run.get("stale_evidence")),
              "run_evidence_fingerprints": run.get("evidence_fingerprints", {}),
              "run_channel": run.get("channel", "absent"),
              "run_emitted_queries": run.get("emitted_queries", {}),
              "run_drift_shots": [item.get("shot_id")
                                  for item in (run.get("drift") or [])],
              "run_audit": run.get("audit", ""),
              "run_audit_shot_events": run.get("audit_shot_events", 0),
              "plan_queries": run.get("plan_queries", []),
              "note": run.get("note", "")}
    if (run["status"] == NA and run["denominator"] == 0
            and not run.get("plan_queries")
            and not run.get("stale_evidence")
            and run.get("channel") == "absent" and not run.get("audit")):
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


def e2_adoption(shots_path: Optional[Path], *, manifest_path=None,
                cases_path=None) -> Dict[str, Any]:
    """E2 经验采纳率（诊断量，不设门）。

    §2.3b 的 E2 = "计划里的运镜来自经验/案例层的镜头比例"。它与 Q5 读**同一份**
    运行证据，所以同受"同代性"约束：`knowledge` 指纹对不上就记 `stale_evidence`
    （诊断量也不许把过期的账读成结论）。
    """
    if shots_path is None or not Path(shots_path).is_file():
        return {"id": "E2", "status": NA,
                "note": "没有 --shots：采纳率无法测量（诊断量，不设门）"}
    payload = json.loads(Path(shots_path).read_text(encoding="utf-8"))
    stale = run_evidence_is_stale(payload, manifest_path=manifest_path,
                                  cases_path=cases_path)
    shots = payload.get("shots") if isinstance(payload, dict) else payload
    shots = shots or []
    adopted = 0
    for shot in shots:
        for movement in shot.get("movements") or []:
            if str(movement.get("source") or "") in ("experience", "lesson", "case"):
                adopted += 1
                break
    detail: Dict[str, Any] = {
        "id": "E2", "status": NA, "diagnostic": True,
        "numerator": adopted, "denominator": len(shots),
        "value": round(adopted / len(shots), 4) if shots else None,
        "evidence_fingerprints": (
            {"hypergraph": str((payload.get("knowledge") or {}).get(
                "hypergraph_fingerprint") or ""),
             "cases": str((payload.get("knowledge") or {}).get(
                 "cases_index_fingerprint") or "")}
            if isinstance(payload, dict) else {}),
        "note": (f"计划里的运镜取自经验/案例层的镜头数 / {len(shots)}"
                 f"（记录，不设门）")}
    if stale:
        detail["stale_evidence"] = True
        detail["note"] = ("这份运行证据与当前索引脱钩（历史记录，诊断量也不许读成"
                          "结论）：" + "；".join(stale))
    return detail


def e1_evidence_is_stale(rows: List[Dict[str, Any]],
                         cases_path: Optional[Path]) -> List[str]:
    """这批打分**能不能用来量当前案例索引**？返回不能用的具名理由。

    为什么需要这一条（2026-10-02 实测）：E1 的分母是"被返回的案例"，而
    `cases.jsonl` 每次重建都会换掉一批 `case_id`。仓库里那份
    `docs/evidence/20261002_real/e1_reviews.jsonl` 有 **16 条**打分，其中
    **9 条的 `case_id` 在当前索引里已经不存在**——也就是说它量的是上一代语料，
    却照样能被算成一个 0.0 的 E1。这和 §24.1（案例层漏跑一天而链路全绿）是
    同一个形状：**过期证据被当成现行证据**。所以 E1 的判据里必须包含
    "这批打分说的是不是**这一份**索引"：

    * `cases_path` 必须给且读得出来（否则无从证明覆盖）；
    * 每一条打分的 `case_id` 必须在当前 `cases.jsonl` 里；
    * 每一条打分必须带 `cases_fingerprint`，且等于 `cases.manifest.json` 的
      `fingerprint`（单一真源：`block_director/knowledge/cases.py`）；
    * 每一条打分必须带 `reviewed_by`（是谁裁的，必须落在记录里）。

    任一条不满足 ⇒ 返回理由 ⇒ 调用方记 `not_measured`（**永不判过**）。
    """
    if cases_path is None:
        return ["没有给出案例索引（--cases）：无法证明这批打分覆盖的是当前语料"]
    cases_path = Path(cases_path)
    if not cases_path.is_file():
        return [f"案例索引 {cases_path} 不存在：无法证明打分覆盖的是当前语料"]
    try:
        live = {str(case.case_id) for case in read_cases(cases_path)}
    except (OSError, ValueError) as exc:
        return [f"案例索引 {cases_path} 读不出来（{exc}）：无法证明覆盖"]
    if not live:
        return [f"案例索引 {cases_path} 一条案例都没有：分母无意义"]

    fingerprint = manifest_fingerprint(cases_path.parent)
    reasons: List[str] = []
    gone = [str(row.get("case_id")) for row in rows
            if str(row.get("case_id")) not in live]
    if gone:
        reasons.append(
            f"{len(gone)}/{len(rows)} 条打分指向的 case_id 已不在当前 "
            f"cases.jsonl（例：{'、'.join(gone[:3])}）——那是上一代语料")
    if not fingerprint:
        reasons.append("读不到 cases.manifest.json 的 fingerprint："
                       "无法证明打分与索引同代")
    else:
        unbound = [row for row in rows
                   if str(row.get("cases_fingerprint") or "") != fingerprint]
        if unbound:
            reasons.append(
                f"{len(unbound)}/{len(rows)} 条打分没有携带当前案例索引指纹 "
                f"({fingerprint[:12]}…)：无法证明它量的是这一份索引")
    unlabelled = [row for row in rows if not str(row.get("reviewed_by") or "")]
    if unlabelled:
        reasons.append(f"{len(unlabelled)}/{len(rows)} 条打分没有 reviewed_by："
                       "谁裁的没有落在记录里")
    return reasons


def e1_relevance(reviews_path: Optional[Path], *,
                 cases_path: Optional[Path] = None) -> Dict[str, Any]:
    """E1 经验引用相关性（打分由人／已授权复核面板给出，agent 不代判）。

    打分一旦**与当前案例索引脱钩**就不再是 E1 的证据，而是历史记录：那种情况下
    记 `not_measured` ＋ `stale_evidence: true`，并把当时算出来的分数一并报出来
    （信息量保留，**但绝不能被读成通过**）。判据见
    :func:`e1_evidence_is_stale`。
    """
    if reviews_path is None or not Path(reviews_path).is_file():
        return {"id": "E1", "status": NA,
                "note": "需要人工对返回的 cases 按 >=4/5 打分（§2.3b）；"
                        "没有 --e1-reviews 就不判——不得由 agent 代判"}
    rows = [json.loads(line) for line in Path(reviews_path).read_text(
        encoding="utf-8").split("\n") if line.strip()]
    scored = [row for row in rows if isinstance(row.get("score"), (int, float))]
    if not scored:
        return {"id": "E1", "status": FAIL, "note": "打分文件为空：分母为 0 判失败"}
    good = [row for row in scored if float(row["score"]) >= 4]
    value = len(good) / len(scored)
    payload = {"id": "E1",
               "numerator": len(good), "denominator": len(scored),
               "value": round(value, 4), "line": 0.70,
               #: §4.1b 的 E1 行写着「判分样本 ≥ 1200（R50）」，而链上这一份只有
               #: 一次真实运行的 6 镜 × top-3 = **18 条**。判据（≥70%）与状态判定
               #: **不因此改变**——分母是 18、不是 0，按硬规则 1 该判失败就判失败；
               #: 但"样本离下界还差多少"必须写在报告里，否则读者会把 3/18 当成
               #: 一个有统计效力的 0.1667。这就是本项目对"缺证据"的一贯处置：**报出来，
               #: 而不是让它看起来像结论**。
               "sample_floor": E1_SAMPLE_FLOOR,
               "sample_shortfall": max(0, E1_SAMPLE_FLOOR - len(scored)),
               "sample_floor_met": len(scored) >= E1_SAMPLE_FLOOR}
    stale = e1_evidence_is_stale(scored, cases_path)
    if stale:
        return {**payload, "status": NA, "stale_evidence": True,
                "note": "这批打分与当前案例索引脱钩（历史记录，不得当成通过）："
                        + "；".join(stale)}
    shortfall = (f"（注意：判分样本 {len(scored)} < §4.1b 下界 {E1_SAMPLE_FLOOR}，"
                 f"差 {E1_SAMPLE_FLOOR - len(scored)} 条——这个比率还不具备"
                 f"统计效力，判据与状态未因此改变）"
                 if len(scored) < E1_SAMPLE_FLOOR else "")
    return {**payload, "status": PASS if value >= 0.70 else FAIL,
            "note": (f"相关案例 {len(good)}/{len(scored)} = {value:.4f}"
                     f"（线 {0.70}）{shortfall}")}


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
                 audit_log: Optional[Path] = None, audit_run_id: str = "",
                 cards_dir: Optional[Path] = None,
                 import_report: Optional[Path] = None,
                 top_k: int, token_limit: int) -> Dict[str, Any]:
    graph = load_graph(ROOT / nodes, ROOT / edges)
    entries = load_holdout(ROOT / holdout)
    metrics: List[Dict[str, Any]] = [q0_build_gate(ROOT / manifest, ROOT / rejects)]
    #: §2.3c 的 **K1–K4**（RK-13 的**前置**，文档写了、链上此前从没查过）。
    #: 它们从**入库语料**重算（K1/K2/K3 完全不读构建期报告），K4 的账还要与语料对得上。
    #: 放在这里而不是单开一份文件，是因为 `hard_gates.py` 按 id 读**同一份报告**：
    #: 分成两处，某天门变空了不会有任何东西红。
    metrics.extend(corpus_metrics(
        cards_dir if cards_dir is not None else DEFAULT_CARDS_DIR,
        import_report if import_report is not None else DEFAULT_REPORT))

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
    #: 运行侧证据的**代际**由现行索引决定：`manifest` 指向
    #: `knowledge/hypergraph.manifest.json`（`--manifest`），`cases` 指向
    #: `knowledge/cases.jsonl`（`--cases`）。
    metrics.append(q5_movement_hit(entries, shots,
                                   audit_path=audit_log, run_id=audit_run_id,
                                   manifest_path=ROOT / manifest,
                                   cases_path=(ROOT / cases) if cases else None,
                                   graph=graph))
    metrics.append(e1_relevance(e1_reviews, cases_path=cases))
    metrics.append(e2_adoption(shots, manifest_path=ROOT / manifest,
                               cases_path=(ROOT / cases) if cases else None))

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
    parser.add_argument("--audit-log", default="",
                        help="这一跑的 audit_log.jsonl（分片）或累积日志；"
                             "Q5 的 join 键只从它的 retrieval_call 事件里读"
                             "（§4.1b 硬规则 2）")
    parser.add_argument("--audit-run-id", default="",
                        help="累积日志里混了多跑时用它点名（不给则记 not_measured）")
    parser.add_argument("--cards-dir", default=str(DEFAULT_CARDS_DIR),
                        help="生成卡目录（K1/K2/K3 从它重算）")
    parser.add_argument("--import-report", default=str(DEFAULT_REPORT),
                        help="构建期账本（K4 的分母来源；与语料对不上即判失败）")
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
        audit_log=Path(args.audit_log) if args.audit_log else None,
        audit_run_id=args.audit_run_id,
        cards_dir=Path(args.cards_dir),
        import_report=Path(args.import_report),
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
