"""逐镜细编排派生器（Ticket 04，纯层，不 import bpy）。

从冻结基准（coarse_world_baseline.json）+ plan 确定性派生逐镜细排数据
（DetailShotContract）。派生坐标必须与冻结基准一致（继承不漂移）；任何
需要改全局空间的点被标记为「退回粗排审批」而非静默修改。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from block_director.contracts.detail_blocking import (
    DETAIL_SHOT_SCHEMA_VERSION,
)

#: 派生坐标与冻结基准的允许偏差（米）。超过即视为空间漂移。
SPATIAL_DRIFT_TOLERANCE_M = 0.01

E_DETAIL_SPATIAL_DRIFT = "E_DETAIL_SPATIAL_DRIFT"

#: R2 07/S2：镜头身份冻结错误码。细排/精修/回溯不得改写分镜表声明的
#: ``characters``（主体集合）／``framing_target``（拍摄对象）／``shot_type``
#: （景别）；冲突即报此错误并保留计划声明。
E_IDENTITY_DRIFT = "E_IDENTITY_DRIFT"

#: A detail proposal may explain a local staging change only when the target
#: shot carries explicit Agent provenance.  This is separate from identity
#: freeze: it governs *where* a permitted revision may physically act.
E_DETAIL_SCOPE_VIOLATION = "E_DETAIL_SCOPE_VIOLATION"


def _vec3(value: Any) -> Dict[str, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return {"x": float(value[0]), "y": float(value[1]),
                    "z": float(value[2])}
        except (TypeError, ValueError):
            return None
    if isinstance(value, Mapping):
        try:
            return {k: float(value.get(k, 0.0)) for k in ("x", "y", "z")}
        except (TypeError, ValueError):
            return None
    return None


def _plan_shots(plan: Any) -> List[Mapping]:
    if isinstance(plan, Mapping):
        return list(plan.get("shots") or [])
    return list(getattr(plan, "shots", None) or [])


def _shot_by_id(plan_shots: List[Mapping]) -> Dict[str, Mapping]:
    return {str(s.get("shot_id") or ""): s for s in plan_shots}


def _character_by_name(reference: Mapping) -> Dict[str, Mapping]:
    return {str(c.get("name") or ""): c
            for c in reference.get("characters") or []}


def _prop_by_owner(reference: Mapping) -> Dict[str, List[Mapping]]:
    result: Dict[str, List[Mapping]] = {}
    for p in reference.get("props") or []:
        owner = str(p.get("owner") or "")
        result.setdefault(owner, []).append(p)
    return result


def _camera_intent(reference: Mapping, shot_id: str) -> Mapping | None:
    return next((c for c in reference.get("camera_intents") or []
                 if str(c.get("shot_id") or "") == shot_id), None)


def derive_detail_shots(
    *,
    baseline: Mapping[str, Any],
    plan: Any,
) -> List[Dict[str, Any]]:
    """从冻结基准 + plan 派生逐镜细排数据（确定性、零 LLM）。"""
    reference = baseline.get("reference") or {}
    plan_shots = _plan_shots(plan)
    by_shot = _shot_by_id(plan_shots)
    chars = _character_by_name(reference)
    props_by_owner = _prop_by_owner(reference)
    result: List[Dict[str, Any]] = []

    for shot in plan_shots:
        shot_id = str(shot.get("shot_id") or "")
        duration = int(shot.get("duration_frames") or 1)
        camera = _camera_intent(reference, shot_id)
        character_names = [str(n) for n in (shot.get("characters") or [])]
        #: R2 07/S2：身份字段（主体/拍摄对象/景别）随派生镜头一起携带，
        #: 供 ``identity_freeze_review`` 与计划声明逐镜对拍；缺失时不编造。
        declared_shot_type = str(shot.get("shot_type") or "")
        declared_framing_target = str(shot.get("framing_target") or "")
        detail_chars: List[Dict[str, Any]] = []
        for name in character_names:
            src = chars.get(name)
            base_position = _vec3(src.get("position")) if src else None
            detail_chars.append({
                "name": name,
                "position": base_position if base_position is not None
                else {"x": 0.0, "y": 0.0, "z": 0.0},
                "rotation": (dict(src["rotation"]) if src
                             and isinstance(src.get("rotation"), Mapping)
                             else None),
                "facing": (list(src.get("facing") or [0.0, 1.0, 0.0])
                           if src else [0.0, 1.0, 0.0]),
                "gaze": (dict(src["gaze"]) if src
                         and isinstance(src.get("gaze"), Mapping)
                         else None),
                "pose": None,
                "motion_beats": _motion_beats(shot),
                "source": "frozen_baseline",
            })
        detail_props: List[Dict[str, Any]] = []
        for name in character_names:
            for prop in props_by_owner.get(name, []):
                detail_props.append({
                    "id": str(prop.get("id") or ""),
                    "position": _vec3(prop.get("position")) or
                    {"x": 0.0, "y": 0.0, "z": 0.0},
                    "rotation": (dict(prop["rotation"])
                                 if isinstance(prop.get("rotation"), Mapping)
                                 else None),
                    "motion_beats": [],
                })
        camera_entry = {
            "position": _vec3(camera.get("position")) if camera else
            {"x": 0.0, "y": 5.0, "z": 1.6},
            "target": _vec3(camera.get("target")) if camera else
            {"x": 0.0, "y": 0.0, "z": 0.9},
            "lens_mm": float(camera.get("lens")
                             or camera.get("lens_mm")
                             or 35.0) if camera else 35.0,
            "movements": list(camera.get("movement") or []) if camera else [],
        }
        result.append({
            "schema_version": DETAIL_SHOT_SCHEMA_VERSION,
            "shot_id": shot_id,
            "order": int(shot.get("order") or len(result) + 1),
            "start_frame": _start_frame(plan_shots, shot_id),
            "end_frame": _end_frame(plan_shots, shot_id),
            "characters": detail_chars,
            "shot_type": declared_shot_type or None,
            "framing_target": declared_framing_target or None,
            "props": detail_props,
            "camera": camera_entry,
            "beats": _beats(shot, duration),
            "audio_proxy": [],
        })
    return result


def _order_before(by_shot: Dict[str, Mapping], s: Mapping,
                  shot_id: str) -> bool:
    """s 是否排在 shot_id 之前（按 order）。"""
    a = int(s.get("order") or 0)
    b = int(by_shot.get(shot_id, {}).get("order") or 0)
    return a < b


def _start_frame(plan_shots: List[Mapping], shot_id: str) -> int:
    total = 1
    for s in plan_shots:
        if str(s.get("shot_id") or "") == shot_id:
            return total
        total += int(s.get("duration_frames") or 1)
    return total


def _end_frame(plan_shots: List[Mapping], shot_id: str) -> int:
    total = 0
    for s in plan_shots:
        total += int(s.get("duration_frames") or 1)
        if str(s.get("shot_id") or "") == shot_id:
            return total
    return total


def _motion_beats(shot: Mapping) -> List[Dict[str, Any]]:
    """从每镜 action 生成骨架运动节拍（起始帧 + 动作描述代理）。"""
    beats: List[Dict[str, Any]] = []
    for action in shot.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        beats.append({
            "frame": 1,
            "action": str(action.get("action") or ""),
            "parameter": action.get("parameter"),
            "target": action.get("target"),
        })
    return beats


def _beats(shot: Mapping, duration: int) -> List[Dict[str, Any]]:
    """每镜节拍骨架：首/中/末帧 + 动作/表情/音频代理占位。"""
    return [{
        "frame": 1, "kind": "start", "note": "镜头起点",
        "actions": _motion_beats(shot),
    }, {
        "frame": max(duration // 2, 1), "kind": "mid", "note": "镜头中段",
        "actions": [],
    }, {
        "frame": max(duration, 1), "kind": "end", "note": "镜头终点",
        "actions": [],
    }]


def spatial_drift_review(
    detail_shots: List[Mapping[str, Any]],
    baseline: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """细排派生坐标 vs 冻结基准：超过容忍偏差 -> 退回粗排审批 finding。"""
    reference = baseline.get("reference") or {}
    base_chars = _character_by_name(reference)
    findings: List[Dict[str, Any]] = []
    for shot in detail_shots:
        shot_id = str(shot.get("shot_id") or "")
        for char in shot.get("characters") or []:
            if not isinstance(char, Mapping):
                continue
            name = str(char.get("name") or "")
            base_char = base_chars.get(name)
            if base_char is None:
                findings.append({
                    "check_id": E_DETAIL_SPATIAL_DRIFT,
                    "shot_id": shot_id,
                    "severity": "error",
                    "message": (f"角色 {name} 未在冻结基准中，细排引入全局"
                                f"空间变更，须退回粗排审批"),
                })
                continue
            base_pos = _vec3(base_char.get("position"))
            derived_pos = _vec3(char.get("position"))
            if base_pos is None or derived_pos is None:
                continue
            if _dist(base_pos, derived_pos) > SPATIAL_DRIFT_TOLERANCE_M:
                findings.append({
                    "check_id": E_DETAIL_SPATIAL_DRIFT,
                    "shot_id": shot_id,
                    "severity": "error",
                    "message": (f"角色 {name} 细排坐标偏离冻结基准 "
                                f"{_dist(base_pos, derived_pos):.3f} m，"
                                f"须退回粗排审批"),
                })
        camera = shot.get("camera") or {}
        intent = _camera_intent(reference, shot_id)
        if intent is not None:
            for key in ("position", "target"):
                base_v = _vec3(intent.get(key))
                derived_v = _vec3(camera.get(key))
                if base_v is not None and derived_v is not None \
                        and _dist(base_v, derived_v) > SPATIAL_DRIFT_TOLERANCE_M:
                    findings.append({
                        "check_id": E_DETAIL_SPATIAL_DRIFT,
                        "shot_id": shot_id,
                        "severity": "error",
                        "message": (f"相机 {key} 细排偏离冻结基准 "
                                    f"{_dist(base_v, derived_v):.3f} m，"
                                    f"须退回粗排审批"),
                    })
    return findings


def identity_freeze_review(
    *,
    detail_shots: List[Mapping[str, Any]],
    plan: Any,
) -> List[Dict[str, Any]]:
    """细排/精修后镜头身份与计划声明逐镜对拍（R2 07/S2）。

    冻结字段：``characters``（主体集合，集合相等判定）、``framing_target``、
    ``shot_type``。任何不一致 ⇒ E 类 error finding（拒绝应用，计划原样
    保留）；一致返回空表。相机/走位/道具/动作等非身份字段不在此检查范围。
    """
    plan_shots = _plan_shots(plan)
    by_shot = _shot_by_id(plan_shots)
    findings: List[Dict[str, Any]] = []
    for shot in detail_shots:
        shot_id = str(shot.get("shot_id") or "")
        declared = by_shot.get(shot_id)
        if declared is None:
            continue
        declared_chars = sorted(
            {str(n) for n in (declared.get("characters") or [])})
        actual_chars = sorted(
            {str(c.get("name") or "")
             for c in shot.get("characters") or []
             if isinstance(c, Mapping)})
        if actual_chars != declared_chars:
            findings.append({
                "check_id": E_IDENTITY_DRIFT,
                "shot_id": shot_id,
                "severity": "error",
                "path": f"{shot_id}.characters",
                "message": (f"镜头主体集合被精修改写：计划声明 "
                            f"{declared_chars}，实际 {actual_chars}；"
                            f"分镜表是剧本的产物，精修不得越权改分镜"),
            })
        for key, label in (("framing_target", "拍摄对象"),
                           ("shot_type", "景别")):
            declared_value = str(declared.get(key) or "")
            actual_value = str(shot.get(key) or "")
            if not declared_value:
                continue
            if actual_value != declared_value:
                findings.append({
                    "check_id": E_IDENTITY_DRIFT,
                    "shot_id": shot_id,
                    "severity": "error",
                    "path": f"{shot_id}.{key}",
                    "message": (f"{label}被精修改写：计划声明 "
                                f"{declared_value!r}，实际 {actual_value!r}；"
                                f"精修不得越权改分镜"),
                })
    return findings


def reference_scope_review(
    *,
    previous: Mapping[str, Any],
    candidate: Mapping[str, Any],
    shot_id: str,
    mode: str = "revision",
) -> List[Dict[str, Any]]:
    """Validate that a candidate mutation is confined to one shot.

    Revision candidates must carry ``agent_local_revision`` provenance for
    every target-shot physical drift.  Restore candidates replay an already
    retained best state, so the target camera may return to its earlier value
    without masquerading as a new Agent revision.  Neighbor and global state
    remain immutable in both modes.
    """
    if mode not in {"revision", "restore"}:
        raise ValueError(f"unknown detail scope mode: {mode}")
    target_shot = str(shot_id)
    findings: List[Dict[str, Any]] = []
    overlays = candidate.get("shot_staging")
    previous_overlays = previous.get("shot_staging")
    previous_staging = (
        previous_overlays if isinstance(previous_overlays, Mapping) else {})
    candidate_staging = (
        overlays if isinstance(overlays, Mapping) else {})
    for neighbor_id in sorted(
            {str(key) for key in previous_staging}
            | {str(key) for key in candidate_staging}):
        if not neighbor_id or neighbor_id == target_shot:
            continue
        if candidate_staging.get(neighbor_id) != previous_staging.get(
                neighbor_id):
            findings.append({
                "check_id": E_DETAIL_SCOPE_VIOLATION,
                "shot_id": target_shot,
                "severity": "error",
                "path": f"shot_staging.{neighbor_id}",
                "message": (
                    f"detail revision for {target_shot} changed neighbor "
                    f"staging {neighbor_id}"),
            })
    target_overlay = (
        (overlays.get(target_shot) or {})
        if isinstance(overlays, Mapping)
        else {}
    )
    if not isinstance(target_overlay, Mapping):
        return [{
            "check_id": E_DETAIL_SCOPE_VIOLATION,
            "shot_id": target_shot,
            "severity": "error",
            "path": f"shot_staging.{target_shot}",
            "message": "target-shot staging must be an object",
        }]
    for name, raw_entry in target_overlay.items():
        entry = raw_entry if isinstance(raw_entry, Mapping) else {}
        if str(entry.get("provenance") or "") != "agent_local_revision":
            findings.append({
                "check_id": E_DETAIL_SCOPE_VIOLATION,
                "shot_id": target_shot,
                "severity": "error",
                "path": f"shot_staging.{target_shot}.{name}.provenance",
                "message": (
                    f"local staging for {name} in {target_shot} lacks "
                    "agent_local_revision provenance"),
            })
    if candidate.get("characters") != previous.get("characters"):
        findings.append({
            "check_id": E_DETAIL_SCOPE_VIOLATION,
            "shot_id": target_shot,
            "severity": "error",
            "path": "characters",
            "message": (
                "detail revisions may not move the global character "
                "continuity baseline; use target-shot staging"),
        })
    previous_cameras = {
        str(row.get("shot_id") or ""): row
        for row in (previous.get("camera_intents") or [])
        if isinstance(row, Mapping)
    }
    candidate_cameras = {
        str(row.get("shot_id") or ""): row
        for row in (candidate.get("camera_intents") or [])
        if isinstance(row, Mapping)
    }
    for neighbor_id in sorted(set(previous_cameras) | set(candidate_cameras)):
        if not neighbor_id or neighbor_id == target_shot:
            continue
        if candidate_cameras.get(neighbor_id) != previous_cameras.get(
                neighbor_id):
            findings.append({
                "check_id": E_DETAIL_SCOPE_VIOLATION,
                "shot_id": target_shot,
                "severity": "error",
                "path": f"camera_intents.{neighbor_id}",
                "message": (
                    f"detail revision for {target_shot} changed neighbor "
                    f"camera {neighbor_id}"),
            })
    previous_target_camera = previous_cameras.get(target_shot)
    candidate_target_camera = candidate_cameras.get(target_shot)
    if mode == "revision" \
            and candidate_target_camera != previous_target_camera:
        provenance = (
            candidate_target_camera.get("provenance")
            if isinstance(candidate_target_camera, Mapping) else None
        )
        if str(provenance or "") != "agent_local_revision":
            findings.append({
                "check_id": E_DETAIL_SCOPE_VIOLATION,
                "shot_id": target_shot,
                "severity": "error",
                "path": f"camera_intents.{target_shot}.provenance",
                "message": (
                    f"camera drift for {target_shot} lacks "
                    "agent_local_revision provenance"),
            })

    target_shots = {
        str(row.get("shot_id") or ""): row
        for row in (candidate.get("shots") or [])
        if isinstance(row, Mapping)
    }
    target_shot_row = target_shots.get(target_shot) or {}
    target_characters = {
        str(name) for name in (target_shot_row.get("characters") or [])
        if str(name)
    }
    framing = target_shot_row.get("framing_target")
    target_framing_ref = (
        str(framing.get("ref") or "")
        if isinstance(framing, Mapping)
        and str(framing.get("kind") or "") == "prop"
        else ""
    )
    previous_props = {
        str(row.get("id") or ""): row
        for row in (previous.get("props") or [])
        if isinstance(row, Mapping)
    }
    candidate_props = {
        str(row.get("id") or ""): row
        for row in (candidate.get("props") or [])
        if isinstance(row, Mapping)
    }
    for prop_id in sorted(set(previous_props) | set(candidate_props)):
        before = previous_props.get(prop_id)
        after = candidate_props.get(prop_id)
        if before == after:
            continue
        owner = (
            str(after.get("owner") or "")
            if isinstance(after, Mapping)
            else str(before.get("owner") or "")
            if isinstance(before, Mapping)
            else ""
        )
        belongs_to_target = (
            (owner and owner in target_characters)
            or (target_framing_ref and prop_id == target_framing_ref)
        )
        if not belongs_to_target:
            findings.append({
                "check_id": E_DETAIL_SCOPE_VIOLATION,
                "shot_id": target_shot,
                "severity": "error",
                "path": f"props.{prop_id}",
                "message": (
                    f"detail revision for {target_shot} changed non-target "
                    f"prop {prop_id}"),
            })
            continue
        prop_shots: set[str] = set()
        for other_shot_id, other_shot in target_shots.items():
            other_characters = {
                str(name) for name in (other_shot.get("characters") or [])
                if str(name)
            }
            other_framing = other_shot.get("framing_target")
            other_framing_ref = (
                str(other_framing.get("ref") or "")
                if isinstance(other_framing, Mapping)
                and str(other_framing.get("kind") or "") == "prop"
                else ""
            )
            if (owner and owner in other_characters) \
                    or (other_framing_ref and prop_id == other_framing_ref):
                prop_shots.add(other_shot_id)
        if len(prop_shots) > 1:
            findings.append({
                "check_id": E_DETAIL_SCOPE_VIOLATION,
                "shot_id": target_shot,
                "severity": "error",
                "path": f"props.{prop_id}",
                "message": (
                    f"prop {prop_id} is shared by shots "
                    f"{sorted(prop_shots)}; a global prop mutation for "
                    f"{target_shot} would leak into another shot"),
            })
            continue
        provenance = (
            after.get("provenance")
            if isinstance(after, Mapping) else None
        )
        if mode == "revision" \
                and str(provenance or "") != "agent_local_revision":
            findings.append({
                "check_id": E_DETAIL_SCOPE_VIOLATION,
                "shot_id": target_shot,
                "severity": "error",
                "path": f"props.{prop_id}.provenance",
                "message": (
                    f"prop drift for {prop_id} in {target_shot} lacks "
                    "agent_local_revision provenance"),
            })
    return findings


def _dist(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2
            + (a["z"] - b["z"]) ** 2) ** 0.5


__all__ = ["derive_detail_shots", "spatial_drift_review",
           "identity_freeze_review",
           "reference_scope_review",
           "E_DETAIL_SPATIAL_DRIFT", "E_IDENTITY_DRIFT",
           "E_DETAIL_SCOPE_VIOLATION",
           "SPATIAL_DRIFT_TOLERANCE_M"]
