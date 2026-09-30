"""held-out 词表口径（`tools/knowledge/holdout_vocab.py`）的对抗性用例。

旧口径是"卡片正文里出现过、按频次取前 12 名"（`HOLDOUT_CAP = 12`）。它有两个
可验证的坏后果：任何一次语料/索引重建都会重排词表（实测漂移样本
`pan_right`／`impact_frame`／`关系轴` 让旧 oracle 整批变成 `unknown_values`），
而且 12 是个与"语料到底支不支持这个取值"无关的魔数。

新口径：进词表的取值必须**能凑出 ≥ `--min-seed-support` 个不同的
`(卡片, 查询)` 对** —— 与门③ 用 `check_holdout.support_from` 判 `thin` 的口径
逐字相同。三条不变量在这里钉住。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_holdout as CH  # noqa: E402
from tools import holdout_pool as HP  # noqa: E402
from tools.holdout_score import load_graph  # noqa: E402
from tools.knowledge import holdout_vocab as HV  # noqa: E402

NODES = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
EDGES = ROOT / "knowledge" / "hypergraph.edges.jsonl"
CARDS = ROOT / "fixtures" / "knowledge_holdout.cards.json"
VOCAB = ROOT / "fixtures" / "knowledge_holdout.vocab.json"


@pytest.fixture(scope="module")
def graph():
    if not (NODES.is_file() and EDGES.is_file()):
        pytest.skip("索引未入库")
    return load_graph(NODES, EDGES)


def test_every_required_kind_is_present_even_when_empty(graph):
    """`character`／`object` 没有查询键，但键**必须存在**。

    键缺席时门③ 判"缺 kind → 那个 kind 免检"并**直接失败**（不是 not_measured），
    所以空表也得写出来。这是上一版实现踩过的坑：词表里少了两个键，整道门红。
    """
    universe = json.loads(CARDS.read_text(encoding="utf-8"))
    payload, _report = HV.build_vocab(graph, universe=universe)
    missing = sorted(set(CH.REQUIRED_VOCAB_KINDS) - set(payload))
    assert missing == [], f"词表缺 kind 会让门③ 直接判失败：{missing}"
    assert payload["character"] == [] and payload["object"] == []


def test_frozen_vocab_survives_the_gate_it_feeds(graph):
    """**核心不变量**：用这份词表生成的条目必须过门③（没有 thin / unknown）。"""
    universe = json.loads(CARDS.read_text(encoding="utf-8"))
    payload, _report = HV.fixpoint(graph, universe)
    # **不要把空表过滤掉**：门③ 把"缺 kind"判成失败（该 kind 从此免检），
    # `character`／`object` 必须带着空表一起传进去。
    vocab = dict(payload)
    rows, _stats = HP.mechanical(graph, universe, vocab=payload)
    entries, rejects = HP.finalise(rows, graph, universe, model_id="t", family="rule",
                                   model_version="t")
    assert rejects == []
    status, detail = CH.gate_seed_coverage(
        [CH.parse_q(entry["q"]) for entry in entries], vocab,
        CH.must_values_from(entries), True, HV.MIN_SUPPORT_EDGES,
        CH.support_from(entries))
    assert status == "pass", detail
    assert detail["missing_values"] == {} and detail["unknown_values"] == {}
    assert detail["thin_values"] == {}


def test_long_tail_values_are_dropped_with_a_reason(graph):
    """只被 1–2 条边表达的取值**必须被剔除**，并且报告里指出是"尾巴"。"""
    universe = json.loads(CARDS.read_text(encoding="utf-8"))
    _payload, report = HV.build_vocab(graph, universe=universe)
    assert report["dropped_values"] > 0, "语料有长尾，剔除数不可能为 0"
    assert report["dropped_long_tail"], "剔除必须按 kind 记账"
    # 剔除的是"支撑不足"，不是"随便砍"：每个被剔的值都 < min_support
    support = HV.edge_support(graph)
    for kind, values in HV.build_vocab(graph, universe=universe)[0].items():
        for value in values:
            assert support.get((kind, value), 0) >= HV.MIN_SUPPORT_EDGES


def test_fixpoint_removes_values_that_cannot_reach_the_support_line(graph):
    """词表既约束生成、又是门③ 的分母，所以必须**迭代到不动点**。

    实测卡住的样本：一个 `sfx` 取值出现在 3 条边里，但这 3 条边同属一张源卡、
    查询串也相同 —— 只有 1 个 `(卡片, 查询)` 对。剔掉它之后生成才可能过门③。
    """
    universe = json.loads(CARDS.read_text(encoding="utf-8"))
    payload, report = HV.fixpoint(graph, universe)
    rows, stats = HP.mechanical(graph, universe, vocab=payload)
    assert stats["under_supported_values"] == [], (
        "不动点之后不该还有支撑不足的取值")
    assert report.get("fixpoint_converged", True) is not False
    assert report["fixpoint_rounds"] >= 1
    assert rows


def test_shipped_vocab_matches_the_fixpoint(graph):
    """入库的那份词表必须等于当前索引算出的不动点（防止手改漂移）。"""
    if not VOCAB.is_file():
        pytest.skip("词表未入库")
    universe = json.loads(CARDS.read_text(encoding="utf-8"))
    payload, _report = HV.fixpoint(graph, universe)
    shipped = json.loads(VOCAB.read_text(encoding="utf-8"))
    assert shipped["kinds"] == payload
    assert shipped["_fingerprint"] == HV.fingerprint(payload)
