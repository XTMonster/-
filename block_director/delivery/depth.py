"""深度序列的交付约定（执行文档 v1.2 §15.6 的纯计算部分）。

渲染本身在 ``layer8_delivery/depth_pass.py``（要 bpy）；这里放"约定"——固定
归一化范围、目录与文件名模板、README 里那段说明。约定是跨镜头可比的前提，
因此必须能被单测钉住，而不是散落在渲染代码里。
"""

from __future__ import annotations

from typing import Dict, Tuple

#: 固定归一化范围（米）。写进 README，保证不同镜头、不同批次之间可比。
DEPTH_RANGE: Tuple[float, float] = (0.1, 50.0)

#: 目录与文件名模板（§15.6：depth_shot_{id}/frame_0001.png）
DEPTH_DIR_TEMPLATE = "depth_shot_{shot_id}"
DEPTH_FRAME_PREFIX = "frame_"


def depth_dir_name(shot_id: str) -> str:
    return DEPTH_DIR_TEMPLATE.format(shot_id=shot_id)


def depth_range_note() -> str:
    """README 里描述深度归一化的一行（跨镜头可比性的说明）。"""
    near, far = DEPTH_RANGE
    return (f"深度序列按固定范围 {near:g}–{far:g} 米归一化到 0–1"
            f"（越近越暗），跨镜头可直接比较。")


def depth_manifest_entry(shot_id: str, frames: int) -> Dict[str, object]:
    """写进 shots.json 的深度条目。"""
    return {"dir": depth_dir_name(shot_id), "frames": int(frames),
            "range_m": [DEPTH_RANGE[0], DEPTH_RANGE[1]],
            "pattern": f"{DEPTH_FRAME_PREFIX}%04d.png",
            "bit_depth": 16, "channels": "BW"}
