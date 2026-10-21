"""B1（D-04）：零 LLM 构图门归因诊断工具（v1.6 卡 B1）。

输入一个跑完（或跑到一半）的运行目录，读 ``audit_log.jsonl`` 与
``llm_trace.jsonl``，用**零 LLM 调用**的方式重建最终分镜计划并 headless 重放
场景，对每一个构图门失败（``E_CAM_001`` / ``composition_score <= threshold``）
的镜头打印：

* 主体包围盒（世界 AABB + 归一化视口盒）；
* 机位与焦距；
* 该镜**首帧目标点** vs 主体实际站位；
* 构图六分量（headroom / lead_room / rule_of_thirds / balance /
  occlusion / framing）与首/中/尾三帧的评分；
* 归因：``camera_misplaced`` / ``solver_no_solution`` /
  ``script_scale_exceeds_extent`` 三选一，并附决定该结论的证据数字。

用法::

    python tools/diagnose_composition.py <run_dir> [--out-dir DIR]
             [--blender PATH] [--no-blender]

红线：本工具**只读**被诊断的运行目录，不修改任何被诊断的代码；绝不建议放宽
``PASS_SCORE``（构图总分必须严格高于 80）或任何验收阈值。

纯层（日志解析、计划重建、归因判定、报告渲染）不依赖 ``bpy``，可被 pytest
直接导入（见 ``tests/test_diagnose_composition.py``）；Blender 采样在
``--blender-measure`` 分支里惰性导入 ``bpy``。
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.composition import PASS_SCORE  # noqa: E402
from block_director.contracts.quality import composition_decision  # noqa: E402
from block_director.contracts.messages import (  # noqa: E402
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.contracts.tools import (  # noqa: E402
    PLAN_TOOL,
    SHOT_DRAFT_TOOL,
)
from block_director.layer5_orchestrator.editor import (  # noqa: E402
    extract_draft,
    merge_draft,
)
from block_director.layer9_persistence.replay import (  # noqa: E402
    ReplayError,
    audit_candidates,
    extract_brief,
    extract_plan,
    read_audit_log,
)

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

CLASS_CAMERA_MISPLACED = "camera_misplaced"
CLASS_SOLVER_NO_SOLUTION = "solver_no_solution"
CLASS_SCRIPT_SCALE_EXCEEDS_EXTENT = "script_scale_exceeds_extent"

#: 归因闭集（任务钉死：恰好三类，多一类/少一类都不算）。
ATTRIBUTION_CLASSES: Tuple[str, ...] = (
    CLASS_CAMERA_MISPLACED,
    CLASS_SOLVER_NO_SOLUTION,
    CLASS_SCRIPT_SCALE_EXCEEDS_EXTENT,
)

#: 机位与"按首帧实际站位重解"的偏差容忍（米）。超过即算机位没摆对。
POSITION_TOL_M = 0.5

#: 距离偏差容忍 —— 与 ``layer3_engine/rule_checker.py`` 的
#: ``DISTANCE_TOLERANCE = 0.25``（R009 景别距离）同口径，不是新阈值。
DISTANCE_DEVIATION_TOL = 0.25

#: 目标点与主体水平偏差的容忍，单位是**该距离上的画面宽度**。
#: 合法的视线留白横移是 1/6 幅宽（``cinema/station.LEAD_ROOM_OFFSET``），
#: 取 1/3 幅宽作为"瞄准点不在主体身上"的上界：既放过合法留白，又抓得住
#: "机位瞄着旧锚点"这种量级的偏差。
AIM_GAP_FRACTION = 1.0 / 3.0

#: 主体站位越界的浮点余量（米）。
EXTENT_EPS_M = 0.05

#: 走路类动作（其 ``target_position`` 才参与"剧本尺度超 extent_m"判定；
#: ``look_at`` 的 target_position 是注视点，不在此列）。
WALK_ACTION_TYPES = frozenset({"walk_to", "run_to"})

DEFAULT_OUT_DIR = ROOT / "docs" / "evidence" / "20261009-composition-diagnosis"
DEFAULT_BLENDER = r"D:\Blender 5.2\blender.exe"

#: 重放分与记录分相差超过该值即标记"重放与原始运行不一致"（1 位小数四舍五入
#: 的浮点余量）。
SCORE_MISMATCH_TOL = 0.55


def _composition_passes(score: float, threshold: float = PASS_SCORE) -> bool:
    """Use the one quality contract for diagnostic pass/fail copy."""
    return composition_decision(
        score, threshold=float(threshold))["status"] == "pass"


def fix_card_for(klass: str) -> str:
    """每个归因类应该落到哪张 v1.6 卡修（只给方向，不给阈值让步）。"""
    mapping = {
        CLASS_CAMERA_MISPLACED:
            "卡 B4（FR-C5：审核/修复回路接入 + reframe 菜单，含机位/锚点回读；"
            "D-12/D-13 的同尺回读）——把机位按该镜首帧实际站位重摆，不动 PASS_SCORE",
        CLASS_SOLVER_NO_SOLUTION:
            "卡 D-12（CU/ECU 像素可测约束反解 + readback_shot_size()，"
            "不满足时自动调距离档；B4 的 reframe 菜单）——不动 PASS_SCORE",
        CLASS_SCRIPT_SCALE_EXCEEDS_EXTENT:
            "场景范围（config.scene.extent_m 与卡 D-10/FR-A1 的环境边界）——"
            "走位目标越界属剧本尺度问题；是否扩大 extent 由用户裁决，"
            "不动 PASS_SCORE",
    }
    return mapping.get(klass, "未知归因类（见报告）")


def _round(value: Any, digits: int = 4) -> Any:
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, (list, tuple)):
        return [_round(item, digits) for item in value]
    if isinstance(value, dict):
        return {key: _round(item, digits) for key, item in value.items()}
    return value


def _dist2(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _dist3(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(
        (float(a[0]) - float(b[0])) ** 2
        + (float(a[1]) - float(b[1])) ** 2
        + (float(a[2]) - float(b[2])) ** 2)


def _out_of_extent(xy: Sequence[float], extent_m: float) -> bool:
    return (abs(float(xy[0])) > float(extent_m) + EXTENT_EPS_M
            or abs(float(xy[1])) > float(extent_m) + EXTENT_EPS_M)


# --------------------------------------------------------------------------- #
# 纯层：日志读取
# --------------------------------------------------------------------------- #

def llm_trace_path(directory: Path) -> Path:
    """llm_trace.jsonl 的可能位置（项目根或 runs/ 下）。"""
    candidates = [directory / "llm_trace.jsonl",
                  directory / "runs" / "llm_trace.jsonl"]
    return next((item for item in candidates if item.exists()),
                candidates[0])


def project_file_paths(directory: Path) -> List[Path]:
    """project.bdproj 的可能位置（项目根或 runs/ 下）。"""
    candidates = [directory / "project.bdproj",
                  directory / "runs" / "project.bdproj"]
    return [item for item in candidates if item.exists()]


def read_jsonl_lines(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            records.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return records


def plan_from_records(records: Sequence[Dict[str, Any]]
                      ) -> Tuple[Optional[Plan], str]:
    """取最终计划：优先 ``plan_received``；旧日志退回 ``emit_plan`` 工具参数。"""
    plan = extract_plan(records)
    if plan is not None:
        return plan, "plan_received"
    for record in records:
        if record.get("kind") != "tool_call":
            continue
        data = record.get("data") or {}
        if data.get("tool") != PLAN_TOOL:
            continue
        args = data.get("args")
        if not isinstance(args, dict) or not isinstance(args.get("shots"), list):
            continue
        return Plan.from_dict({
            "shots": args["shots"],
            "scene_heading": args.get("scene_heading", ""),
            "environment": args.get("environment") or {},
            "continuity_notes": args.get("continuity_notes") or [],
        }), "emit_plan"
    return None, ""


def _editor_draft_calls(trace_records: Sequence[Dict[str, Any]]
                        ) -> List[Dict[str, Any]]:
    """逐镜起草（EDITING）阶段的 ``emit_shot_draft``（只存在于 llm_trace）。"""
    calls: List[Dict[str, Any]] = []
    for record in trace_records:
        if str(record.get("purpose") or "") != "editor":
            continue
        response = record.get("response") or {}
        for tool_call in response.get("tool_calls") or []:
            # llm_trace 的 tool_calls 是 OpenAI 扁平形状
            # ``{"name": ..., "arguments": ...}``，也可能带 ``function`` 包装。
            function = tool_call.get("function") or tool_call
            if str(function.get("name") or "") != SHOT_DRAFT_TOOL:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            if not isinstance(arguments, dict):
                continue
            calls.append({
                "ts": float(record.get("ts") or 0.0),
                "purpose": "editor",
                "shot_id": str(arguments.get("shot_id") or ""),
                "args": arguments,
                "source": "llm_trace",
            })
    return calls


def _audit_draft_calls(records: Sequence[Dict[str, Any]]
                       ) -> List[Dict[str, Any]]:
    """修复/精修（REPAIRING/ReAct）阶段的 ``emit_shot_draft``（audit_log）。"""
    calls: List[Dict[str, Any]] = []
    for record in records:
        if record.get("kind") != "tool_call":
            continue
        data = record.get("data") or {}
        if data.get("tool") != SHOT_DRAFT_TOOL:
            continue
        args = data.get("args")
        if not isinstance(args, dict):
            continue
        calls.append({
            "ts": float(record.get("ts") or 0.0),
            "purpose": "repair/react",
            "shot_id": str(args.get("shot_id") or ""),
            "args": args,
            "source": "audit_log",
        })
    return calls


def _shot_plan(plan: Plan, shot_id: str):
    return next((shot for shot in plan.shots if shot.shot_id == shot_id), None)


def _draft_context(plan: Plan, shot_id: str
                   ) -> Tuple[List[str], List[str]]:
    """与 ``driver._draft_context`` 同款：这一镜的在场角色与本场锚点名。"""
    shot = _shot_plan(plan, shot_id)
    characters = [str(cid) for cid in (shot.characters or [])] if shot else []
    environment = getattr(plan, "environment", None) or {}
    anchors = [str((item or {}).get("name") or "")
               for item in (environment.get("anchors") or [])
               if isinstance(item, dict)]
    return characters, [name for name in anchors if name]


def rebuild_plan(records: Sequence[Dict[str, Any]],
                 trace_records: Optional[Sequence[Dict[str, Any]]] = None,
                 ) -> Tuple[Plan, List[Dict[str, Any]], str]:
    """零 LLM 重建最终计划：基计划 + 按时间顺序重放**通过校验**的逐镜草案。

    校验复用驱动器同一条代码路径（``editor.extract_draft``）——被拒的草案
    （``draft_invalid``/``repair_invalid``/``react_invalid`` 的那批）不合并，
    与原始运行的"无效草案整份丢弃"逐字节同语义。
    """
    plan, source = plan_from_records(records)
    if plan is None:
        raise ReplayError(
            "审计日志里既没有 plan_received 事件，也没有 emit_plan 工具调用"
            "（找过：{0}）。无法零 LLM 重建计划".format(
                "、".join(str(item) for item in audit_candidates("."))))

    calls = _editor_draft_calls(trace_records or [])
    calls.extend(_audit_draft_calls(records))
    # 同一时刻：起草草案（llm_trace）在前、修复草案（audit_log）在后。
    calls.sort(key=lambda item: (
        item["ts"], 0 if item["source"] == "llm_trace" else 1,
        item["shot_id"]))

    events: List[Dict[str, Any]] = []
    for call in calls:
        shot_id = call["shot_id"]
        record: Dict[str, Any] = {
            "shot_id": shot_id, "source": call["source"],
            "purpose": call["purpose"], "accepted": False,
            "reason": "", "actions": 0, "dialogues": 0,
        }
        if _shot_plan(plan, shot_id) is None:
            record["reason"] = "shot_id 不在计划里，跳过"
            events.append(record)
            continue
        characters, anchors = _draft_context(plan, shot_id)
        try:
            function = FunctionCall(
                name=SHOT_DRAFT_TOOL,
                arguments=json.dumps(call["args"], ensure_ascii=False))
            tool_call = ToolCall(id="diagnose", function=function)
            draft = extract_draft(
                ChatReply(tool_calls=[tool_call]), shot_id,
                characters=characters, anchors=anchors)
        except ValueError as exc:
            record["reason"] = str(exc)
            events.append(record)
            continue
        plan = merge_draft(plan, draft)
        record.update({
            "accepted": True,
            "actions": len(draft.actions),
            "dialogues": len(draft.dialogues),
        })
        events.append(record)
    return plan, events, source


def draft_received_counts(records: Sequence[Dict[str, Any]]
                          ) -> Dict[str, Dict[str, Any]]:
    """审计里 ``draft_received`` 的逐镜计数（用于核对重建是否忠实）。"""
    counts: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if record.get("kind") != "draft_received":
            continue
        data = record.get("data") or {}
        shot_id = str(data.get("shot") or "")
        if not shot_id:
            continue
        counts[shot_id] = {
            "actions": int(data.get("actions") or 0),
            "dialogues": int(data.get("dialogues") or 0),
            "stage": str(data.get("stage") or "editor"),
        }
    return counts


def failing_shots(records: Sequence[Dict[str, Any]],
                  plan: Optional[Plan] = None,
                  ) -> List[Dict[str, Any]]:
    """构图门失败的镜头（按计划顺序，每镜一行）：E_CAM_001 / 分未严格高于阈值。"""
    by_shot: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if record.get("kind") != "shot_audit":
            continue
        data = record.get("data") or {}
        shot_id = str(data.get("shot") or "")
        if not shot_id:
            continue
        findings = data.get("findings") or []
        composition_failed = any(
            str(finding.get("code") or "") == "E_CAM_001"
            or str(finding.get("rule") or "") == "COMPOSITION"
            for finding in findings)
        entry = by_shot.setdefault(shot_id, {
            "shot_id": shot_id, "failed": False, "recorded_score": None,
            "threshold": float(data.get("composition_threshold") or PASS_SCORE),
            "findings": [], "audit_count": 0,
        })
        entry["audit_count"] += 1
        if composition_failed:
            entry["failed"] = True
        score = data.get("composition_score")
        if score is not None:
            entry["recorded_score"] = float(score)
        if findings:
            entry["findings"] = findings
    order = [shot.shot_id for shot in (plan.shots if plan is not None else [])]
    result = [by_shot[key] for key in order if by_shot.get(key, {}).get("failed")]
    result.extend(entry for shot_id, entry in by_shot.items()
                  if shot_id not in order and entry["failed"])
    return result


def declared_walk_targets(plan: Plan, extent_m: float
                          ) -> Dict[str, List[Tuple[float, float]]]:
    """每镜走路类动作的目标点里**越出 extent_m** 的那些（供证据展示）。"""
    out: Dict[str, List[Tuple[float, float]]] = {}
    for shot in plan.shots:
        for action in shot.actions or []:
            if not isinstance(action, dict):
                continue
            if str(action.get("action_type") or "") not in WALK_ACTION_TYPES:
                continue
            target = action.get("target_position")
            if not isinstance(target, (list, tuple)) or len(target) < 2:
                continue
            try:
                x, y = float(target[0]), float(target[1])
            except (TypeError, ValueError):
                continue
            if _out_of_extent((x, y), extent_m):
                out.setdefault(shot.shot_id, []).append((x, y))
    return out


# --------------------------------------------------------------------------- #
# 纯层：归因
# --------------------------------------------------------------------------- #

@dataclass
class ShotEvidence:
    """一次构图失败的全部可判定证据（纯数据，不含 bpy 对象）。"""

    shot_id: str = ""
    shot_type: str = "MS"
    side: str = "front"
    lens: Optional[float] = None
    recorded_score: Optional[float] = None
    replayed_score: Optional[float] = None
    threshold: float = PASS_SCORE
    subject_xy: Tuple[float, float] = (0.0, 0.0)
    subject_z: float = 0.0
    extent_m: float = 12.0
    declared_target_out_of_extent: bool = False
    declared_targets: List[Tuple[float, float]] = field(default_factory=list)
    camera_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    target_xyz: Optional[Tuple[float, float, float]] = None
    solver_position: Optional[Tuple[float, float, float]] = None
    solver_distance: Optional[float] = None
    solver_clamped: bool = False
    solver_warnings: List[str] = field(default_factory=list)
    declared_movements: List[Dict[str, Any]] = field(default_factory=list)
    room: Optional[Tuple[float, float, float, float]] = None
    actual_distance: Optional[float] = None
    required_distance: Optional[float] = None
    frame_width: Optional[float] = None
    components: Dict[str, float] = field(default_factory=dict)
    component_items: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    boxes: List[Dict[str, Any]] = field(default_factory=list)
    per_frame_scores: List[Dict[str, Any]] = field(default_factory=list)
    measurements_available: bool = False


@dataclass
class Attribution:
    shot_id: str
    klass: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def fix_card(self) -> str:
        return fix_card_for(self.klass)

    def to_dict(self) -> Dict[str, Any]:
        return {"shot_id": self.shot_id, "class": self.klass,
                "fix_card": self.fix_card,
                "evidence": _round(self.evidence, 4)}


def classify(evidence: ShotEvidence) -> Attribution:
    """把一镜证据归到**恰好三类之一**；顺序即优先级：

    1. ``script_scale_exceeds_extent``：剧本走位目标越出 ``extent_m``，或
       主体首帧实际站位在场景范围外；
    2. ``camera_misplaced``：机位/距离/瞄准点与"按首帧实际站位重解"的
       取景结果不一致（摆错了 / 瞄着旧锚点）；
    3. ``solver_no_solution``：机位就是求解器会摆的位置（含被房间边界夹回
       的 ``clamped`` 情况），构图依然过不了门——求解器在这组参数下无解。
    """
    if not evidence.measurements_available:
        raise ValueError("缺少 Blender 测量（机位/包围盒/目标点），不能归因")
    shot_id = evidence.shot_id
    if evidence.declared_target_out_of_extent \
            or _out_of_extent(evidence.subject_xy, evidence.extent_m):
        return Attribution(shot_id, CLASS_SCRIPT_SCALE_EXCEEDS_EXTENT, {
            "subject_xy": list(evidence.subject_xy),
            "extent_m": evidence.extent_m,
            "declared_target_out_of_extent":
                evidence.declared_target_out_of_extent,
            "declared_targets": [list(target) for target
                                 in evidence.declared_targets],
        })

    # 求解器被房间夹回 = 要求的距离在场景里放不下：求解器确实无解。
    if evidence.solver_clamped:
        return Attribution(shot_id, CLASS_SOLVER_NO_SOLUTION, {
            "solver_clamped": True,
            "room": list(evidence.room) if evidence.room else None,
            "solver_distance": evidence.solver_distance,
            "solver_warnings": list(evidence.solver_warnings),
        })

    misplaced: List[Dict[str, Any]] = []
    if evidence.solver_position is not None:
        gap = _dist3(evidence.camera_xyz, evidence.solver_position)
        if gap > POSITION_TOL_M:
            misplaced.append({
                "camera_vs_solver_m": round(gap, 4),
                "camera_xyz": list(evidence.camera_xyz),
                "solver_position": list(evidence.solver_position),
                "tolerance_m": POSITION_TOL_M,
            })
    if (evidence.target_xyz is not None
            and evidence.frame_width is not None
            and evidence.frame_width > 0):
        gap = _dist2(evidence.target_xyz, evidence.subject_xy)
        if gap > evidence.frame_width * AIM_GAP_FRACTION + EXTENT_EPS_M:
            misplaced.append({
                "target_to_subject_m": round(gap, 4),
                "target_xyz": list(evidence.target_xyz),
                "subject_xy": list(evidence.subject_xy),
                "frame_width_m": round(evidence.frame_width, 4),
                "aim_gap_fraction": AIM_GAP_FRACTION,
            })
    if (evidence.required_distance is not None
            and evidence.required_distance > 0
            and evidence.actual_distance is not None):
        ratio = abs(evidence.actual_distance - evidence.required_distance) \
            / evidence.required_distance
        if ratio > DISTANCE_DEVIATION_TOL:
            misplaced.append({
                "distance_deviation_ratio": round(ratio, 4),
                "actual_distance_m": round(evidence.actual_distance, 4),
                "required_distance_m": round(evidence.required_distance, 4),
                "tolerance": DISTANCE_DEVIATION_TOL,
            })
    if misplaced:
        return Attribution(shot_id, CLASS_CAMERA_MISPLACED,
                           {"reasons": misplaced})

    # 机位与求解器一致、目标点在主体身上、距离也在容差内，却依然低于门：
    # 求解器对这组（景别/焦距/方位/朝向）参数产出的取景本身过不了门。
    return Attribution(shot_id, CLASS_SOLVER_NO_SOLUTION, {
        "camera_matches_solver": True,
        "replayed_score": evidence.replayed_score,
        "threshold": evidence.threshold,
        "components": dict(evidence.components),
    })


# --------------------------------------------------------------------------- #
# 纯层：报告渲染
# --------------------------------------------------------------------------- #

def component_string(components: Dict[str, float]) -> str:
    names = ("headroom", "lead_room", "rule_of_thirds",
             "balance", "occlusion", "framing")
    return " / ".join(
        f"{name} {components.get(name, float('nan')):.2f}"
        if name in components else f"{name} —" for name in names)


def _flatten_evidence(evidence: Dict[str, Any], prefix: str = ""
                      ) -> List[str]:
    """把归因证据拍平成 `键=值` 列表（列表逐项展开，便于写进表格）。"""
    parts: List[str] = []
    for key, value in evidence.items():
        label = f"{prefix}{key}"
        if isinstance(value, dict):
            parts.extend(_flatten_evidence(value, label + "."))
        elif isinstance(value, list):
            if not value:
                continue
            if all(isinstance(item, (int, float, str, bool)) for item in value):
                parts.append(f"{label}={value}")
            else:
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        parts.extend(_flatten_evidence(
                            item, f"{label}[{index}]."))
                    else:
                        parts.append(f"{label}[{index}]={item}")
        else:
            parts.append(f"{label}={value}")
    return parts


def root_note(evidence: Dict[str, Any], threshold: float) -> str:
    """从实测证据机械生成一句根因注记（弱项 + 首帧是否达门 + 声明运镜）。"""
    items = evidence.get("component_items") or {}
    weak = []
    for name, item in items.items():
        if not isinstance(item, dict) or item.get("score") is None:
            continue
        if float(item["score"]) < 0.7:
            weak.append(f"{name}={float(item['score']):.2f}")
    parts = ["弱项：" + "、".join(weak)] if weak else ["全部分项 ≥ 0.7"]
    frames = evidence.get("per_frame_scores") or []
    if frames:
        first = float(frames[0].get("score") or 0.0)
        if _composition_passes(first, threshold):
            parts.append(f"首帧 {first:.1f} 已达门，末段被带出"
                         f"（构图门取首/中/尾最小值）")
        else:
            parts.append(
                f"首帧即 {first:.1f}，未严格高于门 {threshold:.0f}")
    movements = evidence.get("declared_movements") or []
    if movements:
        parts.append("声明运镜：" + "、".join(
            f"{item.get('type')} {item.get('amount')}"
            for item in movements if isinstance(item, dict)))
    return "；".join(parts)


def attribution_distribution(rows: Sequence[Dict[str, Any]]
                             ) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {klass: [] for klass in ATTRIBUTION_CLASSES}
    for row in rows:
        klass = (row.get("attribution") or {}).get("class")
        if klass in out:
            out[klass].append(str(row["shot_id"]))
    return out


def render_markdown(run_dir: Path, plan_source: str, draft_events: List[Dict],
                    problems: List[str], rows: List[Dict[str, Any]],
                    unattributed: List[Dict[str, Any]],
                    replay_mismatch: List[Dict[str, Any]],
                    extent_m: float, code_label: str = "当前工作区") -> str:
    """诊断报告（Markdown）。末尾是归因分布与每类的修卡建议。"""
    lines: List[str] = [
        "# 构图门归因诊断（B1 / D-04）",
        "",
        f"- 运行目录：`{run_dir}`",
        f"- 最终计划来源：`{plan_source}`",
        f"- `config.scene.extent_m`：{extent_m:g}",
        f"- 重放代码：{code_label}",
        "- 诊断方式：读 `audit_log.jsonl` + `llm_trace.jsonl` → 零 LLM 重建"
        "计划 → Blender headless 重放场景 → 逐失败镜测量。",
        "- 红线：**不修改被诊断代码**；**归因不给出任何阈值让步**"
        f"（PASS_SCORE 保持 {PASS_SCORE:g}）。",
        "",
    ]
    if problems:
        lines.append("## 输入侧缺失（原样报告，不猜）")
        lines.append("")
        for problem in problems:
            lines.append(f"- {problem}")
        lines.append("")
    if draft_events:
        rejected = [item for item in draft_events if not item["accepted"]]
        accepted = [item for item in draft_events if item["accepted"]]
        lines.append("## 计划重建")
        lines.append("")
        lines.append(f"- 重放草案 {len(draft_events)} 条：接受 {len(accepted)}"
                     f"、拒绝 {len(rejected)}。")
        for item in rejected:
            lines.append(f"  - {item['shot_id']}（{item['source']}/"
                         f"{item['purpose']}）拒绝：{item['reason']}")
        lines.append("")
    if rows:
        lines.append("## 逐镜诊断表")
        lines.append("")
        lines.append(
            "| 镜号 | 景别 | 记录分 | 重放分 | 主体站位 (x,y) | 机位 (x,y,z) | "
            "焦距 | 首帧目标点 (x,y,z) | 目标-主体 (m) | 六分量 | 归因 | "
            "决定性证据 | 建议修卡 |")
        lines.append(
            "|---|---|---|---|---|---|---|---|---|---|---|---|")
        for row in rows:
            evidence = row.get("evidence") or {}
            attribution = row.get("attribution") or {}
            klass = attribution.get("class") or "—"
            ev = attribution.get("evidence") or {}
            evidence_summary = "；".join(_flatten_evidence(ev)[:6]) or "—"
            lines.append(
                f"| {row['shot_id']} | {row['shot_type']} | "
                f"{row['recorded_score']} | {row['replayed_score']} | "
                f"{evidence['subject_xy']} | {evidence['camera_xyz']} | "
                f"{evidence['lens']} | {evidence['target_xyz']} | "
                f"{row['target_gap_m']} | "
                f"{component_string(evidence.get('components') or {})} | "
                f"**{klass}** | {evidence_summary} | "
                f"{attribution.get('fix_card') or '—'} |")
        lines.append("")
        lines.append("## 逐镜根因注记（由实测证据机械生成）")
        lines.append("")
        for row in rows:
            note = row.get("root_note") or root_note(
                row.get("evidence") or {}, float(row.get("threshold") or PASS_SCORE))
            lines.append(f"- **{row['shot_id']}**（{row['shot_type']}）：{note}")
        lines.append("")
    if replay_mismatch:
        lines.append("## 重放与原始运行不一致（需人工复核，不参与归因分布）")
        lines.append("")
        for item in replay_mismatch:
            lines.append(
                f"- {item['shot_id']}：记录分 {item['recorded_score']}，"
                f"重放分 {item['replayed_score']}（差 "
                f"{abs(item['recorded_score'] - item['replayed_score']):.1f}）。"
                f"说明：{item['note']}")
        lines.append("")
    if unattributed:
        lines.append("## 无法归因（缺什么写什么，不猜）")
        lines.append("")
        for item in unattributed:
            lines.append(f"- {item['shot_id']}：{item['reason']}")
        lines.append("")
    distribution = attribution_distribution(rows)
    lines.append("## 归因分布与修卡去向")
    lines.append("")
    lines.append("| 归因类 | 镜数 | 镜头 | 落到哪张 v1.6 卡修 |")
    lines.append("|---|---|---|---|")
    for klass in ATTRIBUTION_CLASSES:
        shots = distribution[klass]
        lines.append(
            f"| {klass} | {len(shots)} | {', '.join(shots) or '—'} | "
            f"{fix_card_for(klass)} |")
    lines.append("")
    lines.append("## 未覆盖 / 剩余风险")
    lines.append("")
    lines.append(
        f"- 重放代码：{code_label}；重放分与记录分的对拍见上表"
        "（不一致的镜头先核对代码版本再读归因）。")
    lines.append(
        "- 报告只归因构图门失败的镜头；R001/E_AXIS_001 等其他发现不在此列。")
    lines.append("- 逐镜完整证据（包围盒、六分量明细、首/中/尾三帧评分、"
                 "求解器重解）见 `shots/<shot_id>.json`。")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Blender 分支（headless 测量；只有这里才 import bpy）
# --------------------------------------------------------------------------- #

def _blender_measure_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="diagnose_composition --blender-measure")
    parser.add_argument("--payload", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--code-dir", default=None)
    args = parser.parse_args(argv)

    if args.code_dir:
        # 用该运行的**同版本代码**重放：先卸掉本进程已导入的 block_director
        # （工具顶层为解析日志导入过），再让 code_dir 的包优先于当前工作区。
        code_dir = str(Path(args.code_dir).resolve())
        for name in list(sys.modules):
            if name == "block_director" or name.startswith("block_director."):
                del sys.modules[name]
        sys.path.insert(0, code_dir)

    import bpy  # noqa: PLC0415 - 只在 Blender 进程里导入

    import block_director  # noqa: PLC0415
    from block_director.cinema.framing import (  # noqa: PLC0415
        SENSOR_WIDTH,
        SHOT_FRAME,
        required_distance,
        solve_framing,
    )
    from block_director.cinema.station import (  # noqa: PLC0415
        camera_direction,
        subject_frame,
    )
    from block_director.contracts.brief import SceneBrief  # noqa: PLC0415
    from block_director.contracts.cast import SceneSpec  # noqa: PLC0415
    from block_director.contracts.plan import Plan  # noqa: PLC0415
    from block_director.layer3_engine.cinema_engine.composition_guide import (  # noqa: PLC0415,E501
        _screen_box,
        _world_bounds,
        evaluate_camera_composition,
    )
    from block_director.layer3_engine.scene_context import (  # noqa: PLC0415
        get_context,
    )
    from block_director.layer3_engine.shot_builder import (  # noqa: PLC0415
        axis_for_shot,
        build_scene,
        live_subject_entries,
        speaker_of,
    )
    from block_director.settings import get_config  # noqa: PLC0415
    from block_director.utils.geometry import (  # noqa: PLC0415
        rotation_z_to_facing,
    )
    from mathutils import Vector  # noqa: PLC0415

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    block_director.register()
    plan = Plan.from_dict(payload["plan"])
    brief = (SceneBrief.from_dict(payload["brief"])
             if payload.get("brief") else None)
    spec = SceneSpec.from_plan(plan, brief=brief)
    summary = build_scene(plan, spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene
    extent_m = float(get_config().scene.extent_m)

    output: Dict[str, Any] = {
        "summary": summary.to_dict(),
        "extent_m": extent_m,
        "spec_room": list(spec.room) if spec.room else None,
        "shots": [],
    }
    for shot_id in payload["failing_shot_ids"]:
        shot = context.shot(shot_id)
        span = context.schedule.get(shot_id)
        camera = context.camera_for(shot_id)
        subjects = context.subjects_for(shot_id)
        shot_type = str(context.shot_types.get(shot_id, "MS"))
        if shot is None or not span or camera is None or not subjects:
            output["shots"].append({
                "shot_id": shot_id, "error": "重放场景里没有该镜的相机/主体/帧区间"
                f"（shot={shot is not None}, span={bool(span)}, "
                f"camera={camera is not None}, subjects={len(subjects)}）",
            })
            continue
        start, end = int(span[0]), int(span[1])
        frames = sorted({start, start + max((end - start) // 2, 0), end})

        # 构图评分：首/中/尾三帧，与审核器同一份代码。
        per_frame = []
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            report = evaluate_camera_composition(
                camera, subjects, shot_type=shot_type)
            per_frame.append({"frame": frame, **report.to_dict()})
        worst = min(per_frame, key=lambda item: item["score"])

        # 首帧测量。
        scene.frame_set(start)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        camera_pos = tuple(float(v) for v in camera.matrix_world.translation)
        lens = float(camera.data.lens)
        target_obj = bpy.data.objects.get(f"BD_CamTarget_{shot_id}")
        target = (tuple(float(v) for v in target_obj.matrix_world.translation)
                  if target_obj is not None else None)
        roots = [getattr(subject, "root", None) for subject in subjects]
        roots = [root.matrix_world.translation.copy()
                 for root in roots if root is not None]
        centroid = (sum(roots, Vector((0.0, 0.0, 0.0))) / len(roots)
                    if roots else Vector((0.0, 0.0, 0.0)))
        focus = subjects[0]
        facing = ((0.0, 1.0, 0.0)
                  if getattr(focus, "root", None) is None else
                  rotation_z_to_facing(
                      focus.root.matrix_world.to_euler().z))

        boxes = {}
        for label, frame in (("first", start), ("worst", int(worst["frame"]))):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            frame_boxes = []
            for subject in subjects:
                bounds = _world_bounds(subject, depsgraph)
                screen_box = _screen_box(subject, depsgraph, scene, camera,
                                         shot_type)
                frame_boxes.append({
                    "name": str(getattr(subject, "name", "?")),
                    "world_min": [round(float(v), 4) for v in bounds[0]]
                    if bounds is not None else None,
                    "world_max": [round(float(v), 4) for v in bounds[1]]
                    if bounds is not None else None,
                    "screen": None if screen_box is None else {
                        "left": round(screen_box.left, 4),
                        "right": round(screen_box.right, 4),
                        "top": round(screen_box.top, 4),
                        "bottom": round(screen_box.bottom, 4),
                        "center_x": round(screen_box.center_x, 4),
                        "center_y": round(screen_box.center_y, 4),
                        "facing": round(screen_box.facing, 4),
                        "inside_ratio": round(screen_box.inside_ratio(), 4),
                        "clipped_top": screen_box.clipped_top,
                        "clipped_sides": screen_box.clipped_sides,
                    },
                })
            boxes[label] = frame_boxes

        shot_camera = dict((shot.camera or {}) if shot.camera else {})
        side = str(shot_camera.get("side") or "front")
        shot_lens = shot_camera.get("lens")
        #: 与构建器**同一套**方向解算重解机位（station 方向 + 逐镜轴侧镜像 +
        #: frame.anchor）：裸 ``solve_framing`` 不知道轴镜像，会把被镜像过的
        #: 对话机位误归为 camera_misplaced（v10 归因的测量伪差——8 镜
        #: "机位漂移 1.2–9.3 m" 里相当一部分是它）。
        entries = live_subject_entries(shot, context.characters)
        station_frame = subject_frame(entries, shot_type=shot_type,
                                      speaker_id=speaker_of(shot))
        station_axis = axis_for_shot(context, shot)
        direction = camera_direction(
            station_frame, side,
            axis_dir=(station_axis.direction
                      if station_axis is not None else None),
            axis_side=(int(getattr(station_axis, "established_side", 0))
                       if station_axis is not None else 0))
        solution = solve_framing(
            tuple(float(v) for v in station_frame.anchor),
            facing=tuple(float(v) for v in station_frame.facing),
            shot_type=shot_type, side=side, lens=shot_lens,
            room=tuple(spec.room) if spec.room else None,
            direction=direction)
        frame = SHOT_FRAME.get(shot_type.upper())
        required = (required_distance(frame.frame_height, lens)
                    if frame is not None and lens else None)
        actual = float((camera.matrix_world.translation - centroid).length)
        frame_width = actual * SENSOR_WIDTH / lens if lens else None
        target_gap = (_dist2(target, (centroid.x, centroid.y))
                      if target is not None else None)

        output["shots"].append({
            "shot_id": shot_id,
            "shot_type": shot_type,
            "side": side,
            "lens": lens,
            "recorded_plan_lens": shot_lens,
            "declared_movements": [dict(item) for item in
                                   (shot_camera.get("movements") or [])
                                   if isinstance(item, dict)],
            "subject_xy": [round(float(centroid.x), 4),
                           round(float(centroid.y), 4)],
            "subject_z": round(float(centroid.z), 4),
            "facing": [round(float(v), 4) for v in facing],
            "camera_xyz": [round(v, 4) for v in camera_pos],
            "target_xyz": [round(v, 4) for v in target] if target else None,
            "target_gap_m": round(target_gap, 4) if target_gap is not None
            else None,
            "solver_position": [round(v, 4) for v in solution.position],
            "solver_target": [round(v, 4) for v in solution.target],
            "solver_distance": round(solution.distance, 4),
            "solver_clamped": solution.clamped,
            "solver_warnings": list(solution.warnings),
            "axis_side_used": (int(getattr(station_axis,
                                          "established_side", 0))
                               if station_axis is not None else None),
            "actual_distance": round(actual, 4),
            "required_distance": round(required, 4) if required is not None
            else None,
            "frame_width": round(frame_width, 4) if frame_width is not None
            else None,
            "per_frame": per_frame,
            "worst_frame": worst["frame"],
            "worst_score": worst["score"],
            "components": worst["items"],
            "boxes": boxes,
        })

    scene.frame_set(1)
    bpy.context.view_layer.update()
    Path(args.out).write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- #
# 编排分支
# --------------------------------------------------------------------------- #

def parse_cli(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="diagnose_composition",
        description="B1（D-04）：零 LLM 构图门归因诊断（audit_log + llm_trace "
                    "→ 重建计划 → Blender headless 重放 → 三类归因）。")
    parser.add_argument("run_dir", nargs="?", default=None,
                        help="运行目录（含 audit_log.jsonl）")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help="证据输出目录（默认 docs/evidence/"
                             "20261009-composition-diagnosis）")
    parser.add_argument("--blender", default=DEFAULT_BLENDER,
                        help="Blender 可执行文件路径")
    parser.add_argument("--no-blender", action="store_true",
                        help="只做纯层解析与计划重建，跳过场景重放测量")
    parser.add_argument("--code-dir", default=None,
                        help="Blender 重放用指定目录下的 block_director（"
                             "= 该跑当时的提交；缺省用当前工作区）。"
                             "纯层计划重建仍用本工具所在代码树；要整条链都用"
                             "旧代码，请把本工具拷进旧代码树再运行")
    parser.add_argument("--blender-measure", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--payload", help=argparse.SUPPRESS)
    parser.add_argument("--out", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def run_blender_measure(blender: Path, tool_file: Path,
                        payload_path: Path, out_path: Path,
                        log_path: Path, code_dir: Optional[str] = None
                        ) -> Optional[Dict[str, Any]]:
    command = [
        str(blender), "--background", "--factory-startup",
        "--python", str(tool_file), "--",
        "--blender-measure", "--payload", str(payload_path),
        "--out", str(out_path),
    ]
    if code_dir:
        command += ["--code-dir", str(Path(code_dir).resolve())]
    try:
        completed = subprocess.run(
            command, cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=3600)
    except subprocess.TimeoutExpired:
        log_path.write_text("Blender 测量超时（3600 s）\n",
                            encoding="utf-8")
        return None
    log_path.write_text(
        (completed.stdout or "") + "\n===== STDERR =====\n"
        + (completed.stderr or ""), encoding="utf-8")
    if not out_path.is_file():
        return None
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _build_evidence(recorded: Dict[str, Any], measured: Dict[str, Any],
                    extent_m: float) -> ShotEvidence:
    components = {}
    for name, item in (measured.get("components") or {}).items():
        if isinstance(item, dict) and "score" in item:
            components[name] = float(item["score"])
    camera_xyz = tuple(float(v) for v in measured.get("camera_xyz") or (0, 0, 0))
    target = measured.get("target_xyz")
    evidence = ShotEvidence(
        shot_id=recorded["shot_id"],
        shot_type=str(measured.get("shot_type") or "MS"),
        side=str(measured.get("side") or "front"),
        lens=measured.get("lens"),
        recorded_score=recorded.get("recorded_score"),
        replayed_score=(float(measured["worst_score"])
                        if measured.get("worst_score") is not None else None),
        threshold=float(recorded.get("threshold") or PASS_SCORE),
        subject_xy=(float(measured["subject_xy"][0]),
                    float(measured["subject_xy"][1])),
        subject_z=float(measured.get("subject_z") or 0.0),
        extent_m=float(extent_m),
        camera_xyz=camera_xyz,
        target_xyz=tuple(float(v) for v in target) if target else None,
        solver_position=(tuple(float(v) for v in measured["solver_position"])
                         if measured.get("solver_position") else None),
        solver_distance=measured.get("solver_distance"),
        solver_clamped=bool(measured.get("solver_clamped")),
        solver_warnings=list(measured.get("solver_warnings") or []),
        actual_distance=measured.get("actual_distance"),
        required_distance=measured.get("required_distance"),
        frame_width=measured.get("frame_width"),
        components=components,
        component_items=dict(measured.get("components") or {}),
        boxes=[{"frame": label, "boxes": frame_boxes}
               for label, frame_boxes
               in (measured.get("boxes") or {}).items()],
        per_frame_scores=list(measured.get("per_frame") or []),
        declared_movements=list(measured.get("declared_movements") or []),
        measurements_available=True,
    )
    return evidence


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    # Blender 5.x 把**完整**命令行（含它自己的 --background/--python 等）
    # 传给 --python 脚本；脚本参数一律在 "--" 之后，先切掉再进 argparse。
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    args = parse_cli(argv)
    if args.blender_measure:
        rest = argv[1:] if argv and argv[0] == "--blender-measure" else argv
        return _blender_measure_main(rest)
    if not args.run_dir:
        print("错误：缺少 run_dir 位置参数。用法："
              "python tools/diagnose_composition.py <run_dir> [--out-dir DIR]",
              file=sys.stderr)
        return 2

    run_dir = Path(args.run_dir).resolve()
    problems: List[str] = []
    try:
        records = read_audit_log(run_dir)
    except ReplayError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    trace_path = llm_trace_path(run_dir)
    trace_records: Optional[List[Dict[str, Any]]] = None
    if trace_path.is_file():
        trace_records = read_jsonl_lines(trace_path)
    else:
        problems.append(
            f"缺少 llm_trace.jsonl（找过：{trace_path.parent / 'llm_trace.jsonl'}"
            f"、{trace_path}）：逐镜起草（EDITING）的完整参数不可得，"
            "重建计划可能不等于原始运行（改用 audit_log 里的修复草案）。")
    project_files = project_file_paths(run_dir)
    if not project_files:
        problems.append(
            "缺少 project.bdproj（找过：项目根与 runs/ 下均无）：无法与落盘"
            "工程对拍；诊断改由 audit_log + llm_trace 零 LLM 重建，不影响归因。")
    brief = extract_brief(records)
    try:
        plan, draft_events, plan_source = rebuild_plan(records, trace_records)
    except ReplayError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    failing = failing_shots(records, plan)
    if not failing:
        print("该运行目录里没有构图门失败（E_CAM_001）的镜头。")
        return 0

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    payload_path = out_dir / "inputs_plan_payload.json"
    payload_path.write_text(
        json.dumps({
            "plan": plan.to_dict(),
            "brief": brief.to_dict() if brief is not None else None,
            "failing_shot_ids": [item["shot_id"] for item in failing],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    measurements: Optional[Dict[str, Any]] = None
    extent_m = 12.0
    if not args.no_blender:
        blender = Path(args.blender)
        if not blender.is_file():
            blender = None
        if blender is None:
            problems.append(
                f"缺少 Blender 可执行文件（找过：{args.blender}）。"
                "没有它就无法测量机位/包围盒/目标点；加 --no-blender 只做纯层"
                "解析，或加 --blender <路径> 指定。")
        else:
            out_path = out_dir / "measurements.json"
            log_path = out_dir / "blender_run.log"
            measurements = run_blender_measure(
                blender, Path(__file__).resolve(), payload_path, out_path,
                log_path, code_dir=args.code_dir)
            if measurements is None:
                problems.append(
                    "Blender 重放测量失败（命令与日志见 blender_run.log）："
                    "机位/包围盒/目标点不可得，相关镜头不参与归因。")

    if measurements is not None:
        extent_m = float(measurements.get("extent_m") or 12.0)
    declared = declared_walk_targets(plan, extent_m)
    measured_by_shot = {item.get("shot_id"): item
                        for item in (measurements or {}).get("shots") or []}

    rows: List[Dict[str, Any]] = []
    unattributed: List[Dict[str, Any]] = []
    replay_mismatch: List[Dict[str, Any]] = []
    for recorded in failing:
        shot_id = recorded["shot_id"]
        measured = measured_by_shot.get(shot_id)
        shot_type = next((shot.shot_type for shot in plan.shots
                          if shot.shot_id == shot_id), "MS")
        if measured is None or measured.get("error"):
            unattributed.append({
                "shot_id": shot_id,
                "reason": (measured or {}).get("error") or "缺少该镜的测量记录",
            })
            continue
        evidence = _build_evidence(recorded, measured, extent_m)
        evidence.declared_target_out_of_extent = bool(declared.get(shot_id))
        evidence.declared_targets = list(declared.get(shot_id) or [])
        per_shot: Dict[str, Any] = {
            "shot_id": shot_id,
            "shot_type": shot_type,
            "recorded_score": recorded.get("recorded_score"),
            "recorded_findings": recorded.get("findings") or [],
            "audit_count": recorded.get("audit_count"),
            "threshold": evidence.threshold,
            "replayed_score": evidence.replayed_score,
            "evidence": {
                "subject_xy": list(evidence.subject_xy),
                "subject_z": evidence.subject_z,
                "camera_xyz": list(evidence.camera_xyz),
                "lens": evidence.lens,
                "target_xyz": list(evidence.target_xyz)
                if evidence.target_xyz else None,
                "components": dict(evidence.components),
                "component_items": dict(evidence.component_items),
                "boxes": list(evidence.boxes),
                "per_frame_scores": list(evidence.per_frame_scores),
                "solver_position": list(evidence.solver_position)
                if evidence.solver_position else None,
                "solver_distance": evidence.solver_distance,
                "solver_clamped": evidence.solver_clamped,
                "solver_warnings": list(evidence.solver_warnings),
                "actual_distance": evidence.actual_distance,
                "required_distance": evidence.required_distance,
                "frame_width": evidence.frame_width,
                "extent_m": evidence.extent_m,
                "declared_target_out_of_extent":
                    evidence.declared_target_out_of_extent,
                "declared_movements": list(evidence.declared_movements),
            },
            "target_gap_m": measured.get("target_gap_m"),
        }
        if evidence.recorded_score is not None \
                and evidence.replayed_score is not None \
                and abs(evidence.recorded_score
                        - evidence.replayed_score) > SCORE_MISMATCH_TOL:
            replay_mismatch.append({
                "shot_id": shot_id,
                "recorded_score": evidence.recorded_score,
                "replayed_score": evidence.replayed_score,
                "note": "重建现场与原始运行的评分对不上（可能是代码漂移或计划"
                        "重建差异）；该镜不参与三类归因分布。",
            })
        elif (evidence.replayed_score is not None
              and _composition_passes(
                  evidence.replayed_score, evidence.threshold)):
            replay_mismatch.append({
                "shot_id": shot_id,
                "recorded_score": evidence.recorded_score,
                "replayed_score": evidence.replayed_score,
                "note": "重放现场已通过构图门：原始失败未被复现（代码漂移或"
                        "计划重建差异）；该镜不参与三类归因分布。",
            })
        else:
            attribution = classify(evidence)
            per_shot["attribution"] = attribution.to_dict()
            rows.append({
                "shot_id": shot_id, "shot_type": shot_type,
                "recorded_score": evidence.recorded_score,
                "replayed_score": evidence.replayed_score,
                "target_gap_m": measured.get("target_gap_m"),
                "threshold": evidence.threshold,
                "evidence": per_shot["evidence"],
                "attribution": per_shot["attribution"],
                "root_note": root_note(per_shot["evidence"],
                                       evidence.threshold),
            })
        (shots_dir / f"{shot_id}.json").write_text(
            json.dumps(_round(per_shot, 4), ensure_ascii=False, indent=2),
            encoding="utf-8")

    markdown = render_markdown(
        run_dir, plan_source, draft_events, problems, rows, unattributed,
        replay_mismatch, extent_m,
        code_label=(f"`{args.code_dir}`（--code-dir）" if args.code_dir
                    else f"`{ROOT}`（工具自身所在代码树；工作区含并发未提交改动）"))
    (out_dir / "composition_diagnosis.md").write_text(
        markdown, encoding="utf-8")
    summary = {
        "run_dir": str(run_dir),
        "plan_source": plan_source,
        "tool_root": str(ROOT),
        "code_dir": args.code_dir,
        "extent_m": extent_m,
        "failing_shots": len(failing),
        "attributed": len(rows),
        "unattributed": [item["shot_id"] for item in unattributed],
        "replay_mismatch": [item["shot_id"] for item in replay_mismatch],
        "distribution": attribution_distribution(rows),
        "fix_cards": {klass: fix_card_for(klass)
                      for klass in ATTRIBUTION_CLASSES},
        "missing": problems,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    print(f"run_dir={run_dir}")
    print(f"plan_source={plan_source}  extent_m={extent_m:g}")
    print(f"failing={len(failing)} attributed={len(rows)} "
          f"unattributed={len(unattributed)} "
          f"replay_mismatch={len(replay_mismatch)}")
    print("distribution: " + json.dumps(attribution_distribution(rows),
                                        ensure_ascii=False))
    print(f"report={out_dir / 'composition_diagnosis.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
