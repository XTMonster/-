"""v1.4 §2.3 / RK-13 的**打分器**本身必须可信。

held-out 正式集还没产出（需要换族模型跑满 1200 条 + 人抽查），但打分器的
算术与三条 §4.1b 硬规则现在就能用合成数据钉住：

* 分母为 0 → **fail**（不是 not_measured，更不能算通过）；
* Q6b 必须读**真正会注入的文本**——把某条边的成员从注入里拿掉，它必须红；
* Q6a 不是同义反复：成员被改过、或 id 公式漂了，它必须红；
* Q7 只在"查询值与该边的 forbid 成员同类同值"时计入分母。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "bd_holdout_score", ROOT / "tools" / "holdout_score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _graph(module):
    from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node

    nodes = [
        Node("emotion:荒诞", "emotion", "荒诞", ("absurd",)),
        Node("movement:whip_pan_right", "movement", "甩镜", ("whip_pan",)),
        Node("movement:static", "movement", "固定机位", ("固定", "static")),
        Node("shot_size:MS", "shot_size", "中景", ("MS",)),
        Node("intensity:high", "intensity", "high"),
    ]
    edge = HyperEdge.from_dict({
        "type": "EMOTION_PACK",
        "members": [["allow", "emotion", "emotion:荒诞"],
                    ["allow", "movement", "movement:whip_pan_right"],
                    ["qualifier", "intensity", "intensity:high"],
                    ["forbid", "movement", "movement:static"]],
        "source_kind": "theory", "hardness": "hard",
    })
    other = HyperEdge.from_dict({
        "type": "SHOT_PATTERN",
        "members": [["allow", "shot_size", "shot_size:MS"],
                    ["qualifier", "headroom_policy", "headroom_policy:board"]],
        "source_kind": "theory", "hardness": "hard",
    })
    nodes.append(Node("headroom_policy:board", "headroom_policy", "board"))
    return Hypergraph(nodes, [edge, other]), edge, other


def _norm(edge):
    return [edge.type, [[m.role, m.kind, m.node_id] for m in edge.members]]


def _entry(module, edge, *, q: str = "情绪=荒诞；运镜=固定") -> dict:
    return {"id": "h1", "from_card": "c1", "q": q,
            "must": [_norm(edge)], "top1": [_norm(edge)], "never": [],
            "expect_movements": [], "annotator": {"model_id": "x"} }


def test_empty_holdout_cannot_pass():
    module = _load()
    graph, _edge, _other = _graph(module)
    report = module.score_entries([], graph)
    assert report["passed"] is False
    assert all(item["status"] == "fail" for item in report["metrics"])


def test_a_perfect_entry_passes_the_arithmetic_but_not_the_lower_bounds():
    module = _load()
    graph, edge, _other = _graph(module)
    report = module.score_entries([_entry(module, edge)], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    # 算术上是 100%/100%，但 query 数远低于 1200 的下界 → Q1/Q2/Q4 判失败。
    assert by_id["Q6a"]["value"] == 1.0
    assert by_id["Q1"]["status"] == "fail"
    assert "下界" in by_id["Q1"]["note"]
    assert report["passed"] is False


def test_q6b_fails_when_a_member_is_missing_from_the_injected_text():
    """把 forbid 成员从注入文本里拿掉 → Q6b 必须红（不是恒真）。"""
    module = _load()
    graph, edge, _other = _graph(module)
    entry = _entry(module, edge)

    captured: dict = {}
    real_render = module.render_edges

    def stripped(edges, nodes, limit):
        text, dropped, fail = real_render(edges, nodes, limit)
        captured["text"] = text
        return text.replace("固定机位", ""), dropped, fail

    module.render_edges = stripped
    try:
        report = module.score_entries([entry], graph)
    finally:
        module.render_edges = real_render
    by_id = {item["id"]: item for item in report["metrics"]}
    assert "固定机位" in captured["text"]      # 原始注入里确实有它
    assert by_id["Q6b"]["numerator"] == 0
    assert by_id["Q6b"]["status"] == "fail"


def test_q7_only_counts_queries_that_conflict_with_a_forbid_member():
    module = _load()
    graph, edge, _other = _graph(module)
    # 「运镜=固定」正是该边 forbid 的成员 → 计入分母。
    conflicting = _entry(module, edge, q="情绪=荒诞；运镜=固定")
    report = module.score_entries([conflicting], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    assert by_id["Q7"]["denominator"] == 1

    # 「情绪=荒诞；景别=中景」与该边的 forbid 无关 → 不进分母。
    unrelated = _entry(module, edge, q="情绪=荒诞；景别=中景")
    report = module.score_entries([unrelated], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    assert by_id["Q7"]["denominator"] == 0
    assert by_id["Q7"]["status"] == "fail"      # 分母 0 一律失败


def test_negative_samples_are_counted_for_q3():
    module = _load()
    graph, edge, other = _graph(module)
    entry = _entry(module, edge)
    entry["never"] = [_norm(other)]
    report = module.score_entries([entry], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    assert by_id["Q3"]["denominator"] == 1
    assert by_id["Q3"]["status"] in ("pass", "fail")


def test_the_shipped_holdout_is_reported_as_incomplete(capsys):
    """正式 held-out 还没产出时，脚本必须**明说无法判定**而不是判通过。"""
    module = _load()
    code = module.main(["prog", "--holdout", "fixtures/knowledge_holdout.jsonl"])
    out = capsys.readouterr().out
    if code == 0:
        pytest.skip("held-out 已经产出，这条 INSTALL 检查不适用")
    assert "INCOMPLETE" in out


def test_triple_split_keeps_members_but_loses_the_pack():
    """A/B 的拆分器必须**保留成员**（否则对照没有意义）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bd_ab", ROOT / "tools" / "ab_triple_baseline.py")
    ab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ab)

    module = _load()
    graph, edge, other = _graph(module)
    triples = ab.split_into_triples(graph)
    # 拆分后边的条数只会更多（一条 4 元边 → 至少 2 条二元边）。
    assert len(triples.edges) > len(graph.edges)
    # 每个成员都在某条三元组里出现过 —— 拆分不丢信息，只是把它打散。
    seen = {(m.role, m.kind, m.node_id) for item in triples.edges
            for m in item.members}
    for member in list(edge.members) + list(other.members):
        assert (member.role, member.kind, member.node_id) in seen
