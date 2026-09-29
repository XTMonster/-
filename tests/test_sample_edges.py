"""§6 取证工具 `tools/knowledge/sample_edges.py` 的抽样与留白纪律（离线）。"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    HyperEdge,
    Member,
    Node,
)
from tools.knowledge import sample_edges  # noqa: E402


def _nodes():
    return {
        "n:emo:absurd": Node("n:emo:absurd", "emotion", "荒诞", value="荒诞"),
        "n:int:high": Node("n:int:high", "intensity", "high", value="high"),
        "n:mv:whip": Node("n:mv:whip", "movement", "甩镜", aliases=("whip_pan",)),
        "n:ss:MS": Node("n:ss:MS", "shot_size", "MS", value="MS"),
        "n:lens:85": Node("n:lens:85", "lens", "85mm", value="85mm"),
        "n:hr:board": Node("n:hr:board", "headroom_policy", "board", value="board"),
        "n:pair:any": Node("n:pair:any", "pair", "any_two", value="any_two"),
        "n:axis:left": Node("n:axis:left", "axis_side", "left", value="left"),
        "n:gen:film": Node("n:gen:film", "genre", "film", value="film"),
        "n:pac:short": Node("n:pac:short", "pacing", "short", value="short"),
        "n:avl:1-3": Node("n:avl:1-3", "avg_shot_len", "1-3s", value="1-3s"),
        "n:lit:warm": Node("n:lit:warm", "lighting", "暖光", value="warm"),
    }


def _edges():
    m = Member
    return [
        HyperEdge("EMOTION_PACK", (m("allow", "emotion", "n:emo:absurd"),
                                   m("qualifier", "intensity", "n:int:high"),
                                   m("allow", "movement", "n:mv:whip"),
                                   m("forbid", "shot_size", "n:ss:MS"))),
        HyperEdge("EMOTION_PACK", (m("allow", "emotion", "n:emo:absurd"),
                                   m("qualifier", "intensity", "n:int:high"))),
        HyperEdge("EMOTION_PACK", (m("allow", "emotion", "n:emo:absurd"),
                                   m("qualifier", "intensity", "n:int:high"),
                                   m("allow", "shot_size", "n:ss:MS"))),
        HyperEdge("SHOT_PATTERN", (m("allow", "shot_size", "n:ss:MS"),
                                   m("allow", "lens", "n:lens:85"),
                                   m("qualifier", "headroom_policy", "n:hr:board"))),
        HyperEdge("AXIS_RULE", (m("qualifier", "pair", "n:pair:any"),
                                m("qualifier", "axis_side", "n:axis:left"))),
        HyperEdge("TROPE", (m("allow", "genre", "n:gen:film"),
                            m("allow", "emotion", "n:emo:absurd"))),
        HyperEdge("EDIT_RHYTHM", (m("allow", "pacing", "n:pac:short"),
                                  m("qualifier", "avg_shot_len", "n:avl:1-3"))),
        HyperEdge("LIGHT_PACK", (m("allow", "lighting", "n:lit:warm"),
                                 m("qualifier", "intensity", "n:int:high"))),
    ]


def test_stratified_sample_covers_every_type_present():
    edges = _edges()
    picked = sample_edges.stratified_sample(edges, 6)
    assert len(picked) == 6
    types = {e.type for e in picked}
    # 六类各有一条时，抽 6 条必须六类都覆盖到（纯随机抽样会漏）
    assert types == {"EMOTION_PACK", "SHOT_PATTERN", "AXIS_RULE",
                     "TROPE", "EDIT_RHYTHM", "LIGHT_PACK"}


def test_sample_is_deterministic_without_seed_and_stable_with_seed():
    edges = _edges()
    first = [e.edge_id for e in sample_edges.stratified_sample(edges, 8)]
    second = [e.edge_id for e in sample_edges.stratified_sample(edges, 8)]
    assert first == second
    import random
    a = [e.edge_id for e in sample_edges.stratified_sample(edges, 8, random.Random(7))]
    b = [e.edge_id for e in sample_edges.stratified_sample(edges, 8, random.Random(7))]
    assert a == b
    assert sorted(a) == sorted(first)  # 换了顺序，集合不变


def test_sample_never_exceeds_the_index():
    picked = sample_edges.stratified_sample(_edges(), 99)
    assert len(picked) == len(_edges())


def test_spotcheck_row_keeps_forbid_and_leaves_the_verdict_blank():
    nodes = _nodes()
    edge = _edges()[0]
    row = sample_edges.spotcheck_row(edge, nodes)
    # 禁忌成员不得被抽样过滤掉
    assert row["forbid_members"] == ["n:ss:MS"]
    assert "forbid" in {m["role"] for m in row["members"]}
    # 裁决三列**必须留白**（预填 "ok" 就是自证）
    assert row["verdict"] is None
    assert row["reviewer"] == ""
    assert row["notes"] == ""
    assert row["edge_id"].startswith("hg:")
    assert row["rendered"]
    assert row["tokens"] <= 400  # §2.3 校验门⑧：单条渲染 ≤ 400 token


def test_write_and_reload_round_trips(tmp_path):
    rows = [sample_edges.spotcheck_row(e, _nodes()) for e in _edges()[:3]]
    out = sample_edges.write_spotcheck(rows, tmp_path / "nested" / "edge_spotcheck.jsonl")
    text = out.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["edge_id"] for line in text] == [r["edge_id"] for r in rows]


def test_main_writes_into_the_evidence_dir(tmp_path, capsys):
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    nodes_path.write_text(
        "".join(json.dumps(n.to_dict(), ensure_ascii=False) + "\n"
                for n in _nodes().values()), encoding="utf-8")
    edges_path.write_text(
        "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n"
                for e in _edges()), encoding="utf-8")
    out = tmp_path / "ev" / "edge_spotcheck.jsonl"
    code = sample_edges.main(["--n", "4", "--nodes", str(nodes_path),
                              "--edges", str(edges_path), "--out", str(out)])
    assert code == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["sampled"] == 4
    assert summary["unreviewed"] == 4
    assert out.is_file()


def test_main_refuses_a_bad_n(tmp_path, capsys):
    code = sample_edges.main(["--n", "0",
                              "--nodes", str(tmp_path / "x"), "--edges", str(tmp_path / "y")])
    assert code == 2
    assert "error" in capsys.readouterr().out


def test_main_fails_loudly_when_the_index_is_missing(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        sample_edges.load_index(tmp_path / "missing.nodes.jsonl",
                                tmp_path / "missing.edges.jsonl")
