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
from mathutils import Vector  # noqa: E402

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


#: RK-16（§4.1，R43/R46 修正版）：代理形状 → 差分掩膜应占投影框的面积比。
#: **锥体（火焰）的侧影只有包围盒的约 30%**，一律按 0.5 会让正确实现恒红。
PROXY_RHO = {"flame": 0.30, "glow": 0.50, "spark": 0.30, "smoke": 0.50}
#: 掩膜内 |Δ| 的中位数下限。判据**不得预筛像素**——先按阈值筛再取均值是恒真式。
INSIDE_MEDIAN_MIN = 0.05
#: 投影框外的环形区必须没有变化（留 1/255 的抗锯齿余量）。
OUTSIDE_MEDIAN_MAX = 1.0 / 255.0


def _proxy_screen_box(obj, scene, camera):
    """代理由 ``world_to_camera_view`` 独立算出的**投影框**（像素）。"""
    from bpy_extras.object_utils import world_to_camera_view

    width = float(scene.render.resolution_x)
    height = float(scene.render.resolution_y)
    points = [world_to_camera_view(scene, camera,
                                   obj.matrix_world @ Vector(corner))
              for corner in obj.bound_box]
    xs = [point.x * width for point in points]
    ys = [point.y * height for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def t_rk16_crowd_visibility():
    """RK-16（§4.1 R43/R46）：代理可见性必须用**差分掩膜**判定。

    旧判据（先按 ``abs(after-before) > 0.08`` 筛像素、再对筛出来的像素求均值
    ``> 0.05``）是**恒真式**：筛完必然 > 0.08 > 0.05，抓不到任何回归，真正
    起作用的只有那条 coverage。这里换成四条外生判据：

    ① 掩膜 = ``|Δ| ≥ 1/255`` ∩ **投影框**（不是 bbox 当剪影），连通域 ≥1；
    ② 掩膜内 ``median|Δ| ≥ 0.05``；
    ③ ``|掩膜| ≥ ρ × 投影框面积``，ρ 按代理形状取（锥 ≈0.30、球 ≈0.50）；
    ④ 框外 1.5 倍环形区的 ``median|Δ| < 1/255``（负对照；显式关阴影）。
    """
    vfx = [{"id": "flame", "type": "flame", "position": [0.0, 0.0, 1.0],
            "size": [0.5, 0.5, 1.2], "start_frame": 1, "end_frame": 48}]
    _plan, _spec, summary = _built(vfx=vfx)
    obj = bpy.data.objects.get("BD_VFX_flame")
    if obj is None:
        return {"ok": False, "reason": "特效对象没有创建"}
    scene = bpy.context.scene
    scene.camera = bpy.data.objects["BD_Cam_shot_001"]
    # 阴影会污染"框外必须没有变化"这条负对照（§4.1 RK-16 明文要求显式关闭）。
    shading = getattr(scene.display, "shading", None)
    if shading is not None:
        shading.show_shadows = False
    camera = scene.camera
    on_pixels = render_pixels("vfx_on", 24)
    scene.frame_set(24)
    bpy.context.view_layer.update()
    inside_window = not obj.hide_render
    box = _proxy_screen_box(obj, scene, camera)
    scene.frame_set(150)
    outside_window = bool(obj.hide_render)
    scene.frame_set(24)
    # 代理的 hide_render 是**有关键帧**的，手动改值会被下一帧动画覆盖回
    # False；要拿"没有代理"的对照就得真的把它移出场景。
    bpy.data.objects.remove(obj, do_unlink=True)
    off_pixels = render_pixels("vfx_off", 24)
    scene.frame_set(1)
    bpy.context.view_layer.update()

    width = int(scene.render.resolution_x)
    height = int(scene.render.resolution_y)
    # ``render_pixels`` 返回的是**逐像素亮度**（1 个浮点/像素），不是 RGBA；
    # 差分直接逐像素做，**不做任何预筛**（预筛就是旧判据变恒真式的原因）。
    deltas = [abs(after - before)
              for after, before in zip(on_pixels, off_pixels)]

    center_x = (box[0] + box[2]) / 2.0
    center_y = (box[1] + box[3]) / 2.0
    ring_half_w = (box[2] - box[0]) * 0.75
    ring_half_h = (box[3] - box[1]) * 0.75
    inside_values = []
    outside_values = []
    for index, delta in enumerate(deltas):
        x, y = index % width, index // width
        in_box = box[0] <= x <= box[2] and box[1] <= y <= box[3]
        if in_box:
            if delta >= 1.0 / 255.0:
                inside_values.append(delta)
        elif abs(x - center_x) <= ring_half_w and abs(y - center_y) <= ring_half_h:
            outside_values.append(delta)
    _ = height

    box_area = max((box[2] - box[0]) * (box[3] - box[1]), 1.0)
    rho = PROXY_RHO.get("flame", 0.5)
    inside_median = _median(inside_values)
    outside_median = _median(outside_values)
    coverage = len(inside_values) / box_area
    ok = (summary["vfx"] == 1 and inside_window and outside_window
          and len(inside_values) > 0
          and inside_median >= INSIDE_MEDIAN_MIN
          and coverage >= rho
          and outside_median < OUTSIDE_MEDIAN_MAX)
    return {"ok": ok, "box": [round(value, 1) for value in box],
            "box_area": round(box_area, 1),
            "inside_pixels": len(inside_values),
            "inside_median_delta": round(inside_median, 5),
            "inside_min_delta": INSIDE_MEDIAN_MIN,
            "coverage": round(coverage, 4), "rho": rho,
            "outside_pixels": len(outside_values),
            "outside_median_delta": round(outside_median, 6),
            "outside_max_delta": round(OUTSIDE_MEDIAN_MAX, 6),
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
    check("rk16_crowd_visibility", t_rk16_crowd_visibility)
    check("prop_shapes_are_not_all_boxes", t_prop_shapes_are_not_all_boxes)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
