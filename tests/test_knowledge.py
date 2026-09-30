"""§6 Light RAG 测试：语料、BM25 内核、检索器、工具与注入时机。"""

from __future__ import annotations

import pytest

from block_director.cinema.composition import WEIGHTS
from block_director.cinema.framing import SHOT_FRAME
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import RagBackend
from block_director.knowledge import (
    CARDS,
    DOMAINS,
    TOKEN_LIMIT_TOOL,
    BM25,
    KnowledgeRetriever,
    cards_in_domain_order,
    default_retriever,
    estimate_tokens,
    make_bm25,
    register_knowledge_tools,
    reset_default_retriever,
    rrf_merge,
    tokenize,
    truncate_to_tokens,
)
from block_director.layer5_orchestrator.planner import (
    NO_KNOWLEDGE,
    build_plan_payload,
)
from block_director.layer5_orchestrator.tool_registry import ToolRegistry


def retriever(**kwargs) -> KnowledgeRetriever:
    return KnowledgeRetriever(cards=cards_in_domain_order(), **kwargs)


# --------------------------------------------------------------------------- #
# 语料完整性
# --------------------------------------------------------------------------- #
def test_every_domain_has_cards_with_required_fields():
    assert len(CARDS) >= 30
    for domain in DOMAINS:
        entries = [card for card in CARDS if card.domain == domain]
        assert entries, f"知识域 {domain} 是空的"
        for card in entries:
            assert card.title and card.content and card.keywords


def test_card_ids_are_unique_and_relations_resolve():
    ids = [card.id for card in CARDS]
    assert len(ids) == len(set(ids)), "知识卡 id 必须唯一"
    known = set(ids)
    for card in CARDS:
        for other in card.related:
            assert other in known, f"{card.id} 指向了不存在的条目 {other}"


def test_no_field_was_split_into_single_characters():
    """回归：``examples=("只有一条")``（漏尾逗号）会把字符串拆成单字。

    ``keywords`` 允许是单字术语（"推""拉""摇"），因此只对整句字段断言长度。
    """
    for card in CARDS:
        for field in ("keywords", "rules"):
            for item in getattr(card, field):
                assert isinstance(item, str) and item, \
                    f"{card.id}.{field} 里出现了空元素"
        for field in ("examples", "related"):
            for item in getattr(card, field):
                assert isinstance(item, str) and len(item) > 1, \
                    f"{card.id}.{field} 里出现了疑似被拆分的元素 {item!r}"


def test_corpus_matches_the_engine():
    """知识库里的数字必须与引擎实现一致，否则就是在教模型做错事。"""
    sizes = next(card for card in CARDS if card.id == "cine_shot_size")
    heights = next(card for card in CARDS if card.id == "cine_height")
    for shot, frame in SHOT_FRAME.items():
        if shot in ("OTS", "POV"):       # 复用邻近景别，不在九宫格里
            continue
        assert sizes.parameters["frame_height"][shot] == frame.frame_height
        # 对准高度也要对拍：CU 的"头顶被切"正是 target_z 与 frame_height
        # 一起决定的，只盯住一个数字会漏掉另一半。
        assert heights.parameters["target_z"][shot] == frame.target_z

    lenses = next(card for card in CARDS if card.id == "cine_lens")
    for shot, frame in SHOT_FRAME.items():
        if shot in ("OTS", "POV"):
            continue
        assert lenses.parameters["lens"][shot] == frame.lens

    occlusion = next(card for card in CARDS if card.id == "comp_occlusion")
    assert occlusion.parameters["weight"] == WEIGHTS["occlusion"]
    thirds = next(card for card in CARDS if card.id == "comp_thirds")
    assert thirds.parameters["weight"] == WEIGHTS["rule_of_thirds"]

    walk = next(card for card in CARDS if card.id == "block_walk")
    config = AppConfig()
    assert walk.parameters["walk_speed"] == config.animation.walk_speed
    assert walk.parameters["run_speed"] == config.animation.run_speed

    duration = next(card for card in CARDS if card.id == "cine_duration")
    assert duration.parameters["chinese_cps"] == config.dialogue.chinese_cps


