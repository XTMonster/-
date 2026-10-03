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
from .editor import EDITOR_TOOL_NAME
from .review import REVIEW_TOOL_NAME
from .understand import BRIEF_TOOL_NAME


def _heading_of(script: str) -> str:
    first_line = ""
    for raw in (script or "").splitlines():
        text = raw.strip()
        if text:
            first_line = text[:40]
            break
    return first_line or "未命名场景"


def _default_two_shots() -> list:
    """历史默认：不绑剧本时的 2 镜计划。

    ``tools/run_tests.ps1`` 的 ``[4/25]`` 链路（``--offline --build``，不传
    ``--script``）与 ``tests/test_driver.py`` 的短剧本都建立在这 2 镜之上，
    因此"没有脚本 / 脚本没有镜号"时必须原样保留（v1.4 §3.1 的硬约束）。
    """
    return {
        "shot_id": "shot_001",
        "order": 1,
        "intent": "建立场景与人物关系",
        "intent_type": "铺垫",
        "shot_type": "MLS",
        "duration_frames": 96,
        "characters": ["char_001", "char_002"],
        "dialogue_ids": [],
        "prompt": "",
        "axis_note": "以两人连线建立轴线",
        "continuity_in": "开场",
    }, {
        "shot_id": "shot_002",
        "order": 2,
        "intent": "推进对话，给出反应",
        "intent_type": "推进",
        "shot_type": "MCU",
        "duration_frames": 120,
        "characters": ["char_002"],
        "dialogue_ids": [],
        "prompt": "",
        "axis_note": "保持轴线同侧",
        "continuity_in": "承接 shot_001 的站位",
    }


def shots_from_declarations(declarations, *, fps: int = 24) -> list:
    """按分镜表的**声明镜数**造出对应的 mock 镜头（v1.4 §3.1 / R46）。

    每镜的 ``duration_frames = frames_from_seconds(声明秒, fps)``：只对齐镜数
    不对齐时长会让 RK-11 的帧数等式（``total_frames == Σ frames_from_seconds``）
    在离线通路上必破。声明缺失才退回引擎估算（这里用一个保守的 96 帧）。
    角色名映射成 ``char_NNN``（按首次出现顺序）以保持剧组 id 规范。
    """
    from ..layer1_input.timing import frames_from_seconds

    mapping = {}
    shots = []
    for index, declared in enumerate(declarations or [], start=1):
        names = [str(name) for name in (getattr(declared, "characters", []) or [])]
        for name in names:
            if name not in mapping:
                mapping[name] = f"char_{len(mapping) + 1:03d}"
        seconds = getattr(declared, "declared_seconds", None)
        frames = (frames_from_seconds(seconds, fps) if seconds
                  else 96)
        shots.append({
            "shot_id": f"shot_{index:03d}",
            "order": index,
            "intent": (f"镜号{getattr(declared, 'shot_number', index)}："
                       f"{getattr(declared, 'field', lambda *_: '')('作用') or '推进叙事'}"),
            #: 离线链路也要走 `意图=` 这条路，否则"契约串含意图"这件事
            #: 在链上**从来没有被跑过**（探针全绿也可能全是没接线）。
            #: 取值按声明镜号在闭集里轮转：确定性、可复算、不猜导演意图。
            "intent_type": ("铺垫", "推进", "揭示", "收束")[index % 4],
            "shot_type": str(getattr(declared, "shot_type", "") or "MS"),
            "duration_frames": int(frames),
            "characters": [mapping[name] for name in names],
            "dialogue_ids": [],
            "prompt": "",
            "axis_note": "",
            "continuity_in": "",
        })
    return shots


def demo_plan_dict(script: str, declarations=None) -> dict:
    """阶段 A 的确定性产物：**拍摄清单**，不含动作与对白。

    与 §7.2 的 schema 一致——每镜的细节由阶段 B1（`demo_draft_dict`）逐镜补齐。
    ``declarations``（分镜表声明）非空时按声明出对应镜数的计划；否则保持 2 镜。
    """
    shots = shots_from_declarations(declarations) or list(_default_two_shots())
    return {
        "scene_heading": _heading_of(script),
        "continuity_notes": ["离线自检模式生成，仅供链路验证"],
        "shots": shots,
    }


#: 阶段 B1 的确定性草案（索引 = 第几个镜头）
DEMO_DRAFTS = (
    {"shot_id": "shot_001", "shot_type": "MLS",
     "actions": [{"character_id": "char_001", "action_type": "nod",
                  "start_frame": 1, "end_frame": 96, "params": {"cycles": 2}}]},
    {"shot_id": "shot_002", "shot_type": "MCU",
     "actions": [{"character_id": "char_002", "action_type": "sit",
                  "start_frame": 1, "end_frame": 60, "params": {"drop": 0.2}}]},
)


def demo_draft_dict(index: int) -> dict:
    """阶段 B1 的确定性草案：让离线链路的场景与拆分前**完全一致**。"""
    if not DEMO_DRAFTS or index >= len(DEMO_DRAFTS):
        # 计划比内置夹具长时给空草案：宁可"这一镜没有动作"，也不要重复上一个
        # 镜头的动作——那会在场景里造出与计划不符的表演。
        return {"shot_id": f"shot_{index + 1:03d}"}
    draft = dict(DEMO_DRAFTS[index])
    draft.setdefault("characters", [])
    draft.setdefault("dialogues", [])
    draft.setdefault("camera", {})
    draft.setdefault("prompt", "")
    return draft


