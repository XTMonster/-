"""全片拼接（执行文档 v1.2 §15.7 的 `full_concat`）。

用 Blender **内置**的序列编辑器把各镜 mp4 按顺序接成一条
``blockout_full.mp4``：既不重渲染（拼接而不是再渲染一遍），也不需要外部
ffmpeg——§21.5 的 `external_ffmpeg_path` 因此只是可选的加速/替代路径。

时序约定：每个片段在前一段结束的下一帧开始，因此全片长度 = 各片段之和；
这也让"拼接结果与分镜时长一致"成为可断言的等式。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Sequence

import bpy

from ..contracts.enums import resolution_for
from ..utils.blender_compat import configure_video_output, sequence_strips
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("delivery.concat")

FULL_NAME = "blockout_full.mp4"


class ConcatUnavailable(RuntimeError):
    """没有可拼接的片段。消息里给出可执行的下一步。"""


@main_thread_only("concat_shot_clips")
def concat_shot_clips(scene, clips: Sequence[str], output_base: str, *,
                      clip_frames: Sequence[int] = (),
                      preset: str = "hd16x9", fps: int = 24,
                      codec: str = "H264", crf: str = "MEDIUM"
                      ) -> Dict[str, object]:
    """把 ``clips`` 按顺序接成一条全片视频。

    ``clip_frames`` 是每个片段的确切帧数（分段渲染时已知）。给了就按它**钉死**
    片段长度：VSE 从容器元数据推算时长时会多算一帧，累计下来全片会比各镜之和
    长出好几帧——那不是我们想要的"全片"。
    """
    existing = [path for path in clips if os.path.exists(path)]
    if not existing:
        raise ConcatUnavailable("没有可拼接的分镜视频；请先确认 per_shot_clips 已产出")

    previous = {
        "use_sequencer": getattr(scene.render, "use_sequencer", False),
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        #: Blender 5.x 的 image_settings 按 media_type 拆成 IMAGE / VIDEO
        #: 两套枚举：configure_video_output 会先切 media_type="VIDEO" 再写
        #: file_format="FFMPEG"。还原顺序必须先 media_type 再 file_format，
        #: 与 export_sandbox 的 SANDBOX_KEYS 同一纪律（反着还原会在
        #: media_type=VIDEO 下写图片枚举而抛 TypeError）。
        "media_type": getattr(scene.render.image_settings, "media_type", "IMAGE"),
        "file_format": getattr(scene.render.image_settings, "file_format", "PNG"),
    }
    width, height = resolution_for(preset)
    editor = scene.sequence_editor or scene.sequence_editor_create()
    added = []
    try:
        strips = sequence_strips(editor)
        cursor = 1
        for index, path in enumerate(existing, start=1):
            strip = strips.new_movie(
                name=f"BD_Clip_{index:03d}", filepath=path, channel=1,
                frame_start=cursor)
            if index <= len(clip_frames):
                strip.frame_final_duration = max(int(clip_frames[index - 1]), 1)
            added.append(strip)
            # 实测：VSE 的 ``frame_final_end`` 是**开区间右端**（start=1、
            # 时长 6 → end=7）。写成 end+1 会让每段多出一帧的空白。
            cursor = int(strip.frame_final_end)

        scene.render.use_sequencer = True
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.fps = int(fps)
        scene.frame_start = 1
        scene.frame_end = cursor - 1
        configure_video_output(scene, output_base, codec=codec, crf=crf)
        bpy.ops.render.render(animation=True)
    finally:
        for strip in added:
            strips.remove(strip)
        scene.render.use_sequencer = previous["use_sequencer"]
        scene.frame_start = previous["frame_start"]
        scene.frame_end = previous["frame_end"]
        scene.render.fps = previous["fps"]
        scene.render.image_settings.media_type = previous["media_type"]
        scene.render.image_settings.file_format = previous["file_format"]

    produced = output_base
    if not os.path.exists(produced):
        for suffix in (".mp4", ".mkv", ".avi"):
            if os.path.exists(output_base + suffix):
                produced = output_base + suffix
                break
    log.info("全片拼接：%d 段 → %s", len(existing), produced)
    return {"ok": os.path.exists(produced), "path": produced,
            "clips": len(existing), "skipped": [p for p in clips
                                                if p not in existing],
            "frames": cursor - 1, "resolution": [width, height]}


def full_output_path(export_dir: str | Path) -> str:
    return str(Path(export_dir) / FULL_NAME)
