"""GUI 驱动：用 timer 推动同一个 PrevisDriver（执行文档 v1.2 §3.2 / §3.3）。

本模块是**唯一**把状态机接到 Blender 事件循环的地方；它只做三件事：
建运行、按 tick 调 ``driver.step()``、把结果汇报给 UI。
"""

from __future__ import annotations

import os
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import bpy
from bpy.types import Operator

from ..layer6_audit import AuditLogger
from ..settings import get_config
from ..layer7_ui.run_settings import apply_scene_settings, collect_settings
from ..utils.logger import get_logger
from ..utils.paths import default_project_root, ensure_dir
from .driver import DriverLimits, PrevisDriver, default_registry
from .headless_runner import trace_options
from .runtime import clear_active, get_active, set_active
from .states import DriverState
from .transport_factory import TransportUnavailable, make_transport

log = get_logger("modal")

TIMER_INTERVAL = 0.1
SCRIPT_TEXT_BLOCK = "BlockDirector Script"

#: ``build_run_context(builder=...)`` 的默认值：不传就按 GUI 的正常路径建一个
#: ``BpySceneBuilder``；显式传 ``None`` 表示"不注入构建器"，那是**错误**。
_DEFAULT_BUILDER = object()
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


def resolve_parsed_script(context):
    """剧本路径存在时顺带解析一份：R015/R016 与离线镜数都靠它。"""
    scene = context.scene
    path = getattr(scene, "bd_script_path", "") or ""
    if not path or not os.path.isfile(path):
        return None
    try:
        from ..layer1_input import apply_deterministic_coreferences, parse_script

        parsed = parse_script(path)
        apply_deterministic_coreferences(parsed)
        return parsed
    except Exception as exc:  # noqa: BLE001 - 解析失败退回纯文本路径
        log.warning("剧本解析失败，将退回原文：%s", exc)
        return None


@dataclass
class RunContext:
    """一次 GUI 运行的装配结果（v1.4 P9.5）。"""

    driver: Optional[PrevisDriver] = None
    config: Any = None
    mode: str = ""
    builder: Any = None
    problems: List[str] = field(default_factory=list)
    #: v1.4 安全审计 F2：``clear_scene=True`` 时构建前的快照（可回滚）。
    checkpoints: Any = None

    @property
    def ok(self) -> bool:
        return self.driver is not None and not self.problems