def test_movement_cards_declare_the_real_engine_capability():
    """运镜卡的能力标注必须与引擎实际实现一致（v1.3 诉求 5）。

    语料里写"支持环绕"而引擎做不到，模型就会照着写计划；计划落地时才发现
    没有这个运镜，最后交付的视频里动都没动。所以这张表必须与
    ``cinema/camera_motion.py`` 的 ``MOVEMENT_TYPES`` 对拍。
    """
    from block_director.cinema.camera_motion import MOVEMENT_TYPES
    from block_director.knowledge.cards_cinematography import ENGINE_MOVEMENTS

    assert set(ENGINE_MOVEMENTS) == set(MOVEMENT_TYPES)

    movement_cards = [card for card in CARDS
                      if card.id.startswith("cine_move_")
                      and "运镜" in card.tags]
    assert len(movement_cards) >= 24, "运镜卡数量不足，应覆盖封闭清单的 24 种"
    for card in movement_cards:
        if card.id == "cine_move_index":
            assert set(card.parameters["implemented"]) == set(MOVEMENT_TYPES)
            continue
        move_id = card.id[len("cine_move_"):]
        expected = ("implemented" if move_id in MOVEMENT_TYPES
                    else "unsupported")
        assert card.engine_support == expected, (
            f"{card.id} 的能力标注是 {card.engine_support!r}，"
            f"引擎实际是 {expected!r}")
        assert card.emotion and card.emotion != "—", f"{card.id} 缺少情感语义"


def test_every_movement_card_states_when_not_to_use_it():
    """运镜卡必须写清禁忌——只讲"怎么用"的知识会让模型到处乱用。"""
    movement_cards = [card for card in CARDS
                      if card.id.startswith("cine_move_")
                      and "运镜" in card.tags and card.id != "cine_move_index"]
    missing = [card.id for card in movement_cards
               if not any(mark in card.content
                          for mark in ("禁忌", "禁止", "不宜", "不要"))]
    assert missing == [], f"以下运镜卡没有写使用禁忌：{missing}"


# --------------------------------------------------------------------------- #
# 切词与 BM25 内核
# --------------------------------------------------------------------------- #
def test_tokenizer_keeps_terms_and_bigrams():
    tokens = tokenize("180° 轴线与三分法 rule of thirds")
    assert "180" in tokens and "轴线" in tokens and "三分" in tokens
    assert "rule" in tokens and "thirds" in tokens
    # 不是相邻的中文不该被拼成一个 token
    assert "线三" not in tokenize("轴线 三分法")


def test_bm25_scores_a_matching_document_higher():
    corpus = [tokenize("轴线 越轴 同侧"), tokenize("构图 三分法 留白"),
              tokenize("坐下 起立 身体高度")]
    engine = BM25(corpus)
    scores = engine.get_scores(tokenize("越轴"))
    assert scores[0] > 0
    assert scores[1] == 0 and scores[2] == 0


def test_make_bm25_reports_the_engine_name():
    engine, name = make_bm25([tokenize("a b"), tokenize("b c")])
    assert name in ("builtin.BM25Okapi", "rank_bm25.BM25Okapi")
    assert len(engine.get_scores(["b"])) == 2


# --------------------------------------------------------------------------- #
# 检索器
# --------------------------------------------------------------------------- #
def test_domain_filter_confines_the_result():
    hits = retriever().search_hits("轴线", domain="axis_theory", top_k=5)
    assert hits and all(hit.card.domain == "axis_theory" for hit in hits)


def test_unknown_domain_warns_but_still_searches():
    engine = retriever()
    hits = engine.search_hits("越轴", domain="not_a_domain", top_k=3)
    assert hits
    assert any("未知知识域" in warning for warning in engine.warnings)


def test_queries_land_on_the_expected_card():
    engine = retriever()
    cases = {
        "越轴之后怎么换到另一侧": "axis_cross",
        "三分法 构图": "comp_thirds",
        "坐下 起立 身体高度": "perf_posture",
        "对白太长 镜头时长不够": "cine_duration",
        "角色被挡住了 构图": "comp_occlusion",
    }
    for query, expected in cases.items():
        hits = engine.search_hits(query, top_k=1)
        assert hits and hits[0].card.id == expected, f"{query} → {hits}"


