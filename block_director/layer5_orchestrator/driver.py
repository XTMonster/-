"""预演驱动器：与 Blender 解耦的状态机（执行文档 v1.2 §3.2 / §3.3）。

设计红线：
- 本模块 **不得 import bpy**（§2.4）。它只编排，不碰场景。
- ``step()`` 每次只做一件小事并立即返回，绝不阻塞（LLM 调用在后台线程）。
- ``step()`` 必须在主线程调用（用 threading_guard 强制），因为它接下来会
  调用触碰 bpy 的工具。
"""

from __future__ import annotations

import copy
import json
import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..contracts.enums import Purpose, ToolChoice
from ..contracts.audit import (SCENE_BUILT_RESERVED_KEYS, AuditError,
                               AuditResult, scene_built_reason)
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
from ..contracts.plan import Plan, unknown_cast_ids
from ..contracts.brief import SOURCE_DETERMINISTIC, SceneBrief
from ..contracts.enums import ErrorCode
from ..contracts.errors import user_message
from ..contracts.tools import MUTATING_TOOLS, READ_ONLY_TOOLS
from ..layer6_audit.audit_logger import AuditLogger
from ..utils.logger import get_logger
from ..utils.threading_guard import assert_main_thread
from .planner import (
    EMIT_PLAN_TOOL_PARAMETERS,
    PLAN_TOOL_NAME,
    build_plan_payload,
    plan_chunks,
    plan_parameters,
)
from .control_tools import (
    ABORT,
    FINISH_SHOT,
    REQUEST_SELF_REVIEW,
    register_control_tools,
)
from .repair import REPAIR_FOLLOWUP_NUDGE, build_repair_payload
from .budget import Budget, BudgetLimits
from .budget_formula import describe as describe_budget_formula
from .budget_formula import evaluate as evaluate_llm_call_budget
from .context_budget import budget_report, slim_messages, trim_messages
from .editor import (build_editor_payload, extract_draft, merge_draft,
                     rank_drafts)
from .editor import EDITOR_TOOL_NAME, EMIT_SHOT_DRAFT_PARAMETERS
from .react import build_react_payload, render_shot_memory, should_react, shot_memory
from .retry_ladder import (
    DEGRADE,
    RETRY_SAME,
    RETRY_SLIM,
    STAGE_OF,
    CallOutcome,
    RetryPolicy,
    is_timeout,
    next_step,
)
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


# --------------------------------------------------------------------------- #
# v1.6 F2（D-09）：断点续跑的状态模型（纯层，不得 import bpy）
# --------------------------------------------------------------------------- #

RESUME_STATE_VERSION = 1
RESUME_STATE_FILENAME = "resume_state.json"

#: 终态镜的闭集。``finished`` = 模型 `finish_shot` 声明完成但审核未过；
#: ``unverified`` = 审核器没给出结论（异常路径）就前进的镜头。四种都表示
#: "这一镜的 LLM 流程已结束"，resume 时全部零调用跳过。
RESUME_TERMINAL_STATUSES = ("passed", "degraded", "finished", "unverified")


class ResumeStateError(RuntimeError):
    """resume_state 不可用。消息里给出可执行的下一步，绝不静默猜。"""


