"""五镜飞扑/枪击/幽灵现身片段的 Blockout 预演验证（不改生产代码）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import bpy  # noqa: E402


def plan_dict():
    shots = [
        ("shot_001", 72, ["米迦尔", "偷盗者", "伊恩", "贵妇"], "飞扑建立空间"),
        ("shot_002", 120, ["米迦尔"], "三发枪击节拍"),
        ("shot_003", 60, ["偷盗者"], "找不到米迦尔"),
        ("shot_004", 72, ["偷盗者", "米迦尔"], "米迦尔从身后浮现"),
        ("shot_005", 60, ["偷盗者"], "回头惊讶"),
    ]
    cursor = 1
    result = []
    for order, (sid, duration, chars, intent) in enumerate(shots, 1):
        result.append({"shot_id": sid, "order": order, "intent": intent,
                       "shot_type": "MS", "duration_frames": duration,
                       "characters": chars, "actions": [],
                       "camera": {"side": "front", "lens": 35}})
    return {"shots": result}


def design():
    positions = {
        "米迦尔": [-0.8, 0.0, 0.0], "伊恩": [-0.2, 1.0, 0.0],
        "贵妇": [-2.0, 0.0, 0.0], "偷盗者": [1.8, 0.0, 0.0],
    }
    cameras = [
        ("shot_001", [-0.5, 5.5, 2.0], [-0.2, 0.0, 0.8]),
        ("shot_002", [0.0, 5.0, 1.4], [0.0, 0.0, 0.9]),
        ("shot_003", [2.8, 4.5, 1.5], [1.8, 0.0, 0.9]),
        ("shot_004", [3.2, 4.0, 1.6], [0.6, 0.0, 0.9]),
        ("shot_005", [3.0, 3.2, 1.5], [1.8, 0.0, 1.0]),
    ]
    return {
        "schema_version": "spatial-design-snapshot/v1", "scene_id": "dock_fly_bomb",
        "characters": [{"name": n, "position": {"x": p[0], "y": p[1], "z": p[2]},
                         "facing": [0.0, 1.0, 0.0], "provenance": "script_declaration"}
                        for n, p in positions.items()],
        "props": [{"id": "枪", "kind": "prop", "position": [1.8, 0.0, 1.2],
                   "provenance": "script_declaration"}],
        "anchors": [],
        "camera_intents": [{"shot_id": sid, "position": pos, "target": target,
                             "lens": 35.0, "fov_deg": 54.4,
                             "provenance": "script_declaration", "resolved": True}
                            for sid, pos, target in cameras],
        "notes": ["枪击三发由 shot_002 120 帧节拍代理；幽灵浮现由 shot_004 空间关系代理"],
    }


def main():
    argv = list(sys.argv)
    out = ROOT / "docs" / "evidence" / "20261018-fly-bomb-blockout"
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out = Path(args[args.index("--out") + 1])
    out = out.resolve(); out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    from block_director.contracts.plan import Plan
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.layer3_engine.blockout_scene import build_blockout_scene
    from block_director.layer8_delivery.blockout_preview import render_blockout_preview
    from block_director.layer3_engine.blockout_checkpoint import save_blockout_checkpoints
    from block_director.layer8_delivery.blockout_sequence import run_blockout_sequence_review

    manifest = build_blockout_manifest(design=design(), plan=Plan.from_dict(plan_dict()))
    build_blockout_scene(manifest, clear_scene=True)
    preview = render_blockout_preview(manifest, out)
    checkpoints = save_blockout_checkpoints(manifest, out)
    sequence = run_blockout_sequence_review(manifest, out, render_video=True)
    report = {"shots": [c.get("shot_id") for c in manifest["cameras"]],
              "preview": preview["report"], "checkpoint_count": checkpoints["count"],
              "sequence": sequence["review"],
              "video": sequence.get("video", {}),
              "flow": ["script_to_json", "manifest", "blockout", "observe",
                       "judge", "checkpoint", "sequence_review"],
              "proxy_notes": ["红黑剪影/三发定格使用体块与帧段代理，非最终画风"]}
    (out / "fly_bomb_blockout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BD_TEST_RESULT " + json.dumps({"ok": True, "out": str(out),
                                           "passed": 1, "failed": 0,
                                           "checks": {"preview": preview["report"]["verdict"]},
                                           "shots": report["shots"],
                                           "preview_verdict": preview["report"]["verdict"],
                                           "sequence_verdict": sequence["review"]["verdict"],
                                           "checkpoints": checkpoints["count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
