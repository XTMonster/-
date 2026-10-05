"""插件侧的 LightRAG 适配器：挂在**已经声明好的**接缝上（`cases.py:88`）。

契约与词法适配器完全一样：`retrieve(query, *, top_k, cases) -> Sequence[Case]`，
工厂 `(index_dir) -> adapter`。区别只在"检索在哪发生"——它在 sidecar（独立进程，
住着 `lightrag` 与本地 GPU 嵌入），插件这边只用 stdlib `urllib` 说话。

三条纪律：

1. **返回的必须是 `cases` 的子序列**：sidecar 给的 id 不在传入集合里就丢弃并具名记账
   （ADR-0014 说的"陈旧化陷阱"）；上层据此知道索引是不是脏的。
2. **不可达/指纹不匹配 ⇒ 空列表 ＋ 具名 `last_reason`**：由上层回落默认路由，
   绝不把"降级"伪装成"成功的空结果"。
3. **fail closed**：`expected_fingerprint` 给了就先比 `/health` 回的指纹，不一致
   **连查都不查**（不拿脏索引出数）。
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Optional, Sequence

from ..contracts.knowledge import Case
from . import lightrag_client as lc

#: 默认端口（与 sidecar 的约定；环境变量可覆盖）。
DEFAULT_URL = "http://127.0.0.1:8765"
#: 注册开关：**默认关**。产品现行的默认路径是 `hybrid`（BM25），而 LightRAG 那条路
#: 依赖 sidecar——不显式打开就不该让默认检索依赖一个可能不在的服务。
ENABLE_ENV = "BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG"
#: 单次 `/health`／`/query` 的读超时（秒）的**环境变量覆盖**。
#:
#: 为什么需要它（2026-10-05 实测）：默认 10 秒是"sidecar 已经热着"的预算，而
#: LightRAG 的**第一次**查询要把 storages 装进来（还要加载本地嵌入模型），实测
#: 远超 10 秒——于是每条查询都在客户端超时、`CaseIndex` 静默退回 BM25，
#: 那条臂量到的是**超时**而不是检索质量（`work/_dryrun.lightrag.jsonl` 里那行
#: `cases_degrade_reason: lightrag_query_failed:TimeoutError` 就是它）。
#: 生产默认**不动**（10 秒是产品侧的延迟预算；退回 BM25 是 §2.3b 的设计内降级），
#: 但**测量**必须能把超时放宽到"量得到检索"的量级——那是这条环境变量的用途。
TIMEOUT_ENV = "BLOCK_DIRECTOR_LIGHTRAG_TIMEOUT"
_TRUTHY = ("1", "true", "yes", "on")


class LightRAGAdapter:
    """把 sidecar 的 `/query` 结果翻译成本仓的 `Case`。"""

    def __init__(self, *, base_url: str = DEFAULT_URL, timeout: float = 10.0,
                 expected_fingerprint: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.expected_fingerprint = expected_fingerprint
        self.last_reason = ""

    #: 与词法适配器同名的探测面（`CaseIndex` 读它做记账）。
    path_label = "lightrag"

    def _check_health(self) -> Optional[str]:
        """返回失败原因；`None` 表示可以继续。"""
        try:
            info = lc.health(self.base_url, timeout=self.timeout)
        except lc.SidecarError as exc:
            return str(exc)
        if self.expected_fingerprint:
            got = str(info.get("index_fingerprint") or "")
            if got != self.expected_fingerprint:
                return "index_fingerprint_mismatch:%s!=%s" % (got, self.expected_fingerprint)
        return None

    def retrieve(self, query: str, *, top_k: int = 3,
                 cases: Sequence[Case] = ()) -> List[Case]:
        self.last_reason = ""
        why = self._check_health()
        if why:
            self.last_reason = why
            return []
        try:
            hits = lc.query(self.base_url, query, top_k=top_k, timeout=self.timeout)
        except lc.SidecarError as exc:
            self.last_reason = str(exc)
            return []
        by_id = {str(case.case_id): case for case in cases}
        out: List[Case] = []
        dropped = 0
        for hit in hits:
            case = by_id.get(str(hit["case_id"]))
            if case is None:
                dropped += 1
                continue
            out.append(case)
        if dropped:
            #: **具名记账**：上层据此判断索引是不是指向了别的案例集合。
            self.last_reason = "unknown_id_dropped:%d" % dropped
        return out[: max(0, int(top_k))]


def make_lightrag_adapter(index_dir: Any = None, *, base_url: str = "",
                          expected_fingerprint: str = "",
                          timeout: Optional[float] = None) -> LightRAGAdapter:
    """工厂：签名与 `cases.py:88` 的契约一致（`(index_dir) -> adapter`）。

    `timeout` 留空则看 `BLOCK_DIRECTOR_LIGHTRAG_TIMEOUT`，再留空才回默认 10 秒。
    给不出数（不是正数）就**具名报错**——不许把"超时预算写错了"变成"检索没命中"。
    """
    import os
    url = base_url or os.environ.get("BLOCK_DIRECTOR_LIGHTRAG_URL") or DEFAULT_URL
    if timeout is None:
        raw = str(os.environ.get(TIMEOUT_ENV) or "").strip()
        if raw:
            try:
                timeout = float(raw)
            except ValueError as exc:
                raise ValueError("%s 不是数：%r" % (TIMEOUT_ENV, raw)) from exc
    if timeout is not None and float(timeout) <= 0:
        raise ValueError("lightrag 超时必须为正数，收到 %r" % (timeout,))
    return LightRAGAdapter(base_url=url, timeout=float(timeout or 10.0),
                           expected_fingerprint=expected_fingerprint)


def attach_to_index(index: Any, *, base_url: str = "",
                    expected_fingerprint: str = "",
                    timeout: float = 10.0) -> LightRAGAdapter:
    """把适配器装到**已装配**的索引上（与词法适配器的 `attach_to_index` 同形）。

    `CaseIndex.retrieve` 只在 `backend="lightrag"` **且** `adapter is not None` 时
    走适配器；这个函数只做"装上"这一件事，不碰取值、不碰留痕。
    """
    adapter = make_lightrag_adapter(base_url=base_url,
                                    expected_fingerprint=expected_fingerprint,
                                    timeout=timeout)
    index.adapter = adapter
    return adapter


def register_if_enabled(*, env: str = "") -> bool:
    """环境变量门控注册。返回**这次有没有注册**。

    * 变量不设／为空／`0`／`false`／`no`／`off` ⇒ **不注册**（返回 False）；
    * 变量为 `1`／`true`／`yes`／`on` ⇒ 注册**工厂**（不是实例——惰性构造，
      import 期不连 sidecar）；重复调用不会重复注册。
    """
    import os
    from . import cases as kb_cases
    value = str(os.environ.get(env or ENABLE_ENV, "")).strip().lower()
    if value not in _TRUTHY:
        return False
    factory = make_lightrag_adapter
    if factory not in kb_cases._ADAPTER_FACTORIES:
        kb_cases.register_lightrag_adapter(factory)
    return True
