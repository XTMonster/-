"""LLM/RAG 传输层契约与两种实现（执行文档 v1.2 §2.4 / §2.5）。

上层（driver）只依赖 :class:`LLMTransport` 抽象；进程内模式与 sidecar 模式
的实现差异被完全封装在此。选择策略由 :func:`select_transport` 实现，
对应 §2.5 的三条确定性规则。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from .enums import Capability, ErrorCode, TransportMode
from .errors import TransportError, error_for_http_status
from .health import HealthStatus
from .knowledge import Card
from .messages import ChatPayload, ChatReply
from .operations import (
    CancelRequest,
    EmbedRequest,
    EmbedResponse,
    RetrieveRequest,
    RetrieveResponse,
)


# --------------------------------------------------------------------------- #
# 抽象
# --------------------------------------------------------------------------- #
@runtime_checkable
class LLMTransport(Protocol):
    """所有传输实现的公共接口（§2.5）。"""

    def chat(self, payload: ChatPayload, timeout: float = 120.0) -> ChatReply:
        ...

    def embed(self, texts: List[str], timeout: float = 30.0) -> List[List[float]]:
        ...

    def retrieve(self, query: str, domain: Optional[str] = None,
                 top_k: int = 5, timeout: float = 30.0) -> List[Card]:
        ...

    def health(self, timeout: float = 2.0) -> HealthStatus:
        ...

    def cancel(self, request_id: str) -> None:
        ...


# HTTP 打开器签名：(method, url, headers, body, timeout) -> (status, body_text)
Opener = Callable[[str, str, Dict[str, str], Optional[bytes], float],
                  Tuple[int, str]]


def _urllib_opener(method: str, url: str, headers: Dict[str, str],
                   body: Optional[bytes], timeout: float) -> Tuple[int, str]:
    """标准库实现；HTTP 错误码也返回 body 而不是抛异常，便于统一映射。"""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        raise TransportError(ErrorCode.LLM_001, f"连接失败: {exc}") from exc


# --------------------------------------------------------------------------- #
# 实现 ②：sidecar（HTTP）
# --------------------------------------------------------------------------- #
@dataclass
class SidecarTransport:
    """通过本机 HTTP 访问 sidecar 服务（§2.5 线协议）。"""

    base_url: str = "http://127.0.0.1:8765"
    token: str = ""
    timeout: float = 120.0
    opener: Opener = _urllib_opener

    # -- 内部 --------------------------------------------------------------- #
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _call(self, method: str, path: str, payload: Optional[Dict[str, Any]],
              timeout: float) -> Dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        status, text = self.opener(method, url, self._headers(), body, timeout)
        if not (200 <= status < 300):
            raise TransportError(error_for_http_status(status),
                                 f"sidecar 返回 {status}",
                                 http_status=status, body=text[:2000])
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TransportError(ErrorCode.LLM_002,
                                 f"sidecar 响应不是合法 JSON: {exc}", status, text[:2000]) from exc
        if not isinstance(data, dict):
            raise TransportError(ErrorCode.LLM_002, "sidecar 响应不是 JSON 对象",
                                 status, text[:2000])
        return data

    # -- 契约 --------------------------------------------------------------- #
    def chat(self, payload: ChatPayload, timeout: Optional[float] = None) -> ChatReply:
        data = self._call("POST", "/v1/chat", payload.to_dict(),
                          timeout if timeout is not None else self.timeout)
        return ChatReply.from_dict(data)

    def embed(self, texts: List[str], timeout: float = 30.0) -> List[List[float]]:
        data = self._call("POST", "/v1/embed", EmbedRequest(texts=list(texts)).to_dict(),
                          timeout)
        return EmbedResponse.from_dict(data).vectors

    def retrieve(self, query: str, domain: Optional[str] = None,
                 top_k: int = 5, timeout: float = 30.0) -> List[Card]:
        request = RetrieveRequest(query=query, domain=domain, top_k=top_k)
        data = self._call("POST", "/v1/retrieve", request.to_dict(), timeout)
        return RetrieveResponse.from_dict(data).cards

    def health(self, timeout: float = 2.0) -> HealthStatus:
        return HealthStatus.from_dict(self._call("GET", "/health", None, timeout))

    def cancel(self, request_id: str) -> None:
        try:
            self._call("POST", "/v1/cancel", CancelRequest(request_id).to_dict(), 5.0)
        except TransportError:
            pass   # 取消失败不影响主流程（协作式取消，§3.3）

    def probe(self, timeout: float = 2.0) -> Optional[HealthStatus]:
        """健康探测：失败返回 None 而不抛异常（供选择策略使用）。"""
        try:
            status = self.health(timeout)
        except TransportError:
            return None
        return status if status.ok else None


# --------------------------------------------------------------------------- #
# 实现 ①：进程内（direct）
# --------------------------------------------------------------------------- #
ChatFn = Callable[[ChatPayload, float], ChatReply]
EmbedFn = Callable[[List[str]], List[List[float]]]
RetrieveFn = Callable[[str, Optional[str], int], List[Card]]


@dataclass
class DirectTransport:
    """进程内实现：把具体 SDK（openai / 本地端点）注入为可调用对象。

    这样契约层保持零第三方依赖，且测试可注入假实现。
    """

    chat_fn: ChatFn
    embed_fn: Optional[EmbedFn] = None
    retrieve_fn: Optional[RetrieveFn] = None
    capabilities: List[Capability] = field(
        default_factory=lambda: [Capability.LLM, Capability.BM25]
    )
    version: str = ""

    def chat(self, payload: ChatPayload, timeout: float = 120.0) -> ChatReply:
        return self.chat_fn(payload, timeout)

    def embed(self, texts: List[str], timeout: float = 30.0) -> List[List[float]]:
        if self.embed_fn is None:
            raise TransportError(ErrorCode.LLM_002,
                                 "进程内模式未启用 embedding（向量检索需 sidecar）")
        return self.embed_fn(list(texts))

    def retrieve(self, query: str, domain: Optional[str] = None,
                 top_k: int = 5, timeout: float = 30.0) -> List[Card]:
        if self.retrieve_fn is None:
            raise TransportError(ErrorCode.LLM_002,
                                 "进程内模式未注册检索函数（默认应使用 BM25 本地实现）")
        return self.retrieve_fn(query, domain, top_k)

    def health(self, timeout: float = 2.0) -> HealthStatus:
        return HealthStatus(status="ok", version=self.version,
                            capabilities=list(self.capabilities))

    def cancel(self, request_id: str) -> None:
        return None


# --------------------------------------------------------------------------- #
# §2.5 选择策略
# --------------------------------------------------------------------------- #
@dataclass
class TransportSelection:
    transport: LLMTransport
    mode: TransportMode            # 解析结果，永不为 AUTO
    reason: str
    health: Optional[HealthStatus] = None
    warnings: List[str] = field(default_factory=list)


def select_transport(mode: TransportMode,
                     direct: Optional[LLMTransport] = None,
                     sidecar: Optional[SidecarTransport] = None,
                     health_timeout: float = 2.0) -> TransportSelection:
    """按 §2.5 的确定性规则选择传输实现。

    1. ``mode == direct``  → 直接用进程内实现。
    2. ``mode == sidecar`` → 必须探测到健康；探测失败则回退 direct（若有）并告警。
    3. ``mode == auto``    → 探测 sidecar；可用则用 sidecar，否则用 direct。
    """
    warnings: List[str] = []

    if mode is TransportMode.DIRECT:
        if direct is None:
            raise TransportError(ErrorCode.LLM_002, "配置为 direct 但未提供进程内实现")
        return TransportSelection(direct, TransportMode.DIRECT, "显式配置为进程内模式")

    if sidecar is not None:
        status = sidecar.probe(health_timeout)
        if status is not None:
            return TransportSelection(sidecar, TransportMode.SIDECAR,
                                      "sidecar /health 正常", status, warnings)
        if mode is TransportMode.SIDECAR:
            warnings.append("sidecar 不可达（/health 超时或未监听），已回退到进程内模式")
        else:
            warnings.append("未探测到 sidecar，使用进程内模式")
    else:
        if mode is TransportMode.SIDECAR:
            warnings.append("配置为 sidecar 但未提供 sidecar 地址，已回退到进程内模式")
        else:
            warnings.append("未配置 sidecar，使用进程内模式")

    if direct is None:
        raise TransportError(ErrorCode.LLM_001, "sidecar 不可用且无进程内实现，无法继续")
    return TransportSelection(direct, TransportMode.DIRECT, warnings[-1], None, warnings)
