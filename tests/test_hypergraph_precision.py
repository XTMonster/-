"""§2.3 第 2 段的**精确度门**：禁令必须有宿主（离线、确定性、不联网）。

被钉住的对象是 `build_hypergraph.unsupported_prohibition_hosts`。它存在的理由是
提示规则 4b（"卡里出现 *避免/不要* 时把那个取值写成 `forbid`"）给了个**旧宿主**
`EMOTION_PACK`：一张只讲运镜的卡被逼着补出 `emotion`／`intensity` 才能凑满必填槽位。
真实事故（`docs/knowledge/GATE6_LAST_CARD.md`）：

```
gen_cine_0247「摄影机始终处于某种运动中，避免长时间静止固定」
  → EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定
```

卡里没有"平静"，双模型复核（DeepSeek ＋ GLM）两次判它 rejected。门⑥ 因此卡在
"28 张卡零条目 → 1 张"，而**那 1 张不是标注缺口，是抽取缺陷**。

这里同时钉住"这一刀不许过宽"：全局落地判据会判掉 538/540 条边（抽取器本来就在抽象），
所以四条条件缺一不可。最后一条用例直接把**线上那两条边**放进流水线，防止半年后
有人把条件放宽回去。
"""

from __future__ import annotations

import json
import pathlib
import inspect
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import grounding  # noqa: E402
from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.kb_fetch import build_hypergraph as bh  # noqa: E402
from tools.holdout_score import load_graph  # noqa: E402


def _node(node_id: str, name: str, aliases=()) -> hg.Node:
    kind, _, value = node_id.partition(":")
    return hg.Node(node_id=node_id, type=kind, name=name, aliases=tuple(aliases),
                   value=value)


def _nodes(*extra: hg.Node) -> dict:
    base = [
        #: 别名照**入库的**词表（`tools/kb_fetch/vocabulary.py::EMOTIONS`）。
        #: `安静` 是 2026-10-02 实测补进来的一个——漏了它，下面第二条边会被误判
        #: （见 `test_the_same_prohibition_is_dropped_when_the_synonym_is_missing`）。
        _node("emotion:平静", "平静", ("安宁", "留白", "安静")),
        _node("emotion:混乱", "混乱"),
        _node("intensity:low", "low", ("低",)),
        _node("movement:固定", "固定", ("静止", "固定机位")),
        _node("movement:handheld", "handheld", ("手持",)),
        _node("pacing:long", "long"),
        _node("avg_shot_len:>8s", ">8s"),
    ]
    table = {node.node_id: node for node in base}
    for node in extra:
        table[node.node_id] = node
    return table


def _card(card_id: str, content: str, tags=()) -> dict:
    return {"id": card_id, "domain": "cinematography", "title": card_id,
            "content": content, "keywords": [], "tags": list(tags)}


def _edge(card_id: str, members, edge_type: str = "EMOTION_PACK") -> hg.HyperEdge:
    return hg.HyperEdge(
        type=edge_type,
        members=tuple(hg.Member(role=r, kind=k, node_id=n) for r, k, n in members),
        source_kind="theory", hardness="hard", sources=(card_id,),
        source_span={"chunk_id": f"chunk_{card_id}", "start": 0, "end": 10},
        provenance_kind="生成卡片")


#: 线上那两条边（逐字取自 `knowledge/hypergraph.edges.jsonl` 的修复前状态）。
MANUFACTURED = [
    ("gen_cine_0247", "摄影机始终处于某种运动中——位移、摇移或改变焦距，避免长时间静止固定，"
                      "以保持画面的流动感。",
     [("allow", "emotion", "emotion:平静"), ("qualifier", "intensity", "intensity:low"),
      ("forbid", "movement", "movement:固定")]),
    ("cine_move_handheld", "相机由人扛着，带高频微抖与不稳定构图。它把「有人在现场」这件事"
                           "直接写进画面，因此纪实、混乱、紧张都用它。"
                           "禁忌：安静的对话用手持，会让观众误以为有危险在逼近。",
     [("allow", "emotion", "emotion:平静"), ("qualifier", "intensity", "intensity:low"),
      ("forbid", "movement", "movement:handheld")]),
]


def _run(*rows, nodes=None):
    edges = [_edge(card_id, members) for card_id, _text, members in rows]
    cards = {card_id: _card(card_id, text) for card_id, text, _ in rows}
    return bh.unsupported_prohibition_hosts(edges, cards, nodes or _nodes())


