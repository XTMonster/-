"""循环检测（执行文档 v1.2 §7.6）。

三种病态行为：
1. **原地打转**：同一工具 + 同一参数被反复调用；
2. **只查不做**：连续多次只调用查询工具却不修改场景；
3. **来回振荡**：A→B→A→B 交替（v1.0 未覆盖）。

检测到就返回一句可注入系统提示的警告；驱动可据此强制收尾。
"""

from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Sequence, Tuple

DEFAULT_QUERY_TOOLS = ("get_scene_state", "check_visibility",
                       "check_composition", "check_axis", "search_knowledge")


def _fingerprint(name: str, args: Any) -> str:
    try:
        payload = json.dumps(args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        payload = str(args)
    return f"{name}|{payload}"


@dataclass
class LoopReport:
    kind: str
    message: str


class LoopDetector:
    def __init__(self, *, repeat_threshold: int = 3,
                 query_streak_limit: int = 5,
                 oscillation_window: int = 4,
                 query_tools: Sequence[str] = DEFAULT_QUERY_TOOLS) -> None:
        self.repeat_threshold = repeat_threshold
        self.query_streak_limit = query_streak_limit
        self.oscillation_window = oscillation_window
        self.query_tools = set(query_tools)
        self._fingerprints: Counter = Counter()
        self._recent: Deque[Tuple[str, str]] = deque(maxlen=oscillation_window)
        self._query_streak = 0

    def record(self, name: str, args: Any) -> None:
        self._fingerprints[_fingerprint(name, args)] += 1
        self._recent.append((name, _fingerprint(name, args)))
        if name in self.query_tools:
            self._query_streak += 1
        else:
            self._query_streak = 0

    def detect(self) -> Optional[LoopReport]:
        if not self._fingerprints:
            return None

        if self._query_streak >= self.query_streak_limit:
            return LoopReport(
                "query_only",
                f"检测到连续 {self._query_streak} 次只查询不修改。"
                f"请实际调用修改类工具，或结束当前镜头。")

        fingerprint, count = self._fingerprints.most_common(1)[0]
        if count >= self.repeat_threshold:
            name = fingerprint.split("|", 1)[0]
            return LoopReport(
                "repeat",
                f"检测到重复调用：{name} 用同一组参数已调用 {count} 次。"
                f"请换一个做法，或直接推进到下一步。")

        if self._is_oscillating():
            return LoopReport(
                "oscillation",
                "检测到来回振荡：两个操作在交替反复。"
                "请判断哪个方向正确并一次性改到位。")
        return None

    def _is_oscillating(self) -> bool:
        if len(self._recent) < self.oscillation_window:
            return False
        names = [name for name, _ in self._recent]
        first, second = names[0], names[1]
        if first == second:
            return False
        return names == [first, second] * (self.oscillation_window // 2)

    def reset(self) -> None:
        self._fingerprints.clear()
        self._recent.clear()
        self._query_streak = 0

    @property
    def stats(self) -> Dict[str, int]:
        return {"calls": sum(self._fingerprints.values()),
                "distinct": len(self._fingerprints),
                "query_streak": self._query_streak}
