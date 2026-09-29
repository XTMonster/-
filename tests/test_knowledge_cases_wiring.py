"""§2.3b 的**三栏呈现**在插件侧的接线（P14-4 的消费半边）。

要求写死的三件事：

1. 注入文本分三栏——「硬约束（禁/许）」「经验建议（软）」「参考案例（仅参考）」
   （L2 的软边**不得**与硬约束同栏，否则模型会把"某人经验"当成"必须遵守"）；
2. 三栏**共用同一个 token 上限**（每镜 ``rag.max_tokens_per_call``、整场
   ``rag.plan_prefetch_tokens``）——各栏各用满一次会让"注入 ≤800"变成 2×800；
3. 案例与超边**共用同一次** ``/v1/retrieve``（否则 §2.4 的 ``retrieval_calls``
   账会翻倍）。
"""

from __future__ import annotations

from block_director.contracts.enums import RagBackend
from block_director.contracts.knowledge import Case
from block_director.contracts.knowledge import HyperEdge as EdgeDTO
from block_director.contracts.operations import RetrieveResponse
from block_director.knowledge.cases import CaseIndex
from block_director.knowledge.client import KnowledgeClient
from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Member, Node
from block_director.knowledge.retriever import KnowledgeRetriever
from block_director.knowledge.tokens import estimate_tokens


def _nodes():
    return [
        Node(node_id="emotion:荒诞", type="emotion", name="荒诞",
             aliases=("荒诞", "滑稽")),
        Node(node_id="intensity:high", type="intensity", name="high",
             value="high"),
        Node(node_id="movement:甩镜", type="movement", name="甩镜",
             aliases=("甩镜", "whip_pan")),
        Node(node_id="movement:固定机位", type="movement", name="固定机位",
             aliases=("固定机位", "固定")),
    ]


def _edges():
    hard = HyperEdge(type="EMOTION_PACK", source_kind="theory", hardness="hard",
                     members=(Member("allow", "emotion", "emotion:荒诞"),
                              Member("qualifier", "intensity", "intensity:high"),
                              Member("allow", "movement", "movement:甩镜"),
                              Member("forbid", "movement", "movement:固定机位")))
    soft = HyperEdge(type="EMOTION_PACK", source_kind="experience",
                     hardness="soft", confidence=0.5,
                     members=(Member("allow", "emotion", "emotion:荒诞"),
                              Member("qualifier", "intensity", "intensity:high"),
                              Member("allow", "movement", "movement:甩镜")))
    return hard, soft


def _cases():
    """三条案例的摘要**各不相同**（BM25 在完全重复的语料上会退化成全零命中），
    但都提到"荒诞"——`情绪=荒诞` 因此能同时命中三条。"""
    excerpts = ("荒诞时刻先用甩镜，再让画面安静下来。",
                "荒诞的段落里，长镜静止更靠表演推进。",
                "荒诞情绪若越轴，要用中性镜头过渡。")
    return [Case(case_id=f"case_{index}", case_type="narrative",
                 title=f"参考案例 {index}", excerpt=excerpt,
                 source_ref={"title": "参考书", "author": "作者",
                             "license": "PublicDomain"})
            for index, excerpt in enumerate(excerpts, 1)]


def _retriever(**kwargs) -> KnowledgeRetriever:
    hard, soft = _edges()
    graph = Hypergraph(_nodes(), [hard, soft])
    base = dict(cards=[], backend=RagBackend.HYPERGRAPH,
                capabilities=("hypergraph",), hypergraph=graph)
    base.update(kwargs)
    return KnowledgeRetriever(**base)


def test_the_shot_block_carries_all_three_columns():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "hybrid"))
    block = retriever.block_for_shot("情绪=荒诞")
    assert "【硬约束（禁/许）】" in block
    assert "【经验建议（软）】" in block          # L2 的软边自成一栏
    assert "【参考案例（仅参考）】" in block
    info = retriever.cases_info()
    assert info["lanes"] == 2 and info["cases_backend"] == "hybrid"
    assert info["cases_degraded"] is False


def test_the_soft_edge_never_lands_in_the_hard_column():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "hybrid"))
    block = retriever.block_for_shot("情绪=荒诞")
    hard_column, _, rest = block.partition("【经验建议（软）】")
    assert "禁={" in hard_column                 # 硬约束那栏才有禁忌
    assert "禁={" not in rest or "【" not in rest
    assert "甩镜" in rest                        # 软边落在第二栏


