"""卡 G1（D-18）headless 探针：光位变体的**真实灯位** + 白模渲染预设的阴影/AO。

要证明的三件事都只能在 Blender 里看：

1. ``key_direction`` 变体的主光真的摆到规范方位角（front=+Y / side=+X /
   back=-Y，由 ``cinema/lighting.py::KEY_DIRECTION_AZIMUTH_DEG`` 定，容差
   10°）——而不是只在纯层换名字；引擎预设每张表**第一盏灯是主光**。
2. Workbench 渲染预设（``apply_delivery_settings``）真的开了 shadow + cavity，
   且像素证据：接触环比远处地面更暗，且比关掉这两项时再暗一截。
3. EEVEE 渲染预设钉住了 5.2 的 AO/接触阴影等价物（``use_fast_gi`` /
   ``use_shadows``；5.2 RNA 里已没有 ``use_gtao`` / 每灯 ``use_contact_shadow``），
   且像素证据：接触环明显暗于远处地面。

已知边界（记录、不误报）：Workbench 的 ``STUDIO`` 光型**不认场景灯**（实测
``use_scene_lights_render=True`` 后与无灯逐字节相同），所以 key 方向只在
FLAT / EEVEE 下改变画面；STUDIO 下本探针只证 shadow/cavity 生效。

运行：blender --background --factory-startup --python tools/blender_tests/test_lighting_presets.py
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.cinema.lighting import (  # noqa: E402
    KEY_DIRECTION_AZIMUTH_DEG,
    LIGHT_DIRECTION_VARIANTS,
)
from block_director.contracts.config import DeliveryConfig  # noqa: E402
from block_director.contracts.enums import RenderBackend  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    ensure_collections,
)
from block_director.layer3_engine.scene_executor import (  # noqa: E402
    LIGHTING_PRESETS,
    create_lights,
)
from block_director.layer8_delivery.renderer import (  # noqa: E402
    apply_delivery_settings,
)
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}

WIDTH = 512
HEIGHT = 512
AZIMUTH_TOLERANCE_DEG = 10.0


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=5)}


def _render(engine: str) -> list:
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    out = ROOT / "work" / "_g1_lighting_probe.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(out))
    try:
        return list(image.pixels)
    finally:
        bpy.data.images.remove(image)


def _probe_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100

    bpy.ops.mesh.primitive_plane_add(size=24.0)
    ground = bpy.context.object
    mat = bpy.data.materials.new("BD_G1_Ground")
    mat.diffuse_color = (0.78, 0.78, 0.76, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.78, 0.78, 0.76, 1.0)
    ground.data.materials.append(mat)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.5))
    cube = bpy.context.object
    cmat = bpy.data.materials.new("BD_G1_Cube")
    cmat.diffuse_color = (0.62, 0.60, 0.58, 1.0)
    cmat.use_nodes = True
    cbsdf = cmat.node_tree.nodes.get("Principled BSDF")
    if cbsdf is not None:
        cbsdf.inputs["Base Color"].default_value = (0.62, 0.60, 0.58, 1.0)
    cube.data.materials.append(cmat)

    world = bpy.data.worlds.new("BD_G1_World") if scene.world is None else scene.world
    scene.world = world
    world.color = (0.10, 0.11, 0.14)

    cam_data = bpy.data.cameras.new("BD_G1_Cam")
    cam_data.lens = 24.0
    cam = bpy.data.objects.new("BD_G1_Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.location = (0.0, 8.0, 3.0)
    target = bpy.data.objects.new("BD_G1_Target", None)
    scene.collection.objects.link(target)
    target.location = (0.0, 0.0, 0.6)
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    bpy.context.view_layer.update()
    return scene


def _screen(scene, point):
    from bpy_extras.object_utils import world_to_camera_view

    bpy.context.view_layer.update()
    return world_to_camera_view(scene, scene.camera, Vector(point))


def _luminance(pixels, sx, sy):
    x = int(round(sx * (WIDTH - 1)))
    y = int(round(sy * (HEIGHT - 1)))
    index = (y * WIDTH + x) * 4
    r, g, b = pixels[index], pixels[index + 1], pixels[index + 2]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contact_ratio(pixels, scene):
    """接触环（方块底面外沿一圈）与远处地面的平均亮度比。"""
    bpy.context.view_layer.update()
    near = []
    #: 相机在 +Y 朝 -Y 看：只取方块朝相机一侧与左右两侧的地面（背面会被方块挡住）。
    for x, y in (
        (-0.66, -0.30), (-0.66, 0.0), (-0.66, 0.30),
        (0.66, -0.30), (0.66, 0.0), (0.66, 0.30),
        (-0.30, -0.66), (0.0, -0.66), (0.30, -0.66),
    ):
        coord = _screen(scene, (x, y, 0.0))
        if 0.02 <= coord.x <= 0.98 and 0.02 <= coord.y <= 0.98:
            near.append(_luminance(pixels, coord.x, coord.y))
    far = []
    for x in (-1.8, -1.2, 1.2, 1.8):
        for y in (-1.8, -1.2, 1.2, 1.8):
            coord = _screen(scene, (x, y, 0.0))
            if 0.02 <= coord.x <= 0.98 and 0.02 <= coord.y <= 0.98:
                far.append(_luminance(pixels, coord.x, coord.y))
    if not near or not far:
        raise AssertionError("采样点全部落在画面外：相机或采样区有问题")
    return sum(near) / len(near), sum(far) / len(far)


def _add_side_sun():
    sun = bpy.data.lights.new("BD_G1_Sun", type="SUN")
    sun.energy = 5.0
    obj = bpy.data.objects.new("BD_G1_Sun", sun)
    bpy.context.scene.collection.objects.link(obj)
    #: 俯仰 0.7、方位 pi/2：光源在 +X（垂直于相机轴），照射方向朝 -X。
    obj.rotation_euler = (0.7, 0.0, math.pi / 2.0)
    return obj


def _key_source_azimuth(light_obj) -> float:
    """主光**光源方位角**（度，0=+X、90=+Y；结果会归一化到 [0,360)）。

    SUN/AREA：发射方向 = 物体旋转矩阵 @ (0,0,-1)，光源 = 反方向；发射近竖直
    （顶光）时改由 XY 位置定方位。POINT：直接由位置定。
    """
    bpy.context.view_layer.update()
    if light_obj.data.type in ("SUN", "AREA"):
        emission = light_obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
        if abs(emission.z) > 0.99:
            source = Vector((light_obj.location.x, light_obj.location.y, 0.0))
        else:
            source = -emission
        return math.degrees(math.atan2(source.y, source.x))
    return math.degrees(math.atan2(light_obj.location.y,
                                   light_obj.location.x))


def _azimuth_delta(measured: float, target: float) -> float:
    return abs((measured - target + 180.0) % 360.0 - 180.0)


def _fresh_lights_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    return scene


def t_direction_variants_place_the_key_at_canonical_azimuth():
    """引擎侧 15 个变体预设的主光方位角 = 纯层声明的规范值（容差 10°）。"""
    report = {}
    mismatches = []
    for (base, direction), variant in sorted(LIGHT_DIRECTION_VARIANTS.items()):
        if variant not in LIGHTING_PRESETS:
            mismatches.append(f"{variant} 不在引擎预设表里")
            continue
        _fresh_lights_scene()
        lights = create_lights(preset=variant)
        if not lights:
            mismatches.append(f"{variant} 没有建出灯")
            continue
        measured = _key_source_azimuth(lights[0]) % 360.0
        target = float(KEY_DIRECTION_AZIMUTH_DEG[direction])
        delta = _azimuth_delta(measured, target)
        report[variant] = {
            "base": base, "direction": direction,
            "key_type": lights[0].data.type,
            "azimuth": round(measured, 3),
            "target": target, "delta": round(delta, 3),
        }
        if delta > AZIMUTH_TOLERANCE_DEG:
            mismatches.append(
                f"{variant} 主光方位角 {measured:.1f}°，目标 {target:.1f}°")
    return {"ok": not mismatches,
            "variants_checked": len(report),
            "mismatches": mismatches, "report": report}


def t_workbench_preset_enables_shadow_and_cavity():
    """Workbench：预设开 shadow+cavity，且接触环比"全关"时明显更暗。"""
    scene = _probe_scene()
    shading = scene.display.shading
    shading.color_type = "MATERIAL"
    shading.light = "STUDIO"
    shading.background_type = "VIEWPORT"
    shading.background_color = (0.10, 0.11, 0.14)
    shading.show_shadows = False
    shading.show_cavity = False
    baseline = _render("BLENDER_WORKBENCH")
    near0, far0 = _contact_ratio(baseline, scene)

    config = DeliveryConfig()          # 默认：WORKBENCH + CLAY
    warnings = apply_delivery_settings(scene, config)
    assert shading.show_shadows is True
    assert shading.show_cavity is True
    assert shading.cavity_type == "SCREEN"
    assert shading.light == "STUDIO"
    enabled = _render("BLENDER_WORKBENCH")
    near1, far1 = _contact_ratio(enabled, scene)
    ratio0 = near0 / far0
    ratio1 = near1 / far1
    return {"ok": (len(warnings) == 0 and ratio1 < 0.92
                   and ratio1 < ratio0 - 0.05),
            "show_shadows": shading.show_shadows,
            "show_cavity": shading.show_cavity,
            "cavity_type": shading.cavity_type,
            "light": shading.light,
            "baseline_ratio": round(ratio0, 4),
            "enabled_ratio": round(ratio1, 4),
            "near": (round(near0, 4), round(near1, 4)),
            "far": (round(far0, 4), round(far1, 4)),
            "warnings": warnings}


def t_eevee_preset_enables_ao_and_contact_shadows():
    """EEVEE：预设钉住 5.2 的 AO/接触阴影等价物，且有像素证据。"""
    scene = _probe_scene()
    _add_side_sun()
    config = DeliveryConfig()
    config.render_backend = RenderBackend.EEVEE
    warnings = apply_delivery_settings(scene, config)
    eevee = scene.eevee
    names_present = (hasattr(eevee, "use_fast_gi")
                     and hasattr(eevee, "fast_gi_method")
                     and hasattr(eevee, "use_shadows"))
    assert names_present, "EEVEE 5.2 的 AO 属性名没找到（不是猜的，是实测）"
    assert eevee.use_fast_gi is True
    assert eevee.use_shadows is True
    pixels = _render("BLENDER_EEVEE")
    near, far = _contact_ratio(pixels, scene)
    ratio = near / far
    sun = bpy.data.lights["BD_G1_Sun"]
    return {"ok": len(warnings) == 0 and ratio < 0.75,
            "use_fast_gi": eevee.use_fast_gi,
            "fast_gi_method": eevee.fast_gi_method,
            "use_shadows": eevee.use_shadows,
            "use_raytracing": eevee.use_raytracing,
            "legacy_use_gtao_present": hasattr(eevee, "use_gtao"),
            "sun_contact_shadow_props_present": [
                name for name in ("use_contact_shadow",
                                  "contact_shadow_distance")
                if hasattr(sun, name)],
            "contact_ratio": round(ratio, 4),
            "near": round(near, 4), "far": round(far, 4),
            "warnings": warnings}


def main() -> int:
    capture_main_thread()
    check("direction_variants_place_the_key_at_canonical_azimuth",
          t_direction_variants_place_the_key_at_canonical_azimuth)
    check("workbench_preset_enables_shadow_and_cavity",
          t_workbench_preset_enables_shadow_and_cavity)
    check("eevee_preset_enables_ao_and_contact_shadows",
          t_eevee_preset_enables_ao_and_contact_shadows)
    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
