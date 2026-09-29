"""v1.4 P10 / RK-4 / RK-14 / RK-15：角色几何与取景的渲染级验收。

三条独立 oracle（都不读被测实现自写的字段）：

* **RK-14**：头球**不被躯干遮挡**——只渲头得 ``P_head``，再拿"整身"与
  "隐藏头部"两张图的差分得"头可见像素"，比例 ≥ 99%；
* **RK-15**：每个含头部景别（``framing.HEAD_SHOTS``）的首帧，轮廓顶行到
  画面上沿的留白 ≥ 8% × 画面高（board 档，§2.2）；
* **RK-4**：眼材质 == ``config.character.eye_color``（默认 ``#101010``），
  且"隐藏/显示眼睛"两次渲染的差分里左右**各**有 ≥1 个连通域、每域 ≥9 px。

运行：blender --background --factory-startup --python tools/blender_tests/test_character_geometry.py
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

import bpy  # noqa: E402

from block_director.cinema.anchor import DEFAULT_PROFILE as PROFILE  # noqa: E402
from block_director.cinema.framing import HEAD_SHOTS  # noqa: E402
from block_director.layer3_engine.character_system import (  # noqa: E402
    create_character,
)
from block_director.layer3_engine.character_system import (  # noqa: E402
    character_factory,
)
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    place_camera_for_shot,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.settings import get_config  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"
WIDTH, HEIGHT = 640, 360
BG = (0.05, 0.05, 0.06)
TOL = 0.02


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene():
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
        display.shading.background_color = BG
        display.shading.show_shadows = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    scene.world.color = BG
    ensure_collections(scene)
    os.makedirs(OUTDIR, exist_ok=True)
    return scene


def render_pixels(name: str) -> list:
    scene = bpy.context.scene
    path = str(OUTDIR / f"geom_{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(path)
    try:
        return list(image.pixels)
    finally:
        bpy.data.images.remove(image)


def _mask(pixels, reference) -> list:
    """与参考色差异超过容差的像素（行序：先底行后顶行，与 pixels 一致）。"""
    out = []
    for index in range(0, len(pixels), 4):
        delta = max(abs(pixels[index] - reference[0]),
                    abs(pixels[index + 1] - reference[1]),
                    abs(pixels[index + 2] - reference[2]))
        out.append(delta > TOL)
    return out


def _reference(pixels) -> tuple:
    """取左上角像素作背景参考（场景里没有角色时它是纯背景）。"""
    top_left = ((HEIGHT - 1) * WIDTH) * 4
    return (pixels[top_left], pixels[top_left + 1], pixels[top_left + 2])


def _components(mask, *, min_area: int = 9):
    """8 邻接连通域（面积 ≥ min_area），返回 ``[(area, cx), ...]``。"""
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
            found.append((len(pixels),
                          sum(p % WIDTH for p in pixels) / len(pixels)))
    return found


def _character_parts(character):
    return list(character.meshes)


def _show(character, *, head=True, body=True, eyes=True, legs=True) -> None:
    parts = character.parts
    wanted = {"head": head, "body": body,
              "eye_l": eyes, "eye_r": eyes,
              "leg_l": legs, "leg_r": legs}
    for key, obj in parts.items():
        if key in wanted:
            obj.hide_render = not wanted[key]


# --------------------------------------------------------------------------- #
# 1. 输入契约（校核推导，不是"看起来对"）
# --------------------------------------------------------------------------- #
def t_input_contract():
    fresh_scene()
    create_character("char_001", "小明", "#FF6B6B")

    gap = PROFILE.head_center_z - (PROFILE.leg_h + PROFILE.torso_h
                                   + PROFILE.head_r)
    _, forward = PROFILE.eye_offset()
    expected_forward = character_factory.EYE_FORWARD
    config = get_config()
    eye_material = bpy.data.materials.get("BD_Mat_char_001_Eye")
    colour = (tuple(round(v, 4) for v in eye_material.node_tree
                    .nodes["Principled BSDF"].inputs["Base Color"]
                    .default_value[:3])
              if eye_material and eye_material.use_nodes else None)
    wanted = config.character.eye_color
    return {"ok": (abs(gap) <= 0.005
                   and 0.012 <= PROFILE.eye_protrusion <= 0.020
                   and abs(forward - expected_forward) < 1e-6
                   and colour is not None and max(colour) < 0.2),
            "neck_gap": round(gap, 6),
            "eye_protrusion": PROFILE.eye_protrusion,
            "eye_forward": round(forward, 6),
            "factory_eye_forward": round(expected_forward, 6),
            "eye_color_config": wanted, "eye_color_node": colour,
            "head_top": round(PROFILE.head_top_z, 4)}


# --------------------------------------------------------------------------- #
# 2. RK-14：头球不被躯干遮挡
# --------------------------------------------------------------------------- #
def t_head_is_not_occluded():
    fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B")
    place_camera_for_shot("cu", (0.0, 0.0, 0.0), shot_type="CU", side="front")

    _show(character, head=False, body=False, eyes=False, legs=False)
    empty = render_pixels("empty")
    reference = _reference(empty)

    _show(character, head=True, body=False, eyes=True, legs=False)
    head_mask = _mask(render_pixels("head_only"), reference)

    _show(character, head=True, body=True, eyes=True, legs=True)
    full = render_pixels("full")
    _show(character, head=False, body=True, eyes=False, legs=True)
    hidden = render_pixels("head_hidden")

    visible = [a > TOL for a in
               (max(abs(full[i] - hidden[i]), abs(full[i + 1] - hidden[i + 1]),
                    abs(full[i + 2] - hidden[i + 2]))
                for i in range(0, len(full), 4))]
    head_pixels = sum(1 for item in head_mask if item)
    visible_pixels = sum(1 for item in visible if item)
    ratio = (visible_pixels / head_pixels) if head_pixels else 0.0
    return {"ok": head_pixels >= 100 and ratio >= 0.99,
            "head_pixels": head_pixels, "visible_head_pixels": visible_pixels,
            "visible_ratio": round(ratio, 4)}


# --------------------------------------------------------------------------- #
# 3. RK-15：含头部景别的头顶留白 ≥ 8%
# --------------------------------------------------------------------------- #
def t_headroom_is_at_least_eight_percent():
    fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B")
    _show(character)
    measured = {}
    worst = 1.0
    for shot_type in HEAD_SHOTS:
        place_camera_for_shot(shot_type.lower(), (0.0, 0.0, 0.0),
                              shot_type=shot_type, side="front")
        pixels = render_pixels(f"headroom_{shot_type}")
        reference = _reference(pixels)
        mask = _mask(pixels, reference)
        rows = [index // WIDTH for index, hit in enumerate(mask) if hit]
        if not rows:
            measured[shot_type] = None
            worst = -1.0
            continue
        top_row = max(rows)              # pixels 从底行开始
        margin = (HEIGHT - 1 - top_row) / float(HEIGHT)
        measured[shot_type] = round(margin, 4)
        worst = min(worst, margin)
    return {"ok": worst >= 0.08 - 1.0 / HEIGHT, "margins": measured,
            "worst": round(worst, 4), "threshold": round(0.08 - 1.0 / HEIGHT, 4)}


# --------------------------------------------------------------------------- #
# 4. RK-4：眼睛确实渲染出来，且左右各一簇
# --------------------------------------------------------------------------- #
def t_eyes_render_as_two_clusters():
    fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B")
    place_camera_for_shot("cu", (0.0, 0.0, 0.0), shot_type="CU", side="front")

    _show(character, eyes=False)
    without = render_pixels("no_eyes")
    _show(character, eyes=True)
    with_eyes = render_pixels("with_eyes")
    diff = [max(abs(with_eyes[i] - without[i]),
                abs(with_eyes[i + 1] - without[i + 1]),
                abs(with_eyes[i + 2] - without[i + 2])) > TOL
            for i in range(0, len(with_eyes), 4)]

    left = _components([hit and (index % WIDTH) < WIDTH / 2
                        for index, hit in enumerate(diff)])
    right = _components([hit and (index % WIDTH) >= WIDTH / 2
                         for index, hit in enumerate(diff)])
    return {"ok": bool(left) and bool(right),
            "left_clusters": left, "right_clusters": right,
            "diff_pixels": sum(1 for item in diff if item)}


def main() -> int:
    capture_main_thread()
    check("input_contract", t_input_contract)
    check("head_is_not_occluded", t_head_is_not_occluded)
    check("headroom_is_at_least_eight_percent",
          t_headroom_is_at_least_eight_percent)
    check("eyes_render_as_two_clusters", t_eyes_render_as_two_clusters)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
