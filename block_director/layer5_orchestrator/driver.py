"""预演驱动器：与 Blender 解耦的状态机（执行文档 v1.2 §3.2 / §3.3）。

设计红线：
- 本模块 **不得 import bpy**（§2.4）。它只编排，不碰场景。
- ``step()`` 每次只做一件小事并立即返回，绝不阻塞（LLM 调用在后台线程）。
- ``step()`` 必须在主线程调用（用 threading_guard 强制），因为它接下来会
  调用触碰 bpy 的工具。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..contracts.enums import Purpose
from ..contracts.audit import AuditResult
from ..contracts.messages import (
    ChatPayload,
    ChatReply,
    Message,
    MessageRole,
    assistant_message,
    new_request_id,
    tool_message,
    validate_conversation,
)
from ..contracts.plan import Plan
from ..layer6_audit.audit_logger import AuditLogger
from ..utils.logger import get_logger
from ..utils.threading_guard import assert_main_thread
from .planner import EMIT_PLAN_TOOL_PARAMETERS, PLAN_TOOL_NAME, build_plan_payload
from .repair import build_repair_payload
from .budget import Budget, BudgetLimits
from .loop_detector import LoopDetector
from .human_gate import GateDecision, GateRequest, HumanGate
from .review import ReviewVerdict, build_review_payload, parse_review
from .states import TERMINAL_STATES, DriverState
from .tool_registry import ToolRegistry

log = get_logger("driver")


@dataclass
class DriverLimits:
    """运行护栏（§12.6）。"""

    max_steps: int = 4000
    max_llm_calls: int = 8
    llm_timeout_s: float = 120.0
    plan_attempts: int = 2
    max_tool_calls: int = 200
    max_repairs_per_shot: int = 2      # §7.1 B4：每镜定向修复次数上限


@dataclass
class DriverEvent:
    """给 UI / 日志的事件。"""

    kind: str
    message: str
    state: DriverState
    data: Dict[str, Any] = field(default_factory=dict)


def default_registry() -> ToolRegistry:
    """Phase 0 的最小工具集：只有阶段 A 的 emit_plan。"""
    registry = ToolRegistry()
    registry.add(
        name=PLAN_TOOL_NAME,
        description="提交白模预演的分镜计划（阶段 A 的唯一合法产出）",
        parameters=EMIT_PLAN_TOOL_PARAMETERS,
        handler=lambda **kwargs: f"计划已接收：{len(kwargs.get('shots', []))} 个镜头",
    )
    return registry


def _default_thread_factory(target: Callable[[], None],
                            name: str) -> threading.Thread:
    return threading.Thread(target=target, daemon=True, name=name)


class PrevisDriver:
    """一次预演生成运行的状态机。"""

    def __init__(
        self,
        *,
        transport,
        audit: AuditLogger,
        script: str = "",
        config=None,
        limits: Optional[DriverLimits] = None,
        registry: Optional[ToolRegistry] = None,
        builder: Optional[Any] = None,
        auditor: Optional[Any] = None,
        scene_state_provider: Optional[Callable[[], str]] = None,
        loop_detector: Optional[LoopDetector] = None,
        budget: Optional[Budget] = None,
        human_gate: Optional[HumanGate] = None,
        observers: Optional[List[Callable[[DriverEvent], None]]] = None,
        clock: Callable[[], float] = time.monotonic,
        thread_factory: Callable[..., Any] = _default_thread_factory,
    ) -> None:
        self.transport = transport
        self.audit = audit
        self.script = script
        self.config = config
        self.limits = limits or DriverLimits()
        self.registry = registry or default_registry()
        self.builder = builder
        self.auditor = auditor
        self.scene_state_provider = scene_state_provider
        self.loop_detector = loop_detector or LoopDetector()
        self.budget = budget or Budget(
            BudgetLimits(max_llm_calls=self.limits.max_llm_calls))
        self.degraded_reason = ""
        self.human_gate = human_gate
        self._gate_request: Optional[GateRequest] = None
        self._gate_decision: Optional[GateDecision] = None
        self._gate_resume: DriverState = DriverState.FINISHING
        self.gate_history: List[Dict[str, Any]] = []
        self._reviewed_shots: set = set()
        self._pending_review: Optional[str] = None
        self.review_history: List[Dict[str, Any]] = []
        self.clock = clock
        self.thread_factory = thread_factory

        self.state = DriverState.IDLE
        self.plan: Optional[Plan] = None
        self.build_summary: Dict[str, Any] = {}
        self.audit_results: List[AuditResult] = []
        self.error: str = ""
        self.messages: List[Message] = []

        self._observers: List[Callable[[DriverEvent], None]] = list(observers or [])
        self._steps = 0
        self._llm_calls = 0
        self._tool_calls = 0
        self._plan_attempts = 0
        self._reply_q: "queue.Queue[tuple]" = queue.Queue()
        self._cancel = threading.Event()
        self._call_started = 0.0
        self._pending_request_id = ""
        self._plan_problem = ""
        self._call_purpose = "plan"
        self._shot_queue: List[str] = []
        self._current_shot_id = ""
        self._repair_attempts = 0
        self._repairs_total = 0
        self._pending_audit: Optional[AuditResult] = None
        self.repair_messages: List[Message] = []

    # ------------------------------------------------------------ 对外接口
    def add_observer(self, observer: Callable[[DriverEvent], None]) -> None:
        self._observers.append(observer)

    def cancel(self) -> None:
        """请求取消（协作式，§3.4）：不杀线程，只置标志并尽力通知对端。"""
        self._cancel.set()
        if self._pending_request_id:
            try:
                self.transport.cancel(self._pending_request_id)
            except Exception as exc:  # noqa: BLE001 - 取消失败不阻断
                log.debug("取消请求失败: %s", exc)

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL_STATES

    def snapshot(self) -> Dict[str, Any]:
        """给 UI 的只读快照。"""
        return {
            "run_id": self.audit.run_id,
            "state": self.state.value,
            "steps": self._steps,
            "llm_calls": self._llm_calls,
            "tool_calls": self._tool_calls,
            "shots": len(self.plan.shots) if self.plan else 0,
            "total_frames": self.plan.total_frames if self.plan else 0,
            "built": bool(self.build_summary),
            "build": dict(self.build_summary),
            "current_shot": self._current_shot_id,
            "shots_remaining": len(self._shot_queue),
            "audits": len(self.audit_results),
            "repairs": self._repairs_total,
            "shot_repairs": self._repair_attempts,
            "budget": self.budget.summary,
            "loops": self.loop_detector.stats,
            "degraded_reason": self.degraded_reason,
            "error": self.error,
        }

    # ------------------------------------------------------------ 状态机
    def step(self) -> bool:
        """推进一小步；返回 False 表示运行已终止。"""
        assert_main_thread("PrevisDriver.step")
        if self.state in TERMINAL_STATES:
            return False

        self._steps += 1
        if self._steps > self.limits.max_steps:
            self._fail("超出最大步数（疑似死循环）")
            return False
        exhausted = self.budget.exhausted_reason()
        if exhausted and self.state is DriverState.PLANNING:
            # 还没产出计划就触顶：降级收尾（构建与审核不花预算，不该被砍）
            self._degrade_to_finish(exhausted)
            return True
        if self._cancel.is_set() and self.state is not DriverState.CANCELLED:
            self._transition(DriverState.CANCELLED)
            self.audit.log("run_cancelled", "运行已取消", level="warning")
            return False

        handler = getattr(self, f"_step_{self.state.value.lower()}")
        handler()
        return self.state not in TERMINAL_STATES

    def run_to_completion(self, poll_interval: float = 0.0,
                          max_wall_s: Optional[float] = None) -> DriverState:
        """headless 用：同步把状态机推到终止。"""
        started = self.clock()
        while self.step():
            if max_wall_s is not None and self.clock() - started > max_wall_s:
                self._fail(f"超出墙上时间上限 {max_wall_s}s")
                break
            if poll_interval and self.state is DriverState.CALLING_LLM:
                time.sleep(poll_interval)
        return self.state

    # ------------------------------------------------------------ 各状态
    def _step_idle(self) -> None:
        self.audit.log("run_started", "开始白模预演生成",
                       transport=type(self.transport).__name__,
                       registry=self.registry.names())
        self._emit("run_started", "开始")
        self._transition(DriverState.PLANNING)

    def _step_planning(self) -> None:
        if not self.budget.allow_llm_call("plan"):
            self._degrade_to_finish(self.budget.exhausted_reason()
                                    or "LLM 调用预算耗尽")
            return
        if self._plan_attempts >= self.limits.plan_attempts:
            detail = f"：{self._plan_problem}" if self._plan_problem else ""
            self._fail(f"分镜计划生成失败（已达最大尝试次数）{detail}")
            return
        self._plan_attempts += 1
        self._start_plan_call()

    def _step_calling_llm(self) -> None:
        try:
            kind, payload = self._reply_q.get_nowait()
        except queue.Empty:
            return                                  # 仍在等待，下一 tick 再看
        duration = self.clock() - self._call_started
        repairing = self._call_purpose == "repair"
        purpose = str(Purpose.REPAIR if repairing else Purpose.PLAN)

        if kind == "err":
            self.budget.record_llm(None)
            self.audit.log("llm_error", str(payload), level="error",
                           request_id=self._pending_request_id)
            self.audit.log_llm(purpose, None, duration,
                               self._pending_request_id, error=str(payload))
            # 计划失败由 _step_planning 决定是否再试；修复失败则回到复核
            self._transition(DriverState.CHECKING if repairing
                             else DriverState.PLANNING)
            return

        reply: ChatReply = payload
        self.budget.record_llm(reply.usage)
        self.audit.log_llm(purpose, reply, duration, self._pending_request_id)

        if repairing:
            problem = self._dispatch_tool_calls(reply, self.repair_messages)
            if problem:
                self.audit.log("repair_invalid", problem, level="warning")
            self._repair_attempts += 1
            self._repairs_total += 1
            self._transition(DriverState.CHECKING)   # 复核一次，看改没改对
            return

        if self._call_purpose == "review":
            self._finish_review(reply)
            return

        problem = self._dispatch_tool_calls(reply, self.messages)
        if problem:
            self._plan_problem = problem
            self.audit.log("plan_invalid", problem, level="error")
            self._transition(DriverState.PLANNING)
            return
        # 有场景构建器就把计划落成场景（§7.1 阶段 B2），否则只产出计划
        target = (DriverState.BUILDING if self.builder is not None
                  else DriverState.FINISHING)
        if self._gate_enabled("human_gate_on_plan"):
            self._request_gate(
                GateRequest(kind="plan", title="确认分镜计划",
                            detail=self._plan_gate_detail(),
                            payload={"shots": len(self.plan.shots)
                                     if self.plan else 0}),
                resume=target)
            return
        self._transition(target)

    def _plan_gate_detail(self) -> str:
        if self.plan is None:
            return "（没有计划）"
        lines = [f"共 {len(self.plan.shots)} 个镜头，"
                 f"{self.plan.total_frames} 帧"
                 f"（约 {self.plan.total_frames / 24:.1f} 秒）"]
        for shot in self.plan.shots:
            lines.append(f"- {shot.shot_id} {shot.shot_type} "
                         f"{shot.duration_frames} 帧：{shot.intent}")
        return "\n".join(lines)

    def _gate_enabled(self, setting: str) -> bool:
        if self.human_gate is None or self.config is None:
            return False
        return bool(getattr(self.config.audit, setting, False))

    def _request_gate(self, request: GateRequest, resume: DriverState) -> None:
        """发起审批。返回 PENDING 时切到 AWAIT_HUMAN，期间不阻塞。"""
        self._gate_request = request
        self._gate_resume = resume
        try:
            decision = self.human_gate.request(request)
        except Exception as exc:  # noqa: BLE001 - 门坏了不该拖垮整场
            self.audit.log("gate_failed", f"{type(exc).__name__}: {exc}",
                           level="warning", kind=request.kind)
            decision = GateDecision.SKIPPED
        self.audit.log("gate_requested", request.title, kind=request.kind,
                       request_id=request.request_id)
        if decision is GateDecision.PENDING:
            self._gate_decision = None
            self._transition(DriverState.AWAIT_HUMAN)
            return
        self._apply_gate(decision)

    def _apply_gate(self, decision: GateDecision) -> None:
        request = self._gate_request
        kind = request.kind if request else ""
        title = request.title if request else ""
        self.gate_history.append({"kind": kind, "title": title,
                                  "decision": str(decision)})
        self.audit.log("gate_decided", f"{title} → {decision}", kind=kind)
        self._emit("gate_decided", f"{title} → {decision}", kind=kind,
                   decision=str(decision))
        self._gate_request = None
        self._gate_decision = decision
        if decision is GateDecision.REJECTED:
            self.degraded_reason = f"人工审批未通过：{title}"
            self.audit.log("gate_rejected", self.degraded_reason,
                           level="warning", kind=kind)
            self._transition(DriverState.CANCELLED)
            return
        if kind == "axis_violation":
            # 人工已过目并放行该镜头：收下现状，继续下一镜
            self._advance_shot()
            return
        self._transition(self._gate_resume)

    def _step_await_human(self) -> None:
        """等待用户点击；期间只轮询，不阻塞事件循环。"""
        request = self._gate_request
        if request is None:
            self._transition(self._gate_resume)
            return
        try:
            decision = self.human_gate.poll(request.request_id)
        except Exception as exc:  # noqa: BLE001
            self.audit.log("gate_poll_failed", f"{type(exc).__name__}: {exc}",
                           level="warning")
            decision = None
        if decision is None or decision is GateDecision.PENDING:
            return                      # 继续等
        self._apply_gate(decision)

    def _step_building(self) -> None:
        """把分镜计划交给场景构建器（bpy 实现在 layer3_engine/shot_builder.py）。"""
        plan = self.plan or Plan()
        if self.builder is None:
            self._transition(DriverState.FINISHING)
            return
        started = self.clock()
        try:
            summary = self.builder.build(plan) or {}
        except Exception as exc:  # noqa: BLE001 - 构建失败要如实上报并降级
            self.audit.log("build_failed", f"{type(exc).__name__}: {exc}",
                           level="error")
            self._fail(f"场景构建失败：{type(exc).__name__}: {exc}")
            return
        self.build_summary = dict(summary)
        duration = self.clock() - started
        self.audit.log("scene_built", "场景已构建",
                       duration_s=round(duration, 3),
                       **{k: v for k, v in self.build_summary.items()
                          if isinstance(v, (int, float, str))})
        self._emit("scene_built", "场景已构建",
                   **{k: v for k, v in self.build_summary.items()
                      if isinstance(v, (int, float, str))})
        self._transition(self._after_build_state())

    def _after_build_state(self) -> DriverState:
        """建完场景后：有审核器就先逐镜校验（§7.1 B3），否则直接收尾。"""
        if self.auditor is not None:
            shots = [str(s) for s in self.auditor.shot_ids()]
            if shots:
                self._shot_queue = shots
                self._current_shot_id = shots[0]
                self._repair_attempts = 0
                return DriverState.CHECKING
        return DriverState.FINISHING

    def _step_checking(self) -> None:
        """§7.1 B3：逐镜头校验；不通过就进入定向修复。"""
        if self.auditor is None or not self._shot_queue:
            self._transition(DriverState.FINISHING)
            return
        shot_id = self._shot_queue[0]
        self._current_shot_id = shot_id
        try:
            result = self.auditor.audit(shot_id)
        except Exception as exc:  # noqa: BLE001 - 审核器自身出错不该拖垮整场
            self.audit.log("audit_failed",
                           f"{shot_id} 审核器异常：{type(exc).__name__}: {exc}",
                           level="error", shot=shot_id)
            self._emit("audit_failed", f"{shot_id} 审核异常", shot=shot_id)
            self._advance_shot()
            return
        self.audit_results.append(result)
        self.audit.log("shot_audit", f"{shot_id}: {result.format_for_llm().splitlines()[0]}",
                       level="info" if result.passed else "warning",
                       shot=shot_id, passed=result.passed,
                       errors=len(result.errors), warnings=len(result.warnings))
        self._emit("shot_audit",
                   f"{shot_id} {'通过' if result.passed else '未通过'}",
                   shot=shot_id, passed=result.passed)

        if result.passed:
            if self._should_self_review(shot_id):
                self._pending_review = shot_id
                self._transition(DriverState.REVIEWING)
                return
            self._advance_shot()
            return
        if self._repair_attempts >= self.limits.max_repairs_per_shot:
            self.audit.log("shot_degraded",
                           f"{shot_id} 达到修复上限（{self._repair_attempts}），"
                           f"按降级处理并继续", level="warning", shot=shot_id)
            self._emit("shot_degraded", f"{shot_id} 降级", shot=shot_id)
            axis_violation = any(item.rule == "R001" for item in result.errors)
            if axis_violation and self._gate_enabled(
                    "human_gate_on_axis_violation"):
                self._request_gate(
                    GateRequest(kind="axis_violation",
                                title=f"{shot_id} 越轴且自动修复未成功",
                                detail=result.format_for_llm(),
                                payload={"shot_id": shot_id}),
                    resume=DriverState.CHECKING)
                return
            self._advance_shot()
            return
        self._pending_audit = result
        self._transition(DriverState.REPAIRING)

    def _advance_shot(self) -> None:
        if self._shot_queue:
            self._shot_queue.pop(0)
        self._repair_attempts = 0
        self.repair_messages = []
        if self._shot_queue:
            self._current_shot_id = self._shot_queue[0]
        self._transition(DriverState.CHECKING)

    # -------------------------------------------------- Level 2 自我审核（§11.1）
    def _should_self_review(self, shot_id: str) -> bool:
        if self.config is None:
            return False
        if not getattr(self.config.orchestration, "self_review", False):
            return False
        if shot_id in self._reviewed_shots or self.plan is None:
            return False
        return any(shot.shot_id == shot_id for shot in self.plan.shots)

    def _shot_plan(self, shot_id: str):
        if self.plan is None:
            return None
        for shot in self.plan.shots:
            if shot.shot_id == shot_id:
                return shot
        return None

    def _step_reviewing(self) -> None:
        """§7.10：把自我审核做成独立回合，而不是工具内部的同步调用。"""
        shot_id = self._pending_review or self._current_shot_id
        self._pending_review = None
        shot = self._shot_plan(shot_id)
        if shot is None:
            self._advance_shot()
            return
        temperature = 0.2
        if self.config is not None:
            temperature = float(self.config.llm.temperature_repair)
        payload = build_review_payload(
            intent=shot.intent, shot_type=str(shot.shot_type),
            duration_frames=shot.duration_frames,
            audit=self.audit_results[-1] if self.audit_results else None,
            scene_state=self._scene_state_text(), temperature=temperature)
        self._start_llm_call("review", payload, note=f"自我审核 {shot_id}")

    def _finish_review(self, reply: ChatReply) -> None:
        shot_id = self._current_shot_id
        self._reviewed_shots.add(shot_id)
        try:
            verdict = parse_review(reply)
        except ValueError as exc:
            # 结论不合规不阻断流程：规则层已经放行，这里只是少了一层复核
            self.audit.log("self_review_invalid", str(exc), level="warning",
                           shot=shot_id)
            self._advance_shot()
            return

        self.review_history.append({"shot_id": shot_id,
                                    "verdict": verdict.verdict,
                                    "notes": verdict.notes})
        if verdict.needs_fix:
            self.audit.log("self_review",
                           f"{shot_id} 复核认为未表达意图：{verdict.notes}",
                           level="warning", shot=shot_id,
                           issues=verdict.issues)
            self._emit("self_review", f"{shot_id} 需要调整", shot=shot_id)
            self._pending_audit = verdict.to_audit(shot_id)
            self._transition(DriverState.REPAIRING)
            return
        self.audit.log("self_review", f"{shot_id} 复核通过", shot=shot_id)
        self._emit("self_review", f"{shot_id} 复核通过", shot=shot_id)
        self._advance_shot()

    def _step_repairing(self) -> None:
        """§7.1 B4：把结构化违规项回灌给模型，让它调用工具修正。"""
        audit = self._pending_audit
        if audit is None:
            self._transition(DriverState.CHECKING)
            return
        self._pending_audit = None
        temperature = 0.2
        if self.config is not None:
            temperature = float(self.config.llm.temperature_repair)
        payload = build_repair_payload(
            audit, self.registry,
            scene_state=self._scene_state_text(),
            temperature=temperature)
        self._start_llm_call("repair", payload,
                             note=f"请求修复 {self._current_shot_id}"
                                  f"（第 {self._repair_attempts + 1} 次）")

    def _scene_state_text(self) -> str:
        if self.scene_state_provider is None:
            return ""
        try:
            return str(self.scene_state_provider())
        except Exception as exc:  # noqa: BLE001 - 采集失败不该拖垮运行
            return f"（场景状态采集失败：{type(exc).__name__}: {exc}）"

    def _step_finishing(self) -> None:
        plan = self.plan or Plan()
        # 会话结构自检（§3.4）：失败只告警，不阻断收尾
        problems = validate_conversation(self.messages)
        if problems:
            self.audit.log("conversation_invalid", "；".join(problems), level="warning")
        else:
            self.audit.log("conversation_ok",
                           f"{len(self.messages)} 条消息结构合法（§3.4）")
        self._transition(DriverState.DONE)
        self.audit.log("plan_received",
                       f"分镜计划完成：{len(plan.shots)} 个镜头",
                       shots=[shot.to_dict() for shot in plan.shots],
                       total_frames=plan.total_frames)
        self.audit.log("run_finished", "预演生成结束",
                       shots=len(plan.shots), llm_calls=self._llm_calls,
                       tool_calls=self._tool_calls, steps=self._steps,
                       built=bool(self.build_summary),
                       audits=len(self.audit_results),
                       failed_audits=sum(1 for r in self.audit_results
                                         if not r.passed),
                       degraded=self.degraded_reason or None,
                       budget=self.budget.summary)
        self._emit("run_finished", f"完成，共 {len(plan.shots)} 个镜头")

    # ------------------------------------------------------------ 内部
    def _start_plan_call(self) -> None:
        request_id = new_request_id()
        payload: ChatPayload = build_plan_payload(self.script, self.config,
                                                  request_id=request_id)
        self._start_llm_call("plan", payload,
                             note=f"请求分镜计划（第 {self._plan_attempts} 次尝试）")

    def _start_llm_call(self, purpose: str, payload: ChatPayload,
                        note: str = "") -> None:
        """发起一次 LLM 调用。网络在后台线程，主线程只负责发起与轮询。"""
        if not self.budget.allow_llm_call(purpose):
            self._degrade_to_finish(self.budget.exhausted_reason() or "预算耗尽")
            return
        self._call_purpose = purpose
        self._pending_request_id = payload.request_id
        self._llm_calls += 1
        self._call_started = self.clock()
        self.audit.log("llm_request", note or f"请求 {purpose}",
                       purpose=purpose, request_id=payload.request_id,
                       tools=[tool["function"]["name"] for tool in payload.tools])
        self._transition(DriverState.CALLING_LLM)

        def worker() -> None:
            # 后台线程：只做网络 I/O，绝不触碰 bpy
            try:
                reply = self.transport.chat(payload, self.limits.llm_timeout_s)
                self._reply_q.put(("ok", reply))
            except Exception as exc:  # noqa: BLE001
                self._reply_q.put(("err", f"{type(exc).__name__}: {exc}"))

        self.thread_factory(target=worker, name="bd-llm").start()

    def _dispatch_tool_calls(self, reply: ChatReply,
                             messages: Optional[List[Message]] = None) -> str:
        """执行回复里的工具调用；返回非空字符串表示本轮失败原因。"""
        conversation = self.messages if messages is None else messages
        conversation.append(assistant_message(reply))
        if not reply.tool_calls:
            return "回复中没有工具调用"

        errors: List[str] = []
        plan_seen = False
        for call in reply.tool_calls:
            if self._tool_calls >= self.limits.max_tool_calls:
                errors.append("工具调用次数超限")
                break
            try:
                args = call.function.parsed_arguments()
            except ValueError as exc:
                errors.append(str(exc))
                continue

            result = self.registry.execute(call.function.name, args)
            self._tool_calls += 1
            self.audit.count_tool_call()
            self.loop_detector.record(call.function.name, args)
            self.audit.log("tool_call",
                           f"{call.function.name} -> {'ok' if result.ok else result.error}",
                           tool=call.function.name, ok=result.ok, args=args)
            conversation.append(tool_message(call, result.content))
            self._emit("tool_call", f"{call.function.name}",
                       tool=call.function.name, ok=result.ok)

            if not result.ok:
                errors.append(f"{call.function.name}: {result.content}")
                continue
            if call.function.name == PLAN_TOOL_NAME:
                try:
                    self.plan = Plan.from_dict(args)
                    plan_seen = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"计划解析失败: {exc}")

        loop = self.loop_detector.detect()
        if loop is not None:
            self.audit.log("loop_warning", loop.message, level="warning",
                           loop_kind=loop.kind)
            self._emit("loop_warning", loop.message, loop_kind=loop.kind)
            conversation.append(Message(role=MessageRole.SYSTEM,
                                        content=loop.message))

        if errors:
            return "；".join(errors)
        if not plan_seen:
            return f"没有收到 {PLAN_TOOL_NAME} 调用"
        return ""

    def _transition(self, new_state: DriverState) -> None:
        old = self.state
        if old is new_state:
            return
        self.state = new_state
        self.audit.log("state", f"{old.value} → {new_state.value}")
        self._emit("state", f"{old.value} → {new_state.value}", state=new_state)

    def _fail(self, message: str) -> None:
        self.error = message
        self.audit.log("run_failed", message, level="error",
                       llm_calls=self._llm_calls, tool_calls=self._tool_calls)
        self._emit("run_failed", message)
        self._transition(DriverState.ERROR)

    def _degrade_to_finish(self, reason: str) -> None:
        """§12.6：预算触顶按降级收尾并如实标注，已建成的成果不丢。"""
        self.degraded_reason = reason
        self.audit.log("budget_exhausted", reason, level="warning")
        self._emit("budget_exhausted", reason)
        self._transition(DriverState.FINISHING)

    def _emit(self, kind: str, message: str, /, **data: Any) -> None:
        """``kind`` 位置专用：事件数据里可以放心带 ``kind=`` 键。"""
        if not self._observers:
            return
        event = DriverEvent(kind=kind, message=message, state=self.state,
                            data=dict(data))
        for observer in self._observers:
            try:
                observer(event)
            except Exception as exc:  # noqa: BLE001 - 观察者出错不影响主流程
                log.error("观察者回调失败: %s", exc)
