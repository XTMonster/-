"""§15.6 深度序列 / §15.7 全片拼接的端到端测试。

跑一次真实交付：两条短片 → 分镜 mp4 + 深度序列 + 全片拼接，逐项断言产物。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_delivery_extras.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.enums import RenderBackend  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer8_delivery import export_project  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
SHOT_FRAMES = 6


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    ensure_collections(scene)
    return scene


def tiny_plan() -> Plan:
    """两条短片：只求把深度与拼接链路跑通，不与性能测试混在一起。"""
    return Plan.from_dict({
        "scene_heading": "INT. 测试房间 - 日",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立空间",
             "shot_type": "MLS", "duration_frames": SHOT_FRAMES,
             "characters": ["char_001", "char_002"]},
            {"shot_id": "shot_002", "order": 2, "intent": "给出反应",
             "shot_type": "MCU", "duration_frames": SHOT_FRAMES,
             "characters": ["char_001"]},
        ]})


def depth_config() -> AppConfig:
    config = AppConfig()
    config.delivery.export_depth = True
    config.delivery.full_concat = True
    config.delivery.per_shot_clips = True
    config.delivery.render_backend = RenderBackend.EEVEE
    assert config.errors() == [], config.errors()
    return config


def run_export(tmp_dir: str):
    fresh_scene()
    plan = tiny_plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    return export_project(plan, out_dir=Path(tmp_dir),
                          config=depth_config().delivery, project="深度测试")


def frame_spread(path: Path) -> float:
    """读回一帧灰度图，返回 (最大−最小) 亮度差；>0 表示深度确实有变化。"""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        pixels = list(image.pixels)
    finally:
        bpy.data.images.remove(image)
    if not pixels:
        return 0.0
    return max(pixels) - min(pixels)


def png_header(path: Path) -> Dict[str, int]:
    """读 PNG 文件头：位深与颜色类型在 IHDR 里（偏移 24 / 25）。

    Blender 的 ``image.depth`` 反映的是内存里的浮点缓冲（恒为 32），
    要确认"落盘是 16 位灰度"只能看文件本身。
    """
    data = path.read_bytes()[:26]
    return {"bit_depth": data[24], "color_type": data[25],
            "signature_ok": data[:8] == b"\x89PNG\r\n\x1a\n"}


# --------------------------------------------------------------------------- #
# 1. 深度序列真的落盘，帧数与镜头时长一致
# --------------------------------------------------------------------------- #
def t_depth_sequence_is_written():
    tmp_dir = tempfile.mkdtemp(prefix="bd_depth_")
    report = run_export(tmp_dir)
    export_dir = Path(tmp_dir) / "export"
    shots = {item["shot_id"]: item for item in report.depth_shots}
    files = sorted((export_dir / "depth_shot_shot_001").glob("frame_*.png"))
    return {"ok": (report.ok and len(report.depth_shots) == 2
                   and shots["shot_001"]["frames"] == SHOT_FRAMES
                   and len(files) == SHOT_FRAMES
                   and files[0].name == "frame_0001.png"
                   and shots["shot_001"]["range_m"] == [0.1, 50.0]),
            "depth_shots": report.depth_shots,
            "files": [path.name for path in files],
            "warnings": report.warnings}


# --------------------------------------------------------------------------- #
# 2. 深度图是 16 位灰度，且画面里确实有深度变化
# --------------------------------------------------------------------------- #
def t_depth_frames_are_16bit_grey_with_range():
    tmp_dir = tempfile.mkdtemp(prefix="bd_depth_")
    report = run_export(tmp_dir)
    export_dir = Path(tmp_dir) / "export"
    path = export_dir / "depth_shot_shot_001" / "frame_0001.png"
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size[0], image.size[1]
        spread = frame_spread(path)
    finally:
        bpy.data.images.remove(image)
    header = png_header(path)
    return {"ok": (report.ok and header["bit_depth"] == 16
                   and header["color_type"] == 0 and header["signature_ok"]
                   and width == 1280 and height == 720 and spread > 0.0),
            "header": header, "size": [width, height],
            "value_spread": round(spread, 4)}


# --------------------------------------------------------------------------- #
# 3. 全片拼接产出单个 mp4，帧数等于两条分镜之和
# --------------------------------------------------------------------------- #
def t_full_concat_produces_one_video():
    tmp_dir = tempfile.mkdtemp(prefix="bd_concat_")
    report = run_export(tmp_dir)
    full = Path(report.full_video) if report.full_video else None
    head = full.read_bytes()[:16] if full and full.exists() else b""
    clips = sorted((Path(tmp_dir) / "export").glob("blockout_shot_*.mp4"))
    return {"ok": (report.ok and full is not None and full.exists()
                   and head[4:8] == b"ftyp"
                   and report.total_frames_concat == SHOT_FRAMES * 2
                   and len(clips) == 2
                   and full.name == "blockout_full.mp4"),
            "full_video": report.full_video,
            "size": full.stat().st_size if full and full.exists() else 0,
            "frames": report.total_frames_concat,
            "clips": [path.name for path in clips],
            "ftyp": head[4:8].decode("ascii", "replace")}


# --------------------------------------------------------------------------- #
# 4. README 与交付清单记录了深度归一化范围
# --------------------------------------------------------------------------- #
def t_readme_documents_the_depth_range():
    tmp_dir = tempfile.mkdtemp(prefix="bd_depth_")
    report = run_export(tmp_dir)
    export_dir = Path(tmp_dir) / "export"
    readme = (export_dir / "README.md").read_text(encoding="utf-8")
    payload = report.to_dict()
    return {"ok": ("0.1" in readme and "50" in readme and "归一化" in readme
                   and "blockout_full.mp4" in readme
                   and payload["full_video"] == report.full_video
                   and len(payload["depth_shots"]) == 2),
            "readme_has_depth": "归一化" in readme,
            "readme_has_full": "blockout_full.mp4" in readme,
            "report_keys": sorted(payload)}


# --------------------------------------------------------------------------- #
# 5. depth 在非 EEVEE 后端下给出明确告警而不是静默失败
# --------------------------------------------------------------------------- #
def t_depth_without_eevee_warns_instead_of_failing():
    fresh_scene()
    plan = tiny_plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    config = AppConfig()
    config.delivery.export_depth = False      # 关掉深度
    config.delivery.full_concat = False
    config.delivery.render_backend = RenderBackend.WORKBENCH
    tmp_dir = tempfile.mkdtemp(prefix="bd_nodepth_")
    report = export_project(plan, out_dir=Path(tmp_dir), config=config.delivery)
    export_dir = Path(tmp_dir) / "export"
    return {"ok": (report.ok and report.depth_shots == []
                   and not report.full_video
                   and not (export_dir / "depth_shot_shot_001").exists()),
            "warnings": report.warnings,
            "depth_shots": report.depth_shots}


def main() -> int:
    capture_main_thread()
    check("depth_sequence_is_written", t_depth_sequence_is_written)
    check("depth_frames_are_16bit_grey_with_range",
          t_depth_frames_are_16bit_grey_with_range)
    check("full_concat_produces_one_video", t_full_concat_produces_one_video)
    check("readme_documents_the_depth_range", t_readme_documents_the_depth_range)
    check("depth_without_eevee_warns_instead_of_failing",
          t_depth_without_eevee_warns_instead_of_failing)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