def test_the_fabricated_host_is_dropped_with_its_evidence():
    """`gen_cine_0247`：卡只讲运镜，边却断言"平静／低强度" ⇒ 主体是编的，拒收。

    报告里必须写清**主体是哪个**（`emotion:平静`）与**禁半是哪个**（`movement:固定`）。
    """
    card_id, text, members = MANUFACTURED[0]
    kept, report = _run((card_id, text, members))
    assert kept == []
    assert report["dropped"] == 1
    assert report["rule"] == "unsupported_prohibition_host"
    by_card = {row["sources"][0]: row for row in report["edges"]}
    assert by_card["gen_cine_0247"]["invented_subject"] == ["emotion:平静"]
    assert by_card["gen_cine_0247"]["grounded_forbid"] == ["movement:固定"]


def test_the_handheld_prohibition_is_kept_because_the_synonym_is_in_the_vocabulary():
    """`cine_move_handheld`：卡写"**安静的**对话用手持"是禁忌，边写 `forbid_movement=handheld`
    ——意思对得上，`安静` 又是 `emotion:平静` 的别名 ⇒ 主体落地，**必须放行**。

    这条是"规则不许过宽"的实证：这一刀只该砍向编出来的主体，不该砍向**同义词**。
    """
    card_id, text, members = MANUFACTURED[1]
    kept, report = _run((card_id, text, members))
    assert len(kept) == 1 and report["dropped"] == 0


def test_the_same_prohibition_is_dropped_when_the_synonym_is_missing():
    """别名表少一个同义词，这条**正确的**禁令就会被判成"主体是编的"。

    这不是假设：2026-10-02 实测时 `emotion:平静` 的别名只有 `安宁/留白`，
    规则因此把 `cine_move_handheld` 那条正确禁令也拒了（索引实删 2 条、
    `forbid` 成员 8 → 6）。补上 `安静` 之后实删 1 条、`forbid` 成员 8 → 7。
    这条用例把那次发现钉住：**别名表是落地判据的输入**，改它要跟着重跑索引。
    """
    card_id, text, members = MANUFACTURED[1]
    nodes = _nodes()
    nodes["emotion:平静"] = _node("emotion:平静", "平静", ("安宁", "留白"))
    kept, report = _run((card_id, text, members), nodes=nodes)
    assert kept == []
    assert report["dropped"] == 1


def test_a_grounded_subject_keeps_the_edge():
    """条件③的反面：主体在卡里 ⇒ 放行。`cine_move_handheld` 的第二条边就是这样。"""
    cards = {"c": _card("c", "纪实、混乱、紧张都用手持。禁忌：安静的对话用手持会让观众误判。")}
    edges = [_edge("c", [("allow", "emotion", "emotion:混乱"),
                         ("qualifier", "intensity", "intensity:low"),
                         ("forbid", "movement", "movement:handheld")])]
    kept, report = bh.unsupported_prohibition_hosts(edges, cards, _nodes())
    assert len(kept) == 1 and report["dropped"] == 0


def test_without_a_grounded_forbid_the_edge_is_left_alone():
    """条件②的反面：禁半在卡里找不到字面 ⇒ 这不是"禁令的宿主"，不归这条规则管。

    抽取器会做抽象（`intensity=low`、`beat_type=coverage` 这类推断永远没有字面），
    全局落地判据会判掉 538/540 条边——所以这条规则只在"确有落地禁令"时才开火。
    """
    cards = {"c": _card("c", "一句话里既没有情绪也没有被禁的取值，只有一段抽象描述。")}
    edges = [_edge("c", [("allow", "emotion", "emotion:平静"),
                         ("qualifier", "intensity", "intensity:low"),
                         ("forbid", "movement", "movement:固定")])]
    kept, report = bh.unsupported_prohibition_hosts(edges, cards, _nodes())
    assert len(kept) == 1 and report["dropped"] == 0


def test_without_a_negation_cue_the_edge_is_left_alone():
    """条件①的反面：卡里没有"不要/避免/切忌…"⇒ 这条 `forbid` 的理据不在卡里，
    那是规则 8d（抽取期）该管的事，不由精确度门重复裁决。"""
    cards = {"c": _card("c", "画面保持静止固定，使用平静的浅景深。")}
    edges = [_edge("c", [("allow", "emotion", "emotion:平静"),
                         ("qualifier", "intensity", "intensity:low"),
                         ("forbid", "movement", "movement:固定")])]
    kept, report = bh.unsupported_prohibition_hosts(edges, cards, _nodes())
    assert len(kept) == 1 and report["dropped"] == 0


