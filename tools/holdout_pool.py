"""held-out oracle **v2：候选池标注**（P14-1）。

为什么要有这个文件（裁决背景见 `docs/knowledge/ORACLE_DECISION_v15.md`）：

旧通道（`tools/holdout_fill.py`）让标注方在**看不见索引**的前提下自由写
`must`。实测 4558 条未解析 spec 里，与"该卡自己的抽取原子边"成员集完全吻合的
只有 **26 条**、卡片正文含全部期望取值的 **0 条** —— 标注员写的是**编出来的边**。
而供给侧只有 1.35 原子边/卡，oracle 却要 ≈8500 条期望，**期望空间约为语料真实
知识量的 3 倍**。门⑩（期望边必须存在于索引）因此在构造上不可达；门⑧（换族）
又禁止"机械从索引派生 oracle"（那是自证）。唯一自洽的解是 **TREC 式的候选池
标注**：标注方只看**本卡自己的原子边候选池**，从池里挑 `must`／`top1`。

本文件提供两条通道：

* `--mechanical`：**不调模型**，直接把每条索引边写成一条期望（`q` 由该边的
  可查询成员拼出）。它保证门⑨（`q` 覆盖 `must[0]`／`top1` 的全部可查询槽位）
  与门⑩（`must`／`top1`／`never` 都能解析到索引边）**由构造成立**，用来在
  API 不可用时拿到一份可过门的文件、并作为回归基线。
  **它不是换族证据**：`annotator.family` 如实写 `rule`，门⑧ 只认模型族。
* `--provider glm`：把候选池交给 GLM（family=zhipu，与抽取器 deepseek 不同族），
  由它挑 `must`／`top1`／`never` 并写 `q`。产出侧用**同一套**判据拦。

`Q4 = 1.0` 的结构性天花板：它要求**每一条** `required` 边都落进 top-3，所以
`q` 必须能把目标边与同类别的边区分开。实测把 `(type, q)` 相同的边分到一组后，
组大小分布是 `{1: 527, 2: 162, 3: 9, 4: 2, 5: 1}` —— **878/891 条边**所在的组
≤3、可以整体落进 top-3；剩 13 条（3 个组）在构造上无法满足 Q4，按
`query_ambiguous_group` 计入报告，**不编造查询**。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_holdout import (  # noqa: E402
    NON_MODEL_ANNOTATOR_FAMILIES,
    Q_KEY_TO_KIND,
    EntryError,
    query_shortfall,
    validate_entry,
)
from tools.holdout_score import load_graph, spec_to_norm_key  # noqa: E402
from block_director.knowledge import hypergraph as _hg  # noqa: E402

#: `kind` → `q` 里的中文键。**从 `check_holdout` 反查**，不手抄第二份。
#: kind → **主键**。必须只从 `hypergraph.QUERY_KEYS` 建：`Q_KEY_TO_KIND` 现在还含
#: `禁<键>`（同样映射到同一个 kind），从它建会让**主键被 forbid 键覆盖**
#: ——实测后果是 `构图=framing` 被 `禁构图=rule_of_thirds` 顶掉，于是
#: 门⑨ 判"必填槽位没写进 q"，一次跑出 **263 条 weak_q 拒收**。
KEY_FOR_KIND: Dict[str, str] = {kind: key for key, kind in _hg.QUERY_KEYS.items()}
#: kind → **forbid 键**（`构图` → `禁构图`）。见 `hypergraph.FORBID_QUERY_KEYS`：
#: 主键已被必填值占用时，被禁止的取值只能走这个键，否则 `q` 表达不出"不要它"。
FORBID_KEY_FOR_KIND: Dict[str, str] = {kind: key for key, kind in
                                       _hg.FORBID_QUERY_KEYS.items()}
#: `q` 里的键 → kind（`构图` 与 `禁构图` 都指向 `composition_rule`）。
KIND_OF_KEY: Dict[str, str] = dict(Q_KEY_TO_KIND)

DEFAULT_NODES = "knowledge/hypergraph.nodes.jsonl"
DEFAULT_EDGES = "knowledge/hypergraph.edges.jsonl"
DEFAULT_CARDS = "fixtures/knowledge_holdout.cards.json"
DEFAULT_OUT = "work/glm_pool/mechanical.jsonl"
DEFAULT_VOCAB = "fixtures/knowledge_holdout.vocab.json"

#: 一条 `q` 最多挂几张来源卡（同一张卡的知识、同一条查询 = 同一条期望，
#: 多挂几张卡只是让门⑥ 的来源覆盖更广，不改变 Q2 的判据）。
#: 一条边挂几张来源卡。**0 = 不设上限**（默认）。
#:
#: 门⑥ 要求「每张入库卡至少派生 1 条」（`from_card` 去重后 ⊇ 卡片集合），
#: 所以"每条边 × 它的每一张来源卡 = 一条期望"**本来就是协议要的形态**，
#: 不是凑数：每条边在不同卡上表达的是那张卡的知识。实测 915 条边覆盖
#: **1937/2067 张卡**，而截断到 5 张时门⑥ 缺 809 张 —— 少掉的那 679 张
#: 全是"卡在边上、但被截断/被词表/被组大小挡掉"的。
#: 截断只在**自检**时有用（`--max-cards N`），出正式产物时不该截断。
MAX_CARDS_PER_EDGE = 0

#: 门③ 要求每个词表取值至少出现在 `min_support` 个不同的 `(卡片, 查询)` 对里。
#: 主通道按 `MAX_CARDS_PER_EDGE` 截断来源卡，冷门取值会因此掉到 3 以下；
#: 补覆盖轮**只**为这些取值追加"换一张来源卡"的条目（不做无差别的膨胀）。
MIN_VALUE_SUPPORT = 3


def value_of(node_id: str) -> str:
    return str(node_id).split(":", 1)[1]


def spec_of(edge) -> str:
    """索引边 → oracle 规格串（`TYPE:槽位=取值,…`）。"""
    slots = []
    for member in edge.members:
        prefix = "forbid_" if member.role == "forbid" else ""
        slots.append("%s%s=%s" % (prefix, member.kind, value_of(member.node_id)))
    return "%s:%s" % (edge.type, ",".join(slots))


def query_of(edge) -> str:
    """索引边 → 查询串。

    `q` 同时写该边的 **plain** 可查询成员与 **forbid** 可查询成员：后者是
    §3.3 的 Q7 冲突条目（`q` 里点名了一个被 `must` 禁止的取值），也正是门⑤
    要的样本；顺带把 EMOTION_PACK 这类"同 plain、不同 forbid"的边区分开
    （唯一命中数 469 → 527）。

    同一个键既出现在 plain 又出现在 forbid 的边：被禁止的取值不能挤掉主键
    （`q` 里一个键只能有一个取值），所以走 **v1.6 的 `forbid` 键**（`构图=occlusion`
    ＋ `禁构图=balance`）。没有这套键时只能整条跳过 forbid 侧，实测后果是
    `STAGING_PACK` 4 条边不可区分、**150 张卡**在门⑥ 里拿不到条目。
    """
    plain: Dict[str, str] = {}
    forbid: Dict[str, str] = {}
    for member in edge.members:
        key = KEY_FOR_KIND.get(member.kind)
        if not key:
            continue
        target = forbid if member.role == "forbid" else plain
        target[key] = value_of(member.node_id)
    merged = dict(plain)
    for key, value in forbid.items():
        if key not in plain:
            merged[key] = value
            continue
        forbid_key = FORBID_KEY_FOR_KIND.get(KIND_OF_KEY[key])
        if forbid_key:
            merged[forbid_key] = value
    return "；".join("%s=%s" % (key, value) for key, value in merged.items())


def query_signature(edge) -> Tuple[Tuple[str, str], ...]:
    """`(type, q)` 的分组键——`q` 相同的边在查询空间里**不可区分**。"""
    text = query_of(edge)
    return tuple(sorted(tuple(part.split("=", 1))
                        for part in text.split("；") if part))


def _member_pairs(edge) -> set:
    return {(member.role, member.kind, value_of(member.node_id)) for member in edge.members}


def pick_negative(edge, group_ids: set, by_type: Dict[str, list],
                  in_vocab=None):
    """负样本：**与本次查询不相交**的同类边（协议 §3.2 的定义）。

    §3.2 写死了负样本是什么：「`applies_to_*` 与查询不匹配，或 **allow 集与查询
    完全不相交**的边」。第一版实现挑的是"重叠最多的同类边"（想做成 hard negative），
    实测 Q3 = **0.2588**（合同线是 ≤0.10）——那类边本来就该被查询召回，把它们标成
    `never` 等于让 oracle 自相矛盾。改回 §3.2 的定义：取同类边里与目标边
    **成员集完全不相交**的那条（`edge_id` 最小者，保证确定性）。
    """
    want = _member_pairs(edge)
    for other in sorted(by_type.get(edge.type, ()), key=lambda item: item.edge_id):
        if other.edge_id in group_ids:
            continue
        if in_vocab is not None and not in_vocab(other):
            # `never` 也要过门③：词表外的取值出现在 `never` 里同样是
            # `unknown_values`（校验器把 `never` 与 `must` 一起算进 must_values）。
            continue
        if not (want & _member_pairs(other)):
            return other
    return None


def mechanical(graph, universe: Sequence[str], *,
               max_cards: int = MAX_CARDS_PER_EDGE,
               top_up: bool = True,
               vocab: Dict[str, Sequence[str]] | None = None) -> Tuple[List[dict], Dict]:
    """按 `(type, q)` 分组生成期望；组 ≤3 的组**整组**写进 `must`。

    `top_up`：主通道之后，为门③ 里支撑数 <3 的取值追加条目（换一张来源卡），
    直到每个取值都有 ≥3 个不同的 `(卡片, 查询)` 对，或来源卡用尽为止。
    """
    card_set = set(universe)
    # 冻结词表是**硬边界**：`q` 与 `must` 里出现词表外的取值，门③ 直接判
    # `unknown_values`（实测旧词表就是被"频次前 12"这个魔数卡出来的）。
    # 含词表外取值的边**整条不生成**，并如实计数——绝不为了凑覆盖去改词表取值。
    allowed = {kind: set(values) for kind, values in (vocab or {}).items()}

    def _in_vocab(edge) -> bool:
        if not allowed:
            return True
        for member in edge.members:
            values = allowed.get(str(member.kind))
            if values is None:
                continue
            if value_of(member.node_id) not in values:
                return False
        return True

    by_type: Dict[str, list] = collections.defaultdict(list)
    groups: Dict[Tuple, List] = collections.OrderedDict()
    for edge in graph.edges:
        by_type[edge.type].append(edge)
        groups.setdefault((edge.type, query_signature(edge)), []).append(edge)

    entries: List[dict] = []
    skipped = collections.Counter()
    full_counts = full_match_counts(graph)
    #: 门④ 的**可断言对**：该类在词表内、且有来源卡的 `(卡片, 查询)` 对。
    #: **由索引侧给出，与 oracle 实际生成了什么无关** —— 这是"每类至多要求它真能给的
    #: 那些对"这条新门限的输入（`check_holdout --assertable`）。
    assertable: Dict[str, int] = collections.Counter()
    #: `(kind, value)` → 该取值出现过的 (edge_group, edge_index, card) 三元组。
    #: 补覆盖轮用它来找"还能换哪张卡"。
    holders: Dict[Tuple[str, str], List[Tuple[int, int]]] = collections.defaultdict(list)
    group_rows: List[Tuple[List[str], List[int], List[List[str]]]] = []
    ordered = sorted(groups.items(), key=lambda item: (item[0][0], item[0][1]))
    for (_etype, _sig), group in ordered:
        outside = [edge for edge in group if not _in_vocab(edge)]
        if outside:
            skipped["value_outside_frozen_vocab"] += len(outside)
            group = [edge for edge in group if _in_vocab(edge)]
            if not group:
                continue
        live_sources = [sorted({str(s) for s in (e.sources or ()) if str(s) in card_set})
                        for e in group]
        if not any(live_sources):
            skipped["no_live_source_card"] += len(group)
            continue
        if len(group) > 3:
            # Q4 要求每一条 required 边都进 top-3；组内边数 >3 时构造上做不到。
            skipped["query_ambiguous_group"] += len(group)
            continue
        oversubscribed = full_counts[(_etype, _sig)]
        if oversubscribed > 3:
            # **比"组内条数"更准的一刀**：`(type, q)` 相同只是必要条件，真正会被
            # top-3 挤掉的，是"种子全被它解释、它的成员也全被查询点名"的那些边
            # ——实测有一组 `(type,q)` 只有 2 条边，却有 5 条别的边完全对齐同一个
            # 查询，于是 required 仍然进不了 top-3（Q4 卡在 0.95 的根因）。
            # 这类查询在 top-3 里**数学上塞不下**，按 `q_oversubscribed` 计入报告，
            # 不编造查询、也不许靠调 `top_k` 让它看起来过线。
            skipped["q_oversubscribed"] += len(group)
            continue
        group_ids = {e.edge_id for e in group}
        # 整组一起写进 `must`（≤3 条，符合协议上限），这样一组的每条边都被 required
        # 覆盖；`top1` 取第一条（协议要求 top1 ⊆ must）。
        specs = [spec_of(edge) for edge in group]
        slot = len(group_rows)
        group_rows.append((specs, list(range(len(group))), live_sources))
        for index, edge in enumerate(group):
            for member in edge.members:
                if member.role == "forbid":
                    continue
                key = KEY_FOR_KIND.get(member.kind)
                if key:
                    holders[(member.kind, value_of(member.node_id))].append((slot, index))
        for index, edge in enumerate(group):
            for card_index, card in enumerate(live_sources[index]):
                if max_cards and card_index >= max_cards:
                    break
                entries.append(_row(edge, card, specs, index, group_ids, by_type,
                                    _in_vocab))
                assertable[edge.type] += 1

    support: Dict[Tuple[str, str], set] = collections.defaultdict(set)
    for row in entries:
        signature = (row["from_card"], row["q"])
        for kind, value in _q_pairs(row["q"]):
            support[(kind, value)].add(signature)

    topped = collections.Counter()
    if top_up:
        for (kind, value), pairs in sorted(holders.items()):
            if len(support[(kind, value)]) >= MIN_VALUE_SUPPORT:
                continue
            for slot, index in pairs:
                specs, indices, live_sources = group_rows[slot]
                # 不截断时所有来源卡都已经在主通道里发过条目，补覆盖轮无处可加。
                tail = live_sources[index][max_cards:] if max_cards else []
                for card in tail:
                    if len(support[(kind, value)]) >= MIN_VALUE_SUPPORT:
                        break
                    text = _q_from_spec(specs[index])
                    if (card, text) in support[(kind, value)]:
                        continue
                    row = {
                        "from_card": card,
                        "q": text,
                        "must": list(specs),
                        "top1": [specs[index]],
                        "never": [],
                    }
                    entries.append(row)
                    topped[kind] += 1
                    for k, v in _q_pairs(row["q"]):
                        support[(k, v)].add((card, row["q"]))
                if len(support[(kind, value)]) >= MIN_VALUE_SUPPORT:
                    break
    return entries, {"skipped": dict(skipped), "groups": len(ordered),
                     "assertable_pairs_per_type": dict(sorted(assertable.items())),
                     "top_up_added": sum(topped.values()),
                     "top_up_by_kind": dict(topped),
                     "under_supported_values": sorted(
                         "%s=%s" % key for key, seen in support.items()
                         if len(seen) < MIN_VALUE_SUPPORT)}


def _q_pairs(text: str) -> List[Tuple[str, str]]:
    out = []
    for part in str(text).split("；"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        kind = Q_KEY_TO_KIND.get(key.strip())
        if kind:
            out.append((kind, value.strip()))
    return out


def full_match_counts(graph) -> Dict[Tuple, int]:
    """`(type, q)` → 同一查询下**完全对齐**的边数（含自己）。

    这里"完全对齐"的口径与检索侧一致：查询只包含目标边自己的可查询成员，所以
    一条边与之完全对齐 ⟺ 它的**可查询成员集合**相等。超过 3 条时 top-3 装不下，
    `Q4`（合同线 1.0）在数学上不可能过 —— 这类查询必须显式跳过并计数，
    而不是靠调 `top_k` 让它看起来过线。

    预计算一次，避免在分组循环里反复 O(边) 扫（654 组 × 847 边）。
    """
    counts: Dict[Tuple, int] = collections.Counter()
    for edge in graph.edges:
        counts[(edge.type, query_signature(edge))] += 1
    return dict(counts)


def _q_from_spec(spec: str) -> str:
    """规格串 → 查询串（与 `query_of` 同一口径：plain 与 forbid 的可查询键都写）。"""
    _etype, plain, forbid = __import__("tools.check_holdout",
                                       fromlist=["parse_spec"]).parse_spec(spec)
    merged = {}
    for kind, value in plain.items():
        key = KEY_FOR_KIND.get(kind)
        if key:
            merged[key] = value
    for kind, value in forbid.items():
        key = KEY_FOR_KIND.get(kind)
        if key and key not in merged:
            merged[key] = value
    return "；".join("%s=%s" % (key, value) for key, value in merged.items())


def _row(edge, card, specs, index, group_ids, by_type, in_vocab=None) -> dict:
    negative = pick_negative(edge, group_ids, by_type, in_vocab)
    never = []
    if negative is not None:
        spec = spec_of(negative)
        if spec not in specs:
            never = [spec]
    return {"from_card": card, "q": query_of(edge), "must": list(specs),
            "top1": [specs[index]], "never": never}


def finalise(raw_entries: Sequence[dict], graph, universe: Sequence[str],
             *, model_id: str, family: str, model_version: str,
             decode: str = "") -> Tuple[List[dict], List[dict]]:
    """逐条过**与校验器同一套**判据；不合格的收成 reject，绝不放行。"""
    entries: List[dict] = []
    rejects: List[dict] = []
    seen = set()
    annotator = {"model_id": model_id, "family": family,
                 "model_version": model_version, "prompt_sha256": "",
                 "decode": decode}
    #: 机械/规则通道**不是**换族证据（门⑧ 会判红，见 `NON_MODEL_ANNOTATOR_FAMILIES`）。
    #: 字段只有 strong/weak 两档，但默认挑好看的那档就是把"看起来独立"当成了"独立"：
    #: 实测 `--mechanical` 的产物曾写 `family="rule"` ＋ `independence="strong"`。
    independence = ("weak" if family in NON_MODEL_ANNOTATOR_FAMILIES else "strong")
    for raw in raw_entries:
        candidate = {"id": "hq_%04d" % (len(entries) + 1), **raw,
                     "annotator": dict(annotator),
                     "independence": independence, "pilot": False}
        try:
            validate_entry(candidate)
        except EntryError as exc:
            rejects.append({"reason": "gate2:%s" % exc, "raw": str(raw)[:200]})
            continue
        short = query_shortfall(candidate)
        if short:
            rejects.append({"reason": "weak_q:" + ",".join(short[:4]),
                            "raw": str(raw)[:200]})
            continue
        unresolved = []
        for field in ("must", "top1", "never"):
            for spec in candidate[field]:
                if spec_to_norm_key(str(spec), graph) is None:
                    unresolved.append((field, str(spec)[:80]))
        if unresolved:
            rejects.append({"reason": "gate10:unresolvable",
                            "raw": json.dumps(unresolved[:2], ensure_ascii=False)})
            continue
        key = (candidate["from_card"], candidate["q"],
               tuple(candidate["must"]), tuple(candidate["top1"]))
        if key in seen:
            continue
        seen.add(key)
        entries.append(candidate)
    return entries, rejects


def write_jsonl(path: pathlib.Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- GLM 通道

#: 换族纪律（协议 §5.1）：抽取器是 `deepseek`，所以标注必须换族。
#: 用户裁决：用智谱 GLM（`glm-4.7-flash` —— 同一套门，实测比 `glm-4.7` 快两个
#: 数量级；`glm-4.6`/`glm-4.5` 的资源包按模型计费，实测 429）。
GLM_MODEL = "glm-4.7-flash"

GLM_SYSTEM = (
    "你是分镜知识库的**独立标注员**。给你若干条**已抽取好的知识边**，每条边附一段"
    "它来自的卡片正文。你要为每条边写**一条检索期望**：\n"
    "1. `q`：导演会怎么写这条查询。**硬规则**：`q` 必须覆盖该边全部"
    "「有中文查询键的槽位」，取值逐字相同（键=值；键=值）；同一个键只能出现一次。\n"
    "2. `never`：从候选负样本里挑**最多 1 条**「这条查询绝不该召回它」的边，"
    "逐字复制；实在挑不出就写 []。\n"
    "只输出 JSON：{\"entries\":[{\"index\":<第几条>,\"q\":\"...\",\"never\":[\"...\"]}, ...]}。"
    "不要改写边的成员，不要发明新的边。"
)


def _rule_text() -> str:
    """键集与逐类槽位一律**从 `check_holdout` 渲染**，不手抄第二份。"""
    from tools.check_holdout import query_key_text, queryable_slot_hint
    return ("允许的查询键：%s。\n有查询键的槽位：%s。"
            % (query_key_text(), queryable_slot_hint()) +
            "\n**`q` 的键必须是上面那串中文键**（`运镜=`／`景别=`／`情绪=`…），"
            "写英文 kind 名（`action=`／`movement=`）会被机器整条拒收。")


def required_q_hint(item: dict) -> str:
    """这一条 `q` 里**必须出现**的 `键=取值`——由池直接算出来交给模型。

    把"哪些键不能漏"从"模型要记住规则"变成"照抄这一行"，是因为实测模型会写
    英文 kind 名（`action=…`）而被门② 整条拒收（首批 15/15 全废）。取值仍然是
    池里那条边的真值，模型要写的是"怎么组织一次导演查询"。
    """
    from tools.check_holdout import parse_spec

    seen: Dict[str, str] = {}
    for spec in item["specs"]:
        _etype, plain, forbid = parse_spec(spec)
        for kind, value in plain.items():
            key = KEY_FOR_KIND.get(kind)
            if key:
                seen[key] = value
        for kind, value in forbid.items():
            key = KEY_FOR_KIND.get(kind)
            if not key:
                continue
            if key not in seen:
                seen[key] = value
            else:
                # 主键已被必填值占用 → 用 forbid 键，把"不要这个取值"也写进 q。
                forbid_key = FORBID_KEY_FOR_KIND.get(kind)
                if forbid_key:
                    seen[forbid_key] = value
    return "；".join("%s=%s" % (key, value) for key, value in seen.items())


def build_glm_prompt(batch: Sequence[dict]) -> str:
    lines = [_rule_text(), ""]
    for item in batch:
        lines.append("### 第 %d 条" % item["index"])
        lines.append("边（必须原样成为 must/top1）：%s" % item["specs"])
        lines.append("`q` 里**一个都不能少**的键值（逐字照用，可再加别的键）：%s"
                     % required_q_hint(item))
        lines.append("卡片正文：%s" % str(item["card_text"])[:1200])
        if item["negatives"]:
            lines.append("候选负样本（挑最多 1 条，逐字复制）：")
            for spec in item["negatives"][:8]:
                lines.append("  - %s" % spec)
        else:
            lines.append("候选负样本：（无，`never` 写 []）")
        lines.append("")
    return "\n".join(lines)


def glm_pass(graph, universe: Sequence[str], client, *, vocab, batch_size: int = 8,
             limit: int = 0, partial_path=None, progress_path=None,
             resume: bool = True,
             only_values: Sequence[str] = (),
             only_cards: Sequence[str] = ()) -> Tuple[List[dict], List[dict], Dict]:
    """用 GLM 为候选池里的每条边写 `q` 与 `never`；`must`/`top1` 由池固定。

    为什么把 `must` 固定：这正是"候选池标注"的定义（TREC pooling）——标注方判断
    的是"这条查询该不该召回这条边"，而不是凭记忆把它拼出来。换族的证据落在
    `annotator.model_id/family`，产出侧再用**同一套**判据逐条拦。
    """
    from tools.check_holdout import parse_spec

    raw, stats = mechanical(graph, universe, vocab=vocab)
    by_card = {}
    for card in _corpus_cards():
        by_card[str(card.id)] = (card.title or "") + " " + (card.content or "")

    # 同一 `must` 组的原始条目是逐卡复制的，这里按 (must, top1) 去重成"待写 q 的组"。
    buckets: Dict[Tuple, dict] = collections.OrderedDict()
    for row in raw:
        key = (tuple(row["must"]), tuple(row["top1"]))
        item = buckets.setdefault(key, {"index": len(buckets) + 1, "specs": row["must"],
                                        "top1": row["top1"],
                                        "cards": [], "negatives": []})
        item["cards"].append(row["from_card"])
        if row["never"] and row["never"][0] not in item["negatives"]:
            item["negatives"].append(row["never"][0])
    items = list(buckets.values())
    for item in items:
        text = next((by_card[c] for c in item["cards"] if by_card.get(c)), "")
        item["card_text"] = text
        item["target"] = parse_spec(item["specs"][0])[0] if item["specs"] else ""
    if limit:
        items = items[:limit]
    if only_values:
        # **缺口补跑轮**：门③ 要求每个词表取值至少出现在 3 个 `(卡片,查询)` 对里。
        # 模型写 q 时可能漏掉某些槽位（或某批被拒），于是个别取值支撑不足。
        # 只把这些取值所在的组喂给模型重跑一轮，**标注族不变**（还是 zhipu）——
        # 不拿机械产物凑数，否则门⑧ 会看到 `rule` 族并如实判红。
        wanted = {str(v) for v in only_values}
        items = [item for item in items
                 if any(("=" + value) in required_q_hint(item) for value in wanted)]
    if only_cards:
        # **卡片缺口补跑轮**：门⑥ 要求每张入库卡至少派生一条。实测缺的 333 张里
        # 有 **118 张**属于"边在词表内、这张卡也是它的来源，却没发出条目"——
        # 成因是长跑里那几批 transport 失败（6 批 × 8 组 ≈ 48 组）。
        # 只把这些卡所在的组重跑一遍即可，索引与词表都不动（不会作废别的产物）。
        wanted_cards = {str(c) for c in only_cards}
        items = [item for item in items if wanted_cards & set(item["cards"])]

    #: **增量落盘**：原先只在整轮结束时写文件，实测一次 31 分钟的跑卡在一次 HTTP
    #: 调用上（CPU 60 秒增量为 0）就**一点产物都没有**——v2 那次也是。现在每批
    #: 结束就把已接受的条目**追加**进 partial，并写一行进度；重跑时按批次序号跳过
    #: 已经完成的批（`resume=True`）。这是"长跑必须可观测、可续跑"的下限。
    entries: List[dict] = []
    rejects: List[dict] = []
    done_batches: set = set()
    if resume and partial_path is not None:
        path = pathlib.Path(partial_path)
        if path.is_file():
            for line in path.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if "_batch" in row:
                    done_batches.add(int(row["_batch"]))
                    row = {k: v for k, v in row.items() if k != "_batch"}
                entries.append(row)
    total_batches = (len(items) + batch_size - 1) // batch_size
    for batch_index, start in enumerate(range(0, len(items), batch_size)):
        if batch_index in done_batches:
            continue
        batch = items[start:start + batch_size]
        try:
            reply = client.chat_json(GLM_SYSTEM, build_glm_prompt(batch),
                                     temperature=0.0, seed=0, num_ctx=8192)
        except Exception as exc:  # noqa: BLE001 - 单批失败不许打崩整轮
            rejects.append({"reason": "transport:%s" % type(exc).__name__,
                            "batch": start})
            _record_progress(progress_path, batch_index, total_batches, len(entries),
                             len(rejects))
            continue
        got = {int(item["index"]): item for item in reply.get("entries", [])
               if isinstance(item, dict) and str(item.get("index", "")).isdigit()}
        for item in batch:
            answer = got.get(item["index"])
            if not answer:
                rejects.append({"reason": "missing_index", "batch": start})
                continue
            never = [s for s in (answer.get("never") or [])
                     if str(s) in item["negatives"]]
            for card in item["cards"]:
                entries.append({"from_card": card, "q": str(answer.get("q") or ""),
                                "must": list(item["specs"]),
                                "top1": list(item["top1"]),
                                "never": never[:1]})
        if partial_path is not None:
            rows = entries[len(entries) - sum(len(item["cards"]) for item in batch):]
            with pathlib.Path(partial_path).open("a", encoding="utf-8", newline="\n") as fh:
                for row in rows:
                    fh.write(json.dumps({**row, "_batch": batch_index},
                                        ensure_ascii=False) + "\n")
        _record_progress(progress_path, batch_index, total_batches, len(entries),
                         len(rejects))
    return entries, rejects, {"groups": len(items), "stats": stats}


def _record_progress(path, batch_index: int, total: int, entries: int,
                     rejects: int) -> None:
    """写一行进度到 stdout 并把状态 JSON 落盘（长跑必须能看见它在动）。"""
    line = "batch %d/%d entries=%d rejects=%d" % (batch_index + 1, total, entries, rejects)
    print(line, flush=True)
    if path:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"batch": batch_index + 1, "total_batches": total,
                                      "entries": entries, "rejects": rejects},
                                     ensure_ascii=False, indent=2),
                          encoding="utf-8", newline="\n")


def _corpus_cards():
    from block_director.knowledge.corpus import CARDS
    return CARDS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_pool")
    parser.add_argument("--nodes", default=DEFAULT_NODES)
    parser.add_argument("--edges", default=DEFAULT_EDGES)
    parser.add_argument("--cards", default=DEFAULT_CARDS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--report", default="")
    parser.add_argument("--assertable-out", default="",
                        help="把**可断言对**（每类多少 `(卡片,查询)` 对，由索引＋词表决定、"
                             "与 oracle 生成了什么无关）写成 JSON，供 "
                             "`check_holdout --assertable` 判门④。建议随 oracle 一起入库："
                             "它是 `(索引, 词表)` 的属性，不随标注批次变动。")
    parser.add_argument("--vocab", default=DEFAULT_VOCAB,
                        help="冻结词表（门③ 的硬边界）；给空串表示不限制")
    parser.add_argument("--mechanical", action="store_true",
                        help="不调模型：把每条索引边写成一条期望")
    parser.add_argument("--provider", default="",
                        help="用模型写 q/never 的通道；目前支持 glm（智谱，换族）")
    parser.add_argument("--model", default=GLM_MODEL)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--partial", default="",
                        help="GLM 通道的**增量**落盘路径（长跑卡住时留下的产物）")
    parser.add_argument("--progress", default="",
                        help="逐批进度 JSON（配合 `--partial` 用；卡住时看这个文件就知道跑到哪）")
    parser.add_argument("--no-resume", action="store_true",
                        help="忽略已有 partial，从头跑")
    parser.add_argument("--only-values", default="",
                        help="缺口补跑：逗号分隔的取值（如 `smoke,crane_down`），"
                             "只把用到这些取值的组喂给模型。用来补门③ 的支撑数，"
                             "标注族不变（仍写真实模型族）。"
                             "**中文取值请用 `@文件` 传**：PowerShell 会把命令行里的中文"
                             "按本地码页转码，实测 `--only-values 压倒,揭示` 到 Python 手里"
                             "已经变了，过滤器一个都匹配不上（同一个坑在别处也踩过）。"
                             "`@路径` 表示读一个 UTF-8 文本文件，取值按行或逗号分隔。")
    parser.add_argument("--only-cards", default="",
                        help="卡片缺口补跑：`@文件`（每行一个卡片 id），"
                             "只把「这些卡是它来源」的组喂给模型。用来补门⑥ —— "
                             "实测缺的卡里有一类是「边在词表内、卡也是来源，却没发出条目」"
                             "（成因是长跑里几批 transport 失败）。同样支持 `@文件`。")
    parser.add_argument("--limit", type=int, default=0, help="只生成前 N 条（自检用）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    graph = load_graph(ROOT / args.nodes, ROOT / args.edges)
    universe = json.loads((ROOT / args.cards).read_text(encoding="utf-8"))
    vocab = {}
    if args.vocab:
        payload = json.loads((ROOT / args.vocab).read_text(encoding="utf-8"))
        vocab = payload.get("kinds", payload)
    if args.provider:
        from tools.kb_fetch import llm as _llm

        client = _llm.make_client(args.provider, args.model)
        spec = args.only_values
        if spec.startswith("@"):
            text = pathlib.Path(spec[1:]).read_text(encoding="utf-8")
        else:
            text = spec
        only_values = [v.strip() for v in text.replace("\n", ",").split(",") if v.strip()]
        card_spec = args.only_cards
        if card_spec.startswith("@"):
            card_text = pathlib.Path(card_spec[1:]).read_text(encoding="utf-8")
        else:
            card_text = card_spec
        only_cards = [c.strip() for c in card_text.replace("\n", ",").split(",") if c.strip()]
        raw, rejects, extra = glm_pass(graph, universe, client, vocab=vocab,
                                       batch_size=args.batch_size, limit=args.limit,
                                       partial_path=(args.partial or
                                                     str(ROOT / args.out) + ".partial"),
                                       progress_path=(args.progress or
                                                      str(ROOT / args.out) + ".progress.json"),
                                       resume=not args.no_resume,
                                       only_values=only_values, only_cards=only_cards)
        entries, more = finalise(raw, graph, universe,
                                 model_id=client.model_id, family=client.family,
                                 model_version=client.model_version,
                                 decode=str(getattr(client, "decode_tag", "")))
        rejects = list(rejects) + list(more)
        stats = extra["stats"]
        mode = "%s:%s" % (args.provider, args.model)
    else:
        raw, stats = mechanical(graph, universe, vocab=vocab)
        if args.limit:
            raw = raw[:args.limit]
        entries, rejects = finalise(raw, graph, universe,
                                    model_id="mechanical-pool", family="rule",
                                    model_version="pool/v1", decode="deterministic")
        mode = "mechanical"
    write_jsonl(ROOT / args.out, entries)
    report = {"mode": mode, "entries": len(entries),
              "rejects": len(rejects),
              "reject_reasons": dict(collections.Counter(
                  str(item["reason"]) for item in rejects)),
              "edges": len(graph.edges),
              "reject_examples": rejects[:5], **stats}
    if args.report:
        (ROOT / args.report).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / args.report).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.assertable_out:
        target = ROOT / args.assertable_out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"assertable_pairs_per_type":
                        stats.get("assertable_pairs_per_type", {})},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k != "reject_examples"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
