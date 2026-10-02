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
    #: §2.3b 的两通道路由：案例栏吃的是**散文**类比查询，不是约束串。
    block = retriever.block_for_shot("情绪=荒诞", analogy="荒诞的段落该怎么处理")
    assert "【硬约束（禁/许）】" in block
    assert "【经验建议（软）】" in block          # L2 的软边自成一栏
    assert "【参考案例（仅参考）】" in block
    info = retriever.cases_info()
    assert info["lanes"] == 2 and info["cases_backend"] == "hybrid"
    assert info["cases_degraded"] is False


def test_the_soft_edge_never_lands_in_the_hard_column():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "hybrid"))
    block = retriever.block_for_shot("情绪=荒诞", analogy="荒诞的段落该怎么处理")
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
    block = retriever.block_for_shot("情绪=荒诞", analogy="荒诞的段落该怎么处理")
    assert block
    assert estimate_tokens(block) <= 120
    plan_block = retriever.block_for_plan("情绪=荒诞；运镜=固定")
    assert estimate_tokens(plan_block) <= 200


def test_a_case_that_does_not_fit_is_dropped_whole_and_recorded():
    retriever = _retriever(cases_index=CaseIndex(_cases(), "hybrid"),
                           token_limit=1)          # 连一条案例都装不下
    block = retriever.block_for_shot("情绪=荒诞", analogy="荒诞的段落该怎么处理")
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

        def retrieve_response(self, query, domain, top_k, timeout, cases_top_k,
                              analogy_query=""):
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
    #: §2.3b 的两条通道各喂各的：约束串给超图，散文给案例层。
    block = retriever.block_for_shot("情绪=荒诞", analogy="荒诞的瞬间")
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


# --------------------------------------------------------------------------- #
# §3.2 的两个配置键（`rag.cases_backend` / `rag.cases_top_k`）必须有生产者。
# 在此之前两个键都没有任何读取点：`off` 关不掉第三栏，条数永远是写死的 3。
# --------------------------------------------------------------------------- #
def test_the_packaged_case_index_is_assembled_when_there_is_no_sidecar():
    """**没有 sidecar 时的回落必须真的发生**（2026-10-01 修）。

    文档写着"装了 client 时案例由 `/v1/retrieve` 带回；**没有 client 时才用它**
    （进程内案例索引）"，但 `cases_index` 只有测试和 sidecar 会传 ——
    插件侧的 `_make_knowledge` 从来不传，于是这句回落**从来没有执行过**：

    * **凡是没有 client 又会渲染三栏的通路**（进程内超图）第三栏「参考案例」
      恒空，哪怕 `knowledge/cases.jsonl` 就在仓库里、`CaseIndex` 装上就能检索；
      （没有 client 时 backend 会先降级成 BM25 卡片通路，那条路不渲染三栏，
      不属本次修复范围 —— 这里只断言"装上并如实降级"。）
    * `cases_info()` 还会把 `rag.cases_backend=lightrag` 报成 `"off"` —— 而 `off`
      的定义是"**用户显式关闭**"，报告说反了。

    这条用例断言的是"装上并如实降级"：backend 报 `hybrid`、`cases_degraded=true`
    且原因是 `lightrag_adapter_unavailable`（仓库里没有 lightrag 依赖），
    `cases_requested_backend` 保留用户配的 `lightrag`。
    """
    from block_director.contracts.enums import RagBackend
    from block_director.knowledge.retriever import default_retriever

    retriever = default_retriever(backend=RagBackend.BM25,
                                  cases_backend="lightrag", cases_top_k=3)
    assert retriever.cases_enabled is True
    #: 查询要落在**作者写的字**上（见 `CaseIndex._text`）：这条查询在仓库的案例语料里
    #: 有逐字出处（Skwigly 的故事板教程），所以第三栏出得来。
    block = retriever.case_block("cut to a close-up")
    assert block and "【参考案例（仅参考）】" in block
    #: **反面**：纯中文查询在**英文**案例语料里没有词命中，于是拿不到案例。
    #: 这不是"少给"，是不给噪声——2026-10-02 实测过代价：标签（我们生成的
    #: `镜头与焦距：…摘记NNN` 与域标签 `色彩`）也曾进检索，于是中文查询能"命中"
    #: 自己的标签，返回一堆 1900 年代散句（双模型面板 1–2 分，E1 = 0/16）。
    assert retriever.case_block("剪辑节奏 短镜 硬切") == ""
    info = retriever.cases_info()
    assert info["cases_backend"] == "hybrid"           # §2.3b 的降级路径
    assert info["cases_requested_backend"] == "lightrag"
    assert info["cases_degraded"] is True
    assert info["cases_degraded_reason"] == "lightrag_adapter_unavailable"
    assert info["lanes"] == 2
    assert info["cases_index_fingerprint"], "装了索引就必须报出它的指纹"
    # 这条通道**不额外发检索**：进程内索引，`retrieval_calls` 保持 0。
    assert retriever.retrieval_calls == 0


