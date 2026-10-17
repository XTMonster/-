"""插件内空间尺：计划级约束与节奏审核。

这是空间尺进入 BlockDirector 的计划级接缝。它不依赖 bpy，也不负责猜测镜头；
只把已经理解出的角色/时长/节奏约束落实到可执行的 :class:`Plan` 上。

两个入口：
* :func:`audit_and_prepare_plan` —— 只审核并落实 cast（向后兼容的轻量接缝）；
* :func:`apply_plan_prescriptions` —— 审核＋**应用处方**（retime_shot /
  restore_cast），并返回契约形状的处方记录与计划级测量（Ticket 05）。
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

from ..layer1_input.dialogue_timing import DIALOGUE_TAIL_FRAMES
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


def _restore_cast(plan: Plan, brief: Any
                  ) -> Tuple[List[dict], List[AuditError]]:
    """从 ``responsibility.white_model`` 与 SceneBrief 已知角色交集恢复 cast。

    返回 ``(恢复记录, findings)``；恢复记录形如
    ``{"shot_id", "characters", "source"}``，供处方与审计共用。
    """
    known = _brief_names(brief)
    recovered: List[dict] = []
    findings: List[AuditError] = []
    for shot in plan.shots:
        if shot.characters:
            continue
        responsibility = getattr(shot, "responsibility", None)
        white_model = list(getattr(responsibility, "white_model", []) or [])
        names = [name for name in white_model if str(name) in known]
        if names:
            shot.characters = list(names)
            recovered.append({
                "shot_id": str(shot.shot_id),
                "characters": list(names),
                "source": "responsibility.white_model",
            })
            findings.append(_finding(
                Severity.WARNING, RULE_CAST,
                f"{shot.shot_id} 的角色从 responsibility.white_model 恢复到 characters："
                f"{'、'.join(names)}",
                target=shot.shot_id,
                suggestion="后续计划生成必须直接填写 characters 字段"))
        elif white_model:
            findings.append(_finding(
                Severity.ERROR, RULE_CAST,
                f"{shot.shot_id} 声明了白模元素，但没有可确认的角色落点",
                target=shot.shot_id,
                suggestion="补齐 characters，或明确这些元素不是角色"))
    return recovered, findings


def _rhythm_findings(plan: Plan, *,
                     declared_total_seconds: Optional[float],
                     fps: int) -> List[AuditError]:
    """全场时长 vs 声明总时长 ＋ 相邻长镜头节奏同质（只报不修）。"""
    findings: List[AuditError] = []
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
    return findings


def _per_shot_duration_findings(plan: Plan, declared_shots: Iterable[Any],
                                fps: int) -> List[AuditError]:
    """逐镜声明 vs 计划时长漂移（SR002，只报不修）。

    声明的第 n 个镜号 ↔ 计划的第 n 个镜头（与 R015 同顺序口径），
    偏差超过 0.2 s 记 ERROR（hard finding）。与
    :func:`apply_plan_prescriptions` 的 ``retime_shot`` 同容差、同语义，
    但这里只暴露审计，不改帧——处方是否落地由调用方决定。
    """
    findings: List[AuditError] = []
    declared = list(declared_shots or [])
    for index, shot in enumerate(plan.shots):
        if index >= len(declared):
            break
        declared_seconds = getattr(declared[index], "declared_seconds", None)
        if declared_seconds is None:
            continue
        planned_s = shot.duration_frames / float(fps)
        if abs(planned_s - float(declared_seconds)) > 0.2:
            findings.append(_finding(
                Severity.ERROR, RULE_RHYTHM,
                f"逐镜 {shot.shot_id} 时长漂移：声明 {float(declared_seconds):g}s，"
                f"计划 {planned_s:g}s（差 {planned_s - float(declared_seconds):+.3g}s，"
                f"容差 0.2s）",
                target=shot.shot_id,
                suggestion="按声明时长重新分配该镜（retime_shot），"
                            "不得让台词自行拉长整场"))
    return findings


def audit_and_prepare_plan(plan: Plan, *, brief: Any = None,
                           declared_total_seconds: Optional[float] = None,
                           declared_shots: Iterable[Any] = (),
                           fps: int = 24) -> Tuple[Plan, List[AuditError]]:
    """在构建前落实角色，并返回空间/节奏发现。

    角色只从 ``responsibility.white_model`` 与 SceneBrief 的已知角色交集恢复，
    不从自由文本猜角色；因此不会把摊位、海面等环境元素误建成人物。

    ``declared_shots`` 可选：逐镜时长漂移审计（SR002）按顺序对拍声明与
    计划，偏差 >0.2s 记 ERROR；不传则保持既有行为（总时长＋节奏）。
    """
    _recovered, findings = _restore_cast(plan, brief)
    findings.extend(_per_shot_duration_findings(
        plan, declared_shots=declared_shots, fps=fps))
    findings.extend(_rhythm_findings(
        plan, declared_total_seconds=declared_total_seconds, fps=fps))
    return plan, findings


def _plan_measurement(shot_id: str, metric: str, value: Any, unit: str,
                      source: str, expected: Any = None) -> dict:
    """契约 measurement 形状的计划级测量（普通 dict，可直接 JSON）。"""
    return {
        "measurement_id": f"m_{shot_id}_{metric}",
        "shot_id": shot_id, "transition_id": None, "subject_id": None,
        "frame": None, "metric": metric, "value": value,
        "expected": expected, "unit": unit, "source": source,
        "provenance": source,
    }


def _dialogue_latest_end(shot) -> int:
    """这一镜对白的最晚结束帧；没有对白返回 0。"""
    latest = 0
    for item in getattr(shot, "dialogues", None) or []:
        if not isinstance(item, dict):
            continue
        latest = max(latest, int(item.get("end_frame") or 0))
    return latest


def apply_plan_prescriptions(
    plan: Plan, *, brief: Any = None,
    declared_total_seconds: Optional[float] = None,
    declared_seconds_by_shot: Optional[dict] = None,
    fps: int = 24,
) -> Tuple[Plan, List[AuditError], List[dict], List[dict]]:
    """审核并应用计划级处方（Ticket 05）。

    返回 ``(更新后的计划, 审核发现, 处方记录, 计划级测量)``：
    * ``restore_cast``：白模角色 → characters（只交集恢复，不发明）；
    * ``retime_shot``：声明 vs 计划时长漂移 > 0.2 s 时按声明重设帧数；
      对白＋收尾余量装不下新时长 → applied=False 并说明（不改帧、不硬缩）；
    * 全场时长漂移**只报不自动重排**（缺逐镜声明的 provider 数据，擅自
      重排会把对话语义改坏）。
    """
    findings: List[AuditError] = []
    prescriptions: List[dict] = []
    measurements: List[dict] = []

    recovered, cast_findings = _restore_cast(plan, brief)
    findings.extend(cast_findings)
    for record in recovered:
        shot_id = record["shot_id"]
        characters = record["characters"]
        cast_metric_id = f"m_{shot_id}_cast_presence"
        measurements.append(_plan_measurement(
            shot_id, "cast_presence", len(characters), "count",
            "plan_intent", expected=len(characters)))
        prescriptions.append({
            "prescription_id": f"p_restore_cast_{shot_id}",
            "shot_id": shot_id,
            "operation": "restore_cast",
            "parameters": {
                "source": record["source"],
                "characters": characters,
            },
            "precondition_measurement_ids": [],
            "postcondition_measurement_ids": [cast_metric_id],
            "postcondition": "每个需要白模的镜头 characters 非空，且只含可确认角色",
            "applied": True,
            "applied_at": "",
            "waived": False,
            "waive_reason": "",
        })

    declared_map = dict(declared_seconds_by_shot or {})
    for shot in plan.shots:
        shot_id = str(shot.shot_id)
        planned_before_s = shot.duration_frames / float(fps)
        declared_s = declared_map.get(shot_id)
        planned_metric = f"m_{shot_id}_shot_duration_planned"
        if declared_s is not None:
            declared_s = float(declared_s)
            declared_metric = f"m_{shot_id}_shot_duration_declared"
            measurements.append(_plan_measurement(
                shot_id, "shot_duration_declared",
                round(declared_s, 3), "seconds", "script_declaration",
                expected=round(declared_s, 3)))
            measurements.append(_plan_measurement(
                shot_id, "shot_duration_planned_before",
                round(planned_before_s, 3), "seconds", "plan_intent"))
            if abs(planned_before_s - declared_s) <= 0.2:
                measurements.append(_plan_measurement(
                    shot_id, "shot_duration_planned",
                    round(planned_before_s, 3), "seconds", "plan_intent"))
                continue
            new_frames = max(1, int(round(declared_s * fps)))
            latest = _dialogue_latest_end(shot)
            fits = latest + DIALOGUE_TAIL_FRAMES <= new_frames
            applied = bool(fits)
            if applied:
                shot.duration_frames = new_frames
            measurements.append(_plan_measurement(
                shot_id, "shot_duration_planned",
                round((shot.duration_frames if applied else planned_before_s)
                      / float(fps), 3), "seconds", "plan_intent"))
            prescriptions.append({
                "prescription_id": f"p_retime_{shot_id}",
                "shot_id": shot_id,
                "operation": "retime_shot",
                "parameters": {
                    "old_frames": int(planned_before_s * fps),
                    "new_frames": new_frames,
                    "dialogue_policy": {
                        "tail_frames": DIALOGUE_TAIL_FRAMES,
                        "latest_dialogue_end": latest,
                    },
                },
                "precondition_measurement_ids": [
                    f"m_{shot_id}_shot_duration_declared",
                    f"m_{shot_id}_shot_duration_planned_before"],
                "postcondition_measurement_ids": [planned_metric],
                "postcondition": "该镜时长回到声明值，且对白＋收尾余量仍在镜内",
                "applied": applied,
                "applied_at": "",
                "waived": not applied,
                "waive_reason": ("" if applied else
                                 f"对白到第 {latest} 帧 + {DIALOGUE_TAIL_FRAMES} 帧"
                                 f"余量超出声明时长 {declared_s:g}s，未改帧"),
            })
            if not applied:
                #: Ticket 03 验收第二层：漂移**没被自动修复**时，残留的
                #: 逐镜时长漂移是硬发现（SR002 ERROR）——施加处方后仍不达标，
                #: 由驱动器阻断构建，直到对白改短或按既有 policy 显式豁免。
                findings.append(_finding(
                    Severity.ERROR, RULE_RHYTHM,
                    f"逐镜 {shot_id} 时长漂移无法自动修复：声明 {declared_s:g}s，"
                    f"计划 {planned_before_s:g}s（差 "
                    f"{planned_before_s - declared_s:+.3g}s，容差 0.2s），"
                    f"对白＋收尾余量装不下声明时长",
                    target=shot_id,
                    suggestion="缩短该镜对白或按既有审核 policy 显式豁免"))
        else:
            measurements.append(_plan_measurement(
                shot_id, "shot_duration_planned",
                round(planned_before_s, 3), "seconds", "plan_intent"))

    findings.extend(_rhythm_findings(
        plan, declared_total_seconds=declared_total_seconds, fps=fps))
    return plan, findings, prescriptions, measurements
