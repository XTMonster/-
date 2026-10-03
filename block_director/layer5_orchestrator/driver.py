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

from ..contracts.enums import Purpose, ToolChoice
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
from ..contracts.brief import SOURCE_DETERMINISTIC, SceneBrief
from ..contracts.enums import ErrorCode
from ..layer6_audit.audit_logger import AuditLogger
from ..utils.logger import get_logger
from ..utils.threading_guard import assert_main_thread
from .planner import (
    EMIT_PLAN_TOOL_PARAMETERS,
    PLAN_TOOL_NAME,
    build_plan_payload,
    plan_parameters,
)
from .control_tools import (
    ABORT,
    FINISH_SHOT,
    REQUEST_SELF_REVIEW,
    register_control_tools,
)
from .repair import build_repair_payload
from .budget import Budget, BudgetLimits
from .budget_formula import describe as describe_budget_formula
from .budget_formula import evaluate as evaluate_llm_call_budget
from .context_budget import budget_report, trim_messages
from .editor import build_editor_payload, extract_draft, merge_draft
from .editor import EDITOR_TOOL_NAME, EMIT_SHOT_DRAFT_PARAMETERS
from .react import build_react_payload, render_shot_memory, should_react, shot_memory
from .loop_detector import LoopDetector
from .human_gate import GateDecision, GateRequest, HumanGate
from .review import ReviewVerdict, build_review_payload, parse_review
from .states import TERMINAL_STATES, DriverState
from .tool_registry import ToolRegistry
from .understand import (
    build_brief_payload,
    deterministic_brief,
    extract_brief,
    merge_brief_gaze,
)

log = get_logger("driver")


@dataclass
class DriverLimits:
    """运行护栏（§12.6）。"""

    max_steps: int = 4000
    #: v1.4 §2.4：**硬顶**（CLI ``--max-llm-calls`` 的入口）。``0`` = 不限，
    #: 此时初值由 ``budget.max_llm_calls_ceiling`` 注入（见 ``_limits_from``）。
    #: 真正的门禁 = ``max(ceiling, formula)``，再与这里的硬顶取小。
    max_llm_calls: int = 0
    llm_timeout_s: float = 120.0
    plan_attempts: int = 2
    brief_attempts: int = 2      # §3.2：两次不理解就降级为确定性抽取
    max_tool_calls: int = 200
    max_repairs_per_shot: int = 2      # §7.1 B4：每镜定向修复次数上限


@dataclass
class DriverEvent:
    """给 UI / 日志的事件。"""

    kind: str
    message: str
    state: DriverState
    data: Dict[str, Any] = field(default_factory=dict)


def default_registry(max_shots: int = 0) -> ToolRegistry:
    """默认工具集：阶段 A 的 emit_plan + 三个控制工具（§7.4）。

    ``max_shots`` 透传给 emit_plan 的 schema（v1.4 §3.2）；``0`` = 不限，
    此时 schema 里**没有** ``maxItems`` 键。
    """
    registry = ToolRegistry()
    registry.add(
        name=PLAN_TOOL_NAME,
        description="提交白模预演的分镜计划（阶段 A 的唯一合法产出）",
        parameters=plan_parameters(max_shots),
        handler=lambda **kwargs: f"计划已接收：{len(kwargs.get('shots', []))} 个镜头",
    )
    # 单镜草案也注册进默认表：修复/精修阶段需要它来**改对白时序**——
    # 实测（真实模型）：镜头时长装不下对白（R011/S6）是最常见的违规，
    # 而 §7.4 的工具里没有"改时长/挪对白"的入口，只有重新提交这份草案。
    registry.add(
        name=EDITOR_TOOL_NAME,
        description="重新提交这一镜的完整草案（修复对白时序、动作与取景）",
        parameters=EMIT_SHOT_DRAFT_PARAMETERS,
        handler=lambda **kwargs: (
            f"草案已接收：{kwargs.get('shot_id', '?')}"),
    )
    register_control_tools(registry)
    return registry


def _default_thread_factory(target: Callable[[], None],
                            name: str) -> threading.Thread:
    return threading.Thread(target=target, daemon=True, name=name)


def _limits_from(config, limits: "DriverLimits") -> BudgetLimits:
    """把 §21.5 的预算配置翻译成账本上限。

    此前 ``config.budget`` 是**死配置**：驱动器只用 ``DriverLimits`` 里的
    调用次数上限，用户设的 ``max_cost_usd`` / ``max_wall_minutes`` 没人执行。

    v1.4 §2.4：``DriverLimits.max_llm_calls`` 初值 = ``budget.max_llm_calls_ceiling``
    （0 表示"未指定"，由配置注入）；CLI 显式给出的正数覆盖它。
    """
    if config is None or getattr(config, "budget", None) is None:
        return BudgetLimits(max_llm_calls=limits.max_llm_calls)
    budget = config.budget
    ceiling = int(getattr(budget, "max_llm_calls_ceiling", 0) or 0)
    initial = (int(limits.max_llm_calls) if int(limits.max_llm_calls) > 0
               else ceiling)
    return BudgetLimits(
        max_llm_calls=initial,
        max_cost_usd=float(getattr(budget, "max_cost_usd", 0.0) or 0.0),
        max_wall_seconds=float(getattr(budget, "max_wall_minutes", 0.0) or 0.0)
        * 60.0)


