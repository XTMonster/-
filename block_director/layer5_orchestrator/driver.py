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
import math
import os
import queue
import re
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from ..contracts.enums import Purpose, ToolChoice
from ..contracts.audit import (SCENE_BUILT_RESERVED_KEYS, AuditError,
                               AuditResult, canonical_fingerprint,
                               identity_finding, scene_built_reason)
from ..contracts.blockout import manifest_fingerprint
from ..contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)
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
from ..contracts.plan import (
    FPS,
    Plan,
    ShotPlan,
    coarse_plan_identity_drift,
    unknown_cast_ids,
)
from ..contracts.brief import SOURCE_DETERMINISTIC, SceneBrief
from ..contracts.enums import SHOT_TYPES, ErrorCode, ShotType
from ..contracts.errors import user_message
from ..contracts.evidence import (
    EvidenceError,
    EvidenceStore,
    inspect_evidence_store,
)
from ..contracts.tools import MUTATING_TOOLS, READ_ONLY_TOOLS
from ..contracts.world_state import world_state_target_path
from ..contracts.config import DEFAULT_CONTEXT_WINDOW_TOKENS
from ..contracts.quality import (
    COMPOSITION_PASS_SCORE as PASS_SCORE,
    COMPOSITION_PASS_TEXT,
    composition_decision,
)
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
from .adversarial_review import review_shot
from .shot_versioning import ShotVersion, ShotVersionHistory
from .repair import (REPAIR_FOLLOWUP_NUDGE, build_repair_payload,
                     parse_guard_accepts)
from .budget import Budget, BudgetLimits
from .budget_formula import describe as describe_budget_formula
from .budget_formula import evaluate as evaluate_llm_call_budget
from .context_budget import (
    budget_report,
    compress_messages,
    count_tokens,
    slim_messages,
    trim_messages,
)
from .editor import (build_editor_payload, extract_draft, identity_conflicts,
                     merge_draft, normalize_draft_watchdog, rank_drafts)
from .editor import EDITOR_TOOL_NAME, EMIT_SHOT_DRAFT_PARAMETERS
from .react import build_react_payload, render_shot_memory, should_react, shot_memory
from .script_polish import build_polish_payload, extract_polish
from ..contracts.script_polish import PolishResult
from .rhythm_reading import rhythm_readings
from .shot_schema import shot_tool_overrides
from .retry_ladder import (
    DEGRADE,
    RETRY_SAME,
    RETRY_SLIM,
    STAGE_OF,
    CallOutcome,
    RetryPolicy,
    is_server_error,
    is_timeout,
    next_step,
)
from .loop_detector import DEFAULT_QUERY_TOOLS, LoopDetector
from .wall_share import per_shot_wall_share
from .decision_tree import Verdict, build_tree
from ..contracts.backtrack import coarse_plan_backtrack
from ..delivery.coarse_gate import (
    merge_integrity_decision,
    plan_integrity_findings,
)
from .tool_projection import (
    TOOL_TREE_MAP,
    ToolProjection,
    project_tool_call,
)
from .human_gate import GateDecision, GateRequest, HumanGate
from .invalid_category import classify_invalid
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


