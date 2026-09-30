"""超图 schema 与 9 条校验门（执行文档 v1.4 §2.3 / §B.3 的 P14 行）。

纯层测试：不依赖 Blender，也不依赖网络。
"""

from __future__ import annotations

import pytest

from block_director.knowledge import hypergraph as hg


def node(node_id: str, kind: str, name: str, aliases=(), value: str = "") -> hg.Node:
    return hg.Node(node_id=node_id, type=kind, name=name, aliases=tuple(aliases), value=value)


NODES = {
    n.node_id: n for n in (
        node("emotion:荒诞", "emotion", "荒诞", ("滑稽", "absurd")),
        node("intensity:high", "intensity", "高", value="high"),
        node("intensity:low", "intensity", "低", value="low"),
        node("movement:whip_pan", "movement", "甩镜", ("甩镜头",)),
        node("movement:固定", "movement", "固定机位", ("固定", "static")),
        node("shot_size:CU", "shot_size", "特写"),
        node("shot_size:MS", "shot_size", "中景"),
        node("lens:85mm", "lens", "85mm"),
        node("headroom:board", "headroom_policy", "board", value="board"),
        node("pair:any_two", "pair", "any_two", value="any_two"),
        node("axis_side:left", "axis_side", "left", value="left"),
        node("genre:anime", "genre", "anime", value="anime"),
        node("lighting:逆光", "lighting", "逆光"),
        node("camera_angle:低机位", "camera_angle", "低机位"),
    )
}
SPAN = {"chunk_id": "chunk_001", "start": 0, "end": 42}


def edge(edge_type: str, members, **over) -> hg.HyperEdge:
    payload = {"type": edge_type, "members": tuple(members), "source_span": dict(SPAN)}
    payload.update(over)
    return hg.HyperEdge(**payload)


def emotion_pack(**over) -> hg.HyperEdge:
    return edge(hg.EMOTION_PACK, (
        hg.Member("allow", "emotion", "emotion:荒诞"),
        hg.Member("qualifier", "intensity", "intensity:high"),
        hg.Member("allow", "movement", "movement:whip_pan"),
        hg.Member("forbid", "movement", "movement:固定"),
    ), **over)


# --------------------------------------------------------------------------- 闭集


def test_vocabularies_match_the_spec():
    assert len(hg.NODE_TYPES) == 17          # v1.5 起含 `intent`
    assert len(hg.QUALIFIER_KINDS) == 10
    assert set(hg.EDGE_TYPES) == {
        "EMOTION_PACK", "SHOT_PATTERN", "AXIS_RULE", "TROPE", "EDIT_RHYTHM", "LIGHT_PACK",
        "ACTION_BEAT", "PERFORMANCE_PACK", "INTENT_PACK", "IMPACT_PACK",
        "STAGING_PACK", "SOUND_PACK", "TRANSITION_PACK",
    }
    assert set(hg.EDGE_TYPES) <= set(hg.TYPE_PRIORITY)
    for edge_type, required in hg.REQUIRED_MEMBERS.items():
        legal = set(required) | set(hg.OPTIONAL_MEMBERS[edge_type])
        assert set(required) <= legal
        for role, kind in legal:
            assert kind in hg.ALLOWED_KINDS, (edge_type, kind)
            assert role in hg.ROLES


def test_gate9_value_domains_cover_every_qualifier_kind():
    # 门⑨ 的完整覆盖面：每个 qualifier 要么有枚举、要么显式 None（不设枚举）
    for kind in hg.QUALIFIER_KINDS:
        assert kind in hg.VALUE_DOMAINS, kind
    assert hg.VALUE_DOMAINS["example_shot"] is None


# --------------------------------------------------------------------------- edge_id


def test_edge_id_includes_source_kind_and_hardness():
    theory = emotion_pack(source_kind="theory", hardness="hard")
    experience = emotion_pack(source_kind="experience", hardness="soft")
    assert theory.edge_id != experience.edge_id
    assert theory.edge_id == hg.edge_id_for(theory.type, theory.members, "theory", "hard")
    assert theory.to_dict()["edge_id"] == theory.edge_id


def test_occurrences_do_not_change_the_id():
    assert emotion_pack(occurrences=1).edge_id == emotion_pack(occurrences=9).edge_id


def test_gate2_rejects_a_tampered_declared_id():
    payload = emotion_pack().to_dict()
    payload["edge_id"] = "hg:000000000000"
    restored = hg.HyperEdge.from_dict(payload)
    with pytest.raises(hg.GateError, match="gate2_edge_id"):
        hg.validate_edge(restored, NODES)
    payload["edge_id"] = emotion_pack().edge_id
    hg.validate_edge(hg.HyperEdge.from_dict(payload), NODES)  # 正确 id 必须通过


