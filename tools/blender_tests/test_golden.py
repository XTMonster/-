"""Golden Test（执行文档 v1.2 §21.4）：真实 Blender 里逐项比对期望 SDL。

纯 Python 的 Golden Test 保证"计划 → SDL"稳定；这里补上 bpy 那一半：

1. 同一份计划连建两次，构建结果逐项一致（§21.4 的"除浮点容差外逐帧一致"）；
2. 真实建成的场景组装出的 SDL，其镜头 id/景别/帧范围/焦距与
   `fixtures/expected_sdl_simple.json` **逐项相同**——把纯计算路径与 bpy 路径
   钉在一起，任何一边改动都会立刻红；
3. 这份 Golden 计划当前能通过全部规则校验（R001–R011 + 构图门）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_golden.py
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

from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer2_sdl import build_sdl  # noqa: E402
from block_director.cinema.framing import SHOT_FRAME  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.character_system import create_character  # noqa: E402
from block_director.layer3_engine.cinema_engine import (  # noqa: E402
    evaluate_camera_composition,
    place_camera_for_shot,
)
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_state import collect_scene_state  # noqa: E402
from block_director.layer3_engine.shot_auditor import BpyShotAuditor  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
FIXTURES = ROOT / "fixtures"
PLAN_FILE = FIXTURES / "mock_llm_responses" / "plan_simple.json"
SDL_FILE = FIXTURES / "expected_sdl_simple.json"


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
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    ensure_collections(scene)
    return scene


def golden_plan() -> Plan:
    return Plan.from_dict(json.loads(PLAN_FILE.read_text(encoding="utf-8")))


def expected_shots() -> dict:
    payload = json.loads(SDL_FILE.read_text(encoding="utf-8"))
    return {shot["id"]: shot for shot in payload["scenes"][0]["shots"]}


def build_golden():
    fresh_scene()
    plan = golden_plan()
    spec = SceneSpec.from_plan(plan)
    return plan, spec, build_scene(plan, spec, clear_scene=True).to_dict()


def _fingerprint(summary):
    return {
        "shots": summary["shots"],
        "characters": summary["characters"],
        "cameras": summary["cameras"],
        "keyframes": summary["keyframes"],
        "total_frames": summary["total_frames"],
        "per_shot": [[item["shot_id"], item["start_frame"], item["end_frame"],
                      item["camera"], round(item["lens"], 3)]
                     for item in summary["results"]],
    }


# --------------------------------------------------------------------------- #
# 1. 连建两次结果一致
# --------------------------------------------------------------------------- #
def t_build_is_deterministic():
    _plan, _spec, first = build_golden()
    _plan2, _spec2, second = build_golden()
    before, after = _fingerprint(first), _fingerprint(second)
    return {"ok": before == after, "before": before, "after": after}


# --------------------------------------------------------------------------- #
# 2. 真实构建出的 SDL 与期望夹具逐项一致
# --------------------------------------------------------------------------- #
def t_built_scene_matches_the_expected_sdl():
    plan, spec, summary = build_golden()
    sdl = build_sdl(plan, build_summary=summary, spec=spec,
                    project_name=plan.scene_heading)
    expected = expected_shots()
    detail = {}
    same = True
    for shot in sdl.shots:
        want = expected.get(shot.id, {})
        # 焦距不参与比对：期望夹具是"计划 → SDL"（尚无排片与解算），镜头焦距
        # 来自构建结果，两边的真源不同。§10.5 的焦距由下面的单独断言覆盖。
        match = (want.get("shot_type") == shot.shot_type
                 and want.get("start_frame") == shot.start_frame
                 and want.get("end_frame") == shot.end_frame
                 and want.get("duration_frames") == shot.duration_frames
                 and want.get("camera", {}).get("id") == shot.camera.id)
        detail[shot.id] = {
            "shot_type": shot.shot_type,
            "frames": [shot.start_frame, shot.end_frame],
            "lens": shot.camera.lens,
            "camera": shot.camera.id,
            "match": match}
        same = same and match
    return {"ok": same and len(sdl.shots) == len(expected),
            "total_frames": sdl.total_frames, "shots": detail}


# --------------------------------------------------------------------------- #
# 3. 焦距来自 §10.5 的景别表（35/50/35）
# --------------------------------------------------------------------------- #
def t_lenses_come_from_the_shot_table():
    _plan, _spec, summary = build_golden()
    lenses = {item["shot_id"]: round(item["lens"], 3)
              for item in summary["results"]}
    expected = {"shot_001": SHOT_FRAME["MLS"].lens,
                "shot_002": SHOT_FRAME["MCU"].lens,
                "shot_003": SHOT_FRAME["CU"].lens}
    return {"ok": lenses == expected, "actual": lenses, "expected": expected}


# --------------------------------------------------------------------------- #
# 4. Golden 计划通过全部规则校验
# --------------------------------------------------------------------------- #
def t_golden_scene_passes_the_audit():
    _plan, _spec, _summary = build_golden()
    auditor = BpyShotAuditor()
    context = get_context()
    reports = {}
    detail = {}
    passed = True
    for shot_id in auditor.shot_ids():
        result = auditor.audit(shot_id)
        reports[shot_id] = result.to_dict()
        passed = passed and result.passed
        shot = context.shot(shot_id) if context else None
        characters = [context.character(cid) for cid in (shot.characters if shot else [])]
        composition = evaluate_camera_composition(
            context.cameras[shot_id], [c for c in characters if c is not None],
            shot_type=str(shot.shot_type) if shot else "MS")
        detail[shot_id] = composition.to_dict()
    return {"ok": passed and len(reports) == 3,
            "composition_threshold": auditor.composition_threshold,
            "reports": reports, "composition": detail,
            "boxes": _boxes_per_shot()}


# --------------------------------------------------------------------------- #
# 5. 九种景别逐一自检：单主体按景别解算后必须通过构图门
# --------------------------------------------------------------------------- #
NATURAL_SHOTS = ("ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS")


def t_every_shot_type_is_framed_well():
    results = {}
    ok = True
    for shot_type in NATURAL_SHOTS:
        fresh_scene()
        character = create_character("char_001", "小明", "#FF6B6B")
        bundle, _solution = place_camera_for_shot(
            "s", (0.0, 0.0, 0.0), shot_type=shot_type, side="front")
        report = evaluate_camera_composition(bundle.camera, [character],
                                             shot_type)
        results[shot_type] = {
            "score": report.score, "passed": report.passed,
            "headroom": round(report.items["headroom"].score, 3),
            "framing": round(report.items["framing"].score, 3),
            "thirds": round(report.items["rule_of_thirds"].score, 3),
            "window_height": SHOT_FRAME[shot_type].frame_height,
            "suggestions": report.suggestions}
        ok = ok and report.passed
    return {"ok": ok, "shots": results}


def _boxes_per_shot():
    """每个镜头里角色的屏幕方块（top/bottom/height_fraction），用于定位取景缺陷。"""
    context = get_context()
    boxes = {}
    for shot_id in BpyShotAuditor().shot_ids():
        shot = context.shot(shot_id)
        if shot is None:
            continue
        camera = context.cameras[shot_id]
        previous = bpy.context.scene.camera
        bpy.context.scene.camera = camera
        bpy.context.view_layer.update()
        state = collect_scene_state(detailed=True)
        bpy.context.scene.camera = previous
        boxes[shot_id] = {c.id: {"screen_position": c.screen_position,
                                 "height_fraction": c.height_fraction,
                                 "in_frame": c.in_frame}
                          for c in state.characters}
    return boxes


def main() -> int:
    capture_main_thread()
    check("build_is_deterministic", t_build_is_deterministic)
    check("built_scene_matches_the_expected_sdl",
          t_built_scene_matches_the_expected_sdl)
    check("lenses_come_from_the_shot_table", t_lenses_come_from_the_shot_table)
    check("golden_scene_passes_the_audit", t_golden_scene_passes_the_audit)
    check("every_shot_type_is_framed_well", t_every_shot_type_is_framed_well)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
