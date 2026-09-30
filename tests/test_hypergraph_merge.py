"""§2.3 第 2 段「跨卡归并」的对抗性用例（离线、确定性、不联网）。

规格（`改进执行文档v1.4.md` §2.3 第 2 步）写死了三件事，这里逐条钉住：

* 归并窗口 = **同一 domain ＋ 一跳 `related` 闭包**，**每次最多 8 张卡**；
* 归并的输出仍是**完整的超边**：`allow` 与 `forbid` 一起带出来
  （旗舰例子"荒诞 pack"在现实语料里分散在多张卡，单卡抽不出 arity≥2 的完整包）；
* 归并必须**串行且确定**（同一输入两次结果逐字节一致），否则六元指纹缓存失效。

另外钉住一条 §2.3b 的红线：归并**不得凭空造出 `forbid`**——输出里的禁忌成员
必须是 stage-1 输入里已经存在的（E3「经验越权率 = 0」的机制侧保证）。
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.kb_fetch import build_hypergraph as bh  # noqa: E402


def _node(node_id: str, kind: str, name: str, value: str = "") -> hg.Node:
    return hg.Node(node_id=node_id, type=kind, name=name, aliases=(), value=value)


def _nodes(*extra: hg.Node) -> dict:
    base = [
        _node("emotion:荒诞", "emotion", "荒诞", "荒诞"),
        _node("intensity:high", "intensity", "high", "high"),
        _node("movement:固定机位", "movement", "固定机位"),
        _node("movement:甩镜", "movement", "甩镜"),
        _node("movement:推轨", "movement", "推轨"),
        _node("shot_size:MS", "shot_size", "MS", "MS"),
        _node("shot_size:CU", "shot_size", "CU", "CU"),
        _node("lens:85mm", "lens", "85mm", "85mm"),
        _node("headroom_policy:board", "headroom_policy", "board", "board"),
        _node("emotion:压抑", "emotion", "压抑", "压抑"),
        _node("vfx:impact_frame", "vfx", "impact_frame", "impact_frame"),
        _node("sfx:夸张", "sfx", "夸张"),
        _node("pacing:short", "pacing", "short", "short"),
        _node("applies_to_genre:film", "applies_to_genre", "film", "film"),
    ]
    table = {node.node_id: node for node in base}
    for node in extra:
        table[node.node_id] = node
    return table


def _card(card_id: str, domain: str = "cinematography", related=(), start: int = 0) -> dict:
    return {"id": card_id, "domain": domain, "title": card_id, "content": "x",
            "related": list(related), "provenance_kind": "生成卡片",
            "source_span": {"chunk_id": f"chunk_{card_id}", "start": start, "end": start + 10}}


def _edge(card_id: str, members, edge_type: str = "EMOTION_PACK",
          source_kind: str = "theory", hardness: str = "hard",
          start: int = 0) -> hg.HyperEdge:
    return hg.HyperEdge(
        type=edge_type,
        members=tuple(hg.Member(role=r, kind=k, node_id=n) for r, k, n in members),
        source_kind=source_kind, hardness=hardness,
        sources=(card_id,),
        source_span={"chunk_id": f"chunk_{card_id}", "start": start, "end": start + 10},
        provenance_kind="生成卡片",
    )


def _minimal(card_id: str) -> hg.HyperEdge:
    return _edge(card_id, [("allow", "emotion", "emotion:荒诞"),
                           ("qualifier", "intensity", "intensity:high")])


# --------------------------------------------------------------------------- 归并


def test_merge_unions_the_members_of_one_coupling_across_cards():
    """旗舰例子：荒诞 pack 分散在两张卡上，归并后必须是一条**完整**的 n 元边。"""
    cards = {"a": _card("a"), "b": _card("b")}
    edges = [
        _minimal("a"),
        _edge("b", [("allow", "emotion", "emotion:荒诞"),
                    ("qualifier", "intensity", "intensity:high"),
                    ("allow", "movement", "movement:甩镜")]),
        _edge("b", [("allow", "emotion", "emotion:荒诞"),
                    ("qualifier", "intensity", "intensity:high"),
                    ("forbid", "movement", "movement:固定机位")]),
    ]
    merged, report = bh.merge_edges(edges, cards, _nodes())

    assert len(merged) == 1, "同一耦合的三条原子边必须并成一条"
    edge = merged[0]
    ids = {(m.role, m.kind, m.node_id) for m in edge.members}
    assert ("allow", "movement", "movement:甩镜") in ids
    assert ("forbid", "movement", "movement:固定机位") in ids
    assert len(edge.members) >= 4, "归并后的 arity 必须大于任何单卡原子边"
    assert edge.sources == ("a", "b")
    assert edge.occurrences == 3
    assert report["forbid_members"] == 1
    assert report["max_arity"] >= 4
    hg.validate_edge(edge, _nodes())


def test_merge_never_crosses_two_different_required_signatures():
    cards = {"a": _card("a"), "b": _card("b")}
    edges = [
        _minimal("a"),
        _edge("b", [("allow", "emotion", "emotion:压抑"),
                    ("qualifier", "intensity", "intensity:high")]),
    ]
    merged, _report = bh.merge_edges(edges, cards, _nodes())
    assert len(merged) == 2, "不同情绪包不得被并成一条（否则张冠李戴）"


def test_forbid_wins_when_the_same_node_is_both_allowed_and_forbidden():
    cards = {"a": _card("a"), "b": _card("b")}
    edges = [
        _edge("a", [("allow", "emotion", "emotion:荒诞"),
                    ("qualifier", "intensity", "intensity:high"),
                    ("allow", "movement", "movement:固定机位")]),
        _edge("b", [("allow", "emotion", "emotion:荒诞"),
                    ("qualifier", "intensity", "intensity:high"),
                    ("forbid", "movement", "movement:固定机位")]),
    ]
    merged, report = bh.merge_edges(edges, cards, _nodes())
    assert len(merged) == 1
    edge = merged[0]
    # 门⑤：同一个 node_id 不得同时出现在 allow 与 forbid
    hg.validate_edge(edge, _nodes())
    assert ("allow", "movement", "movement:固定机位") not in {(m.role, m.kind, m.node_id)
                                                              for m in edge.members}
    assert report["forbid_wins"] == 1


def test_merge_never_invents_a_forbid_member():
    """E3 的机制侧保证：输出的禁忌 ⊆ 输入的禁忌。"""
    cards = {"a": _card("a"), "b": _card("b")}
    edges = [
        _minimal("a"),
        _edge("b", [("allow", "emotion", "emotion:荒诞"),
                    ("qualifier", "intensity", "intensity:high"),
                    ("forbid", "shot_size", "shot_size:CU")]),
    ]
    merged, _report = bh.merge_edges(edges, cards, _nodes())
    produced = {m.node_id for edge in merged for m in edge.forbids}
    upstream = {m.node_id for edge in edges for m in edge.forbids}
    assert produced <= upstream
    assert produced == {"shot_size:CU"}


# --------------------------------------------------------------------------- 窗口


def test_window_is_capped_at_eight_cards_and_pulls_in_the_related_closure():
    cards = {f"c{i}": _card(f"c{i}") for i in range(12)}
    cards["c0"]["related"] = ["c11"]
    windows = bh.merge_windows(list(cards.values()), window_size=8)
    assert windows, "至少要有一个窗口"
    assert all(len(window) <= 8 for window in windows)
    every_card = [card_id for window in windows for card_id in window]
    assert sorted(every_card) == sorted(cards), "每张卡恰好进一个窗口"
    assert any("c0" in window and "c11" in window for window in windows), \
        "一跳 related 闭包内的卡必须进同一个窗口"


def test_windows_never_mix_two_domains():
    cards = [_card(f"a{i}", domain="cinematography") for i in range(3)]
    cards += [_card(f"b{i}", domain="editing") for i in range(3)]
    windows = bh.merge_windows(cards, window_size=8)
    by_id = {card["id"]: card["domain"] for card in cards}
    for window in windows:
        assert len({by_id[card_id] for card_id in window}) == 1


def test_merge_is_deterministic_and_order_independent():
    cards = {f"c{i}": _card(f"c{i}") for i in range(4)}
    edges = [_minimal("c0"),
             _edge("c1", [("allow", "emotion", "emotion:荒诞"),
                          ("qualifier", "intensity", "intensity:high"),
                          ("allow", "movement", "movement:甩镜")]),
             _edge("c2", [("allow", "emotion", "emotion:荒诞"),
                          ("qualifier", "intensity", "intensity:high"),
                          ("forbid", "movement", "movement:固定机位")])]
    first, rep1 = bh.merge_edges(edges, cards, _nodes())
    second, rep2 = bh.merge_edges(list(reversed(edges)), cards, _nodes())
    dump = lambda out: json.dumps([e.to_dict() for e in out], ensure_ascii=False, sort_keys=True)
    assert dump(first) == dump(second), "输入顺序不得影响归并结果"
    assert rep1 == rep2


# --------------------------------------------------------------------------- 预算


def test_merge_splits_alternatives_instead_of_breaking_the_render_budget():
    """门⑧（渲染 ≤ 400 token）＋ 本轮修掉的"同 kind 多值"死角。

    契约变更说明：旧行为把同一个槽位上的多个取值**塞进同一条边**、塞不下的丢掉，
    于是产出 `TYPE:…,sfx=甲,sfx=乙,sfx=丙` 这种**同 kind 多值**的边。它在 oracle 的
    规格语法里根本写不出来（`tools/check_holdout.parse_spec` 用 dict 收同 kind，
    后一个值覆盖前一个），实测索引里 31 条这样的边 = 门⑩ 的结构性未解析。
    新契约：每个槽位取一个取值，**其余备选各自复制一条边**（备选是"两种做法"，
    不是"同时成立"）。因此下面断言的是**更强**的性质，而不是放宽：

    * 每条边仍 ≤ 渲染预算（门⑧ 原样）；
    * 6 个 `sfx` 取值**一个都不许丢**（旧行为会丢掉 5 个）；
    * 每条边里每个 kind 只出现一次（同 kind 多值 = 语法死角，测试 `test_check_holdout
      ::test_every_index_edge_can_be_written_as_a_spec` 会整库扫这一条）。
    """
    fat = [_node(f"sfx:长{i}", "sfx", "啰" * 120) for i in range(6)]
    nodes = _nodes(*fat)
    cards = {f"c{i}": _card(f"c{i}") for i in range(6)}
    edges = []
    for index in range(6):
        edges.append(_edge(f"c{index}",
                           [("allow", "emotion", "emotion:荒诞"),
                            ("qualifier", "intensity", "intensity:high"),
                            ("allow", "sfx", f"sfx:长{index}")]))
    merged, report = bh.merge_edges(edges, cards, nodes)
    assert merged, "至少得产出一条边"
    for edge in merged:
        hg.validate_edge(edge, nodes)
        assert hg.render_tokens(hg.render_edge(edge, nodes)) <= hg.MAX_RENDER_TOKENS
        plain_kinds = [m.kind for m in edge.members if m.role != "forbid"]
        assert len(plain_kinds) == len(set(plain_kinds)), (
            f"同 kind 多值会让门⑩ 结构性未解析：{plain_kinds}")
    survivors = {m.node_id for edge in merged for m in edge.members
                 if m.kind == "sfx"}
    assert survivors == {f"sfx:长{i}" for i in range(6)}, (
        f"拆边不许丢知识，实测丢了：{{'sfx:长{i}' for i in range(6)}} - {survivors}")
    assert report["dropped_optional"] == 0, "能拆开就不该丢"


def test_merge_still_accounts_for_members_that_cannot_fit_even_alone():
    """拆边**不是**免死金牌：单个成员自己就超预算时仍要丢掉并记账。

    与上一条互补——上一条证明"能拆的必须拆"，这条证明"真装不下的必须记账"，
    两条合起来才是"不静默丢知识"的完整契约。
    """
    huge = [_node(f"sfx:巨{i}", "sfx", "啰" * 4000) for i in range(3)]
    nodes = _nodes(*huge)
    cards = {f"c{i}": _card(f"c{i}") for i in range(3)}
    edges = [
        _edge(f"c{i}",
              [("allow", "emotion", "emotion:荒诞"),
               ("qualifier", "intensity", "intensity:high"),
               ("allow", "sfx", f"sfx:巨{i}")])
        for i in range(3)
    ]
    merged, report = bh.merge_edges(edges, cards, nodes)
    for edge in merged:
        assert hg.render_tokens(hg.render_edge(edge, nodes)) <= hg.MAX_RENDER_TOKENS
    assert not any(m.kind == "sfx" for edge in merged for m in edge.members), (
        "装不下的成员不许硬塞进边里")
    assert report["dropped_optional"] >= 3, "每一个装不下的成员都要计数"
    assert report["over_budget_dropped"] >= 3, "根因必须是超预算，不是校验失败"


def test_every_merged_edge_passes_the_nine_gates():
    cards = {"a": _card("a"), "b": _card("b"), "c": _card("c")}
    edges = [
        _edge("a", [("allow", "shot_size", "shot_size:MS"),
                    ("allow", "lens", "lens:85mm"),
                    ("qualifier", "headroom_policy", "headroom_policy:board")],
              edge_type="SHOT_PATTERN"),
        _edge("b", [("allow", "shot_size", "shot_size:MS"),
                    ("allow", "lens", "lens:85mm"),
                    ("qualifier", "headroom_policy", "headroom_policy:board"),
                    ("allow", "movement", "movement:推轨")], edge_type="SHOT_PATTERN"),
        _edge("c", [("allow", "emotion", "emotion:荒诞"),
                    ("qualifier", "intensity", "intensity:high"),
                    ("qualifier", "applies_to_genre", "applies_to_genre:film")]),
    ]
    merged, _report = bh.merge_edges(edges, cards, _nodes())
    for edge in merged:
        hg.validate_edge(edge, _nodes())


def test_merge_keeps_every_contributing_source_span():
    """§2.3：归并结果要回指**全部** source_span（不是只留第一条）。"""
    cards = {"a": _card("a", start=0), "b": _card("b", start=50)}
    edges = [_minimal("a"),
             _edge("b", [("allow", "emotion", "emotion:荒诞"),
                         ("qualifier", "intensity", "intensity:high"),
                         ("allow", "movement", "movement:甩镜")], start=50)]
    merged, _report = bh.merge_edges(edges, cards, _nodes())
    span = merged[0].source_span
    assert span["chunk_id"], "主 span 仍须可解析（门⑥）"
    spans = {(item["chunk_id"], item["start"], item["end"]) for item in span["spans"]}
    assert spans == {("chunk_a", 0, 10), ("chunk_b", 50, 60)}


def test_merge_of_nothing_is_empty_not_an_error():
    merged, report = bh.merge_edges([], {}, _nodes())
    assert merged == []
    assert report["merged_edges"] == 0