# --------------------------------------------------------------------------- 九条门


def test_gate1_unknown_type():
    bad = emotion_pack()
    bad.type = "SCENE_EVENT"  # §2.3 已把它移出索引
    with pytest.raises(hg.GateError, match="gate1_type"):
        hg.validate_edge(bad, NODES)


@pytest.mark.parametrize("mutate,match", [
    (lambda e: e.members + (hg.Member("allow", "no_such_kind", "x"),), "gate3_kind"),
    (lambda e: e.members + (hg.Member("sideways", "movement", "movement:固定"),), "gate3_role"),
    (lambda e: e.members + (hg.Member("allow", "axis_topic", "axis_topic:x"),),
     "gate4_illegal_member"),
])
def test_gate3_and_gate4_illegal_members(mutate, match):
    bad = emotion_pack()
    bad.members = mutate(bad)
    with pytest.raises(hg.GateError, match=match):
        hg.validate_edge(bad, NODES)


def test_gate2_source_kind_and_hardness_closed():
    bad = emotion_pack(source_kind="rumour")
    with pytest.raises(hg.GateError, match="gate2_source_kind"):
        hg.validate_edge(bad, NODES)
    bad = emotion_pack(hardness="medium")
    with pytest.raises(hg.GateError, match="gate2_hardness"):
        hg.validate_edge(bad, NODES)


def test_gate4_missing_required_member():
    bad = edge(hg.EMOTION_PACK, (hg.Member("allow", "emotion", "emotion:荒诞"),))
    with pytest.raises(hg.GateError, match="gate4_missing"):
        hg.validate_edge(bad, NODES)


def test_gate5_allow_and_forbid_may_not_share_a_node():
    bad = edge(hg.EMOTION_PACK, (
        hg.Member("allow", "emotion", "emotion:荒诞"),
        hg.Member("qualifier", "intensity", "intensity:high"),
        hg.Member("allow", "movement", "movement:固定"),
        hg.Member("forbid", "movement", "movement:固定"),
    ))
    with pytest.raises(hg.GateError, match="gate5_allow_forbid_overlap"):
        hg.validate_edge(bad, NODES)


def test_gate6_source_span_must_be_parseable():
    with pytest.raises(hg.GateError, match="gate6_source_span:chunk_id"):
        hg.validate_edge(emotion_pack(source_span={}), NODES)
    with pytest.raises(hg.GateError, match="gate6_source_span:range"):
        hg.validate_edge(emotion_pack(source_span={"chunk_id": "c", "start": 5}), NODES)


def test_gate7_is_per_kind_containment_not_set_containment():
    """只有 shot_size / genre 参与，且是"按 kind 逐类包含"。"""
    good = edge(hg.SHOT_PATTERN, (
        hg.Member("allow", "shot_size", "shot_size:CU"),
        hg.Member("allow", "lens", "lens:85mm"),
        hg.Member("qualifier", "headroom_policy", "headroom:board"),
    ))
    hg.validate_edge(good, NODES)  # 没有 applies_to_* 时不参与门⑦

    bad = edge(hg.EMOTION_PACK, (
        hg.Member("allow", "emotion", "emotion:荒诞"),
        hg.Member("qualifier", "intensity", "intensity:high"),
        hg.Member("allow", "shot_size", "shot_size:CU"),
        hg.Member("qualifier", "applies_to_shot_size", "shot_size:MS"),
    ))
    with pytest.raises(hg.GateError, match="gate7_containment:shot_size"):
        hg.validate_edge(bad, NODES)

    ok = edge(hg.EMOTION_PACK, (
        hg.Member("allow", "emotion", "emotion:荒诞"),
        hg.Member("qualifier", "intensity", "intensity:high"),
        hg.Member("allow", "shot_size", "shot_size:CU"),
        hg.Member("qualifier", "applies_to_shot_size", "shot_size:CU"),
        hg.Member("allow", "movement", "movement:whip_pan"),  # movement 不受门⑦约束
    ))
    hg.validate_edge(ok, NODES)


def test_gate8_rejects_an_edge_that_cannot_be_rendered_within_budget():
    members = [hg.Member("allow", "emotion", "emotion:荒诞"),
               hg.Member("qualifier", "intensity", "intensity:high")]
    for index in range(60):
        members.append(hg.Member("allow", "movement", f"movement:长名字{index}"))
    extra = {f"movement:长名字{i}": node(f"movement:长名字{i}", "movement", f"很长的运镜名字第{i}号")
             for i in range(60)}
    big = edge(hg.EMOTION_PACK, tuple(members))
    with pytest.raises(hg.GateError, match="gate8_render_cost"):
        hg.validate_edge(big, {**NODES, **extra})


