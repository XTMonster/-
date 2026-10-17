"""空间尺测量的纯层组装（Ticket 04）。

把"声明时长 / 计划帧数 / 相机实测 / 构图报告 / 帧采样"折成契约层的
观测记录（``contracts/spatial_ruler.py`` 的 measurement 形状）。本模块无 bpy：
Blender 侧的采集在 ``layer3_engine/ruler_probe.py``，它只负责把实测值
整理成这里要的形状，真正的单位与来源语义由本模块定死。

来源四态（契约强制，source == provenance）：
* ``script_declaration``：剧本声明的时长；
* ``plan_intent``：LLM 计划的时长（实际 = 计划帧数 / fps）；
* ``blender_geometry``：相机、包围盒、可见性、构图、角差等实测。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

def _measurement(*, shot_id: str, metric: str, value: Any, unit: str,
                 source: str, expected: Any = None,
                 subject_id: Optional[str] = None,
                 frame: Optional[Any] = None,
                 transition_id: Optional[str] = None) -> Dict[str, Any]:
    """构造一条契约形状的 measurement 记录（普通 dict，可直接 JSON）。"""
    measurement_id = (f"m_{shot_id}_{metric}"
                      f"{'_' + str(subject_id) if subject_id else ''}"
                      f"{'_' + str(frame) if frame is not None else ''}")
    return {
        "measurement_id": measurement_id,
        "shot_id": str(shot_id),
        "transition_id": transition_id,
        "subject_id": subject_id,
        "frame": frame,
        "metric": metric,
        "value": value,
        "expected": expected,
        "unit": unit,
        "source": source,
        "provenance": source,
    }


def _frame_metrics_for(sample: Any) -> Dict[str, float]:
    """从帧采样样本提取可序列化的单帧度量（NDC 比例，可越界）。"""
    box = getattr(sample, "box", None)
    if box is None:
        return {}
    visible = float(getattr(sample, "visible_ratio", 1.0) or 1.0)
    inside = float(box.inside_ratio()) if hasattr(box, "inside_ratio") else 1.0
    return {
        "left": float(getattr(box, "left", 0.0)),
        "right": float(getattr(box, "right", 1.0)),
        "top": float(getattr(box, "top", 1.0)),
        "bottom": float(getattr(box, "bottom", 0.0)),
        "center_x": float(getattr(box, "center_x", 0.5)),
        "center_y": float(getattr(box, "center_y", 0.5)),
        "height": float(getattr(box, "height", 1.0)),
        "width": float(getattr(box, "width", 1.0)),
        "facing": float(getattr(box, "facing", 0.0) or 0.0),
        "visible_ratio": round(visible, 4),
        "inside_ratio": round(inside, 4),
    }


def measurements_for_shot(
    *,
    shot_id: str,
    declared_seconds: Optional[float] = None,
    planned_frames: Optional[int] = None,
    fps: int = 24,
    camera: Optional[Dict[str, Any]] = None,
    composition_score: Optional[float] = None,
    composition_items: Optional[Dict[str, Dict[str, Any]]] = None,
    frame_samples: Sequence[Any] = (),
    transition_angle_deg: Optional[float] = None,
    transition_prev_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """组装这一镜的观测测量记录（纯函数，无副作用）。

    ``frame_samples`` 是任意「鸭子类型」帧样本序列（与
    ``frustum_metrics.FrameSample`` 同形状：``frame / subject / box /
    visible_ratio``）。返回值全部是契约层 ``Measurement``。
    """
    measurements: List[Dict[str, Any]] = []
    if declared_seconds is not None:
        measurements.append(_measurement(
            shot_id=shot_id, metric="shot_duration_declared",
            value=round(float(declared_seconds), 3), unit="seconds",
            source="script_declaration",
            expected=round(float(declared_seconds), 3)))
    if planned_frames is not None:
        planned_seconds = float(planned_frames) / max(int(fps), 1)
        measurements.append(_measurement(
            shot_id=shot_id, metric="shot_duration_planned",
            value=round(planned_seconds, 3), unit="seconds",
            source="plan_intent"))
    if camera:
        lens = camera.get("lens")
        if lens is not None:
            measurements.append(_measurement(
                shot_id=shot_id, metric="camera_lens",
                value=float(lens), unit="mm", source="blender_geometry"))
        distance = camera.get("distance")
        if distance is not None:
            measurements.append(_measurement(
                shot_id=shot_id, metric="camera_distance",
                value=round(float(distance), 3), unit="meters",
                source="blender_geometry"))
        if camera.get("position") is not None:
            measurements.append(_measurement(
                shot_id=shot_id, metric="camera_position",
                value=[float(x) for x in camera["position"]],
                unit="meters", source="blender_geometry"))
    if transition_angle_deg is not None and transition_prev_id:
        measurements.append(_measurement(
            shot_id=shot_id, metric="transition_angle_deg",
            value=round(float(transition_angle_deg), 2), unit="degrees",
            source="blender_geometry",
            transition_id=f"{transition_prev_id}->{shot_id}"))
    if composition_score is not None:
        measurements.append(_measurement(
            shot_id=shot_id, metric="composition_score",
            value=round(float(composition_score), 2), unit="0..100",
            source="blender_geometry"))
    for name, item in (composition_items or {}).items():
        if isinstance(item, dict) and item.get("score") is not None:
            measurements.append(_measurement(
                shot_id=shot_id, metric=f"composition_{name}",
                value=round(float(item["score"]), 4), unit="0..1",
                source="blender_geometry"))
    seen: set = set()
    for sample in frame_samples:
        subject_id = str(getattr(sample, "subject", "") or "")
        frame = getattr(sample, "frame", None)
        box_metrics = _frame_metrics_for(sample)
        if not box_metrics or subject_id in seen:
            continue                     # 每主体取首帧的包围盒避免重复
        seen.add(subject_id)
        for metric, value in box_metrics.items():
            measurements.append(_measurement(
                shot_id=shot_id, metric=f"subject_box_{metric}",
                value=value, unit="ndc_0_1" if metric in {
                    "visible_ratio", "inside_ratio"} else "ndc_0_1",
                source="blender_geometry",
                subject_id=subject_id, frame=frame))
    return measurements
