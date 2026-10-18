"""粗排处方生成器与应用器（Ticket 01/02，纯层，不 import bpy）。

输入 BlockoutReport（findings + 每镜 composition/occlusion/on_screen 数值）与
粗编排参考 JSON，输出**结构化粗排处方**列表。处方格式：

``{prescription_id, scope, shot_id, entity, component, axis, direction,
magnitude, current_value, target_value, derived_from, applied}``

原则（处方生成）：

* 只消费空间尺/BlockoutReport 的结构化输出，不在粗排修正层凭空猜坐标；
* 每条处方都可追溯到一条 check/finding（``derived_from``）；
* 量级由 actual/threshold 差与实体当前值推导，确定性可复算。

原则（处方应用）：

* 修改只发生在粗编排参考 JSON，不写 Blender 场景；
* 每条应用记录含 before/after 与指纹；两次应用逐位一致；
* 未知实体/未知轴返回显式未应用记录，不吞错。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
)

E_BLOCKOUT_EMPTY_WALL = "E_BLOCKOUT_EMPTY_WALL"

#: 构图通过分数（与空间尺默认一致；判据单一真源由空间尺 registry 提供）。
COMPOSITION_PASS_SCORE = 80.0


def _vec3(value: Any) -> Dict[str, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return {"x": float(value[0]), "y": float(value[1]),
                    "z": float(value[2])}
        except (TypeError, ValueError):
            return None
    if isinstance(value, Mapping):
        try:
            return {"x": float(value.get("x", 0.0)),
                    "y": float(value.get("y", 0.0)),
                    "z": float(value.get("z", 0.0))}
        except (TypeError, ValueError):
            return None
    return None


def _to_list(value: Mapping[str, float]) -> List[float]:
    """写回参考 JSON 用列表形状（与 spatial_design/blockout 同源）。"""
    return [round(float(value["x"]), 4), round(float(value["y"]), 4),
            round(float(value["z"]), 4)]


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
    only_hard: bool = False,
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
    5. ``E_FOREGROUND_OCCLUSION`` error -> 相机沿视线拉远 15%，让前景体块
       与主体重新建立可读间隔；该处方属于硬伤，粗排循环必须执行。

    ``only_hard=True`` 时只产出 error finding（E_BLOCKOUT_EMPTY_WALL）处方：
    粗排修正循环只修硬伤；构图/遮挡/出画软处方留给细排阶段（T06）。
    """
    prescriptions: List[Dict[str, Any]] = []
    findings_by_shot = _findings_by_shot(report)
    checks_by_shot = _checks_by_shot(report)

    for shot_id, findings in findings_by_shot.items():
        camera = _camera_of(reference, shot_id)
        if camera is None:
            continue  #: 未知镜不产凭空处方
        for finding in findings:
            check_id = str(finding.get("check_id") or "")
            if check_id in {"E_FOREGROUND_OCCLUSION",
                            "E_SUBJECT_AREA_OVERFLOW"}:
                position = _vec3(camera.get("position"))
                target = _vec3(camera.get("target"))
                if position is None or target is None:
                    continue
                distance = max(_distance(position, target), 1e-6)
                direction_vec = {k: (target[k] - position[k]) / distance
                                 for k in ("x", "y", "z")}
                pull = 0.15 * distance
                new_position = {k: position[k] - direction_vec[k] * pull
                                for k in ("x", "y", "z")}
                prescriptions.append({
                    "prescription_id": f"p_coarse_{shot_id}_foreground_occlusion",
                    "scope": "camera", "shot_id": shot_id,
                    "entity": str(camera.get("camera_id") or f"cam_{shot_id}"),
                    "component": "distance", "axis": "distance",
                    "direction": "out", "magnitude": round(pull, 4),
                    "current_value": {"position": position, "target": target},
                    "target_value": {"position": new_position, "target": target},
                    "derived_from": {
                        "check_id": check_id,
                        "severity": str(finding.get("severity") or ""),
                        "message": str(finding.get("message") or ""),
                    },
                    "applied": False,
                })
                continue
            if check_id != E_BLOCKOUT_EMPTY_WALL:
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
        if only_hard:
            break  #: 软指标处方不在粗排修正循环中使用
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


def _apply_target(camera: Dict[str, Any], target_value: Any) -> None:
    if not isinstance(target_value, Mapping):
        raise ValueError("target 处方缺 target_value 坐标")
    camera["target"] = _to_list(target_value)


def _apply_distance(camera: Dict[str, Any], target_value: Any) -> None:
    position = (target_value or {}).get("position")
    if not isinstance(position, Mapping):
        raise ValueError("distance 处方缺 target_value.position")
    camera["position"] = _to_list(position)


def _apply_position_y(camera: Dict[str, Any], target_value: Any) -> None:
    if not isinstance(camera.get("position"), (list, tuple)):
        raise ValueError("position 必须为列表 [x,y,z] 才能改 y")
    position = list(camera["position"])
    position[1] = round(float(target_value), 4)
    camera["position"] = position


_APPLIERS = {
    "target": _apply_target,
    "distance": _apply_distance,
    "position.y": _apply_position_y,
}


def apply_coarse_prescriptions(
    reference: Mapping[str, Any],
    prescriptions: List[Dict[str, Any]],
    *,
    revision_id: str = "",
    round_no: int = 1,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """把处方应用到粗编排参考 JSON，落 revision 留痕。

    返回 ``(new_reference, applied_records)``。``new_reference`` 是深拷贝后
    修改的结果（不污染输入）；``revisions[]`` 追加一条修订记录
    （before/after 指纹 + 逐条处方结果）。未知实体/未知轴记录
    ``applied=False`` 与原因，不抛错、不吞错、不修改。
    """
    import copy

    new_ref = copy.deepcopy(reference)
    by_shot = {str(c.get("shot_id") or ""): c
               for c in new_ref.get("camera_intents") or []}
    records: List[Dict[str, Any]] = []
    for p in prescriptions:
        shot_id = str(p.get("shot_id") or "")
        component = str(p.get("component") or "")
        camera = by_shot.get(shot_id)
        record: Dict[str, Any] = {
            "prescription_id": p.get("prescription_id"),
            "shot_id": shot_id,
            "component": component,
            "applied": False,
            "before": None,
            "after": None,
            "reason": "",
        }
        if camera is None:
            record["reason"] = f"未知 shot_id：{shot_id}"
            records.append(record)
            continue
        applier = _APPLIERS.get(component)
        if applier is None:
            record["reason"] = f"未知 component：{component}"
            records.append(record)
            continue
        try:
            record["before"] = {
                "position": copy.deepcopy(camera.get("position")),
                "target": copy.deepcopy(camera.get("target")),
            }
            applier(camera, p.get("target_value"))
            record["after"] = {
                "position": copy.deepcopy(camera.get("position")),
                "target": copy.deepcopy(camera.get("target")),
            }
            record["applied"] = True
        except (TypeError, ValueError) as exc:
            record["reason"] = f"应用失败：{exc}"
        records.append(record)

    if records:
        new_ref.setdefault("revisions", []).append({
            "revision_id": str(revision_id or "deterministic-replay"),
            "round": int(round_no),
            "fingerprint_before": coarse_reference_content_fingerprint(
                reference),
            "fingerprint_after": coarse_reference_content_fingerprint(
                new_ref),
            "prescriptions": records,
        })
    return new_ref, records


__all__ = ["build_coarse_prescriptions", "apply_coarse_prescriptions",
           "E_BLOCKOUT_EMPTY_WALL", "COMPOSITION_PASS_SCORE"]
