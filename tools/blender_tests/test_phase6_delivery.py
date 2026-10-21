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
from block_director.contracts.enums import DeliveryPreset, RenderBackend  # noqa: E402
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
        export_dir / "blockout_full.mp4",
        export_dir / "first_frames" / "shot_001.png",
        export_dir / "first_frames" / "shot_002.png",
        export_dir / "shots.json",
        export_dir / "prompts.md",
        export_dir / "README.md",
    ]
    #: v1.7 I3：reference_pack 五件套（默认 seedance_2.5）＋ continuity.json 可解析。
    pack_dir = export_dir / "reference_pack"
    pack_expected = [
        pack_dir / "README.md",
        pack_dir / "prompt_seedance_2.5.txt",
        pack_dir / "shot_cards.md",
        pack_dir / "continuity.json",
        pack_dir / "responsibility.md",
    ]
    missing = [str(p) for p in expected if not p.exists()]
    empty = [str(p) for p in expected if p.exists() and p.stat().st_size == 0]
    missing.extend(str(p) for p in pack_expected if not p.exists())
    empty.extend(str(p) for p in pack_expected
                 if p.exists() and p.stat().st_size == 0)
    continuity_shots: list = []
    continuity_path = pack_dir / "continuity.json"
    if continuity_path.exists():
        continuity_shots = sorted(json.loads(
            continuity_path.read_text(encoding="utf-8")))
    continuity_ok = continuity_shots == ["shot_001", "shot_002"]
    payload = report.to_dict()
    legacy_unscoped = (
        payload["delivery_class"] == ""
        and payload["delivery_quality"] == {}
        and payload["final"] is False
        and not (export_dir / "blockout_partial.mp4").exists()
        and not (export_dir / "blockout_diagnostic.mp4").exists()
        and not (export_dir / "final_video.mp4").exists()
        and not (export_dir / "delivery_quality.json").exists()
    )
    return {"ok": (report.ok and not missing and not empty and continuity_ok
                   and legacy_unscoped),
            "missing": missing, "empty": empty,
            "files": len(report.files), "total_frames": report.total_frames,
            "duration_s": report.duration_s,
            "continuity_shots": continuity_shots,
            "legacy_unscoped": legacy_unscoped}


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
                   and len(payload["missing_clips"]) == len(report.missing_clips)
                   and payload["delivered_shots"] == []
                   and payload["passed_shots"] == []
                   and all(shot["video"] is None
                           for shot in payload["shots"])),
            "report_ok": report.ok, "aborted": report.aborted,
            "missing": len(report.missing_clips), "files": len(report.files),
            "delivered_shots": payload.get("delivered_shots"),
            "passed_shots": payload.get("passed_shots"),
            "shot_videos": [shot.get("video")
                            for shot in payload.get("shots", [])]}


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


def _pixels(path: Path):
    image = bpy.data.images.load(str(path))
    try:
        return list(image.pixels)
    finally:
        bpy.data.images.remove(image)


def _differing_pixels(first, second, threshold: float = 0.02) -> int:
    """两张图里差异明显的像素数（比整幅平均亮度敏感得多）。"""
    count = 0
    for index in range(0, min(len(first), len(second)), 4):
        if (abs(first[index] - second[index]) > threshold
                or abs(first[index + 1] - second[index + 1]) > threshold
                or abs(first[index + 2] - second[index + 2]) > threshold):
            count += 1
    return count


