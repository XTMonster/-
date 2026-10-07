"""机械重绑（`rebind/v2`）的纯规则单测（user 2026-10-07 批准代号「换卡」）。

它是**确定性**的：同一份输入必须给出同一份输出；候选只来自"正文真的写了这个取值"
的卡；**不删原来源**（union-add）；找不到候选时**原样保留**（不猜）。

`v2` 再钉一条**保范围**不变量：候选池＝"重绑前就已经有边"的卡，所以重绑**永不**
让一张零边卡变成有边卡——那正是 `v1` 让门⑥ 长出 11 张孤儿卡的机制
（`tools/kb_fetch/rebind.py` 的模块文档）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import rebind  # noqa: E402

BLOBS = {
    #: 注意 fixtures 里**不许**出现取值本身：子串规则会认"与平视无关"里的"平视"
    #: ——这正是 `rebind/v1` 的已知弱点（它只查"写没写过"，不判语义）。测试夹具
    #: 刻意避开它，让用例测的是规则本身；那条弱点记在 `rebind.py` 的 docstring 与
    #: 影子对照里（仍有 37/90 判 `wrong_card`）。
    "card_a": "讲表演节奏与快慢控制的卡",
    "card_b": "机位高度与平视构图的关系",
    "card_c": "平视机位在正反打里的用法",
    "card_d": "构图平衡",
}


def _surfaces(node_id: str):
    return {
        "camera_angle:平视": ["平视"],
        "composition_rule:balance": ["平衡"],
        "camera_angle:仰视": ["仰视"],
    }.get(node_id, [])


def _labels(edge, member):
    #: 夹具：只有 card_a 担保这条边，所以值取自 card_a 的正文
    own = " ".join(BLOBS[str(s)] for s in (edge.get("sources") or [])
                   if str(s) in BLOBS)
    key = str(member[2])
    forms = _surfaces(key)
    return "unattested" if not any(f in own for f in forms) else "attested"


def _edge(members, sources):
    return {"edge_id": "hg:x", "type": "PERFORMANCE_PACK",
            "members": members, "sources": list(sources)}


def test_candidates_come_only_from_cards_that_really_write_the_value():
    assert rebind.candidate_cards(["平视"], BLOBS, limit=5) == ["card_b", "card_c"]
    assert rebind.candidate_cards(["不存在的东西"], BLOBS) == []
    assert rebind.candidate_cards([], BLOBS) == []


def test_the_candidate_pool_restricts_who_may_be_cited():
    """`v2`：池外的卡**一字不许进**；池内照旧按 `blobs` 的顺序取前 N。"""
    assert rebind.candidate_cards(["平视"], BLOBS, limit=5,
                                  pool=["card_a", "card_c"]) == ["card_c"]
    assert rebind.candidate_cards(["平视"], BLOBS, limit=5, pool=["card_a"]) == []
    #: `None` ＝ 不设限（保留 `v1` 的行为给历史对拍）；**空池** ≠ 不设限。
    assert rebind.candidate_cards(["平视"], BLOBS, limit=5, pool=[]) == []


def test_edge_backed_cards_is_the_scope_of_the_input():
    edges = [_edge([["qualifier", "camera_angle", "camera_angle:平视"]], ["card_a"]),
             _edge([["qualifier", "camera_angle", "camera_angle:仰视"]], ["card_a", "card_d"])]
    assert rebind.edge_backed_cards(edges) == {"card_a", "card_d"}
    assert rebind.edge_backed_cards([]) == set()


def test_the_pool_keeps_the_scope_fixed_and_reports_it():
    """`v1` 的行为（不设池）会把 `card_b`/`card_c` **新**变成有边卡；设池之后不会。"""
    edge = _edge([["qualifier", "camera_angle", "camera_angle:平视"]], ["card_a"])

    loose, _ = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces)
    assert rebind.edge_backed_cards(loose) - {"card_a"} == {"card_b", "card_c"}, (
        "不设池时必须复现 `v1` 的行为（这条是 `v2` 的对照）")

    tight, stats = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces,
                                       candidate_pool=rebind.edge_backed_cards([edge]))
    assert tight[0]["sources"] == ["card_a"], "池里没有第二张卡 ⇒ 不猜、不动"
    assert rebind.edge_backed_cards(tight) == {"card_a"}, "保范围：一张新卡都不许进来"
    assert stats["candidate_pool"] == 1
    assert stats["members_without_candidate"] == 1


def test_the_pool_still_rebinds_inside_the_scope():
    """池里有真的写了取值的卡时，照旧重绑（收窄不是"关掉规则"）。"""
    edge = _edge([["qualifier", "camera_angle", "camera_angle:平视"]], ["card_d"])
    out, stats = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces,
                                     candidate_pool=["card_d", "card_c"])
    assert out[0]["sources"] == ["card_d", "card_c"]
    assert stats["edges_touched"] == 1 and stats["sources_added"] == 1


# ---------------------------------------------------------------- 裁决剪枝（prune/v1）
#
# 用户 2026-10-07："用…qwen3.8max0902 解决，代替人工裁决"——零候选槽位由判官逐条裁，
# 判成 wrong_card / wrong_value 的成员从它所属的边上摘掉（边被摘空就整条删）。
# 规则是确定性的：判决来自**入库的记录**，没判决的一律不动。


def _pair(edge_id, kind, value, verdict, why=""):
    return {"edge_id": edge_id, "kind": kind, "value": value,
            "verdict": verdict, "why": why}


def test_prune_removes_flagged_members_only():
    edges = [{"edge_id": "hg:1", "type": "IMPACT_PACK",
              "members": [["allow", "vfx", "vfx:impact_frame"],
                          ["allow", "sfx", "sfx:金属撞击"],
                          ["allow", "movement", "movement:handheld"]],
              "sources": ["card_a"]}]
    out, stats = rebind.prune_members(
        edges, [_pair("hg:1", "vfx", "impact_frame", "wrong_card", "卡与主题无关")])
    assert [str(m[2]) for m in out[0]["members"]] == ["sfx:金属撞击",
                                                      "movement:handheld"]
    assert stats["members_removed"] == 1 and stats["edges_removed"] == 0
    assert stats["edges_touched"] == 1


def test_prune_drops_an_edge_that_loses_every_member():
    edges = [{"edge_id": "hg:2", "type": "SOUND_PACK",
              "members": [["allow", "sfx", "sfx:尖锐哨音"]], "sources": ["card_a"]}]
    out, stats = rebind.prune_members(
        edges, [_pair("hg:2", "sfx", "尖锐哨音", "wrong_value")])
    assert out == [] and stats["edges_removed"] == 1


def test_prune_leaves_everything_alone_when_the_verdict_says_keep():
    """`keep` 与"没判决"都是**不动**：摘枝只许听判决（不许顺手加严）。"""
    edges = [{"edge_id": "hg:3", "type": "SHOT_PATTERN",
              "members": [["allow", "headroom_policy", "headroom_policy:cinematic"]],
              "sources": ["card_a"]}]
    out, stats = rebind.prune_members(
        edges, [_pair("hg:3", "headroom_policy", "cinematic", "keep")])
    assert out == edges and stats["members_removed"] == 0
    out2, stats2 = rebind.prune_members(edges, [])
    assert out2 == edges and stats2["edges_touched"] == 0


def test_load_prune_verdicts_reads_the_shipped_record_and_skips_keeps(tmp_path):
    """入库记录 → 名单：`keep` 不进名单；记录不在（或空）就是一条都不摘。

    **两条闸门**：① 记录里 `apply` 必须显式为真（缺省＝不执行——索引不会因为躺在
    别处的一份记录而悄悄改）；② 只认 `wrong_card`/`wrong_value`。
    """
    import json

    record = {"reviewed_by": "third-party", "apply": True, "rows": [
        _pair("hg:4", "vfx", "impact_frame", "wrong_card", "卡与主题无关"),
        _pair("hg:5", "headline", "cinematic", "keep", "闭集词元")]}
    path = tmp_path / rebind.PRUNE_VERDICT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    picked = rebind.load_prune_verdicts(tmp_path)
    assert [row["edge_id"] for row in picked] == ["hg:4"]
    assert picked[0]["verdict"] == "wrong_card"
    assert rebind.load_prune_verdicts(tmp_path / "nope") == []

    #: 关掉闸门（缺 `apply` 或 `apply: false`）⇒ 一条都不摘，指纹也不该变。
    record["apply"] = False
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    assert rebind.load_prune_verdicts(tmp_path) == []
    assert rebind.binding_rules_version(applied=False) == rebind.REBIND_VERSION
    assert rebind.binding_rules_version(applied=True) == (
        "%s+%s" % (rebind.REBIND_VERSION, rebind.PRUNE_VERSION))

    shipped = rebind.load_prune_verdicts()
    assert all(row["verdict"] in ("wrong_card", "wrong_value") for row in shipped)


def test_the_binding_rules_version_covers_both_rules():
    """第 9 格指纹分量＝绑定规则版本：重绑与剪枝**任一条**变了它就得变。"""
    assert rebind.binding_rules_version(applied=True) == ("%s+%s"
                                                         % (rebind.REBIND_VERSION,
                                                            rebind.PRUNE_VERSION))
    assert rebind.PRUNE_VERSION in rebind.binding_rules_version(applied=True)
    assert rebind.binding_rules_version(applied=False) == rebind.REBIND_VERSION


def test_rebind_unions_candidates_and_keeps_the_original_sources():
    edge = _edge([["qualifier", "camera_angle", "camera_angle:平视"]], ["card_a"])
    out, stats = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces)
    assert out[0]["sources"] == ["card_a", "card_b", "card_c"], out[0]["sources"]
    assert edge["sources"] == ["card_a"], "原输入不许被就地改写"
    assert stats["edges_touched"] == 1 and stats["sources_added"] == 2
    assert stats["rebind_version"] == rebind.REBIND_VERSION


def test_no_candidate_leaves_the_edge_untouched_and_is_counted():
    edge = _edge([["qualifier", "camera_angle", "camera_angle:仰视"]], ["card_a"])
    out, stats = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces)
    assert out[0]["sources"] == ["card_a"], "没有候选 ⇒ 不猜、不动"
    assert stats["edges_touched"] == 0
    assert stats["members_without_candidate"] == 1


def test_attested_members_are_not_touched():
    edge = _edge([["allow", "composition_rule", "composition_rule:balance"]],
                 ["card_d"])
    out, stats = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces)
    assert out[0]["sources"] == ["card_d"]
    assert stats["edges_touched"] == 0


def test_it_is_deterministic():
    edge = _edge([["qualifier", "camera_angle", "camera_angle:平视"]], ["card_a"])
    first, _ = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces)
    second, _ = rebind.rebind_edges([edge], BLOBS, _labels, _surfaces)
    assert first == second
