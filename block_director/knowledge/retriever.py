"""知识检索器（执行文档 v1.2 §6.1 / §6.4 / §6.5）。

后端选择是**确定性**的，没有"看情况"：

1. ``rag.backend = bm25``（默认）→ BM25；
2. ``rag.backend = vector`` → 必须由传输层的 ``capabilities`` 确认可用，
   否则**降级为 bm25 并留下告警**（绝不静默失败）；
3. ``rag.enabled = false`` → 走 digest，把五张顶层摘要卡直接注入。

token 计数用 §6.5 的上限（按需 800 / 计划预取 2000）。Blender 自带 Python
没有 tokenizer，这里用**文档化的确定性估算**：CJK 字符按 1 token，拉丁文按
4 字符 1 token。它只用来裁剪注入长度，不参与计费。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..contracts.enums import RagBackend
from ..contracts.knowledge import Card, Case
from .bm25 import make_bm25, ranked, tokenize
from .cases import CASE_COLUMN_TITLE, CaseIndex, render_cases
from .corpus import CARDS, DOMAIN_LABELS, DOMAINS, cards_by_domain, digest_cards
from .generated import ID_PREFIX as GENERATED_ID_PREFIX
#: v1.4 §2.3d T5：token 估算的**单一真源**在 `tokens.py`——案例通道（`cases.py`）
#: 用的是同一个函数对象，两条通道不可能各算一套。这里的再导出保持既有 API。
from .tokens import (
    LATIN_CHARS_PER_TOKEN,
    TRUNCATION_NOTE,
    estimate_tokens,
    truncate_to_tokens,
)

TOKEN_LIMIT_TOOL = 800      # §6.5：search_knowledge 单次返回上限
TOKEN_LIMIT_PLAN = 2000     # §6.5：阶段 A 预取上限
RRF_K = 60                  # 倒数排名融合常数（§6.4 的 rrf_merge）

#: 人工撰写卡相对生成卡的优先级系数（v1.5）。人工卡是**人工审阅过的规范答案**，
#: 生成卡是"从语料里抽出来的候选"：两者分数接近时应当由人工卡胜出，否则语料
#: 一长大，`comp_thirds` / `axis_cross` 这类旗舰卡就会被同主题的生成卡挤出首位
#: （实测：`越轴` 上 axis_cross 15.01 对生成卡 17.04，差 13.6%；`三分法 构图`
#: 上 comp_thirds 25.14 对 25.91，差 3%）。15% 以内视为并列；超过 15% 说明
#: 生成卡确实更贴题，此时不抢它的位置。
CURATED_BOOST = 1.15


def curated_priority(scored: Sequence, cards: Sequence[Card]) -> List:
    """给人工撰写卡一个**有界**的分数加成后重新排序。

    只改跨档比较：同档之间顺序不变（BM25 分是首位，下标是稳定的次序键）。
    """
    boosted = [
        (index, score * CURATED_BOOST
         if not str(cards[index].id).startswith(GENERATED_ID_PREFIX) else score)
        for index, score in scored
    ]
    boosted.sort(key=lambda item: (-item[1], item[0]))
    return boosted


def rrf_merge(vector_hits: Sequence[int], keyword_hits: Sequence[int],
              k: int = RRF_K) -> List[int]:
    """倒数排名融合（§6.4）：把两路召回合成一路有序下标。"""
    scores: Dict[int, float] = {}
    for hits in (vector_hits, keyword_hits):
        for rank, index in enumerate(hits):
            scores[index] = scores.get(index, 0.0) + 1.0 / (k + rank + 1)
    return [index for index, _ in
            sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def _trace_to_dict(trace) -> Dict[str, Any]:
    """把超图的 ``RetrievalTrace`` 转成可落盘的字典（没有则空字典）。"""
    if trace is None:
        return {}
    if hasattr(trace, "to_dict"):
        return dict(trace.to_dict())
    return dict(trace) if isinstance(trace, dict) else {}


@dataclass
class RetrievalHit:
    card: Card
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.card.id, "domain": self.card.domain,
                "title": self.card.title, "score": round(self.score, 4)}


def cards_in_domain_order() -> List[Card]:
    """全部语料（按域顺序排列，便于阅读与测试）。"""
    ordered: List[Card] = []
    for domain in DOMAINS:
        ordered.extend(cards_by_domain(domain))
    return ordered


@dataclass
class KnowledgeRetriever:
    """BM25（默认）/ 向量增强 / digest 兜底三合一检索器。"""

    cards: Sequence[Card] = field(default_factory=lambda: CARDS)
    backend: RagBackend = RagBackend.BM25
    top_k: int = 5
    token_limit: int = TOKEN_LIMIT_TOOL
    #: v1.4 §2.3：整场预取（``block_for_plan``）的独立预算。缺省沿用
    #: 800——调用方（headless / 面板）应从 ``rag.plan_prefetch_tokens`` 传进来。
    plan_token_limit: int = TOKEN_LIMIT_PLAN
    capabilities: Iterable[str] = ()
    vector_store: Optional[Any] = None
    #: v1.4 §2.3：超图索引（由 sidecar 提供）。没有它就只能降级。
    hypergraph: Optional[Any] = None
    #: v1.4 §2.3：sidecar 知识客户端。**有它就不需要在进程里装索引**——
    #: 三条通道（cards/edges/cases）由 ``/v1/retrieve`` 一次带回。
    client: Optional[Any] = None
    #: v1.4 §2.3b：L3 案例索引（进程内备选）。装了 client 时案例由
    #: ``/v1/retrieve`` 带回；没有 client 时才用它。
    cases_index: Optional[Any] = None
    #: v1.4 §2.3b／§3.2：L3 的开与关**只由 ``rag.cases_backend`` 表达**。
    #: ``off`` ＝ 用户显式关闭：第三栏恒空、**不向 sidecar 索要案例**、
    #: 也不算降级（与 :class:`~block_director.knowledge.cases.CaseIndex`
    #: 的 off 语义逐字一致）。在此之前这个配置键没有任何消费者。
    cases_backend: str = "lightrag"
    #: v1.4 §3.2：``rag.cases_top_k`` —— 注入到「仅参考」栏的案例条数。
    cases_top_k: int = 3
    #: v1.4 §2.4：检索调用与 ``llm_calls`` **分列**记账。
    retrieval_calls: int = 0
    warnings: List[str] = field(default_factory=list)
    #: v1.4 §2.3：**降级必须留痕**——``knowledge_trace.json`` 里的
    #: ``degraded`` / ``degraded_reason`` 由它产出（否则那是死字段）。
    degraded: bool = False
    degraded_reason: str = ""
    #: v1.4 §2.3：最近一次检索的 trace（查询串、种子、命中边、打分、注入集合）。
    last_trace: Dict[str, Any] = field(default_factory=dict)
    #: v1.4 §2.3b：最近一次检索带回来的**参考案例**（第三栏的数据源）。
    #: 记下它是为了让"硬约束"与"参考案例"共用**同一次** ``/v1/retrieve``，
    #: 而不是各发一次（那会把 §2.4 的 ``retrieval_calls`` 账算成两倍）。
    last_cases: List[Any] = field(default_factory=list)
    #: 上一段案例属于哪条查询（查询变了就必须重取，绝不把 A 的案例贴到 B 上）。
    #: 初值 ``None`` 表示"这一次查询还没取过 bundle"——用空串当哨兵会与
    #: 真正的空查询混淆。取过之后就记下查询串，**空结果也算取过**
    #: （否则同一条查询会被反复重取，§2.4 的 ``retrieval_calls`` 直接翻倍）。
    last_cases_query: Optional[str] = None
    #: E2 溯源（2026-10-01）：**最近一次**注入的超边（去掉了因预算被整条丢弃的），
    #: 交付层用它把 ``movements[].source`` 写成 ``theory`` / ``lesson`` 等。
    #: 必须在**同一次**检索里留下来——再查一次会把 §2.4 的 ``retrieval_calls``
    #: 记账翻倍（RK-18 会红），而 E2 只是诊断量，不值得拿预算账换。
    last_edges: List[Any] = field(default_factory=list)
    #: 上面那批边属于哪条查询（查询不同就不许把 A 的溯源贴到 B 上）。
    last_edges_query: str = ""
    _index_cards: List[Card] = field(default_factory=list, init=False, repr=False)
    _engine_name: str = field(default="builtin.BM25Okapi", init=False, repr=False)
    _cache: Dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    #: 请求的后端（降级前）。降级之后仍然能看出"用户要的是超图"，
    #: 供 ``knowledge_trace.json`` 记录。
    requested_backend: RagBackend = field(default=RagBackend.BM25,
                                          init=False, repr=False)

    def __post_init__(self) -> None:
        self.cards = list(self.cards)
        self.capabilities = {str(item) for item in (self.capabilities or ())}
        requested = self.backend
        # 未识别的取值只能落成 `degraded_reason`，不能让构造直接抛崩——
        # 配置是外部输入，检索器要给一条可读的告警并降级（见 resolve_backend）。
        self.requested_backend = (requested if isinstance(requested, RagBackend)
                                  else RagBackend.BM25)
        self.backend = self.resolve_backend(requested)
        self._cache = {}
        self._engine(self.cards)          # 预热，顺便确定实现名

    # ------------------------------------------------------------ 选择逻辑
    def resolve_backend(self, requested: RagBackend) -> RagBackend:
        try:
            requested = RagBackend(str(requested))
        except ValueError:
            # v1.4 §2.3：**未识别的 backend 不许静默回退**——显式记一条
            # 告警并置 degraded，否则 trace 里的 degraded 永远是死字段。
            self.warnings.append(
                f"未知的 rag.backend 取值 {requested!r}：已降级为 bm25")
            self.degraded = True
            self.degraded_reason = f"unknown_backend:{requested}"
            return RagBackend.BM25
        if requested is RagBackend.DIGEST:
            return RagBackend.DIGEST
        if requested is RagBackend.HYPERGRAPH:
            if self.client is not None or (
                    "hypergraph" in self.capabilities
                    and self.hypergraph is not None):
                return RagBackend.HYPERGRAPH
            self.warnings.append(
                "配置要求超图检索，但传输层未确认 hypergraph 能力（或索引不可用）："
                "已降级为 bm25 卡片检索，并在 knowledge_trace 里记 degraded=true")
            self.degraded = True
            self.degraded_reason = "hypergraph_unavailable"
            return RagBackend.BM25
        if requested is RagBackend.VECTOR:
            if "vector" in self.capabilities and self.vector_store is not None:
                return RagBackend.VECTOR
            self.warnings.append(
                "配置要求向量检索，但传输层未确认 vector 能力：已降级为 bm25")
            self.degraded = True
            self.degraded_reason = "vector_unavailable"
            return RagBackend.BM25
        return RagBackend.BM25

    @property
    def engine_name(self) -> str:
        return self._engine_name

    def describe(self) -> Dict[str, Any]:
        """给调试面板与 /health 的自述信息。"""
        return {"backend": str(self.backend), "engine": self.engine_name,
                "cards": len(self.cards), "top_k": self.top_k,
                "token_limit": self.token_limit,
                "plan_token_limit": self.plan_token_limit,
                "retrieval_calls": int(self.retrieval_calls),
                "degraded": bool(self.degraded),
                "degraded_reason": self.degraded_reason,
                **self.cases_info(),
                "warnings": list(self.warnings)}

    def trace_payload(self) -> Dict[str, Any]:
        """``knowledge_trace.json`` 的内容（v1.4 §2.3 / §3.3）。

        每次运行必写：查询串、种子、扩展到的超边、逐条打分、最终注入集合、
        后端、以及**降级留痕**。没有走超图时也返回一份（``backend`` 会写明
        实际用的是谁），这样"这次到底查了什么"永远有据可查。
        """
        payload: Dict[str, Any] = {
            "backend": str(self.backend),
            "requested_backend": str(self.requested_backend),
            "degraded": bool(self.degraded),
            "degraded_reason": self.degraded_reason,
            "cards": len(self.cards),
            "top_k": self.top_k,
            "token_limits": {"shot": self.token_limit,
                             "plan": self.plan_token_limit},
            #: §2.4：检索调用与 llm_calls 分列，别混进同一个计数器。
            "retrieval_calls": int(self.retrieval_calls),
            "warnings": list(self.warnings),
        }
        payload.update(self.last_trace or {})
        #: L3 分节**最后写**：`cases_backend=off` 是本地决定，必须压得住
        #: sidecar 响应里的 `cases_backend`（否则"用户关了"会被上游的
        #: "hybrid" 覆盖，trace 与实跑对不上）。
        payload.update(self.cases_info())
        payload.setdefault("shot_scope", {})
        payload.setdefault("plan_scope", {})
        return payload

    # ------------------------------------------------------------ 检索
    @staticmethod
    def _searchable(card: Card) -> str:
        # 生成卡的检索面 = `id + title + content`：模型自写的关键词没有经过人工审阅，
        # 实测会把生成卡抬到人工撰写的专题卡之前（P14-1 的回归：`comp_thirds` 与
        # `axis_cross` 都被挤出首位）。关键词仍留在卡片产物里，只是不参与排序。
        parts = [card.id, card.title, card.content]
        if not card.id.startswith(GENERATED_ID_PREFIX):
            parts += [" ".join(card.keywords), " ".join(card.rules),
                      " ".join(card.examples), " ".join(card.related),
                      " ".join(str(value) for value in card.parameters.values())]
        return "\n".join(part for part in parts if part)

    def _engine(self, cards: Sequence[Card]):
        """按候选集合建/取缓存索引（域过滤时只需建一次）。"""
        key = "|".join(card.id for card in cards)
        if key not in self._cache:
            documents = [tokenize(self._searchable(card)) for card in cards]
            self._cache[key] = make_bm25(documents)
        engine, name = self._cache[key]
        self._engine_name = name
        return engine

    def retrieve(self, query: str, domain: Optional[str] = None,
                 top_k: Optional[int] = None) -> List[Card]:
        return [hit.card for hit in self.search_hits(query, domain, top_k)]

    def search_hits(self, query: str, domain: Optional[str] = None,
                    top_k: Optional[int] = None) -> List[RetrievalHit]:
        if self.backend is RagBackend.DIGEST:
            return [RetrievalHit(card, 0.0) for card in self._digest_cards(domain)]

        limit = int(top_k or self.top_k)
        candidates = list(self.cards)
        if domain:
            if domain not in DOMAINS:
                self.warnings.append(f"未知知识域 {domain}：已忽略域过滤")
            else:
                candidates = [card for card in candidates
                              if card.domain == domain]
        if not candidates:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        engine = self._engine(candidates)
        scored = ranked(engine, tokens, 0)
        # 人工卡优先：只把分数**接近**的生成卡挤到后面（见 CURATED_BOOST）。
        scored = curated_priority(scored, candidates)
        keyword_order = [index for index, score in scored if score > 0]

        if self.backend is RagBackend.VECTOR and self.vector_store is not None:
            vector_order = self._vector_order(query, limit)
            order = rrf_merge(vector_order, keyword_order)[:limit]
            score_of = {index: score for index, score in scored}
            return [RetrievalHit(candidates[index], float(score_of.get(index, 0.0)))
                    for index in order]

        return [RetrievalHit(candidates[index], score)
                for index, score in scored[:limit] if score > 0]

    # ------------------------------------------------------- v1.4 §2.3 超图
    def hypergraph_edges(self, query: str, *, top_k: Optional[int] = None,
                         token_limit: Optional[int] = None
                         ) -> List[Any]:
        """走超图索引取**整条**超边（含全部 ``forbid`` 成员）。

        返回 ``[]`` 表示没有可用索引/没有命中——调用方据此决定是否退回卡片。
        过程写进 :attr:`last_trace`，供 ``knowledge_trace.json`` 落盘。

        v1.4 §2.3 的**首选路径是 sidecar**：装了 :attr:`client` 时，超边由
        ``/v1/retrieve`` 拿回（插件进程里不需要索引）；进程内的
        :attr:`hypergraph` 只是没有 sidecar 时的备选。
        """
        if self.backend is not RagBackend.HYPERGRAPH:
            return []
        limit = int(top_k or self.top_k)
        if self.client is not None:
            return self._edges_from_client(query, limit)
        if self.hypergraph is None:
            return []
        try:
            edges, _text, trace = self.hypergraph.retrieve(
                query, top_k=limit,
                token_limit=int(token_limit or self.token_limit))
        except Exception as exc:  # noqa: BLE001 - 超图侧失败不该拖垮整场
            self.warnings.append(f"超图检索失败，已退回卡片：{exc}")
            self.degraded = True
            self.degraded_reason = f"hypergraph_error:{type(exc).__name__}"
            return []
        self.last_trace = _trace_to_dict(trace)
        return list(edges or [])

    def _edges_from_client(self, query: str, limit: int) -> List[Any]:
        """经 sidecar 取超边；不可达时**降级留痕**，不拖垮整场。"""
        from .client import to_internal_edges

        response = self.client.retrieve_or_none(query, top_k=limit,
                                                cases_top_k=self._cases_request())
        self.retrieval_calls = int(getattr(self.client, "retrieval_calls", 0) or 0)
        if response is None:
            self.degraded = True
            self.degraded_reason = (getattr(self.client, "degraded_reason", "")
                                    or "sidecar_unavailable")
            self.warnings.append(
                "sidecar 检索不可达，本次退回卡片检索并在 knowledge_trace 记 degraded")
            return []
        self.last_trace = dict(response.trace or {})
        #: §2.3b 的第三栏与硬约束**共用这一次调用**（再发一次会让 §2.4 的
        #: `retrieval_calls` 账翻倍）。案例在这里缓存，`case_block()` 直接取。
        #: 只留**真要注入**的条数（`rag.cases_top_k`）；`off` 时是空——
        #: `cases_info()["cases"]` 报的就是"这一次实际拿到的参考案例条数"。
        requested = self._cases_request()
        self.last_cases = list(response.cases or [])[:requested] if requested else []
        self.last_cases_query = query
        return to_internal_edges(response.edges)

    # ------------------------------------------------- v1.4 §2.3b L3 案例（第三栏）
    def _cases_request(self) -> int:
        """向 sidecar 索要的案例条数（``cases_backend=off`` 时是 **0**）。

        关掉时**根本不发这个请求**——不是"要回来再丢掉"：后者会让 §2.4 的
        ``retrieval_calls`` 与 sidecar 的实际工作量与配置不符。
        """
        if str(self.cases_backend) == "off":
            return 0
        return max(1, int(self.cases_top_k or 1))

    def cases_for(self, query: str, *, top_k: Optional[int] = None) -> List[Any]:
        """取这条查询的参考案例（L3）。

        优先级与超图一致：**sidecar 带回的**（已经在上一次 ``/v1/retrieve``
        里拿到就直接用）→ 进程内的 :attr:`cases_index` → 空。
        """
        if str(self.cases_backend) == "off":
            return []                     # §2.3b：显式关闭 → 恒空，且不算降级
        limit = max(1, int(top_k or self.cases_top_k or 1))
        if self.last_cases_query is not None and self.last_cases_query == query:
            return list(self.last_cases)[:limit]
        if self.client is not None and self.backend is RagBackend.HYPERGRAPH:
            response = self.client.retrieve_or_none(query, top_k=self.top_k,
                                                    cases_top_k=limit)
            self.retrieval_calls = int(getattr(self.client, "retrieval_calls", 0) or 0)
            if response is None:
                self.degraded = True
                self.degraded_reason = (getattr(self.client, "degraded_reason", "")
                                        or "sidecar_unavailable")
                return []
            self.last_trace = dict(response.trace or {})
            self.last_cases = list(response.cases or [])[:limit]
            self.last_cases_query = query
            return list(self.last_cases)[:limit]
        if isinstance(self.cases_index, CaseIndex):
            hits = self.cases_index.retrieve(query, top_k=limit)
            self.last_cases = list(hits)
            self.last_cases_query = query
            return list(hits)[:limit]
        return []

    @property
    def cases_enabled(self) -> bool:
        """L3 这条通道这次是否真的开着（决定 §2.4 的 ``lanes``）。"""
        if str(self.cases_backend) == "off":
            return False
        if isinstance(self.cases_index, CaseIndex):
            return bool(self.cases_index.enabled)
        trace = self.last_trace or {}
        if self.client is not None and trace:
            return int(trace.get("lanes", 1) or 1) >= 2
        return bool(self.last_cases)

    def cases_info(self) -> Dict[str, Any]:
        """``knowledge_trace.json`` 里的 L3 分节（§2.3b：每次运行必记）。"""
        if str(self.cases_backend) == "off":
            # 用户显式关闭：如实记 off + 单通道 + **不是降级**（E1/E3 记
            # not_measured 是判据侧的事，这里只描述"这次跑的是什么"）。
            return {
                "cases": 0,
                "lanes": 1,
                "cases_backend": "off",
                "cases_requested_backend": "off",
                "cases_degraded": False,
                "cases_degraded_reason": "",
                "lightrag_index_fingerprint": "",
                "cases_index_fingerprint": "",
            }
        trace = dict(self.last_trace or {})
        index = self.cases_index if isinstance(self.cases_index, CaseIndex) else None
        if not trace and index is not None:
            trace = index.describe()
        return {
            "cases": len(self.last_cases),
            "lanes": 2 if self.cases_enabled else 1,
            "cases_backend": str(trace.get(
                "cases_backend", index.effective if index else "off")),
            "cases_requested_backend": str(trace.get(
                "cases_requested_backend", index.requested if index else "off")),
            "cases_degraded": bool(trace.get(
                "cases_degraded", index.degraded if index else False)),
            "cases_degraded_reason": str(trace.get(
                "cases_degraded_reason", index.reason if index else "")),
            "lightrag_index_fingerprint": str(
                trace.get("lightrag_index_fingerprint", "")),
            "cases_index_fingerprint": str(
                trace.get("cases_index_fingerprint",
                          index.fingerprint if index else "")),
        }

    def case_block(self, query: str, *, top_k: Optional[int] = None,
                   token_limit: Optional[int] = None,
                   title: str = CASE_COLUMN_TITLE,
                   scope: str = "shot",
                   budgets: Optional[Dict[str, int]] = None) -> str:
        """§2.3b 的第三栏「参考案例（仅参考）」。

        **原子注入**：一条案例装不下就整条丢弃并写 ``dropped_case_ids``，
        绝不截断——截断会把"出处"切掉，模型就分不清"某人的经验"与"规则"。
        ``top_k`` 缺省时取 :attr:`cases_top_k`（``rag.cases_top_k`` 的接线点）；
        :attr:`cases_backend` 为 ``off`` 时**整栏不产出**。
        """
        if str(self.cases_backend) == "off":
            return ""
        top_k = int(top_k or self.cases_top_k or 3)
        cases = self.cases_for(query, top_k=top_k)
        self._record_budget(scope, budgets)
        if not cases:
            return ""
        limit = int(budgets["remaining"] if budgets
                    else (token_limit or self.token_limit))
        text, dropped = render_cases(cases, max(limit, 0), title=title)
        section = self.last_trace.setdefault(f"{scope}_scope", {})
        section["dropped_case_ids"] = list(dropped)
        section.setdefault("columns", {})
        section["columns"]["cases"] = len(cases) - len(dropped)
        section["columns"]["case_tokens"] = estimate_tokens(text)
        #: 预算的**扣减**由调用方（`_hypergraph_block` 的 `_take`）负责：
        #: 在这里扣一次、调用方再扣一次＝双重记账，三栏的实际体积会比预算小
        #: 得多（而且和 trace 里的数字对不上）。
        return text

    def _record_budget(self, scope: str, budgets: Optional[Dict[str, int]]) -> None:
        if budgets is None:
            return
        section = self.last_trace.setdefault(f"{scope}_scope", {})
        section.setdefault("columns", {})["budget"] = int(
            budgets.get("limit", budgets.get("remaining", 0)))

    @staticmethod
    def _fits(budgets: Dict[str, int], text: str, columns: Sequence[str]) -> bool:
        """这一栏（**含**与前一栏之间的空行）还装得下吗？"""
        if not text:
            return False
        cost = estimate_tokens(text) + (2 if columns else 0)
        return cost <= budgets["remaining"]

    def _take(self, budgets: Dict[str, int], text: str,
              columns: Sequence[str]) -> str:
        """把这一栏（含空行）记进共享预算；装不下就整栏不注入。"""
        if not self._fits(budgets, text, columns):
            return ""
        budgets["remaining"] = max(
            0, budgets["remaining"] - estimate_tokens(text)
            - (2 if columns else 0))
        return text

    def edge_block(self, query: str, *, top_k: Optional[int] = None,
                   token_limit: Optional[int] = None,
                   title: str = "硬约束（禁/许）",
                   scope: str = "shot",
                   budgets: Optional[Dict[str, int]] = None) -> str:
        """按 §2.3 的**原子注入**渲染超边：装不下就整条丢弃，绝不截断。

        ``render_edges`` 返回 ``(text, dropped_edge_ids, quality_fail)``；
        后两者按 ``shot_scope`` / ``plan_scope`` 分列记进 trace（T5）。
        """
        hard, _soft = self.edge_columns(query, top_k=top_k,
                                        token_limit=token_limit, scope=scope,
                                        budgets=budgets, hard_title=title)
        return hard

    def edge_columns(self, query: str, *, top_k: Optional[int] = None,
                     token_limit: Optional[int] = None, scope: str = "shot",
                     budgets: Optional[Dict[str, int]] = None,
                     hard_title: str = "硬约束（禁/许）",
                     soft_title: str = "经验建议（软）") -> tuple:
        """按 §2.3b 的**关键纪律 2** 把超边分成两栏：硬约束 ／ 经验建议（软）。

        软边（``hardness == "soft"``，例如 ``source_kind = experience``）**不得**
        与硬约束同栏呈现——同一栏会让模型把"某人经验"当成"必须遵守"。
        返回 ``(硬栏目文本, 软栏目文本)``（**不含**栏目标题）。
        """
        from .hypergraph import render_edges

        self._record_budget(scope, budgets)
        budget = int((budgets["remaining"] if budgets
                      else token_limit) or self.token_limit)
        edges = self.hypergraph_edges(query, top_k=top_k, token_limit=budget)
        nodes = getattr(self.hypergraph, "nodes", None) or {}
        # 分栏判据：**带 `forbid` 成员的边永远进硬约束栏**。`hardness == "soft"`
        # 只是"它是软先验"，但一条**禁忌**不是建议——把它放进「仅参考」那一栏，
        # 模型就有理由照样做（Q7 的拦截率就是这么丢的）。索引里实测存在
        # 1 条 `hardness=soft` 且带 `forbid` 的边，所以这不是假想情况。
        def _is_soft(edge) -> bool:
            if str(getattr(edge, "hardness", "hard")) != "soft":
                return False
            return not any(str(getattr(member, "role", "")) == "forbid"
                           for member in getattr(edge, "members", ()))

        hard = [edge for edge in edges if not _is_soft(edge)]
        soft = [edge for edge in edges if _is_soft(edge)]
        # §2.3b 的关键纪律 2：**同一组成员**若同时以 hard 与 soft 出现（抽取器
        # 跨批把同一条理论边标成了两种硬度，索引里实测有 168 组），硬的那条已经
        # 说了同样的话。再把软的那条放进「经验建议」栏，等于同一句话既"必须遵守"
        # 又"仅供参考"——模型只会照软的做。取硬边，并把条数记进 trace 供审计。
        hard_keys = {edge.norm_key for edge in hard}
        suppressed_soft = [edge for edge in soft if edge.norm_key in hard_keys]
        soft = [edge for edge in soft if edge.norm_key not in hard_keys]
        hard_text, dropped_hard, fail_hard = render_edges(hard, nodes, budget)
        # 栏目标题也算注入体积——不把它计进预算，"≤800 token"会悄悄超发。
        hard_column = f"【{hard_title}】\n{hard_text}" if hard_text else ""
        if budgets is not None and hard_column:
            if not self._fits(budgets, hard_column, ()):
                hard_column = ""                       # 标题都装不下就整栏不要
            else:
                self._take(budgets, hard_column, ())
        remaining = max(0, budget - estimate_tokens(hard_column))
        soft_raw, dropped_soft, fail_soft = render_edges(soft, nodes, remaining)
        soft_column = ""
        if soft_raw:
            candidate = f"【{soft_title}】\n{soft_raw}"
            soft_column = (candidate if budgets is None
                           else self._take(budgets, candidate, (hard_column,)))
        section = self.last_trace.setdefault(f"{scope}_scope", {})
        section["dropped_edge_ids"] = list(dropped_hard) + list(dropped_soft)
        section["quality_fail"] = bool(fail_hard or fail_soft)
        section.setdefault("columns", {})
        section["columns"].update({"hard_edges": len(hard),
                                   "soft_edges": len(soft),
                                   "suppressed_soft_edges": len(suppressed_soft),
                                   "hard_tokens": estimate_tokens(hard_column),
                                   "soft_tokens": estimate_tokens(soft_column)})
        # E2 溯源：只留**真的注入了**的边（被预算整条丢掉的不算"检索命中"）。
        dropped = set(dropped_hard) | set(dropped_soft)
        self.last_edges_query = str(query)
        self.last_edges = [edge for edge in edges
                           if getattr(edge, "edge_id", "") not in dropped]
        self.last_trace["degraded"] = bool(self.degraded)
        self.last_trace["degraded_reason"] = self.degraded_reason
        return hard_column, soft_column

    def provenance(self, query: Optional[str] = None) -> Dict[str, List[List[str]]]:
        """最近一次注入的超边按 ``source_kind`` 归类的 ``(kind, value)`` 清单。

        v1.4 §3.3 的 ``movements[].source`` 只能取 R46 的六个取值
        （``declared|planned|theory|experience|lesson|case``）；E2（经验采纳率）
        数的就是其中 ``experience|lesson|case`` 那几个。**在此之前 manifest
        永远只写 ``declared|planned``**——E2 因此结构性恒为 0（审查 #21：
        "有指标没数据"）。这里提供的是"这条具体取值是哪一类知识带回来的"，
        由 ``delivery/manifest.py::_movements_payload`` 消费。

        传了 ``query`` 且与最近一次不同则返回空表：**绝不**把上一条查询的
        命中贴到这一条上（那会把溯源变成编造）。
        """
        if query is not None and str(query) != self.last_edges_query:
            return {}
        out: Dict[str, List[List[str]]] = {}
        for edge in self.last_edges:
            kind_of_source = str(getattr(edge, "source_kind", "") or "theory")
            bucket = out.setdefault(kind_of_source, [])
            for member in getattr(edge, "members", ()) or ():
                if str(getattr(member, "role", "")) == "forbid":
                    # 禁忌不是"被采纳的建议"：把它算进来等于把违反禁忌也记成采纳。
                    continue
                node = str(getattr(member, "node_id", ""))
                if ":" not in node:
                    continue
                pair = [node.split(":", 1)[0], node.split(":", 1)[1]]
                if pair not in bucket:
                    bucket.append(pair)
        return out

    def _vector_order(self, query: str,
                      limit: int) -> List[int]:  # pragma: no cover - 需 sidecar
        try:
            hits = self.vector_store.search(query, limit * 2)
        except Exception as exc:  # noqa: BLE001 - 向量侧失败不拖垮 BM25
            self.warnings.append(f"向量检索失败，已退回 bm25：{exc}")
            return []
        return [index for index, _score in hits]

    # ------------------------------------------------------------ 注入文本
    def _digest_cards(self, domain: Optional[str]) -> List[Card]:
        cards = digest_cards()
        if domain in DOMAINS:
            return [card for card in cards if card.domain == domain]
        return cards

    @staticmethod
    def render(cards: Sequence[Card]) -> str:
        """把条目渲染成提示词里的「参考资料」块。"""
        blocks: List[str] = []
        for card in cards:
            label = DOMAIN_LABELS.get(card.domain, card.domain)
            lines = [f"[{card.id}] {card.title}（{label}）", card.content]
            if card.rules:
                lines.append("关联规则：" + "、".join(card.rules))
            if card.parameters:
                rendered = "；".join(f"{key}={value}"
                                     for key, value in card.parameters.items())
                lines.append("参数：" + rendered)
            if card.examples:
                lines.append("示例：" + "；".join(card.examples))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def block(self, query: str, domain: Optional[str] = None,
              top_k: Optional[int] = None,
              token_limit: Optional[int] = None) -> str:
        """检索并渲染成 ≤token 上限的注入块。"""
        cards = self.retrieve(query, domain, top_k)
        if not cards:
            return ""
        limit = int(token_limit or self.token_limit)
        return truncate_to_tokens(self.render(cards), limit)

    def digest_block(self, limit: int = TOKEN_LIMIT_PLAN) -> str:
        """digest 兜底的注入块（五域摘要）。"""
        if not self.cards:
            return ""
        return truncate_to_tokens(self.render(self._digest_cards(None)), limit)

    # ------------------------------------------------------------ §6.5 时机
    def block_for_plan(self, script_digest: str,
                       limit: int = 0) -> str:
        """阶段 A：按剧本摘要预取（轴线 / 构图 / 摄影最常相关）。

        v1.3：top_k 从 6 提到 8。语料从 37 条扩到 130 余条之后，6 条常常
        装不下"越轴 + 构图 + 运镜"这三类同时相关的内容；token 上限仍然是
        2000，因此注入体积可控。
        """
        limit = int(limit or self.plan_token_limit or TOKEN_LIMIT_PLAN)
        if self.backend is RagBackend.DIGEST:
            return self.digest_block(limit)
        if self.backend is RagBackend.HYPERGRAPH:
            return self._hypergraph_block(script_digest, limit=limit,
                                          top_k=max(self.top_k, 8),
                                          cards_top_k=4, scope="plan")
        if not self.cards:
            return ""
        return self.block(script_digest, top_k=max(self.top_k, 8),
                          token_limit=limit)

    def block_for_shot(self, shot_type: str, intent: str = "",
                       action_types: Sequence[str] = (),
                       limit: int = 0) -> str:
        """阶段 B1：按该镜的景别 / 意图 / 动作取条目。"""
        limit = int(limit or self.token_limit or TOKEN_LIMIT_TOOL)
        if self.backend is RagBackend.DIGEST:
            return self.digest_block(limit)
        if self.backend is RagBackend.HYPERGRAPH:
            query = " ".join([shot_type or "", intent or "",
                              " ".join(action_types or ())]).strip()
            if not query:
                return self.digest_block(limit)
            return self._hypergraph_block(query, limit=limit, top_k=self.top_k,
                                          cards_top_k=self.top_k, scope="shot")
        if not self.cards:
            return ""
        query = " ".join([shot_type or "", intent or "",
                          " ".join(action_types or ())])
        if not query.strip():
            return self.digest_block(limit)
        return self.block(query, top_k=self.top_k, token_limit=limit)

    def _hypergraph_block(self, query: str, *, limit: int, top_k: int,
                          cards_top_k: int, scope: str) -> str:
        """§2.3b 的**三栏注入**：硬约束 → 经验建议（软）→ 参考案例 → 卡片补充。

        R44/Q6b 的硬约束：**三栏共用一个上限**（每镜 ``rag.max_tokens_per_call``、
        整场 ``rag.plan_prefetch_tokens``）。以前硬约束用满上限、卡片再用满一次，
        单块可以到 2×上限——那会让"注入 token ≤ 800"的判定看似通过而实为超发。
        """
        budgets = {"limit": int(limit), "remaining": int(limit)}
        hard, soft = self.edge_columns(query, top_k=top_k, token_limit=limit,
                                       scope=scope, budgets=budgets)
        columns: List[str] = []
        if hard:
            columns.append(hard)
        if soft:
            columns.append(soft)
        #: 条数来自 `rag.cases_top_k`（§3.2）；这里**不许**再写死 3。
        cases_text = self.case_block(query, scope=scope, budgets=budgets)
        if cases_text and self._take(budgets, cases_text, columns):
            columns.append(cases_text)
        if budgets["remaining"] > 0:
            remaining = max(0, budgets["remaining"] - (2 if columns else 0))
            cards = self.block(query, top_k=cards_top_k, token_limit=remaining)
            if cards:
                cards = self._take(budgets, "【卡片正文补充】\n" + cards, columns)
                if cards:
                    columns.append(cards)
        return "\n\n".join(columns)


_DEFAULT: Optional[KnowledgeRetriever] = None


def default_retriever(backend: RagBackend = RagBackend.BM25,
                      capabilities: Iterable[str] = (),
                      top_k: int = 5,
                      token_limit: int = TOKEN_LIMIT_TOOL,
                      plan_token_limit: int = TOKEN_LIMIT_PLAN,
                      hypergraph: Optional[Any] = None,
                      client: Optional[Any] = None,
                      cases_index: Optional[Any] = None,
                      cases_backend: str = "lightrag",
                      cases_top_k: int = 3) -> KnowledgeRetriever:
    """进程级默认检索器（语料是静态的，默认参数下构建一次即可）。

    带了非默认参数时**不缓存**：否则第二次用不同配置调用会拿到上一份配置的
    检索器，属于典型的"缓存住错配置"缺陷。
    """
    global _DEFAULT
    if (backend is RagBackend.BM25 and not capabilities and top_k == 5
            and token_limit == TOKEN_LIMIT_TOOL
            and plan_token_limit == TOKEN_LIMIT_PLAN and hypergraph is None
            and client is None and cases_index is None
            and cases_backend == "lightrag" and cases_top_k == 3):
        if _DEFAULT is None:
            _DEFAULT = KnowledgeRetriever(cards=cards_in_domain_order())
        return _DEFAULT
    return KnowledgeRetriever(
        cards=cards_in_domain_order(), backend=backend,
        capabilities=capabilities, top_k=top_k, token_limit=token_limit,
        plan_token_limit=plan_token_limit, hypergraph=hypergraph,
        client=client, cases_index=cases_index,
        cases_backend=str(cases_backend), cases_top_k=int(cases_top_k))


def reset_default_retriever() -> None:
    """测试用：清掉进程级默认检索器。"""
    global _DEFAULT
    _DEFAULT = None
