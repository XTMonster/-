"""粗排处方生成器（Ticket 01，纯层，不 import bpy）。

输入 BlockoutReport（findings + 每镜 composition/occlusion/on_screen 数值）与
粗编排参考 JSON，输出**结构化粗排处方**列表。处方格式：

``{prescription_id, scope, shot_id, entity, component, axis, direction,
magnitude, current_value, target_value, derived_from, applied}``

原则：

* 只消费空间尺/BlockoutReport 的结构化输出，不在粗排修正层凭空猜坐标；
* 每条处方都可追溯到一条 check/finding（``derived_from``）；
* 量级由 actual/threshold 差与实体当前值推导，确定性可复算。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

E_BLOCKOUT_EMPTY_WALL = "E_BLOCKOUT_EMPTY_WALL"

#: 构图通过分数（与空间尺默认一致；判据单一真源由空间尺 registry 提供）。
COMPOSITION_PASS_SCORE = 80.0


def _vec3(value: Any) -> Dict[str, float] | None:
    if isinstance(value, Mapping):
        try:
            return {"x": float(value.get("x", 0.0)),
                    "y": float(value.get("y", 0.0)),
                    "z": float(value.get("z", 0.0))}
        except (TypeError, ValueError):
            return None
    return None


def _distance(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2
            + (a["z"] - b["z"]) ** 2) ** 0.5


def _subject_centroid(reference: Mapping[str, Any],
                      shot_id: str) -> Dict[str, float] | None:
    """该镜出场角色的体块质心（脚底 z + 0.9 m 躯干中心，human scale）。"""
    shot = next((s for s in reference.get("shots") or []
                 if str(s.get("shot_id") or "") == shot_id), None)
    names = [str(n) for n in (shot.get("characters") or [])]
    points: List[Dict[str, float]] = []
    for char in reference.get("characters") or []:
        if str(char.get("name") or "") not in names:
            continue
        pos = _vec3(char.get("position"))
        if pos is None:
            continue
        points.append({"x": pos["x"], "y": pos["y"], "z": pos["z"] + 0.9})
    if not points:
        return None
    return {"x": sum(p["x"] for p in points) / len(points),
            "y": sum(p["y"] for p in points) / len(points),
            "z": sum(p["z"] for p in points) / len(points)}


def _camera_of(reference: Mapping[str, Any],
               shot_id: str) -> Dict[str, Any] | None:
    return next((c for c in reference.get("camera_intents") or []
                 if str(c.get("shot_id") or "") == shot_id), None)


def _findings_by_shot(report: Mapping[str, Any]) -> Dict[str, List[Mapping]]:
    result: Dict[str, List[Mapping]] = {}
    for finding in report.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        result.setdefault(str(finding.get("shot_id") or ""), []).append(finding)
    return result


def _checks_by_shot(report: Mapping[str, Any]) -> Dict[str, Dict[str, Mapping]]:
    result: Dict[str, Dict[str, Mapping]] = {}
    for check in report.get("checks") or []:
        if not isinstance(check, Mapping):
            continue
        sid = str(check.get("shot_id") or "")
        result.setdefault(sid, {})[str(check.get("check_id") or "")] = check
    return result


def build_coarse_prescriptions(
    *,
    report: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """从 BlockoutReport + 粗编排参考 JSON 生成结构化粗排处方。

    规则（确定性，全部可追溯）：

    1. ``E_BLOCKOUT_EMPTY_WALL`` error finding -> 该镜相机 target 指向主体质心
       （``component=target, direction=towards_subject``）；
    2. ``on_screen`` check fail（主体几乎出画）-> 相机沿视线拉远 10%
       （``component=distance, direction=out``）；
    3. ``composition`` check fail -> 相机沿视线推近 10%
       （``component=distance, direction=in``；同一镜已有拉远处方则不重复）；
    4. ``occlusion`` check fail（可见比低于 0.5）-> 相机抬高
       （``component=position.y, direction=up``，量级 ∝ (1 - actual)）。
    """
    prescriptions: List[Dict[str, Any]] = []
    findings_by_shot = _findings_by_shot(report)
    checks_by_shot = _checks_by_shot(report)

    for shot_id, findings in findings_by_shot.items():
        camera = _camera_of(reference, shot_id)
        if camera is None:
            continue  #: 未知镜不产凭空处方
        for finding in findings:
            if finding.get("check_id") != E_BLOCKOUT_EMPTY_WALL:
                continue
            target = _subject_centroid(reference, shot_id)
            if target is None:
                continue
            current = _vec3(camera.get("target"))
            if current is None:
                continue
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_empty_wall",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "target", "axis": "target",
                "direction": "towards_subject",
                "magnitude": round(_distance(current, target), 4),
                "current_value": dict(current),
                "target_value": target,
                "derived_from": {
                    "check_id": str(finding.get("check_id")),
                    "severity": str(finding.get("severity") or ""),
                    "message": str(finding.get("message") or ""),
                },
                "applied": False,
            })

    for shot_id, checks in checks_by_shot.items():
        camera = _camera_of(reference, shot_id)
        if camera is None:
            continue
        position = _vec3(camera.get("position"))
        target = _vec3(camera.get("target"))
        if position is None or target is None:
            continue

        already_distance = any(
            p["shot_id"] == shot_id and p["component"] == "distance"
            for p in prescriptions)

        on_screen = checks.get("on_screen")
        if (on_screen and on_screen.get("verdict") == "fail"
                and not already_distance):
            distance = max(_distance(position, target), 1e-6)
            direction_vec = {k: (target[k] - position[k]) / distance
                             for k in ("x", "y", "z")}
            pull = 0.1 * distance
            new_position = {k: position[k] - direction_vec[k] * pull
                            for k in ("x", "y", "z")}
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_pull_back",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "distance", "axis": "distance",
                "direction": "out",
                "magnitude": round(pull, 4),
                "current_value": {"position": position, "target": target},
                "target_value": {"position": new_position, "target": target},
                "derived_from": {
                    "check_id": "on_screen",
                    "actual": on_screen.get("actual"),
                    "threshold": on_screen.get("threshold"),
                    "verdict": "fail",
                },
                "applied": False,
            })
            already_distance = True

        composition = checks.get("composition")
        if (composition and composition.get("verdict") == "fail"
                and not already_distance):
            distance = max(_distance(position, target), 1e-6)
            direction_vec = {k: (target[k] - position[k]) / distance
                             for k in ("x", "y", "z")}
            push = 0.1 * distance
            new_position = {k: position[k] + direction_vec[k] * push
                            for k in ("x", "y", "z")}
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_push_in",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "distance", "axis": "distance",
                "direction": "in",
                "magnitude": round(push, 4),
                "current_value": {"position": position, "target": target},
                "target_value": {"position": new_position, "target": target},
                "derived_from": {
                    "check_id": "composition",
                    "actual": composition.get("actual"),
                    "threshold": composition.get("threshold"),
                    "verdict": "fail",
                },
                "applied": False,
            })

        occlusion = checks.get("occlusion")
        if (occlusion and occlusion.get("verdict") == "fail"
                and not any(p["shot_id"] == shot_id
                            and p["component"] == "position.y"
                            for p in prescriptions)):
            actual = float(occlusion.get("actual") or 0.0)
            raise_by = min(0.6, max(0.1, (1.0 - actual) * 0.8))
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_raise_cam",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "position.y", "axis": "y",
                "direction": "up",
                "magnitude": round(raise_by, 4),
                "current_value": position["y"],
                "target_value": round(position["y"] + raise_by, 4),
                "derived_from": {
                    "check_id": "occlusion",
                    "actual": occlusion.get("actual"),
                    "threshold": occlusion.get("threshold"),
                    "verdict": "fail",
                },
                "applied": False,
            })

    return prescriptions


__all__ = ["build_coarse_prescriptions", "E_BLOCKOUT_EMPTY_WALL",
           "COMPOSITION_PASS_SCORE"]
