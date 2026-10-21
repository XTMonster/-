"""Ticket 04：Blockout 低采样 16:9 预览渲染 + 数值/视觉自检 冒烟。

链：manifest -> 体块建场景（bpy）-> 每镜首/中/末帧 16:9 低采样渲染 ->
数值/视觉自检报告。断言：分辨率/采样确定性、PNG 像素非空非全黑、报告
verdict、相机对空墙 E_BLOCKOUT_EMPTY_WALL finding、空镜合法 pass、设计
vs 实测偏差。全部结论落 BD_TEST_RESULT JSON。

运行：
blender --background --factory-startup --python tools/blender_tests/test_blockout_preview_smoke.py -- --out <dir>
"""

from __future__ import annotations

import hashlib
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
    """三镜设计：shot_001 双人对话、shot_002 空镜、shot_003 相机对准空地。"""
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "dock_market",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
            {"name": "伊恩", "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None, "motion": None,
             "gaze": None, "provenance": "plan_intent"},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            # shot_001：正面拍双人，正常构图
            {"shot_id": "shot_001", "position": [0.0, 5.0, 1.0],
             "target": [0.0, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
            # shot_002：空镜（市场通道），无主体合法
            {"shot_id": "shot_002", "position": [0.0, 5.0, 1.0],
             "target": [0.0, 0.0, 1.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
            # shot_003：声明了角色但机位在角色背后、镜头朝反方向看
            # （米迦尔在 (-0.9,0,0)，相机在 (-0.9,-5,1) 朝 y 负向更远处看 ->
            # 主体投影在相机背后，画面里是空地 -> E_BLOCKOUT_EMPTY_WALL）
            {"shot_id": "shot_003", "position": [-0.9, -5.0, 1.0],
             "target": [-0.9, -10.0, 0.0], "lens": 35.0, "fov_deg": 54.4,
             "provenance": "algorithmic_measurement", "resolved": True},
        ],
        "notes": ["T04 预览冒烟设计快照"],
    }


def _plan():
    from block_director.contracts.plan import Plan, ShotPlan

    return Plan(shots=[
        ShotPlan(
            shot_id="shot_001", intent="双人对话", shot_type="MS",
            duration_frames=24, order=1, characters=["米迦尔", "伊恩"],
            camera={"side": "front", "lens": 35,
                    "movements": [{"type": "dolly_in"}]},
        ),
        ShotPlan(
            shot_id="shot_002", intent="空镜：市场通道", shot_type="MS",
            duration_frames=12, order=2, characters=[],
            camera={"lens": 35},
        ),
        ShotPlan(
            shot_id="shot_003", intent="错误机位：对准空地", shot_type="MS",
            duration_frames=12, order=3, characters=["米迦尔"],
            camera={"lens": 35},
        ),
    ])


def _png_not_blank(path: Path) -> bool:
    """PNG 非空且非全黑（有用例渲染，像素有内容）。"""
    if not path.exists() or path.stat().st_size == 0:
        return False
    image = bpy.data.images.load(str(path), check_existing=True)
    width, height = image.size
    if width <= 0 or height <= 0:
        return False
    pixels = list(image.pixels)
    #: 任一像素 RGB 通道有非零值即视为非全黑
    return any(p > 0.01 for p in pixels[0::4])


def _png_sample_digest(path: Path) -> str:
    """Hash a deterministic pixel sample, independent of PNG metadata."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        pixels = image.pixels
        #: 257 is coprime with the 4-channel stride and the common row sizes,
        #: so this samples all channels across the frame without loading a
        #: second full Python copy of the 1280x720 image.
        sample = b"".join(
            int(max(0.0, min(1.0, float(pixels[index]))) * 65535.0).to_bytes(
                2, "little")
            for index in range(0, len(pixels), 257))
        return hashlib.sha256(sample).hexdigest()
    finally:
        bpy.data.images.remove(image)


def run_smoke(out_dir: Path) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest
    from block_director.layer3_engine.blockout_scene import (
        BD_BLOCKOUT_PREFIX,
        build_blockout_scene,
    )
    from block_director.layer8_delivery.blockout_preview import (
        PREVIEW_HEIGHT,
        PREVIEW_WIDTH,
        render_blockout_preview,
    )
    from block_director.cinema.blockout_report import (
        E_BLOCKOUT_EMPTY_WALL,
    )
    from block_director.contracts.blockout import manifest_fingerprint

    manifest = build_blockout_manifest(design=_design(), plan=_plan())
    build_blockout_scene(manifest, clear_scene=True)

    result = render_blockout_preview(manifest, out_dir)
    report = result["report"]
    previews = result["previews"]

    checks: dict = {}
    mismatches: list = []

    #: 1. 分辨率与采样确定性
    scene = bpy.context.scene
    checks["resolution"] = [scene.render.resolution_x,
                            scene.render.resolution_y]
    if (scene.render.resolution_x, scene.render.resolution_y) != (
            PREVIEW_WIDTH, PREVIEW_HEIGHT):
        mismatches.append("预览分辨率非 16:9 1280x720")
    checks["resolution_percentage"] = scene.render.resolution_percentage

    #: 2. 渲染帧：每镜首/中/末 3 帧，PNG 非空且非全黑
    expected_frames = 3 * len([c for c in manifest["cameras"]])
    checks["render_frame_count"] = len(previews)
    checks["png_count"] = len(list((out_dir / "preview").glob("*.png")))
    if len(previews) != expected_frames:
        mismatches.append(
            f"渲染帧数 {len(previews)} != {expected_frames}")
    blank = [p for p in previews if not _png_not_blank(Path(p["png"]))]
    if blank:
        mismatches.append(f"全黑/空 PNG {len(blank)} 张")
    shot001 = [p for p in previews if p["shot_id"] == "shot_001"]
    shot001_digests = [_png_sample_digest(Path(p["png"])) for p in shot001]
    checks["shot001_pixel_digests"] = shot001_digests
    if len(set(shot001_digests)) != len(shot001_digests):
        mismatches.append("shot_001 首/中/末帧像素相同，运镜未进入视觉证据")

    #: 3. 报告结构：schema 版本、verdict、checks/findings/visual_states
    from block_director.contracts.blockout import (
        BLOCKOUT_REPORT_SCHEMA_VERSION,
    )
    checks["report_schema"] = report["schema_version"]
    if report["schema_version"] != BLOCKOUT_REPORT_SCHEMA_VERSION:
        mismatches.append("报告 schema 版本不符")
    checks["report_verdict"] = report["verdict"]
    checks["report_checks"] = len(report["checks"])
    checks["report_findings"] = len(report["findings"])
    checks["visual_states"] = len(report["visual_states"])
    if not report["checks"]:
        mismatches.append("报告 checks 为空")

    #: 4. 空镜 shot_002 合法（无主体 -> 无空墙 finding）
    shot002 = [c for c in report["checks"] if c["shot_id"] == "shot_002"]
    checks["shot002_checks"] = len(shot002)
    shot002_empty_wall = [
        f for f in report["findings"]
        if f.get("shot_id") == "shot_002"
        and f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    if shot002_empty_wall:
        mismatches.append("空镜被误判为空墙")

    #: 5. 相机对空墙 shot_003 必须出 E_BLOCKOUT_EMPTY_WALL finding
    shot003_empty_wall = [
        f for f in report["findings"]
        if f.get("shot_id") == "shot_003"
        and f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    checks["shot003_empty_wall"] = len(shot003_empty_wall)
    if not shot003_empty_wall:
        mismatches.append("shot_003 相机对空地未报空墙 finding")

    #: 6. 设计 vs 实测偏差：manifest 机位起点与场景实测一致（运镜在镜内移动，
    #:    起点是基准，偏差应 < 0.3 m）
    for check in report["checks"]:
        if check["check_id"] == "design_vs_observed":
            if check["verdict"] != "pass":
                mismatches.append(
                    f"{check['shot_id']} 设计偏差 {check['actual']} 超限")

    #: 7. 指纹可复现 + 重放零 LLM：报告携带 manifest 指纹，且与契约同源
    checks["manifest_fingerprint"] = report["manifest_fingerprint"]
    if report["manifest_fingerprint"] != manifest_fingerprint(manifest):
        mismatches.append("报告 manifest 指纹与契约不同源")

    checks["summary"] = result["settings"]
    checks["mismatches"] = mismatches

    (out_dir / "blockout_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "blockout_preview_summary.json").write_text(
        json.dumps({"settings": result["settings"],
                    "checks": checks}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    return {
        "ok": not mismatches,
        "checks": checks,
        "outputs": {
            "report": str(out_dir / "blockout_report.json"),
            "preview_summary": str(out_dir / "blockout_preview_summary.json"),
            "preview_dir": str(out_dir / "preview"),
        },
    }


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261018-blockout-preview-smoke"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        fresh_scene()
        RESULTS["blockout_preview_smoke"] = run_smoke(out_dir)
    except Exception as exc:  # noqa: BLE001 - 冒烟归一为结果记录
        RESULTS["blockout_preview_smoke"] = {
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