def label_overlap_event_fields(build_summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从构建摘要里取 ``label_overlap_report`` 审计事件的字段（v1.6 A7 / G2）。

    A7 只把重叠帧写成了 ``summary.warnings`` 字符串，审计日志里从没出现过
    ``label_overlap_report`` 事件（契约登记在
    ``contracts/audit.py::V16_EVENT_FIELDS``）。这里是该事件的唯一生产者：
    ``fullframe_verify=true`` 时每次构建后由 :meth:`PrevisDriver._step_building`
    写一条；字段与 ``label_baking._empty_overlap_report()`` 同形。烘焙确实
    发生过（``label_report`` 非空）才产出，没有任何标签时返回 ``None``（静默）。
    """
    label_report = dict((build_summary or {}).get("label_report") or {})
    if not label_report:
        return None
    overlap = dict(label_report.get("label_overlap_report") or {})
    return {
        "max_overlap_ratio": float(overlap.get("max_overlap_ratio", 0.0)),
        "overlap_frames": [int(frame)
                           for frame in overlap.get("overlap_frames") or []],
        "frames_checked": int(overlap.get("frames_checked", 0)),
        "limit": float(overlap.get("limit", 0.05)),
    }


def upstream_error_fields(exc: BaseException) -> Dict[str, Any]:
    """从 ``TransportError.body``（sidecar 的 502 JSON）里取上游状态与正文摘录。

    G8-H：sidecar 在 502 里带 ``upstream_http_status`` / ``upstream_body_excerpt``
    （见 ``tools/sidecar_server.py``），这里把它们提出来供 ``llm_error`` 审计
    事件落盘。只读异常的既有字段：解析失败 / 字段缺失时返回空 dict——绝不影响
    既有错误文案与重试阶梯。

    ``TransportError.body`` 是插件侧截断过的（前 2000 字符）：sidecar 保证
    502 正文落在窗口内，但**旧版 sidecar / 其他服务**可能发更长的正文，把
    摘录截断在字符串中间、整段 JSON 解析失败。这时退回正则直取这两个键
    （状态键总在 2000 字符窗口内；摘录取到哪算哪），宁要部分现场也不要
    把上游 5xx 又变回"sidecar 返回 502"一句空话。
    """
    body = str(getattr(exc, "body", "") or "")
    data: Optional[Dict[str, Any]] = None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        data = None
    if not isinstance(data, dict):
        error_match = re.search(r'"error"\s*:\s*"((?:[^"\\]|\\.)*)"', body)
        status_match = re.search(
            r'"upstream_http_status"\s*:\s*(-?\d+|null)', body)
        excerpt_match = re.search(
            r'"upstream_body_excerpt"\s*:\s*"((?:[^"\\]|\\.)*)"?', body)
        if (error_match is None and status_match is None
                and excerpt_match is None):
            return {}
        data = {}
        if error_match is not None:
            data["error"] = error_match.group(1)
        if status_match is not None:
            raw_status = status_match.group(1)
            data["upstream_http_status"] = (
                None if raw_status == "null" else int(raw_status))
        if excerpt_match is not None:
            data["upstream_body_excerpt"] = excerpt_match.group(1)
    out: Dict[str, Any] = {}
    inner_error = data.get("error")
    if isinstance(inner_error, str) and inner_error:
        out["sidecar_error"] = inner_error[:2000]
    status = data.get("upstream_http_status")
    if status is not None:
        out["upstream_http_status"] = status
    excerpt = data.get("upstream_body_excerpt")
    if excerpt is not None:
        out["upstream_body_excerpt"] = str(excerpt)[:2000]
    return out


def unseen_axis_crossing(plan: Plan, brief, shot_id: str) -> Optional[str]:
    """合并草案后是否存在"无人看见的配对连线大翻转"（R001 的保守前置闸）。

    v1.6 G2：逐轮真跑里 E_AXIS_001 的主因是走位在**单人镜**里绕到两人连线的
    另一侧——审核只能判错、模型修不动。这里用既有的纯函数
    :func:`cinema.axis.crossing_events`（计划期近似：连线转角 ≥90° 才算翻个儿，
    ``visible`` 取该镜是否两人同框）在**合并前**拦截最恶劣的那一类；30–90° 的
    漂移仍由审核/修复回路管，不在这里扩大误杀面。判据与阈值一个都没动。

    位置来源 ``SceneSpec.from_plan``（纯层，不 import bpy）；brief 缺失或
    构不出两人配对时返回 ``None``（不拦）。
    """
    from ..cinema.axis import (
        AXIS_DRIFT_DEG,
        Axis,
        crossing_events,
        drift_is_bridged,
        pair_spans,
    )
    from ..contracts.cast import SceneSpec

    try:
        spec = SceneSpec.from_plan(plan, brief=brief)
    except Exception:                       # noqa: BLE001 - 闸失败不阻断草案
        return None
    pair: Optional[List[str]] = None
    for shot in (plan.shots or []):
        characters = [str(cid) for cid in (shot.characters or [])]
        if len(characters) >= 2:
            pair = characters[:2]
            break
    if not pair:
        return None
    initial: Dict[str, Tuple[float, float, float]] = {}
    for member in (spec.cast or []):
        location = tuple(member.initial_location)
        initial[str(member.id)] = location
        name = str(getattr(member, "name", "") or "")
        if name:
            initial[name] = location
    left, right = pair
    if left not in initial or right not in initial:
        return None
    axis = Axis(start=tuple(initial[left][:2]),
                end=tuple(initial[right][:2]),
                established_side=1, left_label=left, right_label=right)
    for event_shot_id, event in crossing_events(
            axis, plan, initial).items():
        if event.flip and not event.visible:
            return (f"草案让角色在 {event_shot_id} 绕到两人连线的另一侧"
                    f"（连线转角 ≥90°），而那一镜只有单人，观众看不见这次"
                    f"换位（R001）。请把换位放进双人同框的镜头，或不要跨线。")
    #: 30–90° 带（与审核 `_axis_rebuild` 同口径：相对**首镜线**的累计漂移，
    #: 可见旋转累计偿债——`drift_is_bridged`）。审核还在用首镜线做锚，闸用
    #: 同一参照系，才不会"闸放行、审核判错"。
    spans = pair_spans(axis, plan, initial)
    visible_since = 0.0
    for shot in (plan.shots or []):
        span = spans.get(str(shot.shot_id))
        if span is None:
            continue
        a_start, b_start, a_end, b_end = span
        both = len([cid for cid in (shot.characters or [])
                    if str(cid) in (left, right)]) >= 2
        start_dir = None
        rotation = 0.0

        def _unit_pair(point_a, point_b):
            dx = float(point_b[0]) - float(point_a[0])
            dy = float(point_b[1]) - float(point_a[1])
            norm = math.hypot(dx, dy)
            return (dx / norm, dy / norm) if norm > 1e-9 else None

        def _angle_to_anchor(point_a, point_b) -> Optional[float]:
            dx = float(point_b[0]) - float(point_a[0])
            dy = float(point_b[1]) - float(point_a[1])
            norm = math.hypot(dx, dy)
            if norm < 1e-9:
                return None
            direction = (dx / norm, dy / norm)
            cosine = max(-1.0, min(1.0,
                                   axis.direction[0] * direction[0]
                                   + axis.direction[1] * direction[1]))
            return math.degrees(math.acos(cosine))

        start_angle = _angle_to_anchor(a_start, b_start)
        if start_angle is not None:
            start_dir = _unit_pair(a_start, b_start)
            if start_angle >= float(AXIS_DRIFT_DEG) and not drift_is_bridged(
                    start_angle, visible_since, False):
                return (f"草案让 {shot.shot_id} 的两人连线相对首镜线漂移 "
                        f"{start_angle:.0f}°（≥{AXIS_DRIFT_DEG}°），且没有任何"
                        f"双人同框/中性镜头交代这次重建（R001）。"
                        f"请把换位拍出来，或不要跨线。")
        # 本镜两人同框时的可见旋转计入"偿债额"（drift_is_bridged 的口径）。
        if both and start_dir is not None:
            end_dir = _unit_pair(a_end, b_end)
            if end_dir is not None:
                rot_cos = max(-1.0, min(1.0,
                                        start_dir[0] * end_dir[0]
                                        + start_dir[1] * end_dir[1]))
                rotation = math.degrees(math.acos(rot_cos))
        end_angle = _angle_to_anchor(a_end, b_end)
        if end_angle is not None and end_angle >= float(AXIS_DRIFT_DEG) \
                and not drift_is_bridged(end_angle,
                                         visible_since + rotation, False):
            return (f"草案让 {shot.shot_id} 的两人连线相对首镜线漂移 "
                    f"{end_angle:.0f}°（≥{AXIS_DRIFT_DEG}°），且没有任何"
                    f"双人同框/中性镜头交代这次重建（R001）。"
                    f"请把换位拍出来，或不要跨线。")
        visible_since += rotation
    return None


# --------------------------------------------------------------------------- #
# v1.6 F2（D-09）：断点续跑的状态模型（纯层，不得 import bpy）
# --------------------------------------------------------------------------- #

RESUME_STATE_VERSION = 1
RESUME_STATE_FILENAME = "resume_state.json"

#: 终态镜的闭集。``finished`` = 模型 `finish_shot` 声明完成但审核未过；
#: ``unverified`` = 审核器没给出结论（异常路径）就前进的镜头；
#: ``unfinished`` = 单镜均摊墙钟耗尽、流程结束但质量未通过。它们都表示
#: "这一镜的 LLM 流程已结束"，resume 时全部零调用跳过。
RESUME_TERMINAL_STATUSES = ("passed", "degraded", "finished", "unverified",
                            "unfinished", "failed")


class ResumeStateError(RuntimeError):
    """resume_state 不可用。消息里给出可执行的下一步，绝不静默猜。"""


@dataclass
class ResumeState:
    """断点续跑的版本化运行状态（``resume_state.json`` 的单一真源）。

    格式（v1）：顶层 ``schema_version`` 固定为 :data:`RESUME_STATE_VERSION`；
    ``plan`` / ``brief`` 是中断那一刻的完整快照（草案已合并进计划）；
    ``drafts`` 记每镜成功合并的 B1 草案（用于算"还有哪些镜没起草"）；
    ``terminal_shots`` 记每镜终态
    （passed/degraded/finished/unverified/unfinished/failed），
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
    #: D1：逐镜版本历史（`{shot_id: history.to_dict()}`）。断点续跑后
    #: `restore_shot_version` 仍能按版本号取回任意一版计划。
    version_histories: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: R2-D3：逐镜回溯最高分版本快照（`{shot_id: {score, version,
    #: world_state}}`）与连续无新高轮数（`{shot_id: int}`）。断点续跑后
    #: `_failures_payload()` 用持久化值重建，不再因新进程空内存清零历史最高分
    #: （"高分保留"跨进程成立，红线 U10）。旧断点无此字段时缺省空表（兼容）。
    react_best: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    react_no_gain: Dict[str, int] = field(default_factory=dict)
    #: R2-F11：每镜 ReAct 总回合计数随断点落盘，resume 后不重置回合上限。
    react_round_counts: Dict[str, int] = field(default_factory=dict)
    #: Unified per-shot evidence and best pointers.  Kept as a wire-format
    #: mapping here so the pure resume contract does not own mutable evidence.
    evidence_store: Optional[Dict[str, Any]] = None
    #: Exact coarse gate decision associated with that evidence.  Resume must
    #: not silently replace a passing frozen baseline with a fresh low score.
    coarse_decision: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": int(self.version),
            "run_id": str(self.run_id),
            #: ``saved_at`` 是"保存那一刻"的时间戳，由
            #: :func:`save_resume_state` 打一次、原样透传——不在每次
            #: ``to_dict()`` 时现打。现打会让同一份状态的两次序列化跨秒
            #: 时产生不同的字节（实测 `test_resume_state_round_trip` 的
            #: 秒界竞态），round-trip 断言随之偶发红。
            "saved_at": str(self.saved_at),
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
            "version_histories": {
                str(k): dict(v) for k, v in self.version_histories.items()},
            "react_best": {
                str(k): dict(v) for k, v in self.react_best.items()},
            "react_no_gain": {
                str(k): int(v) for k, v in self.react_no_gain.items()},
            "react_round_counts": {
                str(k): int(v) for k, v in self.react_round_counts.items()},
            "evidence_store": copy.deepcopy(self.evidence_store),
            "coarse_decision": copy.deepcopy(self.coarse_decision),
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
        if "version_histories" in payload:
            raw = payload["version_histories"]
            if not isinstance(raw, dict):
                raise ResumeStateError(
                    "resume_state.version_histories 必须是对象")
            histories = {}
            for key, value in raw.items():
                if not isinstance(value, dict):
                    raise ResumeStateError(
                        f"resume_state.version_histories.{key} 必须是对象")
                histories[str(key)] = dict(value)
            state.version_histories = histories
        if "react_best" in payload:
            raw = payload["react_best"]
            if not isinstance(raw, dict):
                raise ResumeStateError(
                    "resume_state.react_best 必须是对象")
            best = {}
            for key, value in raw.items():
                if not isinstance(value, dict):
                    raise ResumeStateError(
                        f"resume_state.react_best.{key} 必须是对象")
                best[str(key)] = dict(value)
            state.react_best = best
        if "react_no_gain" in payload:
            raw = payload["react_no_gain"]
            if not isinstance(raw, dict):
                raise ResumeStateError(
                    "resume_state.react_no_gain 必须是对象")
            gain = {}
            for key, value in raw.items():
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ResumeStateError(
                        f"resume_state.react_no_gain.{key} 必须是整数")
                gain[str(key)] = int(value)
            state.react_no_gain = gain
        if "react_round_counts" in payload:
            raw = payload["react_round_counts"]
            if not isinstance(raw, dict):
                raise ResumeStateError(
                    "resume_state.react_round_counts 必须是对象")
            rounds = {}
            for key, value in raw.items():
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ResumeStateError(
                        f"resume_state.react_round_counts.{key} 必须是整数")
                rounds[str(key)] = int(value)
            state.react_round_counts = rounds
        if payload.get("evidence_store") is not None:
            raw = payload["evidence_store"]
            if not isinstance(raw, dict):
                raise ResumeStateError(
                    "resume_state.evidence_store 必须是对象或 null")
            try:
                store = EvidenceStore.from_dict(raw)
            except (EvidenceError, KeyError, TypeError, ValueError) as exc:
                raise ResumeStateError(
                    f"resume_state.evidence_store 不可用：{exc}") from exc
            errors = store.validate()
            if errors:
                raise ResumeStateError(
                    "resume_state.evidence_store 不一致："
                    + "；".join(errors))
            state.evidence_store = store.to_dict()
        if payload.get("coarse_decision") is not None:
            raw = payload["coarse_decision"]
            if not isinstance(raw, dict):
                raise ResumeStateError(
                    "resume_state.coarse_decision 必须是对象或 null")
            state.coarse_decision = copy.deepcopy(raw)
        return state


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")


def save_resume_state(path, state: "ResumeState") -> Path:
    """原子写 ``resume_state.json``（临时文件 + ``os.replace``）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    #: 保存即打戳：把 ``saved_at`` 回写到对象本体，保证 save → load →
    #: ``to_dict`` 的 round-trip 逐字节一致。只填一次，跨秒边界也不漂移
    #: （此前 `to_dict()` 对空 ``saved_at`` 现取时间，保存 :48 与断言 :49
    #: 会撞出假红——test_resume_state_round_trip 实测）。
    if not state.saved_at:
        state.saved_at = _now_iso()
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
        #: v1.7 空间尺（Ticket 04/06）：断点续跑也要保住逐镜几何测量，
        #: 否则 resume 后的交付包会缺这一镜的 ruler_measurements 证据。
        ruler_measurements=(
            [dict(item) for item in payload.get("ruler_measurements") or []
             if isinstance(item, dict)]
            or None),
    )


def ruler_delivery_args(driver) -> Dict[str, Any]:
    """从驱动器状态折出 ``export_project`` 的空间尺参数（Ticket 06，纯层）。

    * ``ruler_evidence`` ← ``driver._ruler_plan_evidence``（计划级处方/测量）；
    * ``ruler_shot_measurements`` ← ``driver.build_summary["results"][].ruler_measurements``
      （逐镜几何测量，``_record_ruler_measurements`` 写入）。

    没有空间尺数据时两者均为 ``None``（零形状差）。
    """
    evidence = getattr(driver, "_ruler_plan_evidence", None) or None
    build_summary = getattr(driver, "build_summary", None) or {}
    shot_measurements: Dict[str, Any] = {}
    for item in build_summary.get("results") or []:
        if not isinstance(item, dict) or not item.get("shot_id"):
            continue
        values = item.get("ruler_measurements")
        if isinstance(values, list) and values:
            shot_measurements[str(item["shot_id"])] = [
                dict(m) for m in values if isinstance(m, dict)]
    return {"ruler_evidence": evidence,
            "ruler_shot_measurements": shot_measurements or None}


def spatial_delivery_args(driver) -> Dict[str, Any]:
    """从驱动器状态折出 ``export_project`` 的空间快照参数（Ticket 08，纯层）。

    三份快照（设计/观测/diff）直接透传；驱动未生成（离线无 bpy、旧路径）
    时全部为 ``None``——交付层零形状差，一个额外键都不写。
    """
    return {
        "spatial_design": getattr(driver, "_spatial_design", None) or None,
        "spatial_observation": getattr(driver, "_spatial_observation", None)
        or None,
        "spatial_diff": getattr(driver, "_spatial_diff", None) or None,
    }


@dataclass
class DriverLimits:
    """运行护栏（§12.6）。"""

    max_steps: int = 4000
    #: v1.4 §2.4：**硬顶**（CLI ``--max-llm-calls`` 的入口）。``0`` = 不限，
    #: 此时初值由 ``budget.max_llm_calls_ceiling`` 注入（见 ``_limits_from``）。
    #: 真正的门禁 = ``max(ceiling, formula)``，再与这里的硬顶取小。
    max_llm_calls: int = 0
    llm_timeout_s: float = 120.0
    plan_attempts: int = 3
    brief_attempts: int = 2      # §3.2：两次不理解就降级为确定性抽取
    max_tool_calls: int = 200
    #: 兼容/诊断字段（§7.1 B4 历史语义）。按 2026-10-12 用户裁决，修复次数
    #: **不再作为镜头终止条件**：画面未达标就继续修，直到预算/墙钟/人工叫停。
    #: 本字段只保留给旧配置与统计读数，driver 不再因 `_repair_attempts >=
    #: max_repairs_per_shot` 而自动推进或降级（见 `_audit_and_route`）。
    max_repairs_per_shot: int = 2
    #: 一次定向修复允许几轮 LLM（``1`` = 老行为）。见
    #: `orchestration.repair_max_turns`——真跑里 104 个修复回合有 72 个
    #: 死在"查资料 + 看场景就用光唯一一轮"。默认与配置键一致（10，
    #: 2026-10-11 由 3 提到 10，用户裁决）；``from_config`` 会用配置键覆盖。
    repair_turns: int = 10
    #: R2：粗排门失败后的重规划回溯次数（计划级 U10 三态；0 = 关，
    #: 保持旧行为）。``from_config`` 从 ``orchestration.coarse_replan_attempts``
    #: 读取，调用方显式覆盖优先。
    coarse_replan_attempts: int = 3

    @classmethod
    def from_config(cls, config=None, *, llm_timeout_s=None,
                    **overrides) -> "DriverLimits":
        """Resolve an omitted timeout / repair-turn cap from config; keep overrides.

        ``None`` means the caller did not choose a timeout. The legacy
        no-config constructor still uses 120s; a supplied runtime configuration
        owns the default for GUI and command-line runs.
        """
        if llm_timeout_s is None and config is not None:
            llm_timeout_s = getattr(config.llm, "timeout_s", cls.llm_timeout_s)
        if llm_timeout_s is not None:
            overrides["llm_timeout_s"] = float(llm_timeout_s)
        #: 2026-10-11 修复接线：`orchestration.repair_max_turns` 此前没有任何
        #: 生产消费者（GUI/headless 都拿 dataclass 默认值，用户改配置不生效）。
        #: 调用方显式传入的 ``repair_turns`` 优先于配置键。
        if config is not None and "repair_turns" not in overrides:
            repair_turns = getattr(getattr(config, "orchestration", None),
                                   "repair_max_turns", None)
            if repair_turns is not None:
                overrides["repair_turns"] = int(repair_turns)
        if config is not None and "coarse_replan_attempts" not in overrides:
            replans = getattr(getattr(config, "orchestration", None),
                              "coarse_replan_attempts", None)
            if replans is not None:
                overrides["coarse_replan_attempts"] = int(replans)
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
        #: R2-F1：headless 的粗排 gate 回调（纯层，默认 None = 零行为差）。
        #: 签名 ``coarse_gate(plan, brief=None) -> {"ready": bool, "reason": str, ...}``，
        #: ``brief`` 是 Stage S 的 SceneBrief（粗排设计快照需要 environment[]/
        #: props[]/space[]，plan 的 emit_plan payload 往往不带）；
        #: 在 plan 落定、进入逐镜细排构建前调用；blocked 时驱动器转为失败
        #: 阻止进细排（粗排诊断产物已由调用方落盘）。
        coarse_gate: Optional[Callable[..., Dict[str, Any]]] = None,
        #: 计划级回溯耗尽时，用**最高分的计划及其粗排证据**恢复真实 Blender
        #: 场景。回调只接收已经由 driver 选出的 best，不得重新询问 Agent 或
        #: 修改计划。缺省 None = 纯测试/无 bpy 场景只能恢复 plan 账，快照会
        #: 明确记录 ``physical_restore=false``。
        coarse_restore: Optional[Callable[..., Mapping[str, Any] | None]] = None,
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
        self.coarse_gate = coarse_gate
        self.coarse_restore = (
            coarse_restore
            if coarse_restore is not None
            else getattr(coarse_gate, "restore_best", None))
        #: R2-F1：最近一次粗排 gate 判定（快照可观测，无 gate 时 None）。
        self._coarse_decision: Optional[Dict[str, Any]] = (
            copy.deepcopy(resume_state.coarse_decision)
            if resume_state is not None
            and resume_state.coarse_decision is not None
            else None
        )
        self.evidence_store: Optional[EvidenceStore] = None
        self._evidence_status: Dict[str, Any] = {
            "status": "missing",
            "reason": "coarse evidence has not been attached",
        }
        if resume_state is not None and resume_state.evidence_store is not None:
            try:
                self.evidence_store = EvidenceStore.from_dict(
                    resume_state.evidence_store)
            except (EvidenceError, KeyError, TypeError, ValueError) as exc:
                raise ResumeStateError(
                    f"断点中的证据库不可用：{exc}") from exc
            self._evidence_status = self.evidence_store.summary()
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
        #: 缺陷 B / U10（T6）：每镜的最高分快照与分数轨迹。
        #: ``_react_best``：shot_id → {score, version, world_state}；
        #: ``_react_scores``：shot_id → [{version, score, disposition, summary}]；
        #: ``_react_no_gain``：shot_id → **连续无新高轮数（≥3 单镜 fail）**。
        #: 这是终态判据的单一真源，只由 ``_record_react_score`` 的审核裁定
        #: （tie/revert +1，adopt/new_high 归零）写入；``_record_react_tool_progress``
        #: 的只读连续检测写进独立的 ``_react_readonly_rounds``，绝不改它。
        #: （R2 ticket 10 修复：原实现两处共用并"混合轮清零"，真跑中模型每轮
        #: 先调 setup_camera 再打平，累计被反复清零，终态判据永远到不了 3。）
        self._react_best: Dict[str, Dict[str, Any]] = {}
        self._react_scores: Dict[str, List[Dict[str, Any]]] = {}
        self._react_no_gain: Dict[str, int] = {}
        #: R2-F2：只读步连续计数（诊断用，`repair_no_progress` 事件照记）。
        #: 与 ``_react_no_gain`` 解耦——它只反映"连续多少个工具步没动手"，
        #: 不参与任何终态/预算判据；修改步把它清零（空转信号被打断）。
        self._react_readonly_rounds: Dict[str, int] = {}
        #: R2-F11：每镜 ReAct 总回合计数（`_start_react` +1；换镜清零）。
        #: 与 ``_react_no_gain``（连续无新高）互补：微涨 new_high 会把
        #: no_gain 清零，但回合数只增不减，到达 ``react_max_rounds`` 仍未
        #: 过 80 分即单镜失败继续，避免墙钟被低分震荡耗尽。
        self._react_round_counts: Dict[str, int] = {}
        #: 方案 B（§3.6.3）：逐镜预演的迭代计数（同一镜每预演一轮 +1，
        #: 换镜时随 _decision_trees 一起清理）。
        self._per_shot_iterations: Dict[str, int] = {}
        #: F13：各镜进入逐镜迭代时的墙钟起点（``budget.elapsed``），按
        #: shot_id 记录、换镜清理。用于 per-shot 前瞻均摊
        #: （``wall_share.per_shot_wall_share``）——单镜超公平份额且未过线
        #: 时保留 best、渲染最佳版本、如实记 failed 并推进下一镜（等价
        #: F11 ``react_round_exhausted`` 的时间维度版，不降门槛）。
        self._shot_start_wall: Dict[str, float] = {}
        #: D1：每镜对抗审查的版本号（同镜每审一次 +1；跨轮次只增不减，
        #: 保证任何一版审查都有唯一可回溯的 version）。
        self._adversarial_versions: Dict[str, int] = {}
        #: 每镜决策树缓存（§7.3）：draft/react/repair 三轮共用同一棵树；
        #: 换镜（_advance_shot）与 B5 结束（_finish_react）时清空。
        self._decision_trees: Dict[str, Any] = {}
        self.react_history: List[Dict[str, Any]] = []
        #: 阶段 S 的产物（§3.2）。没有它就等于退回 v1.2 的"直接规划"。
        self.brief: Optional[SceneBrief] = None
        self._brief_attempts = 0
        self._brief_problem = ""
        self._brief_messages: List[Message] = []
        #: 阶段 P 的产物（v1.7 E2，默认关）。改写稿只进这里、**绝不进**
        #: ``self._script``：未采纳（``accepted=False``）时 PLANNING 输入恒原稿。
        self.polish_result: Optional[PolishResult] = None
        self._polish_messages: List[Message] = []
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
        #: 空间尺计划级处方证据（Ticket 05/06）：``{"prescriptions", "measurements"}``，
        #: 供交付层写 ruler 观测 JSON；未跑计划级空间尺时为 None。
        self._ruler_plan_evidence: Optional[Dict[str, Any]] = None
        #: 空间尺计划级审核发现（SR001/SR002，AuditError 对象），折观测用。
        self._ruler_findings: List[AuditError] = []
        #: 空间尺相机闭环**已执行**的处方（转正）：driver 自动 reframe 成功后
        #: 按 prescription_id 记录，供观测折档合并——同一处方只有一个生命周期
        #: 状态，已应用版本覆盖默认生成的未应用版本。
        self._ruler_applied_prescriptions: List[Dict[str, Any]] = []
        #: 空间理解快照（Ticket 08）：设计/观测/diff 三份产物的驱动内存位。
        #: 计划定稿后落设计，收尾采样后落观测与 diff；未生成恒为 None
        #: （快照、UI、交付与重放一律零形状差）。
        self._spatial_design: Optional[Dict[str, Any]] = None
        self._spatial_observation: Optional[Dict[str, Any]] = None
        self._spatial_diff: Optional[Dict[str, Any]] = None
        self._finished_shots: List[str] = []
        self._needs_rebuild = False
        self._rebuild_in_place = False
        self.review_history: List[Dict[str, Any]] = []
        self.clock = clock
        self.thread_factory = thread_factory

        self.state = DriverState.IDLE
        self.plan: Optional[Plan] = None
        self.build_summary: Dict[str, Any] = {}
        #: VLM 评审判词是按镜逐轮写入 ``build_summary["results"]`` 的，但修复
        #: 回路会重建场景并整体替换 summary。这里保留一份按镜快照，重建后
        #: 挂回对应 result；找不到 result 时保持 helper 原有的"不猜"纪律。
        self._vlm_reviews: Dict[str, Dict[str, Any]] = {}
        #: D1：对抗审查快照按镜保留（重建摘要条目后挂回；找不到 result 时
        #: 按 `_record_*` 家族"不猜"纪律跳过）。
        self._adversarial_reviews: Dict[str, Dict[str, Any]] = {}
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
        #: R2：粗排门回溯状态（计划级 U10 三态）。内存态——resume 时粗排
        #: gate 会重跑，可从零重新触发回溯；不允许"计划未过粗排却进细排"。
        self._coarse_attempts = 0
        self._coarse_best_score: Optional[float] = None
        self._coarse_no_gain = 0
        self._coarse_best_plan: Optional[Dict[str, Any]] = None
        self._coarse_best_plan_heading = ""
        self._coarse_best_decision: Optional[Dict[str, Any]] = None
        self._coarse_restore_result: Dict[str, Any] = {}
        self._coarse_feedback: List[str] = []
        self._coarse_dispositions: List[str] = []
        self._coarse_backtracking = False
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
        #: D1：逐镜版本历史（append-only，`{shot_id: ShotVersionHistory}`）。
        #: 换镜时**保留**（可回溯），resume 时从断点恢复。
        self._shot_versions: Dict[str, ShotVersionHistory] = {}
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

    def restore_shot_version(self, shot_id: str, version: int) -> Any:
        """只读回溯这一镜的历史版本计划（深拷贝，不改当前计划/历史）。"""
        history = self._shot_versions.get(str(shot_id))
        if history is None:
            raise KeyError(f"no version history for shot {shot_id}")
        return history.restore(version)

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
            #: R2：粗排门回溯观测（计划级三态；无回溯时恒零/空，零形状差）
            "coarse_attempts": self._coarse_attempts,
            "coarse_best_score": self._coarse_best_score,
            "coarse_best_plan_score": self._coarse_best_score,
            "coarse_best_scene_score": (
                ((self._coarse_best_decision or {}).get("payload") or {})
                .get("best_score")
                if isinstance(
                    (self._coarse_best_decision or {}).get("payload"),
                    Mapping)
                else None),
            "coarse_best_plan": self._coarse_best_plan_heading,
            "coarse_best_restore": copy.deepcopy(
                self._coarse_restore_result),
            "coarse_no_gain": self._coarse_no_gain,
            "coarse_dispositions": list(self._coarse_dispositions),
            "coarse_decision": copy.deepcopy(self._coarse_decision),
            "evidence_store": (
                self.evidence_store.to_dict()
                if self.evidence_store is not None else None),
            "evidence_status": copy.deepcopy(self._evidence_status),
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
            #: 空间尺观测（Ticket 04-06）：finishing 后由内存审计折出的 v2
            #: 文档；未审过镜时为 None（快照零形状差）。
            "ruler_observation": self._ruler_observation_payload(),
            #: E2（§9 步骤③）：阶段 P 的产物进 snapshot，供收尾落 project.bdproj。
            "polish": (self.polish_result.to_dict()
                       if self.polish_result is not None else None),
            "drafts": len(self.draft_history),
            "drafts_failed": len(self.drafts_failed),
            #: v1.5 §7（P6-T2）：Best-of-N 里被降级成备选的候选（低分候选进
            #: shots.json 的 alternates[]，**不丢**）。默认 draft_candidates=1
            #: 时恒为空表。
            "draft_alternates": {shot_id: [dict(item) for item in items]
                                 for shot_id, items in
                                 self._draft_alternates.items()},
            "compliance": self._compliance,
            #: 空间尺计划级证据（Ticket 05/06）：已应用处方与计划级测量，
            #: 供 headless 落盘与交付 bundle 折档；未跑计划级空间尺时为 None。
            "spatial_ruler_plan_evidence": self._ruler_plan_evidence,
            #: 空间理解快照（Ticket 08）：设计/观测/diff 三份产物，供 UI、
            #: headless 摘要与交付折档；未生成时为 None（零形状差）。
            "spatial_design": self._spatial_design,
            "spatial_observation": self._spatial_observation,
            "spatial_diff": self._spatial_diff,
            #: v1.4 P15（§3.3）：交付清单要的两张表，由驱动器产出。
            "timing_overrides": list(self.timing_overrides),
            "audit_pass_rate": self._audit_pass_rate(),
            #: E2（§2.3b）：逐镜知识溯源，交付层写 ``movements[].source`` 用。
            "knowledge_provenance": self.knowledge_provenance(),
            #: v1.6 F2（D-09）：断点续跑的对外读数——终态镜、墙钟撞线标志与
            #: checkpoint 落盘位置。没有配置 resume 路径时后两者为空/False。
            "terminal_shots": {str(k): str(v)
                               for k, v in self._shot_terminal.items()},
            #: 缺陷 D / T8（U1）：单镜 fail 继续后，交付层要的失败清单
            #: （镜号 / 最高分 / 无新高轮数 / 原因）。只收 failed 镜，
            #: 无失败时恒为 ``[]``（零形状差）；由 snapshot 单一真源折出。
            "failures": self._failures_payload(),
            "wall_clock_exhausted": self._wall_clock_exhausted,
            "resume_state_path": (str(self._resume_state_path)
                                  if self._resume_state_path else None),
            "error": self.error,
        }

    def _failures_payload(self) -> Dict[str, Any]:
        """把终态表折成交付失败清单（纯层、无 bpy，D3 不造假画面）。"""
        from ..delivery.failures import build_failures_payload

        return build_failures_payload(
            terminal_shots={str(k): str(v)
                            for k, v in self._shot_terminal.items()},
            best_scores={str(k): dict(v) for k, v in self._react_best.items()},
            no_gain={str(k): int(v)
                     for k, v in self._react_no_gain.items()})

    def _ruler_observation_payload(self) -> Optional[Dict[str, Any]]:
        """把内存审计折成空间尺观测 v2 文档（Ticket 04-06，纯层、无 bpy）。

        数据源全部复用运行产物，不重算、不猜：``audit_results`` → 构图分与
        guard 数值证据；``build_summary.results`` → 相机实测；``_ruler_findings``
        → SR001/SR002 计划级发现。没有计划或没审过镜时返回 ``None``
        （快照零形状差：不发明观测）。
        """
        if self.plan is None or not self.audit_results:
            return None
        from .ruler_observation import build_observation, merge_audit_history

        #: 跨轮合并：verdict 取最后一轮，guard 告警与几何测量取全轮并集。
        #: 此前逐镜覆盖只留最后一轮，而 ``_ruler_applied_prescriptions``
        #: 跨轮累积——早轮已执行处方引用的测量在末轮不存在，结构校验把
        #: 导出中止（2026-10-18 实测 files=0）。
        shot_audits = merge_audit_history([
            result.to_dict() for result in self.audit_results])
        build_results: Dict[str, Dict[str, Any]] = {}
        for item in (self.build_summary or {}).get("results") or []:
            if isinstance(item, dict) and item.get("shot_id"):
                build_results[str(item["shot_id"])] = dict(item)
        run_context = {
            "source_run": self.audit.run_id,
            "status": self.state.value,
            "model": str(getattr(self.config, "model", "") or ""),
            "shots": len(self.plan.shots),
            "characters": len({name for shot in self.plan.shots
                               for name in (shot.characters or [])}),
        }
        doc = build_observation(
            plan=self.plan, parsed=self.parsed_script, brief=self.brief,
            shot_audits=shot_audits, build_results=build_results,
            fps=FPS, run_context=run_context,
            observation_id=f"obs-{self.audit.run_id}",
            plan_findings=self._ruler_findings,
            applied_prescriptions=self._ruler_applied_prescriptions,
        )
        #: 转正：收尾时用一次全场采样补序列级 continuity 复核（逐镜审核时
        #: continuity 如实标未核验）。重放/无 bpy 路径缺采样则原样返回——
        #: 观测文档不重算、不伪造。
        from .ruler_observation import attach_sequence_review
        return attach_sequence_review(doc, plan=self.plan, fps=FPS)

    def _spatial_design_payload(self) -> Optional[Dict[str, Any]]:
        """计划定稿后的前向设计快照（Ticket 02/08，纯层、确定性、无 bpy）。

        角色站位与朝向源：``SceneSpec.from_plan``（默认站位 + ``brief.space``
        声明），与构建器共用同一份计划意图——设计值**不读**实测场景（实测由
        观测快照负责），保证"设计 vs 实测"是有意义的两侧对照。没有计划时返回
        None。
        """
        if self.plan is None:
            return None
        from ..contracts.cast import SceneSpec
        from ..cinema.spatial_design import build_design_snapshot

        spec = SceneSpec.from_plan(self.plan, brief=self.brief)
        cast_positions = {
            str(member.name): list(member.initial_location)
            for member in spec.cast}
        cast_facings = {
            str(member.name): list(member.initial_facing)
            for member in spec.cast}
        return build_design_snapshot(
            brief=self.brief, plan=self.plan,
            cast_positions=cast_positions,
            cast_facings=cast_facings,
            scene_id=self.plan.scene_heading or "scene")

    def _build_spatial_design(self) -> None:
        """在计划定稿处生成设计快照并留审计事件（Ticket 08 接线）。

        幂等：每次调用都按当前最终计划重建（处方/修复后计划变了就重转），
        审计事件带 schema 版本 + 指纹 + 完整 payload（重放零 LLM 复原用）。
        失败只记 warning 并置 None——快照是证据不是门，不阻断运行。
        """
        try:
            design = self._spatial_design_payload()
        except Exception as exc:  # noqa: BLE001 - 快照失败不影响主链
            self.audit.log("spatial_design_snapshot",
                           f"空间设计快照生成失败：{type(exc).__name__}: {exc}",
                           level="warning")
            self._spatial_design = None
            return
        self._spatial_design = design
        if design is None:
            return
        from ..contracts.spatial_snapshot import snapshot_audit_event

        event = snapshot_audit_event("spatial_design_snapshot", design)
        event["created_at"] = datetime.now(timezone.utc).isoformat()
        self.audit.log(
            event["kind"],
            f"空间设计快照已生成（{design.get('schema_version')}）",
            **{key: value for key, value in event.items() if key != "kind"},
            payload=design)

    def _sync_spatial_design_from_world(self) -> None:
        """agent 改动后实时把 Blender 世界坐标回写设计 JSON。

        ``runtime_world_state.json`` 已由工具层在每次成功改动后刷新；这里
        把同一份实测载荷合并进 ``_spatial_design``，让导出/粗排重测不再拿
        计划默认站位（2026-10-21 真跑：伊恩实测 -1.6、设计 JSON -0.3）。
        无 bpy/无快照时诚实跳过，不制造坐标。
        """
        if self._spatial_design is None:
            return
        try:
            from ..layer3_engine.scene_context import get_context
            from ..layer3_engine.world_state import collect_world_state
            from ..contracts.world_state import (
                merge_observed_world_into_reference,
            )
            context = get_context()
            if context is None:
                return
            observed = collect_world_state(context)
            merged = merge_observed_world_into_reference(
                self._spatial_design, observed)
            self._spatial_design = merged
            self.audit.log("spatial_world_sync",
                           "agent 改动已实时回写空间设计 JSON",
                           level="info", payload=merged)
        except Exception as exc:  # noqa: BLE001 - 纯层/无 bpy 如实跳过
            self.audit.log("spatial_world_sync",
                           f"空间设计 JSON 回写跳过：{type(exc).__name__}: {exc}",
                           level="warning")

    def _build_spatial_observation_and_diff(self) -> None:
        """收尾采样 -> 观测快照 -> 设计 vs 实测 diff（Ticket 03/04/08 接线）。

        在 FINISHING 一次性采样：整场与逐镜两条构建路径的最终场景一致，设计
        快照已在计划定稿处生成。无 bpy／无场景上下文／无设计快照时如实留空
        （纯 pytest、离线零形状差）；单镜采样或装配失败只记 warning，不阻断。
        """
        if self._spatial_observation is not None or self._spatial_diff is not None:
            return
        if self.plan is None or self._spatial_design is None:
            return
        try:
            from ..layer3_engine.frustum_sampler import sample_spatial
            from ..layer3_engine.scene_context import get_context
        except ImportError:
            return                                     # 无 bpy：观测如实留空
        from ..cinema.spatial_observation import build_observation_snapshot
        from ..cinema.spatial_diff import build_diff_report
        from ..contracts.spatial_snapshot import snapshot_audit_event

        context = get_context()
        if context is None or not getattr(context, "characters", None):
            return
        frames: List[Any] = []
        for shot in self.plan.shots:
            span = context.schedule.get(str(shot.shot_id))
            if not span:
                continue
            start, end = int(span[0]), int(span[1])
            picked = sorted({start, (start + end) // 2, end})
            try:
                frames.extend(sample_spatial(str(shot.shot_id), picked))
            except Exception as exc:  # noqa: BLE001 - 单镜失败不拖垮收尾
                self.audit.log(
                    "spatial_observation_snapshot",
                    f"镜头 {shot.shot_id} 空间采样失败："
                    f"{type(exc).__name__}: {exc}",
                    level="warning")
        if not frames:
            return
        try:
            observation = build_observation_snapshot(frames)
            diff = build_diff_report(self._spatial_design, observation)
        except Exception as exc:  # noqa: BLE001 - 装配失败不阻断收尾
            self.audit.log(
                "spatial_diff_report",
                f"空间观测/diff 装配失败：{type(exc).__name__}: {exc}",
                level="warning")
            return
        self._spatial_observation = observation
        self._spatial_diff = diff
        for kind, snapshot in (
                ("spatial_observation_snapshot", observation),
                ("spatial_diff_report", diff)):
            event = snapshot_audit_event(kind, snapshot)
            event["created_at"] = datetime.now(timezone.utc).isoformat()
            self.audit.log(
                event["kind"],
                f"空间快照已生成（{snapshot.get('schema_version')}）",
                **{key: value for key, value in event.items() if key != "kind"},
                payload=snapshot)

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
        * 分子 = ``composition_score > composition_threshold`` 的镜头数
          （用户 2026-10-18 裁决：构图分必须严格高于阈值，等于不算过）；
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
                    and composition_decision(
                        score, threshold=float(threshold))["status"] == "pass":
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
        if exhausted and self._shot_queue and self.state not in TERMINAL_STATES:
            # 当前镜未通过时，预算触顶只能暂停并保存断点；不把未完成镜头
            # 伪装成 degraded terminal，也不推进到下一镜。
            self._wrap_up_wall_clock(exhausted)
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
        # §3.2：IDLE → UNDERSTANDING → (POLISHING) → PLANNING。理解阶段可以
        # 被配置关掉，关掉就退回 v1.2 的 IDLE → (POLISHING) → PLANNING；
        # E2 的剧本优化（默认关）插在理解之后、规划之前，由 _polish_gate 判定。
        self._transition(DriverState.UNDERSTANDING if self._stage_s_enabled()
                         else self._polish_gate())

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
            self._transition(self._polish_gate())
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

    def _llm_max_tokens(self) -> Optional[int]:
        """本场每次 LLM 请求的 ``max_tokens``（``llm.max_tokens``；0/未设 = 不发送）。

        与阶段 S 的既有取法同一表达式：``0`` 或未设一律按"不限"处理，返回
        ``None`` 交给 :class:`~..contracts.messages.ChatPayload` 自行省略该字段
        （wire 上不出现 ``max_tokens``）。逐镜的 editor / react / repair / review
        请求必须与 brief / plan 用**同一个**取值，否则验收配置里的 65536 到不了
        单镜请求（实测 run 62e83217414c：13 份编辑器草案全部 502）。
        """
        if self.config is None:
            return None
        return int(getattr(self.config.llm, "max_tokens", 0) or 0) or None

    def _start_brief_call(self) -> None:
        temperature = 0.2
        max_tokens: Optional[int] = None
        if self.config is not None:
            temperature = float(self.config.llm.temperature_repair)
            max_tokens = self._llm_max_tokens()
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
        self._transition(self._polish_gate())

    def _fall_back_to_brief(self, reason: str) -> None:
        """理解失败/预算不足：降级为确定性抽取，**永不致命**（§3.2）。"""
        self.audit.log("brief_degraded",
                       f"剧本理解降级为确定性抽取：{reason}",
                       level="warning", error=ErrorCode.BRIEF_001.value)
        self._emit("brief_degraded", "剧本理解降级", reason=reason)
        self._accept_brief(deterministic_brief(self.parsed_script,
                                               self._character_names()))

    # -------------------------------------------------- 阶段 P（§9 剧本优化）
    def _polish_enabled(self) -> bool:
        """Stage P 总开关（默认关 = 全链路零行为差）。"""
        if self.config is None:
            return False
        return bool(getattr(getattr(self.config, "script_polish", None),
                            "enabled", False))

    def _polish_gate(self) -> DriverState:
        """理解之后的迁移目标：polish 开且场景可建 → POLISHING，否则 PLANNING。"""
        if self._polish_enabled() and self.builder is not None:
            return DriverState.POLISHING
        return DriverState.PLANNING

    def _step_polishing(self) -> None:
        """阶段 P：让模型给原剧本提建议并出改写稿（E2，默认关）。

        照 ``_step_understanding`` 的模式：一次 strict-schema 调用；失败一次
        **不重试**，回落原剧本并记 ``E_POLISH_001``（技术方案 §7 成本纪律）；
        ``accepted=false`` 时 PLANNING 输入恒原剧本——改写稿只进
        ``self.polish_result``，绝不进 ``self.script``。
        """
        if not self._polish_enabled() or self.polish_result is not None:
            self._transition(DriverState.PLANNING)
            return
        if not self.budget.allow_llm_call("polish"):
            self._fall_back_polish(self.budget.exhausted_reason()
                                   or "预算不足以做剧本优化")
            return
        self._start_polish_call()

    def _start_polish_call(self) -> None:
        temperature = 0.2
        max_tokens: Optional[int] = None
        if self.config is not None:
            temperature = float(self.config.llm.temperature_repair)
            max_tokens = self._llm_max_tokens()
        brief_text = ""
        if self.brief is not None:
            brief_text = json.dumps(self.brief.to_dict(),
                                    ensure_ascii=False, sort_keys=True)
        payload = build_polish_payload(
            self.script or "", brief_text,
            temperature=temperature, max_tokens=max_tokens)
        # 阶段 P 的会话**不进** self.messages（与理解同款：那是阶段 A 的会话）。
        self._polish_messages = list(payload.messages)
        self._start_llm_call("polish", payload, note="请求剧本优化")

    def _finish_polish(self, reply: ChatReply) -> None:
        try:
            result = extract_polish(reply)
        except ValueError as exc:
            self._fall_back_polish(f"polish 解析失败：{exc}")
            return
        self.polish_result = result
        self.audit.log(
            "polish_result",
            f"剧本优化完成：{len(result.suggestions)} 条建议 / "
            f"改写稿 {len(result.rewritten)} 字（accepted="
            f"{result.accepted}）",
            level="info",
            suggestions=[str(item) for item in result.suggestions[:5]],
            accepted=bool(result.accepted))
        self._emit("polish_result", "剧本优化完成",
                   suggestions=len(result.suggestions),
                   rewritten_chars=len(result.rewritten))
        self._transition(DriverState.PLANNING)

    def _fall_back_polish(self, reason: str) -> None:
        """优化失败/预算不足：回落原剧本，**一次失败即止，不重试**。"""
        self.audit.log("polish_degraded",
                       f"剧本优化回落原剧本：{reason}",
                       level="warning", error=ErrorCode.POLISH_001.value)
        self._emit("polish_degraded", "剧本优化回落原剧本", reason=reason)
        self._transition(DriverState.PLANNING)

    def _step_planning(self) -> None:
        if not self.budget.allow_llm_call("plan"):
            #: R2：粗排回溯中预算耗尽——绝不带着未过粗排的计划降级收尾出片
            #: （`_degrade_to_finish` 会直接进 FINISHING，绕过粗排门）。
            if self._coarse_backtracking:
                self._fail("预算耗尽且计划未通过粗排 gate，"
                           "不得降级收尾出片")
                return
            self._degrade_to_finish(self.budget.exhausted_reason()
                                    or "LLM 调用预算耗尽")
            return
        #: 计的是**失败次数**（见 `_route_llm_error` 的同名注释）：分块的每一段
        #: 都是一次正常调用，不该吃掉重试额度。
        if self._plan_failures >= self.limits.plan_attempts:
            filled = self._complete_plan_with_deterministic_fill()
            if filled is not None:
                detail = f"：{self._plan_problem}" if self._plan_problem else ""
                message = (f"分镜计划经 {self._plan_failures} 次就地调整后仍不"
                           f"完整，已按剧本声明确定性补齐 {filled} 个缺镜"
                           f"（最后问题{detail}）")
                self.audit.log("plan_adjusted", message, level="warning",
                               filled_shots=int(filled),
                               attempts=int(self._plan_failures),
                               problem=str(self._plan_problem or ""))
                self._emit("plan_adjusted", message,
                           filled_shots=int(filled),
                           attempts=int(self._plan_failures),
                           problem=str(self._plan_problem or ""))
                self._plan_accepted_continue()
                return
            detail = f"：{self._plan_problem}" if self._plan_problem else ""
            self._fail(f"分镜计划生成失败（已达最大尝试次数）{detail}")
            return
        self._plan_attempts += 1
        self._start_plan_call()

    def _complete_plan_with_deterministic_fill(self) -> Optional[int]:
        """计划调整到上限后，用剧本声明兜底补齐缺镜；返回补齐的镜数。

        用户 2026-10-11 裁决："不要指望一次性生成成功，边做边改边调整"——
        已通过的模型分块**原样保留**，只补缺失的 shot_id（确定性计划器
        ``offline.demo_plan_dict``，与离线链路同一份真源，不猜导演意图），
        并照常 `plan_adjusted` 留警告（不是静默降级）。没有可用的确定性
        镜头（声明为空且默认两镜也凑不出）时返回 None，由调用方按原纪律
        报 ERROR。
        """
        from .offline import demo_plan_dict

        declarations = list(
            getattr(self.parsed_script, "declared_shots", []) or [])
        fallback = demo_plan_dict(self.script, declarations)
        fallback_shots = {str(shot.get("shot_id") or ""): shot
                          for shot in (fallback.get("shots") or [])}
        ordered_ids = [str(shot.get("shot_id") or "")
                       for shot in (fallback.get("shots") or [])]
        accepted: Dict[str, Dict[str, Any]] = {}
        for shot in self._plan_shots:
            data = shot.to_dict() if hasattr(shot, "to_dict") else dict(shot)
            accepted[str(data.get("shot_id") or "")] = data
        if not ordered_ids:
            return None
        shots = [accepted[shot_id] if shot_id in accepted
                 else fallback_shots[shot_id] for shot_id in ordered_ids]
        filled = sum(1 for shot_id in ordered_ids if shot_id not in accepted)
        #: ``0`` is not a successful deterministic adjustment.  Treating it as
        #: one re-entered the coarse gate with the exact same plan after every
        #: blocked evaluation (real r2), bypassing the normal
        #: replan-or-fail decision.  The caller needs a fresh model attempt
        #: after a semantic backtrack, or an honest ERROR if none remains.
        if filled <= 0:
            return None
        head = dict(getattr(self, "_plan_head", None) or {})
        payload = {
            "scene_heading": str(fallback.get("scene_heading") or ""),
            "continuity_notes": list(fallback.get("continuity_notes") or []),
            "shots": shots,
            "environment": dict(head.get("environment") or {}),
        }
        self.plan = Plan.from_dict(payload)
        self._plan_shots = [ShotPlan.from_dict(shot) for shot in shots]
        self._apply_scene_budget(len(self.plan.shots))
        return filled

    def _plan_accepted_continue(self) -> None:
        """计划落定后的共同收尾（正常通过与兜底补齐共用，单一真源）。"""
        self._pin_declared_dialogue()
        target = (DriverState.EDITING if self.builder is not None
                  else DriverState.FINISHING)
        if target is DriverState.FINISHING:
            #: v1.7 空间尺（Ticket 03/05）：没有构建器就不会走 B1/BUILDING，
            #: 计划级空间尺在这里落地——与 ``_step_building`` 共用同一接缝
            #: （处方应用、审计留痕、硬发现阻断），否则纯离线链路的快照
            #: ``spatial_ruler_plan_evidence`` 恒为 None，观测 JSON 缺计划级
            #: 处方与测量。两条路径互斥，不会重复执行。
            if not self._apply_plan_ruler():
                return
            # 没有构建器就不会走 B1，注视关系在这里一次补齐。
            self._pin_brief_gaze()
        #: R2-F1：headless 在 plan 落定、进入逐镜细排前跑粗排 gate。
        #: **必须先于 human gate**——headless 的 AutoGate() 会立刻 SKIPPED
        #: 并直接 resume 到目标态，若把它放在 human gate 之后，粗排 gate
        #: 在真实执行链里永远不触发（实测 2026-10-19：审计无任何 coarse 事件，
        #: 只有 gate_requested/gate_decided(skipped) → EDITING）。
        #: blocked 时**不静默放行**：转失败并留审计（粗排诊断产物已由
        #: 调用方落盘），与 UI 全管线的 `coarse_is_ready` 同一判定。
        if not self._run_coarse_gate(target):
            return
        if self._gate_enabled("human_gate_on_plan"):
            self._request_gate(
                GateRequest(kind="plan", title="确认分镜计划",
                            detail=self._plan_gate_detail(),
                            payload={"shots": len(self.plan.shots)
                                     if self.plan else 0}),
                resume=target)
            return
        self._transition(target)

    def _restore_cached_coarse_decision(self) -> bool:
        """Reuse a production coarse decision already frozen at a checkpoint.

        Resume must not call the expensive coarse pipeline again: a new run can
        legitimately score differently and overwrite the exact world best that
        the saved evidence and baseline describe.  Legacy decisions without a
        versioned production report are left to the historical gate path.
        """
        decision = self._coarse_decision
        if not isinstance(decision, Mapping) or not decision.get("ready"):
            return False
        payload = decision.get("payload")
        if (not isinstance(payload, Mapping)
                or str(payload.get("schema_version") or "")
                != "coarse-pipeline-report/v1"):
            return False
        if str(payload.get("coarse_status") or "") != "approved":
            self._fail("断点中的粗排决策未标记 approved，拒绝恢复")
            return True
        evidence_error = self._attach_coarse_evidence(decision)
        if evidence_error:
            self.audit.log(
                "coarse_evidence_invalid", evidence_error, level="error",
                payload=payload)
            self._fail(evidence_error)
            return True
        baseline = decision.get("baseline")
        if (not isinstance(baseline, Mapping)
                or str(baseline.get("schema_version") or "")
                != "coarse-baseline/v1"
                or str(baseline.get("state") or "") != "frozen"):
            self._fail("断点中的粗排决策缺少已冻结的 coarse baseline")
            return True
        store = self.evidence_store
        assert store is not None
        best = store.summary()["best"]
        if not best:
            self._fail("断点中的粗排证据库没有 best 指针")
            return True
        first_shot, first_version = sorted(best.items())[0]
        basis = store.get(first_shot, int(first_version)).basis_fingerprints
        checks = (
            ("manifest_fingerprint", basis.get("manifest_fingerprint")),
            ("reference_fingerprint", basis.get("reference_fingerprint")),
            ("report_fingerprint", basis.get("report_fingerprint")),
        )
        for key, expected in checks:
            if str(baseline.get(key) or "") != str(expected or ""):
                self._fail(
                    f"断点中的 coarse baseline {key} 与证据 best 不一致")
                return True
        baseline_manifest = baseline.get("manifest")
        baseline_reference = baseline.get("reference")
        baseline_report = baseline.get("report")
        if (not isinstance(baseline_manifest, Mapping)
                or not isinstance(baseline_reference, Mapping)
                or not isinstance(baseline_report, Mapping)):
            self._fail("断点中的 coarse baseline 内容不完整")
            return True
        if manifest_fingerprint(baseline_manifest) != str(
                basis.get("manifest_fingerprint") or ""):
            self._fail("断点中的 coarse baseline manifest 内容被篡改")
            return True
        if coarse_reference_content_fingerprint(
                baseline_reference) != str(
                    basis.get("reference_fingerprint") or ""):
            self._fail("断点中的 coarse baseline reference 内容被篡改")
            return True
        if canonical_fingerprint(baseline_report) != str(
                basis.get("report_fingerprint") or ""):
            self._fail("断点中的 coarse baseline report 内容被篡改")
            return True
        attach = getattr(self.builder, "attach_coarse_baseline", None)
        if not callable(attach):
            self._fail("断点中的 coarse baseline 无法接入当前构建器")
            return True
        try:
            attached = int(attach(baseline) or 0)
        except Exception as exc:  # noqa: BLE001 - bridge failure is fatal
            reason = (
                f"断点 coarse baseline 无法接入详细构建："
                f"{type(exc).__name__}: {exc}")
            self.audit.log(
                "coarse_baseline_attach_failed", reason, level="error",
                traceback=traceback.format_exc())
            self._fail(reason)
            return True
        self.audit.log(
            "coarse_gate_reused",
            "断点复用已通过的粗排决策与冻结基准",
            gates=decision.get("gates"),
            best=dict(sorted(best.items())),
            attached=attached)
        self.audit.log(
            "coarse_baseline_attached",
            f"断点冻结粗排相机已接入详细构建（{attached} 镜）",
            shots=attached,
            baseline_schema=str(baseline.get("schema_version") or ""))
        return True

    def _run_coarse_gate(self, target: DriverState) -> bool:
        """plan 落定后、进入逐镜细排前跑粗排 gate；返回是否放行。

        - 未注入回调或目标态不需要细排（FINISHING）：直接放行（零差异）。
        - blocked：**回溯重规划**（R2 计划级 U10 三态）——带回粗排反馈回
          PLANNING 重来，高分保留、低分回溯、门过采用；重规划预算耗尽
          仍不过则如实失败，不降级通过。
        - pass：留审计，返回 True。
        首跑（``_plan_accepted_continue``）与断点续跑（``_apply_resume_state``）
        共用这一判定，保证 resume 不会绕过粗排 gate。
        """
        if (self.coarse_gate is None
                or self.plan is None
                or target is DriverState.FINISHING):
            return True
        #: R2 空计划漏洞（final5 实锤）：剧本【角色锚】声明米迦尔/伊恩/
        #: 偷盗者，模型计划 characters=[] 时粗排门曾因"空镜豁免"零修正放行，
        #: 细排构图 0.0。粗排 gate 前先做**计划完整性预检**（纯层、无 bpy）：
        #: 声明角色非空而计划无主体/丢角色 -> error -> 强制 blocked 走既有
        #: 回溯（高分保留、低分回溯、门过采用），不给空计划绕过验证的机会。
        integrity = plan_integrity_findings(
            self.plan, self.parsed_script, brief=self.brief)
        if integrity:
            decision = merge_integrity_decision(
                {"ready": False, "blocked": True, "reason": "",
                 "gates": {}, "artifacts": {}, "payload": {}},
                integrity)
        else:
            bind_budget = getattr(self.coarse_gate, "bind_budget", None)
            if callable(bind_budget):
                bind_budget(self.budget)
            try:
                decision = dict(self.coarse_gate(self.plan,
                                                 brief=self.brief) or {})
            except TypeError:
                decision = dict(self.coarse_gate(self.plan) or {})
        self._coarse_decision = decision
        if not decision.get("ready", False):
            reason = str(decision.get("reason")
                         or "粗排 gate 未通过，禁止进入细排/逐镜构建")
            #: An exception in the coarse program is not evidence that the
            #: plan is semantically wrong.  Re-planning cannot repair a bug
            #: and previously spent another full model call on the identical
            #: 11-shot plan (real r2).  Preserve the traceback and stop.
            if decision.get("execution_error"):
                self.audit.log(
                    "coarse_execution_error", reason, level="error",
                    error_type=str(decision.get("error_type") or ""),
                    traceback=str(decision.get("traceback") or ""))
                self._fail(reason)
                return False
            self.audit.log("coarse_gate_blocked", reason,
                           level="error",
                           payload=decision.get("payload"),
                           gates=decision.get("gates"))
            #: R2：粗排门回溯——按 U10 三态裁定，带回反馈重规划。
            self._coarse_attempts += 1
            score = _coarse_plan_score(decision.get("payload"))
            bk = coarse_plan_backtrack(
                score, best_score=self._coarse_best_score,
                no_gain=self._coarse_no_gain, gate_ready=False)
            self._coarse_best_score = bk.best_score
            self._coarse_no_gain = bk.no_gain
            self._coarse_dispositions.append(bk.disposition)
            if bk.disposition == "new_high" and self.plan is not None:
                self._coarse_best_plan = self.plan.to_dict()
                self._coarse_best_plan_heading = str(
                    getattr(self.plan, "scene_heading", "") or "")
                self._coarse_best_decision = copy.deepcopy(decision)
            if reason and reason not in self._coarse_feedback:
                self._coarse_feedback.append(reason)
            finding_lines = _coarse_finding_lines(decision.get("payload"))
            for line in finding_lines:
                if line not in self._coarse_feedback:
                    self._coarse_feedback.append(line)
            if self._coarse_attempts > int(self.limits.coarse_replan_attempts):
                best_note = (f"；最优版本仍为 "
                             f"{self._coarse_best_score:g} 分（未过线）"
                             if self._coarse_best_score is not None else "")
                restore_note = self._restore_coarse_best()
                self._fail(f"粗排 gate 经 {self._coarse_attempts} 次评估"
                           f"仍未通过，回溯预算耗尽{best_note}"
                           f"{restore_note}：{reason}")
                return False
            self.audit.log(
                "coarse_backtrack",
                f"粗排门失败，按 {bk.disposition} 回溯（attempt="
                f"{self._coarse_attempts}，score={score:g}，"
                f"best={bk.best_score:g}）",
                level="warning",
                attempt=int(self._coarse_attempts), score=float(score),
                disposition=bk.disposition, best_score=float(bk.best_score),
                no_gain=int(bk.no_gain), reason=reason)
            self._coarse_backtracking = True
            #: A coarse failure is a semantic planning failure, not another
            #: syntax retry for the already exhausted candidate.  Reopen the
            #: per-plan attempt budget so the requested backtrack can actually
            #: produce a new plan; the global LLM/wall budgets still bound it.
            self._plan_failures = 0
            self._restart_plan_accumulator()
            self._transition(DriverState.PLANNING)
            return False
        evidence_error = self._attach_coarse_evidence(decision)
        if evidence_error:
            self.audit.log(
                "coarse_evidence_invalid", evidence_error, level="error",
                payload=decision.get("payload"))
            self._fail(evidence_error)
            return False
        #: 过线采用：清掉回溯态（分数/反馈/最佳快照），正常进细排。
        if self._coarse_attempts:
            self.audit.log(
                "coarse_adopted",
                f"粗排 gate 通过，采用该计划（共评估 "
                f"{self._coarse_attempts} 次，best="
                f"{self._coarse_best_score}）",
                level="info",
                attempts=int(self._coarse_attempts),
                dispositions=list(self._coarse_dispositions))
        self._coarse_attempts = 0
        self._coarse_best_score = None
        self._coarse_no_gain = 0
        self._coarse_best_plan = None
        self._coarse_best_plan_heading = ""
        self._coarse_best_decision = None
        self._coarse_restore_result = {}
        self._coarse_feedback = []
        self._coarse_dispositions = []
        self._coarse_backtracking = False
        self._checkpoint_resume(stage="coarse_adopted")
        self.audit.log(
            "coarse_gate_passed", "粗排 gate 通过，进入细排/逐镜构建",
            gates=decision.get("gates"))
        baseline = decision.get("baseline")
        attach = getattr(self.builder, "attach_coarse_baseline", None)
        if baseline is not None and callable(attach):
            try:
                attached = int(attach(baseline) or 0)
            except Exception as exc:  # noqa: BLE001 - bridge failure is fatal
                reason = (f"粗排冻结基准无法接入详细构建："
                          f"{type(exc).__name__}: {exc}")
                self.audit.log(
                    "coarse_baseline_attach_failed", reason, level="error",
                    traceback=traceback.format_exc())
                self._fail(reason)
                return False
            self.audit.log(
                "coarse_baseline_attached",
                f"冻结粗排相机已接入详细构建（{attached} 镜）",
                shots=attached,
                baseline_schema=str(baseline.get("schema_version") or ""))
        return True

    def _restore_coarse_best(self) -> str:
        """Restore the highest-scoring plan and ask the scene seam to rebuild.

        The returned text is appended to the terminal error so a failed physical
        restore can never masquerade as a successful rollback.
        """
        if self._coarse_best_plan is None:
            self._coarse_restore_result = {
                "status": "unavailable",
                "reason": "no retained coarse best plan",
                "physical_restore": False,
            }
            return ""
        try:
            best_plan = Plan.from_dict(copy.deepcopy(self._coarse_best_plan))
        except Exception as exc:  # noqa: BLE001 - corrupt best is explicit
            reason = f"{type(exc).__name__}: {exc}"
            self._coarse_restore_result = {
                "status": "failed",
                "reason": f"best plan deserialise failed: {reason}",
                "physical_restore": False,
            }
            self.audit.log(
                "coarse_best_restore_failed",
                self._coarse_restore_result["reason"],
                level="error",
            )
            return f"；best plan 无法恢复（{reason}）"

        result: Dict[str, Any] = {}
        physical_restore = False
        error = ""
        if self.coarse_restore is None:
            error = "coarse_restore callback is not configured"
        else:
            try:
                restored = self.coarse_restore(
                    plan=best_plan,
                    decision=copy.deepcopy(self._coarse_best_decision or {}),
                )
                if isinstance(restored, Mapping):
                    result = copy.deepcopy(dict(restored))
                physical_restore = bool(
                    result.get("restored") is True
                    or result.get("physical_restore") is True
                )
                if not physical_restore and not error:
                    error = "restore callback did not return evidence"
            except Exception as exc:  # noqa: BLE001 - terminal failure evidence
                error = f"{type(exc).__name__}: {exc}"
                self.audit.log(
                    "coarse_best_restore_failed",
                    f"physical restore failed: {error}",
                    level="error",
                    traceback=traceback.format_exc(),
                )

        #: Adopt the retained plan even if the scene callback failed.  The plan
        #: account and physical account are then explicitly inconsistent rather
        #: than silently pointing at the last losing candidate.
        self.plan = best_plan
        self._coarse_decision = copy.deepcopy(
            self._coarse_best_decision or {})
        self._coarse_decision["restored_best"] = True
        self._coarse_restore_result = {
            **result,
            "status": (
                "restored" if physical_restore else "plan_only"),
            "physical_restore": physical_restore,
            "error": error,
            "plan_score": self._coarse_best_score,
            "scene_score": (
                ((self._coarse_best_decision or {}).get("payload") or {})
                .get("best_score")
                if isinstance(
                    (self._coarse_best_decision or {}).get("payload"),
                    Mapping)
                else None),
            "plan_heading": self._coarse_best_plan_heading,
        }
        self.audit.log(
            "coarse_best_restored",
            (f"已恢复粗排 best 计划：{self._coarse_best_plan_heading or '(未命名)'}"
             f"；物理场景恢复={'yes' if physical_restore else 'no'}"),
            level="info" if physical_restore else "warning",
            **copy.deepcopy(self._coarse_restore_result),
        )
        if physical_restore:
            return ""
        return f"；best 计划已恢复，但物理场景未恢复（{error or 'unknown'}）"

    def _attach_coarse_evidence(
        self, decision: Mapping[str, Any],
    ) -> str:
        """Bind a passing coarse decision to its exact physical evidence."""
        payload = decision.get("payload")
        if not isinstance(payload, Mapping):
            # Legacy callers/tests have no pipeline report; the historical
            # contract remains valid.  A report that exists must be complete.
            return ""
        if (str(payload.get("schema_version") or "")
                != "coarse-pipeline-report/v1"):
            # Explicit legacy/fake callback seam.  Production reports carry
            # the version above and are held to the evidence-store contract.
            return ""
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, Mapping):
            return "粗排 gate 通过但 pipeline report 缺 artifacts，无法核验证据库"
        path = str(artifacts.get("evidence_store") or "")
        if not path:
            return "粗排 gate 通过但缺少 evidence_store 产物，禁止进入细排"
        store = self.evidence_store
        if store is None:
            store, status = inspect_evidence_store(path)
            self._evidence_status = copy.deepcopy(status)
            if store is None:
                label = (
                    "已过期，只读展示，禁止用于当前门禁"
                    if status.get("status") == "stale"
                    else "不可用"
                )
                return (
                    f"粗排证据库{label}：{path}: "
                    f"{status.get('reason') or 'unknown'}")
        else:
            self._evidence_status = store.summary()
        errors = store.validate()
        if errors:
            return "粗排证据库不一致：" + "；".join(errors)
        report_run_id = str(payload.get("run_id") or "")
        if report_run_id and store.run_id != report_run_id:
            return (
                f"粗排证据库 run_id={store.run_id!r} 与报告 "
                f"{report_run_id!r} 不一致")
        report_scene_id = str(payload.get("scene_id") or "")
        if report_scene_id and store.scene_id != report_scene_id:
            return (
                f"粗排证据库 scene_id={store.scene_id!r} 与报告 "
                f"{report_scene_id!r} 不一致")
        expected = {
            "report": str(payload.get("best_report_fingerprint") or ""),
            "manifest": str(payload.get("best_manifest_fingerprint") or ""),
            "world_state": str(
                payload.get("best_world_state_fingerprint") or ""),
        }
        for shot_id, version in sorted(store.summary()["best"].items()):
            record = store.get(shot_id, int(version))
            basis = record.basis_fingerprints
            try:
                adopted = store.adopted_version(shot_id)
            except KeyError:
                return f"粗排证据 {shot_id}@{version} 未标记 adopted"
            if adopted != int(version):
                return (
                    f"粗排证据 {shot_id} 的 adopted={adopted} "
                    f"与 best={version} 不一致")
            if record.gates.get("coarse_passed") is not True:
                return f"粗排证据 {shot_id}@{version} 未通过粗排门"
            for key, actual in (
                ("report", basis.get("report_fingerprint")),
                ("manifest", basis.get("manifest_fingerprint")),
                ("world_state", basis.get("world_state_fingerprint")),
            ):
                if expected[key] and str(actual or "") != expected[key]:
                    return (
                        f"粗排证据 {shot_id}@{version} 的 {key} 指纹"
                        "与发布给门禁的 best 不一致")
            current_plan = getattr(self, "plan", None)
            if current_plan is not None:
                scene_plan = record.plan.get("scene")
                drift = coarse_plan_identity_drift(
                    scene_plan, current_plan)
                if drift:
                    return (
                        f"粗排证据 {shot_id}@{version} 绑定的镜头身份/顺序"
                        f"与当前恢复计划不一致：{', '.join(drift)}")
        self.evidence_store = store
        self._evidence_status = store.summary()
        return ""

    def _step_calling_llm(self) -> None:
        try:
            item = self._reply_q.get_nowait()
            kind, payload = item[0], item[1]
            error_extra = item[2] if len(item) > 2 else {}
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
                           request_id=self._pending_request_id,
                           **error_extra)
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
                #: G2 #8：修复分支行为不变（无工具调用照记 repair_invalid），
                #: 只补 reason/category 两个数据键。
                self.audit.log("repair_invalid", problem, level="warning",
                               reason=problem,
                               category=classify_invalid(problem))
            #: v1.6 B4：accept 绝不静默——修复回复正文里的
            #: `ACCEPT <warning_type> <reason>` 逐条落成 guard_verdict 事件。
            self._record_guard_accepts(reply)
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
            self._transition(self._resume_per_shot_or_checking())
            return

        if self._call_purpose == "react":
            self._react_steps += 1
            called = bool(reply.tool_calls)
            problem = self._dispatch_tool_calls(reply, self._react_messages)
            if not called:
                #: tool_choice=required 仍可能被实现忽略：无工具调用的回复
                #: 照记 react_invalid（带 reason/category）并结束本轮。
                self.audit.log("react_invalid", problem, level="warning",
                               reason=problem,
                               category=classify_invalid(problem))
                self._finish_react("模型停止调用工具")
                return
            finish_called = any(call.function.name == FINISH_SHOT
                                for call in reply.tool_calls)
            if finish_called and self._pending_finish:
                #: G2 #8：finish_shot 真的执行成功（`_pending_finish` 只在这时
                #: 被置位）⇒ 模型正式声明本镜精修完成，正常收尾，不记
                #: react_invalid。它既有的语义（CHECKING 阶段跳过修复循环）与
                #: 精修收尾同向，无需改语义（见 `_step_checking` 的消费处）。
                self._finish_react("模型调用 finish_shot")
                return
            #: R2-F2：只读轮计入 no_gain——一轮 ReAct 里**全部**工具都是只读
            #: 查询（get_scene_state/check_*/search_knowledge）时，这一轮没有
            #: 真正动手修改场景，记 repair_no_progress 并累计 no_gain；只要本轮
            #: 存在任一修改类工具就豁免并把该镜 no_gain 清零（先查后改不惩罚）。
            #: 工具集合与 loop_detector 的只读表同源（单一真源，禁止另抄）。
            self._record_react_tool_progress(reply.tool_calls)
            #: R2-F2 兜底（2026-10-21）：全只读轮说明模型在"看"却没动手。
            #: 与其让它下一轮继续空转，不如用空间尺做一次**确定性**相机处方
            #: （同一镜最多一次，可回溯），把场景真正改起来再回 CHECKING
            #: 复测。这是"用程序为尺子 + 随机应变"，不是固定处方：reframe
            #: 的量来自当前审计的 guard_warnings，改完立即复测。
            if self._react_readonly_auto_reframe(self._react_shot):
                self._finish_react("全只读轮已自动 reframe，回审核复测")
                return
            if problem:
                self.audit.log("react_invalid", problem, level="warning",
                               reason=problem,
                               category=classify_invalid(problem))
            if self._react_steps >= self._react_max_steps():
                self._finish_react("本轮 ReAct 步数用尽，返回审核")
                return
            self._start_react_turn()
            return

        if self._call_purpose == "editor":
            self._finish_editor_turn(reply)
            return

        if self._call_purpose == "understand":
            self._finish_brief(reply)
            return

        if self._call_purpose == "polish":
            self._finish_polish(reply)
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
        self._plan_accepted_continue()

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
        self._pin_declared_shot_types(declared)
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
                shot.declared_duration_frames = max(
                    1, int(round(float(declared_seconds) * FPS)))
                applied_s = round(
                    int(shot.duration_frames) / float(FPS), 3)
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

    def _pin_declared_shot_types(self, declared) -> None:
        """按剧本声明恢复景别；无理由的旧式 ``break`` 不构成豁免。

        阶段 A schema 已拒绝无 ``reason`` 的破例，但旧断点绕过了那条入口。
        因此正式计划收尾与 resume 恢复都必须走同一道守卫：只有
        ``rule=R015``、``action=break`` 且 ``reason`` 非空的条目才能保留
        模型给出的不同景别；其余情况一律回到声明值。
        """
        pinned = 0
        for index, shot in enumerate(self.plan.shots):
            if index >= len(declared):
                break
            declared_type = str(
                getattr(declared[index], "shot_type", "") or "").upper()
            has_break = any(
                str(item.get("rule") or "") == "R015"
                and str(item.get("action") or "").lower() == "break"
                and str(item.get("reason") or "").strip()
                for item in (shot.rule_justifications or []))
            if (declared_type in SHOT_TYPES and not has_break
                    and str(shot.shot_type) != declared_type):
                shot.shot_type = ShotType(declared_type)
                pinned += 1
        if pinned:
            self.audit.log(
                "plan_declared_shot_type_pinned",
                f"已按剧本声明恢复 {pinned} 个镜头的景别",
                shots=len(self.plan.shots))

    def _pin_declared_camera(self, declared) -> None:
        """把分镜表的「拍摄手法」**落实**成运镜（v1.3 §3.6 ＋ v1.4 §八十五）。

        两件事，方向相反、纪律同一条（"声明的必须落实"）：

        * 声明了**非固定**手法而草案没给 ⇒ 钉上（v1.3 起的老行为）；
        * 声明了**固定镜头**而草案自己加了运动 ⇒ **去掉**（这一轮新增）。

        后半段为什么是必须的（2026-10-04 实测，§八十五）：分镜表为 **63 镜**声明
        "固定镜头"，交付里 **40 镜**在这条声明之外自己动了相机（`movements[].source`
        只有 1 次归给 `declared`）。把那些未声明的运动去掉后重建、逐镜复评（零 LLM）：

        | 工程 | 逐镜通过 | 旧构图通过数（历史 ≥70 口径） | 构图分中位 |
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
            if is_server_error(problem):
                # R2-F3：瞬时 5xx（502/503/504）重试耗尽不是镜头质量问题。
                # 按用户红线"拦截错误后回溯而不是停止生成"：保留最高分版本，
                # 记该镜 failed 并**继续下一镜**，白模预演视频仍要生成；
                # 不允许整条链 CANCELLED 停机（超时仍走下方 checkpoint 分支）。
                self.audit.log(
                    "repair_failed",
                    f"{shot_id} 修复调用连续 5xx 失败，保留最高分并继续下一镜："
                    f"{problem}",
                    level="warning", shot=shot_id)
                self._mark_terminal(str(shot_id), "failed")
                self._emit("react_terminal_fail",
                           f"{shot_id} 精修网络失败，标记 failed 并继续",
                           shot=str(shot_id))
                self._advance_shot()
                return
            self.audit.log(
                "repair_failed",
                f"{shot_id} 修复调用连续失败（保留当前镜并暂停）：{problem}",
                level="warning", shot=shot_id)
            # 网络重试阶梯耗尽不是镜头质量达标，不能降级前进；保存断点后
            # 结束本次运行，resume 会从同一镜继续。
            self._checkpoint_resume(stage="repair_failed",
                                    reason=str(problem))
            self._transition(DriverState.CANCELLED)
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
        if purpose == "polish":
            # 优化失败**不重试**（E2 成本纪律）：一次失败即回落原剧本。
            self._fall_back_polish(problem)
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
            self._transition(self._resume_per_shot_or_checking())
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
            message = f"{shot_id}: {problem}"
            self.audit.log("draft_invalid", message,
                           level="warning", shot=shot_id,
                           reason=message, category=classify_invalid(message))
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
        self._transition(self._resume_per_shot_or_checking())

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
    def _supports_prepare_scene(self) -> bool:
        """方案 B（§3.6.3）：builder 是否支持“先准备场景、再逐镜预演”。

        ``prepare_scene`` 与 ``rebuild_shot`` 必须同时存在才走逐镜路径；
        任一缺失（例如测试注入的假 builder 只实现 ``build``）都退回旧的
        整场 ``BUILDING → CHECKING``（兼容回退，不是降级）。
        """
        return (self.builder is not None
                and hasattr(self.builder, "prepare_scene")
                and hasattr(self.builder, "rebuild_shot"))

    def _resume_per_shot_or_checking(self) -> DriverState:
        """修复/ReAct/复核完成后的复核落点（方案 B 出口统一 helper）。

        逐镜路径回 ``PER_SHOT``（同一镜继续预演/审核），旧路径回
        ``CHECKING``。调用方把结果交给 ``_transition``，不改任何行为。
        """
        return (DriverState.PER_SHOT if self._supports_prepare_scene()
                else DriverState.CHECKING)

    def _tree_for_shot(self, shot_id: str) -> Any:
        """当前镜的决策树（懒建 + 缓存，§3.6.6）。

        draft/react/repair 三轮共用同一棵；plan 合并后调用方负责
        ``pop``（树失效条件 S-1）。与 :meth:`_dispatch_tool_calls` 的
        缓存模式同源，不在这里另起一套。
        """
        tree = self._decision_trees.get(shot_id)
        if tree is not None:
            return tree
        shot = self._shot_by_id(shot_id)
        if shot is None or self.plan is None:
            return None
        tree = build_tree(shot, self.plan)
        self._decision_trees[shot_id] = tree
        return tree

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
            self._transition(DriverState.PREPARE_SCENE
                             if self._supports_prepare_scene()
                             else DriverState.BUILDING)
            return
        shot_id = self._editing_queue[self._editing_index]
        if not self.budget.allow_llm_call("editor"):
            self.audit.log("editor_skipped",
                           f"预算不足以逐镜生成，{shot_id} 起沿用计划内容",
                           level="warning")
            self._editing_queue = []
            self._pin_brief_gaze()
            self._transition(DriverState.PREPARE_SCENE
                             if self._supports_prepare_scene()
                             else DriverState.BUILDING)
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
        temperature = 0.7
        max_tokens: Optional[int] = None
        if self.config is not None:
            temperature = float(self.config.llm.temperature_plan)
            max_tokens = int(getattr(self.config.llm, "max_tokens", 0) or 0) or None
        payload = build_editor_payload(
            shot, self.plan, shot_order=self._editing_index + 1,
            scene_state=self._scene_state_text(),
            scene_text=self._shot_script_text(),
            continuity=render_shot_memory(
                shot_memory(self.plan, done=self._finished_shots)),
            characters=characters, full_cast=self._cast_roster(),
            props=props, retriever=self.knowledge,
            temperature=temperature, max_tokens=max_tokens)
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

    def _apply_shot_schemas(self, shot_id: str) -> None:
        """G2 判据 #8：把**这一镜**的逐镜工具 schema 装进注册表（幂等替换）。

        ``emit_shot_draft`` 换成完整逐镜 schema，角色工具（character_id /
        target）注入本镜在场角色与全剧组的枚举。载荷构造
        （``schemas_except`` / ``openai_schemas``）与 ``registry.execute`` 读
        同一个 ``spec.parameters``，所以模型看到的 schema 与校验用的 schema
        是**同一个对象**——换镜时再调一次即可，不会残留上一镜的枚举。
        """
        characters, anchors = self._draft_context(shot_id)
        overrides = shot_tool_overrides(self.registry, characters,
                                        self._cast_roster(), anchors)
        for name, parameters in overrides.items():
            self.registry.override_parameters(name, parameters)

    def _finish_editor_turn(self, reply: ChatReply) -> None:
        shot_id = self._editing_queue[self._editing_index]
        characters, anchors = self._draft_context(shot_id)
        tree = self._tree_for_shot(shot_id)
        try:
            draft = extract_draft(reply, shot_id, characters=characters,
                                  anchors=anchors,
                                  roster=self._cast_roster(),
                                  full_cast=self._cast_roster(),
                                  tree=tree)
        except ValueError as exc:
            # 单镜草案失败不拖垮整场：记进 history 与警告，这一镜沿用计划内容，
            # 后面还有 B3/B4 兜住真正的执行问题。
            self.drafts_failed.append({"shot_id": shot_id, "error": str(exc)})
            message = f"{shot_id}: {exc}"
            self.audit.log("draft_invalid", message, level="warning",
                           shot=shot_id, reason=message,
                           category=classify_invalid(message))
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
                                       characters=characters, anchors=anchors,
                                       full_cast=self._cast_roster())
        if best is not None:
            records = list(getattr(best, "projection_records", None) or [])
            if records:
                event = {"shot_id": shot_id, "stage": "draft",
                         "records": list(records)}
                self.audit.log(
                    "draft_projected",
                    f"{shot_id} 草案 {len(records)} 处投影到合法空间",
                    **event)
                self._emit("draft_projected", f"{shot_id} 草案已投影",
                           **event)
            merged = merge_draft(self.plan, best)
            #: 计划合并 = 树失效条件 S-1：下一轮（react/repair）必须重建，
            #: 旧树继续投影就是拿过期语义换新镜。
            self._decision_trees.pop(str(shot_id), None)
            crossing = unseen_axis_crossing(merged, self.brief, shot_id)
            if crossing:
                #: v1.6 G2：不可见的走位跨线挡在计划外，而不是等到审核判错。
                self.drafts_failed.append(
                    {"shot_id": shot_id, "error": crossing})
                message = f"{shot_id}: {crossing}"
                self.audit.log("draft_invalid", message,
                               level="warning", shot=shot_id,
                               reason=message,
                               category=classify_invalid(message))
                self._emit("draft_invalid", f"{shot_id} 草案无效",
                           shot=shot_id)
            else:
                self.plan = merged
                self.draft_history.append(best.to_dict())
                if alternates:
                    self._draft_alternates[shot_id] = [item.to_dict()
                                                       for item in alternates]
                self.audit.log(
                    "draft_received",
                    f"{shot_id}: {len(best.actions)} 个动作 / "
                    f"{len(best.dialogues)} 句对白",
                    shot=shot_id, actions=len(best.actions),
                    dialogues=len(best.dialogues),
                    #: 只在真的开了 Best-of-N 时才写候选数——默认 1 时
                    #: 事件形状与升级前逐字节相同（NFR-4）。
                    **({"candidates": len(self._draft_candidates)}
                       if wanted > 1 else {}))
                self._emit("draft_received", f"{shot_id} 草案已合并",
                           shot=shot_id)
                # v1.6 F2（D-09）：B1 每镜起草成功即落 checkpoint——即使
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

    def _apply_plan_ruler(self) -> bool:
        """空间尺计划级接缝（Ticket 03/05，有/无构建器共用单一真源）。

        在 bpy 构建前落实角色与节奏约束：审核＋应用处方（retime_shot /
        restore_cast），处方记录与计划级测量一并留痕（审计事件 + compliance
        + 交付证据）。仍残留的逐镜 ERROR 级硬发现阻断后续（``_fail``）。

        ``ruler.enabled=False`` 时全链路零行为差：不审核、不处方、不留证据
        （用户显式关闭，不是降级）。

        返回 False 表示已阻断（调用方应停止推进）；True 表示可继续。
        """
        if not self._ruler_enabled():
            self._ruler_plan_evidence = None
            self._ruler_findings = []
            #: 空间理解快照（Ticket 08）：计划定稿即生成设计快照，与空间尺
            #: 开关无关（快照是产品证据，不是空间尺的处方产物）。
            self._build_spatial_design()
            return True
        plan = self.plan or Plan()
        declared_total = getattr(self.parsed_script, "declared_total_seconds",
                                 None)
        declared_by_shot: dict = {}
        declared_shots = list(
            getattr(self.parsed_script, "declared_shots", []) or [])
        for plan_shot, declared in zip(plan.shots, declared_shots):
            seconds = getattr(declared, "declared_seconds", None)
            if seconds is not None:
                declared_by_shot[str(plan_shot.shot_id)] = float(seconds)
        from .spatial_ruler import apply_plan_prescriptions

        plan, ruler_findings, ruler_prescriptions, ruler_measurements = (
            apply_plan_prescriptions(
                plan, brief=self.brief,
                declared_total_seconds=declared_total,
                declared_seconds_by_shot=declared_by_shot))
        self._ruler_plan_evidence = {
            "prescriptions": list(ruler_prescriptions),
            "applied_prescriptions": [],
            "measurements": list(ruler_measurements),
        }
        self._ruler_findings = list(ruler_findings)
        if ruler_findings or ruler_prescriptions:
            self.audit.log(
                "spatial_ruler_plan_audit",
                f"空间尺计划审核：{len(ruler_findings)} 项发现 / "
                f"{len(ruler_prescriptions)} 条处方",
                level="warning" if not any(
                    item.severity == "error" for item in ruler_findings)
                else "error",
                findings=[item.to_dict() for item in ruler_findings],
                prescriptions=list(ruler_prescriptions),
                measurements=list(ruler_measurements))
            self._compliance = dict(self._compliance or {})
            existing = list(self._compliance.get("findings") or [])
            existing.extend(item.to_dict() for item in ruler_findings)
            self._compliance["findings"] = existing
            self._compliance["ruler_prescriptions"] = list(ruler_prescriptions)
            self._compliance["ruler_measurements"] = list(ruler_measurements)
        #: Ticket 03（空间尺硬发现阻断）：处方已尽量自动应用（retime_shot /
        #: restore_cast），仍残留的 ERROR 级发现 = 未修复的硬发现（SR001 无落点、
        #: SR002 逐镜漂移装不下对白）。**不得静默放行**——阻断构建，直到修复
        #: 或按既有审核 policy 显式豁免。
        #: 阻断范围只收**有修复路径但没落地**的逐镜硬发现（target 是 shot_id）；
        #: 全场时长漂移（target="plan"）缺逐镜声明、policy 明确只报不自动重排
        #: （擅自重排会改坏对话语义）——即按既有 policy 显式豁免，保持 ERROR
        #: 进 compliance 可见，但不阻断。
        hard_findings = [
            item for item in ruler_findings
            if item.severity == "error" and item.target != "plan"
        ]
        if hard_findings:
            self.audit.log(
                "ruler_blocked",
                f"空间尺硬发现阻断构建：{len(hard_findings)} 项未修复",
                level="error",
                findings=[item.to_dict() for item in hard_findings],
                prescriptions=list(ruler_prescriptions),
                measurements=list(ruler_measurements))
            self._fail(f"空间尺硬发现阻断构建：{hard_findings[0].message}")
            return False
        self.plan = plan
        #: 空间理解快照（Ticket 08）：处方应用后的**最终计划**才是设计快照
        #: 的真源——在这之前转会在处方落地前定格，diff 就会拿旧计划对账。
        self._build_spatial_design()
        return True

    def _step_building(self) -> None:
        """把分镜计划交给场景构建器（bpy 实现在 layer3_engine/shot_builder.py）。"""
        #: 空间尺计划级接缝与阻断纪律与无构建器路径共用（单一真源）。
        if not self._apply_plan_ruler():
            return
        if self.builder is None:
            self._transition(DriverState.FINISHING)
            return
        started = self.clock()
        try:
            summary = self.builder.build(self.plan, self.brief) or {}
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
        self._wire_world_state()
        #: v1.6 A7 / G2：全帧自检的余量此前只进 summary.warnings 字符串，
        #: 审计日志与交付 README 都拿不到结构化读数。这里把构建摘要转成
        #: ``label_overlap_report`` 事件（字段与 V16_EVENT_FIELDS 对拍）。
        if self.config is not None and bool(
                getattr(getattr(self.config, "labels", None),
                        "fullframe_verify", True)):
            overlap_fields = label_overlap_event_fields(self.build_summary)
            if overlap_fields is not None:
                self.audit.log("label_overlap_report", "标签全帧自检完成",
                               **overlap_fields)
        self._transition(self._after_build_state())

    # -------------------------------------------------- 方案 B（§3.6.3）逐镜预演
    def _step_prepare_scene(self) -> None:
        """方案 B：只建场景与元素，不摆相机、不烘焙动作（§3.6.3）。"""
        if self.builder is None or self.plan is None:
            self._transition(DriverState.FINISHING)
            return
        #: 空间理解快照（Ticket 08 接线）：逐镜预演路径不经过 `_step_building`
        #: 的整场构建，设计快照在场景准备前先落（计划已是 B1 定稿）。
        self._build_spatial_design()
        started = self.clock()
        try:
            summary = self.builder.prepare_scene(self.plan, self.brief) or {}
        except Exception as exc:  # noqa: BLE001 - 构建失败要如实上报
            log.error("场景准备失败：\n%s", traceback.format_exc())
            self.audit.log("build_failed", f"{type(exc).__name__}: {exc}",
                           level="error")
            self._fail(f"场景准备失败：{type(exc).__name__}: {exc}")
            return
        self.build_summary = dict(summary)
        #: 逐镜结果由 _step_per_shot 逐镜补进（§3.6.4 F/G/U/V/W）。
        if not isinstance(self.build_summary.get("results"), list):
            self.build_summary["results"] = []
        #: 真实墙钟时间（不是 `time.monotonic` 的开机秒——那会让审计里的
        #: prepared_at 落在 1970 年）。与 `_step_building` 的 `duration_s`
        #: 口径一致：`started` 仍用 monotonic 算耗时，时间戳用 datetime.now。
        prepared_at = datetime.now(timezone.utc).isoformat()
        event = {
            "characters": int(summary.get("characters", 0) or 0),
            "cameras": int(summary.get("cameras", 0) or 0),
            "props": int(summary.get("props", 0) or 0),
            "crowd": int(summary.get("crowd", 0) or 0),
            "prepared_at": prepared_at,
        }
        self.audit.log("scene_prepared", "场景与元素已就位", **event)
        self._emit("scene_prepared", "场景与元素已就位", **event)
        #: 逐镜路径也必须发 `scene_built`：交付链与既有探针（rk9）按它判断
        #: "场景已构建"（判据一字不动）。prepare_scene 是方案 B 的"场景就位"
        #: 语义，reason 取 `scene_built_reason` 的静态分支（非重建/非回滚）。
        duration = self.clock() - started
        reason = scene_built_reason(rebuild_in_place=False,
                                    just_rolled_back=False)
        scalars = {k: v for k, v in self.build_summary.items()
                   if isinstance(v, (int, float, str))
                   and k not in SCENE_BUILT_RESERVED_KEYS}
        self.audit.log("scene_built", "场景已构建（逐镜预演路径）",
                       reason=reason, duration_s=round(duration, 3),
                       **scalars)
        self._emit("scene_built", "场景已构建（逐镜预演路径）",
                   reason=reason, **scalars)
        self._wire_world_state()
        #: 逐镜路径下队列**不能从 auditor.shot_ids() 取**：方案 B 的场景此时
        #: 还没摆相机，而 `BpyShotAuditor.shot_ids()` 按
        #: ``shot_id in context.cameras`` 过滤——相机未建 ⇒ 返回空 ⇒ 队列空
        #: ⇒ 整场被 FINISHING 跳过（headless 实测 `built=false`）。镜序的唯一
        #: 真源是 ``plan.shots``（§3.6.3 不变量：顺序推进，不改计划顺序）。
        shots = [str(s.shot_id) for s in self.plan.shots]
        if shots:
            self._shot_queue = shots
            self._current_shot_id = shots[0]
            self._repair_attempts = 0
            self._transition(DriverState.PER_SHOT)
            return
        self._transition(DriverState.FINISHING)

    def _step_per_shot(self) -> None:
        """方案 B（§3.6.3）：逐镜重构 → 审核 → 通过才前进。

        每镜进入本状态时先增量重建当前镜（``builder.rebuild_shot``），
        再走既有审核/修复路由（``_route_audit_result``）；修复/ReAct/
        复核完成后经 ``_resume_per_shot_or_checking`` 回到本状态，继续
        审当前镜——迭代是增量调整，不是整场重来。
        """
        if self.builder is None or not self._shot_queue:
            self._transition(DriverState.FINISHING)
            return
        shot_id = self._shot_queue[0]
        self._current_shot_id = shot_id
        #: F13：per-shot 墙钟前瞻均摊——首轮进入该镜时记录墙钟起点，
        #: 之后每轮迭代（rebuild 前）检查是否已超公平份额。单镜超份额且
        #: 未过线时，保留 best（`_record_react_score` 已保证）、渲染最佳
        #: 版本、如实记 failed 并推进下一镜；不再让单镜空转耗尽全局墙钟
        #: 把整场打成 CANCELLED（final8/final9 实测）。这是资源公平分配，
        #: 不是放宽 80 分门槛；F12 保证 failed 镜照常出 mp4。
        if str(shot_id) not in self._shot_start_wall:
            self._shot_start_wall[str(shot_id)] = self.budget.elapsed
        if self._wall_share_exhausted(shot_id):
            return
        resumed_status = self._shot_terminal.get(str(shot_id), "")
        if str(shot_id) in self._resume_terminal and resumed_status:
            self.audit.log(
                "shot_resumed_skipped",
                f"{shot_id} 终态（{resumed_status}）从断点恢复，跳过",
                shot_id=shot_id, status=resumed_status)
            self._emit("shot_resumed_skipped", f"{shot_id} 从断点跳过",
                       shot_id=shot_id, status=resumed_status)
            self._advance_shot()
            return
        round_no = int(self._per_shot_iterations.get(str(shot_id), 0)) + 1
        self._per_shot_iterations[str(shot_id)] = round_no
        try:
            #: 逐镜迭代是"同镜增量调整"：保留 agent 工具/空间尺改过的相机
            #: （reframe/setup_camera 的成果），否则每轮重建都按计划原值
            #: 重摆相机，构图修复无法收敛（final6 实测：35→25.2mm 的
            #: reframe 被下一轮重建打回，构图停在 20–43 上不了 80）。
            regen = self.builder.rebuild_shot(
                shot_id, plan=self.plan, preserve_camera_edits=True) or {}
        except Exception as exc:  # noqa: BLE001 - 逐镜重建失败要如实上报
            log.error("单镜重建失败：\n%s", traceback.format_exc())
            self.audit.log("build_failed", f"{type(exc).__name__}: {exc}",
                           level="error", shot=shot_id)
            self._fail(f"{shot_id} 单镜重建失败：{type(exc).__name__}: {exc}")
            return
        warnings = [str(item) for item in (regen.get("warnings") or [])]
        protected = [str(item) for item in (regen.get("protected") or [])]
        iteration_event = {
            "shot_id": shot_id,
            "round": round_no,
            "action": "build",
            "result": dict(regen),
            "warnings": warnings,
            "protected": protected,
        }
        self.audit.log("shot_iteration", f"{shot_id} 第 {round_no} 轮预演已构建",
                       **iteration_event)
        self._emit("shot_iteration", f"{shot_id} 第 {round_no} 轮预演",
                   **iteration_event)
        #: 逐镜 result 写进 build_summary["results"]（交付层按 shot_id 读）。
        #: 同镜第二轮起**整体替换**该镜条目——只补缺键会让修复后的新值
        #: （camera_position/lens/warnings）永远留在旧版本（实测隐患）。
        #: 保留非 rebuild 产物的键：justification_audit（破例对拍）、
        #: vlm_review（外部评审）、alternates（Best-of-N 备选）、
        #: adversarial_review（D1 对抗审查）由各自的生产者后续写入，
        #: 这里不能丢掉。
        results = self.build_summary.setdefault("results", [])
        preserved_keys = ("justification_audit", "vlm_review", "alternates",
                          "adversarial_review")
        preserved = {}
        for item in results:
            if isinstance(item, dict) and str(item.get("shot_id")) == shot_id:
                for key in preserved_keys:
                    if key in item:
                        preserved[key] = item[key]
                item.clear()
                item.update(regen)
                item.update(preserved)
                break
        else:
            results.append(dict(regen))
        #: 汇总计数随逐镜结果累计（prepare_scene 的摘要 cameras=0/motions=0/
        #: keyframes=0；交付层与 UI 按这些键读总账）。每镜重建都产生相机；
        #: motions/keyframes 只有成功烘焙的才累计。
        self.build_summary["cameras"] = int(
            (self.build_summary.get("cameras") or 0)
            + (1 if regen.get("camera") else 0))
        self.build_summary["motions"] = int(
            (self.build_summary.get("motions") or 0)
            + (regen.get("motions") or 0))
        self.build_summary["keyframes"] = int(
            (self.build_summary.get("keyframes") or 0)
            + (regen.get("keyframes") or 0))
        #: 与 CHECKING 完全同一套审核/修复/回滚路由（判据与阈值一字不动）。
        #: 无 auditor（测试/嵌入用法）不审计、不修复：与 `_audit_and_route`
        #: 的 None-result 分支同构，逐镜仍摆相机后前进、终态记 unverified，
        #: 保住旧 BUILDING 路径"无 auditor 也产出带相机的场景"的语义——
        #: phase6 探针 `review_requests_survive_real_driver_build_and_export`
        #: 就是用不带 auditor 的驱动跑完后直接导出的。
        if self.auditor is not None:
            self._audit_and_route(shot_id)
            return
        self._mark_terminal(shot_id, "unverified")
        self._advance_shot()

    def _wall_share_enabled(self) -> bool:
        """F13：per-shot 墙钟前瞻均摊是否开启（默认开）。"""
        if self.config is None:
            return True
        return bool(getattr(self.config.orchestration,
                            "wall_share_enabled", True))

    def _wall_share_min_seconds(self) -> float:
        """F13：单镜时间地板（默认 60s）。"""
        if self.config is None:
            return 60.0
        return float(getattr(self.config.orchestration,
                             "wall_share_min_seconds", 60.0))

    def _wall_share_exhausted(self, shot_id: str) -> bool:
        """当前镜是否已超公平墙钟份额（触发收尾推进，不停止生成）。

        逐镜路径下、全局墙钟有界、剩余镜 > 1 时：把剩余墙钟按剩余镜数
        前瞻均摊（不低于 floor）。当前镜自首轮迭代起已用时间 > 份额且
        尚未过线 -> 记 ``wall_share_exhausted``、如实终态 ``unfinished``、
        推进下一镜。与 ``_wrap_up_wall_clock``（全局兜底）并存：本方法
        管"镜级公平"，全局撞线仍由后者收尾。
        """
        if not self._wall_share_enabled():
            return False
        if self.budget is None:
            return False
        max_wall = self.budget.limits.max_wall_seconds
        if not max_wall:
            return False
        remaining_shots = len(self._shot_queue)
        if remaining_shots <= 1:
            return False
        elapsed_global = self.budget.elapsed
        remaining_wall_s = float(max_wall) - elapsed_global
        started = self._shot_start_wall.get(str(shot_id), elapsed_global)
        elapsed_in_shot_s = elapsed_global - started
        if not per_shot_wall_share(
                remaining_wall_s=remaining_wall_s,
                remaining_shots=remaining_shots,
                elapsed_in_shot_s=elapsed_in_shot_s,
                min_share_s=self._wall_share_min_seconds()):
            return False
        self.audit.log(
            "wall_share_exhausted",
            f"{shot_id} 已超公平墙钟份额（剩余 {remaining_wall_s:.0f}s / "
            f"{remaining_shots} 镜，本镜已用 {elapsed_in_shot_s:.0f}s），"
            "保留最佳版本并推进下一镜",
            level="warning", shot=shot_id,
            remaining_wall_s=round(remaining_wall_s, 1),
            remaining_shots=remaining_shots,
            elapsed_in_shot_s=round(elapsed_in_shot_s, 1),
            best_score=(self._react_best.get(str(shot_id)) or
                        {}).get("score"))
        self._emit("wall_share_exhausted",
                   f"{shot_id} 超均摊墙钟，推进下一镜", shot=shot_id)
        self._mark_terminal(shot_id, "unfinished")
        self._advance_shot()
        return True

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
        #: 回滚只恢复到最后一个已知较好版本；不把计数钉到旧上限。
        #: 当前镜仍可继续修复，直到通过或外部资源边界暂停。
        self._repair_attempts = 0
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
        #: 方案 B（§3.6.5）：逐镜路径下回滚**不整场重建**——恢复该镜基线计划
        #: 快照、增量重做当前镜；环境/角色/其他镜不动，bd_user_animated 保护
        #: 不因回滚失效。旧 BUILDING 整场分支只留给无 prepare_scene 的假
        #: builder（兼容回退，不是降级）。
        if self._supports_prepare_scene():
            #: F15（final10 实测）：旧回滚只恢复计划、不恢复场景——空间尺
            #: reframe 的 lens 36mm 与工具改过的机位都是**场景级**状态，
            #: rebuild 会把 79.5 分版本冲回计划原值 50mm/53 分，回滚形同
            #: 虚设。回滚语义升级为"回到最高分版本"：先物理恢复 best 世界
            #: 快照（restore_world_snapshot 会打 agent 标记），再带
            #: ``preserve_camera_edits=True`` 重建当前镜，让高分版本在重建后
            #: 依然在位。纯层/无 bpy 时 ``_revert_to_best`` 自动跳过
            #: （revert_skipped），行为与旧回滚一致。
            self._revert_to_best(shot_id)
            try:
                self.builder.rebuild_shot(
                    shot_id, plan=self.plan,
                    preserve_camera_edits=True)
            except Exception as exc:  # noqa: BLE001 - 回滚重建失败如实上报
                log.error("回滚单镜重建失败：\n%s", traceback.format_exc())
                self.audit.log("build_failed",
                               f"{type(exc).__name__}: {exc}", level="error",
                               shot=shot_id)
                self._fail(f"{shot_id} 回滚单镜重建失败："
                           f"{type(exc).__name__}: {exc}")
                return True
            self.audit.log("shot_iteration",
                           f"{shot_id} 回滚后增量重做当前镜",
                           shot_id=shot_id,
                           round=int(self._per_shot_iterations.get(
                               str(shot_id), 0)) + 1,
                           action="rollback", result={},
                           warnings=[], protected=[])
            self._transition(self._resume_per_shot_or_checking())
            return True
        self._needs_rebuild = True
        self._rebuild_in_place = True
        self._transition(DriverState.BUILDING)
        return True

    def _record_guard_accepts(self, reply: ChatReply) -> None:
        """B4：把修复回复里的 accept 声明落成 ``guard_verdict`` 事件（不静默）。

        正文没有 ``ACCEPT`` 行就什么都不记；有声明但格式错误记
        ``repair_invalid``（格式错了要看得见，不能把一次 accept 悄悄丢掉）。
        """
        content = str(getattr(reply, "content", "") or "")
        if not content or "ACCEPT" not in content.upper():
            return
        try:
            verdicts = parse_guard_accepts(
                content, shot_id=self._current_shot_id or "")
        except ValueError as exc:
            message = f"guard accept 声明格式错误：{exc}"
            self.audit.log("repair_invalid", message, level="warning",
                           reason=message, category=classify_invalid(message))
            return
        for verdict in verdicts:
            self.audit.log(
                "guard_verdict",
                f"{verdict['shot_id']} 声明刻意 {verdict['warning_type']}"
                f"：{verdict['reason'] or '（无理由）'}",
                level="info", **verdict)

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
        #: 空间尺转正：审计 JSON 统一入口。审核后把稳定 JSON 记入审计日志
        #: （``audit_json`` 事件），外部回放/交付层只消费这一份结构，不再
        #: 直接摸 Blender 对象。``audit_json`` 方法是 BpyShotAuditor 的加法；
        #: 缺省不存在的审核器（FakeAuditor）走原路径，零形状差。
        audit_json = getattr(self.auditor, "audit_json", None)
        if callable(audit_json):
            try:
                payload = audit_json(shot_id)
                self.audit.log(
                    "audit_json",
                    f"{shot_id} 空间尺审计 JSON 已落盘",
                    level="info", shot=shot_id,
                    audit_json=payload)
                results = self.build_summary.get("results")
                if isinstance(results, list):
                    for item in results:
                        if (isinstance(item, dict)
                                and str(item.get("shot_id")) == str(shot_id)):
                            item["audit_json"] = payload
                            break
            except Exception as exc:  # noqa: BLE001 - 审计 JSON 失败不伪造
                self.audit.log(
                    "audit_json_failed",
                    f"{shot_id} 空间尺审计 JSON 失败：{exc}",
                    level="warning", shot=shot_id)
        #: v1.7 空间尺（Ticket 04/06）：把这一镜的几何测量写进
        #: ``build_summary["results"]``（交付层据此产逐镜测量证据）并随
        #: ``shot_audit`` 事件留痕（重放侧据此无 LLM 重读）。只读、不参与
        #: passed/score；找不到对应 result（审核早于构建）就跳过，诚实留缺。
        ruler_measurements = list(
            getattr(result, "ruler_measurements", None) or [])
        if ruler_measurements:
            self._record_ruler_measurements(shot_id, ruler_measurements)
        #: 空间尺转正：逐镜六层评测（含 hard_gates）与测量同一次采样产出，
        #: 一并写进 ``build_summary["results"]``（交付层据此产逐镜审核证据）
        #: 并随 ``shot_audit`` 事件留痕（重放侧据此无 LLM 重读）。与测量
        #: 同纪律：不参与 passed/score，找不到对应 result 就跳过。
        ruler_review = getattr(result, "ruler_review", None)
        if ruler_review is not None:
            self._record_ruler_review(shot_id, ruler_review)
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
                        **(dict(ruler_measurements=[
                                dict(m) for m in ruler_measurements])
                            if ruler_measurements else {}),
                       **({"ruler_review": dict(ruler_review)}
                          if ruler_review is not None else {}),
                       **({"restored": True} if restored else {}),
                       **({"degraded": True} if degraded else {}))
        self._emit("shot_audit",
                   f"{shot_id} {'通过' if result.passed else '未通过'}",
                   shot=shot_id, passed=result.passed)
        #: v1.6 B4（FR-C5）：视锥采样跑过就留一条 ``guard_warning`` 事件
        #: （契约三键 shot_id/warnings/frames_sampled，见 V16_EVENT_FIELDS）；
        #: guard 关闭或空镜（没采样、无告警、无采样错误）就不发，
        #: 历史事件形状一个字节都不变。
        guard_warnings = list(getattr(result, "guard_warnings", None) or [])
        frames_sampled = int(getattr(result, "guard_frames_sampled", 0) or 0)
        sampling_error = getattr(result, "guard_sampling_error", None)
        if guard_warnings or frames_sampled or sampling_error:
            self.audit.log(
                "guard_warning",
                f"{shot_id} 视锥采样 {frames_sampled} 帧，"
                f"告警 {len(guard_warnings)} 条",
                level="warning" if guard_warnings else "info",
                shot_id=shot_id,
                warnings=[item.to_dict() if hasattr(item, "to_dict")
                          else dict(item) for item in guard_warnings],
                frames_sampled=frames_sampled,
                **({"sampling_error": dict(sampling_error)}
                   if sampling_error else {}))
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

    def _record_ruler_measurements(
            self, shot_id: str,
            measurements: List[Dict[str, Any]]) -> None:
        """把这一镜的空间尺测量写进 ``build_summary["results"]``（交付层读它）。

        与 ``_record_vlm_review`` 同一条纪律：找不到对应 result 就跳过——
        交付层在缺失时不写这个键（"没测过"与"测了 0 条"必须分得开）。
        """
        results = self.build_summary.get("results")
        if not isinstance(results, list):
            return
        for item in results:
            if isinstance(item, dict) and str(item.get("shot_id")) == str(shot_id):
                item["ruler_measurements"] = [dict(m) for m in measurements]
                return

    @staticmethod
    def _adversarial_digest_inputs(digest: Any
                                   ) -> "Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], float]":
        """从 ``scene_digest`` 折出对抗审查要的量（软尺读数；缺省不猜）。

        真实形状（``cinema/spatial_digest.py`` 与测试夹具同一构型）：
        ``{"framing": {"subjects": {<名字>: [{frame, in_action_safe,
        in_title_safe, thirds, visible_ratio, ...}]}}, "spatial": ...}``。
        - ``safe_area``：每主体 ``<名字>_in_action_safe`` /
          ``<名字>_in_title_safe`` 布尔（缺失跳过）；
        - ``thirds``：每主体 ``<名字>_thirds`` 非空字符串（缺失跳过）；
        - ``visible_ratio``：各主体首条记录的最小值，无可用数据时 1.0。
        """
        framing: Dict[str, Any] = {}
        safe_area: Dict[str, Any] = {}
        thirds: Dict[str, Any] = {}
        visible_ratio = 1.0
        if not isinstance(digest, dict):
            return framing, safe_area, thirds, visible_ratio
        subjects = (digest.get("framing") or {}).get("subjects") or {}
        if not isinstance(subjects, dict):
            return framing, safe_area, thirds, visible_ratio
        ratios: List[float] = []
        first_seen = False
        for subject, records in subjects.items():
            if not isinstance(records, list) or not records:
                continue
            first = records[0]
            if not isinstance(first, dict):
                continue
            name = str(subject)
            if not first_seen:
                framing.update(first)
                first_seen = True
            if "in_action_safe" in first:
                safe_area[f"{name}_in_action_safe"] = bool(
                    first["in_action_safe"])
            if "in_title_safe" in first:
                safe_area[f"{name}_in_title_safe"] = bool(
                    first["in_title_safe"])
            thirds_value = first.get("thirds")
            if isinstance(thirds_value, str) and thirds_value.strip():
                thirds[f"{name}_thirds"] = thirds_value.strip()
            try:
                ratio = float(first.get("visible_ratio"))
            except (TypeError, ValueError):
                ratio = math.nan
            if math.isfinite(ratio):
                ratios.append(ratio)
        if ratios:
            visible_ratio = min(ratios)
        return framing, safe_area, thirds, visible_ratio

    def _run_adversarial_review(self, shot_id: str,
                                result: AuditResult) -> Dict[str, Any]:
        """对这一镜的这一版做确定性对抗审查（梯度下降的"信号"）。

        只读：安全区/九宫格偏差只记成软参考（不改 passed/score/errors）；
        硬 finding → revise；越轴 → escalate（由既有人工 gate 决断）。
        返回不可变 ``AdversarialReview.to_dict()`` 快照。
        """
        version = int(self._adversarial_versions.get(str(shot_id), 0)) + 1
        self._adversarial_versions[str(shot_id)] = version
        digest = getattr(result, "scene_digest", None)
        framing, safe_area, thirds, visible_ratio = \
            self._adversarial_digest_inputs(digest)
        shot = self._shot_by_id(shot_id)
        intent = (str(getattr(shot, "intent", "") or "")
                  if shot is not None else "")
        review = review_shot(
            shot_id=str(shot_id),
            version=version,
            intent=intent,
            audit_passed=bool(result.passed),
            audit_findings=[*result.errors, *result.warnings],
            framing=framing,
            safe_area=safe_area,
            thirds=thirds,
            visible_ratio=visible_ratio)
        return review.to_dict()

    def _record_ruler_review(self, shot_id: str,
                             review: Dict[str, Any]) -> None:
        """把这一镜的空间尺六层评测写进 ``build_summary["results"]``。

        与 ``_record_ruler_measurements`` 同一条纪律：找不到对应 result 就
        跳过——交付层在缺失时不写这个键（"没审过"与"审了 0 分"必须分得开）。
        """
        results = self.build_summary.get("results")
        if not isinstance(results, list):
            return
        for item in results:
            if isinstance(item, dict) and str(item.get("shot_id")) == str(shot_id):
                item["ruler_review"] = dict(review)
                return

    def _record_adversarial_review(self, shot_id: str,
                                   review: Dict[str, Any]) -> None:
        """把这一镜的对抗审查快照写进 ``build_summary["results"]``（交付层读它）。

        与 ``_record_vlm_review`` 同一条纪律：找不到对应 result 就跳过——
        交付层在缺失时不写这个键（"没审过"与"审了 pass"必须分得开）。
        """
        self._adversarial_reviews[str(shot_id)] = dict(review)
        results = self.build_summary.get("results")
        if not isinstance(results, list):
            return
        for item in results:
            if isinstance(item, dict) and str(item.get("shot_id")) == str(shot_id):
                item["adversarial_review"] = dict(review)
                return

    def _record_shot_version(self, shot_id: str, *, reason: str,
                             result: AuditResult,
                             review: Dict[str, Any]) -> None:
        """每镜每次审核都留一版 ``ShotVersion``（initial/repair/rollback）。

        版本历史是 append-only 的：``ShotVersionHistory.append`` 强制版本号
        从 0 连续、shot_id 一致，旧版本永不改写；``restore_shot_version``
        按版本号返回深拷贝计划，供"可调整可回溯"使用。plan 为空时没有
        可留的快照，直接跳过（不是降级：没有计划就没有版本）。
        """
        if self.plan is None:
            return
        shot_id = str(shot_id)
        history = self._shot_versions.get(shot_id)
        if history is None:
            history = ShotVersionHistory(shot_id)
            self._shot_versions[shot_id] = history
        build_summary = {}
        results = self.build_summary.get("results")
        if isinstance(results, list):
            for item in results:
                if (isinstance(item, dict)
                        and str(item.get("shot_id")) == shot_id):
                    build_summary = dict(item)
                    break
        history.append(ShotVersion(
            shot_id=shot_id,
            version=len(history),
            plan=copy.deepcopy(self.plan.to_dict()),
            build_summary=build_summary,
            audit_summary=result.to_dict(),
            adversarial_summary=dict(review),
            created_at=_now_iso(),
            reason=reason,
        ))
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
        self._audit_and_route(shot_id)

    def _audit_and_route(self, shot_id: str) -> None:
        """审核当前镜并按结果路由（CHECKING 与 PER_SHOT 共用，§3.6.3）。

        判据与阈值一字不动：passed → 前进/自审；失败 → 修复/ReAct/gate；
        回滚/修复基线/降级语义与旧 CHECKING 完全一致。
        """
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
        #: 缺陷 B / U10（T6）：每次审核先过回溯三态——分数轨迹留痕、
        #: 新高更新 best 快照、低分自动回滚到 best（不停生成）。
        #: F14（2026-10-20 final10 实测）：空间尺自动 reframe 的版本
        #: （53→79.5）在普通 CHECKING/REPAIRING 路径下从未进入
        #: ``_react_best``；下一轮 repair 里模型 setup_camera 一重摆，79.5
        #: 版本就被覆盖回 53，而 ``_rollback_repair_if_worse`` 只回计划不回
        #: 场景（lens 36mm 丢失），高分永久丢失。reframe 后的这次重审正是
        #: 高分版本诞生的时刻：若该镜已做过空间尺 reframe 且尚未建立 best，
        #: 先把它登记为基线（v1），此后低分审核自动 revert 回这份世界快照。
        reframed_shots = set(getattr(self, "_ruler_reframed_shots", None)
                             or ())
        if (str(shot_id) in reframed_shots
                and str(shot_id) not in self._react_best):
            self._record_react_score(shot_id, result, baseline=True)
            decision = None
        else:
            decision = self._record_react_score(shot_id, result)
        #: D1 对抗审查：**每次审核都出一版**（pass 也出），软尺偏差只记录、
        #: 不改判；越轴 escalate 由下方既有 gate 决断。事件与交付记录先于
        #: 路由，保证"这一版为什么这样走"永远有据可查。
        review = self._run_adversarial_review(shot_id, result)
        result.adversarial_review = review
        self.audit.log(
            "adversarial_review",
            f"{shot_id} 对抗审查 v{review['version']}: "
            f"{review['disposition']}",
            level="info" if review["disposition"] == "pass" else "warning",
            shot_id=str(shot_id),
            version=int(review["version"]),
            disposition=str(review["disposition"]),
            issues=list(review["issues"]),
            rationale=str(review["rationale"]))
        self._record_adversarial_review(shot_id, review)
        #: D1 逐镜版本历史：**每次审核都留一版**（initial/repair/rollback），
        #: 与对抗审查快照同一节奏落账，供 `restore_shot_version` 回溯。
        #: 用函数开头捕获的局部 `restored`（`_just_rolled_back` 已重置）。
        self._record_shot_version(
            shot_id,
            reason=("rollback" if restored
                    else ("repair" if self._repair_attempts > 0
                          else "initial")),
            result=result,
            review=review)
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
            # 空间尺转正：旧审核通过后，再查六层评测的 H1–H6 硬门。命中即
            # 进入确定性 reframe / 定向修复回路（同一镜最多自动 reframe 一次
            # 防振荡）；硬门**不改 passed/score**，只做新增阻断，保证既有
            # 4101 条验收口径不变。
            review = getattr(result, "ruler_review", None) or {}
            gates = set(review.get("hard_gates") or [])
            if gates:
                self.audit.log(
                    "ruler_gate_blocked",
                    f"{shot_id} 空间尺硬门命中：{sorted(gates)}，进入修复回路",
                    level="warning", shot_id=shot_id,
                    hard_gates=sorted(gates))
                self._emit("ruler_gate_blocked",
                           f"{shot_id} 空间尺硬门 {sorted(gates)}",
                           shot_id=shot_id, hard_gates=sorted(gates))
                if self._ruler_camera_repair_enabled() and \
                        self._auto_reframe_from_ruler(shot_id, result):
                    self._pending_audit = None
                    self._transition(DriverState.CHECKING)
                    return
                self._pending_audit = result
                self._transition(DriverState.REPAIRING)
                return
            #: U10「过分数采用」：本次审核已过线（score > PASS_SCORE 且规则
            #: 层通过）→ 立即收尾，不让 Level 2 自我审核把已采用镜头重新
            #: 打开。final9 实测 shot_002 v5=80.7 adopt 后仍被自我审核
            #: reopen（"未表达意图"），随后 v6=79.5 revert、3 轮无新高被记
            #: failed（best=80.7 却报"未达到 80 分门槛"）——违反 U10。
            if decision is not None and decision.adopted:
                self.audit.log(
                    "react_adopted_terminal",
                    f"{shot_id} 审核 {decision.best_score:g} 分过线采用，"
                    f"立即记为通过并前进",
                    shot=shot_id, score=decision.best_score)
                self._emit("react_adopted_terminal",
                           f"{shot_id} 过线采用", shot=shot_id,
                           score=decision.best_score)
                self._mark_terminal(shot_id, "passed")
                self._advance_shot()
                return
            if self._should_self_review(shot_id):
                self._pending_review = shot_id
                self._transition(DriverState.REVIEWING)
                return
            self._mark_terminal(shot_id, "passed")
            self._advance_shot()
            return
        # 正式内置空间尺：相机几何告警先走确定性的 reframe，再把结果交给
        # 原有 LLM 修复回路。这样空间尺不是只记录处方，而是能完成一次
        # “观测→处方→执行→复测”的闭环；失败仍保留原有回路，不降低验收。
        if self._ruler_camera_repair_enabled() and self._auto_reframe_from_ruler(
                shot_id, result):
            self._pending_audit = None
            self._transition(DriverState.CHECKING)
            return
        #: 缺陷 D / T6：单镜连续 3 轮无新高 → 记 failed 并**继续下一镜**
        #: （U6/U1：拦截错误后回溯而不是停止，白模预演视频一定要生成）。
        #: R2-F11 追加：连续一整回合纯只读（≥ react_max_steps 个只读步）
        #: = 该镜无实质进展，与"连续 3 轮无新高"同语义触发失败；计数留在
        #: ``_react_readonly_rounds``（只读步），不改 score 侧 no_gain。
        readonly_exhausted = (
            shot_id in self._react_best
            and self._react_readonly_rounds.get(shot_id, 0)
            >= self._react_max_steps())
        if (self._react_no_gain.get(shot_id, 0) >= 3
                and shot_id in self._react_best) or readonly_exhausted:
            self.audit.log(
                "react_terminal_fail",
                f"{shot_id} 连续 3 轮无新高"
                f"{'或一整回合纯只读' if readonly_exhausted else ''}，"
                f"记为失败并继续下一镜",
                shot=shot_id,
                no_gain=self._react_no_gain.get(shot_id, 0),
                readonly_steps=self._react_readonly_rounds.get(shot_id, 0),
                best_score=self._react_best[shot_id].get("score"))
            self._emit("react_terminal_fail",
                       f"{shot_id} 精修无解，标记失败并继续",
                       shot=shot_id)
            self._mark_terminal(shot_id, "failed")
            self._advance_shot()
            return
        #: R2-F11：每镜 ReAct 总回合上限（默认 4，0=关）。真跑
        #: 20261020-market-real-final8 里 shot_002 在 40.8–60.2 分间微涨
        #: 震荡，连续无新高判据被 new_high 清零、永远到不了 3，墙钟被单镜
        #: 耗尽。到达上限仍未过 80 分 → 记失败继续下一镜（不降 80 分门槛；
        #: U6/U1：拦截错误后回溯而不是停止，白模预演视频一定要生成）。
        max_rounds = self._react_max_rounds()
        if (max_rounds > 0
                and self._react_round_counts.get(shot_id, 0) >= max_rounds
                and shot_id in self._react_best
                and composition_decision(
                    self._react_best[shot_id].get("score"))["status"] != "pass"):
            self.audit.log(
                "react_round_exhausted",
                f"{shot_id} ReAct 总回合 {max_rounds} 用尽仍未过 "
                f"{PASS_SCORE} 分（best="
                f"{self._react_best[shot_id].get('score')}），记为失败继续下一镜",
                shot=shot_id,
                rounds=self._react_round_counts.get(shot_id, 0),
                best_score=self._react_best[shot_id].get("score"))
            self._emit("react_round_exhausted",
                       f"{shot_id} 精修回合用尽，标记失败并继续",
                       shot=shot_id,
                       rounds=self._react_round_counts.get(shot_id, 0))
            self._mark_terminal(shot_id, "failed")
            self._advance_shot()
            return
        # 未通过的镜头绝不能因为固定修复次数而伪装成完成并前进。
        # B4 定向修复优先；已有至少一次修复仍未通过时，进入 ReAct 观察/调整回合。
        # ``max_repairs_per_shot`` 不再是终止条件；真正的停止边界是预算、墙钟、
        # 取消或人工决定，它们都会落 resume checkpoint。
        # （转正批的 reframe 前导已在上方优先执行；reframe 失败或与几何无关
        # 时回到这里，仍不降级、不因构建而伪终态。）
        if self._repair_attempts > 0 and self._should_start_react(shot_id, result):
            self._start_react(shot_id, result)
            return
        # 180-degree violations are explicitly human-gated when configured.
        # The gate is an escalation policy, not a fixed repair-count cutoff.
        if self._repair_attempts > 0 and self._gate_enabled(
                "human_gate_on_axis_violation") and any(
                    item.rule == "R001" for item in result.errors):
            self._request_gate(
                GateRequest(kind="axis_violation",
                            title=f"{shot_id} 越轴，等待人工裁决",
                            detail=result.format_for_llm(),
                            payload={"shot_id": shot_id}),
                resume=DriverState.CHECKING)
            return
        self._pending_audit = result
        self._transition(DriverState.REPAIRING)

    def _ruler_camera_repair_enabled(self) -> bool:
        """空间尺相机几何闭环开关（与计划级接缝同源）。"""
        return self._ruler_enabled()

    def _ruler_enabled(self) -> bool:
        """空间尺总开关；config 缺省或 ``ruler`` 段缺省时按默认启用（转正）。"""
        cfg = getattr(self.config, "ruler", None)
        if cfg is None:
            return True
        return bool(getattr(cfg, "enabled", True))

    def _auto_reframe_from_ruler(self, shot_id: str,
                                 result: AuditResult) -> bool:
        """执行一次可回溯的相机处方；同一镜头最多一次，避免修复振荡。"""
        done = getattr(self, "_ruler_reframed_shots", None)
        if done is None:
            done = self._ruler_reframed_shots = set()
        if shot_id in done:
            return False
        warnings = list(getattr(result, "guard_warnings", None) or [])
        kinds = {str(item.get("type") if isinstance(item, dict)
                     else getattr(item, "type", "")) for item in warnings}
        #: R2 缺口 #3（2026-10-19）：headroom_off 也进入确定性 reframe。
        #: 真跑 evidence 20261019-r2-market-coin-full 显示 shot_001 构图
        #: 53 → 79.5 只靠 edge_clip/framing 自动 reframe，最后 0.5 分差在
        #: headroom_off（头顶留白过多），但它不在触发集合里，只能等 LLM
        #: 修复——真跑里修复请求 190s 未返回被 wall 掐断，分数停在 79.5。
        #: headroom_off 是 warning 级且有确定动作（收紧景别/抬高机位），
        #: 自动 reframe 属确定性修复，不是降级。thirds_deviation 保持不
        #: 自动 reframe：它是 info 级，且模型可用 ACCEPT 声明刻意偏心构图，
        #: 盲改会误伤导演意图。
        if not kinds.intersection({"subject_not_visible", "edge_clip",
                                   "framing_too_tight", "framing_too_loose",
                                   "subject_out_of_frame", "occlusion",
                                   "headroom_off"}):
            return False
        shot = next((s for s in (self.plan.shots if self.plan else [])
                     if str(s.shot_id) == str(shot_id)), None)
        if shot is None:
            return False
        camera = dict(getattr(shot, "camera", None) or {})
        old_lens = float(camera.get("lens") or 50.0)
        for built in reversed(list(
                (getattr(self, "build_summary", None) or {}).get("results")
                or [])):
            if not isinstance(built, dict):
                continue
            if str(built.get("shot_id") or "") != str(shot_id):
                continue
            live_lens = built.get("lens")
            try:
                candidate = float(live_lens)
            except (TypeError, ValueError):
                break
            if math.isfinite(candidate) and candidate > 0.0:
                old_lens = candidate
            break
        #: headroom_off 归收紧分支：留白过多 = 主体偏小，1.28 收紧景别
        #: （与 framing_too_loose 同语义）；thirds_deviation 不在此触发。
        if kinds.intersection({"subject_not_visible", "edge_clip",
                               "framing_too_tight", "subject_out_of_frame",
                               "occlusion"}):
            new_lens = round(max(18.0, old_lens * 0.72), 3)
        else:
            new_lens = round(min(180.0, old_lens * 1.28), 3)
        try:
            outcome = self.registry.execute("reframe", {
                "shot_id": str(shot_id), "shot_type": str(shot.shot_type),
                "lens": new_lens, "preserve_pose": True})
        except Exception as exc:  # pragma: no cover - bpy boundary
            self.audit.log("spatial_ruler_reframe_failed",
                           f"{shot_id} 空间尺 reframe 失败：{exc}",
                           level="warning", shot=shot_id)
            return False
        if not outcome.ok:
            self.audit.log(
                "spatial_ruler_reframe_failed",
                f"{shot_id} 空间尺 reframe 未执行：{outcome.error or outcome.content}",
                level="warning", shot=shot_id)
            return False
        done.add(shot_id)
        #: 转正：把已执行处方按 prescription_id（与观测默认处方同构：
        #: ``p_{shot_id}_{kind}``）记录，供观测折档合并。合并是补丁语义，
        #: 驱动侧不给 precondition/postcondition/operation 等字段时，
        #: 观测层沿用默认处方版本，只有 applied/参数被覆盖。
        from .ruler_observation import guard_kind_metric

        for kind in sorted(kinds):
            metric = guard_kind_metric(kind)
            applied = {
                "prescription_id": f"p_{shot_id}_{kind}",
                "shot_id": str(shot_id),
                "operation": "reframe",
                "parameters": {"reason": kind, "lens_before": old_lens,
                               "lens_after": new_lens},
                "precondition_measurement_ids": [
                    f"m_{shot_id}_{metric}"],
                "postcondition_measurement_ids": [
                    f"m_{shot_id}_composition_score"],
                "postcondition": (
                    "全镜 visible_ratio > 0 且 composition_score > "
                    f"{COMPOSITION_PASS_TEXT}"),
                "applied": True, "applied_at": "runtime",
                "waived": False, "waive_reason": "",
            }
            existing = [p for p in self._ruler_applied_prescriptions
                        if p.get("prescription_id")
                        != applied["prescription_id"]]
            self._ruler_applied_prescriptions = existing + [applied]
        self._mark_repair_applied(applied=True)
        self.audit.log("spatial_ruler_reframe_applied",
                       f"{shot_id} 空间尺自动 reframe：{old_lens:g}→{new_lens:g}mm",
                       shot=shot_id, operation="reframe", old_lens=old_lens,
                       new_lens=new_lens, warning_types=sorted(kinds))
        return True

    def _advance_shot(self) -> None:
        done = ""
        if self._shot_queue:
            done = self._shot_queue.pop(0)
            #: 这一镜结束了：它的修复基线（含一份计划快照）不再需要，
            #: 留着只会让 64 镜的跑里堆 64 份计划副本。
            self._repair_baseline.pop(str(done), None)
            self._decision_trees.pop(str(done), None)
            #: F13：该镜的墙钟起点随换镜清理（下一镜重新计份额）。
            self._shot_start_wall.pop(str(done), None)
            #: 版本历史（_shot_versions）**保留**：可回溯是本插件的核心能力，
            #: 换镜不清理，只随 resume checkpoint 增长/恢复。
            self._finished_shots.append(done)
        self._repair_attempts = 0
        self._repair_turns = 0
        self.repair_messages = []
        next_shot_id = ""
        if self._shot_queue:
            self._current_shot_id = self._shot_queue[0]
            next_shot_id = self._current_shot_id
        if done:
            terminal_status = str(
                self._shot_terminal.get(str(done)) or "unknown")
            if terminal_status == "passed":
                outcome = "通过"
            elif terminal_status == "finished":
                outcome = "模型声明完成但审核未过，待复核"
            else:
                outcome = f"以 {terminal_status} 终态推进"
            event = {
                "shot_id": str(done),
                "next_shot_id": next_shot_id,
                "terminal_status": terminal_status,
                "quality_pass": terminal_status == "passed",
                "decision_trees_evicted": True,
            }
            self.audit.log("shot_advanced",
                           f"{done} {outcome}，移入下一镜"
                           f"（{next_shot_id or '无'}）",
                           **event)
            self._emit("shot_advanced", f"{done} 已前进", **event)
        self._transition(self._resume_per_shot_or_checking())

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
        shot = next((item for item in (self.plan.shots if self.plan else [])
                     if item.shot_id == shot_id), None)
        max_steps = (int(getattr(self.config.orchestration,
                                 "react_max_steps", 6))
                     if self.config is not None else 6)
        return should_react(shot, result, repairs_exhausted=True,
                            max_steps=max_steps)

    def _start_react(self, shot_id: str, result: AuditResult) -> None:
        """进入 B5：开一段有上限的工具对话，让模型自己边看边调。"""
        self._react_round_counts[shot_id] = (
            self._react_round_counts.get(shot_id, 0) + 1)
        #: G2 #8：ReAct 的收尾工具 finish_shot 必须在工具表里。默认注册表自带，
        #: 但调用方可以塞自定义注册表（测试/嵌入用法）：进入 B5 前补齐三个
        #: 控制工具（幂等），于是 build_react_payload 的"缺 finish_shot 就报错"
        #: 守卫只拦**直接误用**，驱动器自己永不发出缺收尾工具的载荷。
        register_control_tools(self.registry)
        #: 缺陷 B / T6：精修阶段额外注册 revert_shot（回到最高分版本）；
        #: 重复调用幂等，不进计划/修复阶段的工具表。
        try:
            from ..layer3_engine.tool_bindings import register_react_tools
            register_react_tools(self.registry)
        except Exception:  # noqa: BLE001 - 纯 pytest 无 bpy：零行为差
            pass
        self._react_done.add(shot_id)          # 仅诊断"曾进入"，不再限制重入
        self._react_shot = shot_id
        self._react_steps = 0
        #: 缺陷 B / U10：进入 B5 时把当前审核记成版本 1（best 基线），
        #: 后续每一轮复核结果由 :meth:`_record_react_score` 三态裁定。
        baseline = float(getattr(result, "score", 0.0) or 0.0)
        self._record_react_score(shot_id, result, baseline=True)
        shot = next((item for item in (self.plan.shots if self.plan else [])
                     if item.shot_id == shot_id), None)
        memory = render_shot_memory(
            shot_memory(self.plan, done=self._finished_shots))
        #: G2 判据 #8：先装**这一镜**的逐镜 schema——载荷构造与后续每一轮
        #: ``registry.execute`` 校验同一份枚举（finish_shot 守卫与提示词不变）。
        self._apply_shot_schemas(shot_id)
        payload = build_react_payload(
            shot, result, scene_state=self._scene_state_text(),
            registry=self.registry, max_steps=self._react_max_steps(),
            roster=self._cast_roster(),
            max_tokens=self._llm_max_tokens())
        if memory:
            payload.messages[0].content += "\n\n" + memory
        self._react_messages = list(payload.messages)
        self.audit.log("react_started", f"{shot_id} 进入镜头精修回合",
                       shot=shot_id, max_steps=self._react_max_steps())
        self._emit("react_started", f"{shot_id} 精修", shot=shot_id,
                   max_steps=self._react_max_steps())
        self._start_react_turn()

    def _react_max_steps(self) -> int:
        # 单段 ReAct 有界，结束后必须重新审核；未通过就可再次进入，不构成
        # 每镜总修复次数上限。全局调用/墙钟预算与取消负责安全停止。
        if self.config is None:
            return 6
        return max(1, int(getattr(self.config.orchestration,
                                  "react_max_steps", 6)))

    def _react_max_rounds(self) -> int:
        """每镜 ReAct 总回合上限；``0`` = 关（保持旧行为）。"""
        if self.config is None:
            return 4
        return max(0, int(getattr(self.config.orchestration,
                                  "react_max_rounds", 4)))

    def _start_react_turn(self) -> None:
        """把当前 ReAct 对话裁到上下文上限内，再发起下一轮。"""
        limit = DEFAULT_CONTEXT_WINDOW_TOKENS
        if self.config is not None:
            limit = int(getattr(self.config.orchestration,
                                "context_window_tokens",
                                DEFAULT_CONTEXT_WINDOW_TOKENS))
        #: 压缩摘要预算：留出固定 20% 窗口给"被裁旧对话的关键信息摘要"，
        #: 剩余窗口才是保留对话的预算——保证注入摘要后总 token 仍 ≤ 窗口
        #: （窗口纪律：压缩不是把窗口挤爆的借口）。
        summary_budget = max(1, int(limit * 0.2))
        kept, dropped = trim_messages(self._react_messages,
                                      limit - summary_budget)
        if dropped:
            compressed = self._inject_compressed(
                kept, dropped, limit=limit, summary_budget=summary_budget)
            self.audit.log("context_trimmed",
                           f"裁剪 {len(dropped)} 条旧观察"
                           f"，压缩为 {len(compressed)} 条关键信息摘要",
                           level="warning", **budget_report(kept, limit))
            self._react_messages = compressed
        payload = ChatPayload(messages=list(self._react_messages),
                              tools=self.registry.openai_schemas(),
                              #: G2 #8：实际发出去的每一轮 ReAct 请求都要求
                              #: 工具调用（build_react_payload 的载荷只贡献
                              #: messages，真正的请求在这里构造）；收尾由
                              #: finish_shot 声明，无工具调用才是例外路径。
                              tool_choice=ToolChoice.REQUIRED,
                              temperature=0.3, purpose=Purpose.REACT,
                              max_tokens=self._llm_max_tokens(),
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
        self._decision_trees.clear()
        # React 结束只代表模型停止本轮工具对话，不代表镜头通过。
        # 返回审核；若仍不通过，_audit_and_route 会继续当前镜修复循环。
        self._transition(DriverState.CHECKING)

    def _record_react_tool_progress(self, tool_calls) -> None:
        """R2-F2：按一轮 ReAct 的工具集合记录只读空转（诊断）。

        R2 ticket 05 原实现把"只读轮 +1 / 混合轮清零"与回溯"连续无新高"
        写进同一个 ``_react_no_gain``——真跑中模型每轮先调 ``setup_camera``
        （修改类）再得相同分数，score 侧累计被反复清零，"连续 3 轮无新高 →
        react_terminal_fail"永远到不了 3，墙钟被单镜耗尽
        （evidence/20261019-r2-market-coin-accept-32k-v2）。

        现在：只读步只累积 ``_react_readonly_rounds``（``repair_no_progress``
        事件照记，排障可见）；终态计数完全由 ``_record_react_score`` 的审核
        裁定负责——只读轮以"场景未变"收场，审核必然 tie/revert，自然计入
        "无新高"。修改步只打断只读连续（清只读计数），不碰 score 计数。

        R2-F11 追加：final8 真跑里 shot_002 每轮 ReAct 都以"只读查询 + 零
        修改"收场，但 ``_record_react_score`` 只在审核轮发生（每轮 6 步
        之后才审一次），而模型在 6 步内反复查询同一个 check_composition
        ——只读空转本身不触发任何终态。这里把连续只读**步**数留在
        ``_react_readonly_rounds`` 里，终态路由单独判"连续一整回合纯只读
        （≥ react_max_steps 步）= 无实质进展"；**绝不写进**
        ``_react_no_gain``（score 侧计数只由审核裁定，避免双重计数）。
        """
        names = [str(call.function.name) for call in tool_calls or []]
        if not names or not self._react_shot:
            return
        if all(name in DEFAULT_QUERY_TOOLS for name in names):
            self._react_readonly_rounds[self._react_shot] = (
                self._react_readonly_rounds.get(self._react_shot, 0) + 1)
            count = self._react_readonly_rounds[self._react_shot]
            self.audit.log("repair_no_progress",
                           f"{self._react_shot} ReAct 轮全只读（{'/'.join(names)}），"
                           f"无实质改动，累计无新高 {count} 轮",
                           level="warning", shot=self._react_shot,
                           tools=names, no_gain=count)
            self._emit("repair_no_progress", f"{self._react_shot} 只读轮无进展",
                       shot=self._react_shot, tools=names)
        else:
            self._react_readonly_rounds[self._react_shot] = 0

    def _react_readonly_auto_reframe(self, shot_id: str) -> bool:
        """R2-F2 兜底：全只读轮触发确定性相机处方。

        模型在 ReAct 里反复"看"（get_scene_state/check_*/search_knowledge）
        却没动手时，用空间尺做一次**确定性** reframe（同一镜最多一次，
        可回溯），把场景真正改起来再回 CHECKING 复测——"用程序为尺子 +
        随机应变"，不是固定处方：reframe 的量来自最近审计的 guard_warnings。
        返回 True 表示已执行处方（调用方应结束本轮 ReAct 回审核复测）。
        """
        if not self._react_readonly_rounds.get(shot_id, 0):
            return False
        if not self._ruler_camera_repair_enabled():
            return False
        done = getattr(self, "_ruler_reframed_shots", None) or set()
        if shot_id in done:
            return False
        last = None
        for item in reversed(self.audit_results):
            if str(getattr(item, "target", "")) == str(shot_id):
                last = item
                break
        if last is None:
            return False
        if not self._auto_reframe_from_ruler(shot_id, last):
            return False
        self.audit.log(
            "react_readonly_reframe",
            f"{shot_id} 全只读轮触发空间尺自动 reframe，回 CHECKING 复测",
            shot=shot_id, level="info")
        return True

    def _wire_world_state(self) -> None:
        """R11：把 ``runtime_world_state.json`` 的落盘路径挂到当前场景上下文。

        构建器先建 SceneContext 再刷新，但此时还没拿到运行目录——路径由
        驱动器在构建成功后补登记（审计目录在 run 开始时就已知），并立即
        刷新一次，从此 agent 工具改动/回滚都会实时重写同一份 JSON。
        """
        try:
            from ..layer3_engine.scene_context import get_context
            context = get_context()
            if context is None:
                return
            target = world_state_target_path(self.audit.directory)
            if target is None:
                return
            context.world_state_path = str(target)
            from ..layer3_engine.world_state import refresh_world_state
            refresh_world_state(context)
        except Exception:  # noqa: BLE001 - 纯 pytest / 无 bpy：如实跳过
            return

    def _collect_world_state(self, shot_id: str):
        """R11：采集当前场景状态作为 best 快照；无 bpy/无场景时返回 None。

        快照也登记进 ``SceneContext.react_best_snapshot``（模型主动调
        revert_shot 时同样能拿到它）。
        """
        shot_id = str(shot_id)
        try:
            from ..layer3_engine.scene_context import get_context
            from ..layer3_engine.world_state import (
                collect_world_state,
                write_world_state,
            )
            context = get_context()
            if context is None:
                return None
            payload = collect_world_state(context)
            write_world_state(context, payload)
            context.react_best_snapshot[shot_id] = payload
            return payload
        except Exception:  # noqa: BLE001 - 纯 pytest / 无 bpy：快照如实缺
            return None

    def _revert_to_best(self, shot_id: str) -> None:
        """把场景物理回滚到最高分版本（D4：回滚后立即给下一轮，不停生成）。"""
        shot_id = str(shot_id)
        best = self._react_best.get(shot_id) or {}
        payload = best.get("world_state")
        if not payload:
            self.audit.log(
                "revert_skipped",
                f"{shot_id} 无世界状态快照（纯层/无 bpy），物理回滚跳过",
                level="warning", shot=shot_id, reason="no_world_snapshot")
            return
        try:
            from ..layer3_engine.scene_context import get_context
            from ..layer3_engine.tool_bindings import restore_world_snapshot
            context = get_context()
            notes = restore_world_snapshot(payload, context)
            if context is not None:
                context.react_best_snapshot[shot_id] = payload
            self.audit.log(
                "revert_applied",
                f"{shot_id} 已回滚到最高分版本（{len(notes)} 类恢复），JSON 已刷新",
                shot=shot_id, best_score=best.get("score"),
                restored=notes)
            self._emit("revert_applied", f"{shot_id} 已回滚到最高分版本",
                       shot=shot_id, best_score=best.get("score"))
        except Exception as exc:  # noqa: BLE001
            self.audit.log(
                "revert_failed", f"{shot_id} 物理回滚失败：{exc}",
                level="warning", shot=shot_id,
                error=f"{type(exc).__name__}: {exc}")

    def _record_react_score(self, shot_id: str, result: AuditResult, *,
                            baseline: bool = False):
        """缺陷 B / U10：一版审核分数进回溯三态并留痕。

        ``baseline=True``（进入 B5 时的当前分数）记成版本 1 / best 基线；
        其余每轮复核按"过分数采用 / 新高保留 / 低分回溯"裁定。返回
        ``BacktrackDecision`` 或 ``None``（分数缺失 / 未进入精修）。
        """
        from ..contracts.backtrack import backtrack_three_state

        shot_id = str(shot_id)
        score_raw = getattr(result, "score", None)
        if score_raw is None:
            return None
        score = float(score_raw)
        if baseline:
            if shot_id in self._react_best:
                return None
            self._react_best[shot_id] = {
                "score": score, "version": 1,
                "world_state": self._collect_world_state(shot_id)}
            self._react_no_gain[shot_id] = 0
            self._react_scores[shot_id] = [{
                "version": 1, "score": score, "disposition": "new_high",
                "summary": "基线（进入精修）"}]
            self.audit.log("react_score",
                           f"{shot_id} v1 {score:.1f} → 基线（new_high）",
                           shot=shot_id, version=1, score=score,
                           disposition="new_high")
            return None
        if shot_id not in self._react_best:
            return None
        best = self._react_best[shot_id]
        decision = backtrack_three_state(
            score, best_score=best.get("score"),
            no_gain=self._react_no_gain.get(shot_id, 0))
        version = len(self._react_scores.get(shot_id, [])) + 1
        self._react_scores.setdefault(shot_id, []).append({
            "version": version, "score": score,
            "disposition": decision.disposition,
            "summary": f"best={decision.best_score:g}",
        })
        if decision.disposition in ("new_high", "adopt"):
            self._react_best[shot_id] = {
                "score": decision.best_score, "version": version,
                "world_state": self._collect_world_state(shot_id)}
            self._react_no_gain[shot_id] = 0
        else:
            if decision.should_revert:
                self._revert_to_best(shot_id)
            self._react_no_gain[shot_id] = decision.no_gain
        self.audit.log(
            "react_score",
            f"{shot_id} v{version} {score:.1f} → {decision.disposition}"
            f"（best={decision.best_score:g}，无新高 "
            f"{self._react_no_gain.get(shot_id, 0)} 轮）",
            shot=shot_id, version=version, score=score,
            disposition=decision.disposition, best_score=decision.best_score,
            no_gain=self._react_no_gain.get(shot_id, 0))
        return decision

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
            scene_state=self._scene_state_text(), temperature=temperature,
            max_tokens=self._llm_max_tokens(),
            prompt_conflict_check=bool(
                getattr(getattr(self.config, "guard", None),
                        "prompt_conflict_check", False)),
            measured_camera=(
                (self.audit_results[-1].measured_camera
                 if self.audit_results and self.audit_results[-1] is not None
                 and getattr(self.audit_results[-1], "measured_camera", None)
                 else None)))
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
                                    "notes": verdict.notes,
                                    **({"prompt_conflict": verdict.prompt_conflict}
                                       if verdict.prompt_conflict else {})})
        if verdict.prompt_conflict:
            #: v1.7 J4（R025）：LLM 裁决层报的文本矛盾只记录＋warning，
            #: 不参与 passed/score（校验层不做语义判断，红线 R-V 不升格）。
            self.audit.log(
                "R025", f"{shot_id} 镜头 prompt 文本与实测运镜矛盾："
                        f"{verdict.prompt_conflict}",
                level="warning", shot=shot_id)
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
            self._transition(self._resume_per_shot_or_checking())
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
        #: G2 判据 #8：先装**这一镜**的逐镜 schema（emit_shot_draft ＋ 角色
        #: 工具），载荷与 registry.execute 才会校验同一份枚举。
        self._apply_shot_schemas(str(self._current_shot_id))
        #: 空间理解快照（Ticket 08）：设计 vs 实测偏差块注入修复提示。
        #: 没有 diff（未采样/离线）时零形状差——build_repair_payload 只在
        #: 非空块时追加，与改动前的提示逐字节一致。
        diff_block = ""
        if self._spatial_diff is not None:
            from ..cinema.spatial_diff import render_diff_block
            diff_block = render_diff_block(self._spatial_diff, max_chars=800)
        payload = build_repair_payload(
            audit, self.registry,
            scene_state=self._scene_state_text(),
            shot=self._shot_by_id(self._current_shot_id),
            roster=self._cast_roster(),
            #: 把**本次要修的镜头**写进提示词：场景摘要里的"当前镜头"是
            #: `SceneContext.current_shot_id`（构建时落在第一镜），实测 long10
            #: 里模型照抄它，把 `emit_shot_draft` 的 shot_id 写成 shot_001。
            shot_id=str(self._current_shot_id),
            temperature=temperature,
            max_tokens=self._llm_max_tokens(),
            diff_block=diff_block)
        #: 对抗审查的解释/建议回流修复提示（梯度下降的"信号"）。
        #: 审查只作为建议来源，不新增任何硬门；payload 结构保持不变。
        review = getattr(audit, "adversarial_review", None)
        if isinstance(review, dict) and review:
            review_text = _adversarial_review_text(review)
            if review_text:
                system = payload.messages[0]
                system.content = str(system.content) + "\n\n" + review_text
        #: F14 辅助（final10 实测）：把该镜最高分版本注入修复提示，防止模型
        #: 用 setup_camera 整位重摆覆盖高分版本（空间尺 reframe 的 79.5 分
        #: 36mm 版本被 setup_camera 50mm 覆盖回 53）。只提示、不改任何门限；
        #: 无 best 或 best 不高于本次时零形状差。
        best = self._react_best.get(str(self._current_shot_id))
        if best:
            best_score = float(best.get("score") or 0.0)
            audit_score = float(getattr(audit, "score", 0.0) or 0.0)
            if best_score > audit_score:
                system = payload.messages[0]
                system.content = (
                    str(system.content)
                    + f"\n\n【高分保留】当前镜头已有最高分版本 "
                      f"best={best_score:g}（本次 {audit_score:g}）。请在"
                      f"最高分版本基础上微调：优先 move_camera / reframe 传"
                      f"具体增量（距离/焦段/高度），不要用 setup_camera "
                      f"整位重摆覆盖它——若确实需要重摆，先 revert_shot "
                      f"回到 best 再基于它调整。")
        #: 工具集与对话都要留住：延续轮必须用**同一套**工具（含收窄），
        #: 并且把这一轮的工具观测带回模型。
        self._repair_tools = list(payload.tools)
        if self._repair_attempts:
            #: 第 2 次尝试接着上一轮的修复对话往下谈（同一镜内），不推倒重来：
            #: 上一轮模型查到的观测、看过的审计、收到的循环警告，都是它这一轮
            #: 判断的依据；丢掉它们等于让它重新踩一遍同一个坑。镜头换了
            #: （`_advance_shot`）才会清空。
            self.repair_messages.extend(payload.messages)
            window = int(getattr(self.config.orchestration,
                                 "context_window_tokens",
                                 DEFAULT_CONTEXT_WINDOW_TOKENS)
                         if self.config is not None
                         else DEFAULT_CONTEXT_WINDOW_TOKENS)
            summary_budget = max(1, int(window * 0.2))
            kept, dropped = trim_messages(
                self.repair_messages,
                window - summary_budget)
            if dropped:
                compressed = self._inject_compressed(
                    kept, dropped, limit=window, summary_budget=summary_budget)
                self.audit.log("context_trimmed",
                               f"修复对话裁剪 {len(dropped)} 条旧观察"
                               f"，压缩为 {len(compressed)} 条关键信息摘要",
                               level="warning")
                self.repair_messages = compressed
            else:
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
        # 没有拿到任何可用观测时，继续重放同一失败没有信息增益；返回审核，
        # 由 repair/react 策略选择下一种动作。这里没有固定总轮次上限。
        if not self._repair_queries_ok:
            return False
        # 同一对话的观测回灌仍需防止无进展空转；这不是镜头修复总次数上限。
        # 新一轮 repair attempt 会重新装载审计与场景状态，镜头仍不前进。
        if self._repair_turns + 1 >= self._repair_turn_limit():
            return False
        if self._tool_calls >= self.limits.max_tool_calls:
            return False
        return self.budget.allow_llm_call("repair")

    def _compress_dropped(self, dropped: Sequence, *,
                          max_tokens: Optional[int] = None) -> List[Message]:
        """把被裁掉的旧对话压缩成一条关键信息摘要（用户裁决：生成关键
        信息文档当缓存，压缩上下文；不直接把旧观察丢掉）。

        ``dropped`` 是 ``trim_messages`` 裁掉的旧消息；压缩产物是单条
        SYSTEM 摘要消息，注入到保留对话的最前面（system 之后），让模型
        仍能看到"修这一镜还需要的关键要点"，但不再携带原文与重复调用 ID。
        """
        if not dropped:
            return []
        return compress_messages(dropped, max_tokens=max_tokens)

    def _inject_compressed(self, kept: List[Message], dropped: Sequence, *,
                           limit: int, summary_budget: int) -> List[Message]:
        """把被裁旧对话的压缩摘要注入保留对话；装不下就不注入（守窗口纪律）。

        ``kept`` 已经按 ``limit - summary_budget`` 裁好；这里尝试注入
        ``compress_messages(dropped, max_tokens=summary_budget)`` 到 system
        之后。若注入后总 token 仍超 ``limit``（极小窗口下 system 几乎占满，
        摘要装不下），退回纯裁剪——压缩是"尽量保留关键信息"，不是把窗口挤爆
        的借口。返回最终对话。
        """
        if not dropped:
            return kept
        compressed = self._compress_dropped(dropped, max_tokens=summary_budget)
        if not compressed:
            return kept
        candidate = kept[:1] + compressed + kept[1:]
        if count_tokens(candidate) <= limit:
            return candidate
        return kept

    def _continue_repair(self) -> None:
        """同一**次**修复尝试里的下一轮：把上一轮的工具观测真的发回给模型。

        `self.repair_messages` 此前是一张**从来不发回**的草稿单
        （`_dispatch_tool_calls` 往里写、没人读）⇒ 模型在修复回合里调
        `get_scene_state` / `check_composition` 拿到的观测全部丢掉，它只能
        凭审计原文猜，然后这一轮就结束了。
        """
        limit = DEFAULT_CONTEXT_WINDOW_TOKENS
        if self.config is not None:
            limit = int(getattr(self.config.orchestration,
                                "context_window_tokens",
                                DEFAULT_CONTEXT_WINDOW_TOKENS))
        summary_budget = max(1, int(limit * 0.2))
        kept, dropped = trim_messages(self.repair_messages,
                                      limit - summary_budget)
        if dropped:
            compressed = self._inject_compressed(
                kept, dropped, limit=limit, summary_budget=summary_budget)
            self.audit.log("context_trimmed",
                           f"修复对话裁剪 {len(dropped)} 条旧观察"
                           f"，压缩为 {len(compressed)} 条关键信息摘要",
                           level="warning", **budget_report(kept, limit))
            self.repair_messages = compressed
        else:
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
                              max_tokens=self._llm_max_tokens(),
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
        #: 空间理解快照（Ticket 08 接线）：收尾一次性采样 -> 观测 -> diff。
        #: 整场与逐镜两条构建路径在这里汇合，最终场景一致；无 bpy/无场景
        #: 时如实留空（零形状差），失败只记 warning。
        self._build_spatial_observation_and_diff()
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
        #: v1.6 D3（FR-B2 / TDD §3.6）：计划确认后落一条节奏读数（info，不是门）。
        #: 采样通道（frustum/guard 的 ShotSummary）由 B4 接线；当前没有采样
        #: 数据就如实传 None —— jump_cut_risks=0（诚实零：不是"检查过且无
        #: 风险"的结论，而是"没有数据就不造数"），其余三字段不受影响。
        readings = rhythm_readings(
            [shot.duration_seconds for shot in plan.shots],
            shot_summaries=None)
        self.audit.log("rhythm_reading", "节奏读数（info，不设门）", **readings)
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
            version_histories={
                str(k): v.to_dict() for k, v in self._shot_versions.items()},
            #: R2-D3：逐镜回溯最高分与连续无新高轮数随断点落盘，resume 后
            #: `_failures_payload()` 读持久化值（"高分保留"跨进程成立）。
            react_best={str(k): dict(v)
                        for k, v in self._react_best.items()},
            react_no_gain={str(k): int(v)
                           for k, v in self._react_no_gain.items()},
            react_round_counts={
                str(k): int(v) for k, v in self._react_round_counts.items()},
            evidence_store=(
                self.evidence_store.to_dict()
                if self.evidence_store is not None else None),
            coarse_decision=copy.deepcopy(self._coarse_decision),
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
            declared = list(
                getattr(self.parsed_script, "declared_shots", []) or [])
            if declared:
                self._pin_declared_shot_types(declared)
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
        #: R2-D3：把持久化的回溯最高分与无新高轮数种回内存，避免新进程
        #: 用空内存重建 `failures.json` 把历史最高分清零（红线 U10）。
        self._react_best = {str(k): dict(v)
                            for k, v in state.react_best.items()}
        self._react_no_gain = {str(k): int(v)
                               for k, v in state.react_no_gain.items()}
        #: R2-F11：每镜 ReAct 总回合计数随断点恢复，回合上限跨进程不重置。
        self._react_round_counts = {
            str(k): int(v) for k, v in state.react_round_counts.items()}
        if state.version_histories:
            try:
                self._shot_versions = {
                    str(k): ShotVersionHistory.from_dict(dict(v))
                    for k, v in state.version_histories.items()}
            except (KeyError, TypeError, ValueError) as exc:
                raise ResumeStateError(
                    f"resume_state.version_histories 无法解析：{exc}") from exc
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
        #: 方案 B：没有待起草的镜头时，直接走逐镜预演路径（prepare → per-shot），
        #: 而不是退回首版整场 BUILDING——否则 resume 与首跑在 `_supports_prepare_scene`
        #: 的 builder 下行为不一致（首跑逐镜、续跑整场）。
        target = (DriverState.EDITING if pending_drafts
                  else (DriverState.PREPARE_SCENE
                        if self._supports_prepare_scene()
                        else DriverState.BUILDING))
        #: R2-F1：断点续跑同样必须在进细排前过粗排 gate——resume 直接恢复
        #: plan 并跳进 EDITING/PREPARE_SCENE，若这里不查，旧断点（首跑时
        #: human gate 短路了粗排）会整体绕过粗排验证（实测同 2026-10-19）。
        if self._restore_cached_coarse_decision():
            if self.state not in TERMINAL_STATES:
                self._transition(target)
            return
        if not self._run_coarse_gate(target):
            return
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
                retry_note=self._plan_retry_note(),
                #: 空间理解快照（Ticket 08）：已有设计快照（如续跑/重规划）时
                #: 注入设计摘要；首跑计划未定，恒为 None ⇒ 提示零形状差。
                design=self._spatial_design)
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

    def _plan_retry_note(self) -> str:
        """plan 提示的"上一次失败原因"：粗排回溯反馈 + 计划生成问题。

        粗排反馈存在 ``_coarse_feedback``（直到门过才清），计划生成问题
        在 ``_plan_problem``（收段即清）——两者并集回灌，保序去重。
        """
        parts: List[str] = []
        for item in list(self._coarse_feedback) + [self._plan_problem]:
            text = str(item or "").strip()
            if text and text not in parts:
                parts.append(text)
        return "\n".join(parts)

    def _plan_chunk_list(self) -> List[Dict[str, Any]]:
        """这一跑的计划分段（只算一次；没有分镜表声明时返回空表 = 不分块）。

        分块规则与 `planner.plan_chunks` 同源（单一真源），驱动只负责"轮到第几段"。
        """
        if self._plan_chunks is None:
            self._plan_chunks = plan_chunks(self.parsed_script)
        return self._plan_chunks

    def _restart_plan_accumulator(self) -> None:
        """从第一段重新收一份完整计划，留给上一条错误计划的状态全部清空。

        粗排回溯是"再规划一条新路线"，不是"重试最后一段"。若只把
        ``_plan_failures`` 清零而保留游标/已收镜头，分块长剧本会从最后
        一段继续追加；64 镜计划会依次膨胀成 80/96/112 镜，重复 shot_id
        还会在按 id 建索引的报告里静默折叠。
        """
        self._plan_chunk_index = 0
        self._plan_shots = []
        self._plan_head = {}
        self._plan_problem = ""
        self._plan_next_slim = False

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
            elif self._shot_queue:
                # 未通过当前镜时，任何资源边界都只允许暂停并续跑，不能降级前进。
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
                self._reply_q.put(
                    ("err", f"{type(exc).__name__}: {exc}",
                     upstream_error_fields(exc)))

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
                #: 协议闭环：assistant 消息已带着这条 tool_call 进了对话，
                #: 就必须给它补一条 role="tool" 的回应——否则下一轮请求里
                #: 出现"有调用、无回应"的畸形对话（DeepSeek 官方端点对此
                #: 容忍度差），而且模型永远收不到"参数 JSON 是坏的"这条
                #: 反馈，同一错误会原样重犯。
                conversation.append(tool_message(
                    call, f"参数不是合法 JSON: {exc}。请重新调用本工具。"))
                continue

            if call.function.name == EDITOR_TOOL_NAME:
                #: G2 #8（用户裁决）：无歧义看门狗在 schema 校验**之前**跑，
                #: 只归一"翻译不可能出错"的值（start_frame 0→1、look_at
                #: target 优先、camera.side='neutral'→''）；有歧义的照旧被
                #: validate_args 拒绝。
                args = normalize_draft_watchdog(args)
            #: v1.6 决策树投影（设计 §7.3）：react/repair 阶段的改场景工具
            #: 先过该镜决策树——PROJECTED ⇒ 改写参数后执行，REJECTED ⇒ 不执行
            #: 并回灌错误。剧本硬约束（P0）优先级最高，所以即使投影层报错
            #: 也不自动放行（这里只对白名单内工具调用投影层）。
            projection: Optional[ToolProjection] = None
            if (call.function.name in TOOL_TREE_MAP
                    and self.plan is not None
                    and self._current_shot_id):
                shot_id = str(self._current_shot_id)
                shot = self._shot_by_id(shot_id)
                if shot is not None:
                    tree = self._decision_trees.get(shot_id)
                    if tree is None:
                        tree = build_tree(shot, self.plan)
                        self._decision_trees[shot_id] = tree
                    stage = ("repair" if self._call_purpose == "repair"
                             else "react" if self._call_purpose == "react"
                             else "react")
                    try:
                        projection = project_tool_call(
                            tree, call.function.name, args, stage=stage)
                    except ValueError as exc:
                        #: 真源漂移等构建/投影异常不得静默放行：记审计并
                        #: 当作本轮错误回灌，避免越界参数绕过硬约束。
                        errors.append(f"{call.function.name}: {exc}")
                        self.audit.log(
                            "projection_error", str(exc), level="error",
                            shot=shot_id, stage=stage,
                            tool=call.function.name)
                        continue
            if projection is not None:
                event_name = ("repair_projected" if stage == "repair"
                              else "react_projected")
                event_data = {
                    "shot_id": str(self._current_shot_id),
                    "stage": stage,
                    "tool": call.function.name,
                    "records": [r.to_dict() for r in projection.records],
                }
                if stage == "repair":
                    event_data["repair_invalid"] = True
                if projection.verdict == Verdict.REJECTED:
                    #: 不执行：把投影拒绝原因回灌给模型，保持会话配对。
                    reason = "；".join(
                        r.reason for r in projection.records) or "越界参数被拒绝"
                    self.audit.log(event_name,
                                   f"{call.function.name} 被拒绝：{reason}",
                                   **event_data)
                    self._emit(event_name, f"{call.function.name} 被拒绝",
                               **event_data)
                    errors.append(f"{call.function.name}: {reason}")
                    conversation.append(tool_message(
                        call, f"{call.function.name} 被决策树拒绝：{reason}"))
                    continue
                if projection.verdict == Verdict.PROJECTED:
                    args = projection.args
                    self.audit.log(event_name,
                                   f"{call.function.name} 参数已投影到合法空间",
                                   **event_data)
                    self._emit(event_name, f"{call.function.name} 已投影",
                               **event_data)
            knowledge_stage = (
                self._call_purpose
                if self._call_purpose in {
                    "plan", "editor", "coarse", "detail", "repair", "react",
                }
                else "direct"
            )
            knowledge_shot = (
                str(self._react_shot or "")
                if knowledge_stage == "react"
                else str(self._current_shot_id or "")
            )
            knowledge_scope = (
                "shot" if knowledge_shot
                else "plan" if knowledge_stage == "plan"
                else "tool"
            )
            result = self.registry.execute(
                call.function.name,
                args,
                context={
                    "stage": knowledge_stage,
                    "scope": knowledge_scope,
                    "shot_id": knowledge_shot,
                },
            )
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
                #: 2026-10-21：agent 成功改动场景后实时把 Blender 实测坐标合并
                #: 进空间设计 JSON（_sync_spatial_design_from_world），粗排/细排
                #: 重测不再拿计划默认站位当"当前事实"。无 bpy/无快照时方法内部
                #: 如实跳过并记审计，不影响纯测试路径。
                self._sync_spatial_design_from_world()
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
                            characters=characters, anchors=anchors,
                            roster=self._cast_roster(),
                            full_cast=self._cast_roster())
                    except ValueError as exc:
                        errors.append(str(exc))
                    else:
                        #: R2 S2（精修身份冻结）：精修不得改写镜头身份。
                        #: 冲突 → 记 E 类错误、草案作废、计划原值保留（绝不
                        #: 静默改写）；无冲突才走合并（并显式冻结身份字段，
                        #: 双保险）。
                        conflicts = identity_conflicts(self.plan, draft)
                        if conflicts:
                            message = identity_finding(
                                shot_id, conflicts)
                            errors.append(message)
                            self.audit.log(
                                "draft_invalid", message, level="error",
                                shot=shot_id, reason=message,
                                category=classify_invalid(message))
                            self._emit("draft_invalid",
                                       f"{shot_id} 草案改写镜头身份被拒",
                                       shot=shot_id)
                            continue
                        merged = merge_draft(self.plan, draft,
                                             freeze_identity=True)
                        crossing = unseen_axis_crossing(
                            merged, self.brief, shot_id)
                        if crossing:
                            errors.append(crossing)
                        else:
                            self.plan = merged
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


