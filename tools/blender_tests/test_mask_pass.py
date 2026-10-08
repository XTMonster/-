"""v1.6 E2（FR-A3）：逐元素遮罩通道 headless 探针。

断言（红线 R-8 的对拍）：

* 每镜 ``masks/<shot_id>/frame_%04d.png``，帧数与 ``cinema/schedule.py`` 的
  帧表完全一致（= 该镜 mp4 的帧数；文件名用绝对帧号，与 depth pass 同口径）；
* 逐像素颜色 = 元素登记表颜色：角色/道具投影中心 3×3 采样逐通道命中
  ``color_hex``（容差 0.01），环境件像素 = ``#808080``，背景 = ``#000000``；
* 标签不可见：全帧没有任何“偏白”像素（标签字面是白底亮色，遮罩里必须消失）；
* 渲染后场景状态**逐字节还原**（材质槽、hide_render、世界覆盖、渲染设置、
  视图变换、帧范围、filepath、film_transparent）；
* 渲染中途抛错时同样还原 + 原异常继续抛出（不吞错误）；
* 同一场景两次运行输出确定性：IDAT（像素）与除墙钟 ``RenderTime`` 外的全部
  PNG 块逐字节相同（Blender 5.2 无条件内嵌 ``RenderTime``，见 ``_stable_png_bytes``）。

运行：
  "D:\\Blender 5.2\\blender.exe" --background --factory-startup
    --python tools/blender_tests/test_mask_pass.py
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.cinema.anchor import DEFAULT_PROFILE  # noqa: E402
from block_director.cinema.schedule import shot_ranges  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.elements import (  # noqa: E402
    ENVIRONMENT_COLOR,
    build_registry,
)
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    ensure_collections,
)
from block_director.layer3_engine.scene_executor import create_prop  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer8_delivery import mask_pass as mp  # noqa: E402
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.blender_compat import engine_identifier  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}

RES_X, RES_Y = 640, 360
#: 逐通道采样容差（8 位 PNG 量化误差 0.5/255，取 5 倍余量；自发光 + Raw
#: 视图变换 + 抖动关闭时内部像素应逐通道精确命中）。
TOL = 0.01
#: 角色身体中心的世界 Z（= 髋高 + 躯干半高，与角色工厂同一份 profile）。
BODY_CENTER_Z = DEFAULT_PROFILE.torso_center_z
#: “标签不可见”的判据：三个通道都亮过 0.90 的像素只能是白色标签字面
#: （遮罩色表里角色三原色、环境灰 0.502、背景黑都到不了这个亮度）。
WHITE_MIN_CHANNEL = 0.90

CHARACTER_COLORS = {"char_001": "#FF0000", "char_002": "#00FF00"}
PROP_ID = "prop_001"
PROP_COLOR_HEX = "#0000FF"
PROP_POSITION = (0.9, 0.35, 0.4)
PROP_SIZE = (0.7, 0.7, 0.7)
CHAR2_STATION = (3.5, 0.0, 0.0)
#: MCU 画幅只到胸以上：躯干中心（髋上）会落在画外，采样点取上胸
#: （髋高 + 0.85 × 躯干高，同一份 profile 推导）。
UPPER_TORSO_Z = DEFAULT_PROFILE.hip_z + 0.85 * DEFAULT_PROFILE.torso_h
#: 场景里角色的**材质色**与登记表色刻意不同（深灰）：只有遮罩通道真的把
#: 登记表色挂上对象槽，采样才会命中登记表色——挂错槽/没挂会拿到深灰。
SCENE_MATERIAL_COLOR = "#202020"

_GEOMETRY_TYPES = {
    "MESH", "CURVE", "SURFACE", "FONT", "META", "LATTICE",
    "POINTCLOUD", "VOLUME", "GREASEPENCIL",
}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False,
                         "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "INT. 测试棚 - 日",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立空间",
             "shot_type": "LS", "duration_frames": 6,
             "characters": ["char_001"], "actions": []},
            {"shot_id": "shot_002", "order": 2, "intent": "特写反应",
             "shot_type": "MCU", "duration_frames": 6,
             "characters": ["char_002"], "actions": []},
        ],
    })


def _build():
    config = AppConfig()
    config.character.label_render = True
    set_config(config)
    plan = _plan()
    spec = SceneSpec.from_plan(plan)
    spec.cast[0].name = "Alice"
    spec.cast[1].name = "Bob"
    spec.cast[0].color = SCENE_MATERIAL_COLOR
    spec.cast[1].color = SCENE_MATERIAL_COLOR
    spec.cast[0].initial_location = (0.0, 0.0, 0.0)
    spec.cast[0].initial_facing = (0.0, 1.0, 0.0)
    spec.cast[1].initial_location = CHAR2_STATION
    spec.cast[1].initial_facing = (0.0, 1.0, 0.0)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    ensure_collections(scene)
    build_scene(plan, spec, clear_scene=True)
    scene.render.engine = engine_identifier("eevee")
    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    scene.render.resolution_percentage = 100
    prop = create_prop(PROP_ID, position=PROP_POSITION, size=PROP_SIZE,
                       color=(0.2, 0.2, 0.2))
    #: ``create_prop`` 目前忽略 ``position``（原语落在 3D 光标上，v1.6 之外
    #: 的已知缺陷，本探针不越界去修）：显式落位，让采样点确定可投影。
    prop.location = tuple(PROP_POSITION)
    #: 登记表色在 build 之后才切到三原色：场景材质保持深灰，登记表/遮罩是
    #: 三原色——只有遮罩真的接管了对象槽，对拍才会成立（颜色即身份）。
    spec.cast[0].color = CHARACTER_COLORS["char_001"]
    spec.cast[1].color = CHARACTER_COLORS["char_002"]
    registry = build_registry(
        plan, cast=[member.to_dict() for member in spec.cast],
        props=[{"id": PROP_ID, "label": "箱子", "color": PROP_COLOR_HEX}])
    return scene, registry, plan


def _is_png(path: Path) -> bool:
    return path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def _hex_rgb(color_hex: str):
    text = str(color_hex).lstrip("#")
    return tuple(int(text[index:index + 2], 16) / 255.0
                 for index in (0, 2, 4))


def _load_pixels(path: Path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        pixels = [float(value) for value in image.pixels]
        width, height = image.size
        return pixels, int(width), int(height)
    finally:
        bpy.data.images.remove(image)


def _histogram(path: Path):
    pixels, _width, _height = _load_pixels(path)
    counts: dict = {}
    white = 0
    for index in range(0, len(pixels), 4):
        red, green, blue = pixels[index], pixels[index + 1], pixels[index + 2]
        key = (round(red, 4), round(green, 4), round(blue, 4))
        counts[key] = counts.get(key, 0) + 1
        if min(red, green, blue) > WHITE_MIN_CHANNEL:
            white += 1
    return counts, white


def _count(histogram: dict, rgb) -> int:
    key = tuple(round(float(channel), 4) for channel in rgb)
    return int(histogram.get(key, 0))


def _character_root(element_id: str):
    for obj in bpy.data.objects:
        if str(obj.get("bd_element_type", "")) != "character_root":
            continue
        if str(obj.get("bd_sdl_id", "")) == element_id:
            return obj
    return None


def _sample_region(scene, camera, frame: int, path: Path, point, expected):
    """把世界点投到画面，取 3×3 邻域像素，逐通道对拍期望色（容差 TOL）。"""
    scene.frame_set(int(frame))
    bpy.context.view_layer.update()
    pixels, width, height = _load_pixels(path)
    projected = world_to_camera_view(scene, camera, Vector(point))
    if projected.z <= 0.0:
        return {"ok": False, "point": list(point),
                "error": f"点落在相机背后（z={projected.z:.4f}）"}
    center_x = int(round(projected.x * width - 0.5))
    center_y = int(round(projected.y * height - 0.5))
    sampled = []
    for offset_y in (-1, 0, 1):
        for offset_x in (-1, 0, 1):
            x = min(max(center_x + offset_x, 0), width - 1)
            y = min(max(center_y + offset_y, 0), height - 1)
            base = (y * width + x) * 4
            sampled.append((pixels[base], pixels[base + 1], pixels[base + 2]))
    ok = all(all(abs(a - b) <= TOL for a, b in zip(color, expected))
             for color in sampled)
    return {"ok": ok,
            "point": [round(float(v), 4) for v in point],
            "ndc": [round(float(projected.x), 4),
                    round(float(projected.y), 4),
                    round(float(projected.z), 4)],
            "center_px": [center_x, center_y],
            "expected": [round(float(v), 4) for v in expected],
            "sampled": [[round(float(v), 4) for v in color]
                        for color in sampled]}


def _state_snapshot(scene) -> dict:
    view_layer = bpy.context.view_layer
    settings = scene.render.image_settings
    labels = bpy.data.collections.get("BlockDirector/Labels")

    def material_names(obj):
        return [slot.material.name if slot.material else None
                for slot in obj.material_slots]

    return {
        "materials": {obj.name: material_names(obj)
                      for obj in bpy.data.objects
                      if obj.type in _GEOMETRY_TYPES},
        "hide_render": {obj.name: bool(obj.hide_render)
                        for obj in bpy.data.objects},
        "labels_hide_render": labels.hide_render if labels is not None else None,
        "material_override": (view_layer.material_override.name
                              if view_layer.material_override is not None
                              else None),
        "world_override": (view_layer.world_override.name
                           if getattr(view_layer, "world_override", None)
                           is not None else None),
        "filepath": scene.render.filepath,
        "frame_start": int(scene.frame_start),
        "frame_end": int(scene.frame_end),
        "film_transparent": bool(scene.render.film_transparent),
        "dither_intensity": float(scene.render.dither_intensity),
        "use_overwrite": bool(scene.render.use_overwrite),
        "use_placeholder": bool(scene.render.use_placeholder),
        "media_type": getattr(settings, "media_type", None),
        "metadata_input": getattr(scene.render, "metadata_input", None),
        "file_format": settings.file_format,
        "color_mode": settings.color_mode,
        "color_depth": settings.color_depth,
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "engine": scene.render.engine,
        "resolution": [int(scene.render.resolution_x),
                       int(scene.render.resolution_y)],
        "camera": scene.camera.name if scene.camera is not None else None,
        "world": scene.world.name if scene.world is not None else None,
        "fps": int(scene.render.fps),
    }


def _serialize(state: dict) -> str:
    return json.dumps(state, sort_keys=True, ensure_ascii=False,
                      allow_nan=False)


def _stable_png_bytes(path: Path) -> bytes:
    """PNG 的确定性载荷：逐块拼接，只剔除墙钟时间元数据。

    Blender 5.2 实测：IDAT（像素）与除 ``RenderTime`` 外的全部块跨运行逐字节
    相同；``RenderTime`` 是 Blender 无条件内嵌的墙钟时间（``metadata_input``
    只有 ``SCENE``/``STRIPS``，关不掉）。``Date`` 一并剔除以兼容 4.x 行为，
    其余任何块的差异都会让确定性检查失败。
    """
    volatile_keys = {b"RenderTime", b"Date"}
    data = path.read_bytes()
    stable = bytearray(data[:8])
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_data = data[offset + 8:offset + 8 + length]
        if chunk_type == b"tEXt":
            keyword = chunk_data.split(b"\x00", 1)[0]
            if keyword in volatile_keys:
                offset += 12 + length
                continue
        stable += data[offset:offset + 12 + length]
        offset += 12 + length
    return bytes(stable)


def t_mask_frames_match_schedule():
    scene, registry, plan = _build()
    out_dir = Path(tempfile.mkdtemp(prefix="bd_e2_frames_"))
    ranges = shot_ranges(plan)
    results = mp.render_mask_pass(scene, registry, ranges, str(out_dir))

    per_shot = {}
    ok = (len(results) == len(ranges)
          and [item["shot_id"] for item in results] == list(ranges.keys()))
    for shot_id, (start, end) in ranges.items():
        directory = out_dir / mp.MASK_ROOT_DIR / shot_id
        files = sorted(directory.glob(f"{mp.MASK_FRAME_PREFIX}*.png"))
        expected_names = [f"{mp.MASK_FRAME_PREFIX}{frame:04d}.png"
                          for frame in range(start, end + 1)]
        names_ok = ([path.name for path in files] == expected_names
                    and all(_is_png(path) for path in files))
        per_shot[shot_id] = {
            "range": [start, end],
            "expected_frames": end - start + 1,
            "actual_frames": len(files),
            "names_ok": names_ok,
            "files": [path.name for path in files],
        }
        ok = ok and names_ok
    return {"ok": ok, "results": results, "per_shot": per_shot}


def t_mask_pixels_match_registry_colours():
    scene, registry, plan = _build()
    #: 故意给一个“会改色”的前置状态：pass 必须强制 film_transparent=False、
    #: Raw 视图变换（Blender 5.2 的 Standard 落盘仍做 sRGB 编码）、抖动关闭，
    #: 才能逐像素命中登记表颜色。
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "AgX"
    scene.render.dither_intensity = 1.0
    out_dir = Path(tempfile.mkdtemp(prefix="bd_e2_px_"))
    mp.render_mask_pass(scene, registry, shot_ranges(plan), str(out_dir))

    red = _hex_rgb(CHARACTER_COLORS["char_001"])
    green = _hex_rgb(CHARACTER_COLORS["char_002"])
    blue = _hex_rgb(PROP_COLOR_HEX)
    grey = _hex_rgb(ENVIRONMENT_COLOR)
    black = (0.0, 0.0, 0.0)

    frame_one = out_dir / mp.MASK_ROOT_DIR / "shot_001" / "frame_0001.png"
    frame_two = out_dir / mp.MASK_ROOT_DIR / "shot_002" / "frame_0007.png"
    histogram_one, white_one = _histogram(frame_one)
    histogram_two, white_two = _histogram(frame_two)

    char_one = _character_root("char_001")
    char_two = _character_root("char_002")
    camera_one = bpy.data.objects["BD_Cam_shot_001"]
    camera_two = bpy.data.objects["BD_Cam_shot_002"]

    sample_char_one = _sample_region(
        scene, camera_one, 1, frame_one,
        char_one.matrix_world.translation + Vector((0, 0, BODY_CENTER_Z)), red)
    sample_char_two = _sample_region(
        scene, camera_two, 7, frame_two,
        char_two.matrix_world.translation + Vector((0, 0, UPPER_TORSO_Z)),
        green)
    sample_prop = _sample_region(scene, camera_one, 1, frame_one,
                                 Vector(PROP_POSITION), blue)

    presence_one = {"char_001_red": _count(histogram_one, red),
                    "prop_blue": _count(histogram_one, blue),
                    "environment_grey": _count(histogram_one, grey),
                    "background_black": _count(histogram_one, black),
                    "white_label_pixels": white_one}
    presence_two = {"char_002_green": _count(histogram_two, green),
                    "white_label_pixels": white_two}

    ok = (presence_one["char_001_red"] > 20
          and presence_one["prop_blue"] > 20
          and presence_one["environment_grey"] > 50
          and presence_one["background_black"] > 10
          and presence_one["white_label_pixels"] == 0
          and presence_two["char_002_green"] > 20
          and presence_two["white_label_pixels"] == 0
          and sample_char_one["ok"] and sample_char_two["ok"]
          and sample_prop["ok"])
    return {"ok": ok, "tolerance": TOL,
            "shot_001_presence": presence_one,
            "shot_002_presence": presence_two,
            "sample_char_001": sample_char_one,
            "sample_char_002": sample_char_two,
            "sample_prop": sample_prop}


def t_mask_scene_state_restored_byte_identical():
    scene, registry, plan = _build()
    #: 与 pass 内部取值**相反**的前置状态，还原纪律必须把它们原样还回来。
    scene.render.film_transparent = True
    scene.render.dither_intensity = 1.0
    scene.render.use_placeholder = True
    scene.frame_start, scene.frame_end = 1, 1
    scene.render.filepath = "//before_mask"
    before = _state_snapshot(scene)

    out_dir = Path(tempfile.mkdtemp(prefix="bd_e2_restore_"))
    mp.render_mask_pass(scene, registry, shot_ranges(plan), str(out_dir))
    after = _state_snapshot(scene)

    identical = _serialize(before) == _serialize(after)
    return {"ok": identical, "identical": identical,
            "before": before, "after": after}


def t_mask_restores_on_failure_and_reraises():
    scene, registry, plan = _build()
    scene.render.film_transparent = True
    before = _state_snapshot(scene)
    out_dir = Path(tempfile.mkdtemp(prefix="bd_e2_fail_"))

    original = mp._render_animation

    def explode(_scene):
        raise RuntimeError("injected render failure")

    mp._render_animation = explode
    try:
        try:
            mp.render_mask_pass(scene, registry, shot_ranges(plan),
                                str(out_dir))
            raised, message = False, ""
        except RuntimeError as exc:
            raised, message = True, str(exc)
    finally:
        mp._render_animation = original

    after = _state_snapshot(scene)
    restored = _serialize(before) == _serialize(after)
    mask_root = out_dir / mp.MASK_ROOT_DIR
    leftover = (list(mask_root.rglob(f"{mp.MASK_FRAME_PREFIX}*.png"))
                if mask_root.exists() else [])
    #: 失败之后场景必须还能再跑一次完整 pass（恢复是真恢复，不是“表面还原”）。
    results = mp.render_mask_pass(scene, registry, shot_ranges(plan),
                                  str(out_dir))
    usable = (len(results) == 2
              and all(item["frames"] == item["expected"]
                      for item in results))
    return {"ok": (raised and "injected render failure" in message
                   and restored and not leftover and usable),
            "raised": raised, "message": message,
            "state_restored": restored,
            "leftover_frames": [str(path) for path in leftover],
            "usable_after_failure": usable}


def t_mask_output_is_deterministic():
    scene, registry, plan = _build()
    out_one = Path(tempfile.mkdtemp(prefix="bd_e2_det1_"))
    out_two = Path(tempfile.mkdtemp(prefix="bd_e2_det2_"))
    first = mp.render_mask_pass(scene, registry, shot_ranges(plan),
                                str(out_one))
    second = mp.render_mask_pass(scene, registry, shot_ranges(plan),
                                 str(out_two))

    rel_one = sorted(Path(path).relative_to(out_one).as_posix()
                     for item in first for path in item["files"])
    rel_two = sorted(Path(path).relative_to(out_two).as_posix()
                     for item in second for path in item["files"])
    same_paths = rel_one == rel_two
    same_bytes = all(_stable_png_bytes(out_one / rel)
                     == _stable_png_bytes(out_two / rel)
                     for rel in rel_one)
    return {"ok": same_paths and same_bytes,
            "paths_equal": same_paths,
            "bytes_equal_ignoring_wall_clock_metadata": same_bytes,
            "frames_compared": len(rel_one)}


def main() -> int:
    capture_main_thread()
    check("mask_frames_match_schedule", t_mask_frames_match_schedule)
    check("mask_pixels_match_registry_colours",
          t_mask_pixels_match_registry_colours)
    check("mask_scene_state_restored_byte_identical",
          t_mask_scene_state_restored_byte_identical)
    check("mask_restores_on_failure_and_reraises",
          t_mask_restores_on_failure_and_reraises)
    check("mask_output_is_deterministic", t_mask_output_is_deterministic)
    reset_config()

    passed = [name for name, value in RESULTS.items() if value.get("ok")]
    failed = [name for name, value in RESULTS.items() if not value.get("ok")]
    # ``allow_nan=False``：任何 NaN/Inf 都会让这行抛错而不是写出非法 JSON。
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False, allow_nan=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