def test_gate9_rejects_values_outside_the_frozen_domain():
    bad = edge(hg.EMOTION_PACK, (
        hg.Member("allow", "emotion", "emotion:荒诞"),
        hg.Member("qualifier", "intensity", "intensity:extreme"),
    ))
    nodes = dict(NODES)
    nodes["intensity:extreme"] = node("intensity:extreme", "intensity", "极端", value="extreme")
    with pytest.raises(hg.GateError, match="gate9_value:intensity=extreme"):
        hg.validate_edge(bad, nodes)


# --------------------------------------------------------------------------- 索引


def test_build_index_identity_and_buildgate():
    goods = [emotion_pack() for _ in range(100)]
    duplicate = emotion_pack(occurrences=2, sources=("card_b",),
                             confidence_max=0.9)
    bad = edge(hg.EMOTION_PACK, (hg.Member("allow", "emotion", "emotion:荒诞"),))
    unique, report = hg.build_index(goods + [duplicate, bad], NODES,
                                    processed_chunks=10, total_chunks=10)
    assert len(unique) == 1
    assert report.raw_edges == 102
    assert report.valid_unique == 1
    assert report.duplicates == 100
    assert report.rejects == 1
    assert report.raw_edges == report.valid_unique + report.duplicates + report.rejects
    assert report.passed is True

    merged = unique[0]
    assert merged.occurrences == 102
    assert merged.confidence_max == 0.9


def test_duplicates_are_not_merged_across_source_kind():
    """E3（经验越权率 = 0）要求理论边与经验边是两条记录。"""
    theory = emotion_pack(source_kind="theory", hardness="hard")
    experience = emotion_pack(source_kind="experience", hardness="soft")
    unique, report = hg.build_index([theory, experience], NODES, 5, 5)
    assert len(unique) == 2
    assert report.duplicates == 0


def test_buildgate_fails_when_a_chunk_was_skipped_or_rejects_too_high():
    good = emotion_pack()
    _unique, report = hg.build_index([good], NODES, processed_chunks=9, total_chunks=10)
    assert report.passed is False  # 有 chunk 被跳过
    rejects = [edge(hg.EMOTION_PACK, (hg.Member("allow", "emotion", "emotion:荒诞"),))
               for _ in range(2)]
    _unique, report = hg.build_index([good] + rejects, NODES, 10, 10)
    assert report.reject_ratio > 0.05
    assert report.passed is False


# --------------------------------------------------------------------------- 注入


def test_render_is_closed_and_atomic():
    good = emotion_pack()
    text, dropped, quality_fail = hg.render_edges([good], NODES, token_limit=400)
    assert "禁=" in text and "固定机位" in text  # forbid 必须一起出现
    assert dropped == [] and quality_fail is False

    text, dropped, quality_fail = hg.render_edges([good], NODES, token_limit=1)
    assert text == ""
    assert dropped == [good.edge_id]
    assert quality_fail is True  # 单条自超限：整条不注入并记 quality_fail


def test_atomic_injection_never_truncates_a_line():
    edges = [emotion_pack() for _ in range(4)]
    text, dropped, _quality = hg.render_edges(edges, NODES, token_limit=60)
    for line in text.splitlines():
        assert line.startswith("[")
        assert "禁=" in line
    assert len(dropped) == 4 - len(text.splitlines()) if text else len(dropped) == 4


# --------------------------------------------------------------------------- 检索


def test_retrieve_seeds_expands_and_scores_forbidden_hits_higher():
    pack = emotion_pack(provenance_kind="拉片笔记", occurrences=5)
    graph = hg.Hypergraph(list(NODES.values()), [pack])
    selected, text, trace = graph.retrieve("情绪=荒诞；运镜=固定", top_k=3)
    assert selected == [pack]
    assert "禁=" in text
    assert trace.seed_miss is False
    assert trace.seeds
    # 查询明确点名了被禁的取值 -> 禁忌命中加成生效
    assert graph.score(pack, hg.parse_query("情绪=荒诞；运镜=固定"),
                       set(trace.seeds)) > graph.score(
        pack, hg.parse_query("情绪=荒诞"), set(trace.seeds))