def test_curated_cards_win_only_near_ties():
    """人工卡只在**分数接近**时抢位；生成卡高出一截时仍然由它胜出。

    这条规则是有界的：语料里每加一批生成卡，旗舰人工卡就会被同主题的候选
    挤下去一位。无界的"人工卡永远优先"会把明显更贴题的生成卡也压掉，
    所以并列带取实测差距（`越轴` 上 13.6%）之上的最小值。
    """
    from block_director.knowledge.retriever import CURATED_BOOST, curated_priority

    class _Card:
        def __init__(self, ident: str):
            self.id = ident

    cards = [_Card("comp_thirds"), _Card("gen_comp_0001"), _Card("comp_x")]
    near = curated_priority([(0, 100.0), (1, 100.0 * (CURATED_BOOST - 0.02))], cards)
    assert near[0][0] == 0, "13% 的差距属于并列，人工卡应当胜出"
    clear = curated_priority([(0, 100.0), (1, 100.0 * (CURATED_BOOST + 0.05))], cards)
    assert clear[0][0] == 1, "生成卡高出并列带时不能被人为压掉"
    # 同档之间只按分数排，且次序键稳定（分数相同时保留下标顺序）。
    same_tier = curated_priority([(2, 90.0), (0, 95.0)], cards)
    assert [index for index, _ in same_tier] == [0, 2]


def test_empty_query_returns_nothing():
    assert retriever().retrieve("   ") == []


def test_vector_request_without_sidecar_downgrades_with_a_warning():
    engine = retriever(backend=RagBackend.VECTOR)
    assert engine.backend is RagBackend.BM25
    assert any("降级" in warning for warning in engine.warnings)


class _FakeVectorStore:
    def __init__(self, order):
        self.order = order

    def search(self, query, limit):
        return [(index, 1.0) for index in self.order[:limit]]


def test_vector_rerank_uses_rrf_when_the_capability_is_confirmed():
    # 假向量库返回的是**语料下标**；写死 5/6/7 只在 132 卡时代成立（P14-1 把
    # 语料扩到 1000+ 之后，那三个下标已经落在别的域上）。按 id 反查真实下标，
    # 断言（向量通道召回的卡必须活过 RRF 合并）保持不变。
    ids = [card.id for card in cards_in_domain_order()]
    anchor = ids.index("axis_cross")
    engine = retriever(backend=RagBackend.VECTOR, capabilities=("vector",),
                       vector_store=_FakeVectorStore([anchor, anchor + 1, anchor + 2]))
    assert engine.backend is RagBackend.VECTOR
    hits = engine.search_hits("越轴", top_k=3)
    assert {hit.card.id for hit in hits} >= {"axis_cross"}
    assert len(hits) == 3


def test_rrf_merge_rewards_agreement():
    merged = rrf_merge([2, 1, 0], [2, 3])
    assert merged[0] == 2                      # 两路都排第一


# --------------------------------------------------------------------------- #
# token 上限与兜底
# --------------------------------------------------------------------------- #
def test_estimate_tokens_is_monotonic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("中文") == 2
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("中文中文") > estimate_tokens("中文")


def test_block_is_capped_to_the_token_limit():
    engine = retriever()
    block = engine.block("轴线 构图 调度 表演 景别", token_limit=60)
    assert estimate_tokens(block) <= 60
    assert "截断" in block


def test_short_block_is_not_truncated():
    block = retriever().block("越轴", domain="axis_theory", top_k=1,
                              token_limit=TOKEN_LIMIT_TOOL)
    assert block and "截断" not in block


def test_truncate_keeps_text_under_limit():
    text = "\n".join(f"第{i}行 三分法 轴线 构图" for i in range(50))
    limited = truncate_to_tokens(text, 80)
    assert estimate_tokens(limited) <= 80


def test_digest_backend_returns_summary_cards():
    engine = retriever(backend=RagBackend.DIGEST)
    cards = engine.retrieve("任意查询")
    assert len(cards) == len(DOMAINS)
    assert engine.block_for_plan("任意") == engine.digest_block()


def test_plan_block_is_larger_than_tool_block():
    engine = retriever()
    assert engine.block_for_plan("轴线 构图") != engine.block_for_shot("CU")
    assert estimate_tokens(engine.block_for_shot("CU")) <= TOKEN_LIMIT_TOOL