class PrevisDriver:
    """一次预演生成运行的状态机。"""

    def __init__(
        self,
        *,
        transport,
        audit: AuditLogger,
        script: str = "",
        parsed_script=None,
        config=None,
        limits: Optional[DriverLimits] = None,
        registry: Optional[ToolRegistry] = None,
        builder: Optional[Any] = None,
        auditor: Optional[Any] = None,
        scene_state_provider: Optional[Callable[[], str]] = None,
        loop_detector: Optional[LoopDetector] = None,
        budget: Optional[Budget] = None,
        human_gate: Optional[HumanGate] = None,
        knowledge: Optional[Any] = None,
        observers: Optional[List[Callable[[DriverEvent], None]]] = None,
        clock: Callable[[], float] = time.monotonic,
        thread_factory: Callable[..., Any] = _default_thread_factory,
    ) -> None:
        self.transport = transport
        self.audit = audit
        self.script = script
        self.parsed_script = parsed_script
        self.config = config
        self.limits = limits or DriverLimits()
        self.registry = registry or default_registry()
        self.builder = builder
        self.auditor = auditor
        self.scene_state_provider = scene_state_provider
        self.loop_detector = loop_detector or LoopDetector()
        self.budget = budget or Budget(_limits_from(config, self.limits))
        #: 调用方**直接**塞进来的预算账本（测试/嵌入用法）里的硬顶。
        #: §2.4 的硬顶入口是 ``limits.max_llm_calls``；但显式传入的预算对象
        #: 同样必须被尊重，否则 ``_apply_scene_budget`` 会把它顶掉。
        self._caller_budget_cap = (int(budget.limits.max_llm_calls)
                                   if budget is not None else 0)
        self.degraded_reason = ""
        self.human_gate = human_gate
        self.knowledge = knowledge
        #: E2 溯源（2026-10-01）：逐镜记下"这一镜的检索**真的注入了**哪几类知识的
        #: 哪些取值"，交付层据此写 ``movements[].source``（``theory`` /
        #: ``lesson`` / ``experience``）。此前 manifest 只有 ``declared|planned``
        #: 两个取值，E2（经验采纳率）因此**结构性恒为 0**（审查 #21）。
        self._shot_knowledge: Dict[str, Dict[str, List[List[str]]]] = {}
        self._shot_knowledge_query: Dict[str, str] = {}
        self._gate_request: Optional[GateRequest] = None
        self._gate_decision: Optional[GateDecision] = None
        self._gate_resume: DriverState = DriverState.FINISHING
        self.gate_history: List[Dict[str, Any]] = []
        self._reviewed_shots: set = set()
        self._pending_review: Optional[str] = None
        self._pending_finish: bool = False
        self.finish_history: List[Dict[str, Any]] = []
        self.review_requests: List[Dict[str, Any]] = []
        self.abort_reason: str = ""
        self._react_steps: int = 0
        self._react_shot: str = ""
        self._react_messages: List[Message] = []
        self._react_done: set = set()
        self.react_history: List[Dict[str, Any]] = []
        #: 阶段 S 的产物（§3.2）。没有它就等于退回 v1.2 的"直接规划"。
        self.brief: Optional[SceneBrief] = None
        self._brief_attempts = 0
        self._brief_problem = ""
        self._brief_messages: List[Message] = []
        self._editing_queue: List[str] = []
        self._editing_index = 0
        self.draft_history: List[Dict[str, Any]] = []
        self.drafts_failed: List[Dict[str, Any]] = []
        #: 剧本落实审核的结果（v1.3 R015/R016）；没有分镜表声明时为 None
        self._compliance: Optional[Dict[str, Any]] = None
        self._finished_shots: List[str] = []
        self._needs_rebuild = False
        self._rebuild_in_place = False
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
        self._paused = False
        self._call_started = 0.0
        self._pending_request_id = ""
        self._pending_payload: Any = None      # §11.3：trace 要落完整 prompt
        self._plan_problem = ""
        self._call_purpose = "plan"
        self._shot_queue: List[str] = []
        self._current_shot_id = ""
        self._repair_attempts = 0
        self._repairs_total = 0
        self._pending_audit: Optional[AuditResult] = None
        #: v1.4 §3.3：时长覆盖留痕（声明时长优先，引擎估算只兜底）。
        self.timing_overrides: List[Dict[str, Any]] = []
        #: v1.4 §3.3：定向修复的留痕（生产者 = 本驱动器；消费者 = US-12②）。
        #: ``repair_applied`` 每个**失败镜**只写一条，所以用集合去重。
        self._pending_repair: Dict[str, Dict[str, Any]] = {}
        self._repaired_shots: set = set()
        self.repair_events: List[Dict[str, Any]] = []
        self._repair_rule: str = ""
        self._repair_before_score: Optional[float] = None
        self._repair_tools_ok: int = 0
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

    # ------------------------------------------------------------ 暂停（§13.1）
    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """暂停推进：状态机不再前进，但**保留**当前状态与已建成的场景。"""
        self._paused = True
        self.audit.log("run_paused", "已暂停", level="warning")

    def resume(self) -> None:
        self._paused = False
        self.audit.log("run_resumed", "已继续")

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
            "failed_audits": sum(1 for result in self.audit_results
                                 if not result.passed),
            "repairs": self._repairs_total,
            "shot_repairs": self._repair_attempts,
            "budget": self.budget.summary,
            "loops": self.loop_detector.stats,
            "knowledge": (self.knowledge.describe()
                          if self.knowledge is not None else None),
            "degraded_reason": self.degraded_reason,
            "abort_reason": self.abort_reason,
            "paused": self._paused,
            "finished_shots": len(self.finish_history),
            "review_requests": len(self.review_requests),
            "react_rounds": len(self.react_history),
            "brief": (self.brief.to_dict() if self.brief is not None
                      else None),
            "brief_source": (self.brief.source if self.brief is not None
                             else ""),
            "drafts": len(self.draft_history),
            "drafts_failed": len(self.drafts_failed),
            "compliance": self._compliance,
            #: v1.4 P15（§3.3）：交付清单要的两张表，由驱动器产出。
            "timing_overrides": list(self.timing_overrides),
            "audit_pass_rate": self._audit_pass_rate(),
            #: E2（§2.3b）：逐镜知识溯源，交付层写 ``movements[].source`` 用。
            "knowledge_provenance": self.knowledge_provenance(),
            "error": self.error,
        }

    def knowledge_provenance(self) -> Dict[str, Dict[str, List[List[str]]]]:
        """逐镜的知识溯源：``{shot_id: {source_kind: [[kind, value], ...]}}``。

        数据来自**该镜构造 B1 请求时那一次**检索（``retriever.provenance()``），
        不额外发起检索——§2.4 的 ``retrieval_calls`` 预算账因此不受影响。
        没有知识层（``--offline``、GUI 未装配）时是空表，交付层就照旧只写
        ``declared|planned``。
        """
        return {shot_id: {kind: [list(pair) for pair in pairs]
                          for kind, pairs in buckets.items()}
                for shot_id, buckets in self._shot_knowledge.items()}

    def _audit_pass_rate(self) -> Dict[str, Any]:
        """构图门通过率（RK-10 的分子/分母口径）。

        * 分母 = **非空镜**且景别 ∉ {ELS, LS}——空镜与超大远景根本没有构图
          可言，把它们算进去等于稀释样本；
        * 分子 = ``composition_score ≥ composition_threshold`` 的镜头数；
        * ``exempt_shots`` 恒为空列表：v1.4 不允许无理由豁免（§4.1b 硬规则 1）。
        """
        from ..contracts.enums import ShotType

        excluded = {str(ShotType.ELS), str(ShotType.LS)}
        threshold = getattr(self.auditor, "composition_threshold", None)
        scores = {str(result.target): result.score
                  for result in self.audit_results}
        denominator = 0
        numerator = 0
        rules: List[str] = []
        for shot in (self.plan.shots if self.plan else []):
            if not shot.characters:
                continue
            if str(shot.shot_type).upper() in excluded:
                continue
            denominator += 1
            score = scores.get(str(shot.shot_id))
            if score is not None and threshold is not None \
                    and float(score) >= float(threshold):
                numerator += 1
                rules.append(str(shot.shot_id))
        return {"numerator": numerator, "denominator": denominator,
                "rules": rules, "sampled_frames": len(self.audit_results),
                "exempt_shots": []}

    # ------------------------------------------------------------ 状态机
    def step(self) -> bool:
        """推进一小步；返回 False 表示运行已终止。"""
        assert_main_thread("PrevisDriver.step")
        if self.state in TERMINAL_STATES:
            return False
        if self._paused:
            return True                      # 暂停：一步都不推进，状态原样保留

        # 只在"真的做了一件事"时计数。等一次 LLM 调用返回要反复进 step()，
        # 本地模型一次调用 60–90 秒、轮询 20ms 就是数千次空转——按 tick 计数会
        # 把"模型慢"误判成"疑似死循环"（实测就是这样撞上 4000 上限的）。
        waiting = (self.state is DriverState.CALLING_LLM
                   and self._reply_q.empty())
        if not waiting:
            self._steps += 1
            if self._steps > self.limits.max_steps:
                self._fail("超出最大步数（疑似死循环）")
                return False
        exhausted = self.budget.exhausted_reason()
        if exhausted and self.state in (DriverState.UNDERSTANDING,
                                        DriverState.PLANNING):
            # 还没产出计划就触顶：降级收尾（构建与审核不花预算，不该被砍）
            self._degrade_to_finish(exhausted)
            return True
        if self._cancel.is_set() and self.state is not DriverState.CANCELLED:
            self._transition(DriverState.CANCELLED)
            self.audit.log("run_cancelled", "运行已取消", level="warning")
            return False
        if self.abort_reason:
            # §7.4 的 abort：LLM 主动放弃。场景保留，运行以 CANCELLED 结束，
            # 不当作成功——这正是它与"降级收尾"的区别。
            self.audit.log("run_aborted",
                           f"模型请求放弃：{self.abort_reason}", level="warning")
            self._transition(DriverState.CANCELLED)
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
            if self._paused:
                time.sleep(poll_interval or 0.05)
            elif poll_interval and self.state is DriverState.CALLING_LLM:
                time.sleep(poll_interval)
        return self.state

    # ------------------------------------------------------------ 各状态
    def _step_idle(self) -> None:
        self.audit.log("run_started", "开始白模预演生成",
                       transport=type(self.transport).__name__,
                       registry=self.registry.names())
        self._emit("run_started", "开始")
        # §3.2：IDLE → UNDERSTANDING → PLANNING。理解阶段可以被配置关掉，
        # 关掉就退回 v1.2 的 IDLE → PLANNING。
        self._transition(DriverState.UNDERSTANDING if self._stage_s_enabled()
                         else DriverState.PLANNING)

    # -------------------------------------------------- 阶段 S（§3.2 剧本理解）
    def _stage_s_enabled(self) -> bool:
        if self.config is None:
            return True
        return bool(getattr(getattr(self.config, "brief", None),
                            "enabled", True))

    def _character_names(self) -> List[str]:
        """给理解阶段看的角色表（从 Layer 1 解析结果取；没有就用计划里的）。"""
        names: List[str] = []
        parsed = self.parsed_script
        if parsed is not None:
            names = [str(name) for name in
                     (getattr(parsed, "character_names", None) or []) if name]
        if not names and self.plan is not None:
            for shot in self.plan.shots:
                for character_id in shot.characters:
                    if character_id not in names:
                        names.append(str(character_id))
        return names

    def _step_understanding(self) -> None:
        """阶段 S：先把"谁对谁说、谁看谁"读出来，再让阶段 A 规划镜头。"""
        if not self._stage_s_enabled() or self.brief is not None:
            self._transition(DriverState.PLANNING)
            return
        if self._brief_attempts >= self.limits.brief_attempts:
            self._fall_back_to_brief(self._brief_problem or "已达最大尝试次数")
            return
        if not self.budget.allow_llm_call("understand"):
            self._fall_back_to_brief(
                self.budget.exhausted_reason() or "预算不足以做剧本理解")
            return
        self._brief_attempts += 1
        self._start_brief_call()

    def _start_brief_call(self) -> None:
        temperature = 0.2
        max_tokens: Optional[int] = None
        if self.config is not None:
            temperature = float(self.config.llm.temperature_repair)
            max_tokens = int(getattr(self.config.llm, "max_tokens", 0) or 0) or None
        payload = build_brief_payload(
            self.script, parsed=self.parsed_script,
            characters=self._character_names(), temperature=temperature,
            max_tokens=max_tokens)
        # 理解阶段的会话**不进** self.messages：那条会话是阶段 A 的，
        # 混进来会污染"计划会话必须合法"的既有约束（§3.4）。
        self._brief_messages = list(payload.messages)
        self._start_llm_call(
            "understand", payload,
            note=f"请求剧本理解（第 {self._brief_attempts} 次尝试）")

    def _finish_brief(self, reply: ChatReply) -> None:
        try:
            brief = extract_brief(reply)
        except ValueError as exc:
            self._brief_problem = str(exc)
            self.audit.log("brief_invalid", str(exc), level="warning")
            self._emit("brief_invalid", "剧本理解未通过解析")
            self._transition(DriverState.UNDERSTANDING)
            return
        self._accept_brief(brief)

    def _accept_brief(self, brief: SceneBrief) -> None:
        characters = self._character_names()
        problems = brief.validate(characters)
        self.brief = brief
        self.audit.log("brief_received",
                       f"剧本理解完成（来源：{brief.source}，"
                       f"{len(brief.beats)} 个节拍 / {len(brief.gaze)} 条注视）",
                       level="warning" if problems else "info",
                       brief=brief.to_dict(), source=brief.source,
                       problems=problems)
        self._emit("brief_received", "剧本理解完成", source=brief.source)
        for problem in problems[:5]:
            self.audit.log("brief_problem", problem, level="warning")
        self._transition(DriverState.PLANNING)

    def _fall_back_to_brief(self, reason: str) -> None:
        """理解失败/预算不足：降级为确定性抽取，**永不致命**（§3.2）。"""
        self.audit.log("brief_degraded",
                       f"剧本理解降级为确定性抽取：{reason}",
                       level="warning", error=ErrorCode.BRIEF_001.value)
        self._emit("brief_degraded", "剧本理解降级", reason=reason)
        self._accept_brief(deterministic_brief(self.parsed_script,
                                               self._character_names()))

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
        # trace 里的 purpose 必须是**真实阶段**：以前这里把"非修复"一律写成
        # plan，于是自我审核与 B5 精修在审计里都被记成了 plan（§11.3 要求
        # 区分 plan/editor/repair/react/review）。
        try:
            purpose = str(Purpose(self._call_purpose))
        except ValueError:
            purpose = str(Purpose.PLAN)

        if kind == "err":
            self.budget.record_llm(None)
            self.audit.log("llm_error", str(payload), level="error",
                           request_id=self._pending_request_id)
            self.audit.log_llm(purpose, None, duration,
                               self._pending_request_id, error=str(payload),
                               payload=self._pending_payload)
            self._recover_from_llm_error(self._call_purpose, str(payload))
            return

        reply: ChatReply = payload
        self.budget.record_llm(reply.usage)
        self.audit.log_llm(purpose, reply, duration, self._pending_request_id,
                           payload=self._pending_payload)

        if repairing:
            problem = self._dispatch_tool_calls(reply, self.repair_messages)
            if problem:
                self.audit.log("repair_invalid", problem, level="warning")
            self._repair_attempts += 1
            self._repairs_total += 1
            self._mark_repair_applied(
                applied=bool(self._repair_tools_ok) or self._needs_rebuild)
            # 修复只改了计划（重提草案）时必须先重建场景再复核：审核器看的是
            # 场景，否则"改好了"根本不会被看见，只会在同一处反复修。
            if self._needs_rebuild and self.builder is not None:
                self._needs_rebuild = False
                self._rebuild_in_place = True
                self._transition(DriverState.BUILDING)
                return
            self._transition(DriverState.CHECKING)   # 复核一次，看改没改对
            return

        if self._call_purpose == "react":
            self._react_steps += 1
            called = bool(reply.tool_calls)
            problem = self._dispatch_tool_calls(reply, self._react_messages)
            if problem:
                self.audit.log("react_invalid", problem, level="warning")
            if not called:
                self._finish_react("模型停止调用工具")
                return
            if self._react_steps >= self._react_max_steps():
                self._finish_react("达到步数上限")
                return
            self._start_react_turn()
            return

        if self._call_purpose == "editor":
            self._finish_editor_turn(reply)
            return

        if self._call_purpose == "understand":
            self._finish_brief(reply)
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
        # 计划通过后先进阶段 B1（逐镜结构化生成），再落成场景（§7.1）。
        # 没有构建器时也不需要逐镜草案——那是给执行引擎吃的。
        self._pin_declared_dialogue()
        target = (DriverState.EDITING if self.builder is not None
                  else DriverState.FINISHING)
        if target is DriverState.FINISHING:
            # 没有构建器就不会走 B1，注视关系在这里一次补齐。
            self._pin_brief_gaze()
        if self._gate_enabled("human_gate_on_plan"):
            self._request_gate(
                GateRequest(kind="plan", title="确认分镜计划",
                            detail=self._plan_gate_detail(),
                            payload={"shots": len(self.plan.shots)
                                     if self.plan else 0}),
                resume=target)
            return
        self._transition(target)

    def _pin_declared_dialogue(self) -> None:
        """把分镜表声明的台词**钉到计划上**（v1.3 R016 的落实侧）。

        阶段 A 的计划只带 ``dialogue_ids``，没有文本。不把声明钉上去，
        阶段 B1 就会按自己的理解分配台词——实测把镜号 3 的台词写进了
        shot_002、把镜号 4 的两句换成自创的一句。钉住之后 B1 只负责
        时间轴与动作，文本由剧本说了算（``merge_draft`` 会守住这条线）。

        这是**阶段 A 的收尾动作**，不是修复回合改计划——它由剧本声明驱动，
        与"计划只能由阶段 A 改写"并不冲突。
        """
        if self.plan is None or self.parsed_script is None:
            return
        declared = list(getattr(self.parsed_script, "declared_shots", []) or [])
        if not declared:
            return
        pinned = 0
        for index, shot in enumerate(self.plan.shots):
            if index >= len(declared):
                break
            # v1.4 F4/X10：把分镜表声明的镜号钉在计划上——R015 的
            # "顺序/身份错位"就是拿它做判据的（模型自己不会写这个键）。
            shot.declared_shot_number = int(declared[index].shot_number)
            #: v1.4 §2.3b（Q5 的入口形状）：把**声明的拍摄手法**也钉在计划上。
            #: 引擎运镜词表里没有"固定"（锁机位＝不动），所以
            #: `_pin_declared_camera` 会跳过 `static` —— 但**查询**词表里有
            #: `运镜=固定`，而逐镜检索发生在 B1 之前（那时计划里还没有相机）。
            #: 不把声明留在计划上，锁机位的镜头在超图那一栏一个运镜种子都没有：
            #: 实测 2026-10-03，`shotlist_market` 第 1 镜声明"固定镜头"，而
            #: 这一镜真实发出的契约串只有 `景别=MCU`。
            shot.declared_camera_move = str(
                getattr(declared[index], "camera_move", "") or "")
            # v1.4 §3.3：声明时长与计划时长的差异要留痕（US-4/S4）。
            declared_seconds = getattr(declared[index], "declared_seconds", None)
            if declared_seconds is not None:
                applied_s = round(int(shot.duration_frames) / 24.0, 3)
                if abs(applied_s - float(declared_seconds)) > 0.2:
                    self.timing_overrides.append({
                        "shot_number": int(declared[index].shot_number),
                        "declared_s": float(declared_seconds),
                        "engine_s": None,
                        "applied_s": applied_s,
                        "reason": "计划时长与声明不一致（R015 会单独报）",
                    })
            lines = [item for item in declared[index].dialogues
                     if str(item.text or "").strip()]
            if not lines:
                continue
            # v1.4 F3：留下"pin 之前模型自己写了什么"的快照——R016 的
            # 对照面必须是**模型的原始产出**，不能是 pin 之后的计划。
            before = " | ".join(str(entry.get("text") or "")
                                for entry in (shot.dialogues or []))
            from .scene_contract import (STATUS_UNRESOLVED,
                                         resolve_speaker)

            entries = []
            pins = []
            for item in lines:
                speaker_id, status = resolve_speaker(item.character,
                                                     shot.characters)
                if status is STATUS_UNRESOLVED:
                    self.audit.log(
                        "speaker_unresolved",
                        f"{shot.shot_id} 的说话人无法落到在场角色："
                        f"{item.character}（不伪造 character_id）",
                        level="warning", shot=shot.shot_id,
                        speaker=item.character)
                entries.append({"character_id": speaker_id,
                                "speaker_raw": str(item.character or ""),
                                "speaker_status": status,
                                "text": item.text,
                                "start_frame": 0, "end_frame": 0})
                pins.append({"shot_number": int(declared[index].shot_number),
                             "speaker_raw": str(item.character or ""),
                             "speaker_status": status,
                             "declared_s": item.declared_seconds,
                             "model_text": before,
                             "applied_s": None})
            shot.dialogues = entries
            shot.dialogue_pins = pins
            pinned += len(lines)
        if pinned:
            self.audit.log("plan_declared_dialogue_pinned",
                           f"已钉住 {pinned} 句剧本声明的台词",
                           shots=len(self.plan.shots))
        self._pin_declared_camera(declared)

    def _pin_declared_camera(self, declared) -> None:
        """把分镜表的「拍摄手法」钉成声明式运镜（v1.3 §3.6）。

        剧本写了"快速推镜"却没有任何环节把它变成相机运动，交付的视频里
        镜头就是死的——这正是 v1.2 的运镜"不可声明"缺口的最后一段。
        B1 已经给了运镜时不覆盖：那才是落实侧。
        """
        pinned = 0
        for index, shot in enumerate(self.plan.shots):
            if index >= len(declared):
                break
            movement = str(getattr(declared[index], "camera_move", "") or "")
            camera = dict(getattr(shot, "camera", None) or {})
            if not movement or movement == "static" or camera.get("movements"):
                continue
            camera["movements"] = [{"type": movement}]
            shot.camera = camera
            pinned += 1
        if pinned:
            self.audit.log("plan_declared_camera_pinned",
                           f"已钉住 {pinned} 个镜头的拍摄手法",
                           shots=len(self.plan.shots))

    def _pin_brief_gaze(self) -> None:
        """阶段 B1 结束后再补注视关系（§3.5 的"声明 vs 落实"）。

        B1 自己给了 ``gaze`` 就以它为准——那才是**落实侧**，R013 要拿它与
        阶段 S 的理解对拍。B1 没给（离线、草案失败、模型偷懒）时才用理解
        兜底，否则这一镜的落实侧是空的，等于没有可比对的证据。
        """
        pinned = merge_brief_gaze(self.brief, self.plan)
        if pinned:
            self.audit.log("plan_gaze_pinned",
                           f"已按剧本理解补齐 {pinned} 个镜头的注视关系",
                           shots=len(self.plan.shots) if self.plan else 0)

    def _recover_from_llm_error(self, purpose: str, problem: str) -> None:
        """一次 LLM 调用失败之后的落点——**按阶段区分**。

        v1.2 只区分 ``repair`` 与非 repair：``editor`` / ``review`` / ``react``
        三个阶段的传输错误全被送回 PLANNING，于是计划被反复重新生成、
        ``plan_attempts`` 迅速耗尽，最终报出"分镜计划生成失败（已达最大尝试
        次数）"——与真实原因（一次瞬时 502，耗时 0.042 秒）完全不符，
        并把整次运行终止掉。实测就是这么丢掉了一整次 18 分钟的运行的。

        顺带修掉两条会让状态机空转的路径：

        * ``repair`` 失败不计入 ``_repair_attempts`` → CHECKING ↔ REPAIRING
          无限往返；
        * ``review`` 失败不记入 ``_reviewed_shots`` → 同一镜被无限复核。
        """
        if purpose == "plan":
            # 计划失败由 _step_planning 决定是否再试（消耗 plan_attempts）
            self._transition(DriverState.PLANNING)
            return
        if purpose == "understand":
            # 理解失败**不重试到死**：一次失败就退回确定性抽取并继续规划。
            self._fall_back_to_brief(problem)
            return
        if purpose == "editor":
            self._skip_editor_turn(problem)
            return
        if purpose == "review":
            self._skip_review_turn(problem)
            return
        if purpose == "repair":
            self._repair_attempts += 1
            self.audit.log("repair_failed",
                           f"修复调用失败（第 {self._repair_attempts} 次）："
                           f"{problem}", level="warning",
                           shot=self._current_shot_id)
            self._transition(DriverState.CHECKING)
            return
        # react：结束本镜的 ReAct 回合，回到复核
        self._finish_react(f"传输错误：{problem}")

    def _skip_editor_turn(self, problem: str) -> None:
        """单镜草案调用失败：记进 drafts_failed 并**前进**。

        不能原地重试：``_step_editing`` 每次都从
        ``_editing_queue[_editing_index]`` 取镜号，不前进就会卡在这一镜。
        与 ``_finish_editor_turn`` 的失败分支保持同一语义（该镜沿用计划内容，
        后面还有 B3/B4 兜住真正的执行问题）。
        """
        if self._editing_queue and self._editing_index < len(self._editing_queue):
            shot_id = self._editing_queue[self._editing_index]
            self.drafts_failed.append({"shot_id": shot_id, "error": problem})
            self.audit.log("draft_invalid", f"{shot_id}: {problem}",
                           level="warning", shot=shot_id)
            self._emit("draft_invalid", f"{shot_id} 草案失败", shot=shot_id)
            self._editing_index += 1
        self._transition(DriverState.EDITING)

    def _skip_review_turn(self, problem: str) -> None:
        """复核调用失败：记为"本次未复核"并继续。

        规则层已经放行，复核只是额外一层；拿不到结论就如实记录并前进，
        绝不重试到死循环。
        """
        shot_id = self._pending_review or self._current_shot_id
        self._pending_review = None
        self._reviewed_shots.add(shot_id)
        self.audit.log("self_review_invalid",
                       f"{shot_id}: 复核未完成（{problem}）",
                       level="warning", shot=shot_id)
        self._transition(DriverState.CHECKING)

    def _log_script_compliance(self, plan) -> None:
        """收尾时核对"导演写下的东西有没有做出来"（v1.3 R015/R016）。

        v1.4 X7：**R014/R017 与剧本有没有分镜表无关**，必须始终执行——
        v1.3 的守卫把叙事剧本整段跳过了，于是"声明了运动却没说动机"
        与"空镜没说用途"这两条对叙事剧本永不生效。R015/R016 仍只在
        分镜表声明存在时判定（在 ``check_compliance`` 内部自我收敛）。
        """
        from .compliance import compliance_report

        level = getattr(getattr(self.config, "audit", None), "level", None)
        # R013/R014/R017 只看计划本身与 SceneBrief，与分镜表无关 → 永远执行；
        # R015/R016 由 check_compliance 在"没有声明"时自行跳过。
        report = compliance_report(plan, self.parsed_script, brief=self.brief,
                                   audit_level=level)
        self._compliance = report
        errors = [item for item in report["findings"]
                  if str(item.get("severity")) == "error"]
        warnings = [item for item in report["findings"]
                    if str(item.get("severity")) != "error"]
        if errors:
            message = (f"剧本落实审核：{len(errors)} 项偏差、"
                       f"{len(warnings)} 项提示")
        else:
            message = (f"剧本落实审核：逐条对上"
                       f"（{report['plan_shot_count']} 镜 / "
                       f"{report['plan_total_seconds']:g} 秒）")
        self.audit.log("script_compliance", message,
                       level="warning" if errors else "info",
                       declared_total_seconds=report["declared_total_seconds"],
                       plan_total_seconds=report["plan_total_seconds"],
                       declared_shot_count=report["declared_shot_count"],
                       plan_shot_count=report["plan_shot_count"],
                       findings=report["findings"])
        for item in errors[:5]:
            self.audit.log("script_compliance_finding", str(item.get("message")),
                           level="warning", rule=item.get("rule"),
                           target=item.get("target"))

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

    # -------------------------------------------------- 阶段 B1（§7.1 逐镜草案）
    def _step_editing(self) -> None:
        """逐镜请求结构化草案；全部完成后再落场景。"""
        if self.plan is None or not self.plan.shots:
            self._transition(DriverState.BUILDING)
            return
        if not self._editing_queue:
            self._editing_queue = [shot.shot_id for shot in self.plan.shots]
            self._editing_index = 0
        if self._editing_index >= len(self._editing_queue):
            self._editing_queue = []
            self._pin_brief_gaze()
            self._transition(DriverState.BUILDING)
            return
        shot_id = self._editing_queue[self._editing_index]
        if not self.budget.allow_llm_call("editor"):
            self.audit.log("editor_skipped",
                           f"预算不足以逐镜生成，{shot_id} 起沿用计划内容",
                           level="warning")
            self._editing_queue = []
            self._pin_brief_gaze()
            self._transition(DriverState.BUILDING)
            return
        self._start_editor_call(shot_id)

    def _start_editor_call(self, shot_id: str) -> None:
        shot = next((item for item in (self.plan.shots if self.plan else [])
                     if item.shot_id == shot_id), None)
        if shot is None:
            self._editing_index += 1
            return
        characters = list(shot.characters)
        props: List[str] = []
        payload = build_editor_payload(
            shot, self.plan, shot_order=self._editing_index + 1,
            scene_state=self._scene_state_text(),
            scene_text=self._shot_script_text(),
            continuity=render_shot_memory(
                shot_memory(self.plan, done=self._finished_shots)),
            characters=characters, props=props, retriever=self.knowledge,
            temperature=(float(self.config.llm.temperature_plan)
                         if self.config is not None else 0.7))
        # E2 溯源：`build_editor_payload` 刚刚（且只）发起了这一镜的检索，
        # 所以此刻读 `provenance()` 拿到的一定是这一镜的命中集。
        self._record_shot_knowledge(shot_id)
        self._start_llm_call("editor", payload,
                             note=f"单镜结构化生成 {shot_id}"
                                  f"（{self._editing_index + 1}/"
                                  f"{len(self._editing_queue)}）")

    def _record_shot_knowledge(self, shot_id: str) -> None:
        """把这一镜注入的知识溯源记下来（E2 的数据源，不发新检索）。"""
        provenance_fn = getattr(self.knowledge, "provenance", None)
        if provenance_fn is None:
            return
        buckets = provenance_fn() or {}
        pairs = {kind: [list(pair) for pair in values]
                 for kind, values in buckets.items() if values}
        if pairs:
            self._shot_knowledge[shot_id] = pairs
            self._shot_knowledge_query[shot_id] = str(
                getattr(self.knowledge, "last_edges_query", ""))

    def _shot_script_text(self) -> str:
        """给 B1 的剧本原文（§18.2 的 ``{scene_text}``）。

        v1.2 的 ``_start_editor_call`` **完全没有传这个参数**，于是 B1 只看到
        "镜号 / 景别 / 时长 / 角色"，模型只能自己编台词。实测后果：
        剧本里的"伊恩，这里就交给我吧！"在计划里变成了"我是米迦尔。"，
        后面三镜的对白全部丢失。

        这里先用 Layer 1 的解析结果渲染（动作行 + 对白行）。
        逐镜的精确归属由 v1.3 的 Stage S（``SceneBrief.speakers``）接手。
        """
        lines: List[str] = []
        parsed = self.parsed_script
        for scene in getattr(parsed, "scenes", None) or []:
            if getattr(scene, "heading", ""):
                lines.append(f"【{scene.heading}】")
            for action in getattr(scene, "actions", None) or []:
                lines.append(f"· {action.text}")
            for dialogue in getattr(scene, "dialogues", None) or []:
                tag = (f"（{dialogue.parenthetical}）"
                       if getattr(dialogue, "parenthetical", "") else "")
                lines.append(f"{dialogue.character}{tag}：{dialogue.text}")
        if lines:
            return "\n".join(lines)
        return self.script or ""

    def _finish_editor_turn(self, reply: ChatReply) -> None:
        shot_id = self._editing_queue[self._editing_index]
        try:
            draft = extract_draft(reply, shot_id)
        except ValueError as exc:
            # 单镜草案失败不拖垮整场：记进 history 与警告，这一镜沿用计划内容，
            # 后面还有 B3/B4 兜住真正的执行问题。
            self.drafts_failed.append({"shot_id": shot_id, "error": str(exc)})
            self.audit.log("draft_invalid", f"{shot_id}: {exc}", level="warning",
                           shot=shot_id)
            self._emit("draft_invalid", f"{shot_id} 草案无效", shot=shot_id)
        else:
            self.plan = merge_draft(self.plan, draft)
            self.draft_history.append(draft.to_dict())
            self.audit.log("draft_received",
                           f"{shot_id}: {len(draft.actions)} 个动作 / "
                           f"{len(draft.dialogues)} 句对白",
                           shot=shot_id, actions=len(draft.actions),
                           dialogues=len(draft.dialogues))
            self._emit("draft_received", f"{shot_id} 草案已合并", shot=shot_id)
        self._editing_index += 1
        self._transition(DriverState.EDITING)

    def _step_building(self) -> None:
        """把分镜计划交给场景构建器（bpy 实现在 layer3_engine/shot_builder.py）。"""
        plan = self.plan or Plan()
        if self.builder is None:
            self._transition(DriverState.FINISHING)
            return
        started = self.clock()
        try:
            summary = self.builder.build(plan, self.brief) or {}
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
        if self._rebuild_in_place:
            # 修复阶段改了计划（重提草案）后重建：审核队列与修复计数保持原样，
            # 否则会从第一镜重新审一遍，甚至在已通过的镜头上再触发修复。
            self._rebuild_in_place = False
            return DriverState.CHECKING
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
        # v1.4 §3.3（R45）：shot_audit 增写构图分与阈值——两者是同一次审核里
        # 已经算好的量（``AuditResult.score`` 与审核器的门限），阈值只有一个来源。
        threshold = getattr(self.auditor, "composition_threshold", None)
        self.audit.log("shot_audit", f"{shot_id}: {result.format_for_llm().splitlines()[0]}",
                       level="info" if result.passed else "warning",
                       shot=shot_id, passed=result.passed,
                       errors=len(result.errors), warnings=len(result.warnings),
                       composition_score=result.score,
                       composition_threshold=threshold)
        self._emit("shot_audit",
                   f"{shot_id} {'通过' if result.passed else '未通过'}",
                   shot=shot_id, passed=result.passed)
        self._record_repair_verification(shot_id, result)

        if self._pending_finish:
            # 模型已用 finish_shot 声明该镜完成：不再进修复循环，直接前进。
            # 审核结论仍然落盘——"谁说的"和"测出来的"分开记。
            self._pending_finish = False
            if not result.passed:
                self.audit.log(
                    "shot_finished_with_errors",
                    f"{shot_id} 由模型声明完成，但审核未通过", level="warning",
                    shot=shot_id, errors=len(result.errors))
                self._emit("shot_finished_with_errors",
                           f"{shot_id} 带问题完成", shot=shot_id)
            self._advance_shot()
            return
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
            if self._should_start_react(shot_id, result):
                self._start_react(shot_id, result)
                return
            self._advance_shot()
            return
        self._pending_audit = result
        self._transition(DriverState.REPAIRING)

    def _advance_shot(self) -> None:
        if self._shot_queue:
            self._finished_shots.append(self._shot_queue.pop(0))
        self._repair_attempts = 0
        self.repair_messages = []
        if self._shot_queue:
            self._current_shot_id = self._shot_queue[0]
        self._transition(DriverState.CHECKING)

    # -------------------------------------------------- v1.4 §3.3 修复留痕
    def _mark_repair_applied(self, *, applied: bool) -> None:
        """标记"这一镜实施过一次定向修复"，等复核后再落 ``repair_applied``。

        每个**失败镜**只留一条（``_repaired_shots`` 去重），因为 US-12② 判定
        的是"条数 == 失败镜数"——一次镜头修两轮不该写两条。
        """
        if not applied:
            return
        shot_id = self._current_shot_id
        if not shot_id or shot_id in self._repaired_shots:
            return
        self._pending_repair.setdefault(shot_id, {
            "rule": self._repair_rule or "COMPOSITION",
            "attempt": int(self._repair_attempts),
            "before_score": self._repair_before_score,
        })

    def _record_repair_verification(self, shot_id: str,
                                    result: AuditResult) -> None:
        """复核回来后补上 ``after_score`` 并写出 ``repair_applied`` 事件。"""
        pending = self._pending_repair.pop(shot_id, None)
        if pending is None:
            return
        self._repaired_shots.add(shot_id)
        self._emit_repair_applied(shot_id, pending,
                                  getattr(result, "score", None))

    def _flush_pending_repairs(self) -> None:
        """收尾时把还没等到复核的留痕补写出去（``after_score=None``）。"""
        for shot_id, pending in list(self._pending_repair.items()):
            self._repaired_shots.add(shot_id)
            self._emit_repair_applied(shot_id, pending, None)
        self._pending_repair.clear()

    def _emit_repair_applied(self, shot_id: str, pending: Dict[str, Any],
                             after_score: Optional[float]) -> None:
        event = {"shot_id": shot_id, "rule": pending.get("rule", ""),
                 "attempt": int(pending.get("attempt") or 0),
                 "before_score": pending.get("before_score"),
                 "after_score": after_score}
        self.repair_events.append(event)
        self.audit.log(
            "repair_applied",
            f"{shot_id} 已实施定向修复（{event['rule']}）",
            shot=shot_id, rule=event["rule"], attempt=event["attempt"],
            before_score=event["before_score"], after_score=after_score)
        self._emit("repair_applied", f"{shot_id} 已修复", shot=shot_id)

    # -------------------------------------------------- Level 2 自我审核（§11.1）
    # -------------------------------------------------- 阶段 B5（§7.1 受限 ReAct）
    def _should_start_react(self, shot_id: str, result: AuditResult) -> bool:
        if shot_id in self._react_done:
            return False
        shot = next((item for item in (self.plan.shots if self.plan else [])
                     if item.shot_id == shot_id), None)
        max_steps = 6
        if self.config is not None:
            max_steps = int(getattr(self.config.orchestration,
                                    "react_max_steps", 6))
        return should_react(shot, result, repairs_exhausted=True,
                            max_steps=max_steps)

    def _start_react(self, shot_id: str, result: AuditResult) -> None:
        """进入 B5：开一段有上限的工具对话，让模型自己边看边调。"""
        self._react_done.add(shot_id)          # 每个镜头只给一次 B5
        self._react_shot = shot_id
        self._react_steps = 0
        shot = next((item for item in (self.plan.shots if self.plan else [])
                     if item.shot_id == shot_id), None)
        memory = render_shot_memory(
            shot_memory(self.plan, done=self._finished_shots))
        payload = build_react_payload(
            shot, result, scene_state=self._scene_state_text(),
            registry=self.registry, max_steps=self._react_max_steps())
        if memory:
            payload.messages[0].content += "\n\n" + memory
        self._react_messages = list(payload.messages)
        self.audit.log("react_started", f"{shot_id} 进入受限 ReAct",
                       shot=shot_id, max_steps=self._react_max_steps())
        self._emit("react_started", f"{shot_id} 精修", shot=shot_id)
        self._start_react_turn()

    def _react_max_steps(self) -> int:
        if self.config is None:
            return 6
        return int(getattr(self.config.orchestration, "react_max_steps", 6))

    def _start_react_turn(self) -> None:
        """把当前 ReAct 对话裁到上下文上限内，再发起下一轮。"""
        limit = 32000
        if self.config is not None:
            limit = int(getattr(self.config.orchestration,
                                "context_window_tokens", 32000))
        kept, dropped = trim_messages(self._react_messages, limit)
        if dropped:
            self.audit.log("context_trimmed",
                           f"裁剪 {len(dropped)} 条旧观察",
                           level="warning", **budget_report(kept, limit))
            self._react_messages = kept
        payload = ChatPayload(messages=list(self._react_messages),
                              tools=self.registry.openai_schemas(),
                              tool_choice=ToolChoice.AUTO,
                              temperature=0.3, purpose=Purpose.REACT,
                              request_id=new_request_id())
        self._start_llm_call("react", payload,
                             note=f"精修 {self._react_shot}"
                                  f"（第 {self._react_steps + 1} 步）")

    def _finish_react(self, reason: str) -> None:
        self.react_history.append({"shot_id": self._react_shot,
                                   "steps": self._react_steps,
                                   "reason": reason})
        self.audit.log("react_finished",
                       f"{self._react_shot} 精修结束（{reason}）",
                       shot=self._react_shot, steps=self._react_steps)
        self._emit("react_finished", f"{self._react_shot} 精修结束",
                   shot=self._react_shot, steps=self._react_steps)
        self._react_messages = []
        self._transition(DriverState.CHECKING)   # 复核一次，看改没改好

    # -------------------------------------------------- Level 2 自我审核（§11.1）
    def _should_self_review(self, shot_id: str) -> bool:
        if self.config is None:
            return False
        if not getattr(self.config.orchestration, "self_review", False):
            return False
        if shot_id in self._reviewed_shots or self.plan is None:
            return False
        shot = self._shot_plan(shot_id)
        if shot is None:
            return False
        if not shot.characters:
            # 空镜（无角色）没有表演可复核。v1.2 照样会审，实测得到的是
            # "角色数量过多且静止站立，破坏宁静氛围"这类与镜头内容无关的意见，
            # 白白花掉一次 LLM 调用，还可能把建立镜头改坏。
            self.audit.log("self_review_skipped",
                           f"{shot_id} 是无角色空镜，跳过自我审核",
                           shot=shot_id)
            return False
        return True

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
        # v1.4 §3.3：记下这条留痕的"规则 + 修前分"，等复核后再补 after_score。
        rules = sorted({str(item.rule) for item in audit.errors}) or ["COMPOSITION"]
        self._repair_rule = "/".join(rules)
        self._repair_before_score = getattr(audit, "score", None)
        self._repair_tools_ok = 0
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
        self._log_script_compliance(plan)
        # 还没等到复核的修复留痕也要落盘（否则"条数 == 失败镜数"会少一条）。
        self._flush_pending_repairs()
        self._transition(DriverState.DONE)
        # replay（§14.4）要能只靠这份日志重建场景，因此整份计划必须落盘：
        # 只记 shots 会丢掉 scene_heading 与 continuity_notes。
        self.audit.log("plan_received",
                       f"分镜计划完成：{len(plan.shots)} 个镜头",
                       plan=plan.to_dict(),
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
    def _apply_scene_budget(self, shots: int) -> None:
        """按 v1.4 §2.4 的**唯一口径**算出这次场景允许的调用上限。

        ``ceiling_effective = max(budget.max_llm_calls_ceiling, formula(N))``：
        ``ceiling`` 是**额度下限保障**（不是上限），所以 61 镜不会被 200 卡死。
        真正的硬顶只来自 CLI ``--max-llm-calls``（``0`` = 不限，该因子不参与）。
        无法识别的公式只记一条警告，退回静态 ceiling。
        """
        budget_config = getattr(self.config, "budget", None)
        if budget_config is None:
            return
        formula = getattr(budget_config, "max_llm_calls_per_scene_formula", "")
        value = evaluate_llm_call_budget(formula, shots)
        ceiling = int(getattr(budget_config, "max_llm_calls_ceiling", 0) or 0)
        if value is None:
            self.audit.log("budget_formula_ignored",
                           describe_budget_formula(formula, shots),
                           level="warning")
            ceiling_effective = ceiling
        else:
            ceiling_effective = max(ceiling, value)
        hard = int(self.limits.max_llm_calls)       # 0 = 不限
        if hard <= 0:
            hard = int(self._caller_budget_cap)
        effective = min(ceiling_effective, hard) if hard > 0 else ceiling_effective
        self.budget.limits.max_llm_calls = effective
        self.audit.log(
            "budget_scoped", describe_budget_formula(formula, shots),
            shots=shots, formula_value=value, ceiling=ceiling,
            ceiling_effective=ceiling_effective, hard_cap=hard,
            effective=effective)

    def _start_plan_call(self) -> None:
        request_id = new_request_id()
        try:
            payload: ChatPayload = build_plan_payload(
                self.script, self.config, request_id=request_id,
                parsed=self.parsed_script, retriever=self.knowledge,
                brief=self.brief)
        except ValueError as exc:
            # v1.4 BW-3/E_SCRIPT_002：声明镜数超过 max_shots 时明确失败，
            # 而不是退回"其余 N 个镜号略"的静默截断。
            self.audit.log("plan_payload_failed", str(exc), level="error")
            self._fail(str(exc))
            return
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
        self._pending_payload = payload
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
            if result.ok and call.function.name != PLAN_TOOL_NAME:
                # v1.4 §3.3：修复回合里**真的执行成功**的场景工具 = 这一镜被
                # 实际修过。不能用"本轮没有 problem"当判据——修复回合只调
                # 场景工具（不重提计划）时，`_dispatch_tool_calls` 会因为
                # "没有收到 emit_plan" 而返回 problem。
                self._repair_tools_ok += 1
            conversation.append(tool_message(call, result.content))
            self._emit("tool_call", f"{call.function.name}",
                       tool=call.function.name, ok=result.ok)

            if not result.ok:
                errors.append(f"{call.function.name}: {result.content}")
                continue
            if call.function.name == PLAN_TOOL_NAME:
                if self._call_purpose != "plan":
                    # 计划的唯一入口是阶段 A（§7.1）。真实模型会在修复回合里
                    # 再提交一份"更满意"的计划——如果照单全收，已经建好的场景
                    # 与计划就此分叉（实测：项目文件里时长 37、帧范围 1–64）。
                    self.audit.log(
                        "plan_ignored",
                        f"{self._call_purpose} 阶段提交的 emit_plan 已忽略",
                        level="warning", stage=self._call_purpose)
                    errors.append("emit_plan 只在阶段 A 被接受")
                else:
                    try:
                        self.plan = Plan.from_dict(args)
                        plan_seen = True
                        self._apply_scene_budget(len(self.plan.shots))
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"计划解析失败: {exc}")
            elif result.ok and call.function.name == ABORT:
                self.abort_reason = str(args.get("reason") or "（未说明原因）")
                self.audit.log("abort_requested", self.abort_reason,
                               level="warning")
                self._emit("abort_requested", self.abort_reason)
            elif result.ok and call.function.name == FINISH_SHOT:
                if self._current_shot_id:
                    self._pending_finish = True
                    self.finish_history.append(
                        {"shot_id": self._current_shot_id,
                         "summary": str(args.get("summary") or "")})
                    self.audit.log("shot_finished",
                                   f"{self._current_shot_id} 由模型声明完成",
                                   shot=self._current_shot_id,
                                   summary=str(args.get("summary") or ""))
                else:
                    errors.append("finish_shot：当前没有正在处理的镜头")
            elif result.ok and call.function.name == REQUEST_SELF_REVIEW:
                shot_id = str(args.get("shot_id") or self._current_shot_id or "")
                if shot_id:
                    self._pending_review = shot_id
                    self.review_requests.append(
                        {"shot_id": shot_id,
                         "intent": str(args.get("shot_intent") or "")})
                    self.audit.log("self_review_requested",
                                   f"{shot_id} 已登记自我审核", shot=shot_id)
                else:
                    errors.append("request_self_review：当前没有正在处理的镜头")
            elif result.ok and call.function.name == EDITOR_TOOL_NAME:
                # 修复/精修阶段重新提交草案：允许改对白时序与动作。
                # 计划阶段不接受它（那时还没有逐镜草案这一说）。
                if self._call_purpose == "plan" or self.plan is None:
                    errors.append("emit_shot_draft 只在单镜阶段被接受")
                else:
                    shot_id = str(args.get("shot_id") or self._current_shot_id)
                    try:
                        draft = extract_draft(
                            ChatReply(tool_calls=[call]), shot_id)
                    except ValueError as exc:
                        errors.append(str(exc))
                    else:
                        self.plan = merge_draft(self.plan, draft)
                        self.draft_history.append(draft.to_dict())
                        self._needs_rebuild = True
                        self.audit.log(
                            "draft_received",
                            f"{shot_id}: 重提草案（{len(draft.actions)} 动作 / "
                            f"{len(draft.dialogues)} 对白）",
                            shot=shot_id, stage=self._call_purpose)

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
