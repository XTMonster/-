"""空间尺外挂评测台（spec §15）。

零耦合外挂：只 import 纯层测量与 demo schema，不 import 主链路、不碰 bpy。
判官可插拔：mock（离线确定性，plumbing） / real（OpenAI 兼容，ab_result）。
"""
from __future__ import annotations

__version__ = "0.1.0"
