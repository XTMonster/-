"""oracle 与索引对齐度工具（`tools/knowledge/oracle_alignment.py`）的对拍测试。

三种关系必须**分开报**，因为它们是三个不同的判据：
`exact`（现行门⑪）／`subset`（标注成员 ⊆ 索引边成员、forbid 相等）／
`card_subset`（再要求同卡来源）。工具如果把它们混成一个数，
"到底该不该改判据"就没法裁决了。
"""

from __future__ import annotations

from tools.knowledge import oracle_alignment as oa


def _edge(etype: str, members: list, card: str) -> dict:
    return {"type": etype, "members": members, "sources": [card]}


EDGES = [
    _edge("EMOTION_PACK",
          [["allow", "emotion", "emotion:荒诞"], ["qualifier", "intensity", "intensity:high"],
           ["forbid", "movement", "movement:固定"]], "gen_cine_0001"),
    _edge("EDIT_RHYTHM",
          [["allow", "pacing", "pacing:short"], ["qualifier", "avg_shot_len", "avg_shot_len:<1s"]],
          "gen_cine_0002"),
]


def _entry(card: str, must: list) -> dict:
    return {"id": "hq_0001", "from_card": card, "q": "", "must": list(must),
            "top1": [must[0]], "never": []}


def test_exact_requires_the_member_set_to_be_identical():
    entry = _entry("gen_cine_0001", ["EMOTION_PACK:emotion=荒诞,intensity=high,"
                                     "forbid_movement=固定"])
    result = oa.match(entry, entry["must"][0], EDGES)
    assert result == {"exact": True, "subset": True, "card_subset": True}


def test_subset_accepts_an_edge_with_extra_members_but_not_extra_forbids():
    """索引那条边多带一个成员时，标注写的下界仍然成立；forbid 必须完全相等。"""
    edges = [_edge("EMOTION_PACK",
                   [["allow", "emotion", "emotion:荒诞"],
                    ["qualifier", "intensity", "intensity:high"],
                    ["allow", "movement", "movement:推镜"]], "gen_cine_0001")]
    entry = _entry("gen_cine_0001", ["EMOTION_PACK:emotion=荒诞,intensity=high"])
    result = oa.match(entry, entry["must"][0], edges)
    assert result["exact"] is False and result["subset"] is True

    forbid_mismatch = _edge("EMOTION_PACK",
                            [["allow", "emotion", "emotion:荒诞"],
                             ["qualifier", "intensity", "intensity:high"],
                             ["forbid", "movement", "movement:固定"]], "gen_cine_0001")
    assert oa.match(entry, entry["must"][0], [forbid_mismatch])["subset"] is False


def test_card_subset_is_scoped_to_the_source_card():
    """同一条边、同一组成员，来自别的卡时只有 exact/subset 成立。"""
    other = _edge("EMOTION_PACK",
                  [["allow", "emotion", "emotion:荒诞"], ["qualifier", "intensity", "intensity:high"]],
                  "gen_comp_0009")
    entry = _entry("gen_cine_0001", ["EMOTION_PACK:emotion=荒诞,intensity=high"])
    result = oa.match(entry, entry["must"][0], [other])
    assert result["exact"] is True and result["subset"] is True
    assert result["card_subset"] is False


def test_run_reports_the_three_relations_separately():
    entries = [
        # 索引里那条 EMOTION_PACK 带 forbid 成员，所以**写全**才谈得上相等：
        # 少写 forbid 的期望在"forbid 完全相等"下不算命中（见 covers 的注释）。
        _entry("gen_cine_0001",
               ["EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"]),
        _entry("gen_cine_0002", ["EDIT_RHYTHM:pacing=short,avg_shot_len=<1s"]),
        _entry("gen_cine_0003", ["TROPE:genre=film,emotion=荒诞"]),   # 索引里没有
    ]
    report = oa.run(entries, EDGES)
    assert report["entries"] == 3 and report["must_total"] == 3
    assert report["must_hits"]["exact"] == 2
    assert report["must_hits"]["card_subset"] == 2
    assert report["ceiling_Q2"]["exact"] == 2 / 3
    assert report["unmatched_examples"][0]["must"].startswith("TROPE:")


def test_unparsable_specs_count_as_misses_not_crashes():
    entry = _entry("gen_cine_0001", ["NOT_A_TYPE:emotion=荒诞"])
    report = oa.run([entry], EDGES)
    assert report["must_hits"] == {"exact": 0, "subset": 0, "card_subset": 0}