def build_run_context(context, *, builder=_DEFAULT_BUILDER, auditor=None,
                      transport=None, config=None, limits=None,
                      parsed_script=None) -> RunContext:
    """装配一次 GUI 运行需要的全部依赖。

    v1.4 P9.5 / X1 / S1：``invoke()`` 里的 ``event_timer_add`` /
    ``modal_handler_add`` 依赖 ``context.window``，``--background`` 下根本跑不了
    模态——所以"建运行"这一步必须抽成**不碰窗口**的函数，探针才能按字面驱动它。
    这里注入 ``builder`` / ``auditor`` / ``parsed_script`` / ``limits`` 四件套，
    缺任何一件都不会再"悄悄只拿到一份计划"。
    """
    from ..layer3_engine.shot_auditor import BpyShotAuditor
    from ..layer3_engine.shot_builder import BpySceneBuilder

    problems: List[str] = []
    run_config = (copy.deepcopy(config) if config is not None
                  else copy.deepcopy(get_config()))
    run_config, settings_problems = apply_scene_settings(
        run_config, collect_settings(context.scene))
    problems.extend(settings_problems)
    if problems:
        return RunContext(config=run_config, problems=problems)

    if builder is _DEFAULT_BUILDER:
        # v1.4 安全审计 F2：``clear_scene=True`` 会删掉场景里**所有**对象
        # （BuildScene 的清理不认 ``BD_`` 前缀），用户在白模之外做过的建模
        # 会一起消失，而旧代码没有任何确认与快照。默认行为保持不变（白模
        # 预演需要一块干净的地面），但：① 面板可以关掉；② 清空前先拍
        # CheckpointManager 快照，失败/取消时能回滚。
        clear = bool(getattr(context.scene, "bd_clear_scene", True))
        checkpoints = None
        if clear:
            try:
                from ..layer3_engine.checkpoint_manager import CheckpointManager

                checkpoints = CheckpointManager()
                checkpoints.capture("before_build")
                log.info("构建前已拍检查点 before_build（%d 个对象）",
                         len(bpy.data.objects))
            except Exception as exc:  # noqa: BLE001 - 快照失败不阻断开跑
                log.warning("构建前拍检查点失败：%s", exc)
                checkpoints = None
        builder = BpySceneBuilder(clear_scene=clear)
    if builder is None:
        # 负对照（RK-9）：operator 路径没有构建器时必须失败，而不是
        # 像 headless 的"仅规划"模式那样以 DONE 收尾。
        problems.append("GUI 路径必须注入场景构建器（builder）；"
                        "否则面板只会拿回一份计划，既没有场景也没有视频")
        return RunContext(config=run_config, builder=None, problems=problems)

    offline = bool(getattr(context.scene, "bd_offline", True))
    if transport is None:
        try:
            transport, mode = make_transport(run_config, offline=offline)
        except TransportUnavailable as exc:
            problems.append(str(exc))
            return RunContext(config=run_config, builder=builder,
                              problems=problems)
    else:
        mode = "offline" if offline else "sidecar"

    if parsed_script is None:
        parsed_script = resolve_parsed_script(context)

    run_dir = ensure_dir(default_project_root() / "runs")
    audit = AuditLogger(directory=run_dir, echo=True,
                        **trace_options(run_config))
    # P14-4 的**插件侧消费**：GUI 通路此前**根本没有装配知识检索器**
    # （`PrevisDriver(knowledge=...)` 缺省 None），于是逐镜的
    # `block_for_shot()` 永远拿不到超图，`knowledge_trace.json` 与
    # `retrieval_calls` 恒为零——"插件会消费知识"只写在文档里。
    # 这里复用 headless 通路同一份装配函数（`_make_knowledge`），
    # 让两条通路的检索器**同源**，不各写一份。
    from .headless_runner import _make_knowledge

    driver = PrevisDriver(
        transport=transport,
        audit=audit,
        script=resolve_script(context),
        parsed_script=parsed_script,
        config=run_config,
        limits=limits,
        registry=default_registry(
            max_shots=int(run_config.orchestration.max_shots)),
        builder=builder,
        auditor=auditor or BpyShotAuditor(
            audit_level=run_config.audit.level,
            #: v1.5 §5.5（P6-T1）：外部评审外回路（缺省关）。评审复用同一条
            #: 传输——它必须和这一跑的主模型走同一份连接/凭证。
            vlm_review=run_config.vlm_review,
            vlm_transport=transport),
        knowledge=_make_knowledge(run_config, transport, audit),
    )
    return RunContext(driver=driver, config=run_config, mode=mode,
                      builder=builder, checkpoints=checkpoints)


def export_finished_run(run: RunContext) -> Optional[Dict[str, Any]]:
    """跑完就地导出交付包，并写 ``export_started``（v1.4 P9.5 / RK-9）。

    场景此刻还在内存里——先导出再拆 timer，用户点一次"运行"就能拿到
    分镜 mp4、首帧、``shots.json`` 与 ``prompts.md``。
    """
    driver = run.driver
    if driver is None or driver.plan is None or not driver.build_summary:
        return None
    from ..layer8_delivery import export_project

    out_dir = Path(default_project_root()) / "exports" / driver.audit.run_id
    spec = getattr(run.builder, "spec", None)
    crowd = list(getattr(spec, "crowd", None) or [])
    driver.audit.log("export_started", f"开始导出交付包：{out_dir}",
                     out_dir=str(out_dir), shots=len(driver.plan.shots),
                     frames=driver.plan.total_frames)
    report = export_project(driver.plan, build_summary=driver.build_summary,
                            out_dir=out_dir, config=run.config.delivery,
                            brief=driver.brief,
                            compliance=driver.snapshot().get("compliance"),
                            llm_calls=int(driver.snapshot().get("llm_calls") or 0),
                            retrieval_calls=int(getattr(driver.knowledge,
                                                        "retrieval_calls", 0) or 0),
                            knowledge_provenance=driver.knowledge_provenance(),
                            crowd=crowd,
                            project=driver.plan.scene_heading or "BlockDirector",
                            roster=driver._cast_roster(),
                            review_requests=driver.review_requests)
    payload = report.to_dict()
    driver.audit.log("export_finished",
                     f"交付包导出结束：{'ok' if report.ok else '失败'}",
                     level="info" if report.ok else "warning",
                     **{key: payload.get(key)
                        for key in ("ok", "aborted", "out_dir", "reason")})
    log.info("GUI 导出结束：%s", report.out_dir)
    return payload