def test_retrieve_reports_seed_miss_instead_of_returning_silently_empty():
    graph = hg.Hypergraph(list(NODES.values()), [emotion_pack()])
    selected, text, trace = graph.retrieve("情绪=完全不存在的词", top_k=3)
    assert selected == [] and text == ""
    assert trace.seed_miss is True


def test_query_aliases_and_boolean_dialogue_mapping():
    parsed = hg.parse_query("运镜=固定机位；景别=中景；对白=有；情绪=滑稽")
    assert parsed["movement"] == ["固定"]
    assert parsed["shot_size"] == ["MS"]
    assert parsed["scene_type"] == ["dialogue"]
    assert parsed["emotion"] == ["荒诞"]


def test_hub_pruning_marks_the_trace():
    # 造一个 hub：同一个节点挂 200 条边
    hub_node = node("movement:hub", "movement", "万能运镜")
    nodes = {**NODES, hub_node.node_id: hub_node}
    edges = []
    for index in range(200):
        edges.append(edge(hg.EMOTION_PACK, (
            hg.Member("allow", "emotion", "emotion:荒诞"),
            hg.Member("qualifier", "intensity", "intensity:high"),
            hg.Member("allow", "movement", hub_node.node_id),
        ), provenance_kind="网络语料"))
    graph = hg.Hypergraph(list(nodes.values()), edges)
    _selected, _text, trace = graph.retrieve("运镜=万能运镜", top_k=3)
    assert trace.expansion_truncated is True


# --------------------------------------------------------------------------- 抽取器


def _card_payload(card_id: str = "gen_cine_0001", provenance: str = "网络语料") -> dict:
    return {"id": card_id, "domain": "cinematography", "title": "t", "content": "c",
            "provenance_kind": provenance,
            "source_span": {"chunk_id": "chunk_001", "start": 0, "end": 10}}


def test_extractor_rejects_unknown_card_and_unlocatable_span():
    from tools.kb_fetch import build_hypergraph as bh

    cards = {"gen_cine_0001": _card_payload()}
    edge, reason = bh.to_edge({"type": "EMOTION_PACK", "source_card": "nope",
                               "members": [["allow", "emotion", "emotion:荒诞"],
                                           ["qualifier", "intensity", "intensity:high"]]},
                              cards)
    assert edge is None and reason.startswith("unknown_source_card")

    broken = {"gen_cine_0001": {**_card_payload(), "source_span": {}}}
    edge, reason = bh.to_edge({"type": "EMOTION_PACK", "source_card": "gen_cine_0001",
                               "members": [["allow", "emotion", "emotion:荒诞"],
                                           ["qualifier", "intensity", "intensity:high"]]},
                              broken)
    assert edge is None and reason == "unlocatable_source_span"


def test_experience_edges_may_not_carry_a_forbidden_member():
    """§2.3b 关键纪律 1：经验默认只能进 allow；越权即拒收（E3 的守门人）。"""
    from tools.kb_fetch import build_hypergraph as bh

    cards = {"gen_cine_0001": _card_payload(provenance="网络语料")}
    edge, reason = bh.to_edge({
        "type": "EMOTION_PACK", "source_card": "gen_cine_0001",
        "source_kind": "experience", "hardness": "soft",
        "members": [["allow", "emotion", "emotion:荒诞"],
                    ["qualifier", "intensity", "intensity:high"],
                    ["forbid", "movement", "movement:固定"]],
    }, cards)
    assert edge is None and reason == "experience_cannot_forbid"

    # lesson 是显式的"教训"，允许带 forbid
    edge, reason = bh.to_edge({
        "type": "EMOTION_PACK", "source_card": "gen_cine_0001",
        "source_kind": "lesson", "hardness": "hard",
        "members": [["allow", "emotion", "emotion:荒诞"],
                    ["qualifier", "intensity", "intensity:high"],
                    ["forbid", "movement", "movement:固定"]],
    }, cards)
    assert reason == "" and edge is not None
    assert edge.source_kind == "lesson"


def test_extractor_attaches_the_card_provenance_and_span():
    from tools.kb_fetch import build_hypergraph as bh

    cards = {"gen_cine_0001": _card_payload(provenance="权威文档")}
    edge, reason = bh.to_edge({
        "type": "EMOTION_PACK", "source_card": "gen_cine_0001",
        "members": [["allow", "emotion", "emotion:荒诞"],
                    ["qualifier", "intensity", "intensity:high"]],
    }, cards)
    assert reason == ""
    assert edge is not None
    assert edge.provenance_kind == "权威文档"
    assert edge.source_span["chunk_id"] == "chunk_001"
    assert edge.sources == ("gen_cine_0001",)
