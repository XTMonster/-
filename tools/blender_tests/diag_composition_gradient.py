"""诊断探针：final16b 冻结世界各镜构图分对相机位移的真实梯度。

与 ``blockout_preview`` 同口径：重建体块场景、按 shot_table 主体集合取
体块、用 ``evaluate_composition``（expected_height=None）算构图分。对每个
composition<80 的镜，从冻结相机位朝推近/拉远/抬/降/左/右小步位移，逐点
记分。产出 JSON 供判断构图处方方向（是否推近能收敛、软处方有没有戏），
不盲改固定处方。

运行：
  blender --background --factory-startup --python
    tools/blender_tests/diag_composition_gradient.py -- --out <dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

FINAL16B = (ROOT / "docs" / "evidence"
            / "20261020-market-coin-coarse-gate-pass-final16b")


def _load_manifest() -> dict:
    path = FINAL16B / "coarse" / "blockout_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _subject_blocks(manifest: dict) -> dict:
    """manifest 主体体块 id -> 对象名（preview 同款）。"""
    blocks: dict = {}
    for primitive in manifest.get("primitives") or []:
        source = primitive.get("source") or {}
        if primitive.get("kind") in {"character", "prop"} \
                and source.get("id"):
            blocks[str(source["id"])] = f"BD_Blockout_{primitive['id']}"
    return blocks


def _project_box(scene, camera, block):
    """体块 8 角投影 NDC 包围盒（preview 同法）。"""
    from bpy_extras.object_utils import world_to_camera_view
    xs, ys = [], []
    for corner in block.bound_box:
        world = block.matrix_world @ Vector(corner)
        projected = world_to_camera_view(scene, camera, world)
        if float(projected.z) < 0.0:
            continue
        xs.append(projected.x)
        ys.append(projected.y)
    if not xs:
        return None
    from block_director.cinema.composition import SubjectBox
    return SubjectBox(
        name=block.name,
        left=min(xs), right=max(xs),
        top=max(ys), bottom=min(ys),
    )


def _composition_for_shot(manifest, camera_obj, shot_id):
    """用 preview 同款 evaluate_composition 算单人/主体构图分。"""
    from block_director.cinema.composition import (
        evaluate_composition,
    )
    scene = bpy.context.scene
    shot_table_row = next(
        (row for row in manifest.get("shot_table") or []
         if row.get("shot_id") == shot_id), {})
    subject_names = [str(name) for name in
                     ((shot_table_row.get("character_ids") or [])
                      + (shot_table_row.get("prop_ids") or []))]
    subject_blocks = _subject_blocks(manifest)
    boxes, occluded = [], {}
    for name in subject_names:
        block_name = subject_blocks.get(name)
        if not block_name:
            continue
        block = bpy.data.objects.get(block_name)
        if block is None:
            continue
        box = _project_box(scene, camera_obj, block)
        if box is None:
            continue
        boxes.append(box)
        #: 可见性按体块与相机之间是否被其它体块挡住近似（preview 用 ray_cast；
        #: 这里为梯度诊断用简单处理，不参与正式判据）
        occluded[box.name] = False
    if not boxes:
        return None
    report = evaluate_composition(boxes, occluded=occluded or None,
                                  expected_height=None)
    return report


def _body_bounds(block) -> tuple:
    """体块世界 AABB：``(low, high)``，与 composition_guide._world_bounds 同源。"""
    low = [None] * 3
    high = [None] * 3
    for corner in block.bound_box:
        point = block.matrix_world @ Vector(corner)
        for index in range(3):
            value = float(point[index])
            if low[index] is None or value < low[index]:
                low[index] = value
            if high[index] is None or value > high[index]:
                high[index] = value
    return Vector(low), Vector(high)


def _project_bounds(low, high, name):
    """世界 AABB 8 角 -> SubjectBox（composition_guide._project_bounds 同法）。"""
    from block_director.cinema.composition import SubjectBox
    from bpy_extras.object_utils import world_to_camera_view
    scene = bpy.context.scene
    xs, ys = [], []
    for ix in (low.x, high.x):
        for iy in (low.y, high.y):
            for iz in (low.z, high.z):
                projected = world_to_camera_view(scene, scene.camera,
                                                 Vector((ix, iy, iz)))
                xs.append(projected.x)
                ys.append(projected.y)
    return SubjectBox(name=name, left=min(xs), right=max(xs),
                      top=max(ys), bottom=min(ys))


def _local_primary_for_shot(manifest, shot_id) -> dict:
    """按 framing_target 构造局部主体框（与细排/ruler 同源语义）。

    * kind=prop：直接用道具体块框作主锚（道具本身就是被摄对象）；
    * kind=character + part=face：头球立方（anchor.profile 推导演出）；
    * kind=character + part=hand：手部代理立方（``anchor.hand_offset``）。
    几何推导走 ``cinema.anchor.coarse_local_bounds``（与 preview 同源，
    单一真源），不再在本探针里手写第二份数字。
    返回 ``{"name", "bounds"}``，供投影成 SubjectBox 后作 primary。
    """
    from block_director.cinema.anchor import (
        DEFAULT_PROFILE as PROFILE,
        coarse_local_bounds,
    )

    ref = json.loads(
        (FINAL16B / "coarse" / "coarse_world_baseline.json")
        .read_text(encoding="utf-8"))
    shot = next((s for s in ref.get("reference", {}).get("shots") or []
                 if str(s.get("shot_id") or "") == shot_id), None)
    ft = (shot or {}).get("framing_target")
    if not isinstance(ft, dict) or not ft.get("ref"):
        return None
    kind = str(ft.get("kind") or "character")
    ref_id = str(ft.get("ref") or "")
    part = str(ft.get("part") or "none")

    subject_blocks = _subject_blocks(manifest)
    block_name = subject_blocks.get(ref_id)
    if not block_name:
        return None
    block = bpy.data.objects.get(block_name)
    if block is None:
        return None
    low, high = _body_bounds(block)
    char_facing = [0.0, 1.0, 0.0]
    ref_data = json.loads(
        (FINAL16B / "coarse" / "coarse_world_baseline.json")
        .read_text(encoding="utf-8"))
    for char in ref_data.get("reference", {}).get("characters") or []:
        if str(char.get("name") or "") == ref_id:
            char_facing = list(char.get("facing") or [0.0, 1.0, 0.0])
            break
    bounds = coarse_local_bounds(
        kind=kind, part=part, low=low, high=high,
        facing=char_facing, profile=PROFILE)
    if bounds is None:
        return None
    label = (f"{ref_id}:{part}" if part not in {"", "none"}
             else f"{ref_id}:prop")
    return {"name": label,
            "bounds": (Vector(bounds[0]), Vector(bounds[1])),
            "block_name": block_name}


def main():
    argv = list(sys.argv)
    out_root = ROOT / "docs" / "evidence" / "20261020-final16b-grad-diag"
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out_root = Path(args[args.index("--out") + 1])
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    from block_director.layer3_engine.blockout_scene import build_blockout_scene

    manifest = _load_manifest()
    build_blockout_scene(manifest, clear_scene=True)

    report_path = FINAL16B / "coarse" / "blockout_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    compose = {
        str(c.get("shot_id") or ""): float(c.get("actual") or 0.0)
        for c in report.get("checks") or []
        if c.get("check_id") == "composition"
    }
    #: framing_target 从 reference.shots 读（计划声明）
    ref_path = FINAL16B / "coarse" / "coarse_world_baseline.json"
    baseline = json.loads(ref_path.read_text(encoding="utf-8"))
    shot_decl = {
        str(s.get("shot_id") or ""): s
        for s in baseline.get("reference", {}).get("shots") or []
    }

    scene = bpy.context.scene
    results = {}
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        cam_obj = bpy.data.objects.get(f"BD_Blockout_{camera.get('camera_id')}")
        if cam_obj is None:
            continue
        scene.camera = cam_obj
        base = cam_obj.matrix_world.translation.copy()
        entry = {
            "shot_id": shot_id,
            "base_composition": compose.get(shot_id),
            "base_position": [round(float(v), 3) for v in base],
            "samples": {},
            "local_primary": None,
        }
        #: 沿世界轴小步位移（0.1m 步长），空间尺几何求解器用
        moves = {
            "push_in_0.15": Vector((base.x, base.y - 0.15, base.z)),
            "push_in_0.30": Vector((base.x, base.y - 0.30, base.z)),
            "pull_out_0.15": Vector((base.x, base.y + 0.15, base.z)),
            "pull_out_0.30": Vector((base.x, base.y + 0.30, base.z)),
            "raise_0.10": Vector((base.x, base.y, base.z + 0.10)),
            "raise_0.20": Vector((base.x, base.y, base.z + 0.20)),
            "lower_0.10": Vector((base.x, base.y, base.z - 0.10)),
            "left_0.15": Vector((base.x - 0.15, base.y, base.z)),
            "right_0.15": Vector((base.x + 0.15, base.y, base.z)),
        }
        for label, pos in moves.items():
            cam_obj.matrix_world.translation = pos
            bpy.context.view_layer.update()
            report_comp = _composition_for_shot(manifest, cam_obj, shot_id)
            entry["samples"][label] = {
                "score": (report_comp.score if report_comp else None),
                "suggestions": list(report_comp.suggestions)
                if report_comp else [],
            }
        cam_obj.matrix_world.translation = base
        bpy.context.view_layer.update()
        #: 局部主体框语义（细排同源）评分：主锚=手/脸/道具，不拿整身当主锚
        local = _local_primary_for_shot(manifest, shot_id)
        if local is not None:
            local_box = _project_bounds(local["bounds"][0],
                                        local["bounds"][1],
                                        local["name"])
            whole_box = None
            row = next((r for r in manifest.get("shot_table") or []
                        if r.get("shot_id") == shot_id), {})
            names = [str(n) for n in
                     ((row.get("character_ids") or []) + (row.get("prop_ids") or []))]
            for name in names:
                bn = _subject_blocks(manifest).get(name)
                if not bn:
                    continue
                blk = bpy.data.objects.get(bn)
                if blk is None:
                    continue
                bbox = _project_box(scene, cam_obj, blk)
                if bbox is not None:
                    whole_box = bbox
                    break
            boxes = [whole_box, local_box] if whole_box is not None else [local_box]
            from block_director.cinema.composition import (
                evaluate_composition,
            )
            local_report = evaluate_composition(
                boxes, occluded=None, primary=local["name"],
                expected_height=1.0, headroom_applies=False)
            entry["local_primary"] = {
                "score": local_report.score,
                "primary": local["name"],
                "suggestions": list(local_report.suggestions),
            }
        results[shot_id] = entry

    (out_root / "composition_gradient.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BD_TEST_RESULT " + json.dumps({
        "ok": True, "out": str(out_root), "shots": {
            sid: {"base": v["base_composition"],
                  "local_primary": (v["local_primary"] or {}).get("score"),
                  "best": max(s["score"] for s in v["samples"].values()),
                  "best_label": max(v["samples"], key=lambda k: v["samples"][k]["score"])}
            for sid, v in results.items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