def test_an_edge_with_no_forbid_at_all_is_never_touched():
    cards = {"c": _card("c", "避免过曝。")}
    edges = [_edge("c", [("allow", "emotion", "emotion:平静"),
                         ("qualifier", "intensity", "intensity:low")])]
    kept, report = bh.unsupported_prohibition_hosts(edges, cards, _nodes())
    assert len(kept) == 1 and report["dropped"] == 0


def test_an_unknown_source_card_is_not_judged():
    """出处引用了不存在的卡 ⇒ 那是另一个缺陷（门⑥ 的幽灵条目），不在这里判。"""
    edges = [_edge("ghost", [("allow", "emotion", "emotion:平静"),
                             ("qualifier", "intensity", "intensity:low"),
                             ("forbid", "movement", "movement:固定")])]
    kept, report = bh.unsupported_prohibition_hosts(edges, {}, _nodes())
    assert len(kept) == 1 and report["dropped"] == 0


def test_any_cited_card_may_supply_the_subject():
    """出处是**全部被引卡**的并集：另一张卡撑住了主体 ⇒ 不拒收（出处不能因为只看一张而丢）。"""
    cards = {"a": _card("a", "避免长时间静止固定。"),
             "b": _card("b", "平静的段落用低强度。")}
    edge = bh.dataclasses.replace(
        _edge("a", [("allow", "emotion", "emotion:平静"),
                    ("qualifier", "intensity", "intensity:low"),
                    ("forbid", "movement", "movement:固定")]),
        sources=("a", "b"))
    kept, report = bh.unsupported_prohibition_hosts([edge], cards, _nodes())
    assert len(kept) == 1 and report["dropped"] == 0


def test_the_rule_is_deterministic():
    edges = [_edge(card_id, members) for card_id, _t, members in MANUFACTURED]
    cards = {card_id: _card(card_id, text) for card_id, text, _ in MANUFACTURED}
    runs = [bh.unsupported_prohibition_hosts(edges, cards, _nodes()) for _ in range(3)]
    payloads = {json.dumps(report, ensure_ascii=False, sort_keys=True) for _, report in runs}
    assert len(payloads) == 1


def test_the_shipped_index_carries_the_ledger_and_is_consistent():
    """入库索引必须留下这门开过火的账，且 `valid_unique` 与文件行数对得上。"""
    manifest = json.loads(
        (ROOT / "knowledge" / "hypergraph.manifest.json").read_text(encoding="utf-8"))
    merge = manifest["merge"]
    ledger = merge["unsupported_prohibition_hosts"]
    assert ledger["rule_version"] == bh.VALIDATION_RULES_VERSION
    assert manifest["validation_rules_version"] == bh.VALIDATION_RULES_VERSION
    edges = [json.loads(line) for line in
             (ROOT / "knowledge" / "hypergraph.edges.jsonl")
             .read_text(encoding="utf-8").splitlines() if line.strip()]
    assert manifest["valid_unique"] == len(edges)
    #: 这里原先是 `assert ledger["dropped"] == 1` —— **当时的索引**的实测值
    #: （v12：540 条边里只有 `gen_cine_0247` 那一条编出来的宿主边）。v14 把 `forbid`
    #: 从 8 个成员扩到 68 个之后，同形状的边自然不止一条，那个魔数就成了"索引一变
    #: 就红"的噪音。换成**结构不变量**＋**具名个案的现状**：
    assert ledger["dropped"] == len(ledger["edges"]) >= 1
    #: 每条账目都要写清"主体是哪个、禁半是哪个"（不能只记一个 id）。
    for row in ledger["edges"]:
        assert row["invented_subject"] and row["grounded_forbid"] and row["type"]
    #: 具名个案换了形态：v14 的规则 4b 不再逼模型"挂到 EMOTION_PACK 上"，
    #: 于是那条**编出来的边在抽取期就没有了**（不是被这一刀砍掉的）。
    #: 这才是根因修复；精确度门留给别处同形状的边（这一轮另有 7 条）。
    assert not [edge for edge in edges
                if "gen_cine_0247" in (edge.get("sources") or [])], (
        "`gen_cine_0247` 只讲运镜、一个字没提情绪，它的边只能是编的")
    #: 被拒收的边**不允许**还留在索引里（这条规则的唯一目的就是它们不在）。
    alive = {edge["edge_id"] for edge in edges}
    assert not (alive & {row["edge_id"] for row in ledger["edges"]})
    #: 账目自洽：`raw = valid_unique + duplicates + rejects`（§2.3 的构建门）。
    assert manifest["raw_edges"] == (manifest["valid_unique"] + manifest["duplicates"]
                                    + manifest["rejects"])


