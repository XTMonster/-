"""**禁忌必须真的进注入**（§4.1 的 Q7 = 100%）——2026-10-03 修的那条真缺陷。

病状（实测，长剧本真实运行 `926a717a2861`）：64 次逐镜检索的
`retrieval_call.forbid_members` **全为 0** —— 三栏里的"硬约束（含禁忌）"那一栏，
**禁忌部分从来没进过模型**。两处结构原因各修一条：

1. **候选**：只靠禁忌值挂上种子的边 `coverage` 恒为 0（`_edge_coverage` 故意不算
   `forbid`），在"按节点的枢纽额度"和"全局 40 条额度"里都排最后被整批丢掉 ⇒
   它们连打分都进不去。修法 = 两层额度各让出保底名额（`reserve_forbid`）。
2. **注入**：进了候选也未必进 top-k —— 实测那 5 条冲突边 0.21 分，而 top-5 的
   `INTENT_PACK` 0.59 分。修法 = **名额**而非权重：`_promote_forbid_conflicts`
   用分数最高的冲突边顶掉分数最低的非冲突边，且**绝不顶掉另一条冲突边**。

配套的判据重定义（§2.3 / R26 ⑦ 的原话："原定义会把『该召回的**禁忌边**』判成
误命中"）：`never` 与"查询点名了它被禁取值"撞车时，那条边不计 Q3 误命中——但要
**如实报出跳过了多少对**（`negative_skipped_forbid_conflicts`）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    HUB_EDGES_PER_NODE,
    HyperEdge,
    Hypergraph,
    Node,
    parse_query_full,
)


def _edge(members, *, edge_type="EMOTION_PACK", occurrences=1, confidence=0.7):
    return HyperEdge.from_dict({
        "type": edge_type,
        "members": [list(item) for item in members],
        "source_kind": "theory", "hardness": "hard",
        "occurrences": occurrences, "confidence": confidence,
        "confidence_max": confidence,
    })


def _node(node_id, name=None):
    kind, _, value = node_id.partition(":")
    return Node(node_id, kind, name or value, value=value)


def _scene():
    """一图两面：高 coverage 的"正常"边 ＋ 只靠禁忌挂种子的冲突边。"""
    #: 全部用 `EMOTION_PACK` 造（必填位 emotion+intensity，[`/`_scene`] 里都写全）
    #: —— 换成 `AXIS_RULE` 之类会缺 `pair`/`axis_side`，`entry_key` 解析不到
    #: （实测踩过：spec 解析成 None，Q3 用例的 `never` 直接空掉）。
    nodes = [_node("movement:固定", "固定"),
             _node("shot_size:MS"), _node("shot_size:CU"),
             _node("intensity:high"),
             _node("emotion:荒诞"), _node("emotion:平静"),
             _node("emotion:压抑"), _node("emotion:狂喜")]
    #: 正常边：把 query 点名的取值覆盖掉（coverage 高）。
    normal = _edge([("allow", "shot_size", "shot_size:MS"),
                    ("allow", "movement", "movement:固定"),
                    ("qualifier", "intensity", "intensity:high")],
                   edge_type="EMOTION_PACK")   # ← 类型只是标签；成员表决定解析
    normal2 = _edge([("allow", "emotion", "emotion:狂喜"),
                     ("qualifier", "intensity", "intensity:high")],
                    edge_type="EMOTION_PACK", occurrences=4, confidence=0.9)
    #: 冲突边：唯一与 query 相关的地方是它**禁止** `运镜=固定`。
    conflict = _edge([("allow", "emotion", "emotion:压抑"),
                      ("qualifier", "intensity", "intensity:high"),
                      ("forbid", "movement", "movement:固定")],
                     edge_type="EMOTION_PACK")
    #: 另一条冲突边（用来验"不许顶掉另一条冲突边"）：禁止 `景别=MS`。
    conflict2 = _edge([("allow", "emotion", "emotion:平静"),
                       ("qualifier", "intensity", "intensity:high"),
                       ("forbid", "shot_size", "shot_size:MS")],
                      edge_type="EMOTION_PACK")
    return Hypergraph(nodes, [normal, normal2, conflict, conflict2]), \
        normal, conflict, conflict2


QUERY = "景别=MS；运镜=固定"


def test_a_query_that_names_a_forbidden_value_gets_it_injected():
    graph, normal, conflict, _conflict2 = _scene()
    edges, text, trace = graph.retrieve(QUERY, top_k=2, token_limit=10 ** 6)
    ids = [edge.edge_id for edge in edges]
    assert conflict.edge_id in ids, (
        "查询点名了 `运镜=固定`，而这条边把它标成禁忌——它必须进注入（Q7 = 100%）")
    assert trace.forbid_promoted, "顶替必须记进 trace（注入了什么要可审计）"
    assert trace.forbid_promoted[0]["added"] == conflict.edge_id
    assert trace.forbid_promoted[0]["kind"] == "movement"
    assert trace.forbid_promoted[0]["value"] == "固定"
    assert "禁" in text, "注入文本里必须真的出现禁忌那一栏"


def test_promotion_never_displaces_another_conflict_edge():
    """全是冲突边时**不许**互相顶替——那会把禁忌稀释成一条。"""
    graph, _normal, conflict, conflict2 = _scene()
    #: top_k=2 且两条正常边，冲突边只有一条能进；再取更小的 top_k 让两条冲突边都进去。
    edges, _text, trace = graph.retrieve("景别=MS；运镜=固定", top_k=4,
                                         token_limit=10 ** 6)
    ids = [edge.edge_id for edge in edges]
    assert conflict.edge_id in ids and conflict2.edge_id in ids
    for event in trace.forbid_promoted:
        assert event["removed"] not in (conflict.edge_id, conflict2.edge_id), (
            "顶替不能落在另一条冲突边上：" + json.dumps(event, ensure_ascii=False))


def test_the_candidate_reservation_survives_the_hub_trim():
    """枢纽节点的按节点额度不许把"只靠禁忌挂种子"的边整批丢光。

    复现现场：`movement:固定` 是枢纽（66 条邻边），额度只留
    `HUB_EDGES_PER_NODE` 条，而冲突边 coverage=0 排最后——**只修全局额度是不够的**
    （实测：5 条冲突边全部倒在按节点那一层）。
    """
    nodes = [_node("movement:固定", "固定"), _node("shot_size:MS")]
    fillers = [
        _edge([("allow", "shot_size", "shot_size:MS"),
               ("qualifier", "intensity", "intensity:high")],
              edge_type="SHOT_PATTERN", occurrences=index + 1)
        for index in range(HUB_EDGES_PER_NODE * 3)
    ]
    nodes.append(_node("intensity:high"))
    conflict = _edge([("qualifier", "intensity", "intensity:high"),
                      ("forbid", "movement", "movement:固定")],
                     edge_type="AXIS_RULE")
    graph = Hypergraph(nodes, fillers + [conflict])
    query, forbid = parse_query_full(QUERY)
    seeds = graph.seeds_for(query)
    candidates, truncated = graph.expand(seeds, query=query, forbid_query=forbid)
    ids = {edge.edge_id for edge in candidates}
    assert truncated, "这条用例要的就是「额度不够」的场景"
    assert conflict.edge_id in ids, (
        "冲突边必须靠禁忌保底穿过按节点的枢纽额度")


def test_q3_exempts_forbid_conflicts_and_reports_how_many():
    """§2.3 的 Q3 重定义：`never` 与禁忌冲突撞车时不计误命中，但要报数。"""
    from tools.holdout_score import score_entries

    graph, normal, conflict, _conflict2 = _scene()
    entries = [{
        "id": "hq_1", "from_card": "card_1", "q": QUERY,
        #: `must`/`top1` 指向**正常**边（可解析），`never` 指向**冲突**边。
        "must": [normal.type + ":emotion=荒诞,intensity=high,movement=固定"],
        "top1": [], "never": [
            conflict.type + ":emotion=压抑,intensity=high,forbid_movement=固定"],
        "expect_movements": [],
    }]
    report = score_entries(entries, graph, top_k=2, token_limit=10 ** 6)
    q3 = [item for item in report["metrics"] if item["id"] == "Q3"][0]
    assert q3["numerator"] == 0, (
        "被禁取值正是查询点名的取值 ⇒ 这条边该被召回，不算 Q3 误命中")
    assert report["negative_skipped_forbid_conflicts"] >= 1, (
        "跳过多少对必须如实报出来（不许静默缩分母）")
    assert "跳过" in q3["note"]
