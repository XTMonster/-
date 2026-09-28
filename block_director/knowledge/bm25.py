"""Okapi BM25 检索内核（执行文档 v1.2 §6.4）。

规范把默认后端定为 ``bm25``，依赖 ``rank_bm25``。但实测 Blender 5.2 自带
Python（3.13）**没有** ``rank_bm25``（见 ``tools/_probe_out/report.json`` 的
``python_env.has_rank_bm25 = false``），而"往 Blender 的 Python 里塞第三方包"
正是 §6.1 想避免的那类风险（体积、与随附 numpy 冲突、下载失败）。

因此这里自带一份**与 ``rank_bm25.BM25Okapi`` 同算法同参数**的实现
（``k1=1.5``、``b=0.75``、负 IDF 用 ``epsilon * average_idf`` 兜底，
``epsilon=0.25``）。选择逻辑：

- 环境里装了 ``rank_bm25`` → :func:`make_bm25` 优先用它（与规范依赖一致）；
- 没装 → 用自带实现，检索质量同算法、零安装。

这不是"降级"：两条路径算的是同一个公式，用哪个由 :func:`make_bm25` 返回的
名字如实标注，供调试面板与 ``/health`` 展示。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Sequence, Tuple

K1 = 1.5
B = 0.75
EPSILON = 0.25

_LATIN = re.compile(r"[a-z]+|[0-9]+")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    """切词：拉丁/数字整词 + CJK 单字与相邻双字。

    为什么中文要出双字："三分法""越轴""轴线"是强术语，只切单字会与"三""分"
    这类高频字混在一起，召回反而变差；加上相邻双字后这些术语可以被精确命中。
    """
    lowered = (text or "").lower()
    tokens: List[str] = [match.group(0) for match in _LATIN.finditer(lowered)]
    positions = [match.start() for match in _CJK.finditer(lowered)]
    for index, position in enumerate(positions):
        tokens.append(lowered[position])
        if index + 1 < len(positions) and positions[index + 1] == position + 1:
            tokens.append(lowered[position:position + 2])
    return tokens


class BM25:
    """与 ``rank_bm25.BM25Okapi`` 等价的纯 Python 实现。"""

    name = "builtin.BM25Okapi"

    def __init__(self, corpus: Sequence[Sequence[str]], k1: float = K1,
                 b: float = B, epsilon: float = EPSILON) -> None:
        self.corpus: List[List[str]] = [list(doc) for doc in corpus]
        self.k1 = float(k1)
        self.b = float(b)
        self.epsilon = float(epsilon)
        self.n_docs = len(self.corpus)
        self.doc_len = [len(doc) for doc in self.corpus]
        self.avgdl = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0
        self.doc_freqs: List[Counter] = []
        document_freq: Counter = Counter()
        for doc in self.corpus:
            freqs = Counter(doc)
            self.doc_freqs.append(freqs)
            document_freq.update(freqs.keys())
        self.idf: Dict[str, float] = {}
        for term, freq in document_freq.items():
            self.idf[term] = (math.log(self.n_docs - freq + 0.5)
                              - math.log(freq + 0.5))
        average_idf = (sum(self.idf.values()) / len(self.idf)) if self.idf else 0.0
        for term, value in list(self.idf.items()):
            if value < 0:
                self.idf[term] = self.epsilon * average_idf

    def get_scores(self, query: Iterable[str]) -> List[float]:
        scores = [0.0] * self.n_docs
        if not self.corpus or self.avgdl <= 0:
            return scores
        for term in query:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for index, freqs in enumerate(self.doc_freqs):
                frequency = freqs.get(term, 0)
                if not frequency:
                    continue
                normaliser = (frequency
                              + self.k1 * (1 - self.b
                                           + self.b * self.doc_len[index] / self.avgdl))
                scores[index] += idf * frequency * (self.k1 + 1) / normaliser
        return scores


def make_bm25(corpus: Sequence[Sequence[str]]) -> Tuple[Any, str]:
    """返回 ``(engine, name)``：有 ``rank_bm25`` 就用它，否则用自带实现。"""
    try:                                    # pragma: no cover - 取决于环境
        from rank_bm25 import BM25Okapi     # type: ignore
    except Exception:
        return BM25(corpus), BM25.name
    return BM25Okapi([list(doc) for doc in corpus]), "rank_bm25.BM25Okapi"


def ranked(engine: Any, query_tokens: Sequence[str],
           limit: int = 0) -> List[Tuple[int, float]]:
    """按分数降序返回 ``(下标, 分数)``；同分时按下标稳定排序。

    ``rank_bm25`` 与自带实现都提供 ``get_scores``，因此这里对两者通用。
    """
    scores = engine.get_scores(list(query_tokens))
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    if limit:
        order = order[:limit]
    return [(index, float(scores[index])) for index in order]
