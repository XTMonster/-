"""G8-MT：``config.llm.max_tokens`` 必须到达每一次逐镜 LLM 请求。

背景（run 62e83217414c，见 ``work/ds_agents/g8z_real_run_r2.last.md``）：验收配置
``llm.max_tokens=65536``，但 editor / react / repair 的请求没带它，全部掉回 sidecar
的 8192 回退——50 次 ``llm_error`` 全是 ``finish_reason=length``，13 份编辑器草案
全部 502。阶段 S（brief）与阶段 A（plan）本来就带；本卡把同一取法接到逐镜请求上，
并钉住三条容易被漏掉的路径：

* react 延续轮（``_start_react_turn`` 里直接构造的 ChatPayload）；
* repair 延续轮（``_continue_repair`` 里直接构造的 ChatPayload）；
* 编辑器候选重发（``_finish_editor_turn`` 复用 ``_editor_payload_cache``）。
"""

from __future__ import annotations

import json

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.contracts.plan import ShotPlan
from block_director.layer5_orchestrator.driver import (
    DriverLimits,
    PrevisDriver,
    default_registry,
)
from block_director.layer5_orchestrator.editor import (
    EDITOR_TOOL_NAME,
    build_editor_payload,
)
from block_director.layer5_orchestrator.offline import demo_plan_dict
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.react import build_react_payload
from block_director.layer5_orchestrator.repair import build_repair_payload
from block_director.layer5_orchestrator.review import build_review_payload
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from stage_helpers import is_understand, understand_reply
from test_driver import InlineThread
from test_driver_repair import FakeAuditor, TrivialBuilder

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def _shot() -> ShotPlan:
    return ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "精修这一镜",
        "shot_type": "MS", "duration_frames": 48,
        "characters": ["char_001"]})


def _audit() -> AuditResult:
    return AuditResult(
        passed=False, target="shot_001", score=55.0,
        errors=[AuditError(rule="COMPOSITION", code="E_CAM_001",
                           message="构图分低", target="shot_001")])


def _draft(shot_id: str) -> dict:
    """一份合法的极简单镜草案（``extract_draft`` 接受、不含动作）。"""
    return {"shot_id": shot_id, "shot_type": "MS", "characters": [],
            "actions": [], "dialogues": [], "camera": {}, "prompt": ""}


def _registry():
    registry = default_registry()
    registry.add(name="setup_camera", description="fix",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda **kwargs: "相机已重设")
    registry.add(name="get_scene_state", description="query",
                 parameters={"type": "object", "properties": {}},
                 handler=lambda **kwargs: "场景状态（测试替身）")
    return registry


def _config(max_tokens: int = 65536) -> AppConfig:
    config = AppConfig()
    config.llm.max_tokens = max_tokens
    config.orchestration.self_review = True
    config.orchestration.draft_candidates = 2
    config.orchestration.react_max_steps = 4
    config.orchestration.repair_max_turns = 3
    return config


class CapturingTransport:
    """按阶段回放整条链路，并把**每一份**发出去的载荷存下来。

    修复：第一轮只读（``get_scene_state``）⇒ 触发延续轮；第二轮动手
    （``setup_camera``）⇒ 收尾。ReAct：第一轮调用工具、第二轮无工具调用 ⇒
    覆盖 `_start_react_turn` 的两次构造。编辑器：``draft_candidates=2`` ⇒
    同一镜两次候选走缓存重发。
    """

    def __init__(self):
        self.payloads = []
        self._editor_drafts = ["shot_001", "shot_001", "shot_002", "shot_002"]
        self._repair_replies = ["get_scene_state", "setup_camera"]
        self._repair_index = 0
        self._react_replies = [("setup_camera", {}), None]
        self._react_index = 0

    def _call(self, name, args):
        return ChatReply(tool_calls=[ToolCall(
            id=f"c{len(self.payloads)}",
            function=FunctionCall(name=name,
                                  arguments=json.dumps(args,
                                                       ensure_ascii=False)))])

    def chat(self, payload, timeout=120.0):
        self.payloads.append(payload)
        if is_understand(payload):
            return understand_reply(payload.request_id)
        if payload.purpose is Purpose.PLAN:
            return self._call(PLAN_TOOL_NAME, demo_plan_dict(SCRIPT))
        if payload.purpose is Purpose.EDITOR:
            shot_id = self._editor_drafts.pop(0)
            return self._call(EDITOR_TOOL_NAME, _draft(shot_id))
        if payload.purpose is Purpose.REPAIR:
            name = self._repair_replies[self._repair_index]
            self._repair_index += 1
            return self._call(name, {})
        if payload.purpose is Purpose.REACT:
            item = self._react_replies[self._react_index]
            self._react_index += 1
            if item is None:
                return ChatReply(content="已经足够好", tool_calls=[],
                                 request_id=payload.request_id)
            name, args = item
            return self._call(name, args)
        if payload.purpose is Purpose.REVIEW:
            return self._call("submit_review", {
                "verdict": "ok", "notes": "通过", "issues": [],
                "suggestion": ""})
        return ChatReply(content="ok", tool_calls=[])

    def cancel(self, request_id):
        return None