def t_render_labels_are_visible_sized_and_excluded_from_stills():
    """v1.3 诉求 4 的量化验收。

    * 标签确实改变画面（否则等于没做）；
    * 屏幕字号落在可读区间（否则"看得清"只是口头承诺）；
    * 首帧 PNG 与"带标签"的渲染**不一样**（标签不进输入图）。
    """
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    from block_director.layer3_engine.collection_router import (
        CONTENT_COLLECTION,
        LABELS_COLLECTION,
        audit_renderable_objects,
        label_pair_audit,
        labels_collection,
        route_object,
    )
    from block_director.layer8_delivery.renderer import render_first_frame

    tmp = tempfile.mkdtemp(prefix="bd_p6_label_")
    _summary, report = _build_and_export(tmp)
    export_dir = Path(tmp) / "export"
    labels = labels_collection()

    fills = [o for o in bpy.data.objects
             if str(o.get("bd_label_role") or "") == "fill"]
    strokes = [o for o in bpy.data.objects
               if str(o.get("bd_label_role") or "") == "stroke"]
    # v1.4 X4 / §1.6 #4：白名单必须是"集合 + 命名 + 数量"，不能再读对象自报的
    # ``bd_element_type``（那是自证）。这里独立重算期望命名集合。
    expected_names = set()
    for character in ("char_001", "char_002"):
        for role in ("Fill", "Stroke"):
            expected_names.add(f"BD_Label_{character}_{role}")
    in_labels = {o.name for o in labels.objects} if labels else set()
    pair_audit = label_pair_audit()
    whitelisted = (in_labels == expected_names
                   and pair_audit["count"] == 2
                   and pair_audit["problems"] == []
                   and audit_renderable_objects() == [])
    # 负例：把同一个标签对象挪进 Content（名字照旧、bd_element_type 照旧），
    # 审计必须重新判它是泄漏 —— 证明白名单靠的是集合与命名，不是自报字段。
    moved = None
    if fills:
        moved = fills[0]
        route_object(moved, CONTENT_COLLECTION)
        negative_leak = moved.name in audit_renderable_objects()
        route_object(moved, LABELS_COLLECTION)
    else:  # pragma: no cover - 没有标签时上面已经判失败
        negative_leak = False
    whitelisted = whitelisted and negative_leak

    scene = bpy.context.scene
    scene.frame_set(1)
    bpy.context.view_layer.update()
    camera = scene.camera
    fill = fills[0]
    # matrix_world 里**已经含**缩放，所以局部端点只写 glyph 尺寸的一半；
    # 再乘一次 scale 会把高度按 scale 缩小（实测 30px 被量成 19px）。
    half = float(fill.data.size) / 2.0
    top = fill.matrix_world @ Vector((0.0, half, 0.0))
    bottom = fill.matrix_world @ Vector((0.0, -half, 0.0))
    pixels = abs(world_to_camera_view(scene, camera, top).y
                 - world_to_camera_view(scene, camera, bottom).y) \
        * scene.render.resolution_y

    exported = _pixels(export_dir / "first_frames" / "shot_001.png")
    with_labels = export_dir / "_probe_with_labels.png"
    without_labels = export_dir / "_probe_without_labels.png"
    labels.hide_render = False
    render_first_frame(scene, 1, str(with_labels))
    labels.hide_render = True
    render_first_frame(scene, 1, str(without_labels))
    labels.hide_render = False

    pixels_with = _pixels(with_labels)
    pixels_without = _pixels(without_labels)
    labeled_pixels = _differing_pixels(pixels_with, pixels_without)
    exported_vs_labeled = _differing_pixels(exported, pixels_with)
    exported_vs_clean = _differing_pixels(exported, pixels_without)
    changes_image = labeled_pixels > 200
    still_is_clean = exported_vs_clean < 50 and exported_vs_labeled > 200

    return {"ok": bool(report.ok and labels is not None
                       and not labels.hide_render
                       and len(fills) >= 2 and len(fills) == len(strokes)
                       and whitelisted
                       and 20.0 <= pixels <= 70.0
                       and changes_image and still_is_clean),
            "labels": len(fills), "pixel_height": round(pixels, 1),
            "whitelisted": whitelisted,
            "labeled_pixels": labeled_pixels,
            "exported_vs_labeled": exported_vs_labeled,
            "exported_vs_clean": exported_vs_clean,
            "changes_image": changes_image, "still_is_clean": still_is_clean}


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
    path_counts = {}
    narrations = {}
    for shot in manifest["shots"]:
        result = built[shot["shot_id"]]
        ok = ok and shot["start_frame"] == result["start_frame"]
        ok = ok and shot["end_frame"] == result["end_frame"]
        ok = ok and shot["camera"]["name"] == result["camera"]
        ok = ok and shot["camera"]["lens"] == result["lens"]
        #: v1.7 I3：camera_narration 必须与 build_summary 对齐（写盘前接线
        #: 同一份 result 写两边），paths 键集一致。
        ok = ok and shot["camera_narration"] == result.get("camera_narration")
        ok = ok and set((shot.get("paths") or {}).keys()) \
            == set((result.get("paths") or {}).keys())
        #: v1.7 I3：paths 每角色 9 点、camera_narration 非空（写盘前接线）。
        paths = shot.get("paths") or {}
        path_counts[shot["shot_id"]] = [len(points)
                                        for points in paths.values()]
        narration = str(shot.get("camera_narration") or "").strip()
        narrations[shot["shot_id"]] = narration
        ok = ok and bool(paths) and all(count == 9 for count in path_counts[shot["shot_id"]])
        ok = ok and bool(narration)
    return {"ok": ok and manifest["total_frames"] == 216,
            "resolution": manifest["resolution"], "fps": manifest["fps"],
            "total_frames": manifest["total_frames"],
            "shots": [s["shot_id"] for s in manifest["shots"]],
            "path_counts": path_counts, "narrations": narrations}


# --------------------------------------------------------------------------- #
# 4. 辅助物泄漏时导出必须中止（画面干净的硬门槛）
# --------------------------------------------------------------------------- #
def t_export_aborts_on_leak():
    """Guides 里的辅助物一旦可渲染，导出必须中止。

    v1.3 起标签默认走 BlockDirector/Labels（**要**进参考视频），
    所以这里显式关掉渲染标签，回到"Guides 标签被误设为可渲染"这条老路径——
    这正是 §15.2 要防的事故。
    """
    from block_director.settings import get_config

    app_config = get_config()
    previous = app_config.character.label_render
    tmp = tempfile.mkdtemp(prefix="bd_p6leak_")
    try:
        app_config.character.label_render = False
        fresh_scene()
        summary = build_scene(demo_plan()).to_dict()

        label = bpy.data.objects.get("BD_Char_char_001_Label")
        assert label is not None, "测试前置：关掉渲染标签后应有 Guides 标签"
        label.hide_render = False          # 故意制造泄漏

        report = export_project(demo_plan(), build_summary=summary,
                                out_dir=Path(tmp), config=fresh_config())
    finally:
        app_config.character.label_render = previous
    export_dir = Path(tmp) / "export"
    videos = list(export_dir.glob("*.mp4"))
    return {"ok": report.aborted and report.audit_leaks and not videos,
            "aborted": report.aborted, "leaks": report.audit_leaks,
            "reason": report.reason, "videos_written": len(videos)}


