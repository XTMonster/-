"""空间尺处方生成器（Ticket 03a）。

从构图读数生成**处方**（不是可执行命令）：每条处方只描述
component / severity / current / target / allowed_tools / direction /
expected_effect，目的是把“尺子给方向”和“模型动手”彻底分开——
尺子永远不替 LLM 选具体工具、不填参数、不写“建议执行”，防止把正确答案
泄漏进提示（detect_pollution 是这条红线的守卫）。

纯 Python、无 bpy。真实运行时，CompositionReport 来自构图审计；本模块只做
“测量结果 -> 结构化观察/处方”，不替 LLM 做最终裁决。

与旧 demo 的关系（03a 收敛）：
* 删除 DEMO_ACTION_TOOL_SCHEMAS / prescriptions_pass_demo_schemas /
  render_ruler_report——尺子读数渲染归评测台（Ticket 03c），工具 schema
  归 layer3_engine/tool_bindings 真源；
* 删除可执行 Prescription（tool/tool_args 字段）——那正是污染源。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ..contracts.tools import ACTION_TOOLS
from .composition import CompositionItem, CompositionReport
from .evaluation_protocol import Prescription, Severity, TargetInterval


PASS_SCORE = 70.0

#: 未注册的内部临时键：处方只能在“几何/构图事实分量”层面给方向，
#: 不允许把 camera_z / delta_* / walk_* 这类实现细节直接端给模型。
_INTERNAL_KEY_PREFIXES: Tuple[str, ...] = ("camera_z", "delta_", "walk_")

#: 六个构图分量的修复方向（措辞只含方向与预期影响，不含工具名与参数）。
#: 与 composition.py 的六项一一对应，是 build_prescriptions 的单源描述。
_COMPONENT_DIRECTIONS: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {
    "headroom": (
        "抬高主体：机位向主体推进或收紧景别，增加头顶留白到目标区间",
        ("headroom",),
        ("move_camera", "reframe"),
    ),
    "lead_room": (
        "把主体放到画面偏对侧，让视线方向留出前方空间",
        ("lead_room",),
        ("move_camera",),
    ),
    "rule_of_thirds": (
        "微调构图让主体中心落到三分线交点附近",
        ("rule_of_thirds",),
        ("move_camera", "reframe"),
    ),
    "balance": (
        "左右重新平衡人物位置，让画面重心回到中央稳定区",
        ("balance",),
        ("move_character", "move_camera"),
    ),
    "occlusion": (
        "移开机位或调整遮挡物，让被挡主体的关键部位恢复可见",
        ("occlusion",),
        ("move_camera",),
    ),
    "framing": (
        "收紧景别或重新构图，让主体完整回到画内并符合景别预期",
        ("framing",),
        ("reframe",),
    ),
}


def _target_for(component: str, item: CompositionItem) -> TargetInterval:
    """把分量分数映射到“达标区间”（0.7..1.0）。

    Demo 只演示“当前值 -> 达标目标”；真实 magnitude 由 probe（Ticket 04+）
    按 composition.py 的真源口径给出，这里不引入新阈值。
    """
    return TargetInterval(min_value=PASS_SCORE / 100.0)


def _severity_for(component: str, item: CompositionItem) -> Severity:
    """分量分数越低严重度越高：<0.3 fatal，<0.5 error，否则 warning。

    与主 spec §5.3 的分级方向一致，且不改变现有 demo 阈值
    （0.7 以下才产处方）。
    """
    if item.score < 0.3:
        return Severity.FATAL
    if item.score < 0.5:
        return Severity.ERROR
    return Severity.WARNING


def build_prescriptions(report: CompositionReport) -> List[Prescription]:
    """把失败构图分量变成新契约 Prescription（不含 tool/tool_args）。"""
    out: List[Prescription] = []
    for name, item in report.items.items():
        if item.score >= PASS_SCORE / 100.0:
            continue
        direction, effects, allowed = _COMPONENT_DIRECTIONS.get(
            name, ("", (), ()))
        if not direction:
            continue
        out.append(Prescription(
            component=name,
            severity=_severity_for(name, item),
            current=round(float(item.score), 2),
            target=_target_for(name, item),
            allowed_tools=tuple(allowed),
            direction=direction,
            expected_effect=tuple(effects),
        ))
    return out


def validate_prescription(p: Prescription) -> Tuple[bool, str]:
    """校验处方的分量、目标区间、工具白名单与方向/预期影响。

    拒绝：
    * camera_z / delta_* / walk_* 等未注册内部键作 component；
    * allowed_tools 里出现 contracts.tools.ACTION_TOOLS 之外的未注册工具。
    """
    component = str(p.component)
    if (component.startswith(_INTERNAL_KEY_PREFIXES)
            or component in ("camera_z", "delta_x", "delta_y", "walk_speed")):
        return False, f"component 是未注册内部键：{component!r}"
    if p.target.min_value is None and p.target.max_value is None:
        return False, "target 必须至少声明 min 或 max"
    allowed_set: Set[str] = set(ACTION_TOOLS)
    for tool in p.allowed_tools:
        if tool not in allowed_set:
            return False, f"allowed_tools 含未注册工具：{tool!r}"
    if not str(p.direction).strip():
        return False, "direction 不能为空"
    if not p.expected_effect:
        return False, "expected_effect 不能为空"
    return True, ""


def guard_verdict(p: Prescription) -> str:
    """确定性地面真值：current 已落在 target 内 -> reject，否则 accept。

    该判词由评测台（Ticket 03c/05）在处方对拍时使用，**不进尺子提示**。
    """
    return "reject" if p.target.contains(float(p.current)) else "accept"


#: 工具/参数层面的泄漏词（“建议执行”是用户 2026-10-13 处方化裁决的红线）。
_POLLUTION_TOKEN_PREFIXES: Tuple[str, ...] = (
    "建议执行", "建议调用", "tool", "move_camera", "move_character",
    "reframe", "setup_camera", "place_character", "character_action",
    "look_at", "face_character", "interact_with", "dolly_in", "dolly_out",
    "truck_left", "truck_right", "pan", "camera_z", "delta_x", "delta_y",
    "walk_speed", "walk_",
)


def detect_pollution(prompt: str) -> Optional[str]:
    """检测提示是否泄漏了正确工具名/参数/“建议执行”。

    只要命中就返回一句泄漏判词（None 表示干净）。这是防污染红线的守卫：
    尺子读数只能给数值与方向，永远不该告诉模型“用哪个工具、怎么调”。
    """
    lowered = prompt.lower()
    for token in _POLLUTION_TOKEN_PREFIXES:
        if token.lower() in lowered:
            return f"尺子提示泄漏修复答案：命中 {token!r}"
    return None
