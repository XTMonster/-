"""选择实际使用的传输实现（执行文档 v1.2 §2.5 降级为运行时接线）。"""

from __future__ import annotations

from typing import Tuple

from ..contracts.enums import TransportMode
from ..contracts.transport import SidecarTransport, select_transport
from ..utils.logger import get_logger
from .offline import OfflineTransport

log = get_logger("transport")


class TransportUnavailable(RuntimeError):
    """当前配置下没有可用的传输实现。"""


def make_transport(config, *, offline: bool = False,
                   force_offline_plan: dict | None = None) -> Tuple[object, str]:
    """返回 ``(transport, 模式说明)``。

    Phase 0 可用路径：离线自检 / sidecar。
    进程内直连（openai SDK）按路线图属于 Phase 4，届时在此接入。
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
        selection = select_transport(mode, direct=None, sidecar=sidecar)
        for warning in selection.warnings:
            log.warning(warning)
        if selection.mode is TransportMode.SIDECAR:
            return selection.transport, "sidecar"

    raise TransportUnavailable(
        "没有可用的 LLM 传输：请开启「离线自检」，或启动 sidecar 并在配置中"
        "填写 sidecar_url。（进程内直连将在 Phase 4 接入）"
    )
