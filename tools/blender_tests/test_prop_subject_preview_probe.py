"""R2 缺陷探针：粗排预览把道具（framing_target=prop）纳入主体测量。

复现链（真跑 20261019-r2-market-coin-final2）：银币特写镜的 ``prop_ids``
在 manifest 里已登记，但 preview 的 ``subject_names`` 只取 ``character_ids``，
于是可见性/空墙/面积判据只测持币角色整身，银币被当成"空墙+面积溢出"误报，
粗排 gate 阻塞、白模视频不产出。

本探针构造一个银币 ECU 特写镜：场景里银币体块在偷盗者胸前（手持坐标），
机位对准银币。断言：
1. 银币体块进入 preview 测量（``subject_names`` 含角色 + 本镜道具）；
2. 主锚读数生效（``per_shot`` 的 ``visible_ratio``/``on_screen_ratio``/
   ``max_subject_area_ratio`` 以银币为准，而非角色整身）；
3. 不产生 E_BLOCKOUT_EMPTY_WALL / E_SUBJECT_AREA_OVERFLOW error finding，
   粗排 gate 通过。

运行：
blender --background --factory-startup --python tools/blender_tests/test_prop_subject_preview_probe.py -- --out <dir>
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
    """两镜设计：shot_001 银币 ECU 特写、shot_002 空镜对照组。"""
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "market_coin",
        "characters": [
            {"name": "偷盗者", "position": {"x": 0.0, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [
            #: 真跑里 plan 写 ref=银币、brief 写 id=银币-金子；预览必须与
            #: 处方/判据共用 resolve_prop_ref，不能只在精确 id 时测量道具。
            {"id": "银币-金子", "kind": "银币化为金子", "owner": "偷盗者",
             "position": {"x": 0.22, "y": 0.80, "z": 0.9107},
             "rotation": None, "motion": None,
             "provenance": "algorithmic_measurement",
             "unit": {"position": "m"}},
        ],
        "anchors": [],
        "camera_intents": [
            #: shot_001：银币 ECU。12 cm 的道具必须在近距 + 85mm 下取景；
            #: 旧 fixture 站在 3.2 m 外，实际只拍成角色 MS，构图门正确拦截。
            #: 银币落在左上三分点附近；对准点因此略向右下偏离银币中心。
            {"shot_id": "shot_001", "position": [0.22, 1.58, 0.8953],
             "target": [0.269, 0.80, 0.8953], "lens": 85.0,
             "fov_deg": 23.9,
             "provenance": "algorithmic_measurement", "resolved": True},
            #: shot_002：空镜（市场通道），无主体合法
            {"shot_id": "shot_002", "position": [4.0, 5.0, 1.0],
             "target": [4.0, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["道具特写预览修复探针"],
    }


def _plan():
    from block_director.contracts.plan import (
        FramingTarget,
        Plan,
        ShotPlan,
    )

    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="银币特写", shot_type="ECU",
            duration_frames=24, order=1, characters=["偷盗者"],
            camera={"side": "front", "lens": 85},
            framing_target=FramingTarget(kind="prop", ref="银币",
                                         part="none"),
        ),
        ShotPlan(
            shot_id="shot_002", intent="空镜：市场通道", shot_type="MS",
            duration_frames=12, order=2, characters=[],
            camera={"lens": 35},
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

    result = render_blockout_preview(manifest, out_dir, expected=plan)
    report = result["report"]
    checks: dict = {}
    mismatches: list = []

    #: 1. manifest 里银币体块已登记，preview 把它纳入主体测量
    shot_table = next(r for r in manifest["shot_table"]
                      if r["shot_id"] == "shot_001")
    checks["shot001_prop_ids"] = list(shot_table.get("prop_ids") or [])
    if "银币-金子" not in (shot_table.get("prop_ids") or []):
        mismatches.append("shot_001 的 prop_ids 未登记银币")

    objs = {obj.name for obj in bpy.data.objects}
    checks["coin_block_present"] = "BD_Blockout_prop_银币-金子" in objs
    if "BD_Blockout_prop_银币-金子" not in objs:
        mismatches.append(
            "场景中缺少银币体块 BD_Blockout_prop_银币-金子")

    #: 2. per_shot 的银币主锚读数（可见/出画/面积）非空
    #: report 不直接暴露 per_shot；用视觉状态 + findings 判定。此处从报告
    #: checks 读 shot_001 的 occlusion/on_screen/subject_area 实际值。
    by_shot = [c for c in report["checks"] if c["shot_id"] == "shot_001"]
    by_id = {c["check_id"]: c for c in by_shot}
    checks["shot001_occlusion"] = (by_id.get("occlusion") or {}).get("actual")
    checks["shot001_on_screen"] = (by_id.get("on_screen") or {}).get("actual")
    checks["shot001_area"] = (by_id.get("subject_area") or {}).get("actual")
    checks["shot001_ft"] = (by_id.get("framing_target") or {})
    for key in ("occlusion", "on_screen", "subject_area", "framing_target"):
        if key not in by_id:
            mismatches.append(f"shot_001 缺 {key} check")
        elif by_id[key].get("actual") is None \
                and key != "framing_target":
            mismatches.append(f"shot_001 {key} 无读数（unresolved）")

    #: 3. 不产生空墙/面积溢出 error finding
    hard = [f for f in report["findings"]
            if f.get("shot_id") == "shot_001"
            and f.get("severity") == "error"]
    checks["shot001_hard_findings"] = len(hard)
    if hard:
        mismatches.append(
            f"shot_001 道具特写被误判硬伤：{hard}")

    #: 4. 粗排 gate 通过（道具特写镜不再阻塞）
    gate = coarse_gate(report)
    checks["coarse_gate_passed"] = gate["passed"]
    if not gate["passed"]:
        mismatches.append(f"粗排 gate 未通过：{gate.get('reasons')}")

    #: 5. 银币体块确实在该镜被投影测量（target on_screen 有值）
    ft = by_id.get("framing_target") or {}
    checks["shot001_ft_on_screen"] = ft.get("actual")
    if ft.get("actual") is None or float(ft.get("actual") or 0.0) < 0.05:
        mismatches.append("拍对象银币投影占比缺失/近零")

    checks["mismatches"] = mismatches
    (out_dir / "blockout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "prop_subject_probe_summary.json").write_text(
        json.dumps({"checks": checks}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"ok": not mismatches, "checks": checks}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261020-prop-subject-preview"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["prop_subject_preview"] = run_probe(out_dir)
    except Exception as exc:  # noqa: BLE001
        RESULTS["prop_subject_preview"] = {
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
