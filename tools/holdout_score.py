"""v1.4 §4.1 RK-13 / §2.3：用 held-out 打分（Q1–Q4、Q6a、Q6b、Q7）。

**为什么单独一个脚本**：这些指标必须在**实现之外**定义的数据上算——
held-out 是人工/换族标注的（`fixtures/knowledge_holdout.jsonl`），
`norm_key` 是标注者写的规范化键（`(type, frozenset((role,kind,node_id)))`），
由本脚本在运行时映射到**当次**索引里的 `edge_id`（§2.3 的 Q6b 前置①，
不让标注者去算 sha1）。

三条 §4.1b 硬规则直接写进代码：

1. **分母下界**：任何分母为 0 的指标判 ``fail``（不是 ``not_measured``）；
2. **禁止自证**：Q6b/Q7 读的是**真正会注入的文本**（同一套 ``render_edges``），
   而不是索引自己的自述；
3. **not_measured 只用于"数据确实没有"**（例如 L3 关闭时的 E1/E3），
   并且**不得据此判通过**。

纯 Python、不依赖 bpy、不联网。

用法：
  python tools/holdout_score.py --holdout fixtures/knowledge_holdout.jsonl \
      [--json out.json] [--top-k 3] [--token-limit 2000]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    Hypergraph,
    parse_query,
    parse_query_full,
    render_edge,
    render_edges,
    render_tokens,
)
from tools.check_holdout import EntryError, parse_spec  # noqa: E402

#: §4.1b 的分母下界（低于它就判 fail，绝不当成"样本不足所以通过"）。
MIN_QUERIES = 1200
MIN_REQUIRED = 200
MIN_FORBID_ITEMS = 60


def norm_key(edge) -> Tuple[str, frozenset]:
    """规范化键：``(type, frozenset((role, kind, node_id)))``。

    刻意**忽略** ``weight`` / ``confidence`` / ``occurrences`` 这类可选量——
    标注者不该为了对齐一个可选成员而把整库判死（§2.3 Q6b 前置①）。
    """
    members = frozenset((str(m.role), str(m.kind), str(m.node_id))
                        for m in edge.members)
    return (str(edge.type), members)


def build_norm_index(graph: Hypergraph) -> Dict[Tuple[str, frozenset], str]:
    index: Dict[Tuple[str, frozenset], str] = {}
    for edge in graph.edges:
        index.setdefault(norm_key(edge), edge.edge_id)
    return index


def _spec_values(spec: str) -> Dict[str, str]:
    """``"EMOTION_PACK:emotion=荒诞,shot_size=MS"`` → ``{emotion: 荒诞, ...}``。"""
    text = str(spec or "")
    if ":" not in text:
        return {}
    _type, _, rest = text.partition(":")
    values: Dict[str, str] = {}
    for item in rest.split(","):
        kind, _, value = item.partition("=")
        kind, value = kind.strip(), value.strip()
        if kind and value:
            values[kind] = value
    return values


def as_norm_key(item) -> Tuple[str, frozenset]:
    """把 JSON 里的 ``norm_key`` 还原成可哈希的 ``(type, frozenset(...))``。

    标注文件是 JSON：``members`` 只能是数组的数组，而索引里是元组集合。
    这一步是 Q4/Q6b 能不能对上的关键（R47/R50：文件里存 norm_key，
    不让标注者去算 sha1）。
    """
    if isinstance(item, (list, tuple)) and len(item) == 2:
        edge_type, members = item
        pairs = []
        for member in members or []:
            if isinstance(member, dict):
                pairs.append((str(member.get("role")),
                              str(member.get("kind")),
                              str(member.get("node_id"))))
            elif isinstance(member, (list, tuple)) and len(member) == 3:
                pairs.append((str(member[0]), str(member[1]), str(member[2])))
        return (str(edge_type), frozenset(pairs))
    raise ValueError(f"不是合法的 norm_key：{item!r}")


def _node_id_for(graph: Hypergraph, kind: str, value: str) -> str:
    """把标注里的 `kind=取值` 解析成索引里的 `node_id`。

    标注写的是**人话/规范名**（`构图=rule_of_thirds`、`情绪=荒诞`），索引里是
    `node_id`（`composition_rule:rule_of_thirds`）。三级匹配：node_id 直接相等 →
    `value` 字段相等 → 名字/别名相等。
    """
    for node in graph.nodes.values():
        if str(node.type) != kind:
            continue
        if node.node_id == f"{kind}:{value}" or str(node.value) == value \
                or str(node.name) == value or value in tuple(node.aliases):
            return node.node_id
    return ""


def spec_to_norm_key(spec: str, graph: Hypergraph) -> Optional[Tuple[str, frozenset]]:
    """把一条 `must`/`never` 写法（协议 §2.2 的字符串）解析成**索引里那条边**的 norm_key。

    §2.3 前置① 的判据是 `norm_key(该边) == norm_key(标注边)`，而 `norm_key` 是
    `(type, frozenset((role,kind,node_id)))`——**包含 role 与完整成员集**。标注侧只写
    `kind=取值`（没有 role），所以这里用"成员集完全相等"在索引里找出那条边，再取它的
    真 norm_key；找不到就返回 `None`（＝这条 required 边不存在，按 §2.3 应判构建失败）。

    为什么不能直接把标注串当成 norm_key：`tools/holdout_score.py` 原先就是这么假设的，
    于是拿真实的 held-out 一跑就 `ValueError: 不是合法的 norm_key`——**Q1–Q7 一条都算不出来**。
    """
    try:
        etype, plain, forbid = parse_spec(spec)
    except EntryError:
        return None
    want_plain = set()
    for kind, value in plain.items():
        node_id = _node_id_for(graph, kind, value)
        if not node_id:
            return None
        want_plain.add((kind, node_id))
    want_forbid = set()
    for kind, value in forbid.items():
        node_id = _node_id_for(graph, kind, value)
        if not node_id:
            return None
        want_forbid.add((kind, node_id))
    for edge in graph.edges:
        if str(edge.type) != etype:
            continue
        edge_plain = {(m.kind, m.node_id) for m in edge.members if m.role != "forbid"}
        edge_forbid = {(m.kind, m.node_id) for m in edge.members if m.role == "forbid"}
        if edge_plain == want_plain and edge_forbid == want_forbid:
            return norm_key(edge)
    return None


def entry_key(item, graph: Hypergraph) -> Optional[Tuple[str, frozenset]]:
    """标注条目里的一个 `must`/`never` 元素 → norm_key。

    同时兼容两种写法：协议里的字符串（`TYPE:槽位=取值,…`）与已经算好的 `norm_key`
    结构（旧夹具/测试里出现过）。两种都解析不出来就返回 `None`。
    """
    if isinstance(item, str):
        return spec_to_norm_key(item, graph)
    try:
        return as_norm_key(item)
    except ValueError:
        return None


def spec_matches_by_subset(spec: str, graph: Hypergraph) -> bool:
    """诊断量：标注成员**只多不少**地落在某条索引边上（`forbid` 仍要求完全相等）。

    为什么要有这一条（而不是让它替代 `spec_to_norm_key`）：规格 §2.3 前置① 的字面
    判据是 `norm_key(该边) == norm_key(标注边)`（**完整成员集相等**），而 §2.3c 的
    标注通道第 2 条又写死"**标注方不可见**：只能拿到语料、schema、本协议，不得拿
    index"。两条放在一起，等于要求标注者在**看不见索引**的前提下把成员集猜到与
    抽取器逐字相同——实测吻合率 **1323/5043 = 26.2%**，其中 `AXIS_RULE` 更是结构性
    不可达：它的必填槽位只有 `pair`＋`axis_side`，而 v1.5 给同类型边加了**可选**
    `axis_topic`，冻结的标注提示又明确要求 `must` 里只写 `pair`＋`axis_side`
    （`tools/kb_fetch/holdout_gen.py` 的规则 10），于是那一类边**永远**少一个成员。

    这是**规格级**的冲突（改判据＝改验收口径），不是实现能自行选的。所以这里只把
    "标注 ⊆ 索引"这一层单独算出来作**诊断**，门⑪ 的判据仍按规格字面（完全相等），
    免得把"结构性冲突"误读成"标注噪声"。详见
    `docs/evidence/20261001-0100/p14_acceptance_ceiling.md` 与
    `docs/evidence/20261001-0057/measurement_integrity.md`。
    """
    try:
        etype, plain, forbid = parse_spec(spec)
    except EntryError:
        return False
    want_plain = set()
    for kind, value in plain.items():
        node_id = _node_id_for(graph, kind, value)
        if not node_id:
            return False
        want_plain.add((kind, node_id))
    want_forbid = set()
    for kind, value in forbid.items():
        node_id = _node_id_for(graph, kind, value)
        if not node_id:
            return False
        want_forbid.add((kind, node_id))
    for edge in graph.edges:
        if str(edge.type) != etype:
            continue
        edge_plain = {(m.kind, m.node_id) for m in edge.members
                      if m.role != "forbid"}
        edge_forbid = {(m.kind, m.node_id) for m in edge.members
                       if m.role == "forbid"}
        if want_forbid == edge_forbid and want_plain <= edge_plain:
            return True
    return False


def _edge_values(edge, kind: str) -> set:
    return {str(member.node_id).split(":", 1)[-1] for member in edge.members
            if str(member.kind) == kind}


def specs_supported_by(edge, specs: Sequence[str]) -> bool:
    """该边是否支撑标注里的某一组 ``spec``（按 kind 逐类比较）。

    判据与校验门③的"闭集"一致：**只比较 ``spec`` 写出来的 kind**，
    不要求边包含标注者没写的槽位。
    """
    for spec in specs or ():
        values = _spec_values(spec)
        if not values:
            continue
        if all(values[kind] in _edge_values(edge, kind)
               for kind in values):
            return True
    return False


def _metric(name: str, numerator: int, denominator: int, line: float,
            *, kind: str = "ratio", note: str = "") -> Dict[str, Any]:
    if denominator <= 0:
        return {"id": name, "status": "fail", "numerator": numerator,
                "denominator": denominator, "value": None, "line": line,
                "note": note or "分母为 0：按 §4.1b 硬规则 1 判失败"}
    value = numerator / denominator
    if kind == "min":
        ok = value >= line
    elif kind == "max":
        ok = value <= line
    else:                                   # 契约型：必须刚好等于
        ok = abs(value - line) <= 1e-9
    return {"id": name, "status": "pass" if ok else "fail",
            "numerator": numerator, "denominator": denominator,
            "value": round(value, 4), "line": line, "note": note}


def _q7_gate_metric(graph, conflicts: int, seen: set) -> Dict[str, Any]:
    """§4.1b 的**禁忌覆盖门** + §4.1 R52 的"两个分母别混"。

    * **夹具侧**（这里）：`q` 点名了索引里被禁取值的**条目数 ≥ `MIN_FORBID_ITEMS`**，
      **且**索引里每个 `forbid` 成员至少被 1 条 `q` 点名。这一侧是 `q` × 索引的
      机械统计，**不掺检索名次**。
    * **运行侧**：拦截率 = "注入文本带上该 `forbid` 成员"的**镜头数** /
      "查询命中某边 `forbid` 成员"的**镜头数**——只在真实模型运行上判
      （§4.4 步骤 2）；照夹具门用镜头数会得 0（R52 原话）。
    """
    members = forbid_members(graph)
    missing = [{"kind": m["kind"], "node_id": m["node_id"], "edge_id": m["edge_id"]}
               for m in members
               if (m["edge_id"], m["kind"], m["node_id"]) not in seen]
    ok = conflicts >= MIN_FORBID_ITEMS and not missing
    return {
        "id": "Q7",
        "status": "pass" if ok else "fail",
        "numerator": conflicts,
        "denominator": MIN_FORBID_ITEMS,
        "value": round(min(1.0, conflicts / MIN_FORBID_ITEMS), 4)
        if MIN_FORBID_ITEMS else 1.0,
        "line": 1.0,
        "note": (f"§4.1b 夹具覆盖门：`q` 点名了索引里被禁取值的条目数 {conflicts}"
                 f"（下界 {MIN_FORBID_ITEMS}）；索引里 {len(members)} 个 `forbid` 成员"
                 f"有 {len(members) - len(missing)} 个至少被 1 条 `q` 点名"
                 + (f"；**没被点名的**：{missing[:4]}" if missing else "")
                 + "。运行期的拦截率（按镜头）是**另一个分母**（§4.1 R52），"
                   "只在真实模型运行上判。"),
        "forbid_members": len(members),
        "uncovered_forbid_members": missing[:20],
    }


def score_entries(entries: Sequence[dict], graph: Hypergraph, *,
                  top_k: int = 3, token_limit: int = 2000) -> Dict[str, Any]:
    """按 §2.3 的 Q0–Q7 打分（只算超图这一侧；L3 的 E1/E3 由案例层另算）。"""
    norm_index = build_norm_index(graph)
    top1_hits = top3_required = required_total = selected_total = 0
    q4_hits = 0
    must_total = 0
    unresolved_must = 0
    unresolved_entries = 0
    unresolved_examples: List[Dict[str, Any]] = []
    negative_pairs = negative_hits = 0
    q6a_edges = q6a_ok = 0
    q6b_required = q6b_ok = 0
    q7_queries = 0
    q7_members_seen: set = set()
    queries = 0

    for entry in entries:
        query = str(entry.get("q") or "")
        if not query:
            continue
        queries += 1
        edges, _text, _trace = graph.retrieve(
            query, top_k=top_k, token_limit=token_limit)
        # 标注写的是 `TYPE:槽位=取值,…`（协议 §2.2）；这里按"成员集完全相等"映射到
        # 当次索引里的那条边，再取它的真 norm_key（含 role）。
        must_items = list(entry.get("must") or [])
        must_resolved = [entry_key(item, graph) for item in must_items]
        must_keys = [key for key in must_resolved if key is not None]
        must_total += len(must_items)
        missing = [str(item) for item, key in zip(must_items, must_resolved)
                   if key is None]
        if missing:
            unresolved_must += len(missing)
            unresolved_entries += 1
            if len(unresolved_examples) < 5:
                unresolved_examples.append(
                    {"id": entry.get("id"), "q": query, "unresolved": missing[:3]})
        required_ids = {norm_index[key] for key in must_keys
                        if key in norm_index}
        top1_keys = [key for key in
                     (entry_key(item, graph) for item in (entry.get("top1") or []))
                     if key is not None]
        top1_ids = {norm_index[key] for key in top1_keys if key in norm_index}
        never_keys = [key for key in
                      (entry_key(item, graph) for item in (entry.get("never") or []))
                      if key is not None]
        never_ids = {norm_index[key] for key in never_keys
                     if key in norm_index}

        selected_ids = [edge.edge_id for edge in edges]
        if top1_ids and selected_ids and selected_ids[0] in top1_ids:
            top1_hits += 1
        if required_ids & set(selected_ids):
            top3_required += 1
        # Q4 是**按 (query, edge) 对**聚合的（规格 §4.1 line 831：
        # `命中的 required_hyperedge_ids 数 / Σ_q |required(q)|`）——不是
        # "至少命中一条的 query 数"，更不是分子恒等于分母的恒真式。
        q4_hits += len(required_ids & set(selected_ids))
        required_total += len(required_ids)
        selected_total += len(selected_ids)
        negative_pairs += len(never_ids)
        negative_hits += len(never_ids & set(selected_ids))

        # Q6a（契约型）：返回的边界**就是**索引里那一条——成员一致，
        # 且 ``edge_id`` 能按冻结公式重算出来（索引键 == 重算值）。
        # 这不是同义反复：成员被改过、或 id 公式漂了，这里立刻红。
        for edge in edges:
            q6a_edges += 1
            record = graph.by_id.get(edge.edge_id)
            if record is not None and tuple(record.members) == tuple(edge.members) \
                    and norm_key(record) == norm_key(edge):
                q6a_ok += 1

        # Q6b：注入文本必须**成员齐全**（allow 与 forbid 全部出现）。
        text, _dropped, _fail = render_edges(edges, graph.nodes, token_limit)
        for key in must_keys:
            edge_id = norm_index.get(key)
            if edge_id is None:
                continue
            q6b_required += 1
            edge = graph.by_id.get(edge_id)
            if edge is None:
                continue
            if all(_member_present(text, member, graph.nodes)
                   for member in edge.members):
                q6b_ok += 1

        # Q7：**§4.1 的 R52 把两个分母分开了，别再混**——
        # 这里算的是**夹具覆盖门**（`q` × 索引的机械统计，不掺检索名次）：
        # 「`q` 的某个键值与某条边的 `forbid` 成员同类同值」的**条目数**，
        # §4.1b 要求 ≥60，且**每个 `forbid` 成员**至少被 1 条这样的 `q` 点名。
        # **运行期**的拦截率（"该情形镜头数" 作分母、注入文本必须带上该成员）
        # 只在真实模型运行上判（§4.4 步骤 2）。
        conflict = query_names_forbidden(query, graph)
        if conflict:
            q7_queries += 1
            for member in conflict:
                q7_members_seen.add((member["edge_id"], member["kind"],
                                     member["node_id"]))

    metrics = [
        _metric("Q1", top1_hits, queries, 0.70, kind="min",
                note=f"held-out query 数 {queries}（下界 {MIN_QUERIES}）"),
        _metric("Q2", top3_required, queries, 0.90, kind="min"),
        _metric("Q3", negative_hits, negative_pairs, 0.10, kind="max"),
        _metric("Q4", q4_hits, required_total, 1.0, kind="contract",
                note=f"required 总数 {required_total}（下界 {MIN_REQUIRED}）"),
        _metric("Q6a", q6a_ok, q6a_edges, 1.0, kind="contract"),
        _metric("Q6b", q6b_ok, q6b_required, 1.0, kind="contract"),
        #: §4.1b 的**夹具覆盖门** + §4.1 R52 的"两个分母别混"。
        #: 这里不判"拦截率"（那要真实运行的镜头），只判**材料够不够**：
        #: ① 冲突条目数 ≥ `MIN_FORBID_ITEMS`；② 索引里**每个 `forbid` 成员**
        #: 至少被 1 条 `q` 点名。两条都不满足就判失败（硬规则 1：分母下界）。
        _q7_gate_metric(graph, q7_queries, q7_members_seen),
    ]
    for item in metrics:
        if item["id"] in ("Q1", "Q2") and queries < MIN_QUERIES:
            item["status"] = "fail"
            item["note"] = (f"held-out query 数 {queries} < 下界 {MIN_QUERIES}："
                            f"按 §4.1b 判失败")
        if item["id"] == "Q4" and required_total < MIN_REQUIRED:
            item["status"] = "fail"
            item["note"] = (f"required 总数 {required_total} < 下界 "
                            f"{MIN_REQUIRED}")
    # §2.3 的 Q6b 前置①（构建期覆盖门）：「若某 query 的 required 边在归并后确实
    # 不存在，则**索引构建失败**（不留给 P14-4 去发现）」。也就是说，解析不到索引边的
    # `must` **不是**"这条不计"，而是 oracle 与索引不同构——它会让 required 的分母
    # 凭空变小（把 Q1/Q2/Q4/Q6b 一起抬高），因此必须单独记账并判失败。
    # （此前它被 `if key is not None` 静默丢掉，正是硬规则 1/2 要堵的洞。）
    unresolved_ok = unresolved_must == 0
    return {"queries": queries, "edges": len(graph.edges),
            "selected_total": selected_total, "metrics": metrics,
            "must_total": must_total,
            "required_unresolved": unresolved_must,
            "required_unresolved_entries": unresolved_entries,
            "unresolved_examples": unresolved_examples,
            "passed": unresolved_ok
            and all(item["status"] == "pass" for item in metrics)}


def _member_present(text: str, member, nodes) -> bool:
    """该成员的名字（或别名）是否出现在注入文本里。"""
    return any(name and name in text
               for name in _node_names(nodes.get(member.node_id),
                                       member.node_id))


def _node_names(node, node_id: str) -> set:
    """一个节点可能被写成的所有名字：id 尾段、规范名、全部别名。"""
    names = {str(node_id).split(":", 1)[-1]}
    if node is not None:
        names.add(str(node.name))
        names.update(str(alias) for alias in (node.aliases or []))
    return {name for name in names if name}


def forbid_members(graph) -> List[Dict[str, Any]]:
    """索引里每个 **`forbid` 成员** → `{kind, names, edge_id}`。

    §4.1b 的禁忌覆盖门有一半是"**每个 `forbid` 成员**至少出现在 1 条 `q` 冲突
    用例里"，所以这里按成员（而不是按取值）列出来，名字集含别名。
    """
    out: List[Dict[str, Any]] = []
    for edge in graph.edges:
        for member in edge.members:
            if str(member.role) != "forbid":
                continue
            out.append({"kind": str(member.kind),
                        "names": _node_names(graph.nodes.get(member.node_id),
                                             member.node_id),
                        "node_id": str(member.node_id),
                        "edge_id": edge.edge_id})
    return out


def query_names_forbidden(query: str, graph) -> List[Dict[str, Any]]:
    """这条 `q` 点名了哪些**索引里被某条边禁止**的取值（§4.1b 的冲突用例口径）。

    **与 §4.1 的 R52 一条对齐**："两个分母别混"——这一侧是**夹具覆盖门**
    （`q` × 索引的机械统计，不掺检索名次）；**运行期**的拦截率是"按镜头"的另一个
    分母（该情形镜头数），由真实模型运行给出。

    **点名有两种合法写法，两种都算**（2026-10-02 对齐，见下）：

    * **冲突式**：主键指的是被禁的那个取值（`特效=flame`，而索引里某条边禁止
      `vfx:flame`）——导演要的正是这条边禁止的东西；
    * **回避式**：`禁<主键>`（`禁特效=flame`）——导演明说不要它。

    为什么必须把后者也算进来：`tools/holdout_pool.required_q_hint` 有一条硬规则
    ——"被禁止的取值**只能**挂在 `禁<主键>` 上"（那是为了修一次真实的误读事故，
    见那里的注释）。于是池通道产出的禁忌条目**全部**是回避式，而本函数原先只读
    主键：它把 99/101 个 `forbid` 成员算作"被点名"，剩下 2 个（`vfx:flame`）
    永远算不到——**因为那两个 kind 在同一条边里已经被必需 allow 槽位占用，
    同一个键在 `parse_q` 里只能出现一次**，冲突式在那两条边上结构性地写不出来。
    也就是说：不是标注没写，是两件工具的"点名"定义不一致。

    判据本身没有放宽——仍然要求"每个 `forbid` 成员至少被一条**真实查询**点到名"，
    只是承认"回避式"也是真实查询。
    """
    #: 把 `禁<主键>`（`parse_query_full` 的第二个返回值）也并进同一个 kind 的取值集合
    #: ——见上面「两种写法都算」的说明。`parse_query` 只返回正向那半，所以这里必须用
    #: 完整版；否则"回避式"的禁忌条目一条都算不到。
    positive, forbidden = parse_query_full(query)
    parsed: Dict[str, List[str]] = {kind: list(values)
                                    for kind, values in positive.items()}
    for kind, values in forbidden.items():
        parsed.setdefault(kind, []).extend(values)
    hits: List[Dict[str, Any]] = []
    for member in forbid_members(graph):
        for value in parsed.get(member["kind"], ()):
            if str(value) in member["names"]:
                hits.append(member)
                break
    return hits


def _query_conflicts_with_forbid(query: str, edges: Iterable, graph) -> List:
    """返回"查询值与该边 forbid 成员同类同值"的 forbid 成员。"""
    wanted = parse_query(query)
    wanted_values = {item for values in wanted.values() for item in values}
    conflicts: List = []
    for edge in edges:
        for member in edge.members:
            if str(member.role) != "forbid":
                continue
            node = graph.nodes.get(member.node_id)
            # 查询里写的是**人话**（"固定"），索引里是 id（movement:static）
            # 与别名（"固定机位"/"static"）——两边都要按名字集对齐。
            if _node_names(node, member.node_id) & wanted_values:
                conflicts.append(member)
    return conflicts


def load_graph(nodes_path: Path, edges_path: Path) -> Hypergraph:
    """从索引文件读回超图——用模块自己的 ``from_dict``，不另写一套解析。"""
    from block_director.knowledge.hypergraph import HyperEdge, Node

    nodes = [Node.from_dict(item) for item in _load_jsonl(nodes_path)]
    edges = [HyperEdge.from_dict(item) for item in _load_jsonl(edges_path)]
    return Hypergraph(nodes, edges)


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        text = line.strip()
        if text:
            out.append(json.loads(text))
    return out


def load_holdout(path: Path) -> List[dict]:
    return _load_jsonl(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_score")
    parser.add_argument("--holdout", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--nodes", default="knowledge/hypergraph.nodes.jsonl")
    parser.add_argument("--edges", default="knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--token-limit", type=int, default=2000)
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv[1:] if argv else sys.argv[1:])

    graph = load_graph(ROOT / args.nodes, ROOT / args.edges)
    entries = load_holdout(ROOT / args.holdout)
    if not entries:
        print("[INCOMPLETE] held-out 为空：Q1–Q7 无法判定（不得判通过）")
        return 1
    report = score_entries(entries, graph, top_k=args.top_k,
                           token_limit=args.token_limit)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
