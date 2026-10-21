"""真实 final16 输入：局部拍对象必须由射线证明可见。

只用 shot_002/003（偷盗者手部/面部特写）走生产路径：真实 plan/brief ->
``build_design_snapshot`` -> ``BlockoutManifest`` -> 体块场景 ->
``render_blockout_preview``。判据同时检查：

1. brief 的中文 ``kind=货币`` 经 manifest 后是硬币尺度；
2. 声明拍对象有投影与真实局部可见性两项证据；
3. 手部局部可见比达到现有 ``VISIBLE_RATIO_MIN``，构图严格 >80；
4. 报告不得出现 ``E_BLOCKOUT_FRAMING_TARGET_OCCLUDED``。

运行：
  blender --background --factory-startup --python
    tools/blender_tests/test_coarse_local_subject_visibility_probe.py
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

import bpy  # noqa: E402

from block_director.cinema.blockout import build_blockout_manifest  # noqa: E402
from block_director.cinema.blockout_report import (  # noqa: E402
    E_BLOCKOUT_FRAMING_TARGET_OCCLUDED,
    VISIBLE_RATIO_MIN,
)
from block_director.cinema.spatial_design import (  # noqa: E402
    build_design_snapshot,
)
from block_director.contracts.brief import SceneBrief  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer3_engine.blockout_scene import (  # noqa: E402
    build_blockout_scene,
)
from block_director.layer5_orchestrator.coarse_pipeline import (  # noqa: E402
    _attach_plan_shots,
)
from block_director.layer8_delivery.blockout_preview import (  # noqa: E402
    render_blockout_preview,
)

FINAL16_STDOUT = (ROOT / "docs" / "evidence" / "20261020-market-real-final16"
                  / "stdout.log")


def _payload() -> dict:
    text = FINAL16_STDOUT.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"BLOCKDIRECTOR_RESULT (.*)", text)
    assert match, "stdout.log 里没有 BLOCKDIRECTOR_RESULT"
    raw = match.group(1)
    return json.loads(raw[: raw.rfind("}") + 1])


def run_probe(out_dir: Path) -> dict:
    payload = _payload()
    plan_payload = payload["plan"]
    plan = Plan.from_dict(plan_payload)
    brief = SceneBrief.from_dict(payload["brief"])
    spec = SceneSpec.from_plan(plan, brief=brief)
    cast_positions = {member.name: list(member.initial_location)
                      for member in spec.cast}
    reference = build_design_snapshot(
        brief=brief, plan=plan, cast_positions=cast_positions,
        scene_id=str(plan_payload.get("scene_heading") or "market"))
    reference = _attach_plan_shots(reference, plan)
    manifest = build_blockout_manifest(design=reference, plan=plan)

    target_shot_ids = {"shot_002", "shot_003"}
    expected_shots = [
        shot for shot in plan_payload["shots"]
        if str(shot.get("shot_id") or "") in target_shot_ids
    ]
    expected = {"shots": expected_shots}
    manifest = dict(manifest)
    manifest["cameras"] = [
        camera for camera in manifest.get("cameras") or []
        if str(camera.get("shot_id") or "") in target_shot_ids
    ]
    manifest["shot_table"] = [
        row for row in manifest.get("shot_table") or []
        if str(row.get("shot_id") or "") in target_shot_ids
    ]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_blockout_scene(manifest, clear_scene=True)
    preview = render_blockout_preview(
        manifest, out_dir, expected=expected, reference_json=reference)
    report = preview["report"]
    checks = {
        (str(check.get("shot_id") or ""), str(check.get("check_id") or "")):
        check
        for check in report.get("checks") or []
    }
    coin = next(
        primitive for primitive in manifest.get("primitives") or []
        if primitive.get("kind") == "prop"
        and str((primitive.get("source") or {}).get("id") or "") == "银币")
    coin_size = coin.get("size") or {}
    mismatches = []
    if float(coin_size.get("x") or 0.0) > 0.2 \
            or float(coin_size.get("y") or 0.0) > 0.2 \
            or float(coin_size.get("z") or 0.0) > 0.1:
        mismatches.append(f"银币尺寸仍非硬币尺度：{coin_size}")
    targets = {}
    compositions = {}
    for shot_id in sorted(target_shot_ids):
        target = checks.get((shot_id, "framing_target")) or {}
        composition = checks.get((shot_id, "composition")) or {}
        targets[shot_id] = target
        compositions[shot_id] = composition
        if target.get("visible_ratio") is None:
            mismatches.append(f"{shot_id} framing_target 缺真实可见性证据")
        elif float(target["visible_ratio"]) < VISIBLE_RATIO_MIN:
            mismatches.append(
                f"{shot_id} 局部主体可见比 {target['visible_ratio']} "
                f"< {VISIBLE_RATIO_MIN}")
        if target.get("verdict") != "pass":
            mismatches.append(
                f"{shot_id} framing_target verdict={target.get('verdict')}")
        if composition.get("verdict") != "pass":
            mismatches.append(f"{shot_id} 构图未过门：{composition}")
    occluded = [
        finding for finding in report.get("findings") or []
        if str(finding.get("check_id") or "")
        == E_BLOCKOUT_FRAMING_TARGET_OCCLUDED
    ]
    if occluded:
        mismatches.append(f"出现局部主体遮挡硬伤：{occluded}")

    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "coin_size": coin_size,
        "framing_targets": targets,
        "compositions": compositions,
        "report_verdict": report.get("verdict"),
        "previews": preview.get("previews"),
    }


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = (ROOT / "docs" / "evidence"
               / "20261021-coarse-local-subject-visibility")
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_probe(out_dir)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "trace": traceback.format_exc(limit=5)}
    (out_dir / "coarse_local_subject_visibility.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BD_TEST_RESULT " + json.dumps({
        "ok": bool(result.get("ok")),
        "out": str(out_dir),
        "passed": (["coarse_local_subject_visibility"]
                   if result.get("ok") else []),
        "failed": ([] if result.get("ok")
                   else ["coarse_local_subject_visibility"]),
        "checks": {"coarse_local_subject_visibility": result},
    }, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
