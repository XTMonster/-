"""F10：镜头隔离 Blender 探针。

验证：粗排逐镜 staging 时，本镜外的角色/道具体块被临时隐藏——
1) ``_shot_isolation_objects`` 返回跨镜角色体块；
2) 隐藏后 ``_visible_fraction`` 对主体不再被跨镜角色遮挡（ray_cast 跳过
   ``hide_render`` 对象）；
3) ``render_blockout_preview`` 报告里 shot_001 无前景遮挡 finding；
4) 渲染结束后所有体块 ``hide_render`` 恢复原值；
5) 渲染中途抛异常时（monkeypatch ``_render_shot_preview``）恢复仍执行
   （try/finally 异常安全）。

运行：blender --background --factory-startup --python
tools/blender_tests/test_shot_isolation_probe.py -- --out <dir>
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
    """跨镜遮挡设计：shot_001 只声明米迦尔，伊恩（shot_002 角色）站在
    相机与米迦尔之间；无隔离时米迦尔被伊恩挡住，有隔离时可见。"""
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "dock_market",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
            {"name": "伊恩", "position": {"x": -0.9, "y": 1.6, "z": 0.0},
             "facing": [0.0, -1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            #: shot_001：正面拍米迦尔；伊恩在相机(y=5)与米迦尔(y=0)之间
            {"shot_id": "shot_001", "position": [0.0, 5.0, 1.0],
             "target": [-0.9, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
            #: shot_002：拍伊恩（仅用于声明伊恩属于其它镜）
            {"shot_id": "shot_002", "position": [0.0, 5.0, 1.0],
             "target": [-0.9, 1.6, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["F10 隔离探针设计快照"],
    }


def _plan():
    from block_director.contracts.plan import Plan, ShotPlan

    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="米迦尔单人", shot_type="MS",
            duration_frames=24, order=1, characters=["米迦尔"],
            camera={"side": "front", "lens": 35},
        ),
        ShotPlan(
            shot_id="shot_002", intent="伊恩单人", shot_type="MS",
            duration_frames=24, order=2, characters=["伊恩"],
            camera={"side": "front", "lens": 35},
        ),
    ])


def run_probe(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.cinema.blockout_report import FOREGROUND_OCCLUSION_MAX
    from block_director.contracts.plan import Plan, ShotPlan
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    from block_director.layer3_engine.world_state import (
        collect_blockout_world_state,
    )
    from block_director.layer8_delivery import blockout_preview as preview_mod
    from block_director.layer8_delivery.blockout_preview import (
        _render_shot_preview,
        _shot_isolation_objects,
        _visible_fraction,
        render_blockout_preview,
    )
    from mathutils import Vector

    manifest = build_blockout_manifest(design=_design(), plan=_plan())
    build_blockout_scene(manifest, clear_scene=True)
    scene = bpy.context.scene

    shot_001_row = next(row for row in manifest["shot_table"]
                        if row["shot_id"] == "shot_001")
    checks: dict = {}
    mismatches: list = []

    #: 1. 隔离集合包含伊恩体块、不含米迦尔
    isolated = _shot_isolation_objects(manifest, shot_001_row)
    isolated_names = [obj.name for obj in isolated]
    checks["isolated_names"] = isolated_names
    michael_obj = bpy.data.objects.get("BD_Blockout_char_米迦尔")
    ian_obj = bpy.data.objects.get("BD_Blockout_char_伊恩")
    if "BD_Blockout_char_伊恩" not in isolated_names:
        mismatches.append("隔离集合未包含跨镜角色伊恩")
    if michael_obj is None or ian_obj is None:
        mismatches.append("角色体块未建立")
    if michael_obj is not None and michael_obj.name in isolated_names:
        mismatches.append("本镜角色米迦尔被错误隔离")

    #: 2. 隐藏前：米迦尔被伊恩挡住（visible 低）；隐藏后：可见（visible 高）
    camera_obj = bpy.data.objects.get("BD_Blockout_cam_shot_001")
    scene.camera = camera_obj
    scene.frame_set(1)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera_pos = Vector(camera_obj.matrix_world.translation)
    if michael_obj is not None:
        before = _visible_fraction(scene, camera_pos, michael_obj, depsgraph)
        checks["visible_before_isolation"] = before
        #: 模拟隔离：隐藏伊恩
        ian_obj.hide_render = True
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        after = _visible_fraction(scene, camera_pos, michael_obj, depsgraph)
        checks["visible_after_isolation"] = after
        ian_obj.hide_render = False
        if not (after > before + 0.2):
            mismatches.append(
                f"隔离未提升主体可见度: before={before} after={after}")

    #: 3. render_blockout_preview 报告：shot_001 无前景遮挡 finding，
    #:    渲染后所有对象 hide_render 恢复
    result = render_blockout_preview(manifest, out_dir)
    report = result["report"]
    fg_findings = [
        f for f in report["findings"]
        if f.get("shot_id") == "shot_001"
        and f["check_id"] == "E_FOREGROUND_OCCLUSION"]
    checks["shot001_fg_findings"] = len(fg_findings)
    if fg_findings:
        mismatches.append("shot_001 仍报前景遮挡 finding")
    shot001 = [c for c in report["checks"] if c["shot_id"] == "shot_001"]
    visible = [c for c in shot001 if c["check_id"] == "occlusion"]
    if not visible or visible[0]["actual"] <= 0.5:
        mismatches.append(
            f"shot_001 可见比例 {visible[0]['actual'] if visible else '无'} 未过 0.5")
    restored = {name: bool(obj.hide_render) for name, obj in
                bpy.data.objects.items()
                if name.startswith("BD_Blockout_char_")}
    checks["hide_render_after_render"] = restored
    if any(restored.values()):
        mismatches.append("渲染结束后仍有体块 hide_render=True 未恢复")

    #: 4. 异常路径：monkeypatch _render_shot_preview 抛异常，
    #:    render_blockout_preview 必须仍恢复 hide_render（try/finally）
    def _boom(*_args, **_kwargs):
        raise RuntimeError("probe-injected render failure")

    preview_mod._render_shot_preview = _boom  # type: ignore[assignment]
    try:
        try:
            render_blockout_preview(manifest, out_dir / "boom")
            mismatches.append("注入异常未传播")
        except RuntimeError as exc:
            checks["injected_error"] = str(exc)
    finally:
        preview_mod._render_shot_preview = _render_shot_preview
    restored_boom = {name: bool(obj.hide_render) for name, obj in
                     bpy.data.objects.items()
                     if name.startswith("BD_Blockout_char_")}
    checks["hide_render_after_boom"] = restored_boom
    if any(restored_boom.values()):
        mismatches.append("异常后仍有体块 hide_render=True 未恢复")

    #: 5. 最终序列 MP4 也必须逐镜隔离。用 monkeypatch 截获每镜
    #:    render_shot_video 调用时的 hide_render 状态，不实际编码视频。
    from block_director.layer8_delivery import blockout_sequence as seq_mod
    from block_director.layer8_delivery.blockout_sequence import (
        render_blockout_sequence_video,
    )

    calls = []
    real_render = seq_mod.render_shot_video
    real_concat = seq_mod.concat_shot_clips
    try:
        def _capture_render(scene, start, end, path, **_kwargs):
            calls.append({
                "camera": scene.camera.name,
                "hidden": {
                    "米迦尔": bool(michael_obj.hide_render),
                    "伊恩": bool(ian_obj.hide_render),
                },
            })
            return f"captured_{len(calls)}.mp4", int(end) - int(start) + 1

        def _capture_concat(_scene, clips, full_path, **_kwargs):
            checks["sequence_concat_clips"] = list(clips)
            return {"path": str(full_path), "clips": list(clips)}

        seq_mod.render_shot_video = _capture_render  # type: ignore[assignment]
        seq_mod.concat_shot_clips = _capture_concat  # type: ignore[assignment]
        render_blockout_sequence_video(manifest, out_dir / "sequence")
    finally:
        seq_mod.render_shot_video = real_render  # type: ignore[assignment]
        seq_mod.concat_shot_clips = real_concat  # type: ignore[assignment]
    checks["sequence_isolation_calls"] = calls
    if len(calls) != 2:
        mismatches.append(f"序列隔离应渲染 2 镜，实际 {len(calls)}")
    else:
        first, second = calls
        if not first["hidden"]["伊恩"] or first["hidden"]["米迦尔"]:
            mismatches.append(f"shot_001 序列隔离状态错误：{first}")
        if not second["hidden"]["米迦尔"] or second["hidden"]["伊恩"]:
            mismatches.append(f"shot_002 序列隔离状态错误：{second}")
    restored_sequence = {
        name: bool(obj.hide_render)
        for name, obj in bpy.data.objects.items()
        if name.startswith("BD_Blockout_char_")
    }
    checks["hide_render_after_sequence"] = restored_sequence
    if any(restored_sequence.values()):
        mismatches.append("序列渲染结束后仍有体块 hide_render=True 未恢复")

    #: 6. 序列渲染异常也必须恢复隔离状态。
    def _sequence_boom(*_args, **_kwargs):
        raise RuntimeError("probe-injected sequence render failure")

    try:
        seq_mod.render_shot_video = _sequence_boom  # type: ignore[assignment]
        try:
            render_blockout_sequence_video(manifest, out_dir / "sequence_boom")
            mismatches.append("序列注入异常未传播")
        except RuntimeError as exc:
            checks["sequence_injected_error"] = str(exc)
    finally:
        seq_mod.render_shot_video = real_render  # type: ignore[assignment]
        seq_mod.concat_shot_clips = real_concat  # type: ignore[assignment]
    restored_sequence_boom = {
        name: bool(obj.hide_render)
        for name, obj in bpy.data.objects.items()
        if name.startswith("BD_Blockout_char_")
    }
    checks["hide_render_after_sequence_boom"] = restored_sequence_boom
    if any(restored_sequence_boom.values()):
        mismatches.append("序列异常后仍有体块 hide_render=True 未恢复")

    #: 7. 局部站位：shot_001 使用 overlay，shot_002 回到全局基准；
    #:    真实 _render_shot_preview 调用期间对象位置必须已经落场。
    fresh_scene()
    staged_design = _design()
    staged_design["shot_staging"] = {
        "shot_001": {
            "米迦尔": {
                "position": {"x": 0.45, "y": 0.2, "z": 0.0},
                "provenance": "agent_local_revision",
                "reason": "把主体移到本镜构图位",
            },
        },
    }
    staged_plan = Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="米迦尔本镜局部站位",
            shot_type="MS", duration_frames=24, order=1,
            characters=["米迦尔"],
            camera={"side": "front", "lens": 35},
        ),
        ShotPlan(
            shot_id="shot_002", intent="米迦尔回到场级连续性位置",
            shot_type="MS", duration_frames=24, order=2,
            characters=["米迦尔"],
            camera={"side": "front", "lens": 35},
        ),
    ])
    staged_manifest = build_blockout_manifest(
        design=staged_design, plan=staged_plan)
    staged_primitive = next(
        item for item in staged_manifest["primitives"]
        if item.get("kind") == "character"
        and item.get("source", {}).get("id") == "米迦尔")
    staged_height = float(staged_primitive["size"]["z"])
    build_blockout_scene(staged_manifest, clear_scene=True)
    staged_obj = bpy.data.objects["BD_Blockout_char_米迦尔"]
    staged_position = staged_primitive.get("position") or {}
    expected_global_origin = (
        float(staged_position.get("x") or 0.0),
        float(staged_position.get("y") or 0.0),
        float(staged_position.get("z") or 0.0) + staged_height / 2.0,
    )
    seen_locations = []
    real_render_shot = preview_mod._render_shot_preview

    def _capture_location(**kwargs):
        bpy.context.scene.frame_set(int(kwargs["frames"][0][1]))
        bpy.context.view_layer.update()
        seen_locations.append({
            "shot_id": kwargs["shot_id"],
            "location": tuple(staged_obj.location),
        })
        return real_render_shot(**kwargs)

    preview_mod._render_shot_preview = _capture_location  # type: ignore[assignment]
    try:
        staged_result = render_blockout_preview(
            staged_manifest, out_dir / "local_staging")
    finally:
        preview_mod._render_shot_preview = real_render_shot  # type: ignore[assignment]
    checks["local_staging_calls"] = [
        {"shot_id": row["shot_id"], "location": list(row["location"])}
        for row in seen_locations
    ]
    shot_one_call = next(
        (row for row in seen_locations if row["shot_id"] == "shot_001"),
        None)
    shot_two_call = next(
        (row for row in seen_locations if row["shot_id"] == "shot_002"),
        None)
    expected_origin_z = staged_height / 2.0
    if shot_one_call is None or any(
            abs(float(actual) - float(expected)) > 1e-6
            for actual, expected in zip(
                shot_one_call["location"], (0.45, 0.2, expected_origin_z))):
        mismatches.append(
            f"shot_001 未按局部站位渲染：{shot_one_call}")
    if shot_two_call is None or any(
            abs(float(actual) - float(expected)) > 1e-6
            for actual, expected in zip(
                shot_two_call["location"], expected_global_origin)):
        mismatches.append(
            f"shot_002 未恢复全局基准：{shot_two_call}")
    bpy.context.scene.frame_set(25)
    bpy.context.view_layer.update()
    if any(
            abs(float(actual) - float(expected)) > 1e-6
            for actual, expected in zip(
                staged_obj.location, expected_global_origin)):
        mismatches.append(
            f"逐镜站位渲染后帧 25 未回到全局基准："
            f"{tuple(staged_obj.location)}")
    checks["shot_staging_audit"] = staged_result.get("shot_staging")
    staged_world = collect_blockout_world_state(staged_manifest)
    checks["shot_staging_world"] = staged_world.get("shot_states")
    staged_sequence_calls = []

    def _capture_staged_sequence(scene, start, end, path, **_kwargs):
        scene.frame_set(int(start))
        bpy.context.view_layer.update()
        staged_sequence_calls.append({
            "camera": scene.camera.name,
            "location": tuple(staged_obj.location),
        })
        return f"staged_{len(staged_sequence_calls)}.mp4", int(end) - int(start) + 1

    def _capture_staged_concat(_scene, clips, full_path, **_kwargs):
        return {"path": str(full_path), "clips": list(clips)}

    try:
        seq_mod.render_shot_video = _capture_staged_sequence  # type: ignore[assignment]
        seq_mod.concat_shot_clips = _capture_staged_concat  # type: ignore[assignment]
        render_blockout_sequence_video(
            staged_manifest, out_dir / "local_staging_sequence")
    finally:
        seq_mod.render_shot_video = real_render  # type: ignore[assignment]
        seq_mod.concat_shot_clips = real_concat  # type: ignore[assignment]
    checks["local_staging_sequence_calls"] = [
        {"camera": row["camera"], "location": list(row["location"])}
        for row in staged_sequence_calls
    ]
    if len(staged_sequence_calls) != 2:
        mismatches.append(
            f"局部站位序列应渲染 2 镜，实际 {len(staged_sequence_calls)}")
    else:
        first, second = staged_sequence_calls
        if any(
                abs(float(actual) - float(expected)) > 1e-6
                for actual, expected in zip(
                    first["location"], (0.45, 0.2, expected_origin_z))):
            mismatches.append(f"序列 shot_001 未使用局部站位：{first}")
        if any(
                abs(float(actual) - float(expected)) > 1e-6
                for actual, expected in zip(
                    second["location"], expected_global_origin)):
            mismatches.append(f"序列 shot_002 未恢复全局基准：{second}")
    bpy.context.scene.frame_set(25)
    bpy.context.view_layer.update()
    if any(
            abs(float(actual) - float(expected)) > 1e-6
            for actual, expected in zip(
                staged_obj.location, expected_global_origin)):
        mismatches.append(
            f"局部站位序列渲染后帧 25 未回到全局基准："
            f"{tuple(staged_obj.location)}")

    def _staging_boom(**_kwargs):
        raise RuntimeError("probe-injected staged render failure")

    preview_mod._render_shot_preview = _staging_boom  # type: ignore[assignment]
    try:
        try:
            render_blockout_preview(
                staged_manifest, out_dir / "local_staging_boom")
            mismatches.append("局部站位注入异常未传播")
        except RuntimeError as exc:
            checks["local_staging_injected_error"] = str(exc)
    finally:
        preview_mod._render_shot_preview = real_render_shot  # type: ignore[assignment]
    bpy.context.scene.frame_set(25)
    bpy.context.view_layer.update()
    if any(
            abs(float(actual) - float(expected)) > 1e-6
            for actual, expected in zip(
                staged_obj.location, expected_global_origin)):
        mismatches.append(
            f"局部站位异常后帧 25 未回到全局基准："
            f"{tuple(staged_obj.location)}")

    (out_dir / "shot_isolation_probe.json").write_text(
        json.dumps({"checks": checks, "mismatches": mismatches},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": not mismatches, "checks": checks}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261020-shot-isolation-probe"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["shot_isolation_probe"] = run_probe(out_dir)
    except Exception as exc:  # noqa: BLE001
        RESULTS["shot_isolation_probe"] = {
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
    raise SystemExit(main())
