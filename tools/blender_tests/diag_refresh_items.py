"""诊断：refresh_blockout_composition 后每镜构图分项明细。

细排 gate 卡在 70-80 分区间时，用分项明细定位是 headroom/lead_room/
thirds/balance/occlusion/framing 哪一项拖分。复用 final16b 冻结 baseline，
零 LLM。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

FINAL16B = (ROOT / "docs" / "evidence"
            / "20261020-market-coin-coarse-gate-pass-final16b")
FINAL16_STDOUT = (ROOT / "docs" / "evidence"
                  / "20261020-market-real-final16" / "stdout.log")


def _plan_from_stdout() -> dict:
    text = FINAL16_STDOUT.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"BLOCKDIRECTOR_RESULT (.*)", text)
    assert match, "stdout.log 里没有 BLOCKDIRECTOR_RESULT"
    raw = match.group(1)
    return json.loads(raw[: raw.rfind("}") + 1])["plan"]


def main():
    argv = list(sys.argv)
    out_root = ROOT / "docs" / "evidence" / "20261021-refresh-items-diag"
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out_root = Path(args[args.index("--out") + 1])
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    baseline = json.loads(
        (FINAL16B / "coarse" / "coarse_world_baseline.json")
        .read_text(encoding="utf-8"))
    plan = _plan_from_stdout()

    from block_director.layer8_delivery.blockout_preview import (
        refresh_blockout_composition,
    )
    report = refresh_blockout_composition(
        baseline=baseline, out_dir=out_root,
        expected=plan, reference_json=baseline.get("reference"))

    #: 单独重算曝光：直接再调一次 evaluate_composition 拿 items（report 里
    #: 只有 composition score，没存分项；这里用同一 manifest 评分侧复算）。
    manifest = json.loads(
        (out_root / "refreshed_manifest.json").read_text(encoding="utf-8"))
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    build_blockout_scene(manifest, clear_scene=True)
    from block_director.layer8_delivery.blockout_preview import (
        _render_shot_preview,
        _shot_isolation_objects,
        _subject_blocks,
    )
    from block_director.cinema.blockout_report import plan_shot_dicts
    from block_director.cinema.spatial_design import resolve_camera_intents

    scene = bpy.context.scene
    reference = resolve_camera_intents(baseline.get("reference") or {})
    expected_shots = plan_shot_dicts(plan)
    expected_by_shot = {str(s.get("shot_id") or ""): s
                        for s in expected_shots}
    cam_objs = {}
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        cam_objs[shot_id] = bpy.data.objects.get(
            f"BD_Blockout_{camera.get('camera_id')}")

    subject_blocks = _subject_blocks(manifest)
    reference_chars = {}
    for char in reference.get("characters") or []:
        reference_chars[str(char.get("name") or "")] = char

    items_out = {}
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        cam = cam_objs.get(shot_id)
        if cam is None:
            continue
        row = next((r for r in manifest.get("shot_table") or []
                    if r.get("shot_id") == shot_id), {})
        start = int(camera.get("start_frame") or 1)
        end = int(camera.get("end_frame") or start)
        scene.camera = cam
        isolated = _shot_isolation_objects(manifest, row)
        previous = {obj.name: bool(obj.hide_render) for obj in isolated}
        for obj in isolated:
            obj.hide_render = True
        try:
            entry, _frames = _render_shot_preview(
                scene=scene, camera_obj=cam, shot_id=shot_id,
                frames=[
                    ("first", start),
                    ("middle", (start + end) // 2),
                    ("last", end),
                ],
                shot_table_row=row, manifest=manifest,
                subject_blocks=subject_blocks,
                reference_chars=reference_chars,
                expected_by_shot=expected_by_shot,
                camera_objects=cam_objs,
                occluder_lookup={},
                preview_dir=out_root / "png")
        finally:
            for obj in isolated:
                obj.hide_render = previous.get(obj.name, False)
        items_out[shot_id] = {
            "composition_score": entry.get("composition_score"),
            "composition_items": entry.get("composition_items"),
            "composition_primary": entry.get("composition_primary"),
            "composition_expected_height": (
                entry.get("composition_expected_height")),
            "visible": entry.get("visible_ratio"),
            "on_screen": entry.get("on_screen_ratio"),
            "area": entry.get("max_subject_area_ratio"),
        }

    (out_root / "items.json").write_text(
        json.dumps(items_out, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("BD_TEST_RESULT " + json.dumps({
        "ok": True, "out": str(out_root), "items": items_out,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
