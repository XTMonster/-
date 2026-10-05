"""BlockDirector — Blender 白模预演插件（执行文档 v1.2）。

包结构（对照 §2.3）：
- ``contracts``           纯 Python 契约层，禁止 import bpy
- ``utils``               日志、路径、主线程守卫
- ``layer5_orchestrator`` 编排：状态机、工具、Planner（不依赖窗口）
- ``layer6_audit``        审计日志与 LLM Trace
- ``layer7_ui``           Blender UI（唯一允许 import bpy 的层）

当前进度：Phase 0（插件骨架 + 空转状态机 + 审计落盘）。
"""

from __future__ import annotations

import logging

from .registration import register_all, unregister_all
from .utils.logger import configure, get_logger

__version__ = "1.3.0"

# 与执行文档 §2.5 /health 返回的 version 字段保持一致（v1.3 契约扩容）
CONTRACT_VERSION = "1.3.0"

# 传统 addon 兼容信息（Blender 4.2 起推荐 blender_manifest.toml，二者可并存）
bl_info = {
    "name": "BlockDirector (白模导演)",
    "author": "BlockDirector",
    "version": (1, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > BlockDirector",
    "description": "剧本 → 白模预演 → AI 视频参考",
    "category": "Animation",
}

_log = None


def _bootstrap() -> None:
    """加载时常驻工作：日志、主线程登记、配置校验。"""
    global _log
    _log = configure(level=logging.INFO)
    # §3.1：显式登记主线程，之后 threading_guard 才能拦截后台线程的 bpy 访问
    from .utils.threading_guard import capture_main_thread
    capture_main_thread()
    from .settings import load_config
    load_config()


def register() -> None:
    """Blender 插件入口。"""
    _bootstrap()
    registered = register_all()
    #: **门控注册**（P8）：只有显式设了 `BLOCK_DIRECTOR_RETRIEVAL_LIGHTRAG=1` 才把
    #: LightRAG 适配器工厂登记进路由表——默认关，产品现行默认路径仍是 `hybrid`。
    #: 任何失败都只记日志：检索臂注册不该拖垮插件加载。
    try:
        from .knowledge import lightrag_adapter

        if lightrag_adapter.register_if_enabled():
            get_logger().info("LightRAG 检索臂已注册（%s）",
                              lightrag_adapter.ENABLE_ENV)
    except Exception as exc:  # noqa: BLE001
        get_logger().error("LightRAG 检索臂注册失败: %s: %s", type(exc).__name__, exc)
    get_logger().info("BlockDirector %s 已加载（注册模块: %s）",
                      __version__, ", ".join(registered) or "无")


def unregister() -> None:
    """Blender 插件卸载入口。"""
    unregister_all()
    get_logger().info("BlockDirector 已卸载")


__all__ = ["__version__", "CONTRACT_VERSION", "bl_info", "register", "unregister"]