class BLOCKDIRECTOR_OT_run_previs(Operator):
    bl_idname = "blockdirector.run_previs"
    bl_label = "生成白模预演"
    bl_description = "驱动 LLM 导演状态机，生成白模预演分镜计划"

    _timer = None
    _run = None

    def invoke(self, context, event):
        if get_active() is not None:
            self.report({'WARNING'}, "已有运行在进行中，请先取消")
            return {'CANCELLED'}

        # v1.4 P9.5：装配（含面板覆盖、传输、builder/auditor/parsed_script/
        # limits 四件套）全部搬进可测的 ``build_run_context``——那里不碰
        # ``context.window``，因此 ``--background`` 下也能被探针按字面驱动。
        run = build_run_context(context)
        if not run.ok:
            self.report({'ERROR'}, "；".join(run.problems))
            return {'CANCELLED'}
        self._run = run
        set_active(run.driver)
        log.info("GUI 运行开始（传输=%s，run_id=%s）", run.mode,
                 run.driver.audit.run_id)

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
        # DONE 时**先导出再拆 timer**：场景还活在内存里，点一次"运行"就该
        # 拿到分片、首帧、shots.json 与 prompts.md（v1.4 P9.5 / RK-9）。
        export_payload = None
        if state is DriverState.DONE and self._run is not None:
            try:
                export_payload = export_finished_run(self._run)
            except Exception as exc:  # noqa: BLE001 - 导出失败不该吞掉运行结果
                log.warning("GUI 收尾导出失败：%s", exc)
                driver.audit.log("export_failed",
                                 f"{type(exc).__name__}: {exc}", level="warning")
        self._teardown(context)
        if state is DriverState.DONE:
            detail = f"完成：{driver.snapshot()['shots']} 个镜头"
            if export_payload is not None:
                detail += f"，交付包：{export_payload.get('out_dir')}"
            self.report({'INFO'}, detail)
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
        # ``clear_active`` 只清**驱动器**这一个注册项；场景上下文
        # （``layer3_engine.scene_context``）必须留着，否则分镜列表、
        # 角色面板与逐镜重跑在运行结束后就全空了。
        clear_active()
        self._run = None


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


class BLOCKDIRECTOR_OT_pause_previs(Operator):
    bl_idname = "blockdirector.pause_previs"
    bl_label = "暂停/继续"
    bl_description = "暂停推进（保留当前状态与已建成的场景），再按一次继续"

    def execute(self, context):
        driver = get_active()
        if driver is None:
            self.report({'INFO'}, "当前没有运行")
            return {'CANCELLED'}
        if driver.paused:
            driver.resume()
            self.report({'INFO'}, "已继续")
        else:
            driver.pause()
            self.report({'INFO'}, "已暂停")
        return {'FINISHED'}


CLASSES = (BLOCKDIRECTOR_OT_run_previs, BLOCKDIRECTOR_OT_cancel_previs,
           BLOCKDIRECTOR_OT_pause_previs)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:  # noqa: BLE001
            log.debug("注销 %s 失败: %s", cls.__name__, exc)