def t_blocked_quality_creates_no_delivery_tree():
    with tempfile.TemporaryDirectory(prefix="bd_blocked_export_") as tmp:
        out_dir = Path(tmp) / "requested"
        report = export_project(
            demo_plan(),
            out_dir=out_dir,
            config=fresh_config(),
            project="BlockDirector",
            delivery_quality={
                "schema_version": "quality-contract/v1",
                "delivery_class": "blocked",
                "reasons": ["authoritative_evidence_store_unavailable"],
                "selected_shots": ["shot_001", "shot_002"],
                "passed_shots": [],
                "failed_shots": [],
                "pending_review_shots": [],
            },
        )
        assert report.aborted, report.to_dict()
        assert report.delivery_class == "blocked"
        assert not out_dir.exists(), list(out_dir.rglob("*"))
        return {
            "ok": True,
            "reason": report.reason,
        }


def t_blocked_quality_clears_stale_concat_identities():
    with tempfile.TemporaryDirectory(prefix="bd_blocked_stale_") as tmp:
        fresh_scene()
        out_dir = Path(tmp) / "requested"
        export_dir = out_dir / "export"
        export_dir.mkdir(parents=True)
        stale_names = (
            "blockout_full.mp4",
            "blockout_partial.mp4",
            "blockout_diagnostic.mp4",
            "final_video.mp4",
        )
        for name in stale_names:
            (export_dir / name).write_bytes(b"stale")
        unrelated = export_dir / "notes.txt"
        unrelated.write_text("keep", encoding="utf-8")

        report = export_project(
            demo_plan(),
            out_dir=out_dir,
            config=fresh_config(),
            project="BlockDirector",
            delivery_quality={
                "schema_version": "quality-contract/v1",
                "delivery_class": "blocked",
                "reasons": ["authoritative_evidence_store_unavailable"],
                "selected_shots": ["shot_001", "shot_002"],
                "passed_shots": [],
                "failed_shots": [],
                "pending_review_shots": [],
            },
        )

        stale = [name for name in stale_names
                 if (export_dir / name).exists()]
        ok = (
            report.aborted
            and report.delivery_class == "blocked"
            and not stale
            and unrelated.read_text(encoding="utf-8") == "keep"
        )
        return {"ok": ok, "stale": stale, "reason": report.reason}


def t_sequence_render_rejects_missing_shot_file_and_clears_stale_clips():
    from block_director.layer8_delivery import blockout_sequence

    with tempfile.TemporaryDirectory(prefix="bd_missing_shot_video_") as tmp:
        fresh_scene()
        out_dir = Path(tmp) / "delivery"
        video_dir = out_dir / blockout_sequence.SHOT_VIDEO_DIRNAME
        video_dir.mkdir(parents=True)
        stale = video_dir / "blockout_shot_009.mp4"
        stale.write_bytes(b"stale")
        claimed = video_dir / "blockout_shot_001.mp4"
        original_render = blockout_sequence.render_shot_video

        def _missing_render(*_args, **_kwargs):
            return str(claimed), 2

        manifest = {
            "cameras": [{
                "shot_id": "shot_001",
                "camera_id": "missing",
                "start_frame": 1,
                "end_frame": 2,
            }],
            "shot_table": [],
            "primitives": [],
        }
        blockout_sequence.render_shot_video = _missing_render
        try:
            rendered = blockout_sequence.render_blockout_sequence_video(
                manifest,
                out_dir,
                delivery_class="diagnostic",
            )
        finally:
            blockout_sequence.render_shot_video = original_render

        ok = (
            rendered.get("path") is None
            and rendered.get("full_path") is None
            and rendered.get("shot_videos") == []
            and [item.get("shot_id")
                 for item in rendered.get("missing_shots") or []]
            == ["shot_001"]
            and not stale.exists()
            and not claimed.exists()
            and not (out_dir / "blockout_diagnostic.mp4").exists()
        )
        return {
            "ok": ok,
            "path": rendered.get("path"),
            "shot_videos": rendered.get("shot_videos"),
            "missing_shots": rendered.get("missing_shots"),
            "stale_exists": stale.exists(),
        }


