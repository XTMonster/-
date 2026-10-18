"""细排数据契约 DetailShotContract（Ticket 04，纯层，不 import bpy）。

逐镜细编排的结构化数据：角色（位置/旋转/朝向/视线/姿态/运动节拍）、道具
（位置/旋转/运动节拍）、相机（位置/目标/镜头/运镜）、节拍（帧点+动作/表情/
音频代理）。从冻结粗排基准派生，继承不漂移。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

DETAIL_SHOT_SCHEMA_VERSION = "detail-shot-contract/v1"

_REQUIRED_SHOT_KEYS = (
    "schema_version", "shot_id", "order", "start_frame", "end_frame",
    "characters", "props", "camera", "beats", "audio_proxy",
)
_REQUIRED_CHAR_KEYS = ("name", "position", "rotation", "facing", "gaze",
                       "pose", "motion_beats", "source")
_REQUIRED_PROP_KEYS = ("id", "position", "rotation", "motion_beats")
_REQUIRED_CAMERA_KEYS = ("position", "target", "lens_mm", "movements")


def validate_detail_shots(detail_shots: Any) -> List[str]:
    """轻量结构守卫：缺必需节/坏类型报 findings；通过返回空表。"""
    findings: List[str] = []
    if not isinstance(detail_shots, list):
        return ["detail_shots 必须是数组"]
    for i, shot in enumerate(detail_shots):
        if not isinstance(shot, Mapping):
            findings.append(f"shots[{i}] 必须是 Mapping")
            continue
        for key in _REQUIRED_SHOT_KEYS:
            if key not in shot:
                findings.append(f"shots[{i}] 缺必需键 {key}")
        if shot.get("schema_version") != DETAIL_SHOT_SCHEMA_VERSION:
            findings.append(f"shots[{i}] schema_version 必须为 "
                            f"{DETAIL_SHOT_SCHEMA_VERSION!r}")
        if not isinstance(shot.get("characters"), list):
            findings.append(f"shots[{i}] characters 必须是数组")
        else:
            for j, char in enumerate(shot.get("characters") or []):
                if not isinstance(char, Mapping):
                    findings.append(f"shots[{i}].characters[{j}] 非对象")
                    continue
                for key in _REQUIRED_CHAR_KEYS:
                    if key not in char:
                        findings.append(
                            f"shots[{i}].characters[{j}] 缺必需键 {key}")
        if not isinstance(shot.get("props"), list):
            findings.append(f"shots[{i}] props 必须是数组")
        camera = shot.get("camera")
        if not isinstance(camera, Mapping):
            findings.append(f"shots[{i}] camera 必须是对象")
        else:
            for key in _REQUIRED_CAMERA_KEYS:
                if key not in camera:
                    findings.append(f"shots[{i}].camera 缺必需键 {key}")
    return findings


__all__ = ["DETAIL_SHOT_SCHEMA_VERSION", "validate_detail_shots"]
