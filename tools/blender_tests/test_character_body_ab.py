"""v1.4 §7 的 **D1b 躯干形状 A/B**：圆柱（**已退役的旧形状**）vs 圆角方体（**现在生产的形状**）。

§7 的裁决方式是"**P10 内以 A/B 截图裁决**"。**裁决已做**：人工裁决通道（GLM-5.3）
判 **② 圆角方体**，`character_factory.py` 的生产路径**已改**（提交见
`docs/knowledge/PLAN_HYPERGRAPH_v4_PROGRESS.md` 的 D1b 那条），两张图在
`docs/evidence/d1b_body_shape/`（`A_cylinder.png` / `B_rounded_box.png`）。

⇒ 这一支的**语义随之改成"回归对拍"**（否则它会退化成自己跟自己比）：

* **A（旧，显式建）**：`_cylinder_body()`——把躯干**显式**换成
  `primitive_cylinder_add(radius=BODY_RADIUS, depth=BODY_HEIGHT)`；
* **B（新，显式建）**：`_rounded_box_body()`——等外接盒的圆角方体（cube ＋ Bevel），
  与生产路径 `character_factory._add_rounded_box_body()` **逐字同序**。
* **另加一条**：`d1b_shipped_torso_is_the_rounded_box` —— 直接量**生产默认**建出来的躯干，
  钉住"真的换了形状"，免得它被谁悄悄改回圆柱。

它回答的不是"哪个好看"，而是**换形状会不会牵动别的东西**——文档写
选项 ② "需改 `character_factory.py` 的 `primitive_cylinder_add` 与相应 bbox/构图常量"。
所以这一支量三件事：

1. **外接盒**：A 与 B 的躯干世界 AABB 是否**一致**（一致 ⇒ 构图/取景常量不必动）；
2. **锚点契约**：头心、标签锚、总高在两种形状下是否**逐位相同**（形状不该动骨架）；
3. **剪影确实不同**：同一机位各渲一张，差分像素数落在"既非 0 也非满屏"的区间
   （否则"换了形状"这件事本身没发生）。

`--save-dir <dir>` 会把两张图写出去（供人看）；链上按缺省跑，只出数字。

运行：blender --background --factory-startup --python tools/blender_tests/test_character_body_ab.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.cinema.anchor import DEFAULT_PROFILE as PROFILE  # noqa: E402
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
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"
WIDTH, HEIGHT = 640, 360
BG = (0.05, 0.05, 0.06)
TOL = 0.02
#: 圆角半径：取躯干半径的 1/4，肉眼能看出"块面"，又不至于把方体磨成圆柱。
BEVEL_RATIO = 0.25


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene(*, shaded: bool = True):
    """空场景 ＋ Workbench。

    **这一支用 `STUDIO` 受光，不用其他探针的 `FLAT`**（2026-10-03 实测）：D1b 要裁的
    是"圆柱 vs 圆角方体"的**块面感**，而 FLAT 让所有面拿到同一个颜色——方体与圆柱
    除了轮廓四角几乎一模一样（差分只有 0.55% 的画面），人根本看不出该看的东西。
    受光之后圆柱是连续渐变、方体是**分明的面与棱**，那才是这条决策要看的图。
    """
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
        display.shading.light = "STUDIO" if shaded else "FLAT"
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


#: 两种机位：分辨率/取景都由**项目自己的求解器**给（见 `build_and_render`）。
#: MS/front 是"产品会给这一镜的标准中景"，CU/left 是**转过来的近景**——躯干的块面
#: 在侧向近景上才看得出来，正面中景两张几乎一样（实测差分只有 0.55% 的画面）。
SHOTS = (("MS", "front"), ("CU", "left"))


def render_to(name: str, save_dir: str = "") -> str:
    scene = bpy.context.scene
    path = str(OUTDIR / f"body_ab_{name}.png")
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if save_dir:
        target = Path(save_dir)
        target.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copyfile(path, target / f"{name}.png")
    return path


def _pixels(path: str) -> list:
    image = bpy.data.images.load(path)
    try:
        return list(image.pixels)
    finally:
        bpy.data.images.remove(image)


def _body_bounds(name: str) -> dict:
    body = bpy.data.objects.get(f"BD_Char_{name}_Body")
    if body is None:
        raise AssertionError(f"找不到躯体对象 BD_Char_{name}_Body")
    corners = [body.matrix_world @ __import__("mathutils").Vector(corner)
               for corner in body.bound_box]
    xs = [item.x for item in corners]
    ys = [item.y for item in corners]
    zs = [item.z for item in corners]
    return {"size": [round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4),
                     round(max(zs) - min(zs), 4)],
            "vertices": len(body.data.vertices),
            "materials": [slot.material.name for slot in body.material_slots
                          if slot.material]}


def _anchors(name: str) -> dict:
    head = bpy.data.objects.get(f"BD_Char_{name}_Head")
    anchor = bpy.data.objects.get(f"BD_Char_{name}_LabelAnchor")
    if head is None or anchor is None:
        raise AssertionError("层级里缺头球或标签锚")
    return {"head_center_z": round(head.matrix_world.translation.z, 6),
            "label_anchor_z": round(anchor.matrix_world.translation.z, 6)}


def _rounded_box_body(name: str) -> None:
    """把 A 的躯干换成**等外接盒**的圆角方体（B），层级与锚点一律不动。"""
    body = bpy.data.objects[f"BD_Char_{name}_Body"]
    parent = body.parent
    local = tuple(body.location)
    materials = [slot.material for slot in body.material_slots if slot.material]
    #: 半径/高度取**工厂常量**（唯一真源），不去量刚建出来的对象——`dimensions`
    #: 在视图层更新之前可能是陈旧值，量它会得到两倍宽（实测踩过：AABB 变成 0.25）。
    radius = character_factory.BODY_RADIUS
    height = character_factory.BODY_HEIGHT
    bpy.data.objects.remove(body, do_unlink=True)

    bpy.ops.mesh.primitive_cube_add(size=1.0,
                                    location=(0.0, 0.0, 0.0))
    cube = bpy.context.active_object
    cube.name = f"BD_Char_{name}_Body"
    # `primitive_cube_add(size=1.0)` 的边长是 1.0，缩放到"直径 × 直径 × 高"。
    cube.scale = (radius * 2.0, radius * 2.0, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = cube.modifiers.new("BD_AB_Bevel", "BEVEL")
    bevel.width = radius * BEVEL_RATIO
    bevel.segments = 4
    bpy.context.view_layer.objects.active = cube
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    cube.location = local
    if parent is not None:
        cube.parent = parent
    for material in materials:
        cube.data.materials.append(material)


def _cylinder_body(name: str) -> None:
    """把躯干换成**旧形状**的圆柱（A）——显式建，不看工厂的默认值。

    为什么要显式：生产默认**已经改成圆角方体**了。若 A 还走工厂默认，A/B 就变成
    "圆角方体 vs 圆角方体"，`d1b_silhouette_differs` 会当场红（差分恒 0）——
    那不是"形状没差"，是**对拍对象写错了**。
    """
    body = bpy.data.objects[f"BD_Char_{name}_Body"]
    parent = body.parent
    local = tuple(body.location)
    materials = [slot.material for slot in body.material_slots if slot.material]
    radius = character_factory.BODY_RADIUS
    height = character_factory.BODY_HEIGHT
    bpy.data.objects.remove(body, do_unlink=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=height,
                                        location=(0.0, 0.0, 0.0))
    cylinder = bpy.context.active_object
    cylinder.name = f"BD_Char_{name}_Body"
    cylinder.location = local
    if parent is not None:
        cylinder.parent = parent
    for material in materials:
        cylinder.data.materials.append(material)


def build_and_render(name: str, *, rounded: bool, save_dir: str = ""):
    """建角色 → 用产品的取景求解器逐机位渲一张（A/B 必须是**同一个机位**）。"""
    fresh_scene()
    character = create_character(f"char_{name.lower()}", name, "#C8C8D0")
    if rounded:
        _rounded_box_body(name)
    else:
        #: A 是**旧形状**：显式建圆柱（生产默认现在是圆角方体，见模块 docstring）。
        _cylinder_body(name)
    frames = {}
    for shot_type, side in SHOTS:
        place_camera_for_shot(f"d1b_{name}_{shot_type}", (0.0, 0.0, 0.0),
                              shot_type=shot_type, side=side)
        label = f"{name}_{shot_type}_{side}"
        frames[f"{shot_type}/{side}"] = _pixels(render_to(label, save_dir))
    return character, frames


# --------------------------------------------------------------------------- 判据


def t_the_torso_footprint_does_not_change() -> dict:
    """**文档最担心的事**：选项 ② 会不会连带改 bbox/构图常量。

    实测：圆角方体按"同一半径、同一高度"建，两种形状的躯干世界 AABB **一致**
    （差 ≤ 1e-4）⇒ 取景/构图常量与 `BODY_CENTER_LOCAL` 都不必动。
    """
    build_and_render("A", rounded=False)
    bounds_a = _body_bounds("A")
    build_and_render("B", rounded=True)
    bounds_b = _body_bounds("B")

    delta = [abs(a - b) for a, b in zip(bounds_a["size"], bounds_b["size"])]
    # 圆角方体在四角被磨掉，AABB 仍应等于 (2r, 2r, h)——磨角不改变外接盒。
    expected = [round(character_factory.BODY_RADIUS * 2, 4),
                round(character_factory.BODY_RADIUS * 2, 4),
                round(character_factory.BODY_HEIGHT, 4)]
    ok = max(delta) <= 1e-3 and bounds_b["size"] == expected
    return {"ok": ok, "bounds_a": bounds_a, "bounds_b": bounds_b,
            "expected": expected, "max_delta": round(max(delta), 6),
            "vertices_a": bounds_a["vertices"], "vertices_b": bounds_b["vertices"]}


def _differing(pixels_a, pixels_b) -> int:
    count = 0
    for index in range(0, min(len(pixels_a), len(pixels_b)), 4):
        if max(abs(pixels_a[index] - pixels_b[index]),
               abs(pixels_a[index + 1] - pixels_b[index + 1]),
               abs(pixels_a[index + 2] - pixels_b[index + 2])) > TOL:
            count += 1
    return count


def t_the_anchor_contract_survives_the_swap() -> dict:
    """形状不该动骨架：头心与标签锚在两种形状下**逐位相同**。"""
    build_and_render("A", rounded=False)
    anchors_a = _anchors("A")
    build_and_render("B", rounded=True)
    anchors_b = _anchors("B")
    same = (anchors_a == anchors_b
            and anchors_a["head_center_z"] == round(PROFILE.head_center_z, 6)
            and anchors_a["label_anchor_z"] == round(PROFILE.label_anchor_z, 6))
    return {"ok": same, "anchors_a": anchors_a, "anchors_b": anchors_b,
            "profile_head_center": round(PROFILE.head_center_z, 6),
            "profile_label_anchor": round(PROFILE.label_anchor_z, 6)}


def t_the_silhouette_really_differs() -> dict:
    """换了形状就必须看得出来：**每个机位**的差分像素既 > 下界又远离满屏。

    下界取 0.2% 的画面（640×360 = 230400 px ⇒ ≥460 px）：圆角的四角磨掉的就是这么多；
    上界 30%：超出就说明两边根本不是同一个主体（机位/材质被谁动过）。
    """
    _, frames_a = build_and_render("A", rounded=False)
    _, frames_b = build_and_render("B", rounded=True)
    total = WIDTH * HEIGHT
    per_shot = {}
    for key in frames_a:
        differing = _differing(frames_a[key], frames_b[key])
        per_shot[key] = {"differing": differing,
                         "share": round(differing / total, 5),
                         "ok": total * 0.002 <= differing <= total * 0.30}
    ok = all(item["ok"] for item in per_shot.values())
    return {"ok": ok, "per_shot": per_shot, "total": total,
            "floor": int(total * 0.002), "ceiling": int(total * 0.30)}


def _cylinder_profile(body) -> dict:
    """独立量躯干网格：与 `test_cylinder_body.py::cylinder_profile` 同法。

    半径按 `hypot(x, y)` 逐顶点对 `BODY_RADIUS`、高度按 `|z|` 对
    `BODY_HEIGHT / 2`（±1e-6），再验证上下两环各 32 个顶点且**等角距**
    （相邻夹角 = τ/32）——顶点数撞对（64）但没有逐顶点形状校验的网格过不了这里。
    缺环用有限哨兵 999.0 上报（`math.inf` 在探针里被 `check_assertions.py` 禁止）。
    """
    radius = character_factory.BODY_RADIUS
    half_height = character_factory.BODY_HEIGHT / 2.0
    rings = {-1: [], 1: []}
    radial_error = 0.0
    height_error = 0.0
    for vertex in body.data.vertices:
        x, y, z = vertex.co
        radial_error = max(radial_error, abs(math.hypot(x, y) - radius))
        height_error = max(height_error, abs(abs(z) - half_height))
        rings[-1 if z < 0 else 1].append(math.atan2(y, x) % math.tau)
    angle_error = 0.0
    for angles in rings.values():
        angles.sort()
        if not angles:
            angle_error = 999.0
            continue
        wrapped = angles[1:] + [angles[0] + math.tau]
        angle_error = max(angle_error, max(
            abs((right - left) - math.tau / 32.0)
            for left, right in zip(angles, wrapped)))
    counts = [len(rings[-1]), len(rings[1])]
    return {
        "ok": (counts == [32, 32] and radial_error <= 1e-6
               and height_error <= 1e-6 and angle_error <= 1e-6),
        "ring_counts": counts, "radial_error": radial_error,
        "height_error": height_error, "angle_error": angle_error,
    }


def t_the_shipped_torso_is_the_v16_cylinder() -> dict:
    """**生产默认**必须真的换成了 v1.6 的 32 边圆柱（不是"加了个开关但还是圆角方体"）。

    判据（都不依赖硬编码顶点数）：生产建出来的躯干与**显式 32 边圆柱**的
    （顶点数、AABB）**逐位相同**，且与**显式圆角方体**的顶点数**不同**——后者正是
    v1.6 换形状这件事本身。外接盒三项必须仍等于 `(2r, 2r, h)`（⇒ bbox／构图常量不动）。
    """
    fresh_scene()
    create_character("char_ship", "Ship", "#C8C8D0")
    shipped = _body_bounds("Ship")
    fresh_scene()
    create_character("char_ref", "Ref", "#C8C8D0")
    _rounded_box_body("Ref")
    rounded = _body_bounds("Ref")
    fresh_scene()
    create_character("char_old", "Old", "#C8C8D0")
    _cylinder_body("Old")
    cylinder = _body_bounds("Old")
    expected = [round(character_factory.BODY_RADIUS * 2, 4),
                round(character_factory.BODY_RADIUS * 2, 4),
                round(character_factory.BODY_HEIGHT, 4)]
    ok = (shipped["vertices"] == cylinder["vertices"]
          and shipped["vertices"] != rounded["vertices"]
          and shipped["size"] == rounded["size"] == cylinder["size"] == expected)
    return {"ok": ok, "shipped": shipped, "rounded_ref": rounded,
            "cylinder_ref": cylinder, "expected": expected}


def t_the_shipped_torso_geometry_is_the_v16_cylinder() -> dict:
    """**生产默认**躯干的独立几何校验：真的两环 × 32 个顶点、半径与高度都等于工厂常量。

    只看**生产建出来的**网格（不走显式圆柱），量逐顶点半径 / 上下两环 / 高度——
    这样即使顶点数撞上 64、AABB 也一致，只要不是指定的圆柱就会红
    （`test_cylinder_body.py` 的"隐藏损伤"用例正是这个反例）。
    """
    fresh_scene()
    create_character("char_ship", "Ship", "#C8C8D0")
    body = bpy.data.objects.get("BD_Char_Ship_Body")
    if body is None:
        raise AssertionError("找不到躯体对象 BD_Char_Ship_Body")
    profile = _cylinder_profile(body)
    return {"ok": profile["ok"], "profile": profile,
            "bounds": _body_bounds("Ship")}


def main() -> int:
    capture_main_thread()
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    save_dir = ""
    if "--save-dir" in args:
        save_dir = args[args.index("--save-dir") + 1]

    check("d1b_torso_footprint_unchanged", t_the_torso_footprint_does_not_change)
    check("d1b_anchor_contract_unchanged", t_the_anchor_contract_survives_the_swap)
    check("d1b_silhouette_differs", t_the_silhouette_really_differs)
    check("d1b_shipped_torso_is_the_v16_cylinder",
          t_the_shipped_torso_is_the_v16_cylinder)
    check("d1b_shipped_torso_geometry_is_the_v16_cylinder",
          t_the_shipped_torso_geometry_is_the_v16_cylinder)

    if save_dir:
        for label in (f"{name}_{shot_type}_{side}"
                      for name in ("A", "B") for shot_type, side in SHOTS):
            source = OUTDIR / f"body_ab_{label}.png"
            if source.is_file():
                target = Path(save_dir)
                target.mkdir(parents=True, exist_ok=True)
                import shutil

                shutil.copyfile(source, target / f"{label}.png")
        # 再给 MS/front 那对起两个**直白**的名字：`A_cylinder.png` / `B_rounded_box.png`
        # 就是这条决策要看的两张图（人打开目录第一眼就找到它们），侧向近景哪张是补充。
        for alias, name in (("A_cylinder", "A"), ("B_rounded_box", "B")):
            source = OUTDIR / f"body_ab_{name}_MS_front.png"
            if source.is_file():
                import shutil

                shutil.copyfile(source, Path(save_dir) / f"{alias}.png")

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS,
         "note": "D1b 已裁决为 ② 圆角方体并合入生产（`character_factory` 已改）："
                 "本支现在是对拍——A 是退役的圆柱（显式建），B 是生产的圆角方体，"
                 "外加一条 `d1b_shipped_torso_is_the_rounded_box` 钉住生产默认"},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
