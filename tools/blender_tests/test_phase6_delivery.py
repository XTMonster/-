"""Phase 6 集成测试：交付包真的产出可用素材（执行文档 v1.2 §15）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase6_delivery.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.contracts.config import DeliveryConfig  # noqa: E402
from block_director.contracts.enums import DeliveryPreset  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer8_delivery import export_project  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixtures import two_shot_plan  # noqa: E402


def demo_plan():
    return two_shot_plan()

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    ensure_collections(scene)
    return scene


def fresh_config(**overrides) -> DeliveryConfig:
    config = DeliveryConfig(preset=DeliveryPreset.HD16X9)
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _build_and_export(tmp: str, config=None):
    fresh_scene()
    summary = build_scene(demo_plan()).to_dict()
    report = export_project(demo_plan(), build_summary=summary,
                            out_dir=Path(tmp), config=config or fresh_config(),
                            project="BlockDirector")
    return summary, report


# --------------------------------------------------------------------------- #
# 1. 交付物齐全
# --------------------------------------------------------------------------- #
def t_export_produces_all_deliverables():
    tmp = tempfile.mkdtemp(prefix="bd_p6_")
    summary, report = _build_and_export(tmp)
    export_dir = Path(tmp) / "export"
    expected = [
        export_dir / "blockout_shot_001.mp4",
        export_dir / "blockout_shot_002.mp4",
        export_dir / "first_frames" / "shot_001.png",
        export_dir / "first_frames" / "shot_002.png",
        export_dir / "shots.json",
        export_dir / "prompts.md",
        export_dir / "README.md",
    ]
    missing = [str(p) for p in expected if not p.exists()]
    empty = [str(p) for p in expected if p.exists() and p.stat().st_size == 0]
    return {"ok": report.ok and not missing and not empty,
            "missing": missing, "empty": empty,
            "files": len(report.files), "total_frames": report.total_frames,
            "duration_s": report.duration_s}


# --------------------------------------------------------------------------- #
# 1b. 缺片必须判失败（v1.3 P0-6）
# --------------------------------------------------------------------------- #
def t_missing_clip_is_reported_as_failure():
    """把渲染打桩成"不产出文件"，报告必须为**失败**。

    这正是 v1.2 的假成功路径：``files`` 里仍然有 shots.json / prompts.md /
    README.md，旧实现据此返回 ``ok=True``，调用方于是以为交付成功，
    用户拿到的却是一个没有视频的空包。
    """
    from block_director.layer8_delivery import export_director

    tmp = tempfile.mkdtemp(prefix="bd_p6_miss_")
    fresh_scene()
    summary = build_scene(demo_plan()).to_dict()
    original_video = export_director.render_shot_video
    original_frame = export_director.render_first_frame
    export_director.render_shot_video = (
        lambda scene, start, end, base, codec="H264", crf="MEDIUM":
        (base, end - start + 1))
    export_director.render_first_frame = lambda scene, frame, path: False
    try:
        report = export_project(demo_plan(), build_summary=summary,
                                out_dir=Path(tmp), config=fresh_config(),
                                project="BlockDirector")
    finally:
        export_director.render_shot_video = original_video
        export_director.render_first_frame = original_frame
    payload = report.to_dict()
    return {"ok": (report.ok is False and not report.aborted
                   and len(report.missing_clips) >= 2
                   and len(payload["missing_clips"]) == len(report.missing_clips)),
            "report_ok": report.ok, "aborted": report.aborted,
            "missing": len(report.missing_clips), "files": len(report.files)}


def t_relative_out_dir_lands_in_the_asked_directory():
    """相对 ``out_dir`` 必须落在**调用方给的目录**。

    实测缺陷：以相对路径调用时，六段 mp4 被 Blender 写到了 ``C:\\runs\\...``
    （``bpy.path.abspath("//")`` 在未保存 .blend 时为空串），而报告依旧 ok。
    """
    tmp = tempfile.mkdtemp(prefix="bd_p6_rel_")
    previous = os.getcwd()
    os.chdir(tmp)
    try:
        fresh_scene()
        summary = build_scene(demo_plan()).to_dict()
        report = export_project(demo_plan(), build_summary=summary,
                                out_dir=Path("relout"), config=fresh_config(),
                                project="BlockDirector")
    finally:
        os.chdir(previous)
    landed = (Path(tmp) / "relout" / "export" / "blockout_shot_001.mp4").exists()
    return {"ok": bool(report.ok and landed),
            "out_dir": report.out_dir, "landed": landed,
            "missing": len(report.missing_clips)}


def t_compliance_report_is_shipped():
    """v1.3：交付包里要有剧本落实对照表，偏差要进告警。"""
    tmp = tempfile.mkdtemp(prefix="bd_p6_comp_")
    fresh_scene()
    summary = build_scene(demo_plan()).to_dict()
    compliance = {
        "ok": False, "declared_shot_count": 6, "plan_shot_count": 2,
        "declared_total_seconds": 33.0, "plan_total_seconds": 9.0, "fps": 24,
        "rows": [],
        "findings": [{"code": "E_SCRIPT_001", "rule": "R015",
                      "severity": "error", "target": "plan",
                      "message": "分镜表声明了 6 个镜号，计划里只有 2 个镜头",
                      "suggestion": "补齐缺失的镜号"}]}
    report = export_project(demo_plan(), build_summary=summary,
                            out_dir=Path(tmp), config=fresh_config(),
                            project="BlockDirector", compliance=compliance)
    path = Path(tmp) / "export" / "script_compliance.json"
    written = (path.exists()
               and json.loads(path.read_text(encoding="utf-8"))
               ["declared_shot_count"] == 6)
    warned = any("剧本落实审核" in item for item in report.warnings)
    return {"ok": bool(written and warned and str(path) in report.files),
            "written": written, "warned": warned,
            "warnings": list(report.warnings)}


# --------------------------------------------------------------------------- #
# 2. mp4 是真正的视频（容器魔数）
# --------------------------------------------------------------------------- #
def t_videos_are_real_mp4():
    tmp = tempfile.mkdtemp(prefix="bd_p6_")
    _build_and_export(tmp)
    export_dir = Path(tmp) / "export"
    checks = {}
    for shot in ("shot_001", "shot_002"):
        path = export_dir / f"blockout_{shot}.mp4"
        with path.open("rb") as handle:
            head = handle.read(12)
        checks[shot] = {"size": path.stat().st_size,
                        "ftyp": head[4:8] == b"ftyp",
                        "brand": head[8:12].decode("ascii", "replace")}
    return {"ok": all(c["ftyp"] and c["size"] > 1000 for c in checks.values()),
            "videos": checks}


# --------------------------------------------------------------------------- #
# 3. 清单与构建结果一致
# --------------------------------------------------------------------------- #
def t_manifest_matches_build():
    tmp = tempfile.mkdtemp(prefix="bd_p6_")
    summary, _ = _build_and_export(tmp)
    manifest = json.loads((Path(tmp) / "export" / "shots.json")
                          .read_text(encoding="utf-8"))
    built = {r["shot_id"]: r for r in summary["results"]}
    ok = manifest["resolution"] == [1280, 720] and manifest["fps"] == 24
    for shot in manifest["shots"]:
        result = built[shot["shot_id"]]
        ok = ok and shot["start_frame"] == result["start_frame"]
        ok = ok and shot["end_frame"] == result["end_frame"]
        ok = ok and shot["camera"]["name"] == result["camera"]
        ok = ok and shot["camera"]["lens"] == result["lens"]
    return {"ok": ok and manifest["total_frames"] == 216,
            "resolution": manifest["resolution"], "fps": manifest["fps"],
            "total_frames": manifest["total_frames"],
            "shots": [s["shot_id"] for s in manifest["shots"]]}


# --------------------------------------------------------------------------- #
# 4. 辅助物泄漏时导出必须中止（画面干净的硬门槛）
# --------------------------------------------------------------------------- #
def t_export_aborts_on_leak():
    tmp = tempfile.mkdtemp(prefix="bd_p6leak_")
    fresh_scene()
    summary = build_scene(demo_plan()).to_dict()

    label = bpy.data.objects.get("BD_Char_char_001_Label")
    assert label is not None, "测试前置：应有中文标签对象"
    label.hide_render = False          # 故意制造泄漏

    report = export_project(demo_plan(), build_summary=summary,
                            out_dir=Path(tmp), config=fresh_config())
    export_dir = Path(tmp) / "export"
    videos = list(export_dir.glob("*.mp4"))
    return {"ok": report.aborted and report.audit_leaks and not videos,
            "aborted": report.aborted, "leaks": report.audit_leaks,
            "reason": report.reason, "videos_written": len(videos)}


# --------------------------------------------------------------------------- #
# 5. 可选相机轨迹逐帧对齐
# --------------------------------------------------------------------------- #
def t_camera_trajectory_is_per_frame():
    tmp = tempfile.mkdtemp(prefix="bd_p6traj_")
    _build_and_export(tmp, fresh_config(export_camera_traj=True))
    path = Path(tmp) / "export" / "camera_traj.json"
    trajectory = json.loads(path.read_text(encoding="utf-8"))
    shots = {s["shot_id"]: s for s in trajectory["shots"]}
    first = shots["shot_001"]["frames"]
    ok = (len(first) == 96 and first[0]["frame"] == 1
          and first[-1]["frame"] == 96
          and len(shots["shot_002"]["frames"]) == 120)
    intrinsics = first[0]["intrinsics"]
    return {"ok": ok and intrinsics["cx"] == 640.0 and intrinsics["cy"] == 360.0,
            "shots": {k: len(v["frames"]) for k, v in shots.items()},
            "intrinsics": intrinsics, "fps": trajectory["fps"]}


# --------------------------------------------------------------------------- #
# 6. Prompt 表覆盖每个镜头
# --------------------------------------------------------------------------- #
def t_prompt_sheet_covers_every_shot():
    tmp = tempfile.mkdtemp(prefix="bd_p6prompt_")
    _build_and_export(tmp)
    sheet = (Path(tmp) / "export" / "prompts.md").read_text(encoding="utf-8")
    ok = all(token in sheet for token in
             ("## shot_001", "## shot_002",
              "blockout_shot_001.mp4", "first_frames/shot_002.png",
              "建立场景与人物关系", "推进对话"))
    return {"ok": ok, "length": len(sheet),
            "has_style": "写实电影质感" in sheet}


def main() -> int:
    capture_main_thread()
    check("export_produces_all_deliverables", t_export_produces_all_deliverables)
    check("missing_clip_is_reported_as_failure",
          t_missing_clip_is_reported_as_failure)
    check("relative_out_dir_lands_in_the_asked_directory",
          t_relative_out_dir_lands_in_the_asked_directory)
    check("compliance_report_is_shipped", t_compliance_report_is_shipped)
    check("videos_are_real_mp4", t_videos_are_real_mp4)
    check("manifest_matches_build", t_manifest_matches_build)
    check("export_aborts_on_leak", t_export_aborts_on_leak)
    check("camera_trajectory_is_per_frame", t_camera_trajectory_is_per_frame)
    check("prompt_sheet_covers_every_shot", t_prompt_sheet_covers_every_shot)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
