"""Blender 离线闭环探针：final12 真跑输入 -> 粗排 gate 必须通过。

回归 ``docs/evidence/20261020-market-real-final12/``（run ``df5538a9578a``，
``state=ERROR``、``coarse_best_score=-7``、4 次评估未过、无法进入细排）。
同一份 plan+brief 走完粗排 gate，是 Fix A/Fix B 的**整机回归**：

* Fix A（shot_002 ``E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED``）：预览侧
  ``_target_block_name`` 只精确匹配，ref=``银币`` 找不到 brief props id
  =``银币-金子`` -> 投影证据 None -> 恒 unresolved。修复后与处方侧共用
  ``resolve_prop_ref`` 别名解析，判据与处方同一口径。
* Fix B（shot_003 ``E_BLOCKOUT_EMPTY_WALL`` + ``E_FOREGROUND_OCCLUSION``）：
  三人镜（MCU，拍偷盗者）旧机位按全组质心 (−0.6,2.13) 求解且放宽 MLS，
  米迦尔/伊恩挡在相机与拍对象之间 -> 空墙+前景遮挡恒报、处方拉远消不掉。
  修复后机位以 ``framing_target`` 声明主体为 subject，景别不退、遮挡消失。

输入零 LLM：plan+brief 从真跑 stdout.log 的 ``BLOCKDIRECTOR_RESULT`` 提取
（与真跑逐字一致），站位用 ``SceneSpec.from_plan(plan, brief)`` 复现
（纯函数，结果与真跑 manifest 一致：米迦尔 [0,3.2,0] / 偷盗者 [0,0,0] /
伊恩 [-1.8,3.2,0]）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_market_coin_coarse_gate_probe.py -- --out <dir>
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

FINAL12_STDOUT = (ROOT / "docs" / "evidence" / "20261020-market-real-final12"
                  / "stdout.log")
BLOCKED_ERRORS = ("E_BLOCKOUT_EMPTY_WALL",
                  "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED")

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def final12_payload() -> dict:
    """从真跑 stdout.log 提取 BLOCKDIRECTOR_RESULT 的 JSON 负载。"""
    assert FINAL12_STDOUT.exists(), f"缺 final12 证据：{FINAL12_STDOUT}"
    text = FINAL12_STDOUT.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"BLOCKDIRECTOR_RESULT (.*)", text)
    assert match, "stdlib: stdout.log 里没有 BLOCKDIRECTOR_RESULT"
    raw = match.group(1)
    #: stdout/stderr 缓冲交错：该行末尾可能粘着 Blender 版本横幅
    raw = raw[: raw.rfind("}") + 1]
    return json.loads(raw)


def plan_brief_cast() -> tuple:
    payload = final12_payload()
    plan = payload["plan"]
    brief = payload["brief"]
    plan_obj = Plan.from_dict(plan)
    brief_obj = SceneBrief.from_dict(brief)
    spec = SceneSpec.from_plan(plan_obj, brief=brief_obj)
    cast_positions = {m.name: list(m.initial_location) for m in spec.cast}
    return plan, brief, cast_positions


def _run(out_dir, max_revisions=3) -> dict:
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
                / "20261020-market-coin-coarse-gate-pass")
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
        if "--out" in args:
            out_root = Path(args[args.index("--out") + 1])
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    def pipeline_pass():
        out = out_root / "coarse"
        report = _run(out)
        report_json = json.loads(
            (out / "blockout_report.json").read_text(encoding="utf-8"))
        findings = report_json.get("findings") or []
        blockers = [f for f in findings
                    if f.get("severity") == "error"
                    and f.get("check_id") in BLOCKED_ERRORS]
        pipeline_json = json.loads(
            (out / "coarse_pipeline_report.json").read_text(encoding="utf-8"))
        rounds = pipeline_json.get("rounds") or []
        return {
            "ok": (report["coarse_status"] == "approved"
                   and report["gates"]["coarse"] == "pass"
                   and (out / "coarse_world_baseline.json").exists()
                   and not blockers),
            "coarse_status": report["coarse_status"],
            "gates_coarse": report["gates"]["coarse"],
            "baseline_frozen": (out / "coarse_world_baseline.json").exists(),
            "blockers": [f.get("check_id") for f in blockers],
            "rounds": rounds,
        }

    check("final12_market_coin_coarse_gate_passes", pipeline_pass)

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