_UNSET = object()


def _driver(transport, *, max_tokens=65536, config=_UNSET):
    return PrevisDriver(
        transport=transport, audit=AuditLogger(), script=SCRIPT,
        config=_config(max_tokens) if config is _UNSET else config,
        builder=TrivialBuilder(),
        auditor=FakeAuditor([_audit()] * 3,
                            shots=("shot_001", "shot_002")),
        registry=_registry(), thread_factory=InlineThread,
        limits=DriverLimits(max_repairs_per_shot=1))


# --------------------------------------------------------------------------- #
# 构造器级：新加的 kwarg 原样流进 ChatPayload
# --------------------------------------------------------------------------- #
def test_build_react_payload_max_tokens_kwarg():
    registry = default_registry()
    assert build_react_payload(
        _shot(), _audit(), registry=registry, max_tokens=65536
    ).max_tokens == 65536
    assert build_react_payload(
        _shot(), _audit(), registry=registry).max_tokens is None


def test_build_repair_payload_max_tokens_kwarg():
    registry = default_registry()
    assert build_repair_payload(
        _audit(), registry, max_tokens=65536).max_tokens == 65536
    assert build_repair_payload(_audit(), registry).max_tokens is None


def test_build_review_payload_max_tokens_kwarg():
    assert build_review_payload(
        intent="x", shot_type="MS", duration_frames=48,
        max_tokens=65536).max_tokens == 65536
    assert build_review_payload(
        intent="x", shot_type="MS", duration_frames=48).max_tokens is None


def test_build_editor_payload_max_tokens_kwarg_still_flows():
    assert build_editor_payload(
        _shot(), None, max_tokens=65536).max_tokens == 65536
    assert build_editor_payload(_shot(), None).max_tokens is None


# --------------------------------------------------------------------------- #
# 驱动级：配置值到达每一次发出去的请求
# --------------------------------------------------------------------------- #
def test_configured_max_tokens_reaches_every_per_shot_request():
    transport = CapturingTransport()
    driver = _driver(transport, max_tokens=65536)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver._llm_max_tokens() == 65536

    purposes = [payload.purpose for payload in transport.payloads]
    for purpose in (Purpose.UNDERSTAND, Purpose.PLAN, Purpose.EDITOR,
                    Purpose.REACT, Purpose.REPAIR, Purpose.REVIEW):
        assert purpose in purposes, f"本次运行必须覆盖 {purpose}"
    for payload in transport.payloads:
        assert payload.max_tokens == 65536, (
            f"{payload.purpose} 的 max_tokens 应为 65536，"
            f"实际 {payload.max_tokens}")

    editor = [p for p in transport.payloads if p.purpose is Purpose.EDITOR]
    react = [p for p in transport.payloads if p.purpose is Purpose.REACT]
    repair = [p for p in transport.payloads if p.purpose is Purpose.REPAIR]
    review = [p for p in transport.payloads if p.purpose is Purpose.REVIEW]
    assert len(editor) == 4, "2 镜 × 2 候选 = 4 次编辑器请求（含候选重发）"
    assert len(react) == 2, "首轮 + 延续轮 = 2 次 ReAct 请求"
    assert len(repair) == 2, "首轮 + 延续轮 = 2 次修复请求"
    assert len(review) == 1, "shot_002 通过后应走一次 Level 2 自我审核"
    # 候选重发走的是 `_editor_payload_cache`：同一对象，max_tokens 必然一致。
    assert editor[0] is editor[1], "候选重发必须复用缓存的编辑器载荷"
    assert editor[2] is editor[3], "第二镜的候选重发同样复用缓存载荷"


def test_zero_max_tokens_leaves_the_field_none():
    transport = CapturingTransport()
    driver = _driver(transport, max_tokens=0)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver._llm_max_tokens() is None
    assert transport.payloads, "必须真的发过请求"
    assert all(payload.max_tokens is None for payload in transport.payloads)


def test_no_config_leaves_the_field_none():
    transport = CapturingTransport()
    driver = _driver(transport, config=None)
    assert driver.run_to_completion() is DriverState.DONE
    assert transport.payloads, "必须真的发过请求"
    assert all(payload.max_tokens is None for payload in transport.payloads)
