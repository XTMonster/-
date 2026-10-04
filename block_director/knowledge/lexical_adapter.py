"""L3 的**零依赖**适配器：精确契约匹配 → BM25 召回 →（可选）上游重排。

为什么需要它（2026-10-06 的 GitHub 复用检查 ＋ 联合会诊，ADR-0014）：
GitHub 上的超图 / GraphRAG 方案（HyperGraphRAG / LightRAG / graphrag / HippoRAG …）
**每一条都要 embedding 模型**才能建索引与检索，而本账号额度只有 `glm-5.3`
（`embedding-*` 不在包内），Blender 自带 Python 也装不了 `torch`。会诊两侧因此都指向
同一条路：**不必解 embedding**——`键=值` 查询要的是**谓词匹配**，召回面 =
"精确/别名归一化 ＋ BM25 ＋ 重排"。

它挂在**已经声明好的适配器接缝**上（`cases.register_lightrag_adapter`，
契约是 `(index_dir) -> adapter`，adapter 只须有
`retrieve(query, *, top_k, cases)`）——所以它**不改契约、不改门、不引依赖**：

* **精确层**：查询里出现的 `键=值` 对（含 `禁<键>=值`）在案例文本/中文线索里**逐字命中**
  的案例排最前（同一档内按命中数、再按 `case_id`，**确定性**）；
* **词法层**：其余位置用仓库自带的 Okapi BM25（与 `rank_bm25` 同算法同参数，
  `bm25.py`）对"中文线索 ＋ 作者原文摘录"打分；
* **重排层（可选、注入式）**：`rerank(query, cases) -> [case_id, …]`。
  sidecar 可以注入一个 `glm-5.3` 的重排器；**它抛错或返回空时退回词法序**，
  并把原因记在 `last_reason`（与 `CaseIndex._filtered` 同一纪律：增强不许弄挂主路）。

**不做什么**：不建向量、不调网络、不读配置、不 import `bpy`，也不吞异常。
"""

from __future__ import annotations

import pathlib
import re
from typing import Callable, Dict, List, Optional, Sequence

from .bm25 import make_bm25, ranked, tokenize
from .cases import Case, CaseIndex

#: 查询里的 `键=值` 对（与超图契约串同形：`；` 分隔，键可带 `禁` 前缀）。
_PAIR = re.compile(r"([^；;，,\s=]{1,12})=([^；;，,\s=]{1,24})")


def query_pairs(query: str) -> List[str]:
    """查询里的 `键=值` / `禁<键>=值` 对（**逐字保留取值**，不改写、不猜同义）。"""
    return [f"{key}={value}" for key, value in _PAIR.findall(query or "")]


def query_values(query: str) -> List[str]:
    """查询点名的**取值**（去重、保序）——精确层的召回面。

    为什么按**取值**而不是按 `键=值` 逐字：案例文本是**自然语言**（作者写的摘录 ＋
    我们生成的检索线索），它不会写着 `运镜=固定`；按整对去匹配等于永不命中。
    取值才是两边的共同词汇（线索按产品词表生成，见 `case_search_zh` 的 SYSTEM）。
    键（`运镜` / `禁运镜`）的语义留给超图层——那一层有冻结词表与 `forbid` 判据；
    这一层只回答"哪几条案例**提到了**这次点名的那些值"。
    """
    out: List[str] = []
    for _key, value in _PAIR.findall(query or ""):
        if value and value not in out:
            out.append(value)
    return out


