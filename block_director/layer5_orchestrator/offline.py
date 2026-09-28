"""离线自检传输：不联网也能跑通整条链路（执行文档 v1.2 §21.4 的 mock LLM）。

用途有两个，都很重要：
1. 让 Phase 0 的 DoD（GUI/headless 跑通空转状态机）在**没有 API Key** 时也能验收；
2. 作为 Golden Test 的确定性替身——输出只依赖输入剧本，天然可断言。
"""

from __future__ import annotations

import json
from typing import List, Optional

from ..contracts.enums import Capability, Purpose
from ..contracts.health import HealthStatus
from ..contracts.knowledge import Card
from ..contracts.messages import ChatPayload, ChatReply, FunctionCall, ToolCall
from .planner import PLAN_TOOL_NAME
from .review import REVIEW_TOOL_NAME


def demo_plan_dict(script: str) -> dict:
    """由剧本粗略生成一份确定性计划（2 镜），用于自检与回归。"""
    first_line = ""
    for raw in (script or "").splitlines():
        text = raw.strip()
        if text:
            first_line = text[:40]
            break
    heading = first_line or "未命名场景"
    return {
        "scene_heading": heading,
        "continuity_notes": ["离线自检模式生成，仅供链路验证"],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "intent": "建立场景与人物关系",
                "shot_type": "MLS",
                "duration_frames": 96,
                "characters": ["char_001", "char_002"],
                "dialogue_ids": [],
                "actions": [
                    {"character_id": "char_001", "action_type": "nod",
                     "start_frame": 1, "end_frame": 96,
                     "params": {"cycles": 2}},
                ],
                "axis_note": "以两人连线建立轴线",
                "continuity_in": "开场",
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "intent": "推进对话，给出反应",
                "shot_type": "MCU",
                "duration_frames": 120,
                "characters": ["char_002"],
                "dialogue_ids": [],
                "actions": [
                    {"character_id": "char_002", "action_type": "sit",
                     "start_frame": 1, "end_frame": 60, "params": {"drop": 0.2}},
                ],
                "axis_note": "保持轴线同侧",
                "continuity_in": "承接 shot_001 的站位",
            },
        ],
    }


class OfflineTransport:
    """实现 LLMTransport 协议的离线替身。"""

    def __init__(self, plan: Optional[dict] = None, fail_times: int = 0) -> None:
        self._plan = plan
        self.fail_times = fail_times
        self.chat_calls = 0
        self.cancelled: List[str] = []
        self.last_payload: Optional[ChatPayload] = None

    # -- LLMTransport ------------------------------------------------------ #
    def chat(self, payload: ChatPayload, timeout: float = 120.0) -> ChatReply:
        self.chat_calls += 1
        self.last_payload = payload
        if self.chat_calls <= self.fail_times:
            raise RuntimeError("离线自检：模拟一次调用失败")

        if payload.purpose is Purpose.REVIEW:
            call = ToolCall(id=f"review_{self.chat_calls}",
                            function=FunctionCall(
                                name=REVIEW_TOOL_NAME,
                                arguments=json.dumps(
                                    {"verdict": "ok",
                                     "notes": "离线自检：默认通过"},
                                    ensure_ascii=False)))
            return ChatReply(content=None, tool_calls=[call],
                             request_id=payload.request_id, model="offline",
                             finish_reason="tool_calls")

        script = ""
        for message in payload.messages:
            if message.content and "<untrusted_script_content>" in message.content:
                script = message.content.split("<untrusted_script_content>", 1)[1]
                script = script.split("</untrusted_script_content>", 1)[0]
                break
        plan = self._plan or demo_plan_dict(script)
        call = ToolCall(
            id=f"call_{self.chat_calls}",
            function=FunctionCall(name=PLAN_TOOL_NAME,
                                  arguments=json.dumps(plan, ensure_ascii=False)),
        )
        return ChatReply(content=None, tool_calls=[call], request_id=payload.request_id,
                         model="offline", finish_reason="tool_calls")

    def health(self, timeout: float = 2.0) -> HealthStatus:
        return HealthStatus(status="ok", version="1.2.0",
                            capabilities=[Capability.LLM, Capability.BM25],
                            detail="offline transport")

    def embed(self, texts: List[str], timeout: float = 30.0) -> List[List[float]]:
        raise NotImplementedError("离线自检不提供向量检索")

    def retrieve(self, query: str, domain: Optional[str] = None,
                 top_k: int = 5, timeout: float = 30.0) -> List[Card]:
        # 离线模式没有 sidecar，但 /health 已声明 bm25 能力，因此这里用本地
        # 检索器兑现该承诺（§6.1 的确定性选择逻辑：bm25 不依赖 sidecar）。
        from ..knowledge import default_retriever

        return default_retriever().retrieve(query, domain, top_k)

    def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)