#: 阶段 S 的确定性夹具。刻意**不含 gaze**：离线链路的角色 id（char_001）
#: 与剧本里的角色名（周野/林可）不是一回事，硬写注视关系只会造出
#: "引用了不在角色表里的角色"这种假告警。注视关系另有专门的单测覆盖。
DEMO_BRIEF: dict = {
    "beats": [
        {"id": "beat_001", "summary": "建立场景与人物关系",
         "participants": [], "emotion": "平静", "function": "建立"},
        {"id": "beat_002", "summary": "推进对话，给出反应",
         "participants": [], "emotion": "推进", "function": "推进"},
    ],
    "notes": ["离线自检：SceneBrief 为确定性夹具，不含注视关系"],
}


class OfflineTransport:
    """实现 LLMTransport 协议的离线替身。"""

    def __init__(self, plan: Optional[dict] = None, drafts: Optional[list] = None,
                 fail_times: int = 0,
                 brief: Optional[dict] = None,
                 declarations: Optional[list] = None,
                 fps: int = 24) -> None:
        self._plan = plan
        self._drafts = list(drafts) if drafts is not None else None
        self._brief = dict(brief) if brief is not None else dict(DEMO_BRIEF)
        self._declarations = list(declarations) if declarations else None
        self._fps = int(fps or 24)
        self.fail_times = fail_times
        self.chat_calls = 0
        self._editor_calls = 0
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

        if payload.purpose is Purpose.UNDERSTAND:
            # 阶段 S：给一份确定性夹具。离线链路因此也能走到
            # brief_received → 计划提示注入 → R013 这一整套接线。
            call = ToolCall(id=f"brief_{self.chat_calls}",
                            function=FunctionCall(
                                name=BRIEF_TOOL_NAME,
                                arguments=json.dumps(self._brief,
                                                     ensure_ascii=False)))
            return ChatReply(content=None, tool_calls=[call],
                             request_id=payload.request_id, model="offline",
                             finish_reason="tool_calls")

        if payload.purpose is Purpose.EDITOR:
            # 阶段 B1：把这一镜已有的细节（demo 计划里带着）作为确定性草案回给
            # 驱动器。顺序与计划一致，因此离线链路完全可复现。
            draft = self._draft_for(self._editor_calls)
            self._editor_calls += 1
            call = ToolCall(id=f"draft_{self._editor_calls}",
                            function=FunctionCall(
                                name=EDITOR_TOOL_NAME,
                                arguments=json.dumps(draft, ensure_ascii=False)))
            return ChatReply(content=None, tool_calls=[call],
                             request_id=payload.request_id, model="offline",
                             finish_reason="tool_calls")

        script = ""
        for message in payload.messages:
            if message.content and "<untrusted_script_content>" in message.content:
                script = message.content.split("<untrusted_script_content>", 1)[1]
                script = script.split("</untrusted_script_content>", 1)[0]
                break
        plan = self._plan or demo_plan_dict(script,
                                            declarations=self._declarations)
        #: v1.5 长分镜表分块出计划：请求的 `metadata.plan_chunk` 说明这一问覆盖
        #: 分镜表的哪一段，离线替身按**同一份段描述**切片——切成几段由
        #: `planner.plan_chunks` 单一真源决定，替身只做"这一段的镜头"。不切片的话
        #: 每一段都会回全表，合并后镜数翻三倍（离线链路与真实链路当场分叉）。
        chunk = (payload.metadata or {}).get("plan_chunk") or {}
        if chunk and int(chunk.get("total") or 0) > 1:
            start = int(chunk.get("start") or 0)
            stop = int(chunk.get("stop") or 0)
            plan = dict(plan)
            plan["shots"] = list(plan.get("shots") or [])[start:stop]
        call = ToolCall(
            id=f"call_{self.chat_calls}",
            function=FunctionCall(name=PLAN_TOOL_NAME,
                                  arguments=json.dumps(plan, ensure_ascii=False)),
        )
        return ChatReply(content=None, tool_calls=[call], request_id=payload.request_id,
                         model="offline", finish_reason="tool_calls")

    def _draft_for(self, index: int) -> dict:
        """第 index 个镜头的草案。给了自定义计划就沿用它的镜号。"""
        if self._drafts is not None and self._drafts:
            draft = dict(self._drafts[min(index, len(self._drafts) - 1)])
            draft.setdefault("characters", [])
            draft.setdefault("dialogues", [])
            draft.setdefault("camera", {})
            draft.setdefault("prompt", "")
            return draft
        draft = demo_draft_dict(index)
        shots = (self._plan or {}).get("shots", [])
        if shots:
            shot = shots[min(index, len(shots) - 1)]
            draft["shot_id"] = shot.get("shot_id", draft["shot_id"])
            draft.setdefault("shot_type", str(shot.get("shot_type", "MS")))
        return draft

    def health(self, timeout: float = 2.0) -> HealthStatus:
        return HealthStatus(status="ok", version="1.3.0",
                            capabilities=[Capability.LLM, Capability.BM25],
                            detail="offline transport")

    def set_declarations(self, declarations, *, fps: int = 24) -> None:
        """绑定分镜表声明：离线计划的镜数与时长据此生成（v1.4 BW-3）。"""
        self._declarations = list(declarations) if declarations else None
        self._fps = int(fps or 24)

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
