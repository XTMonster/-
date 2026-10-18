"""Ticket 06：Blockout 序列回放一致性审查 的 Blender 端到端冒烟。

链：manifest -> 体块建场景（bpy）-> 序列回放（首/中/末帧时间线评估）->
五维一致性审查报告 -> 输出映射表 +（可选）逐镜参考视频拼接。断言：五维
结论齐全、报告版本化、映射表与 shot_table 的 downstream_map 一一对应、
回放逐镜无崩溃（相机实际位置可读）。全部结论落 BD_TEST_RESULT JSON。

运行：
blender --background --factory-startup --python tools/blender_tests/test_blockout_sequence_smoke.py -- --out <dir> [--render-video]
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _design() -> dict:
    """两镜双人对话：shot_001 正面、shot_002 越轴（故意制造 finding）。"""
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "dock_market",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
            {"name": "伊恩", "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [0.0, 5.0, 1.6],
             "target": [0.0, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
            #: 越轴机位：相机从 y=+5 移到 y=-5（相对 A→B 侧别翻转）
            {"shot_id": "shot_002", "position": [0.0, -5.0, 1.6],
             "target": [0.0, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["T06 序列回放冒烟设计快照"],
    }


def _plan():
    from block_director.contracts.plan import Plan, ShotPlan

    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="双人对话", shot_type="MS",
            duration_frames=24, order=1, characters=["米迦尔", "伊恩"],
            camera={"side": "front", "lens": 35},
        ),
        ShotPlan(
            shot_id="shot_002", intent="越轴测试", shot_type="MS",
            duration_frames=12, order=2, characters=["米迦尔", "伊恩"],
            camera={"side": "front", "lens": 35},
        ),
    ])


def run_smoke(out_dir: Path, render_video: bool) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.cinema.blockout_sequence import (
        DIMENSIONS,
        E_BLOCKOUT_AXIS_FLIP,
        build_blockout_sequence_review,
    )
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    from block_director.layer8_delivery.blockout_sequence import (
        run_blockout_sequence_review,
    )

    manifest = build_blockout_manifest(design=_design(), plan=_plan())
    build_blockout_scene(manifest, clear_scene=True)

    checks: dict = {}
    mismatches: list = []

    result = run_blockout_sequence_review(
        manifest, out_dir, render_video=render_video)
    review = result["review"]
    mapping = result["mapping"]

    #: 1. 五维结论齐全且版本化
    checks["schema"] = review["schema_version"]
    checks["dimensions"] = review["dimensions"]
    if set(review["dimensions"]) != set(DIMENSIONS):
        mismatches.append(f"维度 {review['dimensions']} != {DIMENSIONS}")
    if not review["checks"] or len(review["checks"]) != len(DIMENSIONS):
        mismatches.append("报告 checks 缺失维度")

    #: 2. 越轴 finding 可归因到分镜与帧（shot_002）
    axis = [f for f in review["findings"]
            if f["check_id"] == E_BLOCKOUT_AXIS_FLIP]
    checks["axis_flip"] = [(f["shot_id"], f["frame"]) for f in axis]
    if not axis or axis[0]["shot_id"] != "shot_002":
        mismatches.append("越轴 finding 未归因到 shot_002")
    if review["verdict"] != "fail":
        mismatches.append("存在 error finding 但 verdict 非 fail")

    #: 3. 映射表与 shot_table 的 downstream_map 一一对应
    expected_shots = {
        str(row.get("shot_id") or ""): dict(row.get("downstream_map") or {})
        for row in (manifest.get("shot_table") or [])}
    checks["mapping_shots"] = list(mapping["shots"])
    if mapping["shots"] != expected_shots:
        mismatches.append("映射表与 shot_table 的 downstream_map 不一致")
    for shot_id in expected_shots:
        if shot_id not in mapping["shots"]:
            mismatches.append(f"映射表缺 {shot_id}")

    #: 4. 回放逐镜无崩溃、相机实际位置可读
    checks["playback_shots"] = len(result["playback"]["shots"])
    for shot in result["playback"]["shots"]:
        for state in shot["frames"]:
            if state["location"] is None:
                mismatches.append(
                    f"{shot['shot_id']} 帧 {state['frame']} 相机不可读")
                break

    #: 5. 报告与映射表落盘
    for key, path in result["outputs"].items():
        if path is not None and not Path(path).exists():
            mismatches.append(f"{key} 未落盘：{path}")

    #: 6. 纯层引用一致性：两次构建逐位一致
    first = json.dumps(
        build_blockout_sequence_review(manifest=manifest),
        ensure_ascii=False, sort_keys=True)
    second = json.dumps(
        build_blockout_sequence_review(manifest=manifest),
        ensure_ascii=False, sort_keys=True)
    checks["deterministic"] = first == second
    if first != second:
        mismatches.append("序列审查两次构建不一致")

    if render_video:
        checks["full_video"] = result["video"].get("full_path")
        checks["shot_videos"] = len(result["video"].get("shot_videos") or [])
        if not Path(result["outputs"]["full_video"]).exists():
            mismatches.append("参考视频未产出")

    checks["mismatches"] = mismatches
    checks["outputs"] = result["outputs"]
    return {"ok": not mismatches, "checks": checks,
            "outputs": result["outputs"]}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261018-blockout-sequence-smoke"
    render_video = False
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
        if item == "--render-video":
            render_video = True
    try:
        fresh_scene()
        RESULTS["blockout_sequence_smoke"] = run_smoke(
            out_dir, render_video=render_video)
    except Exception as exc:  # noqa: BLE001 - 冒烟归一为结果记录
        RESULTS["blockout_sequence_smoke"] = {
            "ok": False, "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=5),
        }

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
