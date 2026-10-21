"""Ticket 07：五镜飞扑/枪击/幽灵现身剧情——完整流程端到端。

剧本理解 -> 粗编排参考 JSON -> Blockout 粗排 -> 空间尺观察 -> 处方修正循环
-> 粗排通过冻结 -> 分镜表 -> 逐镜细排 -> 逐镜审核 -> 全片回放 -> final gate
-> 输出 final_video.mp4。全程插件自动执行，不手动干预坐标；报告记录每阶段
gate 判定与产物。
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
        ("shot_001", 72, ["米迦尔", "偷盗者"], "飞扑建立空间", "飞扑"),
        ("shot_002", 120, ["米迦尔"], "三发枪击节拍", "贯穿"),
        ("shot_003", 60, ["偷盗者"], "找不到米迦尔", "环视"),
        ("shot_004", 72, ["偷盗者", "米迦尔"], "米迦尔从身后浮现", "浮现"),
        ("shot_005", 60, ["偷盗者"], "回头惊讶", "回头"),
    ]
    result = []
    for order, (sid, duration, chars, intent, action) in enumerate(shots, 1):
        result.append({
            "shot_id": sid, "order": order, "intent": intent,
            "shot_type": "MS", "duration_frames": duration,
            "characters": chars,
            "actions": [{"action": action}],
            "camera": {"side": "front", "lens": 35},
        })
    return {"shots": result}


def cast_positions():
    return {"米迦尔": [-0.8, 0.0, 0.0],
            "偷盗者": [1.8, 0.0, 0.0],
            "伊恩": [-0.2, 1.0, 0.0],
            "贵妇": [-2.0, 0.0, 0.0]}


def main():
    argv = list(sys.argv)
    out = ROOT / "docs" / "evidence" / "20261018-five-shot-fly-bomb-e2e"
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

    plan = plan_dict()
    coarse = run_coarse_pipeline(
        plan=plan,
        cast_positions=cast_positions(),
        scene_id="dock_fly_bomb_five_shots",
        out_dir=out / "coarse",
        max_revisions=3,
    )
    baseline = None
    if coarse["gates"]["coarse"] == "pass" \
            and coarse["gates"]["baseline"] == "frozen":
        baseline = json.loads(
            (out / "coarse" / "coarse_world_baseline.json")
            .read_text(encoding="utf-8"))

    detail = None
    if baseline is not None:
        detail = run_detail_pipeline(
            baseline=baseline, plan=plan,
            out_dir=out / "detail",
            render_video=True,
        )

    summary = {
        "scene": "五镜飞扑/枪击/幽灵现身",
        "coarse": {
            "status": coarse["coarse_status"],
            "gates": coarse["gates"],
            "rounds": coarse["rounds"],
        },
        "detail": detail and {
            "gates": detail["gates"],
            "final": detail["final"],
            "final_video": detail["artifacts"].get("final_video"),
        },
        "flow": [
            "script_to_json", "blockout", "observe",
            "prescription_fix_if_needed", "freeze_baseline",
            "detail_blocking", "detail_review", "sequence_replay",
            "final_gate", "final_video",
        ],
    }
    (out / "five_shot_e2e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    final_ok = (baseline is not None and detail is not None
                and detail["final"] is True
                and (out / "detail" / "final_video.mp4").exists())
    print("BD_TEST_RESULT " + json.dumps({
        "ok": final_ok, "out": str(out),
        "passed": 1 if final_ok else 0, "failed": 0 if final_ok else 1,
        "checks": (detail["gates"] if detail else coarse["gates"]),
        "coarse_status": coarse["coarse_status"],
        "coarse_gates": coarse["gates"],
        "coarse_rounds": len(coarse["rounds"]),
        "detail_gates": detail["gates"] if detail else None,
        "final": detail["final"] if detail else False,
        "final_video": str(out / "detail" / "final_video.mp4")
        if final_ok else None,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