def test_default_retriever_does_not_cache_a_custom_configuration():
    reset_default_retriever()
    first = default_retriever()
    assert default_retriever() is first
    digest = default_retriever(backend=RagBackend.DIGEST)
    assert digest is not first and digest.backend is RagBackend.DIGEST
    assert default_retriever() is first   # 默认仍走缓存


# --------------------------------------------------------------------------- #
# 工具与注入
# --------------------------------------------------------------------------- #
def test_search_knowledge_tool_returns_cards():
    registry = ToolRegistry()
    register_knowledge_tools(registry, retriever())
    result = registry.execute("search_knowledge", {"query": "越轴"})
    assert result.ok and "axis_cross" in result.content
    assert estimate_tokens(result.content) <= TOKEN_LIMIT_TOOL + 10


def test_search_knowledge_rejects_bad_arguments():
    registry = ToolRegistry()
    register_knowledge_tools(registry, retriever())
    assert not registry.execute("search_knowledge", {}).ok
    bad_domain = registry.execute("search_knowledge",
                                  {"query": "越轴", "domain": "nope"})
    assert not bad_domain.ok and "参数校验失败" in bad_domain.content


def test_search_knowledge_miss_is_an_observation_not_an_error():
    registry = ToolRegistry()
    register_knowledge_tools(registry, retriever())
    result = registry.execute("search_knowledge",
                              {"query": "zzzqqq", "domain": "composition"})
    assert result.ok and "没有匹配" in result.content


def test_plan_prompt_carries_retrieved_knowledge():
    payload = build_plan_payload(None, retriever=retriever(),
                                 parsed=_parsed_stub())
    system = payload.messages[0].content
    assert "参考资料" in system and "[comp_thirds]" in system
    assert NO_KNOWLEDGE not in system


def test_plan_prompt_says_when_knowledge_is_off():
    payload = build_plan_payload("INT. 房间 - 日", retriever=None)
    assert NO_KNOWLEDGE in payload.messages[0].content


class _SceneStub:
    dialogues: list = []


class _ParsedStub:
    scenes = [_SceneStub()]

    def digest(self, max_scenes=20):
        return "场景：两人在咖啡馆争吵，涉及越轴与三分法构图"


def _parsed_stub():
    return _ParsedStub()


def test_offline_transport_retrieve_honours_its_bm25_capability():
    from block_director.layer5_orchestrator.offline import OfflineTransport

    cards = OfflineTransport().retrieve("越轴", "axis_theory", 3)
    assert cards and all(card.domain == "axis_theory" for card in cards)


class _InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


def test_driver_hands_the_retriever_to_the_planner_end_to_end():
    """端到端：驱动器真的把检索器交给 Planner，而不是只写了个参数。"""
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.offline import OfflineTransport
    from block_director.layer6_audit.audit_logger import AuditLogger

    transport = OfflineTransport()
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script="INT. 咖啡馆 - 日\n\n两人争吵，机位越过轴线。\n",
                          knowledge=retriever(), thread_factory=_InlineThread)
    driver.run_to_completion()

    plan_prompt = transport.last_payload.messages[0].content \
        if transport.last_payload else ""
    assert "参考资料" in plan_prompt and "[axis_cross]" in plan_prompt
    assert driver.snapshot()["knowledge"]["backend"] == "bm25"


def test_driver_without_knowledge_still_runs():
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.offline import OfflineTransport
    from block_director.layer6_audit.audit_logger import AuditLogger

    driver = PrevisDriver(transport=OfflineTransport(), audit=AuditLogger(),
                          script="INT. 房间 - 日\n", thread_factory=_InlineThread)
    driver.run_to_completion()
    assert driver.snapshot()["knowledge"] is None


def test_repair_payload_advertises_search_knowledge():
    """§6.5 第三条时机：运行中按需——修复回合的工具单里必须有它。"""
    from block_director.contracts.audit import AuditError, AuditResult
    from block_director.layer5_orchestrator.repair import build_repair_payload

    registry = ToolRegistry()
    register_knowledge_tools(registry, retriever())
    audit = AuditResult(passed=False, errors=[
        AuditError(rule="R001", code="E_AXIS_001", message="越轴",
                   severity="error", target="shot_001",
                   suggestion="同侧机位")])
    payload = build_repair_payload(audit, registry, scene_state="（略）")
    names = [tool["function"]["name"] for tool in payload.tools]
    assert "search_knowledge" in names
