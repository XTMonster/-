"""GUI 驱动：用 timer 推动同一个 PrevisDriver（执行文档 v1.2 §3.2 / §3.3）。

本模块是**唯一**把状态机接到 Blender 事件循环的地方；它只做三件事：
建运行、按 tick 调 ``driver.step()``、把结果汇报给 UI。
"""

from __future__ import annotations

import os
import copy

import bpy
from bpy.types import Operator

from ..layer6_audit import AuditLogger
from ..settings import get_config
from ..layer7_ui.run_settings import apply_scene_settings, collect_settings
from ..utils.logger import get_logger
from ..utils.paths import default_project_root, ensure_dir
from .driver import PrevisDriver
from .headless_runner import trace_options
from .runtime import clear_active, get_active, set_active
from .states import DriverState
from .transport_factory import TransportUnavailable, make_transport

log = get_logger("modal")

TIMER_INTERVAL = 0.1
SCRIPT_TEXT_BLOCK = "BlockDirector Script"
DEMO_SCRIPT = """\
INT. 咖啡馆 - 日

小明坐在靠窗的位置，手里拿着一封信。

小明
（低声）
她还是没有回信。
"""


def resolve_script(context) -> str:
    """脚本来源：文件路径 > 文本数据块 > 内置示例。"""
    scene = context.scene
    path = getattr(scene, "bd_script_path", "") or ""
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError as exc:
            log.warning("读取剧本失败 %s: %s", path, exc)
    text = bpy.data.texts.get(SCRIPT_TEXT_BLOCK)
    if text is not None and text.as_string().strip():
        return text.as_string()
    return DEMO_SCRIPT


class BLOCKDIRECTOR_OT_run_previs(Operator):
    bl_idname = "blockdirector.run_previs"
    bl_label = "生成白模预演"
    bl_description = "驱动 LLM 导演状态机，生成白模预演分镜计划"

    _timer = None

    def invoke(self, context, event):
        if get_active() is not None:
            self.report({'WARNING'}, "已有运行在进行中，请先取消")
            return {'CANCELLED'}

        # 面板设置覆盖到**副本**上：配置文件仍是唯一持久真源，反复运行也不会
        # 让上一次的临时选择沉淀进进程级配置。
        config = copy.deepcopy(get_config())
        config, problems = apply_scene_settings(config,
                                                collect_settings(context.scene))
        if problems:
            self.report({'ERROR'}, "；".join(problems))
            return {'CANCELLED'}
        offline = bool(getattr(context.scene, "bd_offline", True))
        try:
            transport, mode = make_transport(config, offline=offline)
        except TransportUnavailable as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        run_dir = ensure_dir(default_project_root() / "runs")
        audit = AuditLogger(directory=run_dir, echo=True,
                            **trace_options(config))
        driver = PrevisDriver(
            transport=transport,
            audit=audit,
            script=resolve_script(context),
            config=config,
        )
        set_active(driver)
        log.info("GUI 运行开始（传输=%s，run_id=%s）", mode, audit.run_id)

        self._timer = context.window_manager.event_timer_add(
            TIMER_INTERVAL, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        driver = get_active()
        if driver is None:                      # 被外部清理
            self._teardown(context)
            return {'CANCELLED'}

        if event.type == 'ESC':
            driver.cancel()
            return {'RUNNING_MODAL'}
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        keep_running = driver.step()
        if keep_running:
            return {'RUNNING_MODAL'}

        state = driver.state
        self._teardown(context)
        if state is DriverState.DONE:
            self.report({'INFO'}, f"完成：{driver.snapshot()['shots']} 个镜头")
            return {'FINISHED'}
        if state is DriverState.CANCELLED:
            self.report({'WARNING'}, "已取消")
            return {'CANCELLED'}
        self.report({'ERROR'}, driver.error or "运行失败")
        return {'CANCELLED'}

    def _teardown(self, context) -> None:
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception as exc:  # noqa: BLE001
                log.debug("移除 timer 失败: %s", exc)
            self._timer = None
        clear_active()


class BLOCKDIRECTOR_OT_cancel_previs(Operator):
    bl_idname = "blockdirector.cancel_previs"
    bl_label = "取消运行"
    bl_description = "请求取消当前预演生成（协作式取消）"

    def execute(self, context):
        driver = get_active()
        if driver is None:
            self.report({'INFO'}, "当前没有运行")
            return {'CANCELLED'}
        driver.cancel()
        self.report({'INFO'}, "已请求取消")
        return {'FINISHED'}


CLASSES = (BLOCKDIRECTOR_OT_run_previs, BLOCKDIRECTOR_OT_cancel_previs)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:  # noqa: BLE001
            log.debug("注销 %s 失败: %s", cls.__name__, exc)
