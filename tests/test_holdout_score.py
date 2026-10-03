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
import json
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
    # **2026-10-02：Q7 的分母按 §4.1 R52 换成"夹具覆盖门"的口径**——
    # 分母是 `MIN_FORBID_ITEMS`（§4.1b 的下界），**分子**才是
    # 「`q` 点名了索引里被禁取值」的条目数。所以这里断言分子。
    # 这条用例的原意不变：**只有与该边 forbid 成员冲突的查询才计入**。
    conflicting = _entry(module, edge, q="情绪=荒诞；运镜=固定")
    report = module.score_entries([conflicting], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    assert by_id["Q7"]["numerator"] == 1
    assert by_id["Q7"]["denominator"] == module.MIN_FORBID_ITEMS

    # 「情绪=荒诞；景别=中景」与该边的 forbid 无关 → 不进分子。
    unrelated = _entry(module, edge, q="情绪=荒诞；景别=中景")
    report = module.score_entries([unrelated], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    assert by_id["Q7"]["numerator"] == 0
    assert by_id["Q7"]["status"] == "fail"      # 冲突条目 0 < 下界，一律失败
    # 而且"每个 forbid 成员至少被 1 条 q 点名"这半也要报出来。
    assert by_id["Q7"]["uncovered_forbid_members"]


def test_negative_samples_are_counted_for_q3():
    module = _load()
    graph, edge, other = _graph(module)
    entry = _entry(module, edge)
    entry["never"] = [_norm(other)]
    report = module.score_entries([entry], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    assert by_id["Q3"]["denominator"] == 1
    assert by_id["Q3"]["status"] in ("pass", "fail")


def test_q4_is_not_a_tautology():
    """Q4 是**按 (query, edge) 对**聚合的，不是分子恒等于分母。

    规格 §4.1（line 831）写死：`Q4 = 命中的 required_hyperedge_ids 数 /
    Σ_q |required(q)|`。此前的实现是 `_metric("Q4", required_total,
    required_total, 1.0)` —— 分子分母同一个变量，等于把自己判成 100%，
    正是 §4.1b 硬规则 2 要堵的"自证"。

    构造：一条 `must` 里有两张边，查询只够得着其中一张 → Q4 必须 < 1 且判 fail。
    """
    module = _load()
    graph, edge, other = _graph(module)
    entry = _entry(module, edge, q="情绪=荒诞")
    entry["must"] = [_norm(edge), _norm(other)]
    entry["top1"] = [_norm(edge)]
    report = module.score_entries([entry], graph)
    by_id = {item["id"]: item for item in report["metrics"]}
    # 分子只能是 1（`other` 是 SHOT_PATTERN，查询里没有任何景别种子）
    assert by_id["Q4"]["denominator"] == 2
    assert by_id["Q4"]["numerator"] == 1
    assert by_id["Q4"]["value"] == 0.5
    assert by_id["Q4"]["status"] == "fail"
    assert report["passed"] is False


def test_a_must_spec_that_maps_to_no_index_edge_is_reported_and_fails():
    """§2.3 的 Q6b 前置①：required 边在索引里不存在 ⇒ **索引构建失败**。

    此前 `if key is not None` 会把它**静默丢掉**，于是分母凭空变小、
    Q1/Q2/Q4/Q6b 一起被抬高——这正是硬规则 1（分母下界）与硬规则 2（禁自证）
    联手要堵的洞。
    """
    module = _load()
    from block_director.knowledge.hypergraph import Node

    graph, edge, _other = _graph(module)
    # 让 lens / headroom_policy 两个 kind 在词表里存在，但**没有**任何边同时带
    # (MS, 50mm, board) —— 于是这条 `must` 解析不出索引边。
    graph.nodes["lens:50mm"] = Node("lens:50mm", "lens", "50mm")
    entry = _entry(module, edge, q="情绪=荒诞")
    entry["must"] = ["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board"]
    entry["top1"] = entry["must"]
    report = module.score_entries([entry], graph)
    assert report["must_total"] == 1
    assert report["required_unresolved"] == 1
    assert report["required_unresolved_entries"] == 1
    assert report["unresolved_examples"][0]["id"] == "h1"
    by_id = {item["id"]: item for item in report["metrics"]}
    # required 分母随之归零 → Q4 按硬规则 1 判 fail（不是"没有 required 所以免测"）
    assert by_id["Q4"]["denominator"] == 0
    assert by_id["Q4"]["status"] == "fail"
    assert report["passed"] is False


def test_all_resolvable_musts_leave_the_report_clean():
    """负对照：每条 `must` 都解析得上时，`required_unresolved` 必须为 0。"""
    module = _load()
    graph, edge, _other = _graph(module)
    report = module.score_entries([_entry(module, edge)], graph)
    assert report["must_total"] == 1
    assert report["required_unresolved"] == 0
    assert report["unresolved_examples"] == []


def test_the_shipped_holdout_is_scored_or_explicitly_incomplete(capsys):
    """正式 held-out 的两种状态都必须**明说**：

    * 还没产出/为空 → 明说 `INCOMPLETE` 并且**退出码非 0**（可判定的天条）；
    * 已产出 → 必须给出 Q1–Q7 的**分子/分母**，不再是 INCOMPLETE。

    v1.5 起 held-out 已经落地（4539 条），所以这条从"只查 INCOMPLETE"升级成
    "两种状态都不许含糊"——空文件仍然必须报 INCOMPLETE，这一点不能因为有了数据就丢掉。
    """
    module = _load()
    shipped = ROOT / "fixtures" / "knowledge_holdout.jsonl"
    rows = [line for line in shipped.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if shipped.is_file() else []

    code = module.main(["prog", "--holdout", str(shipped)])
    out = capsys.readouterr().out
    if not rows:
        assert code != 0 and "INCOMPLETE" in out
        return
    report = json.loads(out[out.find("{"):])
    assert code in (0, 1)
    ids = {m["id"]: m for m in report["metrics"]}
    for name in ("Q1", "Q2", "Q3", "Q4", "Q6a", "Q6b", "Q7"):
        assert name in ids and "denominator" in ids[name]
        assert ids[name]["denominator"] > 0, f"{name} 的分母必须为正（硬规则 1）"


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


def test_the_ab_triple_report_is_written_and_carries_both_arms(tmp_path):
    """`ab_triple.json` 是 P14-5 的**交付物**，不是"跑不跑都行"的脚本。

    2026-10-03 实测：工具一直在库里，而**链上从来没调用过它** ⇒ 任何
    `docs/evidence/<run-id>/` 里都不存在这份账，"超图到底买到了什么"没人能复核。
    所以链上现在跑它并**要求产物落盘**（数字不设通过线——工具的抬头写明：收益只在
    注入预算不足时体现，Δ≈0 不说明超图无用）。

    这条用例拿**入库索引 ＋ 一条 held-out**离线跑一遍，检查两臂、两指标与差值都在。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bd_ab_main", ROOT / "tools" / "ab_triple_baseline.py")
    ab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ab)

    first = json.loads((ROOT / "fixtures" / "knowledge_holdout.jsonl")
                       .read_text(encoding="utf-8").splitlines()[0])
    holdout = tmp_path / "holdout.jsonl"
    holdout.write_text(json.dumps(first, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    out = tmp_path / "ab_triple.json"
    assert ab.main(["prog", "--holdout", str(holdout), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["queries"] == 1
    assert set(payload["Q2"]) == {"hypergraph", "triples"}
    assert set(payload["Q6b"]) == {"hypergraph", "triples"}
    assert payload["edges"]["hypergraph"] > 0
    assert payload["edges"]["triples"] >= payload["edges"]["hypergraph"]
    # 差值可以任何值（含 None：某一臂没算出来时**不许**伪造 0），键必须在。
    assert "delta_Q2" in payload and "delta_Q6b" in payload
    assert "不设通过线" in payload["note"]


def test_the_chain_runs_the_ab_triple_and_requires_the_artifact():
    """链上必须调用它、并且**要求产物存在**——否则交付物会重演"悄悄消失"。"""
    text = (ROOT / "tools" / "run_tests.ps1").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()
             and not line.lstrip().startswith("#")]
    calls = [line for line in lines if "ab_triple_baseline.py" in line]
    assert calls, "链上没有调用 tools/ab_triple_baseline.py"
    assert any("ab_triple.json" in line for line in calls), calls
    assert any("Test-Path" in line and "ab_triple.json" in line for line in lines), (
        "链上必须检查 ab_triple.json 真的写出来了")


def test_the_chain_produces_the_human_edge_spotcheck_sheet():
    """§6 的"抽取噪声"一行把取证写成 `edge_spotcheck.jsonl`（人填 verdict）。

    2026-10-03 实测：只有 **2026-09-30 的三个**证据目录里有它——此后的每一跑都缺
    这一份具名交付物，而链子全绿。链**不能**替人填 verdict（那是人审），但必须
    **产出这张表**；`sample_edges.py` 本身拒绝预填（`verdict` 恒为 `null`，
    预填就是 §4.1b 硬规则 2 说的自证）。
    """
    text = (ROOT / "tools" / "run_tests.ps1").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()
             and not line.lstrip().startswith("#")]
    calls = [line for line in lines if "sample_edges.py" in line]
    assert calls, "链上没有调用 tools/knowledge/sample_edges.py"
    assert any("edge_spotcheck.jsonl" in line for line in calls), calls
    assert any("Test-Path" in line and "edge_spotcheck.jsonl" in line
               for line in lines), "链上必须检查那张表真的写出来了"
