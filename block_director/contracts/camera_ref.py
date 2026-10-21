"""缺陷 E（T2）：相机引用解析（纯层，禁止 import bpy）。

单镜重建会删旧相机建新相机（对象身份变化但镜头键稳定），模型手里上一轮的
``camera_id`` 可能是对象名、镜头键或 ``BD_Cam_<shot>`` 字面量；解析优先
对象名、再回查镜头键，重建后旧 ID 不再产生 domain_error。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

CAMERA_OBJECT_PREFIX = "BD_Cam_"


def resolve_camera_ref(cameras: Mapping[str, Any],
                       camera_id: str) -> Tuple[Optional[Any], str, str]:
    """把模型手里的相机引用解析到当前相机对象。

    优先级：
    1. 对象名（``camera_by_name`` 语义）：按对象 ``name`` 匹配，命中后回查
       它属于哪一镜（镜头键）；
    2. 镜头键直取：``camera_id`` 就是 ``context.cameras`` 的键；
    3. ``BD_Cam_<shot_id>`` 字面量：去掉前缀按镜头键直取。

    返回 ``(camera, shot_id, problem)``；找不到时 ``camera`` 为 None 且
    ``problem`` 给出镜头清单（不静默）。
    """
    if not camera_id:
        return None, "", ""
    # 1) 对象名解析（重建后对象身份变了，但镜头键与对象名保持稳定）。
    for shot_id, obj in cameras.items():
        name = str(getattr(obj, "name", "") or "")
        if name == camera_id:
            return obj, str(shot_id), ""
    # 2) 镜头键直取。
    if camera_id in cameras:
        return cameras[camera_id], camera_id, ""
    # 3) BD_Cam_<shot_id> 字面量。
    if camera_id.startswith(CAMERA_OBJECT_PREFIX):
        shot_id = camera_id[len(CAMERA_OBJECT_PREFIX):]
        if shot_id in cameras:
            return cameras[shot_id], shot_id, ""
    known = ", ".join(sorted(str(key) for key in cameras)) or "（无）"
    return None, "", f"找不到相机 {camera_id}。可用镜头: {known}"