def test_an_explicitly_off_case_lane_does_not_even_load_the_index():
    """用户显式关闭时不装索引、不产出第三栏、也不说自己降级了（§2.3b）。"""
    from block_director.contracts.enums import RagBackend
    from block_director.knowledge.retriever import default_retriever

    retriever = default_retriever(backend=RagBackend.BM25, cases_backend="off")
    assert retriever.cases_enabled is False
    assert retriever.cases_index is None
    assert retriever.case_block("剪辑节奏") == ""
    info = retriever.cases_info()
    assert info["cases_backend"] == "off" and info["lanes"] == 1
    assert info["cases_degraded"] is False


class _RecordingTransport:
    def __init__(self):
        self.cases_top_k_seen = []

    def retrieve_response(self, query, domain, top_k, timeout, cases_top_k,
                          analogy_query=""):
        self.cases_top_k_seen.append(cases_top_k)
        return RetrieveResponse(cards=[], edges=[], cases=_cases(),
                                trace={"backend": "hypergraph", "lanes": 2,
                                       "query": query, "cases_backend": "hybrid",
                                       "cases_degraded": False})


def test_the_case_lane_sends_the_configured_top_k_not_a_hardcoded_three():
    transport = _RecordingTransport()
    retriever = KnowledgeRetriever(
        cards=[], backend=RagBackend.HYPERGRAPH, capabilities=("hypergraph",),
        client=KnowledgeClient(transport), cases_top_k=1)
    block = retriever.block_for_shot("情绪=荒诞", analogy="荒诞的瞬间")
    assert transport.cases_top_k_seen == [1]     # 发出去的就是配置值
    assert "【参考案例（仅参考）】" in block
    assert len(retriever.last_cases) == 1        # 注入的条数也跟着配置


def test_without_an_analogy_query_the_case_lane_is_not_asked_at_all():
    """§2.3b 的两通道路由：**没有类比查询就不查 L3**，而不是拿约束串去查。

    旧实现让两条通道共用 `query`，于是 `景别=CU；运镜=dolly_in；对白=dialogue`
    这种契约串也被送去查案例层。实测代价（2026-10-02，真实运行的 10 条逐镜查询 ×
    每镜 top-3）：返回的 24 条案例被双模型面板判成 1–2 分，**E1 = 0/24**
    ——"参考案例"那一栏在镜头上是噪声。现在没类比查询就**一条都不索要**
    （`cases_top_k=0`），`retrieval_calls` 的账也如实反映这一点。
    """
    transport = _RecordingTransport()
    retriever = KnowledgeRetriever(
        cards=[], backend=RagBackend.HYPERGRAPH, capabilities=("hypergraph",),
        client=KnowledgeClient(transport))
    block = retriever.block_for_shot("情绪=荒诞")
    assert transport.cases_top_k_seen == [0]
    assert "【参考案例（仅参考）】" not in block


def test_cases_backend_off_does_not_even_ask_the_sidecar():
    """`off` ＝ 显式关闭：恒空、**不索要**、不算降级（§2.3b 的取值表）。"""
    transport = _RecordingTransport()
    retriever = KnowledgeRetriever(
        cards=[], backend=RagBackend.HYPERGRAPH, capabilities=("hypergraph",),
        client=KnowledgeClient(transport), cases_backend="off")
    block = retriever.block_for_shot("情绪=荒诞")
    assert "参考案例" not in block
    assert transport.cases_top_k_seen == [0]     # 关掉就不发这个请求
    info = retriever.cases_info()
    assert info == {"cases": 0, "lanes": 1, "cases_backend": "off",
                    "cases_requested_backend": "off", "cases_degraded": False,
                    "cases_degraded_reason": "",
                    "lightrag_index_fingerprint": "",
                    "cases_index_fingerprint": ""}
    payload = retriever.trace_payload()
    assert payload["cases_backend"] == "off" and payload["lanes"] == 1


def test_make_knowledge_reads_both_case_keys_from_the_config():
    """接线落点：`headless_runner._make_knowledge()`——配置改了必须传下去。"""
    import copy

    from block_director.layer5_orchestrator.headless_runner import _make_knowledge
    from block_director.settings import get_config

    config = copy.deepcopy(get_config())
    config.rag.cases_backend = "off"
    config.rag.cases_top_k = 2
    retriever = _make_knowledge(config, transport=_RecordingTransport())
    assert retriever.cases_backend == "off"
    assert retriever.cases_top_k == 2

    defaults = _make_knowledge(copy.deepcopy(get_config()))
    assert defaults.cases_backend == "lightrag"   # 默认值不许被上面那次改掉
    assert defaults.cases_top_k == 3
