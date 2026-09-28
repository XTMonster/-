"""§13.2 分镜列表 / §13.3 调试面板的集成测试。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_ui_panels.py
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

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.audit import AuditError, AuditResult  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.enums import Severity  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer5_orchestrator.budget import Budget, BudgetLimits  # noqa: E402
from block_director.layer5_orchestrator.driver import PrevisDriver  # noqa: E402
from block_director.layer5_orchestrator.offline import OfflineTransport  # noqa: E402
from block_director.layer5_orchestrator.runtime import set_active  # noqa: E402
from block_director.layer5_orchestrator.shot_status import (  # noqa: E402
    STATUS_FAILED,
    STATUS_GENERATED,
    STATUS_PENDING,
    STATUS_REPAIRED,
)
from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: E402
from block_director.layer7_ui import panel_debug, panel_shots  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene(project_dir: str = ""):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    scene.bd_project_dir = project_dir
    ensure_collections(scene)
    return scene


def build_with_driver(tmp_dir: str):
    """建场景 + 造一个带审核历史的驱动器（供状态列与调试面板使用）。"""
    fresh_scene(tmp_dir)
    plan = two_shot_plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    audit = AuditLogger(directory=Path(tmp_dir) / "runs")
    driver = PrevisDriver(transport=OfflineTransport(), audit=audit,
                          script="INT. 咖啡馆 - 日\n", thread_factory=InlineThread,
                          budget=Budget(BudgetLimits(max_llm_calls=8)))
    driver.plan = plan
    driver.build_summary = {"shots": 2, "total_frames": 216}
    driver.audit_results = [
        AuditResult(passed=False, target="shot_001", score=61.0,
                    errors=[AuditError(rule="R001", code="E_AXIS_001",
                                       message="越轴", severity=Severity.ERROR,
                                       target="shot_001", suggestion="挪到同侧")]),
        AuditResult(passed=True, target="shot_001", score=85.2,
                    suggestions=["构图良好"]),
        AuditResult(passed=True, target="shot_002", score=80.1),
    ]
    set_active(driver)
    return driver


# --------------------------------------------------------------------------- #
# 1. 分镜列表：状态列与意图列
# --------------------------------------------------------------------------- #
def t_shot_list_reports_statuses():
    tmp_dir = tempfile.mkdtemp(prefix="bd_ui_")
    try:
        build_with_driver(tmp_dir)
        rows = panel_shots.latest_statuses()
        statuses = {row["shot_id"]: row["status"] for row in rows}
        ok = (statuses == {"shot_001": STATUS_REPAIRED,
                           "shot_002": STATUS_GENERATED}
              and all(row["intent"] for row in rows)
              and all(row["seconds"] > 0 for row in rows))
        return {"ok": ok, "statuses": statuses,
                "rows": [{k: row[k] for k in ("shot_id", "status", "intent",
                                              "seconds", "audits")}
                         for row in rows]}
    finally:
        set_active(None)


def t_shot_list_degrades_when_the_run_did():
    tmp_dir = tempfile.mkdtemp(prefix="bd_ui_")
    try:
        driver = build_with_driver(tmp_dir)
        driver.audit_results = []
        driver.degraded_reason = "预算耗尽"
        rows = panel_shots.latest_statuses()
        return {"ok": all(row["status"] != STATUS_PENDING for row in rows),
                "statuses": [row["status"] for row in rows]}
    finally:
        set_active(None)


# --------------------------------------------------------------------------- #
# 2. 调试面板的三项数据来源
# --------------------------------------------------------------------------- #
def t_debug_panel_has_its_numbers():
    tmp_dir = tempfile.mkdtemp(prefix="bd_ui_")
    try:
        driver = build_with_driver(tmp_dir)
        driver.budget.state.llm_calls = 3
        driver.budget.state.prompt_tokens = 1200
        driver.budget.state.completion_tokens = 300
        snap = driver.snapshot()
        budget = snap["budget"]
        # 面板的"LLM 调用"取预算账本（§12.6 的上限就是按它比的）
        ok = (budget["llm_calls"] == 3 and snap["audits"] == 3
              and snap["failed_audits"] == 1
              and budget["total_tokens"] == 1500
              and budget["limits"]["max_llm_calls"] == 8
              and panel_debug._remaining(budget) == "5/8 次调用"
              and panel_debug._failed(snap) == 1)
        return {"ok": ok, "snapshot": {k: snap[k] for k in
                                      ("llm_calls", "audits", "failed_audits",
                                       "repairs")},
                "budget": budget, "remaining": panel_debug._remaining(budget)}
    finally:
        set_active(None)


# --------------------------------------------------------------------------- #
# 3. 导出 SDL / 场景状态真的写出文件
# --------------------------------------------------------------------------- #
def t_export_actions_write_real_files():
    tmp_dir = tempfile.mkdtemp(prefix="bd_ui_")
    try:
        build_with_driver(tmp_dir)
        sdl_result = bpy.ops.blockdirector.export_sdl()
        state_result = bpy.ops.blockdirector.export_scene_state()
        project = Path(tmp_dir) / "project.bdproj"
        state_file = Path(tmp_dir) / panel_debug.SCENE_STATE_FILE
        payload = json.loads(project.read_text(encoding="utf-8")) \
            if project.exists() else {}
        state = json.loads(state_file.read_text(encoding="utf-8")) \
            if state_file.exists() else {}
        return {"ok": (sdl_result == {'FINISHED'} and state_result == {'FINISHED'}
                       and project.exists() and state_file.exists()
                       and payload.get("version") == "1.2"
                       and len(payload.get("scenes", [{}])[0].get("shots", [])) == 2
                       and bool(state.get("characters"))),
                "sdl": list(sdl_result), "scene_state": list(state_result),
                "shots": len(payload.get("scenes", [{}])[0].get("shots", [])),
                "characters": len(state.get("characters", []))}
    finally:
        set_active(None)


# --------------------------------------------------------------------------- #
# 4. 缩略图：渲染出真实 PNG 并进入预览集合
# --------------------------------------------------------------------------- #
def t_thumbnail_render_produces_an_icon():
    tmp_dir = tempfile.mkdtemp(prefix="bd_ui_")
    try:
        build_with_driver(tmp_dir)
        result = bpy.ops.blockdirector.render_shot_thumbnail(shot_id="shot_002")
        path = Path(tmp_dir) / "thumbs" / "shot_002.png"
        preview = panel_shots._preview_collection().get("shot_002")
        # --background 下 icon_id 恒为 0（图标纹理由 UI 层分配），因此断言
        # 像素数据确实进了预览集合；icon_id 留给有界面时的 template_icon 用。
        loaded = preview is not None
        pixels = len(preview.icon_pixels_float) if loaded else 0
        return {"ok": (result == {'FINISHED'} and path.exists()
                       and path.stat().st_size > 0 and loaded
                       and list(preview.icon_size) == [160, 90]
                       and list(preview.image_size) == [160, 90]
                       and pixels == 160 * 90 * 4),
                "result": list(result), "exists": path.exists(),
                "size": path.stat().st_size if path.exists() else 0,
                "icon_size": list(preview.icon_size) if loaded else None,
                "pixels": pixels, "icon_id": preview.icon_id if loaded else None}
    finally:
        set_active(None)


# --------------------------------------------------------------------------- #
# 5. 查看审核结果：写进文本数据块
# --------------------------------------------------------------------------- #
def t_audit_result_opens_in_a_text_block():
    tmp_dir = tempfile.mkdtemp(prefix="bd_ui_")
    try:
        build_with_driver(tmp_dir)
        result = bpy.ops.blockdirector.show_audit_result(shot_id="shot_001")
        text = bpy.data.texts.get("BD 审核 shot_001")
        body = text.as_string() if text else ""
        return {"ok": (result == {'FINISHED'} and "通过" in body
                       and "共 2 次" in body
                       and "构图良好" in body),
                "result": list(result), "body": body}
    finally:
        set_active(None)


# --------------------------------------------------------------------------- #
# 6. 两个面板模块注册/注销干净（含预览集合）
# --------------------------------------------------------------------------- #
def t_panels_register_and_unregister_cleanly():
    import block_director

    block_director.register()
    try:
        ok_registered = (hasattr(bpy.types, "BLOCKDIRECTOR_PT_debug")
                         and hasattr(bpy.types, "BLOCKDIRECTOR_OT_export_sdl")
                         and hasattr(bpy.types, "BLOCKDIRECTOR_OT_render_shot_thumbnail")
                         and hasattr(bpy.types.Scene, "bd_project_dir")
                         and panel_shots._previews is not None)
        modules = list(block_director.registration._registered)
    finally:
        block_director.unregister()
    ok_unregistered = (not hasattr(bpy.types, "BLOCKDIRECTOR_PT_debug")
                       and not hasattr(bpy.types.Scene, "bd_project_dir")
                       and panel_shots._previews is None)
    return {"ok": ok_registered and ok_unregistered
            and "block_director.layer7_ui.panel_debug" in modules,
            "registered": ok_registered, "unregistered": ok_unregistered,
            "modules": modules}


def main() -> int:
    import block_director

    capture_main_thread()
    # 前五项需要面板注册过的场景属性与算子（bd_project_dir / 三个算子），
    # 因此先走一次真实的注册路径，跑完再注销，最后单独验证注册/注销本身。
    block_director.register()
    try:
        check("shot_list_reports_statuses", t_shot_list_reports_statuses)
        check("shot_list_degrades_when_the_run_did",
              t_shot_list_degrades_when_the_run_did)
        check("debug_panel_has_its_numbers", t_debug_panel_has_its_numbers)
        check("export_actions_write_real_files", t_export_actions_write_real_files)
        check("thumbnail_render_produces_an_icon",
              t_thumbnail_render_produces_an_icon)
        check("audit_result_opens_in_a_text_block",
              t_audit_result_opens_in_a_text_block)
    finally:
        block_director.unregister()
    check("panels_register_and_unregister_cleanly",
          t_panels_register_and_unregister_cleanly)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
