"""完整白模流程 UI 接线。

这是粗排/细排新流程进入原插件的正式入口：优先复用原驱动（PrevisDriver）已经
生成的计划与剧本理解（Stage S 的 ``SceneBrief``），没有计划时先同步跑一遍原
状态机（理解 -> 规划 -> 建场景）再进入新流程。然后按 gate 顺序执行粗排 JSON
修正 -> 基准冻结 -> 逐镜细排 -> 序列审查 -> 最终视频导出。

接入纪律：
* **不手动碰坐标**：粗排修正只改参考世界坐标 JSON，重建由插件完成；
* **gate 阻塞**：粗排未通过/基准未冻结不进细排，细排/序列未通过不导 final；
* **审计留痕**：完整流程的 start/coarse/detail/final 全部写进原 driver 的
  ``audit_log.jsonl``，与既有事件同一条时间线；
* **站位同源**：``cast_positions`` 与 driver 的空间设计快照用同一个
  ``SceneSpec.from_plan`` 派生，新流程不另摆一套坐标。
"""
from __future__ import annotations

from pathlib import Path

import bpy
from bpy.types import Operator

from ..layer3_engine.scene_context import get_context
from ..layer5_orchestrator.coarse_pipeline import run_coarse_pipeline
from ..layer5_orchestrator.detail_pipeline import run_detail_pipeline
from ..layer5_orchestrator.pipeline_ui_inputs import (
    assemble_pipeline_inputs,
    coarse_is_ready,
    detail_is_ready,
    pipeline_summary,
)
from ..layer5_orchestrator.runtime import get_active, set_active
from ..layer5_orchestrator.states import DriverState
from ..utils.logger import get_logger

log = get_logger("full-pipeline-ui")


class BLOCKDIRECTOR_OT_run_full_pipeline(Operator):
    bl_idname = "blockdirector.run_full_pipeline"
    bl_label = "运行完整白模流程"
    bl_description = "粗排 JSON 修正/冻结 → 逐镜细排 → 序列审查 → final 视频"

    def execute(self, context):  # noqa: D102 - bpy 接口
        out_dir = Path(bpy.path.abspath(
            context.scene.bd_project_dir or bpy.app.tempdir)) / "full_pipeline"
        driver = get_active()
        inputs = assemble_pipeline_inputs(driver, get_context())
        if inputs is None:
            # 没有现成计划：同步跑一遍原状态机（理解/规划由原插件负责），
            # 拿到 plan/brief 后再进入新流程，按钮即"一键全流程"。
            runnable = self._run_driver_to_plan(context)
            if not runnable:
                self.report({'ERROR'},
                            "没有可用分镜计划：请先运行生成白模预演（或让本按钮"
                            "先同步产出计划，但需剧本已配置）")
                return {'CANCELLED'}
            driver, plan, brief = runnable
            from ..contracts.cast import SceneSpec
            spec = SceneSpec.from_plan(plan, brief=brief)
            cast_positions = {
                str(member.name): list(member.initial_location)
                for member in spec.cast
            }
            inputs = {
                "plan": plan,
                "brief": brief,
                "cast_positions": cast_positions,
                "scene_id": str(getattr(plan, "scene_heading", "")
                                or "blockdirector_scene"),
            }

        audit = getattr(driver, "audit", None)
        audit_log = (audit.log if audit is not None
                     else lambda *a, **k: None)
        audit_log("full_pipeline_start",
                  "完整白模流程开始（粗排 JSON→冻结→逐镜细排→序列→final）")
        try:
            coarse = run_coarse_pipeline(
                plan=inputs["plan"],
                out_dir=out_dir / "coarse",
                scene_id=inputs["scene_id"],
                brief=inputs["brief"],
                cast_positions=inputs["cast_positions"],
                max_revisions=3,
            )
            audit_log("full_pipeline_coarse",
                      f"粗排结果：{coarse.get('coarse_status')} "
                      f"(gates={coarse.get('gates')})",
                      level="info" if coarse_is_ready(coarse) else "warning",
                      **{"payload": coarse})
            if not coarse_is_ready(coarse):
                self.report({'ERROR'},
                            "粗排未通过，已保留诊断产物，禁止进入细排/最终导出")
                return {'CANCELLED'}

            baseline_path = out_dir / "coarse" / "coarse_world_baseline.json"
            import json
            baseline = json.loads(
                baseline_path.read_text(encoding="utf-8"))
            detail = run_detail_pipeline(
                baseline=baseline, plan=inputs["plan"],
                out_dir=out_dir / "detail",
                render_video=True)
            audit_log("full_pipeline_detail",
                      f"细排结果：final={detail.get('final')} "
                      f"(gates={detail.get('gates')})",
                      level="info" if detail_is_ready(detail) else "warning",
                      **{"payload": detail})
            if not detail_is_ready(detail):
                self.report({'ERROR'},
                            "细排或序列审查未通过，禁止导出 final 视频")
                return {'CANCELLED'}
        except Exception as exc:  # noqa: BLE001 - UI 需报告真实失败
            log.exception("完整白模流程失败")
            audit_log("full_pipeline_failed",
                      f"{type(exc).__name__}: {exc}", level="error")
            self.report({'ERROR'}, f"完整白模流程失败：{type(exc).__name__}: {exc}")
            return {'CANCELLED'}

        summary = pipeline_summary(coarse, detail)
        audit_log("full_pipeline_done",
                  f"完整白模流程完成：{summary['final_video']}",
                  **{"payload": summary})
        self.report({'INFO'},
                    f"完整白模流程完成：{summary['final_video']}")
        return {'FINISHED'}

    def _run_driver_to_plan(self, context):
        """没有 plan 时，同步把原状态机推到 DONE，返回 (driver, plan, brief)。

    走与原面板 ``run_previs`` 同一条装配路径（``build_run_context``），
    只把模态 timer 换成同步 ``run_to_completion``（headless 同款）。失败返回
    ``None``，绝不伪造计划。
    """
        from ..layer5_orchestrator.modal_operator import build_run_context

        run = build_run_context(context)
        if not run.ok:
            self.report({'ERROR'}, "；".join(run.problems))
            return None
        set_active(run.driver)
        try:
            state = run.driver.run_to_completion()
        except Exception as exc:  # noqa: BLE001 - 向 UI 报告真实失败
            run.driver.audit.log("full_pipeline_driver_failed",
                                 f"{type(exc).__name__}: {exc}",
                                 level="error")
            raise
        if state is not DriverState.DONE:
            run.driver.audit.log(
                "full_pipeline_driver_not_done",
                f"状态机停在 {state}：{run.driver.error or ''}",
                level="warning")
            return None
        return run.driver, run.driver.plan, run.driver.brief


CLASSES = (BLOCKDIRECTOR_OT_run_full_pipeline,)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