@dataclass
class ResumeState:
    """断点续跑的版本化运行状态（``resume_state.json`` 的单一真源）。

    格式（v1）：顶层 ``schema_version`` 固定为 :data:`RESUME_STATE_VERSION`；
    ``plan`` / ``brief`` 是中断那一刻的完整快照（草案已合并进计划）；
    ``drafts`` 记每镜成功合并的 B1 草案（用于算"还有哪些镜没起草"）；
    ``terminal_shots`` 记每镜终态（passed/degraded/finished/unverified），
    resume 时对它们**零 LLM 调用**跳过；``delivered_shots`` 记墙钟收尾时
    已经导出的镜头，resume 后的导出不许重渲它们。
    """

    version: int = RESUME_STATE_VERSION
    run_id: str = ""
    saved_at: str = ""
    plan: Optional[Dict[str, Any]] = None
    brief: Optional[Dict[str, Any]] = None
    script: str = ""
    drafts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    terminal_shots: Dict[str, str] = field(default_factory=dict)
    last_audit: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    delivered_shots: List[str] = field(default_factory=list)
    llm_calls: int = 0
    tool_calls: int = 0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": int(self.version),
            "run_id": str(self.run_id),
            "saved_at": self.saved_at or _now_iso(),
            "plan": copy.deepcopy(self.plan),
            "brief": copy.deepcopy(self.brief),
            "script": str(self.script),
            "drafts": {str(k): dict(v) for k, v in self.drafts.items()},
            "terminal_shots": {str(k): str(v)
                               for k, v in self.terminal_shots.items()},
            "last_audit": {str(k): dict(v) for k, v in self.last_audit.items()},
            "delivered_shots": [str(item) for item in self.delivered_shots],
            "llm_calls": int(self.llm_calls),
            "tool_calls": int(self.tool_calls),
            "reason": str(self.reason),
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "ResumeState":
        """严格反序列化：版本错配 / 缺字段 / 类型错误一律报错，**绝不猜**。"""
        if not isinstance(payload, dict):
            raise ResumeStateError(
                f"resume_state 顶层必须是 JSON 对象，实际是 "
                f"{type(payload).__name__}")
        version = payload.get("schema_version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ResumeStateError(
                f"resume_state 缺少合法的 schema_version（整数），实际是 "
                f"{version!r}")
        if version != RESUME_STATE_VERSION:
            raise ResumeStateError(
                f"resume_state 版本不匹配：文件是 {version}，当前支持 "
                f"{RESUME_STATE_VERSION}。请用生成它的版本继续运行，或重新"
                f"跑一次生成——本工具不会对未知版本猜测迁移。")
        required = ("run_id", "plan", "brief", "script", "drafts",
                    "terminal_shots", "last_audit", "delivered_shots",
                    "llm_calls", "tool_calls", "reason")
        missing = [name for name in required if name not in payload]
        if missing:
            raise ResumeStateError(
                f"resume_state 缺少字段：{', '.join(missing)}。文件可能被"
                f"截断或不是本工具写出的版本。")
        if payload.get("plan") is not None and not isinstance(
                payload.get("plan"), dict):
            raise ResumeStateError("resume_state.plan 必须是对象或 null")
        if payload.get("brief") is not None and not isinstance(
                payload.get("brief"), dict):
            raise ResumeStateError("resume_state.brief 必须是对象或 null")
        state = cls(
            version=version,
            run_id=str(payload.get("run_id") or ""),
            saved_at=str(payload.get("saved_at") or ""),
            plan=dict(payload["plan"]) if payload["plan"] is not None else None,
            brief=(dict(payload["brief"])
                   if payload["brief"] is not None else None),
            script=str(payload.get("script") or ""),
        )
        for name in ("drafts", "terminal_shots", "last_audit"):
            value = payload.get(name)
            if not isinstance(value, dict):
                raise ResumeStateError(f"resume_state.{name} 必须是对象")
            setattr(state, name, {str(k): (dict(v) if name != "terminal_shots"
                                           else str(v))
                                  for k, v in value.items()})
        unknown_statuses = sorted({status for status in
                                   state.terminal_shots.values()
                                   if status not in RESUME_TERMINAL_STATUSES})
        if unknown_statuses:
            raise ResumeStateError(
                f"resume_state.terminal_shots 有未知终态："
                f"{', '.join(unknown_statuses)}（合法闭集："
                f"{', '.join(RESUME_TERMINAL_STATUSES)}）")
        delivered = payload.get("delivered_shots")
        if not isinstance(delivered, list):
            raise ResumeStateError("resume_state.delivered_shots 必须是数组")
        state.delivered_shots = [str(item) for item in delivered]
        for name in ("llm_calls", "tool_calls"):
            value = payload.get(name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ResumeStateError(f"resume_state.{name} 必须是整数")
            setattr(state, name, int(value))
        state.reason = str(payload.get("reason") or "")
        return state


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")


def save_resume_state(path, state: "ResumeState") -> Path:
    """原子写 ``resume_state.json``（临时文件 + ``os.replace``）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{_now_iso().replace(':', '')}"
                                 f".tmp")
    payload = state.to_dict()
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        os.replace(str(temporary), str(target))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except (AttributeError, OSError):
            if temporary.exists():
                temporary.unlink()
    return target


def load_resume_state(path) -> "ResumeState":
    """读并校验 ``resume_state.json``；任何不可用都抛 :class:`ResumeStateError`。"""
    target = Path(path)
    if not target.exists():
        raise ResumeStateError(
            f"找不到断点文件：{target}。请确认第一次运行是在墙钟撞线收尾"
            f"（它会写出 resume_state.json），或检查 --resume 目录是否正确。")
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResumeStateError(f"断点文件无法读取：{exc}") from exc
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ResumeStateError(
            f"断点文件不是合法 JSON：{exc}。文件可能被截断；本工具不会对"
            f"残缺内容做任何猜测。") from exc
    return ResumeState.from_dict(payload)


def plan_for_shots(plan: "Plan", shot_ids) -> "Plan":
    """保留镜头顺序，过滤出指定镜头（交付层按"已完成镜"导出用）。"""
    keep = {str(shot_id) for shot_id in shot_ids}
    return Plan(
        shots=[shot for shot in plan.shots if str(shot.shot_id) in keep],
        continuity_notes=list(plan.continuity_notes),
        scene_heading=plan.scene_heading,
        environment=dict(plan.environment),
    )


def _audit_result_from_dict(shot_id: str,
                            payload: Dict[str, Any]) -> AuditResult:
    """把 resume_state 里存的审核结论还原成 AuditResult（contracts 无 from_dict）。"""
    return AuditResult(
        passed=bool(payload.get("passed", False)),
        level=str(payload.get("level") or "rule"),
        errors=[AuditError.from_dict(item)
                for item in (payload.get("errors") or [])
                if isinstance(item, dict)],
        warnings=[AuditError.from_dict(item)
                  for item in (payload.get("warnings") or [])
                  if isinstance(item, dict)],
        suggestions=[str(item) for item in (payload.get("suggestions") or [])],
        score=payload.get("score"),
        target=str(payload.get("target") or shot_id),
    )


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
    #: 一次定向修复允许几轮 LLM（``1`` = 老行为）。见
    #: `orchestration.repair_max_turns`——真跑里 104 个修复回合有 72 个
    #: 死在"查资料 + 看场景就用光唯一一轮"。
    repair_turns: int = 3

    @classmethod
    def from_config(cls, config=None, *, llm_timeout_s=None,
                    **overrides) -> "DriverLimits":
        """Resolve an omitted timeout from config; preserve explicit overrides.

        ``None`` means the caller did not choose a timeout. The legacy
        no-config constructor still uses 120s; a supplied runtime configuration
        owns the default for GUI and command-line runs.
        """
        if llm_timeout_s is None and config is not None:
            llm_timeout_s = getattr(config.llm, "timeout_s", cls.llm_timeout_s)
        if llm_timeout_s is not None:
            overrides["llm_timeout_s"] = float(llm_timeout_s)
        return cls(**overrides)


def tool_call_budget(effective_llm_calls: int, floor: int) -> int:
    """工具调用上限：**静态下限**与**本场 LLM 回合上限**取大（2026-10-04 实测）。

    为什么不能再是一个固定常量：`DriverLimits.max_tool_calls` 原来是 200，与场景规模
    无关。64 镜那趟真跑（`docs/evidence/20261004_chunked_long15/`）里它在第 **362 s**
    就被用光，此后 **57 次修复回合全部被拒**（`repair_invalid: 工具调用次数超限`），
    占整跑最后 117 s（24%），37 镜撞上修复上限被降级——**片子后四分之一一次也没修**。

    口径：工具调用是 **LLM 回合的动作**，所以它的上限不该低于 LLM 回合的上限；
    真正的节流仍然来自 LLM 预算（`budget.max_llm_calls_*`）与墙上时间，
    这里只是保证"预算还没花完，工具却不许用"这种自相矛盾不会发生。
    """
    return max(int(floor), int(effective_llm_calls))


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
        #: v1.6 F2（D-09）：断点续跑。``resume_state_path`` 是 checkpoint 的
        #: 落盘位置（缺省从审计目录推导：``<项目>/resume_state.json``）；
        #: ``resume_state`` 是调用方已加载的断点（``load_resume_state``）。
        #: 两者都是可选：不传就退回 v1.5 的"撞线即整跑作废"行为，零差异。
        resume_state_path: Optional[Any] = None,
        resume_state: Optional["ResumeState"] = None,
    ) -> None:
        self.transport = transport
        self.audit = audit
        self.script = script
        self.parsed_script = parsed_script
        self.config = config
        self.limits = limits if limits is not None else DriverLimits.from_config(config)
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
        #: token 上限的**静态下限**：`_apply_scene_budget` 只会把它抬上去、绝不压下来，
        #: 所以先在这里留一份原始值（重复调用同一条公式 ⇒ 结果不变，幂等）。
        self._static_token_floor = int(self.budget.limits.max_tokens)
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
        #: v1.5 §7（P6-T2）Best-of-N：当前镜已收到的候选草案，以及低分候选
        #: （进 shots.json 的 ``alternates[]``，**不过滤**）。默认
        #: ``draft_candidates=1`` 时这两个容器永远是空的 ⇒ 零行为差。
        self._draft_candidates: List[Any] = []
        self._draft_alternates: Dict[str, List[Dict[str, Any]]] = {}
        self._editor_payload_cache: Optional[ChatPayload] = None
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
        #: v1.5：**计划失败次数**（与 `_plan_attempts` 分列）。分块时每一段都是
        #: 一次正常调用，重试额度只能被"真正的失败"吃掉——否则 64 镜的第 3 段
        #: 会因为前两段成功而报"已达最大尝试次数"。
        self._plan_failures = 0
        #: v1.5：长分镜表分块出计划的状态（`None` = 还没算；空表 = 不分块）。
        #: `_plan_chunks` 是**段描述**，`_plan_chunk_index` 是"轮到第几段"，
        #: `_plan_shots` 是**已合并的各段镜头**（只有全部段到齐才落成 `self.plan`）。
        self._plan_chunks: Optional[List[Dict[str, Any]]] = None
        self._plan_chunk_index = 0
        self._plan_shots: List[Any] = []
        self._plan_head: Dict[str, Any] = {}
        self._reply_q: "queue.Queue[tuple]" = queue.Queue()
        self._cancel = threading.Event()
        self._paused = False
        self._call_started = 0.0
        self._pending_request_id = ""
        self._pending_payload: Any = None      # §11.3：trace 要落完整 prompt
        #: v1.6 F1（D-02）：超时重试阶梯。一个 scope = 一次"这个调用"
        #: （repair/react 每镜一个、plan 每次请求一个）；历史只在同一 scope 内
        #: 累计，换 scope 即清零（TDD §4.5）。纯决策，不发网络请求。
        self._ladder_scope = ""
        self._ladder_history: List[CallOutcome] = []
        #: 当前在途的那次调用是不是瘦身包（下一次失败记账用）。
        self._ladder_inflight_slim = False
        #: plan 的下一次请求是否用瘦身包（阶梯决定，跨 plan 请求传递）。
        self._plan_next_slim = False
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
        #: 这一**轮**修复里成功的**只读**查询数。续轮的判据要用它：
        #: 只有"看了却没动手"才值得再给一轮。
        self._repair_queries_ok: int = 0
        self.repair_messages: List[Message] = []
        #: 本轮**尝试**已经用掉几轮 LLM（``repair_max_turns`` 是上限）。
        #: 它与 `_repair_attempts` 不是一回事：尝试是"这一镜修了几次"
        #: （§7.1 B4 的上限 2），轮次是"一次尝试里模型回了几次"。
        self._repair_turns: int = 0
        #: 这次尝试可用的工具 schema（延续轮必须与原轮**同一套**，
        #: 包括"纯时间轴审计只给 emit_shot_draft"那条收窄）。
        self._repair_tools: List[Dict[str, Any]] = []
        #: 逐镜的**修复前基线**（`{shot_id: {"rules": frozenset, "plan": Plan}}`）：
        #: 用来判"这次修复有没有把片子改坏"。见 `_rollback_repair_if_worse`。
        self._repair_baseline: Dict[str, Dict[str, Any]] = {}
        #: 刚回滚过：下一次审核事件要标 `restored: true`（只影响那一条事件）。
        self._just_rolled_back: bool = False
        self.rollback_events: List[Dict[str, Any]] = []

        # --------------------------------------------------- v1.6 F2 断点续跑
        self._resume_state = resume_state
        if resume_state_path is not None:
            self._resume_state_path: Optional[Path] = Path(resume_state_path)
        elif self.audit.directory is not None:
            self._resume_state_path = (
                Path(self.audit.directory).parent / RESUME_STATE_FILENAME)
        else:
            self._resume_state_path = None
        #: 每镜终态（passed/degraded/finished/unverified）；checkpoint 与
        #: resume 的跳过判据都从它出。
        self._shot_terminal: Dict[str, str] = {}
        #: **resume 那一刻**就是终态的镜号（冻结集合）。跳过判据只看它——
        #: 运行中途新标终态的镜头已经出队，不该再被"跳过"逻辑误伤
        #: （实测：ReAct 精修前先标 degraded 会让同一镜在精修后被跳过）。
        self._resume_terminal: set = set()
        self._resume_last_audit: Dict[str, Dict[str, Any]] = {}
        self._resume_drafts: Dict[str, Dict[str, Any]] = {}
        self._resume_delivered: set = set()
        self._wall_clock_exhausted: bool = False
        self._apply_resume_state()

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
            # The count stays compatible with UI/debug consumers; unattended
            # export also needs a detached, JSON-safe per-shot record list.
            "self_review_requests": copy.deepcopy(self.review_requests),
            "react_rounds": len(self.react_history),
            "brief": (self.brief.to_dict() if self.brief is not None
                      else None),
            "brief_source": (self.brief.source if self.brief is not None
                             else ""),
            "drafts": len(self.draft_history),
            "drafts_failed": len(self.drafts_failed),
            #: v1.5 §7（P6-T2）：Best-of-N 里被降级成备选的候选（低分候选进
            #: shots.json 的 alternates[]，**不丢**）。默认 draft_candidates=1
            #: 时恒为空表。
            "draft_alternates": {shot_id: [dict(item) for item in items]
                                 for shot_id, items in
                                 self._draft_alternates.items()},
            "compliance": self._compliance,
            #: v1.4 P15（§3.3）：交付清单要的两张表，由驱动器产出。
            "timing_overrides": list(self.timing_overrides),
            "audit_pass_rate": self._audit_pass_rate(),
            #: E2（§2.3b）：逐镜知识溯源，交付层写 ``movements[].source`` 用。
            "knowledge_provenance": self.knowledge_provenance(),
            #: v1.6 F2（D-09）：断点续跑的对外读数——终态镜、墙钟撞线标志与
            #: checkpoint 落盘位置。没有配置 resume 路径时后两者为空/False。
            "terminal_shots": {str(k): str(v)
                               for k, v in self._shot_terminal.items()},
            "wall_clock_exhausted": self._wall_clock_exhausted,
            "resume_state_path": (str(self._resume_state_path)
                                  if self._resume_state_path else None),
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
        wall_reason = self._wall_clock_reason()
        if wall_reason and self.state not in TERMINAL_STATES:
            # v1.6 F2（D-09）：墙钟撞线**不是** run_failed——已完成的镜头
            # 必须保下来（checkpoint + 交付收尾），而不是把整跑作废。
            self._wrap_up_wall_clock(wall_reason)
            return True
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
                # v1.6 F2（D-09）：撞线收尾（写 resume_state + CANCELLED），
                # 而不是把已经通过的镜头一起作废。
                self._wrap_up_wall_clock(f"超出墙上时间上限 {max_wall_s}s")
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

    def _cast_roster(self, include_from: Optional[Plan] = None) -> List[str]:
        """v1.6 A2：角色表 = 剧本角色名 + 已分配内部 id（char_NNN）。

        离线/夹具把剧本名映射为 ``char_001``..``char_NNN``；真实模型运行
        应按角色名写计划。为兼容夹具，``include_from`` 里的 ``char_NNN``
        也加入角色表，但占位符（``char_a``/``char_b`` 等）仍会被拒。
        """
        names = self._character_names()
        allocated: List[str] = []
        for plan in (self.plan, include_from):
            if plan is None:
                continue
            for shot in plan.shots:
                for cid in (shot.characters or ()):
                    if (isinstance(cid, str)
                            and cid.startswith("char_")
                            and cid[5:].isdigit()
                            and cid not in allocated):
                        allocated.append(cid)
        return list(dict.fromkeys(names + allocated))

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
        #: 计的是**失败次数**（见 `_route_llm_error` 的同名注释）：分块的每一段
        #: 都是一次正常调用，不该吃掉重试额度。
        if self._plan_failures >= self.limits.plan_attempts:
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
            self._handle_llm_error(str(payload), duration)
            return

        reply: ChatReply = payload
        #: v1.6 F1：一次调用**成功**就结束它的重试阶梯——历史只描述"这一个调用"
        #: 的失败。不清零的话，同一镜先失败一次、成功、下一次修复又失败一次，
        #: 就会被当成"第二次失败"直接降级（违背"同一提示最多 2 次"）。
        self._ladder_history = []
        self._ladder_inflight_slim = False
        if self._call_purpose == "plan":
            #: 收到回复 ⇒ 这次 plan 请求不再处于超时阶梯里：下一段/下次请求
            #: 恢复完整提示（瘦身只属于"上一个请求超时"的那一步）。
            self._plan_next_slim = False
        self.budget.record_llm(reply.usage)
        self.audit.log_llm(purpose, reply, duration, self._pending_request_id,
                           payload=self._pending_payload)

        if repairing:
            problem = self._dispatch_tool_calls(reply, self.repair_messages)
            if problem:
                self.audit.log("repair_invalid", problem, level="warning")
            mutated = bool(self._repair_tools_ok) or self._needs_rebuild
            #: 这一轮**没动手**（只读查询）而额度还有：把**工具观测真的回灌**，
            #: 再来一轮。老行为是"一次回复就收尾"，而真跑（2026-10-04，long17）
            #: 里 104 个修复回合有 72 个恰好是 `search_knowledge` ＋
            #: `get_scene_state`——"查资料 + 看场景"就用光了唯一一轮；更糟的是
            #: 那些观测此前写进 `repair_messages` 后**从没被发回**，模型连自己
            #: 刚查到的东西都看不见。
            if not mutated and self._can_continue_repair():
                self._repair_turns += 1
                self.audit.log(
                    "repair_turn",
                    f"{self._current_shot_id} 修复回合未动手，继续第 "
                    f"{self._repair_turns + 1} 轮", level="warning",
                    shot=self._current_shot_id, turns=self._repair_turns)
                self._emit("repair_turn", "修复回合未动手，继续一轮",
                           shot=self._current_shot_id,
                           turns=self._repair_turns)
                self._continue_repair()
                return
            self._repair_attempts += 1
            self._repairs_total += 1
            self._mark_repair_applied(applied=mutated)
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
            self._plan_failures += 1
            self.audit.log("plan_invalid", problem, level="error")
            #: 分块时**只重试当前这一段**（`_plan_chunk_index` 不动）；
            #: 已收下的前几段留在 `_plan_shots` 里，不白丢。
            self._transition(DriverState.PLANNING)
            return
        if self._plan_needs_more_chunks():
            #: v1.5：长分镜表还有下一段 ⇒ 立刻问下一段，**不进** B1/门。
            #: 审计里留一条 `plan_chunk_received`：截断排障的第一问就是"断在第几段"。
            self._plan_chunk_index += 1
            self.audit.log(
                "plan_chunk_received",
                f"分镜计划第 {self._plan_chunk_index}/"
                f"{len(self._plan_chunk_list())} 段已收到"
                f"（累计 {len(self._plan_shots)} 镜），继续下一段",
                stage="plan", shots=len(self._plan_shots))
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
        """把分镜表的「拍摄手法」**落实**成运镜（v1.3 §3.6 ＋ v1.4 §八十五）。

        两件事，方向相反、纪律同一条（"声明的必须落实"）：

        * 声明了**非固定**手法而草案没给 ⇒ 钉上（v1.3 起的老行为）；
        * 声明了**固定镜头**而草案自己加了运动 ⇒ **去掉**（这一轮新增）。

        后半段为什么是必须的（2026-10-04 实测，§八十五）：分镜表为 **63 镜**声明
        "固定镜头"，交付里 **40 镜**在这条声明之外自己动了相机（`movements[].source`
        只有 1 次归给 `declared`）。把那些未声明的运动去掉后重建、逐镜复评（零 LLM）：

        | 工程 | 逐镜通过 | 构图门（≥70） | 构图分中位 |
        |---|---|---|---|
        | long17 | 29 → **35** | 44 → **55** | 85.6 → **89.5** |
        | long15 | 27 → **29** | 35 → **39** | 71.4 → **77.4** |
        | long18 | 22 → 22 | 31 → **33** | 66.5 → **72.5** |

        ⇒ **忠于分镜表同时更好**；而且它正是链上 Q5 差的那 0.05 的根因——
        检索串与标注都期望 `固定`、交付却是 `push_through`（§八十五 三条不通过）。
        """
        pinned = 0
        for index, shot in enumerate(self.plan.shots):
            if index >= len(declared):
                break
            movement = str(getattr(declared[index], "camera_move", "") or "")
            camera = dict(getattr(shot, "camera", None) or {})
            #: `static` 在这里没有可钉的东西（引擎词表里没有"固定"＝不动），
            #: 但**它不是不管**：草案往后想给这一镜加运动时，
            #: `editor.merge_camera` 会按声明把它挡掉（§八十五）。
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

    # -------------------------------------------------- v1.6 F1 超时重试阶梯
    @staticmethod
    def _retry_policy() -> RetryPolicy:
        """阶梯策略（卡 F1 钉死）：同一份提示最多 2 次、超时改发瘦身包。"""
        return RetryPolicy(max_attempts=2, slim_on_timeout=True, degrade_after=True)

    def _retry_scope_for(self, purpose: str) -> Optional[str]:
        """这一阶段的阶梯 scope；不在阶梯内的阶段返回 ``None``。"""
        if purpose == "plan":
            return "plan"
        if purpose in ("repair", "react"):
            shot_id = self._react_shot if purpose == "react" else self._current_shot_id
            return f"{purpose}:{shot_id or ''}"
        return None

    def _reset_retry_ladder(self, scope: str, *, slim: bool = False) -> None:
        """开始一个新的阶梯 scope（换镜 / 新的 plan 请求时调用）。"""
        self._ladder_scope = scope
        self._ladder_history = []
        self._ladder_inflight_slim = bool(slim)

    def _log_retry_step(self, decision: str, problem: str, elapsed_s: float,
                        shot_id: str) -> None:
        """每走一步阶梯都记一条 ``retry_ladder`` 事件（TDD §3.6 三键齐备）。"""
        self.audit.log(
            "retry_ladder",
            f"{self._call_purpose} 传输错误（{problem[:160]}）→ {decision}",
            level="warning",
            stage=STAGE_OF.get(decision, decision),
            shot_id=shot_id,
            elapsed_s=round(float(elapsed_s), 3),
        )

    def _handle_llm_error(self, problem: str, elapsed_s: float) -> None:
        """一次传输错误的阶梯化落点（v1.6 F1，TDD §4.5）。

        只在 repair / react / plan 三处接阶梯：同一 scope 内先问纯状态机
        ``next_step``，再按决定走：

        * ``retry_same``：同一份载荷再发一次（新 request_id）；
        * ``retry_slim``：消息过 ``slim_messages`` 后再发（只去 RAG 三栏）；
        * ``degrade``：落回既有按阶段的恢复路径，且 repair 不会再赌第三次。

        其余阶段（understand / editor / review）原样走 ``_recover_from_llm_error``。
        """
        purpose = self._call_purpose
        scope = self._retry_scope_for(purpose)
        if scope is None:
            self._recover_from_llm_error(purpose, problem)
            return
        if self._ladder_scope != scope:
            self._reset_retry_ladder(scope)
        outcome = CallOutcome(ok=False, timed_out=is_timeout(problem),
                              slim=self._ladder_inflight_slim)
        self._ladder_history.append(outcome)
        decision = next_step(self._ladder_history, self._retry_policy())
        shot_id = (self._react_shot if purpose == "react" else
                   self._current_shot_id if purpose == "repair" else "")
        self._log_retry_step(decision, problem, elapsed_s, shot_id)
        if decision in (RETRY_SAME, RETRY_SLIM):
            self._retry_or_charge(purpose, decision)
            return
        # DEGRADE：同一份提示的命已用完，落回既有按阶段的恢复。
        if purpose == "repair":
            #: 既有恢复路径只回 CHECKING，复审不过还会发起**第三次**修复调用——
            #: 卡 F1 禁止。把这一镜的修复额度直接钉到上限，让 CHECKING 走
            #: "shot_degraded → 前进（或 B5）"的老路，不赌第三次。
            self._repair_attempts = max(self._repair_attempts,
                                        self.limits.max_repairs_per_shot)
            self.audit.log(
                "repair_failed",
                f"{shot_id} 修复调用连续失败（重试阶梯降级）：{problem}",
                level="warning", shot=shot_id)
            self._transition(DriverState.CHECKING)
            return
        self._recover_from_llm_error(purpose, problem)

    def _retry_or_charge(self, purpose: str, decision: str) -> None:
        """把 ``retry_same`` / ``retry_slim`` 变成一次真正的再调用。

        plan 的"重试"走既有 ``plan_attempts`` 预算（卡 F1 的 reconcile）：记一次
        计划失败、由 ``_step_planning`` 决定是否再发起——**绝不**给计划加出
        预算之外的调用，也因此超时后的 plan 永远不再收到"原样的完整提示"。
        repair / react 直接重发同一份载荷（新 request_id；``retry_slim`` 只把
        消息过 ``slim_messages``，该镜声明、审计发现与工具结果一律保留）。
        """
        slim = (decision == RETRY_SLIM
                or (decision == RETRY_SAME and self._ladder_inflight_slim))
        if purpose == "plan":
            self._plan_failures += 1
            self._plan_next_slim = bool(slim)
            self._transition(DriverState.PLANNING)
            return
        payload = self._pending_payload
        retry = replace(payload, request_id=new_request_id())
        if slim:
            retry.messages, _removed = slim_messages(payload.messages)
        self._ladder_inflight_slim = bool(slim)
        self._start_llm_call(purpose, retry,
                             note=f"重试 {purpose}（阶梯：{decision}）")

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
            # 计划失败由 _step_planning 决定是否再试。**计的是"失败次数"**，
            # 不是"调用次数"：长分镜表要问 ⌈N/24⌉ 段（实测 64 镜 = 3 段），
            # 把成功的段也计进去会让第 3 段还没问就报"已达最大尝试次数"
            # （2026-10-03 的分块用例当场抓到这个）。
            self._plan_failures += 1
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
        #: 新的一镜：候选累加器清零（P6-T2）。同镜的第 2…N 个候选走
        #: `_finish_editor_turn` 里的续发路径，不经过这里，因此不会误清。
        self._draft_candidates = []
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
        #: 缓存这一份 payload：同镜的第 2…N 个候选**直接复用它**，不再发起一次
        #: 检索——否则候选数会把 `retrieval_calls` 一起放大（§2.4 的预算账）。
        self._editor_payload_cache = payload
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

    def _draft_context(self, shot_id: str):
        """这一镜的 ``(characters, anchors)``，供 ``extract_draft`` 校拍点引用。

        v1.5 §3.1（P2-T4）：拍点的 ``subject``/``target`` 必须在**本镜角色**
        或**本场锚点**里解析得到。``anchors`` 从 ``plan.environment.anchors[].name``
        取（阶段 A 的产物）——**给空表就是"本场没有锚点"**，此时 target 只能
        落到角色上（与 ``validate_beats`` 的"未知 vs 空"语义一致，不猜）。
        """
        characters: list = []
        anchors: list = []
        if self.plan is not None:
            for shot in self.plan.shots:
                if shot.shot_id == shot_id:
                    characters = [str(c) for c in (shot.characters or [])]
                    break
            environment = getattr(self.plan, "environment", None) or {}
            anchors = [str((item or {}).get("name") or "")
                       for item in (environment.get("anchors") or [])
                       if isinstance(item, dict)]
            anchors = [name for name in anchors if name]
        return characters, anchors

    def _finish_editor_turn(self, reply: ChatReply) -> None:
        shot_id = self._editing_queue[self._editing_index]
        characters, anchors = self._draft_context(shot_id)
        try:
            draft = extract_draft(reply, shot_id, characters=characters,
                                  anchors=anchors)
        except ValueError as exc:
            # 单镜草案失败不拖垮整场：记进 history 与警告，这一镜沿用计划内容，
            # 后面还有 B3/B4 兜住真正的执行问题。
            self.drafts_failed.append({"shot_id": shot_id, "error": str(exc)})
            self.audit.log("draft_invalid", f"{shot_id}: {exc}", level="warning",
                           shot=shot_id)
            self._emit("draft_invalid", f"{shot_id} 草案无效", shot=shot_id)
            self._draft_candidates = []
            self._editor_payload_cache = None
            self._editing_index += 1
            self._transition(DriverState.EDITING)
            return

        self._draft_candidates.append(draft)
        wanted = self._draft_candidate_count()
        if len(self._draft_candidates) < wanted \
                and self.budget.allow_llm_call("editor") \
                and self._editor_payload_cache is not None:
            # Best-of-N（P6-T2）：对**同一镜**再要一个候选。复用缓存 payload ⇒
            # 不重复发起检索；候选数不放大 `retrieval_calls`。
            self._start_llm_call(
                "editor", self._editor_payload_cache,
                note=f"单镜结构化生成 {shot_id}（候选 "
                     f"{len(self._draft_candidates) + 1}/{wanted}）")
            return

        best, alternates = rank_drafts(self._draft_candidates,
                                       characters=characters, anchors=anchors)
        if best is not None:
            self.plan = merge_draft(self.plan, best)
            self.draft_history.append(best.to_dict())
            if alternates:
                self._draft_alternates[shot_id] = [item.to_dict()
                                                    for item in alternates]
            self.audit.log("draft_received",
                           f"{shot_id}: {len(best.actions)} 个动作 / "
                           f"{len(best.dialogues)} 句对白",
                           shot=shot_id, actions=len(best.actions),
                           dialogues=len(best.dialogues),
                           #: 只在真的开了 Best-of-N 时才写候选数——默认 1 时
                           #: 事件形状与升级前逐字节相同（NFR-4）。
                                   **({"candidates": len(self._draft_candidates)}
                                       if wanted > 1 else {}))
            self._emit("draft_received", f"{shot_id} 草案已合并", shot=shot_id)
            # v1.6 F2（D-09）：B1 每镜起草成功即落 checkpoint——即使接下来
            # 进程被杀，这一镜的草案也不会丢。
            self._resume_drafts[shot_id] = best.to_dict()
            self._checkpoint_resume(stage="draft", shot_id=shot_id)
        self._draft_candidates = []
        self._editor_payload_cache = None
        self._editing_index += 1
        self._transition(DriverState.EDITING)

    def _draft_candidate_count(self) -> int:
        """每镜要几个候选（``orchestration.draft_candidates``，默认 1 = 现状）。"""
        if self.config is None:
            return 1
        value = getattr(self.config.orchestration, "draft_candidates", 1)
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

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
            #: 2026-10-07 实测：审计里只有一行 `TypeError: ...`，**traceback 被丢掉了**，
            #: 于是一次真实的构建崩溃只能靠"重跑一遍 20 分钟"才定位得到（长剧本那一跑
            #: 的 `could not convert string to float: 's'` 就是这么丢的）。日志里留全文，
            #: 审计里仍只留一行摘要——审计是**结论**，日志是**证据**。
            log.error("场景构建失败：\n%s", traceback.format_exc())
            self.audit.log("build_failed", f"{type(exc).__name__}: {exc}",
                           level="error")
            self._fail(f"场景构建失败：{type(exc).__name__}: {exc}")
            return
        self.build_summary = dict(summary)
        #: v1.5 §7（P6-T2）：Best-of-N 的备选草案写进**这一镜的 build result**
        #: （manifest 已按 shot_id 读这份 results）。默认无备选 ⇒ 一个键都不加，
        #: 交付清单与升级前逐字节相同。
        if self._draft_alternates:
            results = self.build_summary.get("results")
            if isinstance(results, list):
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    alternates = self._draft_alternates.get(
                        str(item.get("shot_id")))
                    if alternates:
                        item["alternates"] = [dict(entry)
                                              for entry in alternates]
        duration = self.clock() - started
        #: v1.6 A6（D-08）：第二条 scene_built 不是日志重复，而是修复回路的就地重建
        #: （重提草案 ⇒ `_needs_rebuild`；修复回滚 ⇒ `_just_rolled_back`，两者都置
        #: `_rebuild_in_place` 回到 BUILDING）。行为不改，只补可观测性；取值只读
        #: 驱动器已有状态，不新增状态。回滚优先于"修复改了计划"。
        reason = scene_built_reason(rebuild_in_place=self._rebuild_in_place,
                                    just_rolled_back=self._just_rolled_back)
        #: 构建摘要里若恰好也有 `reason`/`duration_s` 键，不得覆盖事件自己的字段
        #: （也不能让关键字参数重名直接抛 TypeError）。
        scalars = {k: v for k, v in self.build_summary.items()
                   if isinstance(v, (int, float, str))
                   and k not in SCENE_BUILT_RESERVED_KEYS}
        self.audit.log("scene_built", "场景已构建",
                       reason=reason,
                       duration_s=round(duration, 3),
                       **scalars)
        self._emit("scene_built", "场景已构建", reason=reason, **scalars)
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

    def _rollback_repair_if_worse(self, shot_id: str,
                                  result: AuditResult) -> bool:
        """这次修复**把片子改坏了**吗？坏就把计划与场景退回修复前的基线。

        现场（2026-10-04，真跑复算）：long16 有 **12** 镜、long15 有 **4** 镜在修复
        之后**多出**了原本没有的违规（典型：为了让构图合格去挪机位，顺手把 R001
        轴线踩了）。long18 里"构图触底（≤20.0）"的镜头由 8 涨到 16。系统此前对
        这种退化**没有任何动作**——`repair_applied` 照写，改坏的那一版留在交付里。

        判据刻意取**严格变多**（`new - baseline` 非空）而不是"没变好"：
        - 清掉一条规则 ⇒ 改善，留；
        - 规则集不变 ⇒ 修没修成是另一回事（`shot_degraded` 会记账），不回滚；
        - **多出一条** ⇒ 这次修复引入了观众看得见的新毛病 ⇒ 回滚。

        回滚用**已有**的机制，不新造一套：计划换成基线快照，然后走"计划变了 ⇒ 重建"
        那条现成通路（`_needs_rebuild` ＋ `_rebuild_in_place`），场景由构建器按计划
        重建（bpy 侧一次，**不花 token**）。审核照旧在重建后跑，那条事件带
        `restored: true`，账上分得清"审的是哪一版"。
        """
        shot_id = str(shot_id)
        baseline = self._repair_baseline.get(shot_id)
        if baseline is None or self.plan is None or self.builder is None:
            return False
        if self._repair_attempts <= 0:
            #: 还没修过 —— 这是**首次**审计，没有"改坏"可言。
            return False
        after = frozenset(str(item.rule) for item in (result.errors or []))
        introduced = sorted(after - frozenset(baseline["rules"]))
        if not introduced:
            return False
        self.plan = copy.deepcopy(baseline["plan"])
        #: 回滚即认输：这一镜不再修（否则下一次修复又会踩同一个坑，白烧回合）。
        self._repair_attempts = int(self.limits.max_repairs_per_shot)
        event = {"shot_id": shot_id, "before": sorted(baseline["rules"]),
                 "after": sorted(after), "introduced": introduced}
        self.rollback_events.append(event)
        self.audit.log(
            "repair_rolled_back",
            f"{shot_id} 的修复引入了新的违规 {introduced}，已回滚到修复前",
            level="warning", shot=shot_id, before=event["before"],
            after=event["after"], introduced=introduced)
        self._emit("repair_rolled_back",
                   f"{shot_id} 修复回滚（引入 {introduced}）", shot=shot_id)
        self._just_rolled_back = True
        self._needs_rebuild = True
        self._rebuild_in_place = True
        self._transition(DriverState.BUILDING)
        return True

    def _audit_shot(self, shot_id: str, *, degraded: bool = False,
                    restored: bool = False
                    ) -> Optional[AuditResult]:
        """跑一次审核并把结论**逐字**记进 `audit_log.jsonl`（零 LLM、零工具）。

        `degraded=True` 专指"预算触顶之后补审的那一批"：结论照记，事件里多一个
        `degraded` 标记，读账的人一眼能分清"审过、没过"与"根本没过审"。
        （正常路径**不加**这个键，历史事件的形状因此一个字节都没变。）

        审核器自身抛异常时返回 `None` 并记 `audit_failed`——注意它与"这一镜没过"
        是两回事，两种都在账上分得开。
        """
        if self.auditor is None:
            return None
        try:
            result = self.auditor.audit(shot_id)
        except Exception as exc:  # noqa: BLE001 - 审核器自身出错不该拖垮整场
            self.audit.log("audit_failed",
                           f"{shot_id} 审核器异常：{type(exc).__name__}: {exc}",
                           level="error", shot=shot_id)
            self._emit("audit_failed", f"{shot_id} 审核异常", shot=shot_id)
            return None
        self.audit_results.append(result)
        # v1.4 §3.3（R45）：shot_audit 增写构图分与阈值——两者是同一次审核里
        # 已经算好的量（``AuditResult.score`` 与审核器的门限），阈值只有一个来源。
        threshold = getattr(self.auditor, "composition_threshold", None)
        #: v1.5：**记下是哪几条规则红的**。此前事件里只有 `errors=2` 这样的计数，
        #: 于是"通过率掉了"这件事根本没法归因——2026-10-03 的 64 镜真跑就是
        #: 29/56、而没人知道红的是构图、R002 还是 R011。规则名、码与严重度都在
        #: `AuditResult` 里现成，落盘不额外花钱；`rule_ids` 只列 ERROR 级。
        findings = [item.to_dict() for item in
                    (list(result.errors) + list(result.warnings))[:12]]
        #: v1.5 §5.4（P4-T4）：**破例辩护对拍**（声明 vs 实测）。只在真有内容时
        #: 写进事件（与 `restored`/`degraded` 同一纪律）——没声明、没违规的镜不在
        #: 事件里多一个空键，历史事件形状因此一个字节都没变。
        reconciliation = getattr(result, "justification_audit", None) or {}
        reconciliation_extra = {}
        if any(reconciliation.get(key) for key in
               ("declared_breaks", "declared_follows", "detected_violations")):
            reconciliation_extra["justification_audit"] = dict(reconciliation)
            #: 交付清单也要这一栏（§6 第 8 步：shots.json 收破例对拍结果）。写进
            #: 这一镜的 build result——manifest 本就按 shot_id 读这份 results，
            #: 不必再新开一条从驱动器到导出层的管道。
            self._record_justification_audit(shot_id, reconciliation)
        #: v1.5 §5.5（P6-T1）：**外部评审外回路**。缺省关 ⇒ 这里恒为空、
        #: 事件与交付物一个字节都不变；打开后也只多一个键，**不改判定**。
        review = getattr(result, "vlm_review", None) or {}
        review_extra = {}
        if review:
            review_extra["vlm_review"] = dict(review)
            self._record_vlm_review(shot_id, review)
        self.audit.log("shot_audit", f"{shot_id}: {result.format_for_llm().splitlines()[0]}",
                       level="info" if result.passed else "warning",
                       shot=shot_id, passed=result.passed,
                       errors=len(result.errors), warnings=len(result.warnings),
                       rule_ids=[item["rule"] for item in findings
                                 if item.get("severity") == "error"],
                       findings=findings,
                       composition_score=result.score,
                       composition_threshold=threshold,
                       **reconciliation_extra,
                       **review_extra,
                       **({"restored": True} if restored else {}),
                       **({"degraded": True} if degraded else {}))
        self._emit("shot_audit",
                   f"{shot_id} {'通过' if result.passed else '未通过'}",
                   shot=shot_id, passed=result.passed)
        return result

    def _record_vlm_review(self, shot_id: str, review: Dict[str, Any]) -> None:
        """把这一镜的外部评审判词写进 ``build_summary["results"]``（交付层读它）。

        与 ``_record_justification_audit`` 同一条纪律：找不到对应 result 就跳过
        ——交付层在缺失时不写这个键（"没评过"与"评了 0 分"必须分得开）。
        """
        results = self.build_summary.get("results")
        if not isinstance(results, list):
            return
        for item in results:
            if isinstance(item, dict) and str(item.get("shot_id")) == str(shot_id):
                item["vlm_review"] = dict(review)
                return

    def _record_justification_audit(self, shot_id: str,
                                    reconciliation: Dict[str, Any]) -> None:
        """把这一镜的破例对拍写进 ``build_summary["results"]``（交付层读它）。

        找不到对应 result 就跳过（例如审核发生在没有构建结果的路径上）——这
        **不是**降级：交付层在缺失时会写成四个空集（"查过、两边都空"），
        而不是编一个结论。
        """
        results = self.build_summary.get("results")
        if not isinstance(results, list):
            return
        for item in results:
            if isinstance(item, dict) and str(item.get("shot_id")) == str(shot_id):
                item["justification_audit"] = dict(reconciliation)
                return

    def _step_checking(self) -> None:
        """§7.1 B3：逐镜头校验；不通过就进入定向修复。"""
        if self.auditor is None or not self._shot_queue:
            self._transition(DriverState.FINISHING)
            return
        shot_id = self._shot_queue[0]
        self._current_shot_id = shot_id
        resumed_status = ""
        if str(shot_id) in self._resume_terminal:
            resumed_status = self._shot_terminal.get(str(shot_id), "")
        if resumed_status:
            # v1.6 F2（D-09）：终态镜（passed/degraded/…）从断点恢复时**零
            # LLM 调用**跳过。它的旧审核结论已在 resume 时种回 audit_results，
            # 这里不再重新审——重审会把它重新推进修复回路，白烧模型调用。
            self.audit.log(
                "shot_resumed_skipped",
                f"{shot_id} 终态（{resumed_status}）从断点恢复，跳过",
                shot_id=shot_id, status=resumed_status)
            self._emit("shot_resumed_skipped", f"{shot_id} 从断点跳过",
                       shot_id=shot_id, status=resumed_status)
            self._advance_shot()
            return
        restored = self._just_rolled_back
        self._just_rolled_back = False
        result = self._audit_shot(shot_id, restored=restored)
        if result is None:
            self._mark_terminal(shot_id, "unverified")
            self._advance_shot()
            return
        if self._rollback_repair_if_worse(shot_id, result):
            return
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
            self._mark_terminal(shot_id, "passed" if result.passed
                                else "finished")
            self._advance_shot()
            return
        if result.passed:
            if self._should_self_review(shot_id):
                self._pending_review = shot_id
                self._transition(DriverState.REVIEWING)
                return
            self._mark_terminal(shot_id, "passed")
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
                # v1.6 F2：gate 放行走 `_apply_gate → _advance_shot`，不进
                # 这里的分支——先落终态，否则这镜从断点里消失（实测：smoke
                # 跑的 shot_002 走 gate 收尾后不在 terminal_shots 里）。
                self._mark_terminal(shot_id, "degraded")
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
            self._mark_terminal(shot_id, "degraded")
            self._advance_shot()
            return
        self._pending_audit = result
        self._transition(DriverState.REPAIRING)

    def _advance_shot(self) -> None:
        if self._shot_queue:
            done = self._shot_queue.pop(0)
            #: 这一镜结束了：它的修复基线（含一份计划快照）不再需要，
            #: 留着只会让 64 镜的跑里堆 64 份计划副本。
            self._repair_baseline.pop(str(done), None)
            self._finished_shots.append(done)
        self._repair_attempts = 0
        self._repair_turns = 0
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
            self._mark_terminal(shot_id, "passed")
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
        self._mark_terminal(shot_id, "passed")
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
        #: **修复前基线**：只在这一镜的**第一次**修复前拍（`deepcopy` 计划 + 红着的
        #: 规则集）。修完如果**多出**了新规则，就说明这次修复把片子改坏了，
        #: `_rollback_repair_if_worse` 会把计划与场景一起退回这个基线。
        shot_id = str(self._current_shot_id)
        if shot_id and shot_id not in self._repair_baseline and self.plan is not None:
            self._repair_baseline[shot_id] = {
                "rules": frozenset(str(item.rule) for item in audit.errors),
                "plan": copy.deepcopy(self.plan),
            }
        self._repair_rule = "/".join(rules)
        self._repair_before_score = getattr(audit, "score", None)
        self._repair_tools_ok = 0
        self._repair_queries_ok = 0
        #: 新的一次**尝试**：轮次归零，对话以这次的修复提示词开头。
        self._repair_turns = 0
        temperature = 0.2
        if self.config is not None:
            temperature = float(self.config.llm.temperature_repair)
        payload = build_repair_payload(
            audit, self.registry,
            scene_state=self._scene_state_text(),
            shot=self._shot_by_id(self._current_shot_id),
            #: 把**本次要修的镜头**写进提示词：场景摘要里的"当前镜头"是
            #: `SceneContext.current_shot_id`（构建时落在第一镜），实测 long10
            #: 里模型照抄它，把 `emit_shot_draft` 的 shot_id 写成 shot_001。
            shot_id=str(self._current_shot_id),
            temperature=temperature)
        #: 工具集与对话都要留住：延续轮必须用**同一套**工具（含收窄），
        #: 并且把这一轮的工具观测带回模型。
        self._repair_tools = list(payload.tools)
        if self._repair_attempts:
            #: 第 2 次尝试接着上一轮的修复对话往下谈（同一镜内），不推倒重来：
            #: 上一轮模型查到的观测、看过的审计、收到的循环警告，都是它这一轮
            #: 判断的依据；丢掉它们等于让它重新踩一遍同一个坑。镜头换了
            #: （`_advance_shot`）才会清空。
            self.repair_messages.extend(payload.messages)
            kept, dropped = trim_messages(
                self.repair_messages,
                int(getattr(self.config.orchestration,
                            "context_window_tokens", 32000))
                if self.config is not None else 32000)
            if dropped:
                self.audit.log("context_trimmed",
                               f"修复对话裁剪 {len(dropped)} 条旧观察",
                               level="warning")
            self.repair_messages = kept
        else:
            self.repair_messages = list(payload.messages)
        #: 发出去的必须是**累积**的那份对话（否则上面那段就是白写的）。
        payload.messages = list(self.repair_messages)
        self._start_llm_call("repair", payload,
                             note=f"请求修复 {self._current_shot_id}"
                                  f"（第 {self._repair_attempts + 1} 次）")

    def _repair_turn_limit(self) -> int:
        """一次修复尝试里允许几轮 LLM（``1`` = v1.4 之前的老行为）。"""
        if self.config is None:
            return max(1, int(self.limits.repair_turns))
        return max(1, int(getattr(self.config.orchestration,
                                  "repair_max_turns", self.limits.repair_turns)))

    def _can_continue_repair(self) -> bool:
        """还能再给这一镜一轮吗？（观测、轮次、工具额度、LLM 预算四关）

        "观测"这一关是关键：只有这一轮**真的看到了东西却没动手**
        （`_repair_queries_ok > 0` 且没有改动类工具成功）才值得再给一轮。
        整轮全失败（例：没建场景时 `setup_camera` 必然失败）再给几轮也只是把
        同一次失败重放——`test_sidecar_mode_runs_the_whole_chain` 的夹具正是
        这种形态：那里的 7 次调用不许因为这条改动变成 9 次。
        """
        if not self._repair_queries_ok:
            return False
        if self._repair_turns + 1 >= self._repair_turn_limit():
            return False
        if self._tool_calls >= self.limits.max_tool_calls:
            return False
        return self.budget.allow_llm_call("repair")

    def _continue_repair(self) -> None:
        """同一**次**修复尝试里的下一轮：把上一轮的工具观测真的发回给模型。

        `self.repair_messages` 此前是一张**从来不发回**的草稿单
        （`_dispatch_tool_calls` 往里写、没人读）⇒ 模型在修复回合里调
        `get_scene_state` / `check_composition` 拿到的观测全部丢掉，它只能
        凭审计原文猜，然后这一轮就结束了。
        """
        limit = 32000
        if self.config is not None:
            limit = int(getattr(self.config.orchestration,
                                "context_window_tokens", 32000))
        kept, dropped = trim_messages(self.repair_messages, limit)
        if dropped:
            self.audit.log("context_trimmed",
                           f"修复对话裁剪 {len(dropped)} 条旧观察",
                           level="warning", **budget_report(kept, limit))
        self.repair_messages = kept
        self.repair_messages.append(Message(role=MessageRole.SYSTEM,
                                            content=REPAIR_FOLLOWUP_NUDGE))
        #: 新一轮的计数器归零：`_can_continue_repair` 读的必须是**这一轮**的观测。
        self._repair_tools_ok = 0
        self._repair_queries_ok = 0
        temperature = 0.2
        if self.config is not None:
            temperature = float(self.config.llm.temperature_repair)
        payload = ChatPayload(messages=list(self.repair_messages),
                              tools=list(self._repair_tools),
                              tool_choice=ToolChoice.REQUIRED,
                              temperature=temperature,
                              purpose=Purpose.REPAIR,
                              request_id=new_request_id())
        self._start_llm_call("repair", payload,
                             note=f"继续修复 {self._current_shot_id}"
                                  f"（第 {self._repair_turns + 1} 轮）")
    def _scene_state_text(self) -> str:
        if self.scene_state_provider is None:
            return ""
        try:
            return str(self.scene_state_provider())
        except Exception as exc:  # noqa: BLE001 - 采集失败不该拖垮运行
            return f"（场景状态采集失败：{type(exc).__name__}: {exc}）"

    def _shot_by_id(self, shot_id: str):
        """按 id 取计划里的镜头；没有计划/找不到时返回 ``None``。"""
        if self.plan is None:
            return None
        return next((item for item in self.plan.shots
                     if item.shot_id == shot_id), None)

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

    # ---------------------------------------------------- v1.6 F2 断点续跑
    def _wall_clock_reason(self) -> Optional[str]:
        """预算账本里的墙钟是否已撞线（与 ``Budget.exhausted_reason`` 同一口径）。"""
        limits = self.budget.limits
        if limits.max_wall_seconds and self.budget.elapsed >= \
                limits.max_wall_seconds:
            return f"运行时间已达上限（{limits.max_wall_seconds:.0f}s）"
        return None

    def _mark_terminal(self, shot_id: str, status: str) -> None:
        """记下这一镜的终态并落 checkpoint（每镜审核/修复终态 = 断点）。"""
        shot_id = str(shot_id)
        self._shot_terminal[shot_id] = status
        for result in reversed(self.audit_results):
            if str(getattr(result, "target", "") or "") == shot_id:
                self._resume_last_audit[shot_id] = result.to_dict()
                break
        self._checkpoint_resume(stage="terminal", shot_id=shot_id,
                                status=status)

    def _checkpoint_resume(self, *, stage: str = "", shot_id: str = "",
                           status: str = "", reason: str = "") -> None:
        """把当前运行状态落成 ``resume_state.json``（版本化、原子写）。

        每个 B1 草案与每个终态镜之后都拍一张：即便进程被**硬杀**（不是走
        收尾路径），磁盘上也留着最近一张可续的断点。
        """
        path = self._resume_state_path
        if path is None:
            return
        state = ResumeState(
            run_id=self.audit.run_id,
            plan=(copy.deepcopy(self.plan.to_dict())
                  if self.plan is not None else None),
            brief=(copy.deepcopy(self.brief.to_dict())
                   if self.brief is not None else None),
            script=self.script or "",
            drafts={str(k): dict(v) for k, v in self._resume_drafts.items()},
            terminal_shots={str(k): str(v)
                            for k, v in self._shot_terminal.items()},
            last_audit={str(k): dict(v)
                        for k, v in self._resume_last_audit.items()},
            delivered_shots=sorted(self._resume_delivered),
            llm_calls=self._llm_calls,
            tool_calls=self._tool_calls,
            reason=reason,
        )
        try:
            save_resume_state(path, state)
        except (OSError, ResumeStateError) as exc:
            # 落盘失败**不得**静默吞掉：审计里留一条 error，运行照常继续
            # （断点写不出是交付风险，不是本次运行已坏）。
            log.error("resume 检查点写入失败 %s：%s", path, exc)
            self.audit.log(
                "resume_checkpoint_failed",
                f"断点写入失败：{type(exc).__name__}: {exc}",
                level="error", path=str(path), stage=stage, shot_id=shot_id)
            return
        if stage:
            self.audit.log("resume_checkpoint",
                           f"断点已落盘（{stage}）",
                           stage=stage, shot_id=shot_id, status=status,
                           path=str(path))

    def _wrap_up_wall_clock(self, reason: str) -> None:
        """v1.6 F2（D-09）：墙钟撞线收尾——保已完成镜，不整跑作废。

        与 ``_fail`` 的区别：场景保留、终态镜的 checkpoint 落盘、状态记为
        CANCELLED（不是成功）。已完成镜的**交付物**由调用方（headless CLI
        的收尾分支）按 ``snapshot()["terminal_shots"]`` 过滤导出；驱动器自己
        是纯层，只负责把状态钉在磁盘上。
        """
        if self._wall_clock_exhausted:
            return                          # 幂等：重复撞线不再写一遍
        self._wall_clock_exhausted = True
        self._flush_pending_repairs()
        self.audit.log(
            "wall_clock_exhausted", reason, level="warning",
            llm_calls=self._llm_calls,
            terminal_shots=sorted(self._shot_terminal),
            resume_state_path=(str(self._resume_state_path)
                               if self._resume_state_path else ""))
        self._emit("wall_clock_exhausted", reason)
        self._checkpoint_resume(stage="wall", reason=reason)
        self._transition(DriverState.CANCELLED)

    def _apply_resume_state(self) -> None:
        """resume 入口：加载断点，跳过终态镜，从第一个非终态镜继续。"""
        state = self._resume_state
        if state is None:
            return
        if state.plan is not None:
            try:
                self.plan = Plan.from_dict(copy.deepcopy(state.plan))
            except Exception as exc:  # noqa: BLE001 - 坏计划必须报错，不猜
                raise ResumeStateError(
                    f"resume_state.plan 无法解析：{exc}") from exc
            self._apply_scene_budget(len(self.plan.shots))
        if state.brief is not None:
            try:
                self.brief = SceneBrief.from_dict(copy.deepcopy(state.brief))
            except Exception as exc:  # noqa: BLE001 - 坏 brief 必须报错，不猜
                raise ResumeStateError(
                    f"resume_state.brief 无法解析：{exc}") from exc
        if state.script:
            self.script = state.script
        self._shot_terminal = {str(k): str(v)
                               for k, v in state.terminal_shots.items()}
        self._resume_terminal = set(self._shot_terminal)
        self._resume_last_audit = {str(k): dict(v)
                                   for k, v in state.last_audit.items()}
        self._resume_drafts = {str(k): dict(v)
                               for k, v in state.drafts.items()}
        self._resume_delivered = {str(item)
                                  for item in state.delivered_shots}
        #: 终态镜的旧审核结论种回账本：通过率统计与"哪几镜审过"保持完整，
        #: 而不是在 resume 之后假装它们没发生过。
        for shot_id, payload in self._resume_last_audit.items():
            self.audit_results.append(_audit_result_from_dict(shot_id, payload))
        plan_shots = [str(shot.shot_id)
                      for shot in (self.plan.shots if self.plan else [])]
        terminal = set(self._shot_terminal)
        pending_drafts = [shot_id for shot_id in plan_shots
                          if shot_id not in self._resume_drafts
                          and shot_id not in terminal]
        first_non_terminal = next(
            (shot_id for shot_id in plan_shots if shot_id not in terminal),
            "")
        self._finished_shots = [shot_id for shot_id in plan_shots
                                if shot_id in terminal]
        self._editing_queue = list(pending_drafts)
        self._editing_index = 0
        self.audit.log(
            "run_resumed",
            f"从断点继续：终态镜 {sorted(terminal)}，待起草 "
            f"{len(pending_drafts)} 镜，下一镜 {first_non_terminal or '（无）'}",
            version=state.version, terminal_shots=sorted(terminal),
            pending_drafts=list(pending_drafts),
            first_shot=first_non_terminal,
            delivered_shots=sorted(self._resume_delivered))
        self._emit("run_resumed", "从断点继续",
                   terminal_shots=sorted(terminal),
                   first_shot=first_non_terminal)
        if self.plan is None:
            return                      # 没有可续计划：从 IDLE 正常开始
        target = (DriverState.EDITING if pending_drafts
                  else DriverState.BUILDING)
        self._transition(target)

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
        #: 工具预算跟着场景走（见 `tool_call_budget` 的抬头）：固定 200 在 64 镜那跑
        #: 第 362 s 就耗光，之后 57 次修复回合全被拒、后四分之一一次也没修。
        tool_calls_effective = tool_call_budget(effective,
                                               self.limits.max_tool_calls)
        self.limits.max_tool_calls = tool_calls_effective
        #: **token 上限跟着场景走**（2026-10-07，用户"你看着来"授权；见
        #: `BudgetConfig.tokens_per_call_allowance` 的注释）：调用额度与 token 上限
        #: 必须互相自洽——写死 2 M 会让"没用完的调用额度"结构上不可达（v15 管线下
        #: 64 镜真跑两次都在 59% 调用额度处吃满 2 M）。这里取
        #: ``max(静态下限, min(静态帽, 本场调用额度 × 每次调用额度))``：
        #: 小场景**一个字节都不变**（仍是 2 M 下限），长场景才抬起来。
        tokens_effective = self._scene_token_budget(effective)
        self.budget.limits.max_tokens = tokens_effective
        self.audit.log(
            "budget_scoped", describe_budget_formula(formula, shots),
            shots=shots, formula_value=value, ceiling=ceiling,
            ceiling_effective=ceiling_effective, hard_cap=hard,
            effective=effective, tool_calls_effective=tool_calls_effective,
            max_tokens_effective=tokens_effective)

    def _scene_token_budget(self, effective_calls: int) -> int:
        """本场 token 上限（纯函数式；见 `_apply_scene_budget` 的注释）。

        三个量取法固定：**静态下限**（`BudgetLimits.max_tokens`）＋ **每次调用额度**
        ＋ **静态帽**。任何一格为 0 都按"不限"处理（与账本其余上限同一约定）。
        """
        floor = int(getattr(self, "_static_token_floor",
                            self.budget.limits.max_tokens))  # 静态下限（0 = 不限）
        budget_config = getattr(self.config, "budget", None)
        per_call = int(getattr(budget_config, "tokens_per_call_allowance", 0) or 0)
        ceiling = int(getattr(budget_config, "max_tokens_ceiling", 0) or 0)
        if per_call <= 0 or effective_calls <= 0:
            return floor                                    # 不设公式 ⇒ 保持原样
        value = per_call * int(effective_calls)
        if ceiling > 0:
            value = min(value, ceiling)
        return max(floor, value)

    def _start_plan_call(self) -> None:
        request_id = new_request_id()
        chunks = self._plan_chunk_list()
        chunk = chunks[self._plan_chunk_index] if len(chunks) > 1 else None
        try:
            payload: ChatPayload = build_plan_payload(
                self.script, self.config, request_id=request_id,
                parsed=self.parsed_script, retriever=self.knowledge,
                brief=self.brief, chunk=chunk, plan_chunks_total=len(chunks),
                #: 上一次被拒的原因回灌给这一次——否则模型把同一个错误再犯一遍。
                retry_note=self._plan_problem)
        except ValueError as exc:
            # v1.4 BW-3/E_SCRIPT_002：声明镜数超过 max_shots 时明确失败，
            # 而不是退回"其余 N 个镜号略"的静默截断。
            self.audit.log("plan_payload_failed", str(exc), level="error")
            self._fail(str(exc))
            return
        #: v1.6 F1：上一次 plan 请求超时 ⇒ 这次用瘦身包（只去 RAG 三栏）。
        #: 收到回复后 `_step_calling_llm` 会把它复位，分块/重试都不带脏状态。
        if self._plan_next_slim:
            payload.messages, _removed = slim_messages(payload.messages)
        #: 阶梯历史按 plan 请求切 scope（TDD §4.5 "per plan request"）。
        self._reset_retry_ladder("plan", slim=bool(self._plan_next_slim))
        self._start_llm_call("plan", payload,
                             note=(f"请求分镜计划（第 {self._plan_attempts} 次尝试）"
                                   + (f"；第 {chunk['index'] + 1}/{len(chunks)} 段"
                                      f"（镜号 {chunk['shot_numbers'][0]}–"
                                      f"{chunk['shot_numbers'][-1]}）"
                                      if chunk else "")))

    def _plan_chunk_list(self) -> List[Dict[str, Any]]:
        """这一跑的计划分段（只算一次；没有分镜表声明时返回空表 = 不分块）。

        分块规则与 `planner.plan_chunks` 同源（单一真源），驱动只负责"轮到第几段"。
        """
        if self._plan_chunks is None:
            self._plan_chunks = plan_chunks(self.parsed_script)
        return self._plan_chunks

    def _plan_needs_more_chunks(self) -> bool:
        """还有一段没收到？（不分块时恒 False ⇒ 与分块前的行为逐字一致。）"""
        chunks = self._plan_chunk_list()
        return len(chunks) > 1 and self._plan_chunk_index + 1 < len(chunks)

    def _accept_plan_chunk(self, chunk_plan) -> None:
        """收下一段计划（分块）或直接落成计划（不分块）。

        分块时的**完整性判据**是"这一段应有的镜号数 == 收到的镜头数"：段与段的边界
        由分镜表决定，模型只是被要求"只提交这一段"。数量对不上就当场退回重问这一段
        （`plan_invalid` → 驱动重试**同一段**），不把半段并进累计表——否则最终计划
        的镜数会与分镜表对不上，那是 `R015` 阶段才炸、排查成本高得多的形态。
        顺序不是靠模型保证的：段按声明顺序串起来（`_plan_shots` 追加），
        镜号由 `_pin_declared_dialogue` 按位置钉死。
        """
        chunks = self._plan_chunk_list()
        roster = self._cast_roster(include_from=chunk_plan)
        if roster:
            bad = unknown_cast_ids(chunk_plan, roster)
            if bad:
                raise ValueError(
                    user_message(ErrorCode.CAST_001,
                                 ids=", ".join(bad),
                                 roster=", ".join(roster)))
        if len(chunks) <= 1:
            self.plan = chunk_plan
            self._plan_shots = list(chunk_plan.shots)
            self._apply_scene_budget(len(self.plan.shots))
            return
        chunk = chunks[self._plan_chunk_index]
        expected = len(chunk.get("shot_numbers") or [])
        got = len(chunk_plan.shots)
        if got != expected:
            raise ValueError(
                f"这一段（第 {chunk['index'] + 1}/{len(chunks)} 段，"
                f"镜号 {chunk['shot_numbers'][0]}–{chunk['shot_numbers'][-1]}）"
                f"应有 {expected} 个镜头，收到 {got} 个")
        if not self._plan_shots:
            self._plan_head = {"scene_heading": chunk_plan.scene_heading,
                               "continuity_notes": list(
                                   chunk_plan.continuity_notes or []),
                               #: v1.5 §3.2（P2-T4）：场级环境是**全场共用**的
                               #: 声明，必须跟着分块计划一起带下去；不带就等于
                               #: 在分块路径上把它悄悄丢掉（长剧本一律走分块）。
                               "environment": dict(
                                   getattr(chunk_plan, "environment", {}) or {})}
        else:
            merged = list(self._plan_head.get("continuity_notes") or [])
            for note in (chunk_plan.continuity_notes or []):
                if note not in merged:
                    merged.append(note)
            self._plan_head["continuity_notes"] = merged
            #: 环境只在缺省时被后来者补齐——阶段 A 每段都会重新声明一次，
            #: 第一个给出非空 environment 的那段说了算（同一场戏只有一份）。
            if not self._plan_head.get("environment") and getattr(
                    chunk_plan, "environment", None):
                self._plan_head["environment"] = dict(chunk_plan.environment)
        self._plan_shots.extend(chunk_plan.shots)
        #: 这一段收下了，上一次的拒绝原因就过期了——别带进下一段的提示里。
        self._plan_problem = ""
        if not self._plan_needs_more_chunks():
            payload = dict(self._plan_head)
            payload["shots"] = [shot.to_dict() for shot in self._plan_shots]
            self.plan = Plan.from_dict(payload)
            self._apply_scene_budget(len(self.plan.shots))

    def _start_llm_call(self, purpose: str, payload: ChatPayload,
                        note: str = "") -> None:
        """发起一次 LLM 调用。网络在后台线程，主线程只负责发起与轮询。"""
        if not self.budget.allow_llm_call(purpose):
            reason = self.budget.exhausted_reason() or "预算耗尽"
            if self._wall_clock_reason():
                # v1.6 F2（D-09）：墙钟撞线走"保已完成镜"的收尾，不走
                # "补审剩余镜头"的预算降级路径。
                self._wrap_up_wall_clock(reason)
            else:
                self._degrade_to_finish(reason)
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
            if result.ok and call.function.name in MUTATING_TOOLS:
                # v1.4 §3.3：修复回合里**真的执行成功**的**改动类**工具 = 这一镜
                # 被实际修过。不能用"本轮没有 problem"当判据（修复回合不重提计划时
                # `_dispatch_tool_calls` 会因为"没有收到 emit_plan"而返回 problem），
                # 也不能用"任何成功的工具调用"当判据——**只读查询不是动手**：
                # 实测（2026-10-03 的 64 镜真跑）模型只调 `get_scene_state` +
                # `check_composition`，而 `repair_applied` 照写"已实施定向修复"。
                self._repair_tools_ok += 1
            elif result.ok and call.function.name in READ_ONLY_TOOLS:
                #: "这一轮**拿到了观测**"（只读查询成功）。它与"动手"是两件事：
                #: 前者是模型判断的依据，后者才是修复本身。修复回合的**续轮**
                #: 判据要用它——只有"看了却没动"才值得再给一轮；整轮全失败
                #: （例：没有场景上下文时 `setup_camera` 必然失败）再给几轮也
                #: 只是把同一次失败重放，白烧预算。
                self._repair_queries_ok += 1
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
                        #: v1.5：分块时这一段先**单独**校验（镜号/时长/字段），
                        #: 收进 `_plan_shots`；只有最后一段到齐才落成 `self.plan`。
                        self._accept_plan_chunk(Plan.from_dict(args))
                        plan_seen = True
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
                        characters, anchors = self._draft_context(shot_id)
                        draft = extract_draft(
                            ChatReply(tool_calls=[call]), shot_id,
                            characters=characters, anchors=anchors)
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
            #: **只有阶段 A 才要求 emit_plan**（§7.1：计划的唯一入口）。修复/精修/
            #: 反应回合在上面**明确拒绝** `emit_plan`（"emit_plan 只在阶段 A 被接受"），
            #: 所以它们在这里必然 `plan_seen=False`——原来那条不分阶段的收尾判据于是
            #: 让**每一轮修复**都返回"没有收到 emit_plan 调用"。实测（2026-10-04，
            #: `docs/evidence/20261004_chunked_long16/`）：104 条 `repair_invalid` 里
            #: **89 条**是这条假问题，真错与假错混在同一个事件名里，"这一轮到底错没错"
            #: 就判不出来了。
            if self._call_purpose == "plan":
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
        """§12.6：预算触顶按降级收尾并如实标注，已建成的成果不丢。

        **审核不受预算约束**（2026-10-04 实测，long18）：审核是 bpy 侧的纯规则计算，
        既不调用模型也不花钱；而原来这里直接跳 FINISHING，把 `_shot_queue` 里剩下的
        镜头**整段丢掉**——long18 因此只审了 **55/64**，最后 9 镜在交付证据里连一条
        `shot_audit` 都没有。"没审过"与"审过没过"在账上长得一样，这是最坏的一种：
        读者会把缺失当成通过。所以降级收尾前先把剩下的镜头**只审不修**地补完，
        并给这些事件打上 `degraded: true` 与一条 `audit_after_budget` 汇总。
        """
        self.degraded_reason = reason
        self.audit.log("budget_exhausted", reason, level="warning")
        self._emit("budget_exhausted", reason)
        #: 只补**还没审过**的：队列头部那一镜通常正是"刚审完、卡在修复上"的那一镜，
        #: 再审一次只是把同一条结论重写一遍，还会把"补审了几镜"报大。
        already = {str(getattr(item, "target", "") or "")
                   for item in self.audit_results}
        pending = [str(shot_id) for shot_id in self._shot_queue
                   if str(shot_id) not in already]
        audited = 0
        for shot_id in pending:
            if self._audit_shot(shot_id, degraded=True) is not None:
                audited += 1
        if pending:
            self.audit.log(
                "audit_after_budget",
                f"预算触顶后补审 {audited}/{len(pending)} 镜（只审不修）",
                level="warning", shots=len(pending), audited=audited,
                reason=reason)
            self._emit("audit_after_budget",
                       f"补审 {audited}/{len(pending)} 镜", shots=len(pending))
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