def _adversarial_review_text(review: Dict[str, Any]) -> str:
    """把对抗审查快照渲染成修复提示的一段（含证据与建议）。

    只作"信号"回流：disposition 原样透传（含 ``revise``/``escalate``），
    每条 issue 带证据与建议。软尺（safe_area/thirds）偏差在这里同样只
    作为参考列出，不改变任何门限。
    """
    issues = review.get("issues") or []
    lines = [f"【对抗性审查｜镜 {review.get('shot_id', '')} "
             f"v{review.get('version', '')}】"
             f"disposition={review.get('disposition', '')}"]
    for issue in issues:
        if isinstance(issue, dict):
            lines.append(
                f"- [{issue.get('severity', '')}] {issue.get('type', '')}："
                f"{issue.get('evidence', '')}｜建议："
                f"{issue.get('suggestion', '')}")
    rationale = review.get("rationale", "")
    if rationale:
        lines.append(f"审查结论：{rationale}")
    return "\n".join(lines)


def _coarse_plan_score(payload: Any) -> float:
    """把粗排 pipeline_report 折成回溯分数：越高越好。

    口径（2026-10-21 真跑修复）：把**构图通过率**纳入分数——粗排 gate
    现在是构图硬门（任一非空镜 ≤80 即 blocked），若回溯分数只看 error
    findings，重规划模型永远以为"error 没变"而放弃。新口径：

    * 分数 = 构图通过率×100 − error findings 数；
    * 门过（composition 全 >80 且无 error）-> gate_ready=True -> adopt；
    * 低分镜越多分数越低，让"站位/取景更合理"的重规划能被三态比较。

    payload 缺失/异常形状按 0 分（诚实不猜）。
    """
    if not isinstance(payload, dict):
        return 0.0
    errors = len(payload.get("findings") or [])
    for round_item in (payload.get("rounds") or []):
        if isinstance(round_item, dict):
            errors += int(round_item.get("findings") or 0)

    #: 构图通过率：读 blockout_report（payload.artifacts 或 payload.report）。
    #: 分母 = 有 composition check 的镜（非空镜）；空镜豁免不计。
    report = None
    if isinstance(payload.get("report"), dict):
        report = payload["report"]
    else:
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, dict) and artifacts.get("blockout_report"):
            try:
                from pathlib import Path
                report = json.loads(
                    Path(str(artifacts["blockout_report"]))
                    .read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - 证据缺失按 0 分
                report = None
    pass_count = 0
    total_count = 0
    if isinstance(report, dict):
        for check in report.get("checks") or []:
            if str(check.get("check_id") or "") != "composition":
                continue
            total_count += 1
            actual = check.get("actual")
            if composition_decision(actual)["status"] == "pass":
                pass_count += 1
    pass_rate = (pass_count / total_count if total_count else 0.0)
    return round(pass_rate * 100.0 - float(errors), 4)


def _coarse_finding_lines(payload: Any) -> List[str]:
    """把 error finding 明细折成反馈行，供重规划模型看到具体失败项。

    两个来源都支持：

    * ``payload.findings``（计划完整性预检直接携带的 finding 列表，
      不依赖落盘文件）；
    * ``payload.artifacts.blockout_report``（粗排管线的完整报告路径），
      文件缺失/不可读按空列表处理（反馈仍带 blocked reason，不因证据
      缺失中断回溯）。

    每行形如 ``- [error] shot_003 E_BLOCKOUT_EMPTY_WALL: <message>``。
    """
    if not isinstance(payload, dict):
        return []

    def _line(finding: Any) -> Optional[str]:
        if not isinstance(finding, dict):
            return None
        if str(finding.get("severity") or "") != "error":
            return None
        shot_id = str(finding.get("shot_id") or "?")
        check_id = str(finding.get("check_id") or "?")
        message = str(finding.get("message") or "")
        return f"- [error] {shot_id} {check_id}: {message}"

    direct = payload.get("findings")
    if isinstance(direct, list):
        lines = [line for line in (_line(f) for f in direct) if line]
        if lines:
            return lines

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return []
    report_path = artifacts.get("blockout_report")
    if not report_path:
        return []
    try:
        from pathlib import Path
        report = json.loads(Path(str(report_path)).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 证据缺失不阻断回溯
        return []
    lines: List[str] = []
    for finding in report.get("findings") or []:
        line = _line(finding)
        if line:
            lines.append(line)
    return lines
