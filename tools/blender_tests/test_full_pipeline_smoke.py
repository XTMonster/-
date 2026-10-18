"""Ticket 05 bpy 冒烟：完整粗排管线（含修正循环 + 冻结）。

故意构造「相机对空墙」的初始参考：相机 target 指向远离主体的空中，首轮观察
必然 E_BLOCKOUT_EMPTY_WALL fail；处方把 target 拉回主体质心后重建，粗排 gate
应通过并冻结 baseline。若渲染几何导致不收敛，则显式 blocked（机制仍正确），
但不允许把 fail 当 pass。
"""
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
        ("shot_001", 96, ["米迦尔"], "米迦尔站立"),
        ("shot_002", 72, ["偷盗者"], "偷盗者举枪"),
    ]
    result = []
    for order, (sid, duration, chars, intent) in enumerate(shots, 1):
        result.append({
            "shot_id": sid, "order": order, "intent": intent,
            "shot_type": "MS", "duration_frames": duration,
            "characters": chars, "actions": [],
            "camera": {"side": "front", "lens": 35},
        })
    return {"shots": result}


def cast_positions():
    return {"米迦尔": [-1.2, 0.0, 0.0],
            "偷盗者": [1.5, 0.0, 0.0]}


def main():
    argv = list(sys.argv)
    out = ROOT / "docs" / "evidence" / "20261018-full-pipeline-smoke"
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out = Path(args[args.index("--out") + 1])
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    from block_director.layer5_orchestrator.coarse_pipeline import (
        run_coarse_pipeline,
    )
    from block_director.layer5_orchestrator.understand import (
        deterministic_brief,
    )
    from block_director.cinema.spatial_design import build_design_snapshot

    #: 先按管线语义生成参考 JSON，再把 shot_001 相机 target 故意指向远离主体
    #: 的空中 -> 首轮观察必出 E_BLOCKOUT_EMPTY_WALL，处方循环应修正。
    brief = deterministic_brief(
        parsed=None,
        characters=sorted({n for s in plan_dict()["shots"]
                           for n in s["characters"]}))
    ref = build_design_snapshot(brief=brief, plan=plan_dict(),
                                cast_positions=cast_positions(),
                                scene_id="coarse_pipeline_smoke")
    ref["camera_intents"][0]["target"] = [20.0, 20.0, 5.0]

    report = run_coarse_pipeline(
        plan=plan_dict(),
        reference=ref,
        cast_positions=cast_positions(),
        scene_id="coarse_pipeline_smoke",
        out_dir=out,
        max_revisions=4,
    )
    (out / "coarse_pipeline_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    reference = json.loads(
        (out / "coarse_world_reference.json").read_text(encoding="utf-8"))
    baseline_path = out / "coarse_world_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) \
        if baseline_path.exists() else None

    ok = (
        "coarse_world_reference" in report["artifacts"]
        and len(reference.get("revisions") or []) >= 1
        and report["gates"]["coarse"] in ("pass", "blocked")
        and (report["gates"]["baseline"] == "frozen"
             if report["gates"]["coarse"] == "pass" else True)
        and (baseline["state"] == "frozen"
             if baseline else True)
    )
    print("BD_TEST_RESULT " + json.dumps({
        "ok": ok, "out": str(out),
        "coarse_status": report["coarse_status"],
        "gates": report["gates"],
        "revision_count": len(reference.get("revisions") or []),
        "rounds": report["rounds"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
