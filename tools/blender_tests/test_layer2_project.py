"""Layer 2/9 集成测试：SDL 保存 → 加载 → 重建的保真度（§5 / §14）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_layer2_project.py
"""

from __future__ import annotations

import json
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
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.contracts.sdl import SDL_VERSION  # noqa: E402
from block_director.layer2_sdl import (  # noqa: E402
    build_sdl,
    sdl_to_plan,
    sdl_to_spec,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer9_persistence import (  # noqa: E402
    load_project,
    project_file,
    save_project,
)
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    return scene


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _first_pass():
    """建第一次场景，返回 (plan, spec, summary, sdl)。"""
    fresh_scene()
    plan = two_shot_plan()
    spec = SceneSpec.from_plan(plan)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()
    return plan, spec, summary, build_sdl(plan, build_summary=summary,
                                          spec=spec, project_name="咖啡馆")


# --------------------------------------------------------------------------- #
# 1. 保存 → 加载 → 重建，时间轴与机位完全一致
# --------------------------------------------------------------------------- #
def t_save_load_rebuild_keeps_the_timeline():
    _plan, _spec, summary, sdl = _first_pass()
    tmp = tempfile.mkdtemp(prefix="bd_l2_")
    save_project(tmp, sdl)

    loaded = load_project(tmp)
    assert loaded.ok, [item.to_dict() for item in loaded.findings]

    fresh_scene()
    rebuilt = build_scene(sdl_to_plan(loaded.sdl), sdl_to_spec(loaded.sdl),
                          clear_scene=True).to_dict()

    original = {item["shot_id"]: item for item in summary["results"]}
    again = {item["shot_id"]: item for item in rebuilt["results"]}
    same = True
    detail = {}
    for shot_id, first in original.items():
        second = again.get(shot_id, {})
        match = (first["start_frame"] == second.get("start_frame")
                 and first["end_frame"] == second.get("end_frame")
                 and first["camera"] == second.get("camera")
                 and abs(first["lens"] - second.get("lens", 0)) < 1e-6)
        detail[shot_id] = {"before": [first["start_frame"], first["end_frame"]],
                           "after": [second.get("start_frame"),
                                     second.get("end_frame")],
                           "match": match}
        same = same and match
    return {"ok": same and rebuilt["total_frames"] == summary["total_frames"],
            "shots": detail, "total_frames": rebuilt["total_frames"],
            "notes": loaded.notes}


# --------------------------------------------------------------------------- #
# 2. SDL 落盘后再读回来逐字段一致
# --------------------------------------------------------------------------- #
def t_sdl_survives_the_file_round_trip():
    _plan, _spec, _summary, sdl = _first_pass()
    tmp = tempfile.mkdtemp(prefix="bd_l2_")
    save_project(tmp, sdl)
    loaded = load_project(tmp)
    before = sdl.to_dict()
    after = loaded.sdl.to_dict()
    # saved_at 是文件级元数据，不属于 SDL 本身
    assert "saved_at" in json.loads(project_file(tmp).read_text(encoding="utf-8"))
    return {"ok": before == after, "shots": len(loaded.sdl.shots),
            "characters": [m.id for m in loaded.sdl.characters]}


# --------------------------------------------------------------------------- #
# 3. 旧版本项目能加载、能迁移、也能重建
# --------------------------------------------------------------------------- #
def t_legacy_project_migrates_and_rebuilds():
    tmp = tempfile.mkdtemp(prefix="bd_l2legacy_")
    legacy = {"name": "旧项目", "scenes": [{
        "heading": "INT. 咖啡馆 - 日",
        "environment": {"ground_size": [30.0, 30.0], "lighting": "clay_studio"},
        "shots": [{"id": "shot_001", "shot_type": "MS", "duration_frames": 48,
                   "characters": ["char_001"]}]}]}
    project_file(tmp).write_text(json.dumps(legacy), encoding="utf-8")

    loaded = load_project(tmp)
    assert loaded.ok, [item.to_dict() for item in loaded.findings]
    fresh_scene()
    rebuilt = build_scene(sdl_to_plan(loaded.sdl), sdl_to_spec(loaded.sdl),
                          clear_scene=True).to_dict()
    return {"ok": (loaded.sdl.version == SDL_VERSION and any("迁移" in note for note in loaded.notes)
                   and rebuilt["shots"] == 1
                   and rebuilt["results"][0]["start_frame"] == 1),
            "notes": loaded.notes, "result": rebuilt["results"][0]}


# --------------------------------------------------------------------------- #
# 4. 坏项目被拒绝，而不是建出一个半成品
# --------------------------------------------------------------------------- #
def t_invalid_project_is_refused():
    tmp = tempfile.mkdtemp(prefix="bd_l2bad_")
    payload = {"version": "1.2", "fps": 24, "characters": [],
               "scenes": [{"id": "scene_001", "heading": "INT. x - 日",
                           "shots": [{"id": "shot_001", "shot_type": "MS",
                                      "duration_frames": 48,
                                      "characters": ["ghost"]}]}]}
    project_file(tmp).write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_project(tmp)
    return {"ok": not loaded.ok
            and any(item.rule == "S2" for item in loaded.findings),
            "errors": [item.to_dict() for item in loaded.findings
                       if item.is_error]}


def _placements():
    """场景里每个角色根节点的世界 x/y（按 id）。"""
    context = get_context()
    out = {}
    for cid, character in (getattr(context, "characters", {}) or {}).items():
        root = getattr(character, "root", None)
        if root is not None:
            out[cid] = (float(root.location.x), float(root.location.y))
    return out


# --------------------------------------------------------------------------- #
# 5. 摆位不因"同层另一个动作只写了别的通道"而丢（场景层不变量）
# --------------------------------------------------------------------------- #
def t_a_base_action_keeps_the_placement():
    """一个只写单通道的同层动作，不得把角色的**摆位**从基线上抹掉。

    背景（2026-10-03 长剧本真跑）：``motion/model.py::compose`` 曾经把 base 层
    的状态**整份替换**成"本帧算出来的通道集合"。``turn_body`` 只写
    ``root.rotation_z``，于是 base 层的 ``root.location`` 从层状态里消失；
    此后 ``sit``/``stand``/``walk_to`` 冻结接管时基线里没有摆位，
    ``baseline = base.get(channel, 0)`` 取到 0 —— **角色被瞬移到世界原点**，
    两人重叠、构图整片判红（occlusion 42/64 镜失败）。

    这条判据守的是**场景层**的不变量（"坐着的那位还在他被摆下的地方"）。
    镜数 / 帧数 / 相机名的对拍**抓不到它**——长跑的重建检查当时就是绿的；
    纯层用例在 ``tests/test_motion_model.py``，这里钉住它真的落到了场景里。
    """
    fresh_scene()
    plan = Plan(shots=[
        ShotPlan.from_dict({
            "shot_id": "shot_001", "order": 1, "intent": "转身",
            "shot_type": "MLS", "duration_frames": 48,
            "characters": ["char_001", "char_002"],
            "actions": [{"character_id": "char_002",
                         "action_type": "turn_body",
                         "start_frame": 1, "end_frame": 24,
                         "params": {"angle_deg": 45.0}}],
        }),
        ShotPlan.from_dict({
            "shot_id": "shot_002", "order": 2, "intent": "坐下",
            "shot_type": "MCU", "duration_frames": 72,
            "characters": ["char_002"],
            "actions": [{"character_id": "char_002", "action_type": "sit",
                         "start_frame": 1, "end_frame": 48,
                         "params": {"drop": 0.2}}],
        }),
    ], scene_heading="INT. 咖啡馆 - 日")
    spec = SceneSpec.from_plan(plan)
    build_scene(plan, spec, clear_scene=True)
    bpy.context.scene.frame_set(80)          # 全局第 80 帧 = 第二镜坐下中段
    placed = _placements()
    expected = {member.id: (float(member.initial_location[0]),
                            float(member.initial_location[1]))
                for member in spec.cast}
    drift = {cid: {"expected": expected[cid], "actual": placed.get(cid)}
             for cid in expected
             if cid in placed
             and (abs(placed[cid][0] - expected[cid][0]) > 1e-3
                  or abs(placed[cid][1] - expected[cid][1]) > 1e-3)}
    return {"ok": not drift, "expected": expected, "placed": placed,
            "drift": drift}


def main() -> int:
    capture_main_thread()
    check("save_load_rebuild_keeps_the_timeline",
          t_save_load_rebuild_keeps_the_timeline)
    check("sdl_survives_the_file_round_trip", t_sdl_survives_the_file_round_trip)
    check("legacy_project_migrates_and_rebuilds",
          t_legacy_project_migrates_and_rebuilds)
    check("invalid_project_is_refused", t_invalid_project_is_refused)
    check("a_base_action_keeps_the_placement",
          t_a_base_action_keeps_the_placement)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
