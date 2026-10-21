"""回归探针：声明了拍对象但体块未解析时粗排预览不崩溃、不猜通过。

复现链（真跑 20261020-market-real-final）：模型计划声明了
``framing_target.kind=prop, ref=gold_coin``，但 manifest 里没有对应体块
（Stage S brief 漏道具，体块自然未落），旧 preview 把 ``None`` 传给
``bpy.data.objects.get(None)``，Blender 5.2 抛 ``KeyError``，整个粗排门
以运行时异常终止，白模视频不产出。

本探针构造同一形状：场景里只有角色体块，计划却声明拍道具 gold_coin。
断言：
1. ``render_blockout_preview`` 不抛异常（未解析是合法状态，不是崩溃）；
2. 报告保留 ``E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED`` error finding，
   ``framing_target`` check 的 actual 为 None（不伪造投影数值）；
3. 粗排 gate 保持阻塞（unresolved 不静默通过）。

运行：
blender --background --factory-startup --python tools/blender_tests/test_framing_target_unresolved_probe.py -- --out <dir>
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
    """单镜设计：场景里只有角色米迦尔，没有任何道具体块。"""
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "market_unresolved",
        "characters": [
            {"name": "米迦尔", "position": {"x": 0.0, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            #: shot_001：正面拍米迦尔，构图本身合法（角色在画面内）；
            #: 但计划声明拍 gold_coin，而场景里没有这个道具体块。
            {"shot_id": "shot_001", "position": [0.0, 5.0, 1.0],
             "target": [0.0, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["未解析拍对象回归探针"],
    }


def _plan():
    from block_director.contracts.plan import (
        FramingTarget,
        Plan,
        ShotPlan,
    )

    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="道具特写", shot_type="ECU",
            duration_frames=12, order=1, characters=["米迦尔"],
            camera={"side": "front", "lens": 35},
            framing_target=FramingTarget(kind="prop", ref="gold_coin",
                                         part="none"),
        ),
    ])


def run_probe(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    from block_director.layer8_delivery.blockout_preview import (
        render_blockout_preview,
    )
    from block_director.cinema.pipeline_gates import coarse_gate

    plan = _plan()
    manifest = build_blockout_manifest(design=_design(), plan=plan)
    build_blockout_scene(manifest, clear_scene=True)

    #: 旧实现在这里崩（KeyError: ... not NoneType）；修复后必须走到 report。
    result = render_blockout_preview(manifest, out_dir, expected=plan)
    report = result["report"]
    checks: dict = {}
    mismatches: list = []

    #: 1. manifest 里确实没有 gold_coin 体块（复现 unresolved 的前提）
    primitives = list(manifest.get("primitives") or [])
    checks["prop_primitives"] = [
        str((p.get("source") or {}).get("id") or "")
        for p in primitives if p.get("kind") == "prop"]
    if any(str((p.get("source") or {}).get("id") or "") == "gold_coin"
           for p in primitives):
        mismatches.append("场景里不应有 gold_coin 体块（复现前提被破坏）")

    #: 2. 报告必须保留 UNRESOLVED error finding，actual 为 None（不伪造）
    unresolved = [
        f for f in report["findings"]
        if f.get("shot_id") == "shot_001"
        and f["check_id"] == "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED"]
    checks["unresolved_findings"] = len(unresolved)
    if not unresolved:
        mismatches.append("声明拍对象但无体块：缺 E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED")

    ft_checks = [c for c in report["checks"]
                 if c.get("check_id") == "framing_target"
                 and c.get("shot_id") == "shot_001"]
    checks["framing_target_actual"] = (
        ft_checks[0].get("actual") if ft_checks else None)
    checks["framing_target_verdict"] = (
        ft_checks[0].get("verdict") if ft_checks else None)
    if not ft_checks:
        mismatches.append("缺 framing_target check")
    elif ft_checks[0].get("actual") is not None:
        mismatches.append("未解析拍对象被伪造了投影数值："
                          f"{ft_checks[0].get('actual')}")
    elif ft_checks[0].get("verdict") != "unresolved":
        mismatches.append(f"未解析拍对象 verdict 应为 unresolved，"
                          f"实际 {ft_checks[0].get('verdict')}")

    #: 3. 粗排 gate 保持阻塞（unresolved 不静默通过）
    gate = coarse_gate(report)
    checks["coarse_gate_passed"] = gate["passed"]
    if gate["passed"]:
        mismatches.append("未解析拍对象不应通过粗排 gate（否则等于静默放行）")

    #: 4. 角色主体自身照常测量（只有拍对象 unresolved，不影响同镜角色读数）
    occlusion = [c for c in report["checks"]
                 if c.get("check_id") == "occlusion"
                 and c.get("shot_id") == "shot_001"]
    checks["shot001_occlusion"] = (
        occlusion[0].get("actual") if occlusion else None)
    if not occlusion or occlusion[0].get("actual") is None:
        mismatches.append("同镜角色读数丢失（修复误伤主体测量）")

    checks["mismatches"] = mismatches
    (out_dir / "blockout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "framing_target_unresolved_summary.json").write_text(
        json.dumps({"checks": checks}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"ok": not mismatches, "checks": checks}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261020-framing-target-unresolved"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["framing_target_unresolved"] = run_probe(out_dir)
    except Exception as exc:  # noqa: BLE001
        RESULTS["framing_target_unresolved"] = {
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
