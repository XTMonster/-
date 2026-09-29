"""v1.3 P6：群众代理、特效代理与道具形状的 Blender 端验收。

覆盖三件纯 Python 验证不了的事：

1. 群众是**共享网格的实例**、确定性排布、**不进** context.characters、不带标签；
2. 特效代理真的进画面（RK-2：与"隐藏它"的同一帧做亮度差比较）；
3. 道具形状库真的造出不同形状（v1.2 一律是盒子）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_crowd_vfx.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_executor import (  # noqa: E402
    PROP_SHAPES,
    build_environment,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = Path(tempfile.gettempdir()) / "bd_crowd_vfx"


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    scene.render.image_settings.file_format = "PNG"
    display = scene.display.shading if hasattr(scene, "display") else None
    if display is not None:
        display.light = "STUDIO"
        display.color_type = "MATERIAL"
        display.background_type = "VIEWPORT"
        display.background_color = (0.10, 0.11, 0.14)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    ensure_collections(scene)
    return scene


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def render_luma(name: str, frame: int) -> float:
    """整帧平均亮度（用于"有没有变化"的粗判）。"""
    pixels = render_pixels(name, frame)
    return round(sum(pixels) / max(len(pixels), 1), 5) if pixels else -1.0


def render_pixels(name: str, frame: int) -> list:
    """渲染一帧并返回逐像素亮度（RGB 平均，忽略 alpha）。"""
    scene = bpy.context.scene
    os.makedirs(OUTDIR, exist_ok=True)
    path = str(OUTDIR / f"{name}.png")
    scene.frame_set(frame)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        return []
    image = bpy.data.images.load(path)
    try:
        pixels = list(image.pixels)
    finally:
        bpy.data.images.remove(image)
    return [(pixels[index] + pixels[index + 1] + pixels[index + 2]) / 3.0
            for index in range(0, len(pixels), 4)]


CROWD = [{"count": 12, "mode": "walk", "seed": 3, "spread": 8.0,
          "label": "背景有大量路人"}]


def _built(crowd=None, vfx=None, props=None):
    fresh_scene()
    plan = two_shot_plan()
    if vfx:
        plan.shots[0].vfx = vfx
    spec = SceneSpec.from_plan(plan, crowd=crowd)
    if props is not None:
        spec.props = props
    summary = build_scene(plan, spec, clear_scene=True).to_dict()
    return plan, spec, summary


def t_crowd_instances_share_one_mesh_and_stay_out_of_the_cast():
    _plan, _spec, summary = _built(crowd=CROWD)
    context = get_context()
    objects = [obj for obj in bpy.data.objects
               if obj.name.startswith("BD_Crowd_")]
    meshes = {obj.data.name for obj in objects}
    labels = [obj for obj in bpy.data.objects
              if obj.name.startswith("BD_Label_")]
    # 群众**不在** characters 里；标签只给两个角色（填充 + 描边 = 4 个）
    crowd_ids = {obj.name for obj in objects}
    cast_names = {getattr(item, "name", "") for item in context.character_list
                  if item is not None}
    return {"ok": (summary["crowd"] == 12 and len(objects) == 12
                   and len(meshes) == 1
                   and len(context.crowd) == 12
                   and len(context.character_list) == 2
                   and not (crowd_ids & cast_names)
                   and len(labels) == 4),
            "count": len(objects), "meshes": len(meshes),
            "context_crowd": len(context.crowd),
            "characters": len(context.character_list),
            "labels": len(labels)}


def t_crowd_layout_is_deterministic():
    _plan, _spec, _summary = _built(crowd=CROWD)
    first = sorted((obj.name, tuple(round(v, 4) for v in obj.location))
                   for obj in bpy.data.objects
                   if obj.name.startswith("BD_Crowd_"))
    _built(crowd=CROWD)
    second = sorted((obj.name, tuple(round(v, 4) for v in obj.location))
                    for obj in bpy.data.objects
                    if obj.name.startswith("BD_Crowd_"))
    # 位置取的是第 1 帧（walk 的起点），两次重建必须完全一致
    return {"ok": first == second and len(first) == 12,
            "first": first[:3], "second": second[:3]}


def t_crowd_walks_with_keyframes():
    _built(crowd=CROWD)
    obj = bpy.data.objects["BD_Crowd_001"]
    animated = obj.animation_data is not None and obj.animation_data.action
    scene = bpy.context.scene
    scene.frame_set(1)
    bpy.context.view_layer.update()
    start = tuple(obj.location)
    scene.frame_set(int(scene.frame_end))
    bpy.context.view_layer.update()
    end = tuple(obj.location)
    moved = abs(end[0] - start[0]) > 0.1
    scene.frame_set(1)
    bpy.context.view_layer.update()
    return {"ok": bool(animated) and moved, "start": start, "end": end}


def t_vfx_is_visible_in_the_render():
    """RK-2：特效代理区域与背景的平均亮度差必须 > 0.05，且只在时间窗内可见。

    整帧平均会被背景稀释（代理只占几个百分点），所以按**逐像素差**先找出
    代理覆盖的像素，再比较区域与背景的平均亮度——这才是"看得见"的判据。
    """
    vfx = [{"id": "flame", "type": "flame", "position": [0.0, 0.0, 1.0],
            "size": [0.5, 0.5, 1.2], "start_frame": 1, "end_frame": 48}]
    _plan, _spec, summary = _built(vfx=vfx)
    obj = bpy.data.objects.get("BD_VFX_flame")
    if obj is None:
        return {"ok": False, "reason": "特效对象没有创建"}
    scene = bpy.context.scene
    scene.camera = bpy.data.objects["BD_Cam_shot_001"]
    on_pixels = render_pixels("vfx_on", 24)
    # 注意：代理的 hide_render 是**有关键帧**的，手动改值会被下一帧的动画
    # 覆盖回 False（这正是 v1.3 已经踩过一次的坑）。要拿"没有代理"的对照
    # 就得真的把它移出场景。
    scene.frame_set(24)
    inside_window = not obj.hide_render
    scene.frame_set(150)
    outside_window = bool(obj.hide_render)
    scene.frame_set(24)
    bpy.data.objects.remove(obj, do_unlink=True)
    off_pixels = render_pixels("vfx_off", 24)
    scene.frame_set(1)
    bpy.context.view_layer.update()

    # 先按"明显变化"找出代理真正覆盖的像素（阈值 0.08 高于抗锯齿边缘的
    # 微差），再比较这块区域在有/无代理时的平均亮度。
    changed = [index for index, (before, after)
               in enumerate(zip(off_pixels, on_pixels))
               if abs(after - before) > 0.08]
    # RK-2 的判据是"代理区域与背景的平均亮度差"。背景**逐个像素**不同
    # （火焰一半压在地面上、一半压在背景板上，有亮有暗），所以取逐像素
    # 绝对差的均值——有符号均值会正负抵消，反而测不出"看不看得见"。
    deltas = [abs(on_pixels[index] - off_pixels[index])
              for index in changed]
    delta = sum(deltas) / len(deltas) if deltas else 0.0
    signed = ((sum(on_pixels[index] for index in changed)
               - sum(off_pixels[index] for index in changed))
              / len(changed)) if changed else 0.0
    coverage = len(changed) / max(len(on_pixels), 1)
    return {"ok": (summary["vfx"] == 1 and inside_window and outside_window
                   and coverage > 0.005
                   and delta > 0.05),
            "coverage": round(coverage, 5),
            "mean_abs_delta": round(delta, 5),
            "signed_delta": round(signed, 5),
            "inside_window": inside_window,
            "hidden_outside_window": outside_window}


def t_prop_shapes_are_not_all_boxes():
    fresh_scene()
    props = [{"id": f"p{index}", "position": [float(index) * 2.0, -4.0, 0.4],
              "size": [0.6, 0.6, 0.6], "shape": shape}
             for index, shape in enumerate(PROP_SHAPES)]
    environment = build_environment(props=props)
    shapes = {obj.name: obj.get("bd_shape") for obj in environment.props}
    vertices = {obj.get("bd_shape"): len(obj.data.vertices)
                for obj in environment.props}
    return {"ok": len(environment.props) == len(PROP_SHAPES)
            and len(set(shapes.values())) == len(PROP_SHAPES)
            and len(set(vertices.values())) > 3,
            "shapes": sorted(shapes.values()), "vertices": vertices}


def main() -> int:
    capture_main_thread()
    check("crowd_instances_share_one_mesh_and_stay_out_of_the_cast",
          t_crowd_instances_share_one_mesh_and_stay_out_of_the_cast)
    check("crowd_layout_is_deterministic", t_crowd_layout_is_deterministic)
    check("crowd_walks_with_keyframes", t_crowd_walks_with_keyframes)
    check("vfx_is_visible_in_the_render", t_vfx_is_visible_in_the_render)
    check("prop_shapes_are_not_all_boxes", t_prop_shapes_are_not_all_boxes)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
