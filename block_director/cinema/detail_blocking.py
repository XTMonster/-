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


def _vec3(value: Any) -> Dict[str, float] | None:
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
            "lens_mm": float(camera.get("lens_mm")
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


def _dist(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2
            + (a["z"] - b["z"]) ** 2) ** 0.5


__all__ = ["derive_detail_shots", "spatial_drift_review",
           "E_DETAIL_SPATIAL_DRIFT", "SPATIAL_DRIFT_TOLERANCE_M"]
