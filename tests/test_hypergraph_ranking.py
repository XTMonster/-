"""排序：**精确匹配的边必须压过超集边**（v1.5 的 precision 项）。

只有 `coverage`（种子被边覆盖了多少）时，一条"把种子成员全带上、另外还多带
几个成员"的超集边能拿到同样的 1.0，再靠 `occurrences`/`confidence` 把精确
匹配的那条挤下去。实测（`tools/knowledge/ranking_quality.py`，300 条索引派生
查询）：加 precision 项后 Q1 0.5167 → 0.5867、Q2 0.7867 → 0.8567。
"""

from __future__ import annotations

from block_director.knowledge import hypergraph as hg


def _edge(members, occurrences: int = 1, confidence: float = 0.7) -> hg.HyperEdge:
    return hg.HyperEdge(
        type="EMOTION_PACK", members=tuple(members), source_kind="theory", hardness="hard",
        occurrences=occurrences, confidence=confidence, confidence_max=confidence,
        sources=("card_1",), source_span={"chunk_id": "c1", "start": 0, "end": 4},
        extractor={"prompt_version": "test"}, provenance_kind="生成卡片")


def _graph() -> tuple[hg.Hypergraph, hg.HyperEdge, hg.HyperEdge]:
    exact = _edge([hg.Member("allow", "emotion", "emotion:荒诞"),
                   hg.Member("qualifier", "intensity", "intensity:high")])
    # 语料支持**相同**（同 occurrences、同 confidence）：这时只有 precision 能把
    # 精确匹配与超集分开。若给超集更高的 occurrences，加权和可以正当地选它。
    superset = _edge([hg.Member("allow", "emotion", "emotion:荒诞"),
                      hg.Member("qualifier", "intensity", "intensity:high"),
                      hg.Member("allow", "movement", "movement:固定")])
    nodes = [hg.Node(node_id="emotion:荒诞", type="emotion", name="荒诞", value="荒诞"),
             hg.Node(node_id="intensity:high", type="intensity", name="high", value="high"),
             hg.Node(node_id="movement:固定", type="movement", name="固定", value="固定")]
    return hg.Hypergraph(nodes, [exact, superset]), exact, superset


def test_exact_edge_outranks_a_superset_that_merely_covers_the_seeds():
    """**同等语料支持**下，精确匹配必须压过"多带一个成员"的超集。

    这正是加 precision 项要修的回归：只有 coverage 时两者同分（都是 1.0），
    排序完全交给 occurrences/confidence。反过来，当超集边的 `occurrences`
    确实高出很多时，加权和仍可能选它——那是"这条耦合在语料里反复出现"的
    信号在起作用，属**有意为之**，不在本测试的射程内。
    """
    graph, exact, superset = _graph()
    query = hg.parse_query("情绪=荒诞")
    seeds = set(graph.seeds_for(query))
    assert seeds, "查询至少要命中一个种子，否则测的不是排序"

    assert graph.score(exact, query, seeds) > graph.score(superset, query, seeds), (
        "超集边靠 occurrences/confidence 抢到第一就是这条测试要挡的回归")

    selected, _text, _trace = graph.retrieve("情绪=荒诞", top_k=2, token_limit=10 ** 6)
    assert [edge.edge_id for edge in selected][0] == exact.edge_id


def test_intensity_key_makes_sibling_edges_distinguishable():
    """`强度` 这个查询键值不值，实测说了算。

    我先前只按"**可达性**"判定它没用（加键不会让任何边从召不回变成召得回），
    漏了"**区分度**"：同一类型里大量近邻边**只差一个 `intensity`**，查询说
    不出强度时它们无法区分，排序只能交给 occurrences/confidence，目标边常常
    屈居第二。全量 683 条索引派生查询：加 `强度` Q1 0.6164 → **0.7189**、
    Q2 0.8653 → **0.9165**（双双越过 0.70/0.90 线）。
    """
    assert hg.QUERY_KEYS.get("强度") == "intensity", "查询键必须存在，否则查询说不出强度"

    def pack(intensity: str) -> hg.HyperEdge:
        return hg.HyperEdge(
            type="EMOTION_PACK",
            members=(hg.Member("allow", "emotion", "emotion:荒诞"),
                     hg.Member("qualifier", "intensity", f"intensity:{intensity}")),
            source_kind="theory", hardness="hard", occurrences=1, confidence=0.7,
            confidence_max=0.7, sources=("card_1",),
            source_span={"chunk_id": "c1", "start": 0, "end": 4},
            extractor={"prompt_version": "test"}, provenance_kind="生成卡片")

    low, mid = pack("low"), pack("mid")
    nodes = [hg.Node(node_id="emotion:荒诞", type="emotion", name="荒诞", value="荒诞"),
             hg.Node(node_id="intensity:low", type="intensity", name="low", value="low"),
             hg.Node(node_id="intensity:mid", type="intensity", name="mid", value="mid")]
    graph = hg.Hypergraph(nodes, [low, mid])

    selected, _text, _trace = graph.retrieve("情绪=荒诞；强度=low", top_k=2,
                                             token_limit=10 ** 6)
    # 两条边只差强度：点名 low 时 low 必须在前，mid 只能排第二（这就是"能区分"）。
    assert [edge.edge_id for edge in selected] == [low.edge_id, mid.edge_id]


