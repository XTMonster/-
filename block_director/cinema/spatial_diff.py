"""设计 vs 实测对照器与阈值 registry（Ticket 04，纯层，不 import bpy）。

对同一镜的「空间设计快照」（该怎样，expected）与「观测快照」（实际怎样，
actual）做确定性对照，产出结构化偏差报告：位置偏差（欧氏距离）、朝向夹角、
视线夹角、运动路径偏差。**所有阈值收进 ``REGISTRY``**（一处定义，代码不散
魔法数字；沿用观测契约"expected/actual/threshold" 三件套）。

判定语义：数值越接近越好，``actual <= threshold`` -> ``pass``；设计值缺失
或未解析 -> ``verdict = unresolved``（不脑补 expected）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: 快照版本（契约演进时逐代升）。
DIFF_SNAPSHOT_SCHEMA = "spatial-diff/v1"

#: 偏差阈值 registry（唯一真源，代码不硬编码）。
#: 数值口径：位置米、夹角度、速度 m/s。均为"越大越差"型（<= threshold
#: 为 pass）。调整只许在这改，消费方全部从这里读。
REGISTRY: Dict[str, float] = {
    "camera_position_m": 0.3,      # 机位落位偏差容忍（30 cm）
    "character_position_m": 0.3,   # 角色站位偏差容忍（30 cm）
    "heading_angle_deg": 30.0,     # 朝向夹角容忍（与 R001 轴线 30° 同口径）
    "gaze_angle_deg": 30.0,        # 视线夹角容忍
    "motion_displacement_m": 0.5,  # 运动路径首末位移偏差容忍
    "speed_delta_m_s": 0.5,        # 运动速度偏差容忍
}


def _vec3(value: Any) -> Sequence[float]:
    if isinstance(value, Mapping):
        return (float(value.get("x") or 0.0),
                float(value.get("y") or 0.0),
                float(value.get("z") or 0.0))
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return tuple(float(v) for v in value[:3])
    return ()


def _euclidean(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) < 3 or len(b) < 3:
        return None
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _angle_deg(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """两向量的夹角（度）。任一向量为零 -> None（无法判定，不猜）。"""
    if not a or not b or len(a) < 3 or len(b) < 3:
        return None
    la = math.sqrt(sum(float(c) * float(c) for c in a))
    lb = math.sqrt(sum(float(c) * float(c) for c in b))
    if la < 1e-9 or lb < 1e-9:
        return None
    dot = sum(float(a[i]) * float(b[i]) for i in range(3)) / (la * lb)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _verdict(actual: Optional[float], threshold: float) -> str:
    if actual is None:
        return "unresolved"
    return "pass" if actual <= threshold else "fail"


def _item(metric: str, subject: str, expected: Any, actual: Optional[float],
          threshold: float, unit: str) -> Dict[str, Any]:
    return {
        "metric": metric, "subject": subject,
        "expected": expected, "actual": actual,
        "threshold": threshold, "verdict": _verdict(actual, threshold),
        "unit": unit,
    }


def _observed_shots(observed: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    shots: Dict[str, Dict[str, Any]] = {}
    for raw in observed.get("shots") or []:
        shot = dict(raw) if isinstance(raw, Mapping) else {}
        shot_id = str(shot.get("shot_id") or "")
        if shot_id:
            shots[shot_id] = shot
    return shots


def _first_element(shot: Mapping[str, Any], subject_id: str,
                   ) -> Optional[Dict[str, Any]]:
    samples = shot.get("samples") or []
    for sample in samples:
        for element in (sample.get("elements") or []):
            if str(element.get("id") or "") == subject_id:
                return dict(element)
    return None


def _observed_subjects(shot: Mapping[str, Any]) -> List[str]:
    subjects: List[str] = []
    for sample in (shot.get("samples") or []):
        for element in (sample.get("elements") or []):
            el_id = str(element.get("id") or "")
            if el_id and el_id not in subjects:
                subjects.append(el_id)
    return subjects


def build_diff_report(design: Mapping[str, Any],
                      observed: Mapping[str, Any],
                      ) -> Dict[str, Any]:
    """构建设计 vs 实测偏差报告（确定性）。

    ``design``：`build_design_snapshot` 的输出；``observed``：
    `build_observation_snapshot` 的输出。按 shot_id 对齐；观测里没有对应
    镜 -> 逐项标 unresolved（不猜）。数值项带 expected/actual/threshold/
    verdict/unit。
    """
    items: List[Dict[str, Any]] = []
    observed_shots = _observed_shots(observed)
    camera_intents = {str(item.get("shot_id") or ""): dict(item)
                      for item in (design.get("camera_intents") or [])
                      if isinstance(item, Mapping)}
    design_chars = {str(item.get("name") or ""): dict(item)
                    for item in (design.get("characters") or [])
                    if isinstance(item, Mapping)}

    shot_ids = sorted(set(camera_intents) | set(observed_shots))
    for shot_id in shot_ids:
        intent = camera_intents.get(shot_id)
        obs_shot = observed_shots.get(shot_id)
        if intent is None:
            items.append(_item(
                "camera_position", shot_id, None, None,
                REGISTRY["camera_position_m"], "m"))
            items.append(_item(
                "camera_heading", shot_id, None, None,
                REGISTRY["heading_angle_deg"], "deg"))
            continue
        cam_expected = _vec3(intent.get("position"))
        cam_actual = None
        if obs_shot is not None:
            samples = obs_shot.get("samples") or []
            cam_actual = (None if not samples else _euclidean(
                cam_expected,
                _vec3((samples[0].get("camera") or {}).get("position"))))
        items.append(_item("camera_position", shot_id,
                           list(cam_expected) or None, cam_actual,
                           REGISTRY["camera_position_m"], "m"))

        design_names = set(design_chars)
        observed_names = set() if obs_shot is None else set(
            _observed_subjects(obs_shot))
        for name in sorted(design_names | observed_names):
            char = design_chars.get(name) or {}
            pos_design = _vec3(char.get("position"))
            element = None if obs_shot is None else _first_element(
                obs_shot, name)
            #: 位置比较用同一锚点：设计 position 是根部站位（z≈0），观测侧
            #: 取 aabb_min（脚底），而不是包围盒中心——否则 z 轴锚点差异
            #: （中心高于脚底 ~0.85m）会污染偏差（实测见 smoke：0.85 vs 0.0）。
            pos_actual = (None if element is None else _euclidean(
                pos_design, _vec3(element.get("aabb_min"))))
            items.append(_item("character_position", name,
                               list(pos_design) or None, pos_actual,
                               REGISTRY["character_position_m"], "m"))

            heading_design = _vec3(char.get("facing"))
            heading_actual = (None if element is None else _angle_deg(
                heading_design, _vec3(element.get("facing"))))
            items.append(_item("heading_angle", name,
                               list(heading_design) or None, heading_actual,
                               REGISTRY["heading_angle_deg"], "deg"))

            gaze_design = _vec3((char.get("gaze") or {}).get("direction"))
            gaze_actual = None
            if element is not None:
                gaze_actual = _angle_deg(
                    gaze_design,
                    _vec3((element.get("gaze") or {}).get("direction")))
                if gaze_actual is None and not gaze_design:
                    gaze_actual = None
            items.append(_item("gaze_angle", name,
                               list(gaze_design) or None, gaze_actual,
                               REGISTRY["gaze_angle_deg"], "deg"))

            motion_design = None
            for motion in (char.get("motion_by_shot") or []):
                if str(motion.get("shot_id") or "") == shot_id:
                    motion_design = dict(motion)
                    break
            if motion_design is None and char.get("motion") is not None:
                motion_design = dict(char["motion"])
            motion_actual = None
            if element is not None and motion_design is not None:
                obs_motion = element.get("motion") or {}
                obs_waypoints = obs_motion.get("waypoints") or []
                if obs_waypoints:
                    start_d = _vec3(motion_design.get("start"))
                    end_d = _vec3(motion_design.get("end"))
                    if start_d and end_d:
                        planned = _euclidean(start_d, end_d)
                        observed_m = _euclidean(
                            _vec3(obs_waypoints[0]),
                            _vec3(obs_waypoints[-1]))
                        if planned is not None and observed_m is not None:
                            motion_actual = abs(planned - observed_m)
            if motion_design is not None:
                items.append(_item("motion_displacement", name, None,
                                   motion_actual,
                                   REGISTRY["motion_displacement_m"], "m"))

    return {
        "schema_version": DIFF_SNAPSHOT_SCHEMA,
        "items": items,
    }


def render_diff_block(report: Mapping[str, Any], *,
                      max_chars: int = 800) -> str:
    """把偏差报告渲染成「设计 vs 实测」提示块（修复提示注入用）。

    整行追加、放不下整行舍弃（与 digest 渲染同机制）；无 items -> 空串。
    """
    if max_chars <= 0 or not isinstance(report, Mapping):
        return ""
    items = report.get("items") or []
    if not items:
        return ""
    lines: List[str] = ["【设计 vs 实测】偏差（expected|actual|threshold|verdict）"]

    def fits(line: str) -> bool:
        current = len("\n".join(lines)) if lines else 0
        return current + len(line) + (1 if lines else 0) <= max_chars

    for item in items:
        actual = (f"{item.get('actual'):.3f}"
                  if isinstance(item.get("actual"), (int, float)) else "-")
        line = (f"- {item.get('metric')} {item.get('subject')}: "
                f"actual={actual} threshold={item.get('threshold')} "
                f"verdict={item.get('verdict')} {item.get('unit', '')}")
        if fits(line):
            lines.append(line)
    return "\n".join(lines)


__all__ = ["build_diff_report", "render_diff_block",
           "REGISTRY", "DIFF_SNAPSHOT_SCHEMA"]