def t_partial_reuse_clears_stale_omitted_shot_artifacts_and_claims():
    from block_director.layer8_delivery import export_director

    with tempfile.TemporaryDirectory(prefix="bd_partial_reuse_") as tmp:
        fresh_scene()
        plan = demo_plan()
        summary = build_scene(plan).to_dict()
        export_dir = Path(tmp) / "export"
        first_frames = export_dir / "first_frames"
        depth = export_dir / "depth_shot_shot_002"
        masks = export_dir / "masks" / "shot_002"
        for folder in (first_frames, depth, masks):
            folder.mkdir(parents=True)
        stale_001 = export_dir / "blockout_shot_001.mp4"
        stale_002 = export_dir / "blockout_shot_002.mp4"
        stale_first_002 = first_frames / "shot_002.png"
        for path in (stale_001, stale_002, stale_first_002):
            path.write_bytes(b"stale")
        (depth / "frame_0001.png").write_bytes(b"stale")
        (masks / "frame_0001.png").write_bytes(b"stale")
        unrelated = export_dir / "notes.txt"
        unrelated.write_text("keep", encoding="utf-8")
        original_render = export_director.render_shot_video

        def _missing_render(_scene, _start, _end, base, **_kwargs):
            return str(base), 2

        quality = {
            "schema_version": "quality-contract/v1",
            "component": "delivery",
            "delivery_class": "partial",
            "reasons": ["failed_shots_omitted_from_partial_delivery"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "selected_shots": ["shot_001"],
            "sequence_reviewed_shots": ["shot_001"],
            "sequence_review_passed": True,
            "full_sequence_review_passed": False,
            "subset_sequence_review_passed": True,
            "delivered_shots": [],
            "artifact_check_complete": False,
            "adoption_explanations": {},
            "blocked_shots": {},
        }
        export_director.render_shot_video = _missing_render
        try:
            report = export_project(
                plan,
                build_summary=summary,
                out_dir=Path(tmp),
                config=fresh_config(
                    mask_pass=False,
                    reference_cards=False,
                    export_depth=False,
                ),
                project="BlockDirector",
                delivery_quality=quality,
            )
        finally:
            export_director.render_shot_video = original_render

        ok = (
            report.aborted
            and report.canonical_delivery_class == "blocked"
            and "delivered_artifact_set_mismatch"
            in report.delivery_quality.get("reasons", [])
            and not stale_001.exists()
            and not stale_002.exists()
            and not stale_first_002.exists()
            and not depth.exists()
            and not masks.exists()
            and unrelated.read_text(encoding="utf-8") == "keep"
        )
        return {
            "ok": ok,
            "delivery_class": report.canonical_delivery_class,
            "reasons": report.delivery_quality.get("reasons"),
        }


def t_partial_quality_identity_is_consistent_across_the_package():
    with tempfile.TemporaryDirectory(prefix="bd_partial_identity_") as tmp:
        fresh_scene()
        plan = demo_plan()
        summary = build_scene(plan).to_dict()
        quality = {
            "schema_version": "quality-contract/v1",
            "component": "delivery",
            "delivery_class": "partial",
            "reasons": ["failed_shots_omitted_from_partial_delivery"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "selected_shots": ["shot_001"],
            "sequence_reviewed_shots": ["shot_001"],
            "sequence_review_passed": True,
            "full_sequence_review_passed": False,
            "subset_sequence_review_passed": True,
            "delivered_shots": [],
            "artifact_check_complete": False,
            "adoption_explanations": {},
            "blocked_shots": {},
        }
        report = export_project(
            plan,
            build_summary=summary,
            out_dir=Path(tmp),
            config=fresh_config(
                mask_pass=False,
                reference_cards=False,
            ),
            project="BlockDirector",
            failures={
                "schema_version": "delivery-failures/v1",
                "failures": [{
                    "shot_id": "shot_002",
                    "best_score": 80.0,
                    "no_gain_rounds": 3,
                    "reason": "strict boundary not passed",
                }],
                "pending_review": [],
            },
            delivery_quality=quality,
        )
        export_dir = Path(tmp) / "export"
        manifest = json.loads(
            (export_dir / "shots.json").read_text(encoding="utf-8"))
        failures = json.loads(
            (export_dir / "failures.json").read_text(encoding="utf-8"))
        written_quality = json.loads(
            (export_dir / "delivery_quality.json").read_text(encoding="utf-8"))
        readme = (export_dir / "README.md").read_text(encoding="utf-8")
        prompts = (export_dir / "prompts.md").read_text(encoding="utf-8")
        rows = {row["shot_id"]: row for row in manifest["shots"]}
        checks = {
            "report_ok": report.ok,
            "report_partial": report.delivery_class == "partial",
            "report_not_final": report.to_dict()["final"] is False,
            "report_video_identity": (
                Path(report.full_video).name == "blockout_partial.mp4"),
            "artifact_check_complete": (
                report.delivery_quality["artifact_check_complete"] is True),
            "quality_partial": written_quality["delivery_class"] == "partial",
            "quality_delivery_exact": (
                written_quality["delivered_shots"] == ["shot_001"]),
            "manifest_partial": manifest["delivery"]["class"] == "partial",
            "manifest_delivery_exact": (
                manifest["delivery"]["delivered_shots"] == ["shot_001"]),
            "passed_included": (
                rows["shot_001"]["delivery_status"] == "passed"
                and rows["shot_001"]["delivery_included"] is True),
            "failed_omitted": (
                rows["shot_002"]["delivery_status"] == "failed"
                and rows["shot_002"]["delivery_included"] is False
                and rows["shot_002"]["video_file"] is None
                and rows["shot_002"]["first_frame"] is None),
            "failures_aligned": (
                failures["delivery_class"] == "partial"
                and failures["selected_shots"] == ["shot_001"]
                and [item["shot_id"] for item in failures["failures"]]
                == ["shot_002"]),
            "readme_partial": (
                "交付身份：**partial**" in readme
                and "已从 PARTIAL 成片中省略失败镜头：shot_002" in readme),
            "prompts_omitted": (
                "未包含在本次 PARTIAL 交付包" in prompts),
            "partial_video_only": (
                (export_dir / "blockout_partial.mp4").is_file()
                and not (export_dir / "blockout_full.mp4").exists()
                and not (export_dir / "final_video.mp4").exists()),
            "omitted_assets_absent": (
                not (export_dir / "blockout_shot_002.mp4").exists()
                and not (
                    export_dir / "first_frames" / "shot_002.png").exists()),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise AssertionError(
                f"partial identity mismatch: {failed}; "
                f"report={report.to_dict()}; quality={written_quality}")
        return {
            "ok": True,
            "delivery_class": report.delivery_class,
            "selected_shots": written_quality["selected_shots"],
        }


def t_partial_mask_pass_uses_only_selected_built_ranges():
    """Partial delivery must carry exactly the selected built ranges into masks.

    The delivery report and masks share one frame schedule. A selected subset
    therefore cannot fall back to the plan-wide schedule, and an omitted shot
    must not gain a mask directory.
    """
    from block_director.layer8_delivery import export_director, mask_pass

    with tempfile.TemporaryDirectory(prefix="bd_partial_mask_") as tmp:
        fresh_scene()
        plan = demo_plan()
        summary = build_scene(plan).to_dict()
        results = {
            str(item["shot_id"]): item
            for item in summary.get("results") or []
        }
        selected_range = (
            int(results["shot_001"]["start_frame"]),
            int(results["shot_001"]["end_frame"]),
        )
        quality = {
            "schema_version": "quality-contract/v1",
            "component": "delivery",
            "delivery_class": "partial",
            "reasons": ["failed_shots_omitted_from_partial_delivery"],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "selected_shots": ["shot_001"],
            "sequence_reviewed_shots": ["shot_001"],
            "sequence_review_passed": True,
            "full_sequence_review_passed": False,
            "subset_sequence_review_passed": True,
            "delivered_shots": [],
            "artifact_check_complete": False,
            "adoption_explanations": {},
            "blocked_shots": {},
        }
        original_video = export_director.render_shot_video
        original_still = export_director.render_first_frame
        original_mask_render = mask_pass._render_animation

        def fake_video(_scene, start_frame, end_frame, base_path, **_kwargs):
            path = Path(base_path)
            path.write_bytes(b"BD_FAKE_MP4")
            return str(path), int(end_frame) - int(start_frame) + 1

        def fake_still(_scene, _frame, path):
            Path(path).write_bytes(b"BD_FAKE_PNG")
            return True

        def fake_mask_render(scene):
            prefix = str(scene.render.filepath)
            for frame in range(int(scene.frame_start),
                               int(scene.frame_end) + 1):
                Path(f"{prefix}{frame:04d}.png").write_bytes(b"BD_FAKE_MASK")

        export_director.render_shot_video = fake_video
        export_director.render_first_frame = fake_still
        mask_pass._render_animation = fake_mask_render
        try:
            report = export_project(
                plan,
                build_summary=summary,
                out_dir=Path(tmp),
                config=fresh_config(
                    render_backend=RenderBackend.EEVEE,
                    mask_pass=True,
                    reference_cards=False,
                    export_depth=False,
                    full_concat=False,
                ),
                project="BlockDirector",
                delivery_quality=quality,
            )
        finally:
            export_director.render_shot_video = original_video
            export_director.render_first_frame = original_still
            mask_pass._render_animation = original_mask_render

        export_dir = Path(tmp) / "export"
        mask_shots = {
            str(item["shot_id"]): item for item in report.mask_shots
        }
        checks = {
            "report_ok": report.ok,
            "partial_identity": report.delivery_class == "partial",
            "selected_only": list(mask_shots) == ["shot_001"],
            "built_range": (
                mask_shots["shot_001"]["start_frame"],
                mask_shots["shot_001"]["end_frame"],
            ) == selected_range,
            "omitted_mask_absent": not (
                export_dir / "masks" / "shot_002").exists(),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise AssertionError(
                f"partial mask mismatch: {failed}; "
                f"selected_range={selected_range}; "
                f"mask_shots={mask_shots}; report={report.to_dict()}")
        return {
            "ok": True,
            "delivery_class": report.delivery_class,
            "mask_shots": mask_shots,
        }


def t_diagnostic_quality_identity_is_consistent_across_the_package():
    with tempfile.TemporaryDirectory(prefix="bd_diagnostic_identity_") as tmp:
        fresh_scene()
        plan = demo_plan()
        summary = build_scene(plan).to_dict()
        quality = {
            "schema_version": "quality-contract/v1",
            "component": "delivery",
            "delivery_class": "diagnostic",
            "reasons": [
                "failed_shots_require_diagnostic_delivery",
                "full_sequence_review_not_passed",
            ],
            "passed_shots": ["shot_001"],
            "failed_shots": ["shot_002"],
            "pending_review_shots": [],
            "selected_shots": ["shot_001", "shot_002"],
            "sequence_reviewed_shots": [],
            "sequence_review_passed": False,
            "full_sequence_review_passed": False,
            "subset_sequence_review_passed": False,
            "delivered_shots": [],
            "artifact_check_complete": False,
            "adoption_explanations": {
                "shot_002": "composition_not_strictly_above_threshold",
            },
            "blocked_shots": {},
        }
        report = export_project(
            plan,
            build_summary=summary,
            out_dir=Path(tmp),
            config=fresh_config(mask_pass=False, reference_cards=False),
            project="BlockDirector",
            failures={
                "schema_version": "delivery-failures/v1",
                "failures": [{
                    "shot_id": "shot_002",
                    "best_score": 79.0,
                    "no_gain_rounds": 3,
                    "reason": "composition did not pass",
                }],
                "pending_review": [],
            },
            delivery_quality=quality,
        )
        export_dir = Path(tmp) / "export"
        manifest = json.loads(
            (export_dir / "shots.json").read_text(encoding="utf-8"))
        failures = json.loads(
            (export_dir / "failures.json").read_text(encoding="utf-8"))
        written_quality = json.loads(
            (export_dir / "delivery_quality.json").read_text(
                encoding="utf-8"))
        readme = (export_dir / "README.md").read_text(encoding="utf-8")
        prompts = (export_dir / "prompts.md").read_text(encoding="utf-8")
        rows = {row["shot_id"]: row for row in manifest["shots"]}
        checks = {
            "report_ok": report.ok,
            "report_diagnostic": (
                report.canonical_delivery_class == "diagnostic"),
            "report_not_final": report.to_dict()["final"] is False,
            "report_video_identity": (
                Path(report.full_video).name == "blockout_diagnostic.mp4"),
            "artifact_check_complete": (
                report.delivery_quality["artifact_check_complete"] is True),
            "quality_diagnostic": (
                written_quality["delivery_class"] == "diagnostic"),
            "quality_delivery_exact": (
                written_quality["delivered_shots"]
                == ["shot_001", "shot_002"]),
            "manifest_diagnostic": (
                manifest["delivery"]["class"] == "diagnostic"),
            "manifest_delivery_exact": (
                manifest["delivery"]["delivered_shots"]
                == ["shot_001", "shot_002"]),
            "shot_dispositions": (
                rows["shot_001"]["delivery_status"] == "passed"
                and rows["shot_002"]["delivery_status"] == "failed"
                and rows["shot_001"]["delivery_included"] is True
                and rows["shot_002"]["delivery_included"] is True),
            "failures_aligned": (
                failures["delivery_class"] == "diagnostic"
                and failures["selected_shots"]
                == ["shot_001", "shot_002"]
                and [item["shot_id"] for item in failures["failures"]]
                == ["shot_002"]),
            "readme_diagnostic": (
                "交付身份：**diagnostic**" in readme
                and "DIAGNOSTIC 最佳努力版本" in readme),
            "prompts_diagnostic": (
                "- 交付身份：**diagnostic**" in prompts),
            "diagnostic_video_only": (
                (export_dir / "blockout_diagnostic.mp4").is_file()
                and not (export_dir / "blockout_full.mp4").exists()
                and not (export_dir / "blockout_partial.mp4").exists()
                and not (export_dir / "final_video.mp4").exists()),
            "all_inspection_assets_present": (
                (export_dir / "blockout_shot_001.mp4").is_file()
                and (export_dir / "blockout_shot_002.mp4").is_file()
                and (export_dir / "first_frames" / "shot_001.png").is_file()
                and (export_dir / "first_frames" / "shot_002.png").is_file()),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise AssertionError(
                f"diagnostic identity mismatch: {failed}; "
                f"report={report.to_dict()}; quality={written_quality}")
        return {
            "ok": True,
            "delivery_class": report.delivery_class,
            "selected_shots": written_quality["selected_shots"],
        }


def t_final_quality_identity_is_consistent_across_the_package():
    with tempfile.TemporaryDirectory(prefix="bd_final_identity_") as tmp:
        fresh_scene()
        plan = demo_plan()
        summary = build_scene(plan).to_dict()
        quality = {
            "schema_version": "quality-contract/v1",
            "component": "delivery",
            "delivery_class": "final",
            "reasons": [],
            "passed_shots": ["shot_001", "shot_002"],
            "failed_shots": [],
            "pending_review_shots": [],
            "selected_shots": ["shot_001", "shot_002"],
            "sequence_reviewed_shots": ["shot_001", "shot_002"],
            "sequence_review_passed": True,
            "full_sequence_review_passed": True,
            "subset_sequence_review_passed": False,
            "delivered_shots": [],
            "artifact_check_complete": False,
            "adoption_explanations": {},
            "blocked_shots": {},
        }
        report = export_project(
            plan,
            build_summary=summary,
            out_dir=Path(tmp),
            config=fresh_config(mask_pass=False, reference_cards=False),
            project="BlockDirector",
            delivery_quality=quality,
        )
        export_dir = Path(tmp) / "export"
        manifest = json.loads(
            (export_dir / "shots.json").read_text(encoding="utf-8"))
        written_quality = json.loads(
            (export_dir / "delivery_quality.json").read_text(
                encoding="utf-8"))
        readme = (export_dir / "README.md").read_text(encoding="utf-8")
        rows = {row["shot_id"]: row for row in manifest["shots"]}
        checks = {
            "report_ok": report.ok,
            "report_final": report.canonical_delivery_class == "final",
            "report_final_flag": report.to_dict()["final"] is True,
            "report_video_identity": (
                Path(report.full_video).name == "blockout_full.mp4"),
            "artifact_check_complete": (
                report.delivery_quality["artifact_check_complete"] is True),
            "quality_final": written_quality["delivery_class"] == "final",
            "quality_delivery_exact": (
                written_quality["delivered_shots"]
                == ["shot_001", "shot_002"]),
            "manifest_final": manifest["delivery"]["class"] == "final",
            "manifest_delivery_exact": (
                manifest["delivery"]["delivered_shots"]
                == ["shot_001", "shot_002"]),
            "all_shots_passed": all(
                row["delivery_status"] == "passed"
                and row["delivery_included"] is True
                for row in rows.values()),
            "readme_final": "交付身份：**final**" in readme,
            "final_video_only": (
                (export_dir / "blockout_full.mp4").is_file()
                and not (export_dir / "blockout_partial.mp4").exists()
                and not (export_dir / "blockout_diagnostic.mp4").exists()
                and not (export_dir / "final_video.mp4").exists()),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise AssertionError(
                f"final identity mismatch: {failed}; "
                f"report={report.to_dict()}; quality={written_quality}")
        return {
            "ok": True,
            "delivery_class": report.delivery_class,
            "selected_shots": written_quality["selected_shots"],
        }


def t_post_render_artifact_mismatch_blocks_final_metadata():
    with tempfile.TemporaryDirectory(prefix="bd_artifact_mismatch_") as tmp:
        fresh_scene()
        plan = demo_plan()
        summary = build_scene(plan).to_dict()
        report = export_project(
            plan,
            build_summary=summary,
            out_dir=Path(tmp),
            config=fresh_config(
                per_shot_clips=False,
                mask_pass=False,
                reference_cards=False,
            ),
            project="BlockDirector",
            delivery_quality={
                "schema_version": "quality-contract/v1",
                "component": "delivery",
                "delivery_class": "diagnostic",
                "reasons": ["failed_shots_require_diagnostic_delivery"],
                "passed_shots": ["shot_001"],
                "failed_shots": ["shot_002"],
                "pending_review_shots": [],
                "selected_shots": ["shot_001", "shot_002"],
                "sequence_reviewed_shots": [],
                "sequence_review_passed": False,
                "full_sequence_review_passed": False,
                "subset_sequence_review_passed": False,
                "delivered_shots": [],
                "artifact_check_complete": False,
                "adoption_explanations": {},
                "blocked_shots": {},
            },
        )
        export_dir = Path(tmp) / "export"
        checks = {
            "aborted": report.aborted,
            "blocked": report.canonical_delivery_class == "blocked",
            "mismatch_reason": (
                "delivered_artifact_set_mismatch"
                in report.delivery_quality.get("reasons", [])),
            "inspection_stills_retained": (
                (export_dir / "first_frames" / "shot_001.png").is_file()
                and (export_dir / "first_frames" / "shot_002.png").is_file()),
            "no_video_claim": not any(
                (export_dir / name).exists()
                for name in (
                    "blockout_full.mp4",
                    "blockout_partial.mp4",
                    "blockout_diagnostic.mp4",
                    "final_video.mp4",
                )),
            "no_manifest_or_readme": (
                not (export_dir / "shots.json").exists()
                and not (export_dir / "delivery_quality.json").exists()
                and not (export_dir / "README.md").exists()),
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise AssertionError(
                f"artifact mismatch handling failed: {failed}; "
                f"report={report.to_dict()}")
        return {
            "ok": True,
            "delivery_class": report.delivery_class,
            "reason": report.reason,
        }


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


def t_review_requests_survive_real_driver_build_and_export():
    """A5: actual control dispatch -> JSON runner boundary -> actual rendered package."""
    from block_director.contracts.audit import AuditError, AuditResult
    from block_director.contracts.config import AppConfig
    from block_director.contracts.enums import Purpose, Severity
    from block_director.contracts.messages import (
        ChatReply,
        FunctionCall,
        ToolCall,
    )
    from block_director.layer3_engine.shot_builder import BpySceneBuilder
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.offline import OfflineTransport
    from block_director.layer5_orchestrator.states import DriverState
    from block_director.layer6_audit.audit_logger import AuditLogger

    class InlineThread:
        def __init__(self, target, name=""):
            self.target = target

        def start(self):
            self.target()

    class ReviewAuditor:
        """Force one repair turn so the controller has a real current shot."""

        def __init__(self):
            self.failed = set()

        def shot_ids(self):
            return ["shot_001", "shot_002"]

        def audit(self, shot_id):
            if shot_id == "shot_001" and shot_id not in self.failed:
                self.failed.add(shot_id)
                return AuditResult(
                    passed=False,
                    target=shot_id,
                    errors=[AuditError(
                        rule="R001",
                        code="E_AXIS_001",
                        message="测试用首轮轴线路由",
                        severity=Severity.ERROR,
                        target=shot_id,
                        suggestion="留在当前轴侧",
                    )],
                )
            return AuditResult(passed=True, target=shot_id)

    class ReviewTransport(OfflineTransport):
        def __init__(self):
            super().__init__()
            self._repair_reviewed = False

        def chat(self, payload, timeout=120.0):
            if payload.purpose is Purpose.REPAIR and not self._repair_reviewed:
                self._repair_reviewed = True
                self.chat_calls += 1
                self.last_payload = payload
                requests = [
                    ToolCall(id=f"review_{i}", function=FunctionCall(
                        name="request_self_review",
                        arguments=json.dumps({"shot_id": "shot_001",
                                              "shot_intent": "检查构图"})))
                    for i in range(2)
                ]
                requests.append(ToolCall(
                    id="review_finish",
                    function=FunctionCall(
                        name="finish_shot",
                        arguments=json.dumps({"summary": "已完成自审"}),
                    ),
                ))
                return ChatReply(
                    content=None,
                    tool_calls=requests,
                    request_id=payload.request_id,
                    model="offline-review",
                    finish_reason="tool_calls",
                )
            return super().chat(payload, timeout=timeout)

    fresh_scene()
    with tempfile.TemporaryDirectory(prefix="bd_a5_review_") as tmp:
        audit = AuditLogger(directory=Path(tmp) / "runs")
        driver = PrevisDriver(
            transport=ReviewTransport(), audit=audit, config=AppConfig(),
            builder=BpySceneBuilder(clear_scene=True),
            auditor=ReviewAuditor(), thread_factory=InlineThread)
        assert driver.run_to_completion() is DriverState.DONE, driver.error
        summary = json.loads(json.dumps(driver.snapshot()))
        report = export_project(
            driver.plan, build_summary=driver.build_summary,
            out_dir=Path(tmp), config=fresh_config(),
            review_requests=summary["self_review_requests"])
        manifest = json.loads((Path(report.out_dir) / "shots.json").read_text(
            encoding="utf-8"))
        readme = (Path(report.out_dir) / "README.md").read_text(encoding="utf-8")
        events = [json.loads(line) for line in audit.audit_path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
        requested = [event for event in events
                     if event.get("kind") == "self_review_requested"]
        rows = {shot["shot_id"]: shot for shot in manifest["shots"]}
        assert report.ok, report.to_dict()
        assert len(requested) == 2, requested
        assert rows["shot_001"]["needs_review"] is True
        assert rows["shot_001"]["review_request_count"] == 2
        assert rows["shot_002"]["needs_review"] is False
        assert rows["shot_002"]["review_request_count"] == 0
        assert "shot_001：登记 2 次" in readme
        assert "shot_002：登记" not in readme
        return {"ok": True, "registered": 2,
                "rendered_shots": len(report.shots),
                "review_counts": {key: row["review_request_count"]
                                  for key, row in rows.items()}}


def main() -> int:
    capture_main_thread()
    check("export_produces_all_deliverables", t_export_produces_all_deliverables)
    check("missing_clip_is_reported_as_failure",
          t_missing_clip_is_reported_as_failure)
    check("relative_out_dir_lands_in_the_asked_directory",
          t_relative_out_dir_lands_in_the_asked_directory)
    check("compliance_report_is_shipped", t_compliance_report_is_shipped)
    check("render_labels_are_visible_sized_and_excluded_from_stills",
          t_render_labels_are_visible_sized_and_excluded_from_stills)
    check("videos_are_real_mp4", t_videos_are_real_mp4)
    check("manifest_matches_build", t_manifest_matches_build)
    check("export_aborts_on_leak", t_export_aborts_on_leak)
    check("blocked_quality_creates_no_delivery_tree",
          t_blocked_quality_creates_no_delivery_tree)
    check("blocked_quality_clears_stale_concat_identities",
          t_blocked_quality_clears_stale_concat_identities)
    check("sequence_render_rejects_missing_shot_file_and_clears_stale_clips",
          t_sequence_render_rejects_missing_shot_file_and_clears_stale_clips)
    check("partial_reuse_clears_stale_omitted_shot_artifacts_and_claims",
          t_partial_reuse_clears_stale_omitted_shot_artifacts_and_claims)
    check("partial_quality_identity_is_consistent_across_the_package",
          t_partial_quality_identity_is_consistent_across_the_package)
    check("partial_mask_pass_uses_only_selected_built_ranges",
          t_partial_mask_pass_uses_only_selected_built_ranges)
    check("diagnostic_quality_identity_is_consistent_across_the_package",
          t_diagnostic_quality_identity_is_consistent_across_the_package)
    check("final_quality_identity_is_consistent_across_the_package",
          t_final_quality_identity_is_consistent_across_the_package)
    check("post_render_artifact_mismatch_blocks_final_metadata",
          t_post_render_artifact_mismatch_blocks_final_metadata)
    check("camera_trajectory_is_per_frame", t_camera_trajectory_is_per_frame)
    check("prompt_sheet_covers_every_shot", t_prompt_sheet_covers_every_shot)
    check("review_requests_survive_real_driver_build_and_export",
          t_review_requests_survive_real_driver_build_and_export)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
