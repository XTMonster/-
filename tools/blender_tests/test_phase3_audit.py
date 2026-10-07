"""Phase 3 集成测试：轴线与构图审核（执行文档 v1.2 §10.3 / §10.4）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase3_audit.py
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

from block_director.layer3_engine.character_system import create_character  # noqa: E402
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    check_camera_axis,
    create_camera,
    establish_axis_from_speakers,
    evaluate_camera_composition,
    place_camera_for_shot,
    visualize_axis,
)
from block_director.layer3_engine.collection_router import (  # noqa: E402
    GUIDES_COLLECTION,
    ensure_collections,
    objects_in_collection,
)
from block_director.cinema.axis import thirty_degree_violation  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
OUTDIR = ROOT / "tools" / "_probe_out"


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    ensure_collections(scene)
    return scene


def two_characters():
    left = create_character("char_001", "小明", "#FF6B6B", location=(-0.5, 0.0, 0.0))
    right = create_character("char_002", "小红", "#6BC5FF", location=(0.5, 0.0, 0.0))
    return left, right


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


# --------------------------------------------------------------------------- #
# 1. 轴线：首镜确立基准侧，越轴被拦下
# --------------------------------------------------------------------------- #
def t_axis_established_and_enforced():
    scene = fresh_scene()
    left, right = two_characters()
    good = create_camera("good", (0.0, 5.0, 1.2), look_at=(0.0, 0.0, 1.0))
    axis = establish_axis_from_speakers([left, right], good.camera)
    assert axis is not None

    violation_ok = check_camera_axis(axis, good.camera) is None
    bad = create_camera("bad", (0.0, -5.0, 1.2), look_at=(0.0, 0.0, 1.0),
                        make_scene_camera=False)
    violation_bad = check_camera_axis(axis, bad.camera)

    return {"ok": violation_ok and bool(violation_bad)
            and "180° 轴线" in violation_bad,
            "established_side": axis.established_side,
            "labels": [axis.left_label, axis.right_label],
            "good_camera_ok": violation_ok,
            "bad_camera_message": violation_bad}


# --------------------------------------------------------------------------- #
# 2. 轴线可视化必须落在 Guides 且不参与渲染
# --------------------------------------------------------------------------- #
def t_axis_visual_is_a_guide():
    fresh_scene()
    left, right = two_characters()
    camera = create_camera("c", (0.0, 5.0, 1.2), look_at=(0.0, 0.0, 1.0))
    axis = establish_axis_from_speakers([left, right], camera.camera)
    visual = visualize_axis(axis)
    guides = {o.name for o in objects_in_collection(GUIDES_COLLECTION)}
    return {"ok": visual.name in guides and visual.hide_render is True,
            "object": visual.name, "in_guides": visual.name in guides,
            "hide_render": bool(visual.hide_render)}


# --------------------------------------------------------------------------- #
# 3. 构图评分：合理解算高分，主体出画低分
# --------------------------------------------------------------------------- #
def t_composition_rewards_good_framing():
    scene = fresh_scene()
    left, right = two_characters()
    place_camera_for_shot("ms", (0.0, 0.0, 0.0), shot_type="MS", side="front")
    good = evaluate_camera_composition(scene.camera, [left, right], "MS")

    # 把角色整体推出画面，构图分必须掉下来
    for character in (left, right):
        character.root.location.x += 9.0
    bpy.context.view_layer.update()
    bad = evaluate_camera_composition(scene.camera, [left, right], "MS")

    return {"ok": good.passed and bad.score < good.score - 10,
            "good_score": good.score, "bad_score": bad.score,
            "good_items": {k: round(v.score, 2) for k, v in good.items.items()},
            "bad_suggestions": bad.suggestions}


# --------------------------------------------------------------------------- #
# 4. 遮挡检测（权重最高的分项）
# --------------------------------------------------------------------------- #
def t_occlusion_is_detected():
    scene = fresh_scene()
    left, right = two_characters()
    place_camera_for_shot("ms", (0.0, 0.0, 0.0), shot_type="MS", side="front")
    clean = evaluate_camera_composition(scene.camera, [left, right], "MS")

    # 在相机与角色之间塞一块挡板
    bpy.ops.mesh.primitive_cube_add(size=2.6, location=(0.0, 2.0, 0.9))
    blocker = bpy.context.object
    blocker.name = "BD_Blocker"
    bpy.context.view_layer.update()
    blocked = evaluate_camera_composition(scene.camera, [left, right], "MS")

    return {"ok": clean.items["occlusion"].score == 1.0
            and blocked.items["occlusion"].score == 0.0
            and blocked.score < clean.score,
            "clean_score": clean.score, "blocked_score": blocked.score,
            "occlusion_score": blocked.items["occlusion"].score,
            "suggestion": blocked.items["occlusion"].suggestion}


# --------------------------------------------------------------------------- #
# 5. R010：角差不足且景别未变化时报警
# --------------------------------------------------------------------------- #
def t_thirty_degree_rule():
    fresh_scene()
    target = (0.0, 0.0)
    previous = (0.0, 5.0)
    same_angle = (0.0, 5.02)
    flagged = thirty_degree_violation(previous, same_angle, target, "MS", "MS")
    allowed_by_size = thirty_degree_violation(previous, same_angle, target, "MS", "CU")
    allowed_by_angle = thirty_degree_violation(previous, (5.0, 0.0), target,
                                               "MS", "MS")
    return {"ok": bool(flagged) and allowed_by_size is None
            and allowed_by_angle is None,
            "flagged": flagged, "allowed_by_size": allowed_by_size,
            "allowed_by_angle": allowed_by_angle}


# --------------------------------------------------------------------------- #
# 6. 一段对话的多镜连续性：双人建立轴线 + 四个单人反打必须**全部**待在同一侧
#
# 现场（`docs/evidence/20261003_chunked_long9/`，64 镜真跑）：R001 的 61 条
# 错误、命中 21/64 镜，**全部是单人镜头**；同跑里两人镜头一条都没有。
# 根因是 `camera.side` 相对**被摄主体朝向**解析，而两人相对而立时两个角色的
# 朝向相反 —— 同一个 `front_right` 落在世界轴线的两侧。v1.5 只把两人镜头
# 改成按轴线法线解算，单人镜头那条路当时没接上。
# 这条判据换了不变量：不是"某一次算出来等于某个数"，而是**整段对话的每一镜
# 都不越轴**——对拍不到的那类缺陷（摆位错但两次都错得一样）才会被抓到。
# --------------------------------------------------------------------------- #
def _dialogue_line_plan():
    from block_director.contracts.plan import Plan, ShotPlan

    shots = [
        ShotPlan.from_dict({
            "shot_id": "shot_001", "order": 1, "intent": "建立对话关系",
            "shot_type": "MS", "duration_frames": 48,
            "characters": ["char_001", "char_002"],
            "camera": {"side": "front_left", "lens": 35}}),
        # 甲的单人：`front_right` 本来就在建立侧，不需要镜像
        ShotPlan.from_dict({
            "shot_id": "shot_002", "order": 2, "intent": "甲的反应",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_001"], "camera": {"side": "front_right"}}),
        # 乙的单人：同一个 `front_right` 被镜像到建立侧
        ShotPlan.from_dict({
            "shot_id": "shot_003", "order": 3, "intent": "乙的反打",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_002"], "camera": {"side": "front_right"}}),
        # 甲的另一侧：同样要被镜像回来
        ShotPlan.from_dict({
            "shot_id": "shot_004", "order": 4, "intent": "甲换一个角度",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_001"], "camera": {"side": "front_left"}}),
        # 乙的背侧：镜像后仍是背拍（前/后关系不变），也必须合规
        ShotPlan.from_dict({
            "shot_id": "shot_005", "order": 5, "intent": "乙转身离开",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_002"], "camera": {"side": "back_right"}}),
    ]
    return Plan(shots=shots, scene_heading="INT. 码头 - 午后")


def t_a_dialogue_line_survives_reverse_singles():
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene

    fresh_scene()
    plan = _dialogue_line_plan()
    spec = SceneSpec.from_plan(plan)
    summary = build_scene(plan, spec, clear_scene=True)
    context = get_context()
    axis = context.axis
    assert axis is not None, "双人首镜必须建立轴线"

    violations = {}
    sides = {}
    for shot_id, camera in sorted(context.cameras.items()):
        message = check_camera_axis(axis, camera)
        if message:
            violations[shot_id] = message
        sides[shot_id] = axis.side_of(
            (camera.matrix_world.translation.x,
             camera.matrix_world.translation.y))
    mirrored = [w for w in summary.warnings if "镜像" in w]
    return {"ok": not violations
            and set(sides.values()) == {axis.established_side}
            and len(mirrored) == 3,
            "established_side": axis.established_side,
            "sides": sides, "violations": violations,
            "mirror_notes": mirrored,
            "warnings": summary.warnings}


# --------------------------------------------------------------------------- #
# 7. 机位瞄的是"这一镜人在哪"，不是"剧本开始时的站位"（v1.6）
#
# 现场（2026-10-04，`work/_anchor_probe.py`，`long9` 工程）：角色在**前面的镜头**
# 里走动过，而 `place_shot_camera` 一直用 `CastMember.initial_location` 摆机位——
# 64 镜里 **20 镜**的单主体与锚点差 > 1 m，最远 **7.7 m**（`shot_059`：伊恩实际在
# (8.6, −6.0)，机位却按 (0.9, 0.0) 摆）。那些镜头本来就把主体拍在画框边缘/画外，
# 是剩下的 COMPOSITION 低分的主因。
#
# 这条判据换了不变量：不是"某个坐标等于某个数"，而是**机位的对准点跟着角色走**。
# 旧代码在这里必然红（对准点会停在起始位置 0.0，而角色已经走到 5.0 附近）。
# --------------------------------------------------------------------------- #
def _anchor_plan():
    from block_director.contracts.plan import Plan, ShotPlan

    shots = [
        # 第一镜把角色从起始站位走到 +X 5 米处
        ShotPlan.from_dict({
            "shot_id": "shot_001", "order": 1, "intent": "走过去",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_001"],
            "actions": [{"character_id": "char_001", "action_type": "walk_to",
                         "start_frame": 1, "end_frame": 48,
                         "target_position": [5.0, 0.0, 0.0]}]}),
        ShotPlan.from_dict({
            "shot_id": "shot_002", "order": 2, "intent": "他已经不在原地了",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_001"]}),
    ]
    return Plan(shots=shots, scene_heading="INT. 码头 - 日")


def t_the_camera_aims_where_the_character_is_now():
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene

    fresh_scene()
    plan = _anchor_plan()
    spec = SceneSpec.from_plan(plan)
    summary = build_scene(plan, spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene
    start = int(context.schedule["shot_002"][0])
    scene.frame_set(start)
    bpy.context.view_layer.update()
    placed = context.character("char_001").root.matrix_world.translation
    target = next(item.camera_target for item in summary.results
                  if item.shot_id == "shot_002")
    camera = context.cameras["shot_002"]
    initial = next(member.initial_location for member in spec.cast
                   if member.id == "char_001")
    return {"ok": (placed.x > 3.0
                   and abs(target[0] - placed.x) < 0.6
                   and abs(target[1] - placed.y) < 0.6
                   and abs(target[0] - initial[0]) > 3.0),
            "character_now": [round(float(placed.x), 3), round(float(placed.y), 3)],
            "camera_target": [round(float(v), 3) for v in target],
            "initial_location": [round(float(v), 3) for v in initial],
            "camera_position": [round(float(v), 3)
                                for v in camera.matrix_world.translation]}


# --------------------------------------------------------------------------- #
# 8. R001 必须说清**根因**：是机位摆错，还是"角色走位跨过了轴线"
#
# 现场（2026-10-04，`work/_r001_probe.py`）：锚点与接力修好之后仍会红的 10 条
# R001 里，多数是"人已经走到轴线另一侧"——此时"拍到这张脸"与"待在轴线同侧"
# 不可能同时满足（`station._honour_the_established_side` 的边界：镜像会把正面
# 变成背拍，所以它保持模型要的方向、把冲突留给 R001 报）。旧文案只写"把相机移
# 到另一侧"，修复回路就会去挪机位，白烧回合。
# --------------------------------------------------------------------------- #
def _crossing_plan(visible: bool = False):
    from block_director.contracts.plan import Plan, ShotPlan

    walk = {"character_id": "char_001", "action_type": "walk_to",
            "start_frame": 1, "end_frame": 48,
            "params": {"target_position": [-0.9, 3.0, 0.0]}}
    first = ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "建立关系",
        "shot_type": "MS", "duration_frames": 48,
        "characters": ["char_001", "char_002"],
        "camera": {"side": "front_left", "lens": 35}})
    middle = ShotPlan.from_dict({
        "shot_id": "shot_002", "order": 2,
        "intent": "两人同框、他走过去" if visible else "只拍另一个人，他绕过去",
        "shot_type": "MS", "duration_frames": 48,
        "characters": ["char_001", "char_002"] if visible else ["char_002"],
        "camera": {"side": "front_left", "lens": 35},
        "actions": [walk]})
    last = ShotPlan.from_dict({
        "shot_id": "shot_003", "order": 3, "intent": "再同框",
        "shot_type": "MS", "duration_frames": 48,
        "characters": ["char_001", "char_002"],
        "camera": {"side": "front_left", "lens": 35}})
    shots = [first, middle, last]
    return Plan(shots=shots, scene_heading="INT. 码头 - 日")


def t_r001_reports_an_unbridged_axis_rebuild():
    """R001 现在判的是**观众看到的东西**（GLM 5.3 会诊 A2/A3）：
    量"**规范首镜线** vs **走位后的派生线**"的偏差——构建器按派生线摆机位也能
    满足几何约束，但"这次重建有没有被拍出来"是它无法自证的。
    重建若发生在**两人同框**的那一镜里（看得见）⇒ 合法，只给告警；
    谁也没看见就重建 ⇒ 报错。"""
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.shot_builder import build_scene

    def r001(visible: bool):
        fresh_scene()
        plan = _crossing_plan(visible=visible)
        build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
        context = get_context()
        bpy.context.scene.frame_set(int(context.schedule["shot_003"][0]))
        bpy.context.view_layer.update()
        result = BpyShotAuditor().audit("shot_003")
        return {"errors": [item.message for item in result.errors
                           if item.rule == "R001"],
                "warnings": [item.message for item in result.warnings
                             if item.rule == "R001"],
                "passed": bool(result.passed)}

    unseen = r001(visible=False)
    seen = r001(visible=True)
    return {"ok": bool(unseen["errors"])
            and "轴线已被走位重建" in unseen["errors"][0]
            and "没有任何镜头把" in unseen["errors"][0]
            and not seen["errors"] and bool(seen["warnings"]),
            "unseen": unseen, "visible": seen}


# --------------------------------------------------------------------------- #
# 9. R003 必须**按镜收口**：别的镜头里的重叠不许算在干净的镜头上
#
# 现场（2026-10-04，`long12`）：全片只有 **7 处**同角色动作重叠，却被记成
# **312 条 / 64 镜全红**——`_action_ranges` 读的是整份计划，审计只按角色过滤，
# 于是一处重叠被**广播**到每一张含该角色的镜头审计里（同一条消息出现 48 次），
# 逐镜通过率塌成 0/64，修复回路也被同一句话灌满。
# --------------------------------------------------------------------------- #
def _overlap_scope_plan():
    from block_director.contracts.plan import Plan, ShotPlan

    shots = [
        ShotPlan.from_dict({
            "shot_id": "shot_001", "order": 1, "intent": "有重叠的那一镜",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_001"],
            "actions": [{"character_id": "char_001", "action_type": "turn_head",
                         "start_frame": 1, "end_frame": 30, "params": {}},
                        {"character_id": "char_001", "action_type": "look_at",
                         "start_frame": 10, "end_frame": 40,
                         "params": {"yaw_deg": 10}}]}),
        ShotPlan.from_dict({
            "shot_id": "shot_002", "order": 2, "intent": "干净的那一镜",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_001"],
            "actions": [{"character_id": "char_001", "action_type": "nod",
                         "start_frame": 1, "end_frame": 20,
                         "params": {"cycles": 1}}]}),
    ]
    return Plan(shots=shots, scene_heading="INT. 码头 - 日")


def t_r003_is_scoped_to_the_shot_being_audited():
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.shot_builder import build_scene

    fresh_scene()
    plan = _overlap_scope_plan()
    spec = SceneSpec.from_plan(plan)
    build_scene(plan, spec, clear_scene=True)
    auditor = BpyShotAuditor()
    dirty = auditor.audit("shot_001")
    clean = auditor.audit("shot_002")
    dirty_rules = [item.rule for item in dirty.errors]
    clean_rules = [item.rule for item in clean.errors]
    clean_msgs = [item.message for item in clean.errors if item.rule == "R003"]
    return {"ok": "R003" in dirty_rules and "R003" not in clean_rules
            and not clean_msgs,
            "dirty_rules": dirty_rules, "clean_rules": clean_rules,
            "clean_errors": [item.message for item in clean.errors],
            "clean_passed": clean.passed}


# --------------------------------------------------------------------------- #
# 10. 视线留白真的接上了：单主体镜头横移 1/6 幅宽，双人镜头不动
#
# 现场：`cinema/station.aim_offset_for_lead_room` ＋ `solve_framing(aim_offset_x=…)`
# 在 2026-10-04 第一次接上时是**净负**（那时机位锚点还是剧本起始站位，主体本来
# 就在画框边缘）。锚点（§六十三）与走位接力（§六十四）落地后重测三份冻结工程
# （`docs/evidence/20261004-leadroom-retest/`）：构图门 ≥70 的镜数
# long9 30 → **41**、long11 17 → **21**、long12 25 → 24 ⇒ 接上。
# 这条用例钉住"接上了"，免得哪天被顺手摘掉。
# --------------------------------------------------------------------------- #
def _lead_room_plan():
    from block_director.contracts.plan import Plan, ShotPlan

    shots = [
        ShotPlan.from_dict({
            "shot_id": "shot_001", "order": 1, "intent": "单人镜",
            "shot_type": "MCU", "duration_frames": 48,
            "characters": ["char_001"], "camera": {"side": "left", "lens": 50}}),
        ShotPlan.from_dict({
            "shot_id": "shot_002", "order": 2, "intent": "双人镜",
            "shot_type": "MS", "duration_frames": 48,
            "characters": ["char_001", "char_002"],
            "camera": {"side": "front", "lens": 35}}),
    ]
    return Plan(shots=shots, scene_heading="INT. 码头 - 日")


def t_lead_room_shifts_single_subject_shots_only():
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene

    fresh_scene()
    plan = _lead_room_plan()
    spec = SceneSpec.from_plan(plan)
    summary = build_scene(plan, spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene

    def target_of(shot_id: str):
        return next(item.camera_target for item in summary.results
                    if item.shot_id == shot_id)

    scene.frame_set(int(context.schedule["shot_001"][0]))
    bpy.context.view_layer.update()
    single_now = context.character("char_001").root.matrix_world.translation
    single_target = target_of("shot_001")
    single_offset = ((single_target[0] - single_now.x) ** 2
                     + (single_target[1] - single_now.y) ** 2) ** 0.5

    scene.frame_set(int(context.schedule["shot_002"][0]))
    bpy.context.view_layer.update()
    two_target = target_of("shot_002")
    people = [context.character("char_001").root.matrix_world.translation,
              context.character("char_002").root.matrix_world.translation]
    centre_x = sum(p.x for p in people) / 2.0
    centre_y = sum(p.y for p in people) / 2.0
    two_offset = ((two_target[0] - centre_x) ** 2
                  + (two_target[1] - centre_y) ** 2) ** 0.5
    notes = [w for item in summary.results for w in (item.warnings or [])
             if "视线留白" in w]
    #: 竖直：单主体抬 `HEAD_ROOM_AIM_M`，双人不动（`SHOT_FRAME.target_z` 是冻结常量）。
    from block_director.cinema.framing import SHOT_FRAME
    from block_director.cinema.station import HEAD_ROOM_AIM_M

    single_expected_z = SHOT_FRAME["MCU"].target_z + HEAD_ROOM_AIM_M
    two_expected_z = SHOT_FRAME["MS"].target_z
    single_dz = abs(single_target[2] - single_expected_z)
    two_dz = abs(two_target[2] - two_expected_z)
    return {"ok": single_offset > 0.15 and two_offset < 0.05 and bool(notes)
            and single_dz < 1e-6 and two_dz < 1e-6,
            "single_offset_m": round(single_offset, 3),
            "two_shot_offset_m": round(two_offset, 3),
            "single_target_z": round(single_target[2], 3),
            "two_target_z": round(two_target[2], 3),
            "lead_room_notes": notes[:2]}


def _composition_declaration_plan():
    """四镜同几何：只有 `composition` 声明不同（其余字段逐字相同）。"""
    from block_director.contracts.plan import Plan, ShotPlan

    common = {"shot_type": "MCU", "duration_frames": 48,
              "characters": ["char_001"], "camera": {"side": "left", "lens": 50}}
    shots = []
    for index, composition in enumerate([
            {},                                   # 0 不声明（= 求解器默认）
            {"rule": "center"},                   # 1 显式居中
            {"subject_position": "left_third"},   # 2 主体落左三分线
            {"subject_position": "right_third"},  # 3 主体落右三分线
    ], start=1):
        payload = {"shot_id": f"shot_{index:03d}", "order": index,
                   "intent": f"构图声明 {index}"}
        payload.update(common)
        payload["composition"] = composition
        shots.append(ShotPlan.from_dict(payload))
    return Plan(shots=shots, scene_heading="INT. 码头 - 日")


def t_declared_composition_overrides_the_default_aim():
    """v1.5 §4.6（卡 P3-T4）：`shot.composition` 真的接到了求解器上。

    同一几何下四镜只换声明 ⇒ 对准点必须按声明落到不同位置：
    居中 ⇒ 对准点回到主体；左/右三分 ⇒ 朝相反两侧偏 1/6 幅宽且与前两者里的
    **缺省那一镜**同幅（缺省就是 `lead_room`，它的取值就是 ±1/6 幅宽之一）。
    """
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene

    fresh_scene()
    plan = _composition_declaration_plan()
    spec = SceneSpec.from_plan(plan)
    summary = build_scene(plan, spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene

    targets = {}
    for shot in plan.shots:
        scene.frame_set(int(context.schedule[shot.shot_id][0]))
        bpy.context.view_layer.update()
        target = next(item.camera_target for item in summary.results
                      if item.shot_id == shot.shot_id)
        root = context.character("char_001").root.matrix_world.translation
        targets[shot.shot_id] = ((float(target[0]), float(target[1])),
                                 (float(root.x), float(root.y)))

    def delta(shot_id):
        (tx, ty), (sx, sy) = targets[shot_id]
        return (tx - sx, ty - sy)

    def magnitude(shot_id):
        dx, dy = delta(shot_id)
        return (dx * dx + dy * dy) ** 0.5

    default_d = delta("shot_001")
    center_d = delta("shot_002")
    left_d = delta("shot_003")
    right_d = delta("shot_004")

    opposite = (left_d[0] * right_d[0] + left_d[1] * right_d[1]) < 0.0
    #: 缺省那一镜的位移必须**逐分量**等于左三分或右三分之一（幅值同为 1/6）。
    matches_a_declared_side = any(
        abs(default_d[0] - candidate[0]) < 1e-6
        and abs(default_d[1] - candidate[1]) < 1e-6
        for candidate in (left_d, right_d))
    ok = (magnitude("shot_001") > 0.15
          and magnitude("shot_002") < 0.05
          and magnitude("shot_003") > 0.15
          and magnitude("shot_004") > 0.15
          and opposite and matches_a_declared_side)
    return {"ok": bool(ok),
            "default_offset_m": round(magnitude("shot_001"), 3),
            "center_offset_m": round(magnitude("shot_002"), 3),
            "left_third_offset_m": round(magnitude("shot_003"), 3),
            "right_third_offset_m": round(magnitude("shot_004"), 3),
            "left_and_right_opposite": opposite,
            "default_matches_a_declared_side": matches_a_declared_side,
            "default_delta": [round(value, 4) for value in default_d],
            "left_delta": [round(value, 4) for value in left_d],
            "right_delta": [round(value, 4) for value in right_d]}


def _sequential_axis_plan():
    """三镜：第一镜确立轴线，第二镜里乙绕到另一侧并且**两人同框**（观众看得见）。"""
    from block_director.contracts.plan import Plan, ShotPlan

    shots = [
        ShotPlan.from_dict({
            "shot_id": "shot_001", "order": 1, "intent": "确立轴线",
            "shot_type": "MS", "duration_frames": 48,
            "characters": ["char_001", "char_002"]}),
        ShotPlan.from_dict({
            "shot_id": "shot_002", "order": 2, "intent": "绕到另一侧",
            "shot_type": "MS", "duration_frames": 48,
            "characters": ["char_001", "char_002"],
            "actions": [{"character_id": "char_002", "action_type": "walk_to",
                         "start_frame": 1, "end_frame": 48,
                         "target_position": [-1.6, 1.6, 0.0]}]}),
        ShotPlan.from_dict({
            "shot_id": "shot_003", "order": 3, "intent": "换位之后",
            "shot_type": "MS", "duration_frames": 48,
            "characters": ["char_001", "char_002"]}),
    ]
    return Plan(shots=shots, scene_heading="INT. 码头 - 日")


def t_the_builder_state_machine_is_camera_truthful():
    """**构建器摆完之后的侧别表，必须等于"用真机位算出来"的那张表**（§七十三 收尾）。

    现场（2026-10-04）：构建器原来用"连线转角 ≥90°"**猜**换位，`long9` 上它猜出的表
    与真机位表在 **38 镜**上不一致（其中 27 镜是画面左右序判据都证实不了的自指错误）。
    修法是**顺序**：摆完一镜就量"连线扫没扫过这台机位"，再决定后续镜头待在哪一侧。
    这条不变量正是那个修法：`_axis_sides_used`（构建器实际用的） == `axis_state(cameras=…)`
    （真机位算的）。
    """
    from block_director.cinema.axis import axis_state
    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene

    fresh_scene()
    plan = _sequential_axis_plan()
    spec = SceneSpec.from_plan(plan)
    build_scene(plan, spec, clear_scene=True)
    context = get_context()
    scene = bpy.context.scene
    axis = context.axis
    used = {name: int(side)
            for name, side in (getattr(context, "_axis_sides_used", None) or {}).items()}
    initial = {}
    for member in spec.cast:
        initial[str(member.id)] = tuple(member.initial_location)
        if member.name:
            initial[str(member.name)] = tuple(member.initial_location)
    cameras = {}
    restore = int(scene.frame_current)
    for shot in plan.shots:
        camera = context.camera_for(shot.shot_id)
        if camera is None:
            continue
        start = int(context.schedule[shot.shot_id][0])
        scene.frame_set(start)
        bpy.context.view_layer.update()
        position = camera.matrix_world.translation
        cameras[str(shot.shot_id)] = (float(position.x), float(position.y),
                                      float(position.z))
    scene.frame_set(restore)
    bpy.context.view_layer.update()
    truthful = axis_state(axis, plan, initial, cameras) if axis is not None else {}
    common = sorted(set(used) & set(truthful))
    mismatched = [name for name in common if used[name] != truthful[name]]
    return {"ok": bool(common) and not mismatched,
            "shots_with_a_side": len(common),
            "mismatched": mismatched,
            "used": used,
            "camera_truth": {name: truthful[name] for name in common}}


def main() -> int:
    capture_main_thread()
    check("axis_established_and_enforced", t_axis_established_and_enforced)
    check("axis_visual_is_a_guide", t_axis_visual_is_a_guide)
    check("composition_rewards_good_framing", t_composition_rewards_good_framing)
    check("occlusion_is_detected", t_occlusion_is_detected)
    check("thirty_degree_rule", t_thirty_degree_rule)
    check("a_dialogue_line_survives_reverse_singles",
          t_a_dialogue_line_survives_reverse_singles)
    check("the_camera_aims_where_the_character_is_now",
          t_the_camera_aims_where_the_character_is_now)
    check("r001_reports_an_unbridged_axis_rebuild",
          t_r001_reports_an_unbridged_axis_rebuild)
    check("r003_is_scoped_to_the_shot_being_audited",
          t_r003_is_scoped_to_the_shot_being_audited)
    check("lead_room_shifts_single_subject_shots_only",
          t_lead_room_shifts_single_subject_shots_only)
    check("declared_composition_overrides_the_default_aim",
          t_declared_composition_overrides_the_default_aim)
    check("the_builder_state_machine_is_camera_truthful",
          t_the_builder_state_machine_is_camera_truthful)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
