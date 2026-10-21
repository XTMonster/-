"""R10（T7）Blender 探针：粗排 gate 对"参考 JSON 被改错"必须有效拦下。

对抗：把粗排参考世界坐标 JSON 的 shots[] 顺序颠倒（order 值互换）后跑
``run_coarse_pipeline``，粗排必须 blocked，``blockout_report.json`` 必须
含 ``E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH`` error finding；同一份干净的
参考 JSON 再跑一遍必须 approved 且基准冻结。改对通过、改错必拦，R10 才算
有效验证分镜序列。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_coarse_gate_adversarial_probe.py -- --out <dir>
"""

from __future__ import annotations

import copy
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from block_director.cinema.spatial_design import build_design_snapshot  # noqa: E402
from block_director.layer5_orchestrator.coarse_pipeline import (  # noqa: E402
    run_coarse_pipeline,
)
from block_director.layer5_orchestrator.understand import (  # noqa: E402
    deterministic_brief,
)

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def plan_dict():
    return {
        "scene_heading": "第十四街区码头市场",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "米迦尔打响指",
             "shot_type": "MS", "duration_frames": 24,
             "characters": ["米迦尔", "偷盗者"], "actions": []},
            {"shot_id": "shot_002", "order": 2, "intent": "偷盗者捧金",
             "shot_type": "MS", "duration_frames": 24,
             "characters": ["米迦尔", "偷盗者"], "actions": []},
        ],
    }


def cast_positions():
    return {"米迦尔": [-0.9, 0.0, 0.0],
            "偷盗者": [0.9, 0.0, 0.0]}


def _reference() -> dict:
    plan = plan_dict()
    brief = deterministic_brief(
        parsed=None,
        characters=sorted({n for s in plan["shots"] for n in s["characters"]}))
    ref = build_design_snapshot(
        brief=brief, plan=plan, cast_positions=cast_positions(),
        scene_id="coarse_gate_adversarial")
    #: 语义层 shots[]（与 run_coarse_pipeline._attach_plan_shots 同口径）
    ref["shots"] = [dict(s) for s in plan["shots"]]
    return ref


def _swapped_reference() -> dict:
    ref = _reference()
    ref = copy.deepcopy(ref)
    #: 分镜顺序被颠倒：order 值互换（shot_001 变第 2 镜、shot_002 变第 1 镜）
    ref["shots"][0]["order"], ref["shots"][1]["order"] = 2, 1
    return ref


def _run(out_dir, reference):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return run_coarse_pipeline(
        plan=plan_dict(), reference=reference,
        cast_positions=cast_positions(),
        scene_id="coarse_gate_adversarial",
        out_dir=out_dir, max_revisions=1,
    )


def main():
    argv = list(sys.argv)
    out_root = ROOT / "docs" / "evidence" / "20261019-coarse-gate-adversarial"
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out_root = Path(args[args.index("--out") + 1])
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    def adversarial():
        out = out_root / "swapped"
        report = _run(out, _swapped_reference())
        report_json = json.loads(
            (out / "blockout_report.json").read_text(encoding="utf-8"))
        mismatches = [f for f in report_json.get("findings") or []
                      if f.get("check_id")
                      == "E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH"]
        manifest_json = json.loads(
            (out / "blockout_manifest.json").read_text(encoding="utf-8"))
        orders = [int(r["order"]) for r in manifest_json["shot_table"]]
        return {
            "ok": (report["coarse_status"] == "blocked"
                   and report["gates"]["coarse"] == "blocked"
                   and len(mismatches) >= 1
                   and all(m["severity"] == "error" for m in mismatches)
                   and orders == [2, 1]),
            "coarse_status": report["coarse_status"],
            "gates_coarse": report["gates"]["coarse"],
            "mismatch_findings": len(mismatches),
            "manifest_orders": orders,
        }

    def clean():
        out = out_root / "clean"
        report = _run(out, _reference())
        baseline = (out / "coarse_world_baseline.json").exists()
        return {
            "ok": (report["coarse_status"] == "approved"
                   and report["gates"]["coarse"] == "pass"
                   and baseline),
            "coarse_status": report["coarse_status"],
            "gates_coarse": report["gates"]["coarse"],
            "baseline_frozen": baseline,
        }

    check("adversarial_swapped_sequence_blocked", adversarial)
    check("clean_sequence_approved", clean)

    passed = [name for name, result in RESULTS.items()
              if result.get("ok") is True]
    failed = [name for name, result in RESULTS.items()
              if result.get("ok") is not True]
    print("BD_TEST_RESULT " + json.dumps({
        "ok": not failed, "out": str(out_root),
        "passed": passed, "failed": failed,
        "checks": RESULTS,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
