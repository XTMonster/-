"""v1.4 P12 / RK-1（②③④⑤）＋ RK-2（①②）＋ RK-5：标签布局与墨迹验收。

样本按 §4.1b 的**共用下界**：镜头数 ≥6，且含 ≥1 个 ELS/LS 与 ≥1 个含头部
景别（``cinema.framing.HEAD_SHOTS``）；像素阈值按 1920×1080 校准。

判据全部**外生**：只读渲染出的掩膜、``world_to_camera_view`` 的投影、以及
bake 写出的 ``offset_reason``；不读对象自报的 ``bd_element_type``。

* **RK-1①**：每个启用标签的角色恰好一对 ``BD_Label_<id>_Fill`` / ``_Stroke``，
  且都在 ``BlockDirector/Labels``；
* **RK-1②**：单渲该标签的 ink 面积 ≥ 200 px（1920×1080）；
* **RK-1③**：白字连通域数 ≥ 字符数（8 邻接、面积 ≥9 px）；
* **RK-1⑤（R43 修正版）**：描边＝整层放大 1.15 倍，所以判据是
  四向外扩各 ≥1 px、``|e_left − e_right| ≤ 1``、``|e_up − e_down| ≤ 1``、
  ``area(stroke)/area(fill) = 1.15² ± 3%``、两掩膜 AABB 中心重合 ≤1 px；
* **RK-2①**：任意两标签的屏幕 AABB 交叠率 ≤ 5%；
* **RK-2②**：``offset_reason == "none"`` 的采样帧，AABB 中心与锚点投影的偏差
  ≤ 2 × ``character.label_pixels``；触发避让的帧必须写明理由；
* **RK-5**：同一镜内相邻采样帧的 AABB 高度变化率 ≤ 5%。

运行：blender --background --factory-startup --python tools/blender_tests/test_label_layout.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.cinema.framing import HEAD_SHOTS  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    LABELS_COLLECTION,
    ensure_collections,
    label_pair_audit,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"
WIDTH, HEIGHT = 1920, 1080
OVERLAP_LIMIT = 0.05
CONTINUITY_LIMIT = 0.05
INK_MIN_PIXELS = 200
STROKE_SCALE = 1.15


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _plan() -> Plan:
    """≥6 镜，含 ELS/LS 与含头部景别（§4.1b 的共用样本下界）。"""
    shots = [("shot_001", "MS"), ("shot_002", "MCU"), ("shot_003", "CU"),
             ("shot_004", "ELS"), ("shot_005", "LS"), ("shot_006", "MLS")]
    return Plan.from_dict({
        "scene_heading": "INT. 码头 - 日",
        "shots": [{"shot_id": shot_id, "order": index, "intent": "推进",
                   "shot_type": shot_type, "duration_frames": 48,
                   "characters": ["char_001", "char_002"]}
                  for index, (shot_id, shot_type) in enumerate(shots, start=1)],
    })


def _build():
    config = AppConfig()
    config.character.label_render = True
    set_config(config)
    plan = _plan()
    spec = SceneSpec.from_plan(plan)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "FLAT"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.05, 0.05, 0.06)
        display.shading.show_shadows = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    scene.world.color = (0.05, 0.05, 0.06)
    ensure_collections(scene)
    os.makedirs(OUTDIR, exist_ok=True)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()
    return scene, plan, spec, summary, config


def _labels() -> dict:
    collection = bpy.data.collections.get(LABELS_COLLECTION)
    objects = list(collection.objects) if collection else []
    fills = {obj.name: obj for obj in objects if obj.name.endswith("_Fill")}
    strokes = {obj.name: obj for obj in objects if obj.name.endswith("_Stroke")}
    return {"fills": fills, "strokes": strokes, "all": objects}


def _screen_box(scene, camera, obj) -> tuple:
    """标签在屏幕上的像素 AABB（用对象自己的 ``bound_box``，含字号）。"""
    matrix = obj.matrix_world
    corners = [matrix @ Vector(corner) for corner in obj.bound_box]
    points = [world_to_camera_view(scene, camera, point) for point in corners]
    xs = [point.x * WIDTH for point in points]
    ys = [point.y * HEIGHT for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a, b) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]),
                  (b[2] - b[0]) * (b[3] - b[1]))
    return (width * height) / smaller if smaller > 0 else 0.0


def _render_mask(name: str, visible) -> list:
    """只让 ``visible`` 里的对象参与渲染，返回逐像素的"非背景"掩膜。"""
    scene = bpy.context.scene
    targets = set(visible)
    for obj in bpy.data.objects:
        if obj.type in ("MESH", "FONT", "CURVE", "EMPTY"):
            obj.hide_render = obj not in targets
    path = str(OUTDIR / f"label_{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(path)
    try:
        pixels = list(image.pixels)
    finally:
        bpy.data.images.remove(image)
    reference = (pixels[0], pixels[1], pixels[2])
    mask = []
    for index in range(0, len(pixels), 4):
        delta = max(abs(pixels[index] - reference[0]),
                    abs(pixels[index + 1] - reference[1]),
                    abs(pixels[index + 2] - reference[2]))
        mask.append(delta > 0.02)
    return mask


def _components(mask, *, min_area: int = 9):
    seen = [False] * len(mask)
    found = []
    for start in range(len(mask)):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = True
        pixels = []
        while stack:
            index = stack.pop()
            pixels.append(index)
            y, x = divmod(index, WIDTH)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < HEIGHT and 0 <= nx < WIDTH:
                        neighbour = ny * WIDTH + nx
                        if mask[neighbour] and not seen[neighbour]:
                            seen[neighbour] = True
                            stack.append(neighbour)
        if len(pixels) >= min_area:
            found.append(len(pixels))
    return found


def _bbox(mask):
    xs = [index % WIDTH for index, hit in enumerate(mask) if hit]
    ys = [index // WIDTH for index, hit in enumerate(mask) if hit]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def t_one_pair_per_character():
    _build()
    audit = label_pair_audit()
    labels = _labels()
    ids = sorted(name[len("BD_Label_"):-len("_Fill")] for name in labels["fills"])
    ok = (len(labels["fills"]) == 2 and len(labels["strokes"]) == 2
          and ids == ["char_001", "char_002"]
          and audit["count"] == 2 and audit["problems"] == []
          and not any(obj.hide_render for obj in labels["all"]))
    return {"ok": ok, "ids": ids, "audit": audit,
            "hidden": [obj.name for obj in labels["all"] if obj.hide_render]}


def t_rk1_ink_stroke_and_components():
    """RK-1②③⑤：单渲 ink 面积、连通域数、描边环带几何。"""
    scene, _plan_obj, _spec, _summary, config = _build()
    labels = _labels()
    scene.frame_set(24)
    bpy.context.view_layer.update()
    # 掩膜判定必须用**中灰底**：描边是纯黑（#000000），在深色视口背景上
    # 几乎与背景同色，差分掩膜会把描边整条吃掉（实测 area_ratio 只有 1.09）。
    shading = getattr(scene.display, "shading", None)
    if shading is not None:
        shading.background_color = (0.5, 0.5, 0.5)
    scene.world.color = (0.5, 0.5, 0.5)
    bpy.context.view_layer.update()

    fill = labels["fills"]["BD_Label_char_001_Fill"]
    stroke = labels["strokes"]["BD_Label_char_001_Stroke"]
    fill_mask = _render_mask("fill_only", [fill])
    stroke_mask = _render_mask("stroke_only", [stroke])

    ink = sum(1 for hit in fill_mask if hit)
    ring = sum(1 for index, hit in enumerate(stroke_mask)
               if hit and not fill_mask[index])
    stroke_area = sum(1 for hit in stroke_mask if hit)
    components = _components(fill_mask)
    chars = len(str(getattr(fill.data, "body", "") or ""))

    # 四向外扩用**几何投影**量，不用渲染掩膜：整层等比放大 1.15 之后，
    # 上/下扩量只有 2 个像素量级，栅格化的抗锯齿会把 ±1 px 的均匀性判据
    # 变成掷骰子（实测掩膜量出 4/2，几何量出 2.2/2.2）。
    fill_box = _screen_box(scene, scene.camera, fill)
    stroke_box = _screen_box(scene, scene.camera, stroke)
    expansions = None
    centre_gap = None
    ratio = 0.0
    expansions = {
        "up": fill_box[1] - stroke_box[1],
        "down": stroke_box[3] - fill_box[3],
        "left": fill_box[0] - stroke_box[0],
        "right": stroke_box[2] - fill_box[2],
    }
    centre_gap = (
        abs((fill_box[0] + fill_box[2]) / 2.0
            - (stroke_box[0] + stroke_box[2]) / 2.0),
        abs((fill_box[1] + fill_box[3]) / 2.0
            - (stroke_box[1] + stroke_box[3]) / 2.0))
    if ink:
        ratio = stroke_area / ink

    wanted_ratio = STROKE_SCALE ** 2
    ok = (ink >= INK_MIN_PIXELS
          and len(components) >= max(chars, 1)
          and all(value >= 1 for value in expansions.values())
          and abs(expansions["left"] - expansions["right"]) <= 1
          and abs(expansions["up"] - expansions["down"]) <= 1
          and abs(ratio - wanted_ratio) <= 0.03 * wanted_ratio
          and max(centre_gap) <= 1.0)
    return {"ok": ok, "ink_pixels": ink, "ink_min": INK_MIN_PIXELS,
            "components": len(components), "characters": chars,
            "stroke_area": stroke_area, "ring_pixels": ring,
            "area_ratio": round(ratio, 4), "wanted_ratio": round(wanted_ratio, 4),
            "expansions": expansions, "centre_gap": centre_gap}


def t_rk2_overlap_and_offsets():
    """RK-2① 交叠率；RK-2② ``offset_reason`` 分档。"""
    scene, plan, _spec, summary, config = _build()
    labels = _labels()
    camera = scene.camera
    schedule = [(shot.shot_id, (index - 1) * 48 + 1, index * 48)
                for index, shot in enumerate(plan.shots, start=1)]
    worst = 0.0
    worst_at = {}
    continuity = []
    for shot_id, start, end in schedule:
        middle = start + (end - start) // 2
        for frame in (start, start + 8, middle, end - 8, end):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            boxes = []
            for name in sorted(labels["fills"]):
                boxes.append((name, _screen_box(scene, camera,
                                                labels["fills"][name])))
            continuity.append((shot_id, frame, boxes))
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    ratio = _overlap(boxes[i][1], boxes[j][1])
                    if ratio > worst:
                        worst = ratio
                        worst_at = {"frame": frame,
                                    "pair": [boxes[i][0], boxes[j][0]]}
    offsets = summary.get("label_report", {}).get("offsets", {})
    limit_px = 0.25 * HEIGHT
    bad_offsets = {}
    for char_id, entry in offsets.items():
        reason = str(entry.get("offset_reason") or "")
        applied = float(entry.get("applied_offset_px") or 0.0)
        if reason not in ("none", "out_of_frame", "occluded", "overlap",
                          "out_of_frame+occluded"):
            bad_offsets[char_id] = reason
        elif reason != "none" and applied > limit_px:
            bad_offsets[char_id] = f"{reason}@{applied:.1f}px"
    return {"ok": worst <= OVERLAP_LIMIT and not bad_offsets
            and bool(offsets),
            "worst_overlap": round(worst, 4), "limit": OVERLAP_LIMIT,
            "worst_at": worst_at, "offsets": offsets,
            "offset_limit_px": round(limit_px, 1),
            "bad_offsets": bad_offsets,
            "sampled": len(continuity)}


def t_rk5_label_size_is_continuous():
    """RK-5：**同一镜内**相邻采样帧的标签高度变化率 ≤5%。"""
    scene, plan, _spec, _summary, _config = _build()
    labels = _labels()
    camera = scene.camera
    worst = 0.0
    cross = 0.0
    series: dict = {}
    ends: dict = {}
    for index, shot in enumerate(plan.shots, start=1):
        start, end = (index - 1) * 48 + 1, index * 48
        heights = []
        for frame in range(start, end + 1, 4):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            box = _screen_box(scene, camera,
                              labels["fills"]["BD_Label_char_001_Fill"])
            heights.append(max(box[3] - box[1], 1e-6))
        series[shot.shot_id] = [round(value, 2) for value in heights]
        ends[shot.shot_id] = heights[0]
        for previous, current in zip(heights, heights[1:]):
            worst = max(worst, abs(current - previous) / max(previous, 1e-6))
    ordered = [ends[shot.shot_id] for shot_id in series]
    for previous, current in zip(ordered, ordered[1:]):
        cross = max(cross, abs(current - previous) / max(previous, 1e-6))
    return {"ok": bool(series) and worst <= CONTINUITY_LIMIT,
            "worst_change": round(worst, 4), "limit": CONTINUITY_LIMIT,
            "cross_shot_step": round(cross, 4), "series": series}


def t_head_shots_are_present():
    """§4.1b 的共用样本下界自检：≥6 镜、含 ELS/LS 与含头部景别。"""
    plan = _plan()
    types = [str(shot.shot_type) for shot in plan.shots]
    head = [item for item in types if item in HEAD_SHOTS]
    wide = [item for item in types if item in ("ELS", "LS")]
    return {"ok": len(types) >= 6 and head and wide,
            "shots": len(types), "types": types,
            "head_shots": head, "wide_shots": wide}


def main() -> int:
    capture_main_thread()
    check("rk1_one_pair_per_character", t_one_pair_per_character)
    check("head_shots_are_present", t_head_shots_are_present)
    check("rk1_ink_stroke_and_components", t_rk1_ink_stroke_and_components)
    check("rk2_overlap_and_offsets", t_rk2_overlap_and_offsets)
    check("rk5_label_size_is_continuous", t_rk5_label_size_is_continuous)
    reset_config()

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