# --------------------------------------------------------------------------- #
# 契约串的**两半**：正向槽位与 `禁<键>`（2026-10-01 修）
# --------------------------------------------------------------------------- #
def _staging(composition: str, *, role: str) -> hg.HyperEdge:
    return hg.HyperEdge(
        type="STAGING_PACK",
        members=(hg.Member(role, "composition_rule", f"composition_rule:{composition}"),
                 hg.Member("allow", "shot_size", "shot_size:MS"),
                 hg.Member("qualifier", "camera_angle", "camera_angle:平视")),
        source_kind="theory", hardness="hard", occurrences=1, confidence=0.7,
        confidence_max=0.7, sources=("card_1",),
        source_span={"chunk_id": "c1", "start": 0, "end": 4},
        extractor={"prompt_version": "test"}, provenance_kind="生成卡片")


def test_parse_query_full_keeps_the_forbid_half_that_used_to_be_dropped():
    """`禁<键>=值` 必须被解析出来——此前它被 `parse_query` **整段丢掉**。

    `6c82511` 给 forbid 值配了独立查询键（`禁运镜=固定`），标注通道照它写 `q`，
    但解析器只查 `QUERY_KEYS`，于是"不要什么"这半从来没进过检索器：种子不含那个
    取值、`score()` 的禁忌项也永远算不出来。`parse_query` 的**公开行为不变**
    （只回正向半），新加的 `parse_query_full` 回两半。
    """
    plain, forbid = hg.parse_query_full("情绪=压抑；强度=high；禁运镜=固定")
    assert plain == {"emotion": ["压抑"], "intensity": ["high"]}
    assert forbid == {"movement": ["固定"]}
    # 老函数不变（既有调用点不受影响）
    assert hg.parse_query("情绪=压抑；禁运镜=固定") == {"emotion": ["压抑"]}
    # 别名在禁用半同样生效
    assert hg.parse_query_full("禁景别=特写")[1] == {"shot_size": ["CU"]}


def test_a_forbidden_value_never_counts_as_positive_coverage():
    """**问"三分法"不能被"不要用三分法"的边满足**——禁用成员不算正向覆盖。

    实测（v12 的 2438 条 oracle）：主导 Q4 缺口的那条查询
    `构图=rule_of_thirds；景别=MS；机位=平视` 重复 34 次，required 边输给三条
    "把 rule_of_thirds 标成 forbid"的 STAGING_PACK —— 因为 `_edge_coverage`
    把 **forbid 成员也算成覆盖**。修掉之后那条查询的 required 边在真实索引里
    排到 **第 1**（0.7329 vs 被禁边的 0.6598），全量 Q1 0.797→0.872、Q4 缺失 55→12。

    这里断言的是**不变量本身**（覆盖口径），不是"谁排第一"：查询里**正向**点名
    的取值，只有当它出现在 allow/qualifier 槽位上时才算覆盖；`禁<键>=值` 那半
    走 `forbid_hit`（见 `test_an_explicit_forbid_seed_pulls_the_forbidding_edge_up`）。
    """
    want = _staging("rule_of_thirds", role="qualifier")
    forbidding = _staging("rule_of_thirds", role="forbid")
    other = _staging("balance", role="qualifier")
    nodes = [hg.Node(node_id="composition_rule:rule_of_thirds",
                     type="composition_rule", name="rule_of_thirds", value="rule_of_thirds"),
             hg.Node(node_id="composition_rule:balance", type="composition_rule",
                     name="balance", value="balance"),
             hg.Node(node_id="shot_size:MS", type="shot_size", name="MS", value="MS"),
             hg.Node(node_id="camera_angle:平视", type="camera_angle", name="平视", value="平视")]
    graph = hg.Hypergraph(nodes, [want, forbidding, other])
    query, forbid = hg.parse_query_full("构图=rule_of_thirds；景别=MS；机位=平视")
    seeds = set(graph.seeds_for(query))
    assert seeds == {"composition_rule:rule_of_thirds", "shot_size:MS",
                     "camera_angle:平视"}
    # 正向覆盖：allow/qualifier 那 3 个槽位都命中 = 1.0；被禁的那条只有 2/3。
    assert graph._edge_coverage(want, seeds) == 1.0
    assert abs(graph._edge_coverage(forbidding, seeds) - 2 / 3) < 1e-9
    # 而"另一条完全不同的构图规则"完全不覆盖 rule_of_thirds（2/3 也一样）。
    assert abs(graph._edge_coverage(other, seeds) - 2 / 3) < 1e-9


def test_an_explicit_forbid_seed_pulls_the_forbidding_edge_up():
    """反向：查询写 `禁构图=occlusion` 时，**带这条禁忌的边**要能被点名。

    它靠两件事：`parse_query_full` 把禁用语义带出来（`trace.forbid_seeds`），
    以及 `forbid_hit` 认得它。
    """
    forbidding = _staging("occlusion", role="forbid")
    other = _staging("balance", role="qualifier")
    nodes = [hg.Node(node_id="composition_rule:occlusion", type="composition_rule",
                     name="occlusion", value="occlusion"),
             hg.Node(node_id="composition_rule:balance", type="composition_rule",
                     name="balance", value="balance"),
             hg.Node(node_id="shot_size:MS", type="shot_size", name="MS", value="MS"),
             hg.Node(node_id="camera_angle:平视", type="camera_angle", name="平视", value="平视")]
    graph = hg.Hypergraph(nodes, [forbidding, other])
    text = "构图=balance；景别=MS；机位=平视；禁构图=occlusion"
    selected, rendered, trace = graph.retrieve(text, top_k=3, token_limit=10 ** 6)
    assert trace.forbid_seeds == {"composition_rule": ["occlusion"]}
    assert selected and selected[0].edge_id == forbidding.edge_id
    assert "禁=" in rendered
