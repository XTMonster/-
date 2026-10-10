"""运行状态事件 DTO（v1.7 TDD §2.1）。

plugin → sidecar → web 的观察流：每个状态迁移 / 每镜完成 / 每次 LLM 调用
各产生一条事件。事件是**观察流**，``kind`` 不做枚举校验（宽松读）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class UIEvent:
    seq: int                 # 单调递增，Web 端用 since=seq 增量拉
    ts: float                # time.time()
    #: state_change | shot_progress | llm_call | audit | chat | error
    kind: str
    state: str = ""          # DriverState.value，kind=state_change 时必填
    shot_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "state": self.state,
            "shot_id": self.shot_id,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UIEvent":
        return cls(
            seq=int(data["seq"]),
            ts=float(data["ts"]),
            kind=str(data["kind"]),
            state=str(data.get("state", "")),
            shot_id=str(data.get("shot_id", "")),
            payload=dict(data.get("payload") or {}),
        )
