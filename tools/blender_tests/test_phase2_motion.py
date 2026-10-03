"""Phase 2 集成测试：动作烘焙、动画可见性、冲突拒绝（执行文档 v1.2 §9.6 / §9.7）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase2_motion.py
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
from mathutils import Vector  # noqa: E402

from block_director.layer3_engine.character_system import (  # noqa: E402
    MotionBlender,
    PIVOT_Z,
    create_character,
)
from block_director.layer3_engine.cinema_engine import create_camera  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 160
    scene.render.resolution_y = 90
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        display.shading.light = "FLAT"
        display.shading.color_type = "MATERIAL"
        display.shading.background_type = "VIEWPORT"
        display.shading.background_color = (0.05, 0.05, 0.06)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    scene.world.color = (0.05, 0.05, 0.06)
    ensure_collections(scene)
    return scene


def render_luma(name: str, frame: int) -> float:
    scene = bpy.context.scene
    os.makedirs(OUTDIR, exist_ok=True)
    path = str(OUTDIR / f"phase2_{name}.png")
    scene.frame_set(frame)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        return -1.0
    image = bpy.data.images.load(path)
    try:
        pixels = list(image.pixels)
    finally:
        bpy.data.images.remove(image)
    rgb = [v for i, v in enumerate(pixels) if i % 4 != 3]
    return round(sum(rgb) / max(len(rgb), 1), 5)


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _setup_character_scene():
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 96
    character = create_character("char_001", "小明", "#FF6B6B",
                                 location=(0.0, 0.0, 0.0))
    create_camera("shot_001", (0.0, -6.0, 1.2), look_at=(0.0, 0.0, 0.9), lens=50.0)
    return scene, character


# --------------------------------------------------------------------------- #
# 1. 烘焙出关键帧
# --------------------------------------------------------------------------- #
def t_bake_creates_keyframes():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0.0, 0.0, 0.0),
                target_position=(2.0, 0.0, 0.0), speed="walk")
    blender.add("nod", 1, 48, cycles=2)
    result = blender.bake()

    root_animated = character.root.animation_data is not None
    head_animated = character.head_pivot.animation_data is not None
    leg_animated = character.leg_pivots[0].animation_data is not None
    return {"ok": result.keyframes > 0 and root_animated and head_animated
            and leg_animated,
            "keyframes": result.keyframes, "frames": result.frames,
            "channels": result.channels,
            "root_animated": root_animated, "head_animated": head_animated,
            "leg_animated": leg_animated}


# --------------------------------------------------------------------------- #
# 2. 根节点真的随时间移动
# --------------------------------------------------------------------------- #
def t_root_moves_over_time():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0.0, 0.0, 0.0),
                target_position=(2.0, 0.0, 0.0))
    blender.bake()

    scene.frame_set(1)
    x_start = round(character.root.matrix_world.translation.x, 4)
    scene.frame_set(48)
    x_end = round(character.root.matrix_world.translation.x, 4)
    scene.frame_set(24)
    x_mid = round(character.root.matrix_world.translation.x, 4)
    return {"ok": abs(x_start) < 0.01 and x_end > 1.9 and 0.05 < x_mid < 1.95,
            "x_start": x_start, "x_mid": x_mid, "x_end": x_end}


# --------------------------------------------------------------------------- #
# 3. 渲染出来的画面随动画变化（这才是"能动"的证据）
# --------------------------------------------------------------------------- #
def t_render_frames_differ():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0.0, 0.0, 0.0),
                target_position=(2.0, 0.0, 0.0))
    blender.add("shake_head", 1, 48)
    blender.bake()

    luma_start = render_luma("frame_01", 1)
    luma_mid = render_luma("frame_24", 24)
    luma_end = render_luma("frame_48", 48)
    moved = abs(luma_end - luma_start) > 0.005
    distinct = len({luma_start, luma_mid, luma_end}) == 3
    return {"ok": moved and distinct,
            "luma": {"f01": luma_start, "f24": luma_mid, "f48": luma_end}}


# --------------------------------------------------------------------------- #
# 4. 语义冲突被拒绝（§9.7）
# --------------------------------------------------------------------------- #
def t_conflict_rejected():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("walk_to", 1, 48, from_=(0, 0, 0), target_position=(2, 0, 0))
    blender.add("fall_down", 20, 60)
    problems = blender.validate()
    raised = False
    try:
        blender.bake()
    except ValueError:
        raised = True
    return {"ok": bool(problems) and raised,
            "problems": problems, "bake_raised": raised}


# --------------------------------------------------------------------------- #
# 5. 先坐后站精确回到地面（接管冻结语义的端到端验证）
# --------------------------------------------------------------------------- #
def t_sit_then_stand_returns_to_ground():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("sit", 1, 24, drop=0.2)
    blender.add("stand", 25, 48, drop=0.2)
    blender.bake()

    def body_z(frame: int) -> float:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        return round(character.body_pivot.matrix_world.translation.z, 4)

    z_start = body_z(1)
    z_sit = body_z(24)
    z_end = body_z(48)
    return {"ok": abs(z_start - PIVOT_Z["body"]) < 0.02
            and abs(z_sit - (PIVOT_Z["body"] - 0.2)) < 0.02
            and abs(z_end - PIVOT_Z["body"]) < 0.02,
            "z": {"start": z_start, "sitting": z_sit, "end": z_end},
            "expected": {"start": PIVOT_Z["body"], "sitting": PIVOT_Z["body"] - 0.2,
                         "end": PIVOT_Z["body"]}}


# --------------------------------------------------------------------------- #
# 6. 头部动作只动头（不污染根节点）
# --------------------------------------------------------------------------- #
def t_head_motion_is_isolated():
    scene, character = _setup_character_scene()
    blender = MotionBlender(character)
    blender.add("nod", 1, 24, cycles=2)
    blender.bake()

    angles = []
    for frame in (1, 7, 13, 19, 24):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        angles.append(round(character.head_pivot.rotation_euler[0], 4))
    root_moved = character.root.animation_data is not None
    return {"ok": len(set(angles)) > 1 and not root_moved,
            "head_pitch": angles, "root_animated": root_moved}


def t_bake_keeps_the_authored_facing():
    """v1.3：动作烘焙不得抹掉角色的身体朝向。

    v1.2 的 ``clear_animation`` 把 root 的 ``rotation_euler`` 也清零了，
    而 ``apply_motions`` 又在清除**之后**才读基姿态——于是角色第一次烘焙动作
    时，"创建时设定的朝向"就被抹掉，两人相对而立会一起弹回面朝 +Y。
    """
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 48
    character = create_character("char_001", "小明", "#FF6B6B",
                                 location=(0.0, 0.0, 0.0),
                                 facing=(1.0, 0.0, 0.0))   # 面朝 +X
    create_camera("shot_001", (3.0, 0.0, 1.2), look_at=(0.0, 0.0, 0.9), lens=50.0)

    blender = MotionBlender(character)
    blender.add("nod", 1, 48, cycles=2)          # 只动头，不该动身体
    blender.bake()
    scene.frame_set(48)
    bpy.context.view_layer.update()

    from block_director.layer3_engine.character_system import get_facing
    facing = get_facing(character)
    return {"ok": facing[0] > 0.99 and abs(facing[1]) < 0.02,
            "facing": list(facing),
            "root_yaw": round(float(character.root.rotation_euler[2]), 4)}


# --------------------------------------------------------------------------- #
# RK-6（v1.4 §4.1）：悬空 / 穿地的**双向**判据
# --------------------------------------------------------------------------- #
GROUND_EPS = 0.02
#: RK-6 反向突变用的抬升量：明显高于 GROUND_EPS（0.02），又远小于角色身高。
LIFT = 0.05
#: 采样集：本镜首 / 中 / 尾 **±4 帧**（3×9 = 27 帧/镜）。
_SAMPLE_OFFSETS = (-4, -3, -2, -1, 0, 1, 2, 3, 4)


def _min_z(character, frame: int):
    """depsgraph 求值后，四个网格对象的世界包围盒最低点；**量不到返回 ``None``**。

    为什么不是 ``float("nan")``：探针把结果打成 ``BD_TEST_RESULT {json}``，而
    `json.dumps` 会把 NaN 原样印成非法的 JSON 记号 `NaN` → PowerShell 5.1 的
    `ConvertFrom-Json` 整行解析失败 → 这一批 `passed` 名称全丢 → 挂在它上面的
    RK 静默变成 `not_measured`（实测 RK-6/RK-8 就是这么掉成"未量"的）。
    ``None`` 在 JSON 里是合法的 ``null``，语义同样是"取不到值"。
    """
    scene = bpy.context.scene
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lowest = None
    for key in ("body", "head", "leg_l", "leg_r"):
        obj = character.parts.get(key)
        if obj is None:
            return None
        try:
            evaluated = obj.evaluated_get(depsgraph)
        except (ReferenceError, RuntimeError):
            # 对象已被删除（负例）：必须判失败，不能静默跳过。
            return None
        for corner in evaluated.bound_box:
            point = evaluated.matrix_world @ Vector(corner)
            lowest = point.z if lowest is None else min(lowest, point.z)
    return lowest


def _sample_frames(start: int, end: int):
    middle = start + max((end - start) // 2, 0)
    frames = []
    for anchor in (start, middle, end):
        for offset in _SAMPLE_OFFSETS:
            frame = anchor + offset
            if start <= frame <= end:
                frames.append(frame)
    return sorted(set(frames))


def t_rk6_no_floating_no_sinking():
    """站立段落点 ∈ [-0.02, +0.02]，行走段 ≥ -0.02（逐采样帧）。"""
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 96
    character = create_character("char_001", "小明", "#FF6B6B")
    create_camera("shot_001", (0.0, -4.0, 1.2), look_at=(0.0, 0.0, 0.9))

    blender = MotionBlender(character)
    blender.add("nod", 1, 48, cycles=2)                 # 站立段：只有头动
    blender.add("walk_to", 49, 96,
                target_position=(1.0, 0.0, 0.0))        # 行走段
    blender.bake()

    standing = []
    walking = []
    for frame in _sample_frames(1, 48):
        standing.append((frame, _min_z(character, frame)))
    for frame in _sample_frames(49, 96):
        walking.append((frame, _min_z(character, frame)))

    bad_standing = [item for item in standing
                    if not (item[1] is not None
                            and -GROUND_EPS <= item[1] <= GROUND_EPS)]
    bad_walking = [item for item in walking
                   if not (item[1] is not None and item[1] >= -GROUND_EPS)]
    return {"ok": (bool(standing) and bool(walking)
                   and not bad_standing and not bad_walking),
            "standing_frames": len(standing), "walking_frames": len(walking),
            "bad_standing": [(f, round(z, 4)) for f, z in bad_standing],
            "bad_walking": [(f, round(z, 4)) for f, z in bad_walking],
            "standing_range": [round(min(z for _, z in standing), 4),
                               round(max(z for _, z in standing), 4)],
            "walking_range": [round(min(z for _, z in walking), 4),
                              round(max(z for _, z in walking), 4)]}


def _ground_report(*, overshoot: bool) -> dict:
    """建一个"坐下 → 站起 → 站定"的场景，逐采样帧量网格最低点。

    **反向突变怎么做，这里踩过一次坑，记下来**（2026-10-03 实测）：§B.5 的 RK-6
    行点名的突变是"把 `stand` 的落点从绝对地面高度改回**相对 `+drop`**"。
    我按字面实现（把 `motion.model._root_drop` 换成旧的相对写法）之后，
    `compose` 出来的轨迹与 `min_z` **逐位相同**——

    ```
    compose(stand 49-96) 在 96 帧：clean 0.2 ／ "旧写法" 0.2
    sit→stand 的 min_z：clean {1:0.0, 48:-0.162, 72:-0.1098, 96:0.038}
                        旧写法 完全相同
    ```

    原因是 `compose` 的核心语义是"**基线 ＋ (当前姿态 − 起手姿态)**"（见它的
    docstring）：每个动作只贡献**差值**，所以 `-drop→0` 与 `0→+drop` 的差都是
    `+drop`，两者在合成里**等价**。也就是说 §B.5 那一行的**机制**不具区分力
    （它的**意图**——"落点抬到地面上方就必须判悬空"——是可测的）。

    所以这里的突变按**意图**做：让站起段的终点落在**地面上方 `drop`**
    （`-drop*(1-t) + drop*t`：起手仍与 sit 首尾相接，终点多抬 `drop`）。
    它才是"角色悬空"这件事的忠实表达，也真的能把判据逼红。

    正向与突变**共用这一段测量**：判据一个字不改，只改被测实现。
    """
    import block_director.motion.model as motion_model

    original = motion_model._root_drop

    #: 突变：**行走时把根节点整体抬高 `lift`**（"角色悬空"的忠实表达）。
    #: 替换的是走路姿态函数本身——烘焙路径真的会调用它，所以这是"把实现做坏"，
    #: 不是事后把物体挪一挪。
    original_walk = motion_model._walk_root

    def lifted(start, end, source, target, rate, bob, lean):
        inner = original_walk(start, end, source, target, rate, bob, lean)

        def pose(frame: int):
            values = dict(inner(frame))
            value = values.get("root.location")
            if value is not None:
                # **必须是斜坡，不能是常数**：`compose` 只取"当前 − 起手"的差值，
                # 给每一帧加同一个常数会被它整个抵消（实测：常数版与 clean **逐位
                # 相同**）。斜坡改变的是**差值**，才是"越走越高/最终悬空"。
                t = motion_model._ease(motion_model._progress(frame, start, end))
                values["root.location"] = (value[0], value[1],
                                           value[2] + LIFT * t)
            return values

        return pose

    if overshoot:
        motion_model._root_drop = original
        motion_model._walk_root = lifted
    try:
        scene = fresh_scene()
        scene.frame_start, scene.frame_end = 1, 96
        character = create_character("char_001", "小明", "#FF6B6B")
        create_camera("shot_001", (0.0, -4.0, 1.2), look_at=(0.0, 0.0, 0.9))
        blender = MotionBlender(character)
        # 与 RK-6 的正向判据**同一组动作**（`t_rk6_no_floating_no_sinking`）：
        # 站立段只有头动，行走段必须非负。sit/stand 那对不适合做这条正对照——
        # 坐下的 0.2 下沉与折腿会让**网格**最低点落到地面以下（实测 −0.21），
        # 那是坐姿本身的形态，不是"悬空/穿地"要量的东西。
        blender.add("nod", 1, 48, cycles=2)
        blender.add("walk_to", 49, 96, target_position=(1.0, 0.0, 0.0))
        blender.bake()
        samples = [(frame, _min_z(character, frame))
                   for frame in _sample_frames(1, 96)]
    finally:
        motion_model._root_drop = original
        motion_model._walk_root = original_walk
    missing = [frame for frame, z in samples if z is None]
    floating = [(frame, round(z, 4)) for frame, z in samples
                if z is not None and z > GROUND_EPS]
    sinking = [(frame, round(z, 4)) for frame, z in samples
               if z is not None and z < -GROUND_EPS]
    return {"frames": len(samples), "missing": missing,
            "floating": floating, "sinking": sinking,
            "z_range": [round(min(z for _, z in samples if z is not None), 4),
                        round(max(z for _, z in samples if z is not None), 4)]}


def t_rk6_floating_must_go_red():
    """§B.5 的 **RK-6 反向突变**（按**意图**做，机制见 `_ground_report` 的说明）：
    让角色在行走段被抬离地面 → 必须出现 `min_z > +0.02` 的帧。

    成对跑：正向（现实现）全程**既不悬空也不穿地**；突变之后**必须**出现悬空帧。
    只跑突变的一半不算数——"判据恒红"也能骗过那种写法。
    """
    baseline = _ground_report(overshoot=False)
    mutated = _ground_report(overshoot=True)
    ok = (baseline["frames"] > 0 and not baseline["missing"]
          and not baseline["floating"] and not baseline["sinking"]
          and not mutated["missing"] and bool(mutated["floating"]))
    return {"ok": ok, "baseline": baseline, "mutated": mutated,
            "ground_eps": GROUND_EPS, "lift": LIFT,
            "mutation": ("行走段的根节点随进度抬升（终点离地 lift）——"
                         "角色悬空"),
            "doc_note": ("§B.5 原文点名的『把 stand 落点改回相对 +drop』经实测在 "
                         "compose 下与现实现**逐位等价**（它只取『当前 − 起手』"
                         "的差值，常数偏移会被整个抵消），不具区分力；常数版的"
                         "walk 抬升同样被抵消。所以突变按**意图**做：让根节点"
                         "的**差值**把它抬离地面")}


def t_rk6_missing_mesh_is_a_failure():
    """负例：网格对象缺失必须判失败，而不是静默跳过。"""
    scene = fresh_scene()
    character = create_character("char_001", "小明", "#FF6B6B")
    create_camera("shot_001", (0.0, -4.0, 1.2), look_at=(0.0, 0.0, 0.9))
    body = character.parts.get("body")
    hidden_name = body.name
    bpy.data.objects.remove(body, do_unlink=True)
    value = _min_z(character, 1)
    # `NaN` **不是合法 JSON**：`json.dumps` 会原样印出 `NaN`，而 PowerShell 5.1 的
    # `ConvertFrom-Json` 直接解析失败 → `run_tests.ps1` 收不到这一批 `passed`
    # 名称 → **RK-6 与 RK-8 会双双变成 `not_measured`**（按 §4.1b 硬规则 1，
    # "没量到"不能算通过）。判据本身不变（仍是"取不到 min_z 就判失败"），
    # 只把上报值换成 JSON 安全的 `null`（`None`）。
    return {"ok": value is None, "removed": hidden_name, "min_z": value}


# --------------------------------------------------------------------------- #
# RK-8（v1.4 §4.1）：躯干主惯性轴与 +Z 的夹角 = 登记倾角 ±3°
# --------------------------------------------------------------------------- #
def _principal_axis(obj, *, iterations: int = 64):
    """用世界空间顶点的协方差矩阵做幂迭代，取主特征向量（确定性）。"""
    from mathutils import Vector as _V

    scene = bpy.context.scene
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co
                  for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    if len(points) < 8:
        return None
    center = sum(points, _V()) / len(points)
    covariance = [[0.0] * 3 for _ in range(3)]
    for point in points:
        delta = point - center
        for i in range(3):
            for j in range(3):
                covariance[i][j] += delta[i] * delta[j]
    vector = _V((1.0, 0.0, 0.0))
    for _ in range(max(int(iterations), 1)):
        updated = _V((sum(covariance[i][j] * vector[j] for j in range(3))
                      for i in range(3)))
        if updated.length < 1e-12:
            return None
        vector = updated.normalized()
    _ = scene
    return vector


def t_rk8_body_tilt_matches_the_registered_angle():
    scene = fresh_scene()
    scene.frame_start, scene.frame_end = 1, 48
    character = create_character("char_001", "小明", "#FF6B6B")
    create_camera("shot_001", (0.0, -4.0, 1.2), look_at=(0.0, 0.0, 0.9))

    from block_director.motion.model import body_tilt_params
    registered = {"degrees": 12.0}      # 写方用的别名（BW-1）
    angle_deg, axis = body_tilt_params(registered)

    blender = MotionBlender(character)
    blender.add("body_tilt", 1, 48, **registered)
    blender.bake()
    scene.frame_set(48)
    bpy.context.view_layer.update()

    torso = character.parts.get("body")
    principal = _principal_axis(torso) if torso is not None else None
    if principal is None:
        return {"ok": False, "error": "躯干网格不可用"}
    import math
    cos_value = max(-1.0, min(1.0, abs(principal.z) / max(principal.length, 1e-9)))
    measured = math.degrees(math.acos(cos_value))
    return {"ok": abs(measured - angle_deg) <= 3.0,
            "registered_deg": angle_deg, "axis": axis,
            "measured_deg": round(measured, 3),
            "tolerance": 3.0}


def main() -> int:
    capture_main_thread()
    check("bake_creates_keyframes", t_bake_creates_keyframes)
    check("bake_keeps_the_authored_facing", t_bake_keeps_the_authored_facing)
    check("root_moves_over_time", t_root_moves_over_time)
    check("render_frames_differ", t_render_frames_differ)
    check("conflict_rejected", t_conflict_rejected)
    check("sit_then_stand_returns_to_ground", t_sit_then_stand_returns_to_ground)
    check("head_motion_is_isolated", t_head_motion_is_isolated)
    check("rk6_no_floating_no_sinking", t_rk6_no_floating_no_sinking)
    # §B.5 的反向突变：把角色抬离地面，判据必须变红（成对跑）。
    check("rk6_floating_goes_red", t_rk6_floating_must_go_red)
    check("rk6_missing_mesh_is_a_failure", t_rk6_missing_mesh_is_a_failure)
    check("rk8_body_tilt_matches_the_registered_angle",
          t_rk8_body_tilt_matches_the_registered_angle)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
