"""空间尺观测文档的纯层折档（Ticket 04-06）。

把现有运行产物（``Plan`` / ``ParsedScript`` / 每次审核的 score 与
``guard_warnings`` 数值证据 / ``build_summary`` 的相机实测）折成
``spatial-ruler-observation/v2`` 观测文档。**本模块不 import bpy**：
它是外部 seam——插件侧只消费 JSON 友好的输入，产出可被
``contracts/spatial_ruler/`` 下的 schema 校验的观测记录。

纪律：
* **只抄不改**：measurement 数值全部来自已有产物，不重算、不猜缺测；
* 来源四态：``script_declaration`` / ``plan_intent`` / ``algorithmic_measurement``
  / ``blender_geometry``，每条测量 ``source == provenance``；
* 阈值注册表：生产侧直接读 ``contracts/spatial_ruler/contract.v2.json`` 的
  ``registry``（对照载体），代码常量仍是执行真源，本模块不新建第二份阈值；
* 处方闭集：``retime_shot / restore_cast / reframe / move_character /
  change_camera_side / review_transition``，未知操作拒绝。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts.audit import AuditError
from ..contracts.enums import Severity as AuditSeverity
from ..contracts.plan import Plan


SCHEMA_VERSION = "spatial-ruler-observation/v2"
CONTRACT_PATH = (Path(__file__).resolve().parents[1] / "contracts"
                 / "spatial_ruler" / "contract.v2.json")

#: 处方操作闭集（与 schema / integration mapping 对齐，单一真源在此）。
PRESCRIPTION_OPERATIONS: Tuple[str, ...] = (
    "retime_shot", "restore_cast", "reframe", "move_character",
    "change_camera_side", "review_transition",
)

_PROVENANCE_STATES = frozenset({
    "script_declaration", "plan_intent",
    "algorithmic_measurement", "blender_geometry",
})

_STATUS_ORDER = {
    AuditSeverity.ERROR: "repair",
    AuditSeverity.WARNING: "warning",
}

_SEVERITY_ORDER = {
    AuditSeverity.ERROR: "error",
    AuditSeverity.WARNING: "warning",
}

#: guard 告警类型 → (metric, 取值键, 期望键, unit)。期望键为空时 expected=None。
_GUARD_TO_METRIC: Dict[str, Tuple[str, str, str, str]] = {
    "subject_behind_camera": ("visibility_ratio", "visible_ratio", "", "ratio_of_9"),
    "subject_not_visible": ("visibility_ratio", "visible_ratio", "", "ratio_of_9"),
    "subject_out_of_frame": ("inside_ratio", "", "", "ratio"),
    "occlusion": ("occlusion_ratio", "visible_ratio", "occlusion_warn", "ratio"),
    "edge_clip": ("edge_clip", "edge_clip", "edge_clip_max", "ratio"),
    "headroom_off": ("headroom", "headroom", "expected_range", "ndc"),
    "lead_room_short": ("lead_room", "lead_room", "lead_room_min", "ndc"),
    "thirds_deviation": ("thirds_deviation", "thirds_deviation", "threshold", "ndc"),
    "sudden_jump": ("jump_ratio", "ratio_change", "jump_ratio", "ratio"),
    "size_drift": ("shot_size_readback", "drift", "size_drift", "ratio"),
    "unplanned_exit": ("inside_ratio", "exit_frame", "", "frames"),
    "axis_screen_order": ("screen_order", "", "", "none"),
}


def _load_registry() -> Dict[str, Any]:
    """读取契约注册表（对照载体，代码常量仍为执行真源）。"""
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(f"空间尺契约注册表缺失：{CONTRACT_PATH}")
    data = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    return dict(data.get("registry") or {})


def _declared_map(parsed) -> Dict[int, Any]:
    """``{declared_shot_number: ParsedShotDeclaration}``（按键序）。"""
    out: Dict[int, Any] = {}
    for shot in getattr(parsed, "declared_shots", []) or []:
        number = int(getattr(shot, "shot_number", 0) or 0)
        if number:
            out[number] = shot
    return out


def _brief_names(brief) -> set:
    names: set = set()
    for item in getattr(brief, "speakers", []) or []:
        if isinstance(item, dict):
            names.update(str(item.get(k) or "").strip()
                         for k in ("speaker", "listener"))
    for item in getattr(brief, "gaze", []) or []:
        if isinstance(item, dict):
            names.update(str(item.get(k) or "").strip()
                         for k in ("from", "to"))
    for item in getattr(brief, "space", []) or []:
        if isinstance(item, dict):
            names.update(str(item.get(k) or "").strip()
                         for k in ("character", "relative_to"))
    return {name for name in names if name}


# --------------------------------------------------------------------------- #
# measurements
# --------------------------------------------------------------------------- #
def _duration_measurement(shot_id: str, planned_s: float,
                          declared_s: Optional[float],
                          metric: str = "duration") -> Dict[str, Any]:
    equal = declared_s is not None and abs(planned_s - declared_s) < 1e-9
    provenance = "script_declaration" if equal else "plan_intent"
    return {
        "measurement_id": f"m_{shot_id}_{metric}",
        "shot_id": shot_id, "transition_id": None, "subject_id": None,
        "frame": None, "metric": metric,
        "value": round(planned_s, 3),
        "expected": declared_s, "unit": "seconds",
        "source": provenance, "provenance": provenance,
    }


def _composition_measurement(shot_id: str, score, threshold: float,
                             measurement_id: str) -> Dict[str, Any]:
    return {
        "measurement_id": measurement_id,
        "shot_id": shot_id, "transition_id": None, "subject_id": None,
        "frame": None, "metric": "composition_score",
        "value": round(float(score), 2), "expected": threshold,
        "unit": "score_0_100", "source": "blender_geometry",
        "provenance": "blender_geometry",
        "note": "取首/中/尾三帧审核分数（构图为镜头最小值）",
    }


def _guard_measurements(warning: Dict[str, Any],
                        measurement_ids: List[str]) -> List[Dict[str, Any]]:
    """一条 guard 告警 → 0..2 条测量（只抄 evidence 里的实测值）。"""
    shot_id = str(warning.get("shot_id") or "scene")
    subject = warning.get("subject") or None
    kind = str(warning.get("type") or "")
    evidence = dict(warning.get("evidence") or {})
    if kind == "jump_cut_risk":
        out: List[Dict[str, Any]] = []
        previous = evidence.get("previous_shot")
        transition_id = (f"t_{previous}_{shot_id}" if previous else None)
        if "angle_diff_deg" in evidence:
            mid = f"m_{shot_id}_camera_angle_deg"
            measurement_ids.append(mid)
            out.append({
                "measurement_id": mid, "shot_id": shot_id,
                "transition_id": transition_id, "subject_id": None,
                "frame": None, "metric": "camera_angle_deg",
                "value": round(float(evidence["angle_diff_deg"]), 3),
                "expected": evidence.get("jump_cut_angle_deg"),
                "unit": "degrees", "source": "blender_geometry",
                "provenance": "blender_geometry",
                "note": f"jump_cut_risk（与 {previous} 相邻）",
            })
        if "size_diff" in evidence:
            mid = f"m_{shot_id}_shot_size_delta"
            measurement_ids.append(mid)
            out.append({
                "measurement_id": mid, "shot_id": shot_id,
                "transition_id": transition_id, "subject_id": None,
                "frame": None, "metric": "shot_size_delta",
                "value": round(float(evidence["size_diff"]), 4),
                "expected": evidence.get("jump_cut_size_diff"),
                "unit": "ratio", "source": "blender_geometry",
                "provenance": "blender_geometry",
                "note": "jump_cut_risk 的景别占比差",
            })
        return out
    if kind == "pace_monotony":
        return []
    metric, value_key, expected_key, unit = _GUARD_TO_METRIC.get(
        kind, ("visibility_ratio", "visible_ratio", "", "ratio"))
    value = None
    if value_key and value_key in evidence:
        value = evidence[value_key]
    elif kind == "subject_out_of_frame":
        value = 0.0
    expected = evidence.get(expected_key) if expected_key else None
    note = f"guard {kind}（帧 {warning.get('frame_range')}）"
    if not value_key:
        note = f"guard {kind}（无数值估读，见 note）"
    measurement_ids.append(f"m_{shot_id}_{metric}")
    return [{
        "measurement_id": f"m_{shot_id}_{metric}",
        "shot_id": shot_id, "transition_id": None, "subject_id": subject,
        "frame": None, "metric": metric, "value": value, "expected": expected,
        "unit": unit, "source": "blender_geometry",
        "provenance": "blender_geometry", "note": note,
    }]


# --------------------------------------------------------------------------- #
# verdicts
# --------------------------------------------------------------------------- #
def _finding_verdict(finding: AuditError, *, evidence: Sequence[str],
                     provenance: str = "plan_intent",
                     expected=None, actual=None, threshold=None,
                     unit: str = "none") -> Dict[str, Any]:
    status = _STATUS_ORDER.get(finding.severity, "pass")
    return {
        "verdict_id": f"v_{finding.rule}_{'|'.join(evidence) or 'none'}",
        "shot_id": str(finding.target or "scene"),
        "transition_id": None,
        "rule_code": str(finding.rule),
        "status": status,
        "severity": _SEVERITY_ORDER.get(finding.severity, "info"),
        "expected": expected, "actual": actual, "threshold": threshold,
        "unit": unit, "evidence": list(evidence),
        "provenance": provenance, "message": finding.message,
        "suggestion": finding.suggestion,
    }


def _verdict(shot_id: str, rule_code: str, status: str, severity: str, *,
             expected, actual, threshold, unit: str,
             evidence: Sequence[str], provenance: str,
             message: str, suggestion: str = "",
             transition_id: Optional[str] = None,
             counter: int = 0) -> Dict[str, Any]:
    suffix = f"_{counter}" if counter else ""
    verdict_id = f"v_{shot_id}_{rule_code}{suffix}".replace(" ", "_")
    return {
        "verdict_id": verdict_id, "shot_id": shot_id,
        "transition_id": transition_id, "rule_code": rule_code,
        "status": status, "severity": severity,
        "expected": expected, "actual": actual, "threshold": threshold,
        "unit": unit, "evidence": list(evidence),
        "provenance": provenance, "message": message,
        "suggestion": suggestion,
    }


# --------------------------------------------------------------------------- #
# prescriptions
# --------------------------------------------------------------------------- #
def build_prescriptions(*, plan: Plan, parsed=None, brief=None,
                        plan_findings: Optional[Sequence[AuditError]] = None,
                        shot_audits: Optional[Dict[str, Dict[str, Any]]] = None,
                        fps: int = 24) -> List[Dict[str, Any]]:
    """把计划级发现 + guard 数值证据折成处方（只允许注册操作）。"""
    prescriptions: List[Dict[str, Any]] = []
    known = _brief_names(brief)
    for finding in list(plan_findings or []):
        if str(finding.rule) == "SR001":
            target = next((s for s in plan.shots
                           if s.shot_id == finding.target), None)
            responsibility = getattr(target, "responsibility", None)
            white_model = list(getattr(responsibility, "white_model", []) or [])
            recovered = [name for name in white_model if str(name) in known]
            prescriptions.append({
                "prescription_id": "p_restore_cast",
                "shot_id": str(finding.target or "scene"),
                "operation": "restore_cast",
                "parameters": {"source": "responsibility.white_model",
                               "characters": recovered},
                "precondition_measurement_ids": [],
                "postcondition_measurement_ids": [],
                "postcondition": "每个需要白模的镜头 characters 非空且只含已确认角色",
                "applied": bool(recovered),
                "applied_at": None, "waived": False, "waive_reason": "",
            })
        elif str(finding.rule) == "SR002":
            declared_total = getattr(parsed, "declared_total_seconds", None)
            if declared_total is not None:
                actual = plan.total_frames / float(fps)
                prescriptions.append({
                    "prescription_id": "p_total_duration",
                    "shot_id": "scene", "operation": "retime_shot",
                    "parameters": {
                        "declared_total_seconds": declared_total,
                        "actual_total_seconds": round(actual, 3),
                    },
                    "precondition_measurement_ids": ["m_scene_total_duration"],
                    "postcondition_measurement_ids": ["m_scene_total_duration"],
                    "postcondition": "全场时长回到声明总时长（±0.2s）",
                    "applied": abs(actual - declared_total) <= 0.2,
                    "applied_at": None, "waived": False, "waive_reason": "",
                })
    for shot_id, record in (shot_audits or {}).items():
        for warning in record.get("guard_warnings") or []:
            kind = str(warning.get("type") or "")
            evidence = dict(warning.get("evidence") or {})
            if kind == "jump_cut_risk":
                prescriptions.append({
                    "prescription_id": f"p_transition_{shot_id}",
                    "shot_id": shot_id,
                    "operation": "review_transition",
                    "parameters": {
                        "from": evidence.get("previous_shot"), "to": shot_id,
                        "angle_degrees": evidence.get("angle_diff_deg"),
                        "required_degrees": evidence.get("jump_cut_angle_deg"),
                        "alternative": "change_shot_size",
                    },
                    "precondition_measurement_ids": [
                        f"m_{shot_id}_camera_angle_deg"],
                    "postcondition_measurement_ids": [
                        f"m_{shot_id}_camera_angle_deg"],
                    "postcondition": "角度 >= 30° 或景别至少变化一档",
                    "applied": False, "applied_at": None,
                    "waived": False, "waive_reason": "",
                    "note": "待处理处方：需 LLM/人裁决机位或景别",
                })
            elif kind in ("subject_not_visible", "edge_clip",
                          "framing_too_tight", "framing_too_loose",
                          "occlusion", "subject_out_of_frame"):
                metric = _GUARD_TO_METRIC.get(
                    kind, ("visibility_ratio", "", "", "ratio"))[0]
                prescriptions.append({
                    "prescription_id": f"p_{shot_id}_{kind}",
                    "shot_id": shot_id, "operation": "reframe",
                    "parameters": {"reason": kind,
                                   "target": warning.get("subject")},
                    "precondition_measurement_ids": [f"m_{shot_id}_{metric}"],
                    "postcondition_measurement_ids": [
                        f"m_{shot_id}_composition_score"],
                    "postcondition": "全镜 visible_ratio > 0 且 composition_score > 80",
                    "applied": False, "applied_at": None,
                    "waived": False, "waive_reason": "",
                    "note": "相机类处方不自动执行：进入修复提示由模型走工具",
                })
    return prescriptions


def apply_plan_prescriptions(plan: Plan,
                             prescriptions: Sequence[Dict[str, Any]],
                             *, brief=None, fps: int = 24,
                             ) -> Tuple[Plan, List[Dict[str, Any]]]:
    """应用计划级确定性处方（restore_cast / retime_shot），其余保持待处理。

    * ``restore_cast``：从 responsibility.white_model ∩ brief 已知名恢复
      ``characters``（不发明角色）；
    * ``retime_shot``：把全场时长改回声明的总秒数（记录 old/new 帧与对白策略）；
    * 相机类（reframe / move_character / change_camera_side）与
      ``review_transition`` 不自动执行——返回 ``applied=False`` 且保持可见。

    返回 ``(plan, applied_records)``；applied_records 每条带
    ``prescription_id / operation / shot_id / applied / old_frames /
    new_frames / dialogue_policy``（未应用的操作也可见，applied=False）。
    """
    known = _brief_names(brief)
    records: List[Dict[str, Any]] = []
    by_shot = {shot.shot_id: shot for shot in plan.shots}
    for prescription in prescriptions:
        operation = str(prescription.get("operation") or "")
        if operation not in PRESCRIPTION_OPERATIONS:
            raise ValueError(f"未知处方操作 {operation!r}")
        shot_id = str(prescription.get("shot_id") or "scene")
        record: Dict[str, Any] = {
            "prescription_id": prescription.get("prescription_id"),
            "operation": operation, "shot_id": shot_id,
            "applied": False, "old_frames": None, "new_frames": None,
            "dialogue_policy": "preserved",
        }
        if operation == "restore_cast" and shot_id in by_shot:
            shot = by_shot[shot_id]
            if not shot.characters:
                responsibility = getattr(shot, "responsibility", None)
                white_model = list(getattr(responsibility,
                                           "white_model", []) or [])
                recovered = [name for name in white_model
                             if str(name) in known]
                if recovered:
                    shot.characters = recovered
                    record["applied"] = True
            else:
                record["applied"] = True
        elif operation == "retime_shot" and shot_id == "scene":
            params = dict(prescription.get("parameters") or {})
            declared_total = params.get("declared_total_seconds")
            if declared_total is not None:
                declared_frames = int(round(float(declared_total) * fps))
                old_total = max(plan.total_frames, 1)
                ratio = declared_frames / old_total
                old_frames: List[int] = []
                new_frames: List[int] = []
                for shot in plan.shots:
                    old_frames.append(shot.duration_frames)
                    shot.duration_frames = max(int(round(shot.duration_frames
                                                         * ratio)), 1)
                    new_frames.append(shot.duration_frames)
                record["old_frames"] = old_frames
                record["new_frames"] = new_frames
                record["dialogue_policy"] = (
                    "preserved（不删对白；超出时长由对白审核另行发现）")
                record["applied"] = True
        records.append(record)
    return plan, records


# --------------------------------------------------------------------------- #
# 文档折档
# --------------------------------------------------------------------------- #
def build_observation(*, plan: Plan, parsed=None, brief=None,
                      shot_audits: Optional[Dict[str, Dict[str, Any]]] = None,
                      build_results: Optional[Dict[str, Dict[str, Any]]] = None,
                      fps: int = 24,
                      run_context: Optional[Dict[str, Any]] = None,
                      observation_id: str = "obs-blockdirector",
                      plan_findings: Optional[Sequence[AuditError]] = None,
                      prescriptions: Optional[Sequence[Dict[str, Any]]] = None,
                      applied_prescriptions: Optional[Sequence[Dict[str, Any]]] = None,
                      ) -> Dict[str, Any]:
    """把运行产物折成 v2 观测文档（纯函数，确定性）。"""
    registry = _load_registry()
    declared = _declared_map(parsed)
    audits = dict(shot_audits or {})
    build = dict(build_results or {})
    pass_score = float(registry.get("composition", {}).get("pass_score", 80.0))
    fps = int(fps or 24)

    shot_specs: List[Dict[str, Any]] = []
    camera_specs: List[Dict[str, Any]] = []
    for order, shot in enumerate(plan.shots, start=1):
        decl = declared.get(int(getattr(shot, "declared_shot_number", 0)
                                or order))
        declared_s = (float(decl.declared_seconds)
                      if decl is not None and decl.declared_seconds is not None
                      else None)
        declared_frames = (int(round(declared_s * fps))
                           if declared_s is not None else None)
        shot_specs.append({
            "shot_id": shot.shot_id, "order": shot.order or order,
            "declared": {
                "seconds": declared_s, "frames": declared_frames,
                "shot_type": (str(getattr(decl, "shot_type", "") or "")
                              if decl is not None else None),
                "characters": (list(getattr(decl, "characters", []) or [])
                               if decl is not None else []),
            },
            "planned": {
                "seconds": round(shot.duration_frames / fps, 3),
                "frames": int(shot.duration_frames),
                "shot_type": str(shot.shot_type),
                "characters": list(shot.characters),
            },
        })
        cam = dict(getattr(shot, "camera", None) or {})
        measured = build.get(shot.shot_id) or {}
        has_measured = "camera_position" in measured
        camera_specs.append({
            "shot_id": shot.shot_id, "shot_type": str(shot.shot_type),
            "lens": (float(measured.get("lens"))
                     if measured.get("lens") is not None
                     else (float(cam["lens"]) if cam.get("lens") is not None
                           else None)),
            "frame_height": None, "distance": None,
            "side": cam.get("side") or None,
            "direction": cam.get("direction") or None,
            "position": measured.get("camera_position") or None,
            "target": measured.get("camera_target") or None,
            "camera_height": None,
            "aim_offset_x": None, "aim_offset_y": None,
            "sensor_width": 36.0, "aspect": 16.0 / 9.0,
            "clamped": False,
            "source": "blender_geometry" if has_measured else "plan_intent",
            **( {"note": "机位世界坐标本次未落盘，诚实标 null"}
                if not has_measured else {}),
        })

    measurements: List[Dict[str, Any]] = []
    measurement_ids: List[str] = []
    declared_total = getattr(parsed, "declared_total_seconds", None)
    total_s = plan.total_frames / fps
    measurements.append(_duration_measurement(
        "scene", total_s, declared_total, metric="total_duration"))
    measurement_ids.append("m_scene_total_duration")
    for shot in plan.shots:
        decl = declared.get(int(getattr(shot, "declared_shot_number", 0)
                                or 0))
        declared_s = (float(decl.declared_seconds)
                      if decl is not None and decl.declared_seconds is not None
                      else None)
        mid = f"m_{shot.shot_id}_duration"
        measurements.append(_duration_measurement(
            shot.shot_id, shot.duration_frames / fps, declared_s))
        measurement_ids.append(mid)
        mid = f"m_{shot.shot_id}_cast_presence"
        measurements.append({
            "measurement_id": mid, "shot_id": shot.shot_id,
            "transition_id": None, "subject_id": None, "frame": None,
            "metric": "cast_presence",
            "value": 1 if shot.characters else 0, "expected": 1,
            "unit": "none", "source": "plan_intent",
            "provenance": "plan_intent",
        })
        measurement_ids.append(mid)
        record = audits.get(shot.shot_id) or {}
        score = record.get("score")
        if score is not None:
            mid = f"m_{shot.shot_id}_composition_score"
            measurements.append(_composition_measurement(
                shot.shot_id, score, pass_score, mid))
            measurement_ids.append(mid)
        for warning in record.get("guard_warnings") or []:
            measurements.extend(_guard_measurements(warning, measurement_ids))

    #: v1.7 空间尺（Ticket 04+）：把逐镜几何实测（``ruler_probe`` 采集，挂在
    #: ``AuditResult.ruler_measurements`` / ``shot_audit`` 事件的
    #: ``ruler_measurements``）折进测量段。按 ``measurement_id`` 去重——保留本
    #: 模块先折的（带 expected/threshold 语义），不覆盖、不重复；两条来源
    #: （driver 内存路径 + 审计日志重放路径）共用同一折档逻辑。
    existing_ids = set(measurement_ids)
    for record in audits.values():
        if not isinstance(record, dict):
            continue
        for item in record.get("ruler_measurements") or []:
            if not isinstance(item, dict) or not item.get("measurement_id"):
                continue
            mid = str(item["measurement_id"])
            if mid in existing_ids:
                continue
            measurements.append(dict(item))
            measurement_ids.append(mid)
            existing_ids.add(mid)

    verdicts: List[Dict[str, Any]] = []
    if declared_total is not None:
        delta = abs(total_s - declared_total)
        verdicts.append(_verdict(
            "scene", "SR002",
            "pass" if delta <= 0.2 else "repair",
            "info" if delta <= 0.2 else "error",
            expected=declared_total, actual=round(total_s, 3),
            threshold=0.2, unit="seconds",
            evidence=["m_scene_total_duration"],
            provenance="script_declaration",
            message=(f"全场时长 {total_s:g}s 与声明 {declared_total:g}s "
                     + ("一致" if delta <= 0.2 else "不一致")),
            counter=0))
    for index, shot in enumerate(plan.shots):
        record = audits.get(shot.shot_id) or {}
        score = record.get("score")
        #: 转正：原审核器的规则 findings（R001–R025 等）折进 verdicts——规则
        #: 层的 errors/warnings 是既有审核的真源，观测文档**只折不改**：
        #: error → status=repair/severity=error；warning → warning。缺失时
        #: 不给 verdict（诚实标缺，不猜规则通过）。
        for finding in (list(record.get("errors") or [])
                        + list(record.get("warnings") or [])):
            if not isinstance(finding, dict) or not finding.get("rule"):
                continue
            severity = str(finding.get("severity") or "error").lower()
            is_error = severity == "error"
            verdicts.append(_verdict(
                shot.shot_id, str(finding["rule"]),
                "repair" if is_error else "warning",
                "error" if is_error else "warning",
                expected=None, actual=None, threshold=None, unit="none",
                evidence=[], provenance="algorithmic_measurement",
                message=str(finding.get("message") or ""),
                suggestion=str(finding.get("suggestion") or ""),
                counter=len(verdicts)))
        if score is not None:
            mid = f"m_{shot.shot_id}_composition_score"
            #: 用户 2026-10-18 裁决：构图分必须严格高于 80，
            #: score == pass_score 不算通过。
            passed = float(score) > pass_score
            verdicts.append(_verdict(
                shot.shot_id, "COMPOSITION",
                "pass" if passed else "repair",
                "info" if passed else "error",
                expected=pass_score, actual=round(float(score), 2),
                threshold=pass_score, unit="score_0_100",
                evidence=[mid], provenance="blender_geometry",
                message=(f"构图评分 {score:g}，"
                         + ("通过" if passed
                            else f"低于阈值 {pass_score:g}")),
                counter=index))
        for warning in record.get("guard_warnings") or []:
            kind = str(warning.get("type") or "")
            severity = str(warning.get("severity") or "warning")
            rule_code = "R010" if kind == "jump_cut_risk" else kind
            evidence = dict(warning.get("evidence") or {})
            if kind == "jump_cut_risk":
                evidence_refs = [f"m_{shot.shot_id}_camera_angle_deg"]
            else:
                metric = _GUARD_TO_METRIC.get(
                    kind, ("visibility_ratio", "", "", "ratio"))[0]
                candidate = f"m_{shot.shot_id}_{metric}"
                evidence_refs = ([candidate]
                                 if candidate in measurement_ids else [])
            status = "repair" if severity == "error" else "warning"
            if kind == "jump_cut_risk":
                # R010 的对照阈值直接取 guard 证据里的跳切角差门限。
                verdict_threshold = evidence.get("jump_cut_angle_deg")
                verdict_unit = "degrees"
            else:
                verdict_threshold = None
                verdict_unit = "none"
            verdicts.append(_verdict(
                shot.shot_id, rule_code, status, severity,
                expected=None, actual=None, threshold=verdict_threshold,
                unit=verdict_unit,
                evidence=evidence_refs, provenance="blender_geometry",
                message=(f"guard {kind}（{warning.get('subject')}，"
                         f"帧 {warning.get('frame_range')}）"),
                suggestion=str(warning.get("suggestion_hint") or ""),
                transition_id=(f"t_{evidence.get('previous_shot')}_{shot.shot_id}"
                               if kind == "jump_cut_risk" else None),
                counter=len(verdicts)))

    for finding in list(plan_findings or []):
        if str(finding.rule) == "SR001":
            target = str(finding.target or "scene")
            evidence = [f"m_{target}_cast_presence"
                        if f"m_{target}_cast_presence" in measurement_ids
                        else "m_scene_total_duration"]
            verdicts.append(_finding_verdict(
                finding, evidence=evidence))

    #: 空间尺转正：逐镜六层评测（``RulerReview.to_dict()`` 形状，挂在
    #: ``AuditResult.ruler_review`` / ``shot_audit`` 事件的 ``ruler_review``）。
    #: 与 verdicts 并置：六层分/硬门/读数/失败项/处方是审核主层的独立输出，
    #: 不折进 measurement 段（那里只放契约 measurement 形状的几何测量）。
    #: 没有跑出评测的镜头不在 dict 里（"没审过"与"审了 0 分"分得开）。
    ruler_reviews: Dict[str, Any] = {}
    for shot in plan.shots:
        record = audits.get(shot.shot_id) or {}
        review = record.get("ruler_review")
        if isinstance(review, dict) and review.get("shot_id"):
            ruler_reviews[str(shot.shot_id)] = dict(review)

    if prescriptions is None:
        prescriptions = build_prescriptions(
            plan=plan, parsed=parsed, brief=brief, plan_findings=plan_findings,
            shot_audits=audits, fps=fps)
    if applied_prescriptions:
        #: 转正：驱动自动 reframe 等**已执行**处方回写。按 prescription_id
        #: 覆盖默认生成的未应用版本——同一镜同一操作只允许一个生命周期状态，
        #: 避免"已应用"与"未应用"自相矛盾；未被覆盖的默认处方（如
        #: review_transition）原样保留。
        #: 合并是**补丁语义**：已应用版本里缺省的字段（operation /
        #: measurement ids / postcondition 等）沿用默认版本，只有显式给出的
        #: 字段覆盖——驱动侧只需记 prescription_id + applied 状态 + 执行参数，
        #: 不必重复维护整套字段，避免两处漂移。
        by_id: Dict[str, Dict[str, Any]] = {}
        for item in prescriptions:
            if isinstance(item, dict) and item.get("prescription_id"):
                by_id[str(item["prescription_id"])] = dict(item)
        for item in applied_prescriptions:
            if not isinstance(item, dict) or not item.get("prescription_id"):
                continue
            key = str(item["prescription_id"])
            base = by_id.get(key)
            merged = dict(item)
            if base:
                for field, value in base.items():
                    merged.setdefault(field, value)
            by_id[key] = merged
        prescriptions = list(by_id.values())

    return {
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id,
        "run_context": dict(run_context or {
            "source_run": "blockdirector", "status": "completed",
        }),
        "plugin_adapter": {
            "consumer": "BlockDirector.audit",
            "phase": ["pre_build", "post_build"],
            "blocking_policy": {"error": "blocks", "warning": "persists"},
            "integration_status": (
                "full" if any(bool(item.get("applied")) and
                               item.get("operation") in {"reframe", "move_character", "change_camera_side"}
                               for item in (prescriptions or []))
                else "full_pre_build"),
            "note": "空间尺已作为插件内置审核层；相机处方按运行记录标记执行状态",
        },
        "observation_request": {
            "targets": [
                {
                    "shot_id": shot.shot_id,
                    "subject_ids": list(shot.characters),
                    "metrics": ["composition_score", "visibility_ratio",
                                "camera_angle_deg", "duration"],
                    "sampling": {"frames": ["first", "middle", "last"],
                                 "step": 4},
                }
                for shot in plan.shots
            ],
            "coordinate_system": "normalized_screen_0_1",
            "fps": fps,
        },
        "registry": registry,
        "shot_specs": shot_specs,
        "camera_specs": camera_specs,
        "measurements": measurements,
        "verdicts": verdicts,
        "ruler_reviews": ruler_reviews,
        "prescriptions": list(prescriptions),
    }


def write_observation(doc: Dict[str, Any], export_dir) -> Path:
    """把观测文档写进交付目录；返回写入路径。"""
    path = Path(export_dir) / "ruler_observation.json"
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    return path


def shot_audits_from_log(records: Sequence[Dict[str, Any]],
                         ) -> Dict[str, Dict[str, Any]]:
    """从审计日志的 ``shot_audit`` / ``guard_warning`` 事件重建审核字典。

    与 ``AuditResult.to_dict()`` 的形状对齐：``{shot_id: {passed, score,
    errors, warnings, guard_warnings}}``，其中 ``guard_warnings`` 是
    ``GuardWarning.to_dict()`` 的普通 dict 列表。没有事件就给出空表——
    ``build_observation`` 对缺审镜头诚实标缺（零猜测）。
    """
    audits: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if record.get("kind") != "shot_audit":
            continue
        data = dict(record.get("data") or {})
        shot_id = str(data.get("shot") or "")
        if not shot_id:
            continue
        entry = audits.setdefault(shot_id, {
            "passed": True, "score": None, "errors": [],
            "warnings": [], "guard_warnings": [],
        })
        entry["passed"] = bool(data.get("passed", True))
        entry["score"] = data.get("composition_score")
        review = data.get("ruler_review")
        if isinstance(review, dict):
            entry["ruler_review"] = dict(review)
        findings = list(data.get("findings") or [])
        entry["errors"] = [
            item for item in findings
            if str(item.get("severity") or "error") in ("error", "ERROR")]
        entry["warnings"] = [
            item for item in findings
            if str(item.get("severity") or "error") not in ("error", "ERROR")]
        ruler_items = [
            dict(item) for item in data.get("ruler_measurements") or []
            if isinstance(item, dict)]
        if ruler_items:
            entry["ruler_measurements"] = ruler_items
    for record in records:
        if record.get("kind") != "guard_warning":
            continue
        data = dict(record.get("data") or {})
        shot_id = str(data.get("shot_id") or "")
        if not shot_id:
            continue
        entry = audits.setdefault(shot_id, {
            "passed": True, "score": None, "errors": [],
            "warnings": [], "guard_warnings": [],
        })
        entry["guard_warnings"].extend(list(data.get("warnings") or []))
    return audits


def plan_findings_from_log(records: Sequence[Dict[str, Any]],
                           ) -> List[AuditError]:
    """取最后一次 ``spatial_ruler_plan_audit`` 事件的 findings（SR001/SR002）。"""
    findings: List[AuditError] = []
    for record in records:
        if record.get("kind") != "spatial_ruler_plan_audit":
            continue
        data = dict(record.get("data") or {})
        findings = [AuditError.from_dict(item)
                    for item in data.get("findings") or []
                    if isinstance(item, dict)]
    return findings


def build_observation_from_log(records: Sequence[Dict[str, Any]], plan: Plan,
                               *, parsed=None, brief=None,
                               build_summary: Optional[Dict[str, Any]] = None,
                               fps: int = 24,
                               applied_prescriptions: Optional[Sequence[Dict[str, Any]]] = None,
                               run_context: Optional[Dict[str, Any]] = None,
                               observation_id: str = "obs-blockdirector-replay"
                               ) -> Dict[str, Any]:
    """重放折档：只读 ``audit_log.jsonl`` 重建观测（无 LLM、无 bpy）。

    数据源全部来自日志事件与重放建场景的 ``build_summary``：
    * ``shot_audit`` / ``guard_warning`` → 审核字典；
    * ``spatial_ruler_plan_audit`` → SR001/SR002 findings；
    * ``build_summary.results`` → 相机实测（lens / camera_position）。
    缺事件（旧日志）时给空表，产物仍过结构校验——诚实标缺，不猜。
    """
    shot_audits = shot_audits_from_log(records)
    plan_findings = plan_findings_from_log(records)
    build_results: Dict[str, Dict[str, Any]] = {}
    for item in (build_summary or {}).get("results") or []:
        if isinstance(item, dict) and item.get("shot_id"):
            build_results[str(item["shot_id"])] = dict(item)
    return build_observation(
        plan=plan, parsed=parsed, brief=brief, shot_audits=shot_audits,
        build_results=build_results, fps=fps, run_context=run_context,
        observation_id=observation_id, plan_findings=plan_findings,
        applied_prescriptions=applied_prescriptions)


def validate_observation(doc: Dict[str, Any]) -> List[str]:
    """结构化校验（纯层、快速）：闭集 / 来源四态 / verdict 三件套 / 引用闭合。"""
    findings: List[str] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        findings.append(f"schema_version 必须为 {SCHEMA_VERSION!r}")
    if doc.get("plugin_adapter", {}).get("integration_status") not in {
            "planned", "partial_plan_level_only", "full_pre_build",
            "full_post_build", "full"}:
        findings.append("plugin_adapter.integration_status 非法")
    measurement_ids = {m.get("measurement_id")
                       for m in doc.get("measurements", [])}
    for measurement in doc.get("measurements", []):
        source = measurement.get("source")
        if source not in _PROVENANCE_STATES:
            findings.append(
                f"{measurement.get('measurement_id')} source 非法：{source}")
        if source != measurement.get("provenance"):
            findings.append(
                f"{measurement.get('measurement_id')} source!=provenance")
    for verdict in doc.get("verdicts", []):
        for key in ("expected", "actual", "threshold", "unit"):
            if key not in verdict:
                findings.append(f"{verdict.get('verdict_id')} 缺 {key}")
        for ref in verdict.get("evidence", []) or []:
            if str(ref).startswith("m_") and ref not in measurement_ids:
                findings.append(
                    f"{verdict.get('verdict_id')} 证据引用不存在：{ref}")
    for shot_id, review in (doc.get("ruler_reviews") or {}).items():
        layer_scores = review.get("layer_scores") or {}
        if not isinstance(layer_scores, dict) or set(layer_scores) != {
                "geometry", "attention", "action", "continuity",
                "cinema", "robustness"}:
            findings.append(
                f"{shot_id} ruler_review 层键必须恰好为六层")
        if not isinstance(review.get("hard_gates") or [], list):
            findings.append(f"{shot_id} ruler_review.hard_gates 必须为数组")
    for prescription in doc.get("prescriptions", []):
        operation = prescription.get("operation")
        if operation not in PRESCRIPTION_OPERATIONS:
            findings.append(
                f"{prescription.get('prescription_id')} 未知 operation："
                f"{operation}")
        for ref in (prescription.get("precondition_measurement_ids", [])
                    + prescription.get("postcondition_measurement_ids", [])):
            if str(ref).startswith("m_") and ref not in measurement_ids:
                findings.append(
                    f"{prescription.get('prescription_id')} 引用不存在：{ref}")
    return findings


def attach_sequence_review(doc: Dict[str, Any], *, plan: Plan,
                           fps: int = 24) -> Dict[str, Any]:
    """在收尾阶段补一处序列级 continuity 复核（转正接缝，纯层无 bpy）。

    输入 ``doc`` 是已折好的观测文档（含逐镜 ``ruler_reviews``）；本函数
    向 ``scene`` 键追加一条 ``RulerReview``：逐镜五层沿用逐镜读数（只折不改），
    continuity 用**真实**的全场镜头链打分（补上逐镜审核时如实标缺的那一层）。

    实时路径由驱动器在 FINISHING 用 ``ruler_probe`` 全场采样一次后调用；
    重放路径（无 bpy）拿到 ``None`` 时原样返回（诚实标缺，不重算、不伪造）。
    """
    from ..cinema.ruler_review import run_ruler_review

    if doc.get("ruler_reviews") is None:
        doc["ruler_reviews"] = {}
    per_shot = doc.get("ruler_reviews") or {}
    per_shot = {str(k): dict(v) for k, v in per_shot.items()}
    continuity: Optional[Dict[str, Any]] = None
    if plan is not None and plan.shots:
        samples = _sequence_samples(plan)
        if samples is not None:
            try:
                continuity = run_ruler_review(
                    plan, samples, fps=fps).to_dict()
            except Exception:            # noqa: BLE001 - 序列复核失败如实缺
                continuity = None
    if continuity is not None:
        per_shot["scene"] = continuity
    doc["ruler_reviews"] = per_shot
    return doc


def _sequence_samples(plan: Plan):
    """全场逐镜采样一次（实时路径经 ``ruler_probe``，需 bpy）；否则 None。"""
    try:
        from .ruler_probe import collect_shot_samples
        return collect_shot_samples(plan)
    except Exception:                    # noqa: BLE001 - 无 bpy/失败 -> 缺
        return None

