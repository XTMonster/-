"""`tools/knowledge/holdout_ceiling.py`：把"排序还能改进多少"与"这条线根本不可达"
分开的算术必须可信。

为什么要钉住它：`holdout_score` 报出的 Q1≈0.14 看起来像检索排序不行，于是自然会去
调权重；但如果**上限**（神谕排序器）本身低于验收线，调排序永远到不了线——那条
require 的边在索引里根本不存在（§2.3 的 Q6b 前置①把它定义为"索引构建失败"）。
这个文件保证上限探针不会把"不存在"错算成"已达标"，也不会在分母为 0 时谎报。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node  # noqa: E402
from tools.knowledge import holdout_ceiling  # noqa: E402


def _graph() -> Hypergraph:
    nodes = [
        Node("emotion:荒诞", "emotion", "荒诞"),
        Node("intensity:high", "intensity", "high"),
        Node("lighting:逆光", "lighting", "逆光"),
        Node("transition:cut", "transition", "cut"),
        Node("pacing:short", "pacing", "short"),
        Node("scene_type:insert", "scene_type", "insert"),
    ]
    edges = [
        HyperEdge.from_dict({
            "type": "EMOTION_PACK",
            "members": [["allow", "emotion", "emotion:荒诞"],
                        ["qualifier", "intensity", "intensity:high"]],
            "source_kind": "theory", "hardness": "hard",
        }),
        HyperEdge.from_dict({
            "type": "LIGHT_PACK",
            "members": [["allow", "lighting", "lighting:逆光"],
                        ["qualifier", "intensity", "intensity:high"]],
            "source_kind": "theory", "hardness": "hard",
        }),
        # 与「情绪=荒诞」的种子**完全没有交集**（两跳也扩不到）——用来把
        # "边存在但召不回"与"边根本不存在"分开。
        HyperEdge.from_dict({
            "type": "TRANSITION_PACK",
            "members": [["qualifier", "transition", "transition:cut"],
                        ["allow", "pacing", "pacing:short"],
                        ["qualifier", "scene_type", "scene_type:insert"]],
            "source_kind": "theory", "hardness": "hard",
        }),
    ]
    return Hypergraph(nodes, edges)


def _entry(idx: int, q: str, must: list, top1: list | None = None) -> dict:
    return {"id": f"hq_{idx:04d}", "from_card": f"card_{idx}", "q": q,
            "must": must, "top1": top1 if top1 is not None else list(must),
            "never": [], "annotator": {"model_id": "x", "family": "y",
                                       "model_version": "1"}}


SPEC = "EMOTION_PACK:emotion=荒诞,intensity=high"


def test_ceiling_counts_only_required_edges_that_exist_and_are_reachable():
    graph = _graph()
    entries = [
        _entry(1, "情绪=荒诞", [SPEC]),
        # 这条 required 边在索引里不存在（SOUND_PACK 一条都没有）→ 上限必须被拉低。
        _entry(2, "情绪=荒诞", ["SOUND_PACK:sfx=雨声,pacing=short,intensity=high"]),
    ]
    report = holdout_ceiling.measure(graph, entries)
    assert report["queries"] == 2
    assert report["must_total"] == 2
    assert report["must_resolvable"] == 1
    assert report["ceilings"] == {"Q1": 0.5, "Q2": 0.5, "Q4": 0.5, "Q6b": 0.5}
    assert report["ceilings_below_lines"] == ["Q1", "Q2", "Q4", "Q6b"]
    per_type = report["must_per_type"]
    assert per_type["EMOTION_PACK"] == {"demanded": 1, "resolvable": 1,
                                        "in_candidates": 1, "absent": 0}
    assert per_type["SOUND_PACK"]["absent"] == 1


def test_a_fully_isomorphic_oracle_has_no_ceiling_below_the_lines():
    graph = _graph()
    report = holdout_ceiling.measure(graph, [_entry(1, "情绪=荒诞", [SPEC])])
    assert report["ceilings"] == {"Q1": 1.0, "Q2": 1.0, "Q4": 1.0, "Q6b": 1.0}
    assert report["ceilings_below_lines"] == []


def test_a_resolvable_edge_that_never_enters_the_candidate_set_caps_q1_and_q2():
    """一条边能解析、但查询的种子根本扩不到它 → Q1/Q2 上限被卡住（而 Q4 不受影响）。"""
    graph = _graph()
    isolated = "TRANSITION_PACK:transition=cut,pacing=short,scene_type=insert"
    # q 只写「情绪=荒诞」——TRANSITION_PACK 与它的两跳闭包没有交集。
    report = holdout_ceiling.measure(
        graph, [_entry(1, "情绪=荒诞", [isolated])])
    assert report["must_resolvable"] == 1          # 索引里有这条边
    assert report["ceilings"]["Q4"] == 1.0         # 边存在
    assert report["ceilings"]["Q1"] == 0.0         # 但进不了候选集
    assert report["ceilings"]["Q2"] == 0.0
    assert "Q2" in report["ceilings_below_lines"]
    assert "Q4" not in report["ceilings_below_lines"]


def test_empty_oracle_is_incomplete_and_never_a_pass(tmp_path, capsys):
    """空集：上限全为 0、退出码非 0，**不得**当成"还没判"或通过（硬规则 1）。"""
    empty = tmp_path / "holdout.jsonl"
    empty.write_text("", encoding="utf-8")
    code = holdout_ceiling.main(["prog", "--holdout", str(empty)])
    out = json.loads(capsys.readouterr().out)
    assert code == 2
    assert "INCOMPLETE" in out
    assert out["ceilings_below_lines"] == ["Q1", "Q2", "Q4", "Q6b"]


def test_missing_holdout_is_a_clean_error(tmp_path, capsys):
    assert holdout_ceiling.main(["prog", "--holdout", str(tmp_path / "nope.jsonl")]) == 2
    assert "不存在" in capsys.readouterr().out


@pytest.mark.parametrize("line_name,line", sorted(holdout_ceiling.LINES.items()))
def test_lines_match_the_spec_table(line_name, line):
    """上限探针自带一份验收线——它必须与 §2.3 的质量表一致，不能自行放宽。"""
    assert line in (0.70, 0.90, 1.0)
    assert line_name in ("Q1", "Q2", "Q4", "Q6b")
