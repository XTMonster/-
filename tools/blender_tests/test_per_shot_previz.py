"""方案 B 逐镜预演（§3.6.3）的 bpy 探针。

判据三条（都不从被测实现借通道）：

1. ``prepare_scene`` 只建场景与元素：角色在、相机数 0、无剪切标记、
   无动作关键帧；
2. ``rebuild_shot`` 只动当前镜：其他镜的相机矩阵逐字节不变、该镜
   相机/标记被替换；
3. 轴传递：同一工程「整场 build」与「prepare + 逐镜 rebuild」两趟，
   对应镜头的相机 ``matrix_world`` 差 < 1e-4（逐镜重建不丢轴）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_per_shot_previz.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from _fixtures import three_shot_plan_with_empty, two_shot_plan  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_builder import (  # noqa: E402
    BpySceneBuilder,
    build_scene,
    prepare_scene,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    scene.render.resolution_percentage = 100
    ensure_collections(scene)
    return scene


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _cameras():
    return [o for o in bpy.data.objects if o.type == "CAMERA"]


def _matrix(obj):
    return tuple(round(v, 5) for v in obj.matrix_world.translation) + \
           tuple(round(v, 5) for v in obj.matrix_world.to_euler())


def t_prepare_scene_is_static_only():
    fresh_scene()
    builder = BpySceneBuilder()
    summary = builder.prepare_scene(two_shot_plan())
    cameras = _cameras()
    markers = list(bpy.context.scene.timeline_markers)
    # 角色网格（BD_Char_*）：2 个角色各 7 个部件 = 至少 14 个对象
    characters = [o for o in bpy.data.objects if o.name.startswith("BD_Char_")]
    ok = (summary["characters"] == 2 and summary["cameras"] == 0
          and len(cameras) == 0 and len(markers) == 0
          and len(characters) >= 14)
    return {"ok": ok, "summary": summary,
            "cameras": len(cameras), "markers": len(markers),
            "character_objects": len(characters)}


def t_rebuild_shot_only_touches_current_shot():
    fresh_scene()
    builder = BpySceneBuilder()
    builder.prepare_scene(two_shot_plan())
    regen = builder.rebuild_shot("shot_001")
    cameras = _cameras()
    # prepare 后只有重建的那一镜有相机；重建第二镜前，第一镜相机不动
    first = next((o for o in cameras if o.name == "BD_Cam_shot_001"), None)
    matrix_before = _matrix(first) if first else None
    regen2 = builder.rebuild_shot("shot_002")
    cameras2 = _cameras()
    first2 = next((o for o in cameras2 if o.name == "BD_Cam_shot_001"), None)
    matrix_after = _matrix(first2) if first2 else None
    markers = [m.name for m in bpy.context.scene.timeline_markers]
    ok = (regen["ok"] and regen2["ok"]
          and matrix_before is not None and matrix_before == matrix_after
          and len(cameras2) == 2 and sorted(markers) == ["BD_Cut_shot_001",
                                                        "BD_Cut_shot_002"])
    return {"ok": ok, "shot1_before": matrix_before,
            "shot1_after": matrix_after,
            "cameras": len(cameras2), "markers": sorted(markers)}


def t_axis_passed_to_rebuild_matches_full_build():
    fresh_scene()
    full = build_scene(two_shot_plan())
    full_shots = {item.shot_id: item for item in full.results}
    full_matrix = {}
    for shot_id in ("shot_001", "shot_002"):
        cam = bpy.data.objects.get(f"BD_Cam_{shot_id}")
        full_matrix[shot_id] = _matrix(cam)

    fresh_scene()
    builder = BpySceneBuilder()
    builder.prepare_scene(two_shot_plan())
    builder.rebuild_shot("shot_001")
    builder.rebuild_shot("shot_002")
    per_shot_matrix = {}
    for shot_id in ("shot_001", "shot_002"):
        cam = bpy.data.objects.get(f"BD_Cam_{shot_id}")
        per_shot_matrix[shot_id] = _matrix(cam)

    deltas = {shot_id: max(abs(a - b) for a, b in
                           zip(full_matrix[shot_id], per_shot_matrix[shot_id]))
              for shot_id in ("shot_001", "shot_002")}
    ok = all(delta < 1e-4 for delta in deltas.values())
    return {"ok": ok, "full": full_matrix, "per_shot": per_shot_matrix,
            "deltas": deltas,
            "full_lens": {sid: round(full_shots[sid].lens, 3)
                          for sid in ("shot_001", "shot_002")}}


def t_rebuild_result_shape_matches_whole_build_serialization():
    """逐镜 results 必须与整场 ``ShotBuildResult.to_dict()`` 同构。

    回归：replay 探针 ``replay_rebuilds_the_same_timeline`` 曾红——逐镜
    rebuild 的返回把机位取整到 4 位、lens 到 3 位，且缺
    ``shot_type/camera_target/characters/axis_*``，与整场序列化形状漂移。
    这里的判据 = 单一真源（``ShotBuildResult.to_dict`` 的键与精度），
    不降级；机位 3 位 / lens 2 位 / 全字段必须与整场一致。
    """
    fresh_scene()
    full = build_scene(two_shot_plan())
    full_dict = {item.shot_id: item.to_dict() for item in full.results}

    fresh_scene()
    builder = BpySceneBuilder()
    builder.prepare_scene(two_shot_plan())
    regen = builder.rebuild_shot("shot_001")

    canonical = full_dict["shot_001"]
    missing = [key for key in canonical if key not in regen]
    same_position = (
        [round(v, 3) for v in regen.get("camera_position", [])]
        == canonical["camera_position"])
    same_lens = round(float(regen.get("lens") or 0.0), 2) == canonical["lens"]
    same_characters = list(regen.get("characters") or []) == canonical["characters"]
    ok = (regen["ok"] and not missing and same_position and same_lens
          and same_characters and regen.get("shot_type") == canonical["shot_type"])
    return {"ok": ok, "missing": missing, "regen": regen,
            "canonical": canonical}


def t_two_shot_anchor_semantics_match_full_build():
    """双人 MCU 锚点逐镜：两趟 camera_target 一致且锚点语义正确。

    六视角评审 §4 缺口 2（SPEC_d1_merge_pre_tests_20261017 任务 B）：
    two_shot_plan 是 MLS 双人（shot_001，char_001+char_002）→ MCU 单人
    （shot_002，char_002）。断言：

    * 「整场 build_scene」与「prepare_scene + 逐镜 rebuild_shot」两趟的
      ``camera_target`` / ``camera_position`` 一致（差 < 1e-4，沿用
      ``t_axis_passed_to_rebuild_matches_full_build`` 的判据风格）；
    * 组中心锚点语义：shot_001（MLS 双人，有轴）target 落在两角色
      root 连线的中点上（双人组框，无视线留白偏移）；
    * 焦点主体语义：shot_002（MCU 单人）target 更贴近焦点主体
      char_002 而不是另一人 char_001（单人镜质心 = 焦点主体，带
      lead_room 横移所以不断言精确重合，只断言"朝 char_002 一侧"）。
    """
    fresh_scene()
    full = build_scene(two_shot_plan())
    full_target = {item.shot_id: tuple(item.camera_target)
                   for item in full.results}
    full_position = {item.shot_id: tuple(item.camera_position)
                     for item in full.results}

    fresh_scene()
    builder = BpySceneBuilder()
    builder.prepare_scene(two_shot_plan())
    regen_a = builder.rebuild_shot("shot_001")
    regen_b = builder.rebuild_shot("shot_002")
    per_shot_target = {"shot_001": tuple(regen_a["camera_target"]),
                       "shot_002": tuple(regen_b["camera_target"])}

    #: 角色 root 只在 per-shot 场景里取——整场那趟的对象在 fresh_scene()
    #: 时已被销毁，跨趟保留引用会踩 StructRNA removed（实测）。两趟的计划
    #: 相同、站位由同一 SceneSpec.from_plan 解出，取这一趟即可。
    char_a = bpy.data.objects.get("BD_Char_char_001_Root")
    char_b = bpy.data.objects.get("BD_Char_char_002_Root")
    if char_a is None or char_b is None:
        return {"ok": False, "error": "角色 root 不存在",
                "objects": [o.name for o in bpy.data.objects
                            if o.name.startswith("BD_Char_")]}
    pair_mid = tuple(
        (float(char_a.matrix_world.translation[i])
         + float(char_b.matrix_world.translation[i])) / 2.0
        for i in range(3))

    #: 整场 build 的 camera_target 是全精度（solution.target），逐镜 rebuild
    #: 的结果经 ShotBuildResult.to_dict round 3（交付口径，与整场序列化同渠）。
    #: 因此把整场值也 round 3 再逐字节比较——这比"差 < 1e-4"更强且是**同一
    #: 交付形状**，不是放宽。
    def round3(value):
        return tuple(round(float(item), 3) for item in value)

    target_deltas = {shot_id: max(
        abs(round3(full_target[shot_id])[i]
            - per_shot_target[shot_id][i])
        for i in range(3))
        for shot_id in ("shot_001", "shot_002")}
    same_in_both = all(delta == 0.0 for delta in target_deltas.values())

    #: 双人组框无 lead_room 偏移 ⇒ target 的 x/y 应落在两人 root 连线中点
    #: 附近。z 是取景高度（对准头部/身体），与 root 的 z 不同（实测 0.62 vs
    #: −0.10，属取景语义不是锚点漂移），所以只比水平分量。
    group_anchor_delta = max(
        abs(round3(per_shot_target["shot_001"])[i] - round(pair_mid[i], 3))
        for i in range(2))
    #: MCU 单人的 target 应朝向焦点主体 char_002 一侧（带 lead_room 横移）。
    target_b = per_shot_target["shot_002"]
    d_b = sum((target_b[i] - float(char_b.matrix_world.translation[i])) ** 2
              for i in range(2))
    d_a = sum((target_b[i] - float(char_a.matrix_world.translation[i])) ** 2
              for i in range(2))
    ok = (regen_a["ok"] and regen_b["ok"] and same_in_both
          and group_anchor_delta == 0.0            # 组中心锚点语义（水平）
          and d_b < d_a)                            # 焦点主体语义
    return {"ok": ok, "target_deltas": target_deltas,
            "full_target": {sid: round3(v)
                            for sid, v in full_target.items()},
            "per_shot_target": {sid: list(v)
                                for sid, v in per_shot_target.items()},
            "pair_mid": list(pair_mid),
            "group_anchor_delta": group_anchor_delta,
            "focus_distances": {"char_001": round(d_a, 6),
                                "char_002": round(d_b, 6)}}


def t_empty_shot_rebuild_is_ok_and_shape_matches():
    """空镜（无角色）在逐镜路径：建相机、无动作、结果形状与整场同构。

    D1 交接 §3b 的未覆盖项：空镜走"建相机无动作 → audit 空镜豁免"，
    per-shot 探针此前没有空镜用例。这里验证 ``rebuild_shot`` 对
    ``characters=[]`` 的镜头：

    * ``ok=True`` 且 ``motions=0``、``characters=[]``；
    * 相机与剪切标记照常落地（``BD_Cam_shot_003`` / ``BD_Cut_shot_003``）；
    * 结果键与整场 ``ShotBuildResult.to_dict`` 同构（交付序列化同一渠）；
    * 重建空镜不碰已有镜头（shot_001 相机矩阵逐字节不变）。
    """
    plan = three_shot_plan_with_empty()

    fresh_scene()
    full = build_scene(plan)
    canonical = {item.shot_id: item.to_dict() for item in full.results}

    fresh_scene()
    builder = BpySceneBuilder()
    builder.prepare_scene(plan)
    builder.rebuild_shot("shot_001")
    before = _matrix(bpy.data.objects["BD_Cam_shot_001"])
    regen = builder.rebuild_shot("shot_003")

    cameras = _cameras()
    cam_003 = next((o for o in cameras if o.name == "BD_Cam_shot_003"), None)
    markers = [m.name for m in bpy.context.scene.timeline_markers]
    after = _matrix(bpy.data.objects["BD_Cam_shot_001"])

    canonical_003 = canonical["shot_003"]
    missing = [key for key in canonical_003 if key not in regen]
    ok = (regen["ok"] and regen["motions"] == 0
          and regen["characters"] == []
          and cam_003 is not None
          and "BD_Cut_shot_003" in markers
          and not missing
          and before == after)
    return {"ok": ok, "regen": regen, "canonical_missing": missing,
            "cameras": len(cameras), "markers": sorted(markers),
            "shot1_matrix_unchanged": (before == after)}


def main() -> int:
    capture_main_thread()
    check("prepare_scene_is_static_only", t_prepare_scene_is_static_only)
    check("rebuild_shot_only_touches_current_shot",
          t_rebuild_shot_only_touches_current_shot)
    check("axis_passed_to_rebuild_matches_full_build",
          t_axis_passed_to_rebuild_matches_full_build)
    check("rebuild_result_shape_matches_whole_build_serialization",
          t_rebuild_result_shape_matches_whole_build_serialization)
    check("two_shot_anchor_semantics_match_full_build",
          t_two_shot_anchor_semantics_match_full_build)
    check("empty_shot_rebuild_is_ok_and_shape_matches",
          t_empty_shot_rebuild_is_ok_and_shape_matches)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
