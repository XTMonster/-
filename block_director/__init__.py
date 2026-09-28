"""BlockDirector — Blender 白模预演插件.

当前阶段：契约层（contracts）与规格（specs）已实现并可测试；
Blender 侧模块（layer1..layer9）按执行文档 v1.2 的路线图实现。
"""

from __future__ import annotations

__version__ = "1.2.0"

# 与执行文档 v1.2 §2.5 /health 返回的 version 字段保持一致
CONTRACT_VERSION = "1.2.0"

__all__ = ["__version__", "CONTRACT_VERSION"]
