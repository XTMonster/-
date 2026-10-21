"""Ticket 06：Blockout 序列回放一致性审查 + 参考视频/映射输出（bpy 侧）。

逐分镜完成后按序列回放：把每镜首/中/末帧在 Blender 时间线上走一遍（无崩溃），
渲染低采样 16:9 每镜 mp4 并经既有 ``concat_shot_clips`` 拼成一条
``blockout_full.mp4``；五维一致性结论（空间连续/出入画/相机方向/光照方向/
转场）由纯层 ``cinema.blockout_sequence`` 从 manifest 判定，本模块负责
回放动作与产出落盘（``sequence_review.json`` + ``mapping.json``）。

确定性：同一 manifest + 场景两次回放报告逐位一致；映射表与 shot_table 的
downstream_map 一一对应。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import bpy

from ..cinema.blockout_sequence import build_blockout_sequence_review
from ..contracts.blockout import manifest_fingerprint
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .concat import FULL_NAME, concat_shot_clips, full_output_path
from .renderer import render_shot_video

log = get_logger("blockout-sequence")

#: 序列审查报告文件名。
SEQUENCE_REVIEW_FILENAME = "sequence_review.json"

#: 下游映射表文件名。
MAPPING_FILENAME = "mapping.json"

#: 每镜 mp4 目录名。
SHOT_VIDEO_DIRNAME = "shot_videos"


def _playback_frames(camera: Mapping[str, Any]) -> List[int]:
    """每镜回放采样帧：首/中/末（确定性，与 preview 同口径）。"""
    start = int(camera.get("start_frame") or 1)
    end = int(camera.get("end_frame") or start)
    return sorted({start, (start + end) // 2, end})


def _playback(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """把每镜首/中/末帧在时间线上走一遍；记录相机实际位置（实测证据）。"""
    scene = bpy.context.scene
    observed: List[Dict[str, Any]] = []
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        camera_obj = bpy.data.objects.get(
            f"BD_Blockout_{camera.get('camera_id')}")
        states = []
        for frame in _playback_frames(camera):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            location = None
            if camera_obj is not None:
                location = [round(float(v), 4)
                            for v in camera_obj.matrix_world.translation]
            states.append({"frame": frame, "location": location})
        observed.append({"shot_id": shot_id, "frames": states})
    return {"shots": observed, "ok": True}


@main_thread_only("render_blockout_sequence_video")
def render_blockout_sequence_video(
    manifest: Mapping[str, Any],
    out_dir: Path | str,
    *,
    fps: int = 24,
    preset: str = "hd16x9",
    shot_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """逐镜渲染 16:9 低采样 mp4 并拼接成全片参考视频。

    复用既有 ``render_shot_video`` + ``concat_shot_clips``（不另起炉灶）；
    逐镜文件入 ``shot_videos/``，全片 ``blockout_full.mp4``。返回每镜
    ``{shot_id, video, frames}`` 清单 + 全片结果。
    """
    out_dir = Path(out_dir)
    video_dir = out_dir / SHOT_VIDEO_DIRNAME
    video_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene

    clips: List[str] = []
    clip_frames: List[int] = []
    shot_videos: List[Dict[str, Any]] = []
    allowed = ({str(item) for item in shot_ids}
               if shot_ids is not None else None)
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        if allowed is not None and shot_id not in allowed:
            continue
        camera_obj = bpy.data.objects.get(
            f"BD_Blockout_{camera.get('camera_id')}")
        if camera_obj is not None:
            scene.camera = camera_obj
        start = int(camera.get("start_frame") or 1)
        end = int(camera.get("end_frame") or start)
        #: 与既有导出器同口径：base 带 .mp4 后缀，Blender 才不把帧号插进
        #: 文件名（实测裸名会产出 shot_0010001-0024.mp4）。
        base = video_dir / f"blockout_{shot_id}.mp4"
        #: 粗排逐镜 staging 的隔离语义必须延续到最终 MP4：其它镜头的
        #: 角色/持有道具不能作为本镜前景被烘进参考视频。只隔离 owned
        #: characters/props；环境锚点保留。异常路径也必须恢复原状态。
        from .blockout_preview import (
            _apply_character_staging,
            _restore_character_staging,
            _shot_isolation_objects,
        )

        shot_row = next(
            (row for row in manifest.get("shot_table") or []
             if str(row.get("shot_id") or "") == shot_id), {})
        isolated = _shot_isolation_objects(manifest, shot_row)
        previous = [(obj, bool(obj.hide_render)) for obj in isolated]
        for obj in isolated:
            obj.hide_render = True
        staged_previous: Dict[str, Any] = {}
        try:
            staged_previous, _staging_audit = _apply_character_staging(
                manifest, shot_id)
            try:
                path, frames = render_shot_video(
                    scene, start, end, str(base), codec="H264", crf="LOW")
            finally:
                _restore_character_staging(staged_previous)
        finally:
            if staged_previous:
                _restore_character_staging(staged_previous)
            for obj, hide_render in previous:
                obj.hide_render = hide_render
        clips.append(path)
        clip_frames.append(frames)
        shot_videos.append({"shot_id": shot_id, "video": path,
                            "frames": frames})

    full_path = full_output_path(out_dir)
    concat_result = concat_shot_clips(
        scene, clips, full_path,
        clip_frames=clip_frames, preset=preset, fps=fps,
        codec="H264", crf="MEDIUM")
    return {
        "shot_videos": shot_videos,
        "full_video": concat_result,
        "full_path": str(full_path),
    }


@main_thread_only("run_blockout_sequence_review")
def run_blockout_sequence_review(
    manifest: Mapping[str, Any],
    out_dir: Path | str,
    *,
    render_video: bool = False,
) -> Dict[str, Any]:
    """序列回放一致性审查：回放 + 五维报告 + （可选）参考视频 + 映射表。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    playback = _playback(manifest)
    review = build_blockout_sequence_review(
        manifest=manifest,
        manifest_fingerprint=manifest_fingerprint(manifest),
        notes=["bpy 序列回放：首/中/末帧时间线评估无崩溃"])

    #: 映射表：shot_id -> downstream_map（与 shot_table 一一对应）
    mapping: Dict[str, Any] = {
        "schema_version": "blockout-mapping/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "shots": {
            str(row.get("shot_id") or ""):
                dict(row.get("downstream_map") or {})
            for row in (manifest.get("shot_table") or [])
        },
    }

    video_result: Dict[str, Any] = {"rendered": False}
    if render_video:
        video_result = render_blockout_sequence_video(manifest, out_dir)
        video_result["rendered"] = True
        mapping["reference_videos"] = {}
        for shot in video_result.get("shot_videos") or []:
            mapping["reference_videos"][shot["shot_id"]] = shot["video"]
        mapping["full_video"] = video_result.get("full_path")

    (out_dir / SEQUENCE_REVIEW_FILENAME).write_text(
        json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    (out_dir / MAPPING_FILENAME).write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")

    return {
        "playback": playback,
        "review": review,
        "mapping": mapping,
        "video": video_result,
        "outputs": {
            "review": str(out_dir / SEQUENCE_REVIEW_FILENAME),
            "mapping": str(out_dir / MAPPING_FILENAME),
            "full_video": video_result.get("full_path")
            if video_result.get("rendered") else None,
        },
    }


__all__ = [
    "run_blockout_sequence_review",
    "render_blockout_sequence_video",
    "SEQUENCE_REVIEW_FILENAME",
    "MAPPING_FILENAME",
    "SHOT_VIDEO_DIRNAME",
]
