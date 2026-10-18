"""Ticket 04：Blockout 低采样 16:9 预览渲染 + 数值/视觉自检（bpy 侧）。

对 Ticket 03 建好的体块场景，按 manifest 每镜渲染首/中/末三帧低采样 16:9
PNG（分辨率与画幅确定性），并采集数值证据（构图分/可见比例/画面占比/出入画/
设计 vs 实测偏差），经 ``cinema.blockout_report`` 折成版本化自检报告。
渲染帧同时作为执行 AI 视觉检查的输入——数据合法不等于视觉有效。

确定性：同一 manifest + 同一场景两次渲染设置逐位一致；报告两次构建逐位一致。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..cinema.blockout_report import (
    ON_SCREEN_MIN,
    build_blockout_report,
)
from ..cinema.composition import SubjectBox, evaluate_composition
from ..contracts.blockout import manifest_fingerprint
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("blockout-preview")

#: 预览分辨率：16:9 低采样（粗排只用低精度视觉自检，不做成片质量）。
PREVIEW_WIDTH = 1280
PREVIEW_HEIGHT = 720

#: 低采样帧数（EEVEE 抗锯齿采样；attr 存在才写，缺省由引擎默认）。
EEVEE_SAMPLES = 8

#: 遮挡射线采样点数（与 frustum_sampler 的 N=9 同口径）。
VISIBLE_POINTS = 9


def _subject_blocks(manifest: Mapping[str, Any]) -> Dict[str, str]:
    """manifest 角色体块 id -> 对象名（投影/遮挡判定用）。"""
    blocks: Dict[str, str] = {}
    for primitive in manifest.get("primitives") or []:
        source = primitive.get("source") or {}
        if primitive.get("kind") == "character" and source.get("id"):
            blocks[str(source["id"])] = f"BD_Blockout_{primitive['id']}"
    return blocks


def _block_object(node_name: str) -> Optional[bpy.types.Object]:
    return bpy.data.objects.get(node_name)


def _project_box(scene, camera, block) -> Optional[SubjectBox]:
    """把体块 8 个角投影成 NDC 包围盒（与 frustum_sampler 同法）。"""
    bounds = block.bound_box
    if not bounds:
        return None
    xs: List[float] = []
    ys: List[float] = []
    for corner in bounds:
        world = block.matrix_world @ Vector(corner)
        projected = world_to_camera_view(scene, camera, world)
        if float(projected.z) < 0.0:
            #: 相机背后的角点投影会镜像 x/y（与 frustum_sampler 的
            #: behind_camera 同口径）：跳过，避免包围盒被镜像角点拉满。
            continue
        xs.append(float(projected.x))
        ys.append(float(projected.y))
    if not xs:
        return None
    box = SubjectBox(
        name=str(block.name), left=min(xs), right=max(xs),
        top=max(ys), bottom=min(ys))
    return box


def _visible_fraction(scene, camera_pos: Vector, block,
                      depsgraph) -> float:
    """9 个采样点从相机到体块的遮挡判定（命中自身才计可见）。"""
    visible = 0
    bounds = block.bound_box
    if not bounds:
        return 0.0
    #: 采样点集：8 角 + 中心（与 frustum_sampler 的 N=9 同口径，
    #: 中心用于避免角点落在体块投影边缘时被自己的边挡掉）。
    points: List[Vector] = [
        block.matrix_world @ Vector(corner) for corner in bounds
    ]
    points.append(block.matrix_world.translation)
    for point in points[:VISIBLE_POINTS]:
        direction = point - camera_pos
        distance = direction.length
        if distance < 1e-6:
            continue
        unit = direction / distance
        hit, _location, _normal, _index, obj, _ = scene.ray_cast(
            depsgraph, camera_pos, unit,
            distance=distance + 0.001)
        if hit and obj is not None and obj.name == block.name:
            visible += 1
    return float(visible) / float(VISIBLE_POINTS)


def _max_deviation(manifest: Mapping[str, Any],
                   camera_objects: Mapping[str, bpy.types.Object],
                   shot_id: str) -> float:
    """设计 vs 实测：本镜机位起点与场景实测位置的最大偏差（米）。

    只对当前 shot 的相机、在该镜自己的 start_frame 处比对——运镜会在镜内
    移动相机，起点是 manifest 基准；拿别的镜的 start 去 set 帧会把运镜终点
    误算成偏差（多镜时尤其明显）。
    """
    deviation: float = 0.0
    for camera in manifest.get("cameras") or []:
        camera_shot_id = str(camera.get("shot_id") or "")
        if camera_shot_id != shot_id:
            continue
        camera_obj = camera_objects.get(camera_shot_id)
        if camera_obj is None or camera.get("position") is None:
            continue
        expected = [float(v) for v in camera["position"]]
        bpy.context.scene.frame_set(int(camera.get("start_frame") or 1))
        bpy.context.view_layer.update()
        actual = list(camera_obj.location)
        deviation = max(deviation, sum((a - e) ** 2
                                       for a, e in zip(actual, expected)) ** 0.5)
    return round(deviation, 4)


def _apply_preview_settings(scene) -> None:
    """16:9 低采样确定性设置（不改用户成片配置）。"""
    scene.render.resolution_x = PREVIEW_WIDTH
    scene.render.resolution_y = PREVIEW_HEIGHT
    scene.render.resolution_percentage = 100
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = EEVEE_SAMPLES


@main_thread_only("render_blockout_preview")
def render_blockout_preview(manifest: Mapping[str, Any],
                            out_dir: Path | str) -> Dict[str, Any]:
    """渲染每镜首/中/末帧 16:9 PNG 并产出数值自检报告。

    相机对象名沿用 Ticket 03：``BD_Blockout_cam_<shot_id>``；主体体块名
    ``BD_Blockout_char_<name>``。返回 report + previews + 证据路径。
    """
    #: 库函数防御：绝对化，避免 Blender 渲染把相对路径解析到引擎 CWD。
    out_dir = Path(out_dir).resolve()
    preview_dir = out_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    _apply_preview_settings(scene)
    subject_blocks = _subject_blocks(manifest)

    camera_objects: Dict[str, bpy.types.Object] = {}
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        camera_id = str(camera.get("camera_id") or f"cam_{shot_id}")
        obj = bpy.data.objects.get(f"BD_Blockout_{camera_id}")
        if obj is not None:
            camera_objects[shot_id] = obj

    per_shot: List[Dict[str, Any]] = []
    previews: List[Dict[str, Any]] = []
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        camera_obj = camera_objects.get(shot_id)
        if camera_obj is None or camera.get("position") is None:
            continue
        start = int(camera.get("start_frame") or 1)
        end = int(camera.get("end_frame") or start)
        frames = sorted({start, (start + end) // 2, end})
        scene.camera = camera_obj

        shot_table_row = next(
            (row for row in manifest.get("shot_table") or []
             if row.get("shot_id") == shot_id), {})
        subject_names = [str(name) for name in
                         (shot_table_row.get("character_ids") or [])]
        rendered_frames: List[Dict[str, Any]] = []
        comp_scores: List[float] = []
        visible_ratios: List[float] = []
        on_screen_ratios: List[float] = []
        off_screen = False
        blocks_found = 0
        boxes_total = 0

        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            depsgraph = bpy.context.evaluated_depsgraph_get()
            camera_pos = Vector(camera_obj.matrix_world.translation)
            png_path = preview_dir / f"{shot_id}_f{frame:04d}.png"
            scene.render.filepath = str(png_path)
            bpy.ops.render.render(write_still=True)
            rendered_frames.append({
                "frame": frame, "png": str(png_path),
                "bytes": png_path.stat().st_size if png_path.exists() else 0,
            })

            boxes = []
            occluded: Dict[str, bool] = {}
            for name in subject_names:
                block_name = subject_blocks.get(name)
                if not block_name:
                    continue
                block = _block_object(block_name)
                if block is None:
                    continue
                blocks_found += 1
                box = _project_box(scene, camera_obj, block)
                visible = _visible_fraction(scene, camera_pos, block, depsgraph)
                occluded[block.name] = visible <= 0.5
                visible_ratios.append(visible)
                if box is not None:
                    boxes.append(box)
                    boxes_total += 1
                    #: 出入画只在"主体几乎完全出画或不透明遮挡到近零"时置位；
                    #: 贴边/部分出画由构图分项处理，不当作整镜出入画硬伤。
                    if box.inside_ratio() <= ON_SCREEN_MIN or visible <= 0.0:
                        off_screen = True
                    on_screen_ratios.append(
                        float(box.inside_ratio()) * visible)

            if boxes:
                #: 粗排不猜景别：expected_height 传 None，framing 只按
                #: "主体是否出画"计分，不做细排的景别-高度匹配。
                report = evaluate_composition(
                    boxes, occluded=occluded, expected_height=None)
                comp_scores.append(float(report.score))

        #: 声明了主体、场景里也有体块，但整镜一个 box 都没投影出来
        #: （主体在相机背后/完全出画）：这是"主体不在画面内"而非"数据
        #: 缺失"——归零让纯层报 E_BLOCKOUT_EMPTY_WALL finding（as described
        #: in spec：主体投影近零 -> 相机对空墙）。主体体块对象缺失
        #: （blocks_found == 0）才保持 unresolved。
        if subject_names and blocks_found and not on_screen_ratios:
            on_screen_ratios.append(0.0)

        per_shot.append({
            "shot_id": shot_id,
            "empty": len(subject_names) == 0,
            "composition_score": (round(sum(comp_scores) / len(comp_scores), 2)
                                  if comp_scores else None),
            "visible_ratio": (round(sum(visible_ratios)
                                    / len(visible_ratios), 4)
                              if visible_ratios else None),
            "on_screen_ratio": (round(max(on_screen_ratios), 4)
                                if on_screen_ratios else None),
            "off_screen": bool(off_screen),
            "design_diff": {"max_deviation_m":
                            _max_deviation(manifest, camera_objects, shot_id)},
            "frames": rendered_frames,
        })
        previews.extend(rendered_frames)

    report = build_blockout_report(
        manifest=manifest,
        per_shot=per_shot,
        manifest_fingerprint=manifest_fingerprint(manifest),
        notes=["16:9 低采样预览；数值自检 + 渲染帧供执行 AI 视觉检查"])

    return {
        "report": report,
        "previews": previews,
        "evidence_dir": str(out_dir),
        "settings": {
            "resolution": [PREVIEW_WIDTH, PREVIEW_HEIGHT],
            "aspect": round(PREVIEW_WIDTH / PREVIEW_HEIGHT, 4),
            "eevee_samples": EEVEE_SAMPLES,
        },
    }


__all__ = ["render_blockout_preview", "PREVIEW_WIDTH", "PREVIEW_HEIGHT"]
