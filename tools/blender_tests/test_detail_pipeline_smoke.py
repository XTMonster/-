"""Ticket 06 bpy 冒烟：细排编排器（冻结->细排->审核->回放->final gate）。

先跑粗排管线拿到冻结 baseline，再跑细排管线；断言 final gate 通过并产出
final_video.mp4（final:true），且报告每阶段 gate 判定齐全。
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
            "characters": chars, "actions": [
                {"action": "举枪" if sid == "shot_002" else "站立"},
            ],
            "camera": {"side": "front", "lens": 35},
        })
    return {"shots": result}


def cast_positions():
    return {"米迦尔": [-1.2, 0.0, 0.0],
            "偷盗者": [1.5, 0.0, 0.0]}


def main():
    argv = list(sys.argv)
    out = ROOT / "docs" / "evidence" / "20261018-detail-pipeline-smoke"
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
    from block_director.layer5_orchestrator.detail_pipeline import (
        run_detail_pipeline,
    )
    from block_director.layer3_engine.detail_session import (
        DetailSceneSession,
    )

    def session_factory(**kwargs):
        values = dict(kwargs)
        values.pop("transport", None)
        values.pop("knowledge", None)
        return DetailSceneSession(**values)

    coarse = run_coarse_pipeline(
        plan=plan_dict(),
        cast_positions=cast_positions(),
        scene_id="detail_pipeline_smoke",
        out_dir=out / "coarse",
        max_revisions=3,
    )
    assert coarse["gates"]["coarse"] == "pass", coarse
    assert coarse["gates"]["baseline"] == "frozen", coarse

    baseline = json.loads(
        (out / "coarse" / "coarse_world_baseline.json")
        .read_text(encoding="utf-8"))
    detail = run_detail_pipeline(
        baseline=baseline, plan=plan_dict(),
        out_dir=out / "detail",
        render_video=True,
        session_factory=session_factory,
    )
    (out / "detail_pipeline_report.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")

    final_path = out / "detail" / "final_video.mp4"
    ok = (
        detail["gates"]["detail"] == "pass"
        and detail["gates"]["sequence"] == "pass"
        and detail["gates"]["final"] == "pass"
        and detail["final"] is True
        and final_path.exists()
        and final_path.stat().st_size > 0
    )
    print("BD_TEST_RESULT " + json.dumps({
        "ok": ok, "out": str(out),
        "passed": 1 if ok else 0, "failed": 0 if ok else 1,
        "checks": detail["gates"],
        "gates": detail["gates"],
        "final": detail["final"],
        "final_video": str(final_path),
        "video": detail["video"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
