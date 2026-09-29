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
from ..contracts.knowledge import Card
from .bm25 import make_bm25, ranked, tokenize
from .corpus import CARDS, DOMAIN_LABELS, DOMAINS, cards_by_domain, digest_cards
from .generated import ID_PREFIX as GENERATED_ID_PREFIX

TOKEN_LIMIT_TOOL = 800      # §6.5：search_knowledge 单次返回上限
TOKEN_LIMIT_PLAN = 2000     # §6.5：阶段 A 预取上限
LATIN_CHARS_PER_TOKEN = 4.0
RRF_K = 60                  # 倒数排名融合常数（§6.4 的 rrf_merge）
TRUNCATION_NOTE = "\n…（已按 token 上限截断）"


def estimate_tokens(text: str) -> int:
    """确定性 token 估算：CJK 字符 1 token，拉丁文 4 字符 1 token。"""
    cjk = 0
    other = 0
    for char in text or "":
        if "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff":
            cjk += 1
        else:
            other += 1
    return int(cjk + other / LATIN_CHARS_PER_TOKEN + 0.999)


def truncate_to_tokens(text: str, limit: int) -> str:
    """按估算 token 截断文本；超限时补一句说明，便于模型知道内容不完整。"""
    if limit <= 0 or estimate_tokens(text) <= limit:
        return text
    budget = max(limit - estimate_tokens(TRUNCATION_NOTE), 1)
    kept: List[str] = []
    used = 0
    for line in text.splitlines():
        cost = estimate_tokens(line) + 1
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    if not kept:                        # 单行就超限：按字符硬截
        kept = [text[: max(budget * 2, 40)]]
    return "\n".join(kept) + TRUNCATION_NOTE


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
    #: v1.4 §2.4：检索调用与 ``llm_calls`` **分列**记账。
    retrieval_calls: int = 0
    warnings: List[str] = field(default_factory=list)
    #: v1.4 §2.3：**降级必须留痕**——``knowledge_trace.json`` 里的
    #: ``degraded`` / ``degraded_reason`` 由它产出（否则那是死字段）。
    degraded: bool = False
    degraded_reason: str = ""
    #: v1.4 §2.3：最近一次检索的 trace（查询串、种子、命中边、打分、注入集合）。
    last_trace: Dict[str, Any] = field(default_factory=dict)
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

        response = self.client.retrieve_or_none(query, top_k=limit)
        self.retrieval_calls = int(getattr(self.client, "retrieval_calls", 0) or 0)
        if response is None:
            self.degraded = True
            self.degraded_reason = (getattr(self.client, "degraded_reason", "")
                                    or "sidecar_unavailable")
            self.warnings.append(
                "sidecar 检索不可达，本次退回卡片检索并在 knowledge_trace 记 degraded")
            return []
        self.last_trace = dict(response.trace or {})
        return to_internal_edges(response.edges)

    def edge_block(self, query: str, *, top_k: Optional[int] = None,
                   token_limit: Optional[int] = None,
                   title: str = "硬约束（禁/许）") -> str:
        """按 §2.3 的**原子注入**渲染超边：装不下就整条丢弃，绝不截断。

        ``render_edges`` 返回 ``(text, dropped_edge_ids, quality_fail)``；
        后两者按 ``shot_scope`` / ``plan_scope`` 分列记进 trace（T5）。
        """
        from .hypergraph import render_edges

        edges = self.hypergraph_edges(query, top_k=top_k,
                                      token_limit=token_limit)
        if not edges:
            return ""
        nodes = getattr(self.hypergraph, "nodes", None) or {}
        text, dropped, quality_fail = render_edges(
            edges, nodes, token_limit=int(token_limit or self.token_limit))
        scope = "shot_scope" if token_limit == self.token_limit else "plan_scope"
        self.last_trace.setdefault(scope, {})["dropped_edge_ids"] = list(dropped)
        self.last_trace.setdefault(scope, {})["quality_fail"] = bool(quality_fail)
        self.last_trace["degraded"] = bool(self.degraded)
        self.last_trace["degraded_reason"] = self.degraded_reason
        return f"【{title}】\n{text}" if text else ""

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
            edges = self.edge_block(script_digest, top_k=max(self.top_k, 8),
                                    token_limit=limit)
            # 超边之外再补一点卡片正文（§2.3：超边优先、卡片补充）。
            cards = self.block(script_digest, top_k=4, token_limit=limit)
            if edges and cards:
                return edges + "\n\n【卡片正文补充】\n" + cards
            return edges or cards
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
            edges = self.edge_block(query, top_k=self.top_k,
                                    token_limit=limit)
            cards = self.block(query, top_k=self.top_k, token_limit=limit)
            if edges and cards:
                return edges + "\n\n【卡片正文补充】\n" + cards
            return edges or cards
        if not self.cards:
            return ""
        query = " ".join([shot_type or "", intent or "",
                          " ".join(action_types or ())])
        if not query.strip():
            return self.digest_block(limit)
        return self.block(query, top_k=self.top_k, token_limit=limit)


_DEFAULT: Optional[KnowledgeRetriever] = None


def default_retriever(backend: RagBackend = RagBackend.BM25,
                      capabilities: Iterable[str] = (),
                      top_k: int = 5,
                      token_limit: int = TOKEN_LIMIT_TOOL,
                      plan_token_limit: int = TOKEN_LIMIT_PLAN,
                      hypergraph: Optional[Any] = None,
                      client: Optional[Any] = None) -> KnowledgeRetriever:
    """进程级默认检索器（语料是静态的，默认参数下构建一次即可）。

    带了非默认参数时**不缓存**：否则第二次用不同配置调用会拿到上一份配置的
    检索器，属于典型的"缓存住错配置"缺陷。
    """
    global _DEFAULT
    if (backend is RagBackend.BM25 and not capabilities and top_k == 5
            and token_limit == TOKEN_LIMIT_TOOL
            and plan_token_limit == TOKEN_LIMIT_PLAN and hypergraph is None
            and client is None):
        if _DEFAULT is None:
            _DEFAULT = KnowledgeRetriever(cards=cards_in_domain_order())
        return _DEFAULT
    return KnowledgeRetriever(
        cards=cards_in_domain_order(), backend=backend,
        capabilities=capabilities, top_k=top_k, token_limit=token_limit,
        plan_token_limit=plan_token_limit, hypergraph=hypergraph,
        client=client)


def reset_default_retriever() -> None:
    """测试用：清掉进程级默认检索器。"""
    global _DEFAULT
    _DEFAULT = None
