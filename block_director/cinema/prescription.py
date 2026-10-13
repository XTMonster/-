"""空间尺 demo：把构图数值翻译成 LLM 可执行的工具处方。

纯 Python、无 bpy。真实运行时，CompositionReport 来自构图审计；本模块只做
"测量结果 -> 结构化观察/处方"，不替 LLM 做最终裁决。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .composition import CompositionItem, CompositionReport


@dataclass(frozen=True)
class Prescription:
    component: str
    current: float
    target: float
    tool: str
    tool_args: Dict[str, Any]
    note: str = ""


_PRESCRIPTION_TEMPLATES = {
    "headroom": ("move_camera", {"movement_type": "dolly_in", "start_frame": 1,
                                   "end_frame": 48, "amount": 0.5}),
    "lead_room": ("move_camera", {"movement_type": "truck_right", "start_frame": 1,
                                    "end_frame": 48, "amount": 0.3}),
    "rule_of_thirds": ("move_camera", {"movement_type": "pan", "start_frame": 1,
                                         "end_frame": 48, "amount": 6.0}),
    "balance": ("move_character", {"character_id": "char_b",
                                     "target_position": [0.4, 2.5, 0.0],
                                     "start_frame": 1, "end_frame": 48,
                                     "speed": "walk"}),
    "occlusion": ("move_camera", {"movement_type": "truck_left", "start_frame": 1,
                                    "end_frame": 48, "amount": 0.4}),
    "framing": ("reframe", {"shot_id": "shot_001", "shot_type": "MS",
                              "lens": 35.0}),
}


def _target_for(_name: str, _item: CompositionItem) -> float:
    # Demo 只演示"当前值 -> 达标目标"；真实 magnitude 由 probe 验证。
    return 0.70


def build_prescriptions(report: CompositionReport) -> List[Prescription]:
    out: List[Prescription] = []
    for name, item in report.items.items():
        if item.score >= 0.7:
            continue
        template = _PRESCRIPTION_TEMPLATES.get(name)
        if template is None:
            continue
        tool, args = template
        out.append(Prescription(name, round(item.score, 2), _target_for(name, item),
                                tool, dict(args), item.suggestion))
    return out


def render_ruler_report(report: CompositionReport,
                        prescriptions: List[Prescription]) -> str:
    lines = [f"构图读数：{report.score:.1f}/100（{'通过' if report.passed else '需调整'}）"]
    for name, item in report.items.items():
        suffix = f"（{item.suggestion}）" if item.suggestion else ""
        lines.append(f"- {name}: {item.score:.2f}{suffix}")
    if prescriptions:
        lines.append("处方（可执行）：")
        for p in prescriptions:
            lines.append(f"  - {p.component} 当前 {p.current} → 目标 {p.target}，"
                         f"建议执行 {p.tool}({p.tool_args})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# demo 层工具 schema 的轻量替身（正式实现以 tool_bindings/registry 为真源）
# --------------------------------------------------------------------------- #
DEMO_ACTION_TOOL_SCHEMAS = {
    "move_camera": {
        "type": "object", "additionalProperties": False,
        "required": ["movement_type", "start_frame", "end_frame"],
        "properties": {
            "camera_id": {"type": "string"},
            "movement_type": {"type": "string", "enum": ["dolly_in", "dolly_out",
                                                         "truck_left", "truck_right",
                                                         "pan"]},
            "amount": {"type": "number", "minimum": 0, "maximum": 180},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "move_character": {
        "type": "object", "additionalProperties": False,
        "required": ["character_id", "target_position", "start_frame", "end_frame"],
        "properties": {
            "character_id": {"type": "string"},
            "target_position": {"type": "array", "minItems": 3, "maxItems": 3,
                                "items": {"type": "number"}},
            "speed": {"type": "string", "enum": ["walk", "run"]},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "reframe": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "shot_id": {"type": "string"},
            "shot_type": {"type": "string", "enum": ["MS"]},
            "lens": {"type": "number", "minimum": 8, "maximum": 300},
        },
    },
}


def prescriptions_pass_demo_schemas(prescriptions: List[Prescription]) -> List[str]:
    """返回不通过 demo schema 的处方 component；空列表表示全部可执行。"""
    from ..layer5_orchestrator.tool_schema import validate_args
    bad: List[str] = []
    for p in prescriptions:
        schema = DEMO_ACTION_TOOL_SCHEMAS.get(p.tool)
        if schema is None:
            bad.append(p.component)
            continue
        if validate_args(schema, p.tool_args):
            bad.append(p.component)
    return bad
