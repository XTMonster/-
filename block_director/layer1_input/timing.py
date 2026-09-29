"""剧本声明的时长（v1.3 诉求 6）。

**为什么需要它**：v1.2 只按"中文 3 字/秒 + 情绪倍率 + 标点停顿"估算，
把剧本里明明白白写着的"（约 3 秒）""预估时长：6 秒""总时长：10 秒"
全部忽略。实测后果：一份声明总时长 33 秒的分镜表被估成 39.54 秒，
镜头 4 从 6 秒拉到 8 秒、镜头 6 从 7 秒拉到 11.5 秒。

**优先级链（固定，不可协商）**：

    台词级声明 → 镜头级声明 → 节点/场级声明 → 引擎估算（3 字/秒）

本模块负责第一环——从台词文本里抽出声明值；镜头级与节点级声明依赖
v1.3 的分镜表解析（见执行计划的附录 C），届时复用 :class:`DeclaredTiming`。

纯计算，可单测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

FPS = 24

#: 台词的时长声明：``（约3秒）`` / ``(3s)`` / ``（2.5 秒）``——
#: 只认"数字 + 秒/s"，因此 `（低声）` 这类表演提示不会被误吃。
DURATION_SUFFIX_RE = re.compile(
    r"[（(]\s*(?:约\s*)?(\d+(?:\.\d+)?)\s*(?:秒|s|sec|seconds?)\s*[）)]\s*$",
    re.IGNORECASE)


@dataclass(frozen=True)
class DeclaredTiming:
    """一条剧本声明的时长。

    ``scope`` 取 ``dialogue`` / ``shot`` / ``scene`` / ``node``；
    ``ref`` 是它所属的对象（台词序号、镜号、节点号），便于核对与报错。
    """

    scope: str
    seconds: float
    ref: str = ""
    source_index: int = 0
    raw: str = ""

    @property
    def frames(self) -> int:
        return frames_from_seconds(self.seconds)

    def to_dict(self) -> dict:
        return {"scope": self.scope, "seconds": self.seconds, "ref": self.ref,
                "source_index": self.source_index, "raw": self.raw}


def frames_from_seconds(seconds: float, fps: int = FPS,
                        minimum: int = 1) -> int:
    """秒 → 帧（四舍五入）。声明值不参与"最短 8 帧"的兜底，
    因为那是引擎估算的下限，不是剧本的意图。"""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return max(int(minimum), 1)
    return max(int(round(value * int(fps))), int(minimum))


def extract_declared_seconds(text: str) -> Tuple[str, Optional[float]]:
    """从台词末尾抽出时长声明，返回 ``(清理后的文本, 秒数 or None)``。

    >>> extract_declared_seconds('好的，那你多小心一些。（约3秒）')
    ('好的，那你多小心一些。', 3.0)
    >>> extract_declared_seconds('（低声）你还在听吗。')
    ('（低声）你还在听吗。', None)
    """
    raw = str(text or "")
    match = DURATION_SUFFIX_RE.search(raw)
    if match is None:
        return raw, None
    cleaned = raw[:match.start()].rstrip()
    if not cleaned:
        # 整行只有一个时长声明：保留原文，别把台词清成空串
        return raw, None
    try:
        seconds = float(match.group(1))
    except (TypeError, ValueError):
        return raw, None
    if seconds <= 0:
        return raw, None
    return cleaned, seconds


def dialogue_timing(
    declared_seconds: Optional[float], *,
    source: str = "script_first",
) -> Optional[int]:
    """按优先级链决定"这一句用不用声明值"。

    返回帧数表示**采用声明**；``None`` 表示交给引擎估算。
    ``source == "engine"`` 时一律返回 ``None``（显式关闭声明优先）。
    """
    if str(source or "").strip().lower() != "script_first":
        return None
    if declared_seconds is None:
        return None
    return frames_from_seconds(declared_seconds)
