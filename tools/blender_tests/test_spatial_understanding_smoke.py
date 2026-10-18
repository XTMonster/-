"""Ticket 07：空间理解/设计快照的 Blender 端到端冒烟。

完整链：离线计划 fixture -> build_scene（真实 Blender 白模）-> 设计快照
（brief+plan -> 空间设计 JSON）-> sample_spatial（回读 rotation/motion/gaze）
-> 观测快照 -> 设计 vs 实测偏差报告 -> 修复/计划提示渲染，四类产物全部
非空落盘。Blender 内不做 jsonschema 校验（生产侧零运行时依赖），产物由
本机测试链校验。

运行：blender --background --factory-startup --python tools/blender_tests/test_spatial_understanding_smoke.py -- --out <dir>
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


def run_smoke(out_dir: Path) -> dict:
    from block_director.contracts.plan import Plan
    from block_director.layer3_engine.frustum_sampler import sample_spatial
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.cinema.spatial_design import (
        build_design_snapshot,
        render_design_summary,
    )
    from block_director.cinema.spatial_observation import (
        build_observation_snapshot,
    )
    from block_director.cinema.spatial_diff import (
        build_diff_report,
        render_diff_block,
    )

    fixture = ROOT / "fixtures" / "mock_llm_responses" / "plan_simple.json"
    plan = Plan.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
    build_scene(plan, clear_scene=True)
    context = get_context()
    if context is None or not context.characters:
        raise RuntimeError("build_scene 后 SceneContext 为空或没有角色")

    shot = plan.shots[0]
    shot_id = shot.shot_id
    start, end = context.schedule[shot_id]

    # 角色站位（设计层 plan_intent 源：场景实际建好的角色位置）
    cast_positions = {}
    for character_id, character in context.characters.items():
        if getattr(character, "root", None) is not None:
            cast_positions[character_id] = tuple(
                float(v) for v in character.root.matrix_world.translation)
        else:
            cast_positions[character_id] = tuple(
                float(v) for v in character.matrix_world.translation)

    design = build_design_snapshot(
        brief={"environment": []},
        plan=plan.to_dict(),
        cast_positions=cast_positions,
        scene_id="smoke")

    frames = sorted({start, (start + end) // 2, end})
    spatial_frames = sample_spatial(shot_id, frames)
    if not spatial_frames:
        raise RuntimeError("sample_spatial 返回空（没有采样帧）")
    observation = build_observation_snapshot(spatial_frames)
    diff = build_diff_report(design, observation)
    design_text = render_design_summary(design, max_chars=2000)
    diff_text = render_diff_block(diff, max_chars=2000)

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "design": out_dir / "spatial_design_snapshot.json",
        "observation": out_dir / "spatial_observation_snapshot.json",
        "diff": out_dir / "spatial_diff_report.json",
        "prompts": out_dir / "spatial_prompt_blocks.txt",
    }
    paths["design"].write_text(
        json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["observation"].write_text(
        json.dumps(observation, ensure_ascii=False, indent=2),
        encoding="utf-8")
    paths["diff"].write_text(
        json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["prompts"].write_text(
        design_text + "\n\n=====\n\n" + diff_text, encoding="utf-8")

    return {
        "ok": bool(design_text) and bool(diff_text),
        "shot_id": shot_id,
        "frames": frames,
        "character_count": len(context.characters),
        "element_count": len(spatial_frames[0].elements),
        "camera_rotation_present": any(
            frame.camera.rotation is not None for frame in spatial_frames),
        "character_gaze_present": any(
            element.gaze is not None and element.gaze.get("direction")
            for frame in spatial_frames for element in frame.elements),
        "outputs": {key: str(path) for key, path in paths.items()},
    }


def main() -> int:
    #: Blender 会把整条命令行塞进 sys.argv（含 --background 等），argparse
    #: 不可靠；只取 ``--`` 分隔符之后的参数，缺省用固定 evidence 目录。
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261018-spatial-understanding-smoke"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["spatial_understanding_smoke"] = run_smoke(out_dir)
    except Exception as exc:  # noqa: BLE001 - 冒烟脚本归一为结果记录
        RESULTS["spatial_understanding_smoke"] = {
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