class LexicalAdapter:
    """`retrieve(query, *, top_k, cases)` 的零依赖实现（见模块 docstring）。"""

    family = "lexical"

    def __init__(self, index_dir: Optional[pathlib.Path] = None, *,
                 rerank: Optional[Callable[[str, Sequence[Case]], Sequence[str]]] = None
                 ) -> None:
        self.index_dir = pathlib.Path(index_dir) if index_dir else None
        self.rerank = rerank
        #: 上一次调用的具名结果（`""` = 一切正常）——trace 里看得到。
        self.last_reason = ""

    # ------------------------------------------------------------------ #
    def _text_of(self, case: Case, search_zh: Dict[str, str]) -> str:
        clue = str(search_zh.get(str(case.case_id), ""))
        return f"{clue} {case.excerpt or ''}".strip()

    def retrieve(self, query: str, *, top_k: int = 3,
                 cases: Sequence[Case] = ()) -> List[Case]:
        """返回**重排之后**的前 `top_k` 条（可能少于 `top_k`，绝不造案例）。"""
        self.last_reason = ""
        pool = [case for case in cases if case is not None]
        limit = max(1, int(top_k))
        if not pool:
            return []
        search_zh = self._search_zh()
        texts = {str(case.case_id): self._text_of(case, search_zh) for case in pool}

        #: ① 精确层：查询点名的每个**取值**在文本里出现的个数（去重后计）。
        values = query_values(query)
        exact: Dict[str, int] = {}
        if values:
            for case_id, text in texts.items():
                hits = sum(1 for value in values if value in text)
                if hits:
                    exact[case_id] = hits

        #: ② 词法层：Okapi BM25（与产品同一份实现）。
        order: List[str] = []
        engine, _name = make_bm25([tokenize(texts[str(case.case_id)]) for case in pool])
        tokens = tokenize(query)
        if tokens and engine is not None:
            hits = [(index, score) for index, score in ranked(engine, tokens, 0)
                    if score > 0]
            hits.sort(key=lambda item: (-item[1], str(pool[item[0]].case_id)))
            order = [str(pool[index].case_id) for index, _score in hits]
        for case in pool:                      # BM25 没命中的按 id 兜底，保持确定性
            if str(case.case_id) not in order:
                order.append(str(case.case_id))

        by_id = {str(case.case_id): case for case in pool}
        ranked_ids = sorted(order, key=lambda case_id: (-exact.get(case_id, 0),
                                                        order.index(case_id)))
        #: ③ 重排层：注入的 reranker 只许**重排池内**的 id；失败/空就退回词法序。
        if self.rerank is not None:
            try:
                preferred = [str(case_id) for case_id in
                             self.rerank(query, [by_id[case_id] for case_id in ranked_ids])]
            except Exception as exc:  # noqa: BLE001 - 重排是增强，不是关键路径
                self.last_reason = f"rerank_failed:{type(exc).__name__}"
            else:
                known = set(ranked_ids)
                head = [case_id for case_id in preferred if case_id in known]
                if head:
                    rest = [case_id for case_id in ranked_ids if case_id not in set(head)]
                    ranked_ids = head + rest
                else:
                    self.last_reason = "rerank_empty"
        return [by_id[case_id] for case_id in ranked_ids[:limit]]

    # ------------------------------------------------------------------ #
    def _search_zh(self) -> Dict[str, str]:
        """取中文检索线索；没有索引目录就返回空（**不报错**，只退化成只吃原文）。"""
        if self.index_dir is None:
            return {}
        try:
            from .cases import read_search_zh

            return read_search_zh(self.index_dir, self.index_dir)[0]
        except Exception:  # noqa: BLE001 - 线索缺失只是退化，不影响可用性
            return {}


def make_lexical_adapter(index_dir: pathlib.Path, *,
                         rerank: Optional[Callable[[str, Sequence[Case]],
                                                   Sequence[str]]] = None
                         ) -> LexicalAdapter:
    """适配器工厂（`register_lightrag_adapter` 的契约：`(index_dir) -> adapter`）。"""
    return LexicalAdapter(index_dir, rerank=rerank)


def attach_to_index(index: CaseIndex, *, index_dir: Optional[pathlib.Path] = None,
                    rerank=None) -> LexicalAdapter:
    """把一个 `LexicalAdapter` 装到**已装配**的索引上（给 sidecar / 评测用）。

    为什么单独一个入口：`CaseIndex.retrieve` 只在 `backend=lightrag` **且**
    `adapter is not None` 时走适配器（`cases.py:408`）。这个函数只做这一件事，
    不碰取值、不碰留痕——把"用哪条检索路径"留给调用方显式决定。
    """
    adapter = LexicalAdapter(index_dir, rerank=rerank)
    index.adapter = adapter
    return adapter
