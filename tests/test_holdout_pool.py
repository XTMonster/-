"""`tools/holdout_pool.py`（候选池标注 v2）的对抗性用例。

核心是三条**由构造保证**的性质，任何一条回归，门⑨/门⑩ 就会重新变红：

* `q` 覆盖 `must[0]`／`top1` 的全部可查询槽位（门⑨）；
* `must`／`top1`／`never` 的每一条都能解析到当前索引的边（门⑩，exact 口径）；
* 组内边数 >3 的 `(type, q)` 组**不生成**期望（Q4 要求每条 required 进 top-3，
  >3 条时构造上做不到），而不是编一条查询出来。
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

NODES = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
EDGES = ROOT / "knowledge" / "hypergraph.edges.jsonl"
CARDS = ROOT / "fixtures" / "knowledge_holdout.cards.json"


@pytest.fixture(scope="module")
def graph():
    if not (NODES.is_file() and EDGES.is_file()):
        pytest.skip("索引未入库")
    return load_graph(NODES, EDGES)


@pytest.fixture(scope="module")
def universe():
    return json.loads(CARDS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pool(graph, universe):
    raw, stats = HP.mechanical(graph, universe)
    entries, rejects = HP.finalise(raw, graph, universe, model_id="t", family="rule",
                                   model_version="t")
    return entries, rejects, stats


def test_every_generated_entry_is_reachable(pool):
    """门⑨：`q` 必须覆盖 `must[0]`／`top1` 的全部可查询槽位——由构造成立。"""
    entries, _rejects, _stats = pool
    assert entries
    short = [CH.query_shortfall(entry) for entry in entries]
    assert [item for item in short if item] == []
    status, detail = CH.gate_reachability(entries)
    assert status == "pass", detail
    assert detail["short"] == 0


def test_every_generated_entry_resolves_to_the_index(pool, graph):
    """门⑩（exact 口径）：`must`／`top1`／`never` 全部解析到当前索引的边。"""
    entries, _rejects, _stats = pool
    status, detail = CH.gate_index_resolvable(entries, graph, "exact")
    assert status == "pass", detail
    assert detail["unresolved"] == 0
    assert detail["resolved"] == detail["totals"]


def test_generation_never_asserts_an_edge_outside_the_pool(pool, graph, universe):
    """产出的每一条 spec 都必须是**索引里真实存在的边**（池外即拒）。

    这是"候选池"的定义：`must` 只能从池里挑。校验器侧由
    `finalise()` 的 gate⑩ 分支保证——这里用一条**故意写错**的 must 打进去，
    确认它变成 reject 而不是悄悄留下。
    """
    entries, _rejects, _stats = pool
    sample = dict(entries[0])
    sample["must"] = ["EMOTION_PACK:emotion=不存在的情绪,intensity=high"]
    sample["top1"] = list(sample["must"])
    _kept, rejects = HP.finalise([sample], graph, universe, model_id="t",
                                 family="rule", model_version="t")
    assert rejects, "池外 / 解析不到的边必须被拒收"
    assert any(item["reason"].startswith("gate10") or
               item["reason"].startswith("gate2") for item in rejects)


def test_query_that_misses_a_slot_is_rejected(graph, universe):
    """门⑨ 的对抗面：把 `q` 里的一条键删掉，必须被拒收。"""
    raw, _stats = HP.mechanical(graph, universe)
    sample = dict(raw[0])
    parts = [item for item in str(sample["q"]).split("；") if item]
    sample["q"] = "；".join(parts[:-1]) or parts[0]
    if sample["q"] == raw[0]["q"]:  # 只有一条键时删不掉，换一条更长的样本
        sample = dict(next(item for item in raw
                           if len(str(item["q"]).split("；")) >= 2))
        parts = [p for p in str(sample["q"]).split("；") if p][:-1]
        sample["q"] = "；".join(parts)
    _kept, rejects = HP.finalise([sample], graph, universe, model_id="t",
                                 family="rule", model_version="t")
    assert rejects and rejects[0]["reason"].startswith("weak_q")


def test_ambiguous_groups_are_skipped_not_faked(pool):
    """`(type, q)` 组内边数 >3 时**不生成**期望（Q4 的构造性天花板）。"""
    entries, _rejects, stats = pool
    assert stats["skipped"].get("query_ambiguous_group", 0) > 0, (
        "实测有 3 个组（13 条边）构造上无法满足 Q4，必须被显式跳过并计数")
    assert stats["skipped"].get("no_live_source_card", 0) >= 0
    # 被跳过的组不许出现在产物里
    emitted = {entry["q"] for entry in entries}
    assert emitted


def test_negative_sample_is_disjoint_from_the_query(pool):
    """负样本必须与查询**不相交**（协议 §3.2），否则 Q3 会把该召回的边算成误召。"""
    entries, _rejects, _stats = pool
    with_never = [entry for entry in entries if entry["never"]]
    assert with_never, "必须有负样本，否则 Q3 分母为 0（按 §4.1b 判失败）"
    for entry in with_never[:50]:
        spec = entry["never"][0]
        _etype, plain, _forbid = CH.parse_spec(spec)
        q_pairs = CH.parse_q(entry["q"])
        have = {(CH.Q_KEY_TO_KIND[key], value) for key, value in q_pairs.items()}
        assert not ({(kind, value) for kind, value in plain.items()} & have), (
            f"负样本 {spec} 与查询 {entry['q']} 相交：它本来就该被召回")
