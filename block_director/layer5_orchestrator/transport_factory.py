"""选择实际使用的传输实现（执行文档 v1.2 §2.5 降级为运行时接线）。"""

from __future__ import annotations

from typing import Tuple

from typing import Optional

from ..contracts.enums import TransportMode
from ..contracts.transport import OpenAICompatibleTransport, SidecarTransport
from ..utils.logger import get_logger
from .offline import OfflineTransport

log = get_logger("transport")


class TransportUnavailable(RuntimeError):
    """当前配置下没有可用的传输实现。"""


def make_transport(config, *, offline: bool = False,
                   force_offline_plan: dict | None = None) -> Tuple[object, str]:
    """返回 ``(transport, 模式说明)``。

    选择顺序（§2.5）：离线自检 → sidecar（能探到才用）→ 直连 OpenAI 兼容端点。
    三者都不可用时抛出明确指引，而不是静默失败。
    """
    if offline:
        return OfflineTransport(plan=force_offline_plan), "offline"

    mode = config.llm.transport
    if mode is TransportMode.SIDECAR or mode is TransportMode.AUTO:
        sidecar = SidecarTransport(
            base_url=config.llm.sidecar_url,
            token=config.llm.sidecar_token,
            timeout=config.llm.sidecar_timeout_s,
        )
        if sidecar.probe(2.0) is not None:
            return sidecar, "sidecar"
        log.warning("sidecar 不可达（%s），继续尝试直连端点", config.llm.sidecar_url)

    direct = build_direct(config)
    if direct is not None:
        return direct, "direct"

    raise TransportUnavailable(
        "没有可用的 LLM 传输。三条路径任选其一：\n"
        "1) 开启「离线自检」；\n"
        "2) 启动 sidecar 并填写 llm.sidecar_url；\n"
        "3) 填写 llm.api_key（或本地模型的 llm.base_url，如 "
        "http://127.0.0.1:11434/v1）走直连。"
    )


def build_direct(config) -> Optional[OpenAICompatibleTransport]:
    """按配置构造直连传输；没有可用的端点信息时返回 None。

    直连说的是 **OpenAI 兼容**协议，因此同一个实现同时覆盖 OpenAI、
    DeepSeek、Ollama、vLLM 等——只需 base_url 与 model 不同。
    """
    base_url = (config.llm.base_url or "").strip()
    api_key = (config.llm.api_key or "").strip()
    if not base_url and not api_key:
        return None
    if base_url and not base_url.rstrip("/").endswith("/v1") \
            and "/v1" not in base_url:
        # 用户多半填的是根地址（如 http://127.0.0.1:11434）；补上 /v1
        base_url = base_url.rstrip("/") + "/v1"
    return OpenAICompatibleTransport(
        base_url=base_url or "https://api.openai.com/v1",
        api_key=api_key,
        model=config.llm.model,
        timeout=float(config.llm.sidecar_timeout_s),
    )
