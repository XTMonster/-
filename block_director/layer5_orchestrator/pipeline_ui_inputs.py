"""完整白模流程的 UI 接线辅助（纯层，不 import bpy）。

把"从 driver / scene_context 折出粗排+细排需要的输入"与"gate 判定"抽成
纯函数，operator 只做薄封装：这样 pytest 不进 Blender 也能钉住接线语义，
避免 operator 里出现只有进 Blender 才会暴露的字段漂移。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple


def assemble_pipeline_inputs(
    driver: Any, scene_context: Any
) -> Optional[Dict[str, Any]]:
    """折出完整流程输入；没有可用计划时返回 ``None``。

    优先取 driver 内存（运行中/刚结束仍在 active 时），回退
    ``SceneContext.plan``（GUI 常规结束后 driver 被 clear，但场景上下文
    保留——那里只有 plan，没有 brief）。

    返回：
    * ``plan``：Plan 或 dict（``run_coarse_pipeline`` 两种都支持）；
    * ``brief``：SceneBrief 或 None（无 driver 时由粗排确定性理解兜底）；
    * ``cast_positions``：角色名 -> 初始站位（与 ``driver._spatial_design_payload``
      同源，避免新流程与既有空间设计快照各摆一份）；
    * ``scene_id``：剧本标题或默认值。
    """
    plan = getattr(driver, "plan", None) if driver is not None else None
    brief = getattr(driver, "brief", None) if driver is not None else None
    if plan is None and scene_context is not None:
        plan = getattr(scene_context, "plan", None)
    if plan is None:
        return None

    cast_positions: Dict[str, Sequence[float]] = {}
    try:
        from ..contracts.cast import SceneSpec
        spec = SceneSpec.from_plan(plan, brief=brief)
        cast_positions = {
            str(member.name): list(member.initial_location)
            for member in spec.cast
        }
    except Exception:  # noqa: BLE001 - 站位只是证据，失败不阻断主链
        cast_positions = {}

    scene_id = str(getattr(plan, "scene_heading", "") or "blockdirector_scene")
    return {
        "plan": plan,
        "brief": brief,
        "cast_positions": cast_positions,
        "scene_id": scene_id,
    }


def gate_value(report: Optional[Mapping[str, Any]], key: str) -> str:
    """取 gate 字典里的一项，缺省返回 ""（不抛 KeyError）。"""
    if not report:
        return ""
    gates = report.get("gates") or {}
    return str(gates.get(key) or "")


def coarse_is_ready(report: Optional[Mapping[str, Any]]) -> bool:
    """粗排 gate 通过且基准已冻结，才允许进入细排。"""
    return (gate_value(report, "coarse") == "pass"
            and gate_value(report, "baseline") == "frozen")


def detail_is_ready(report: Optional[Mapping[str, Any]]) -> bool:
    """细排 final gate 通过（sequence/pass + final 视频已产出）。"""
    if not report:
        return False
    return bool(report.get("final")) and gate_value(report, "final") == "pass"


def pipeline_summary(coarse: Optional[Mapping[str, Any]],
                     detail: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """一页纸状态摘要（operator 报告 + 审计事件共用）。"""
    return {
        "schema_version": "full-pipeline-ui-summary/v1",
        "gates": {
            "coarse": gate_value(coarse, "coarse"),
            "baseline": gate_value(coarse, "baseline"),
            "detail": gate_value(detail, "detail"),
            "sequence": gate_value(detail, "sequence"),
            "final": gate_value(detail, "final"),
        },
        "coarse_rounds": len((coarse or {}).get("rounds") or []),
        "coarse_artifacts": (coarse or {}).get("artifacts") or {},
        "detail_artifacts": (detail or {}).get("artifacts") or {},
        "final_video": ((detail or {}).get("artifacts") or {}).get(
            "final_video"),
    }


__all__ = [
    "assemble_pipeline_inputs",
    "coarse_is_ready",
    "detail_is_ready",
    "gate_value",
    "pipeline_summary",
]
