"""规则包装配（执行文档 v1.5 TDD §5.1/§5.2/§5.3；卡 P4-T1/P4-T2）。

PRD 的问题陈述（P-3）说得很直白：超图 RAG 与三栏注入都已实现，但

* 注入**无强度标注**——`hardness` 在边上、渲染进 prompt 时却不区分"必须"与
  "通常"，模型无法掌握让步空间；
* **无规则预算**——一次注入多少条不可控，规则堆积会互相打架；
* **冲突不并陈**——两条规则竞争时系统悄悄二选一，不交给模型裁决。

本模块把这三件事一次做掉，并且**只加一层**：渲染的正文仍然由
``hypergraph.render_edge`` 产出（单一真源），这里只在前面贴强度标、在外面套
条数预算与冲突并陈。**判据/阈值/门限一个字没动**（红线 R-5）：强度标来自边自己
的 ``hardness``，预算来自 ``rag.rule_top_k``。

纯 Python，不 import bpy（红线 R-1）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .hypergraph import HyperEdge, Node, node_value, render_edge, render_tokens

#: 强度前缀（TDD §5.1）。**硬边**不是"永远不能违反"，而是"要违反必须声明"
#: ——这正是 FR-8 的破例辩护字段存在的理由，两者必须一起读。
HARD_PREFIX = "[必须（除非声明破例）]"
SOFT_PREFIX = "[通常]"

#: 冲突并陈的固定尾注（TDD §5.2）。措辞里必须有"由你裁决"——系统的职责是
#: 把竞争摆出来，不是替模型选一个。
CONFLICT_TAIL = "（更具体者优先，由你裁决）"

#: 自由度声明的小节标题（TDD §5.3）。
FREEDOM_TITLE = "【自由度】"

#: ``rag.rule_top_k`` 的缺省与合法区间（与 ``contracts/config.py`` 的校验同源；
#: 这里再写一遍只是为了"没有配置对象时也能跑"，**不是第二真源**——
#: 真正的单一真源仍是 `RagConfig.rule_top_k`）。
DEFAULT_RULE_TOP_K = 5


@dataclass
class RulePackStats:
    """一次装配的可审计读数（进 ``knowledge_trace``）。"""

    budget: int = DEFAULT_RULE_TOP_K
    hard: int = 0
    soft: int = 0
    injected: int = 0
    count_dropped: List[str] = field(default_factory=list)
    token_dropped: List[str] = field(default_factory=list)
    conflict_pairs: int = 0
    conflict_edge_ids: List[str] = field(default_factory=list)
    tokens: int = 0
    quality_fail: bool = False

    @property
    def dropped(self) -> List[str]:
        return list(self.count_dropped) + list(self.token_dropped)

    def to_dict(self) -> Dict[str, Any]:
        return {"budget": int(self.budget), "hard": int(self.hard),
                "soft": int(self.soft), "injected": int(self.injected),
                "count_dropped": list(self.count_dropped),
                "token_dropped": list(self.token_dropped),
                "conflict_pairs": int(self.conflict_pairs),
                "conflict_edge_ids": list(self.conflict_edge_ids),
                "tokens": int(self.tokens),
                "quality_fail": bool(self.quality_fail)}


def strength_prefix(edge: HyperEdge) -> str:
    """这条边该贴哪个强度标（``soft`` → ``[通常]``，其余 → ``[必须…]``）。"""
    return SOFT_PREFIX if str(getattr(edge, "hardness", "hard")) == "soft" \
        else HARD_PREFIX


def rule_line(edge: HyperEdge, nodes: Optional[Dict[str, Node]] = None) -> str:
    """一条规则**带强度标**的一行。

    正文调用 ``hypergraph.render_edge``（单一真源），所以"禁={…} 必须与 allow
    一起出现"这条闭合输出纪律不会因为这里多贴一个前缀而丢。
    """
    return f"{strength_prefix(edge)} {render_edge(edge, dict(nodes or {}))}"


def _primary_key(edge: HyperEdge,
                 nodes: Dict[str, Node]) -> Tuple[str, str]:
    """分桶键 = ``(类型, 主键值)``（TDD §5.2）。

    主键取**第一个非 forbid 成员**（成员顺序是抽取与校验时的稳定顺序），
    所以同一个"话题 × 类型"下的近邻边才会落进同一个桶、才有"桶内超预算截断"
    可言。
    """
    for member in edge.members:
        if member.role == "forbid":
            continue
        return (str(edge.type),
                f"{member.kind}={node_value(nodes.get(member.node_id), member.node_id)}")
    return (str(edge.type), "")


def _conflict_key(edge: HyperEdge,
                  nodes: Dict[str, Node]) -> Tuple[str, str]:
    """**冲突检测**的分桶键 = ``(类型, 主键 kind)``。

    为什么不复用 :func:`_primary_key`（值桶）：TDD §5.2 点名的第一种冲突是
    "**同 kind 不同值**"（`构图=occlusion` vs `构图=balance`）——而这两条边
    **按定义**不在同一个**值**桶里，用值桶会让这类冲突结构性检测不到。
    第二种冲突（一条 allow、另一条 forbid 同一个取值）在两种桶下都成立。
    （真索引里的形状：`STAGING_PACK` 有 4 条边必填成员完全相同、只差"禁止哪个
    构图规则"——见 `hypergraph.FORBID_QUERY_KEYS` 的注释。）

    所以**两个桶各司其职**：值桶管"条数预算"（TDD 原文），kind 桶管"冲突搜索"。
    """
    for member in edge.members:
        if member.role == "forbid":
            continue
        return (str(edge.type), str(member.kind))
    return (str(edge.type), "")


def _kind_values(edge: HyperEdge, nodes: Dict[str, Node]) -> Dict[str, set]:
    """这条边**正向**讲了哪些 ``kind=value``（forbid 成员不算）。"""
    out: Dict[str, set] = {}
    for member in edge.members:
        if member.role == "forbid":
            continue
        value = node_value(nodes.get(member.node_id), member.node_id)
        out.setdefault(member.kind, set()).add(value)
    return out


def _forbid_values(edge: HyperEdge, nodes: Dict[str, Node]) -> Dict[str, set]:
    out: Dict[str, set] = {}
    for member in edge.forbids:
        value = node_value(nodes.get(member.node_id), member.node_id)
        out.setdefault(member.kind, set()).add(value)
    return out


def edges_conflict(a: HyperEdge, b: HyperEdge,
                   nodes: Dict[str, Node]) -> bool:
    """两条边是否**结论互斥**（TDD §5.2 的两种情形，纯函数）。

    ① 同一个 kind 上给出**不同的取值**（`构图=occlusion` vs `构图=balance`）；
    ② 一条允许 (kind, value)，另一条**禁止**同一个 (kind, value)。
    """
    av, bv = _kind_values(a, nodes), _kind_values(b, nodes)
    for kind, a_values in av.items():
        b_values = bv.get(kind)
        if b_values and a_values != b_values:
            return True
    for kind, a_values in av.items():
        if a_values & _forbid_values(b, nodes).get(kind, set()):
            return True
    for kind, b_values in bv.items():
        if b_values & _forbid_values(a, nodes).get(kind, set()):
            return True
    return False


def conflict_pairs(edges: Sequence[HyperEdge], nodes: Dict[str, Node]
                   ) -> List[Tuple[HyperEdge, HyperEdge]]:
    """同桶内的冲突对（跨桶不算——不同话题的规则各说各话，不是竞争）。

    桶见 :func:`_conflict_key`（`(类型, 主键 kind)`）。
    """
    buckets: Dict[Tuple[str, str], List[HyperEdge]] = {}
    for edge in edges:
        buckets.setdefault(_conflict_key(edge, nodes), []).append(edge)
    pairs: List[Tuple[HyperEdge, HyperEdge]] = []
    for entries in buckets.values():
        for index, first in enumerate(entries):
            for second in entries[index + 1:]:
                if edges_conflict(first, second, nodes):
                    pairs.append((first, second))
    return pairs


def freedom_block(constrained_kinds: Sequence[str],
                  blank_kinds: Sequence[str]) -> str:
    """TDD §5.3 的自由度声明（两行）。

    ``constrained_kinds`` = 本场戏**已有强惯例**的维度（被 hard 边覆盖的 kind）；
    ``blank_kinds`` = **刻意留白**的维度（查询点名的 kind 里没被任何边覆盖的）。
    两边都空时返回空串（不产出空标题）。
    """
    lines: List[str] = []
    constrained = [str(item) for item in constrained_kinds if str(item)]
    blank = [str(item) for item in blank_kinds if str(item)]
    if constrained:
        lines.append(f"- 已有强惯例（按它来）：{'、'.join(sorted(set(constrained)))}")
    if blank:
        lines.append(f"- 刻意留白（可自由发挥）：{'、'.join(sorted(set(blank)))}")
    if not lines:
        return ""
    return FREEDOM_TITLE + "\n" + "\n".join(lines)


def render_rule_pack(edges: Sequence[HyperEdge],
                     nodes: Optional[Dict[str, Node]] = None, *,
                     budget: int = DEFAULT_RULE_TOP_K,
                     token_limit: int = 400,
                     exempt_edge_ids: Sequence[str] = ()
                     ) -> Tuple[str, List[str], RulePackStats]:
    """按 TDD §5.1/§5.2 装配规则包，返回 ``(文本, dropped, stats)``。

    纪律：

    1. **分桶限条数**：同 ``(类型, 主键值)`` 桶最多 ``budget`` 条，桶内按
       ``confidence × occurrences`` 降序取前 ``budget``（确定性：同分比 edge_id）。
    2. **冲突对不受条数预算截断**（宁可超一条，不藏冲突）：被判定为冲突的边
       一律保留，并在正文里并陈成一行 ``[冲突] A ｜ B（更具体者优先，由你裁决）``。
    3. **禁忌补挂不受条数预算**（FR-9）：``exempt_edge_ids`` 里的边跳过桶截断。
    4. **原子注入**：一行装不下就整条不注入并记 dropped（绝不截断）——
       与 ``hypergraph.render_edges`` 逐字同一条纪律。
    """
    node_map = dict(nodes or {})
    stats = RulePackStats(budget=int(budget))
    items = [edge for edge in (edges or [])]
    stats.hard = sum(1 for edge in items if strength_prefix(edge) == HARD_PREFIX)
    stats.soft = len(items) - stats.hard

    pairs = conflict_pairs(items, node_map)
    conflicted: set = set()
    for first, second in pairs:
        conflicted.add(first.edge_id)
        conflicted.add(second.edge_id)
    stats.conflict_pairs = len(pairs)
    stats.conflict_edge_ids = sorted(conflicted)
    exempt = {str(item) for item in (exempt_edge_ids or ())}

    # ---- 桶内截断（冲突边与补挂边不受截断） ----
    buckets: Dict[Tuple[str, str], List[HyperEdge]] = {}
    for edge in items:
        buckets.setdefault(_primary_key(edge, node_map), []).append(edge)
    kept: List[HyperEdge] = []
    for key in sorted(buckets):
        entries = sorted(buckets[key],
                         key=lambda e: (-(float(e.confidence) * int(e.occurrences)),
                                        e.edge_id))
        room = max(int(budget), 1)
        for edge in entries:
            if edge.edge_id in conflicted or edge.edge_id in exempt:
                kept.append(edge)
                continue
            if room > 0:
                kept.append(edge)
                room -= 1
            else:
                stats.count_dropped.append(edge.edge_id)

    # ---- 原子注入（token 上限，绝不截断） ----
    #: TDD §5.6 的"渲染排最前"落在这里：**禁忌补挂**的边要最先被模型看到
    #: （先看到"这条不能做"，再看"该怎么做"）。注意这只改**注入文本的顺序**，
    #: **不改检索名次**——名次属于 `Hypergraph.retrieve` 的 `selected`，而 `Q1`
    #: （每个查询的 top-1 是否就是期望边）量的正是那个顺序。实测（2026-10-07）：
    #: 把补挂边插到**检索列表最前**会让 Q1 从 0.9975 塌到 0.1208（40 条抽样里
    #: 30 条的 top-1 被顶掉）。
    kept = ([edge for edge in kept if edge.edge_id in exempt]
            + [edge for edge in kept if edge.edge_id not in exempt])

    lines: List[str] = []
    used = 0
    for edge in kept:
        line = rule_line(edge, node_map)
        cost = render_tokens(line)
        if cost > token_limit or used + cost > token_limit:
            stats.token_dropped.append(edge.edge_id)
            if cost > token_limit:
                stats.quality_fail = True
            continue
        lines.append(line)
        used += cost

    # ---- 冲突并陈（冲突对不受预算截断，附在正文之后） ----
    for first, second in pairs:
        line = (f"[冲突] {render_edge(first, node_map)} ｜ "
                f"{render_edge(second, node_map)}{CONFLICT_TAIL}")
        cost = render_tokens(line)
        if cost > token_limit:
            stats.quality_fail = True
            continue
        lines.append(line)
        used += cost

    stats.injected = len(lines)
    stats.tokens = used
    return "\n".join(lines), stats.dropped, stats


__all__ = [
    "HARD_PREFIX", "SOFT_PREFIX", "CONFLICT_TAIL", "FREEDOM_TITLE",
    "DEFAULT_RULE_TOP_K", "RulePackStats",
    "strength_prefix", "rule_line", "edges_conflict", "conflict_pairs",
    "freedom_block", "render_rule_pack",
]
