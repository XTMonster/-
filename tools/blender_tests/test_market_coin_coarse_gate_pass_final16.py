"""Blender 离线闭环探针：final16 真跑输入 -> 粗排 gate 必须通过。

回归 ``docs/evidence/20261020-market-real-final16/``（run id
``0d7bf00d1ee0``，``state=ERROR``、``coarse_best_score=-133``、50 轮 strafe
死循环）。同一份 plan+brief 走完粗排 gate，是本轮修复的**整机回归**：

* Fix C（shot_002/shot_003 ``E_FOREGROUND_OCCLUSION``）：遮挡检测把同镜
  剧情道具（银币）也放进遮挡候选，银币与主体偷盗者互相被记成 occluder
  （``occluders=["银币","偷盗者"]``），strafe 处方把相机一路推到 -4.8 仍
  不收敛。修复后前景遮挡候选只保留"非主体的其他角色"（``F11`` 纯函数），
  道具体块不再进入候选，遮挡 error 消失、粗排 gate 通过。

输入零 LLM：plan+brief 从真跑 stdout.log 的 ``BLOCKDIRECTOR_RESULT`` 提取
（与真跑逐字一致），站位用 ``SceneSpec.from_plan(plan, brief)`` 复现。

运行：
  blender --background --factory-startup --python
    tools/blender_tests/test_market_coin_coarse_gate_pass_final16.py
    -- --out <dir>
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from block_director.contracts.brief import SceneBrief  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer5_orchestrator.coarse_pipeline import (  # noqa: E402
    run_coarse_pipeline,
)

FINAL16_STDOUT = (ROOT / "docs" / "evidence" / "20261020-market-real-final16"
                  / "stdout.log")
BLOCKED_ERRORS = ("E_BLOCKOUT_EMPTY_WALL",
                  "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED",
                  "E_FOREGROUND_OCCLUSION")

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def final16_payload() -> dict:
    """从真跑 stdout.log 提取 BLOCKDIRECTOR_RESULT 的 JSON 负载。"""
    assert FINAL16_STDOUT.exists(), f"缺 final16 证据：{FINAL16_STDOUT}"
    text = FINAL16_STDOUT.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"BLOCKDIRECTOR_RESULT (.*)", text)
    assert match, "stdlib: stdout.log 里没有 BLOCKDIRECTOR_RESULT"
    raw = match.group(1)
    #: stdout/stderr 缓冲交错：该行末尾可能粘着 Blender 版本横幅
    raw = raw[: raw.rfind("}") + 1]
    return json.loads(raw)


def plan_brief_cast() -> tuple:
    payload = final16_payload()
    plan = payload["plan"]
    brief = payload["brief"]
    plan_obj = Plan.from_dict(plan)
    brief_obj = SceneBrief.from_dict(brief)
    spec = SceneSpec.from_plan(plan_obj, brief=brief_obj)
    cast_positions = {m.name: list(m.initial_location) for m in spec.cast}
    return plan, brief, cast_positions


def _run(out_dir, max_revisions=50) -> dict:
    plan, brief, cast_positions = plan_brief_cast()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return run_coarse_pipeline(
        plan=plan, brief=brief, cast_positions=cast_positions,
        scene_id=str(plan.get("scene_heading") or "market"),
        out_dir=out_dir, max_revisions=max_revisions,
    )


def main():
    argv = list(sys.argv)
    out_root = (ROOT / "docs" / "evidence"
                / "20261020-market-coin-coarse-gate-pass-final16")
    max_revisions = 50
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out_root = Path(args[args.index("--out") + 1])
        if "--max-revisions" in args:
            max_revisions = int(
                args[args.index("--max-revisions") + 1])
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    def pipeline_pass():
        out = out_root / "coarse"
        report = _run(out, max_revisions=max_revisions)
        report_json = json.loads(
            (out / "blockout_report.json").read_text(encoding="utf-8"))
        findings = report_json.get("findings") or []
        blockers = [f for f in findings
                    if f.get("severity") == "error"
                    and f.get("check_id") in BLOCKED_ERRORS]
        pipeline_json = json.loads(
            (out / "coarse_pipeline_report.json").read_text(encoding="utf-8"))
        rounds = pipeline_json.get("rounds") or []
        error_findings = [f for f in findings
                          if f.get("severity") == "error"]
        return {
            "ok": (report["coarse_status"] == "approved"
                   and report["gates"]["coarse"] == "pass"
                   and (out / "coarse_world_baseline.json").exists()
                   and not blockers),
            "coarse_status": report["coarse_status"],
            "gates_coarse": report["gates"]["coarse"],
            "baseline_frozen": (out / "coarse_world_baseline.json").exists(),
            "blockers": [f.get("check_id") for f in blockers],
            "error_findings": [f.get("check_id") for f in error_findings],
            "rounds": len(rounds),
            "max_revisions": max_revisions,
        }

    check("final16_market_coin_coarse_gate_passes", pipeline_pass)

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