def test_grounding_is_the_single_source_for_the_cues():
    """门⑤ 与阶段二必须读**同一份**否定词表（否则同一条边在两处得到两个答案）。"""
    from tools import holdout_pool

    assert holdout_pool.NEGATION_CUES is grounding.NEGATION_CUES


def test_the_vocabulary_carries_the_synonym_that_the_rule_depends_on():
    """`安静` → `emotion:平静` 必须在**入库的**节点表里，否则上面那条放行会失效。"""
    nodes = {}
    for line in (ROOT / "knowledge" / "hypergraph.nodes.jsonl").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            node = json.loads(line)
            nodes[node["node_id"]] = node
    assert "安静" in nodes["emotion:平静"]["aliases"]


# ---------------------------------------------------------------- 自相矛盾的边

def _edge_of(etype, members):
    return hg.HyperEdge(type=etype, source_kind="theory", hardness="hard",
                        members=tuple(hg.Member(*item) for item in members),
                        sources=("c1",))


def test_an_edge_may_not_require_and_forbid_the_same_value():
    """`axis_topic=越轴 ＋ forbid_axis_topic=越轴`：同一个 node_id 两处出现 ⇒ 拒收。

    v14 的规则 4b 让抽取器把卡里的"避免 X"写成 `forbid`，而 `AXIS_RULE` 的
    `axis_topic` 是**必填**槽位，于是这类边真的出现了。它们在 oracle 语法里
    表达不出来（`parse_spec` 当场拒收），留在索引里等于"有一条边谁都标注不了"——
    实测 `tools/holdout_pool.py` 的 GLM 通道正是在这种边上**整轮崩掉**。
    """
    edge = _edge_of("AXIS_RULE", [("qualifier", "pair", "pair:双人"),
                                  ("qualifier", "axis_side", "axis_side:左"),
                                  ("qualifier", "axis_topic", "axis_topic:越轴"),
                                  ("forbid", "axis_topic", "axis_topic:越轴")])
    kept, report = bh.contradictory_roles([edge])
    assert kept == []
    assert report["dropped"] == 1
    assert report["edges"][0]["clash"] == ["axis_topic=越轴"]


def test_requiring_one_value_and_forbidding_another_is_legal():
    """正对照：同 kind **不同取值**不是矛盾（要 crane_up、禁 dolly_out）。"""
    edge = _edge_of("EMOTION_PACK", [("allow", "emotion", "emotion:荒诞"),
                                     ("qualifier", "intensity", "intensity:mid"),
                                     ("allow", "movement", "movement:crane_up"),
                                     ("forbid", "movement", "movement:dolly_out")])
    kept, report = bh.contradictory_roles([edge])
    assert len(kept) == 1 and report["dropped"] == 0


def test_the_shipped_index_has_no_contradictory_edge():
    """入库索引里一条自相矛盾的边都不许有（判据与 oracle 侧同源）。"""
    kept, report = bh.contradictory_roles(
        load_graph(ROOT / "knowledge/hypergraph.nodes.jsonl",
                   ROOT / "knowledge/hypergraph.edges.jsonl").edges)
    assert report["dropped"] == 0, report["edges"][:3]
    assert kept


def test_the_pool_skips_an_unusable_group_instead_of_dying():
    """`holdout_pool` 的 GLM 通道遇到读不了目标类型的组要**跳过并留痕**，不许崩。"""
    from tools import holdout_pool

    assert hasattr(holdout_pool, "glm_pass")
    source = inspect.getsource(holdout_pool.glm_pass)
    assert "unusable" in source, "坏组必须被跳过并记账，而不是让整轮抛异常"
    assert "unusable_groups" in source