def test_a_prohibition_is_never_demoted_into_the_advice_column():
    """`hardness=soft` 但带 `forbid` 的边仍属**硬约束**：禁不是建议。

    索引里实测存在 1 条这种边——按"只看 hardness"分栏，它的禁忌会被放进
    「经验建议（软）」，模型就有理由照样做（Q7 的拦截率就是这么丢的）。
    """
    nodes = _nodes()
    soft_with_forbid = HyperEdge(
        type="EMOTION_PACK", source_kind="lesson", hardness="soft",
        members=(Member("allow", "emotion", "emotion:荒诞"),
                 Member("qualifier", "intensity", "intensity:high"),
                 Member("forbid", "movement", "movement:固定机位")))
    graph = Hypergraph(nodes, [soft_with_forbid])
    retriever = KnowledgeRetriever(cards=[], backend=RagBackend.HYPERGRAPH,
                                   capabilities=("hypergraph",), hypergraph=graph)
    block = retriever.block_for_shot("情绪=荒诞")
    hard_column, _, rest = block.partition("【经验建议（软）】")
    assert "禁={" in hard_column and "固定机位" in hard_column
    assert "禁={" not in rest


def test_the_three_columns_share_one_token_budget():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "hybrid"),
                           token_limit=120, plan_token_limit=200)
    block = retriever.block_for_shot("情绪=荒诞")
    assert block
    assert estimate_tokens(block) <= 120
    plan_block = retriever.block_for_plan("情绪=荒诞；运镜=固定")
    assert estimate_tokens(plan_block) <= 200


def test_a_case_that_does_not_fit_is_dropped_whole_and_recorded():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "hybrid"),
                           token_limit=1)          # 连一条案例都装不下
    block = retriever.block_for_shot("情绪=荒诞")
    assert "【参考案例（仅参考）】" not in block   # 不输出空栏
    trace = retriever.trace_payload()
    # 顺序由 BM25 打分决定（不是 case_id 顺序），所以这里按集合判。
    assert sorted(trace["shot_scope"]["dropped_case_ids"]) == [
        "case_1", "case_2", "case_3"]
    assert trace["shot_scope"]["columns"]["case_tokens"] == 0


def test_the_client_lane_fetches_edges_and_cases_in_one_call():
    class _Transport:
        def __init__(self):
            self.calls = 0

        def retrieve_response(self, query, domain, top_k, timeout, cases_top_k):
            self.calls += 1
            edge = EdgeDTO(edge_id="hg:1", type="EMOTION_PACK",
                           members=[["allow", "emotion", "emotion:荒诞"],
                                    ["qualifier", "intensity", "intensity:high"],
                                    ["forbid", "movement", "movement:固定机位"]],
                           forbid=[["forbid", "movement", "movement:固定机位"]])
            return RetrieveResponse(cards=[], edges=[edge], cases=_cases(),
                                    trace={"backend": "hypergraph", "lanes": 2,
                                           "query": query,
                                           "cases_backend": "hybrid",
                                           "cases_degraded": False,
                                           "lightrag_index_fingerprint": "lr-fp"})

    transport = _Transport()
    client = KnowledgeClient(transport)
    retriever = KnowledgeRetriever(cards=[], backend=RagBackend.HYPERGRAPH,
                                   capabilities=("hypergraph",), client=client)
    block = retriever.block_for_shot("情绪=荒诞", "荒诞的瞬间")
    assert "【硬约束（禁/许）】" in block
    assert "【参考案例（仅参考）】" in block
    assert transport.calls == 1                 # 两栏共用一次检索
    assert retriever.retrieval_calls == 1
    info = retriever.cases_info()
    assert info["cases"] == 3 and info["cases_backend"] == "hybrid"
    assert info["lightrag_index_fingerprint"] == "lr-fp"


def test_an_off_case_lane_leaves_the_other_two_columns_intact():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "off"))
    block = retriever.block_for_shot("情绪=荒诞")
    assert "【硬约束（禁/许）】" in block
    assert "【参考案例（仅参考）】" not in block
    assert retriever.cases_info()["lanes"] == 1
    assert retriever.cases_info()["cases_degraded"] is False


def test_a_degraded_case_lane_says_so_in_the_trace():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "lightrag"))
    retriever.block_for_shot("情绪=荒诞")
    info = retriever.cases_info()
    assert info["cases_backend"] == "hybrid"     # §2.3b 的降级路径
    assert info["cases_degraded"] is True
    assert info["cases_degraded_reason"] == "lightrag_adapter_unavailable"
    payload = retriever.trace_payload()
    assert payload["cases_degraded"] is True
    assert payload["lanes"] == 2
