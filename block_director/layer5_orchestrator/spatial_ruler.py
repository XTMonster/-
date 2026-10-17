"""插件内空间尺：计划级约束与节奏审核。

这是空间尺进入 BlockDirector 的计划级接缝。它不依赖 bpy，也不负责猜测镜头；
只把已经理解出的角色/时长/节奏约束落实到可执行的 :class:`Plan` 上。
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

from ..contracts.audit import AuditError
from ..contracts.enums import Severity
from ..contracts.plan import Plan
from .compliance import _finding


RULE_CAST = "SR001"
RULE_RHYTHM = "SR002"


def _brief_names(brief: Any) -> set[str]:
    names: set[str] = set()
    for item in getattr(brief, "speakers", []) or []:
        names.update(str(item.get(k) or "").strip()
                     for k in ("speaker", "listener"))
    for item in getattr(brief, "gaze", []) or []:
        names.update(str(item.get(k) or "").strip()
                     for k in ("from", "to"))
    for item in getattr(brief, "space", []) or []:
        names.update(str(item.get(k) or "").strip()
                     for k in ("character", "relative_to"))
    return {name for name in names if name}


def audit_and_prepare_plan(plan: Plan, *, brief: Any = None,
                           declared_total_seconds: Optional[float] = None,
                           fps: int = 24) -> Tuple[Plan, List[AuditError]]:
    """在构建前落实角色，并返回空间/节奏发现。

    角色只从 ``responsibility.white_model`` 与 SceneBrief 的已知角色交集恢复，
    不从自由文本猜角色；因此不会把摊位、海面等环境元素误建成人物。
    """
    findings: List[AuditError] = []
    known = _brief_names(brief)
    for shot in plan.shots:
        if shot.characters:
            continue
        responsibility = getattr(shot, "responsibility", None)
        white_model = list(getattr(responsibility, "white_model", []) or [])
        recovered = [name for name in white_model if str(name) in known]
        if recovered:
            shot.characters = recovered
            findings.append(_finding(
                Severity.WARNING, RULE_CAST,
                f"{shot.shot_id} 的角色从 responsibility.white_model 恢复到 characters："
                f"{'、'.join(recovered)}",
                target=shot.shot_id,
                suggestion="后续计划生成必须直接填写 characters 字段"))
        elif white_model:
            findings.append(_finding(
                Severity.ERROR, RULE_CAST,
                f"{shot.shot_id} 声明了白模元素，但没有可确认的角色落点",
                target=shot.shot_id,
                suggestion="补齐 characters，或明确这些元素不是角色"))

    if declared_total_seconds is not None:
        actual = plan.total_frames / float(fps)
        delta = actual - float(declared_total_seconds)
        if abs(delta) > 0.2:
            findings.append(_finding(
                Severity.ERROR, RULE_RHYTHM,
                f"全场时长 {actual:g}s 偏离声明 {float(declared_total_seconds):g}s "
                f"（差 {delta:+.3g}s）",
                target="plan",
                suggestion="按声明时长重新分配镜头，不得让单镜台词自行拉长整场"))

    for previous, current in zip(plan.shots, plan.shots[1:]):
        prev_s = previous.duration_frames / float(fps)
        curr_s = current.duration_frames / float(fps)
        if prev_s >= 5.0 and curr_s >= 5.0 and abs(prev_s - curr_s) < 0.5:
            findings.append(_finding(
                Severity.WARNING, RULE_RHYTHM,
                f"{previous.shot_id}→{current.shot_id} 连续长镜头节奏同质（"
                f"{prev_s:g}s→{curr_s:g}s）",
                target=current.shot_id,
                suggestion="检查是否需要景别/运动/时长形成节奏对比"))
    return plan, findings
