"""剧本落实审核（v1.3 的 R015 / R016）。

这一层回答的是一个很朴素的问题：**导演写下来的东西，最后做出来了吗？**

* 声明侧 = ``ParsedScript.declared_shots``（分镜表解析的结果，见
  ``layer1_input/shotlist.py``）；
* 落实侧 = ``Plan``（阶段 A 的拍摄清单 + 阶段 B1 的逐镜草案）。

v1.2 没有任何环节做这件事：计划和剧本各写各的，台词被改、镜号被合并、
时长被拉长都没有人发现。实测把 6 个镜号压成 2 个、把声明 33 秒的片子
规划成 39.5 秒，直到人工比对视频才发现。

纯计算，不依赖 bpy，可直接单测。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..contracts.audit import AuditError
from ..contracts.enums import AuditLevel, Severity
from ..contracts.plan import Plan
from ..layer1_input.timing import frames_from_seconds

FPS = 24
TOLERANCE_SECONDS = 0.2

RULE_COUNT = "R015"
RULE_DURATION = "R015"
RULE_SHOT_TYPE = "R015"
RULE_DIALOGUE = "R016"

#: v1.3：注视落实（SceneBrief.gaze 必须被 shot.gaze 落实，或显式豁免）
RULE_GAZE = "R013"

CODE_SCRIPT = "E_SCRIPT_001"


def _finding(severity: Severity, rule: str, message: str,
             target: str = "", suggestion: str = "") -> AuditError:
    return AuditError(rule=rule, code=CODE_SCRIPT, severity=severity,
                      target=target, message=message, suggestion=suggestion)


def _declared_shots(script) -> List[Any]:
    return list(getattr(script, "declared_shots", []) or [])


def _gaze_pairs(entries) -> List[tuple]:
    pairs: List[tuple] = []
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or "").strip()
        target = str(item.get("to") or "").strip()
        if source and target:
            pairs.append((source, target))
    return pairs


def check_gaze(plan: Optional[Plan], brief, *,
               strict: bool = False) -> List[AuditError]:
    """R013：阶段 S 读出来的注视关系，计划有没有落实（§3.5）。

    默认只是告警——理解可能有误，不该因为一条推断就把运行判为失败；
    ``audit.level = strict`` 时升级为错误，供"零容忍"的场合使用。
    """
    if plan is None or brief is None or not getattr(brief, "gaze", None):
        return []
    severity = Severity.ERROR if strict else Severity.WARNING
    findings: List[AuditError] = []
    for index, shot in enumerate(plan.shots, start=1):
        shot_id = str(getattr(shot, "shot_id", "") or "")
        expected = set(_gaze_pairs(brief.gazes_in(shot_id, index)))
        if not expected:
            continue
        actual = set(_gaze_pairs(getattr(shot, "gaze", None)))
        missing = sorted(expected - actual)
        if not missing:
            continue
        detail = "、".join(f"{source}→{target}" for source, target in missing)
        findings.append(_finding(
            severity, RULE_GAZE,
            f"{shot_id} 没有落实剧本理解的注视关系：{detail}",
            target=shot_id,
            suggestion="让角色互相看向对方（face_character / look_at），"
                       "或在 SceneBrief 里删掉这条注视"))
    return findings


def _shot_seconds(shot, fps: int) -> float:
    return round(int(shot.duration_frames) / float(fps), 3)


def check_compliance(plan: Plan, script, *, fps: int = FPS,
                     tolerance_seconds: float = TOLERANCE_SECONDS,
                     brief=None, audit_level=None
                     ) -> List[AuditError]:
    """返回全部落实偏差；空列表表示逐条对上。

    R015/R016 在声明为空（叙事剧本、没有分镜表）时**不做任何判定**——它们
    只在"导演明确写下了约束"时生效，绝不凭空发明约束。R013（注视落实）不同：
    它比较的是阶段 S 的理解与计划，与有没有分镜表无关。
    """
    strict = str(audit_level or "") == str(AuditLevel.STRICT)
    findings: List[AuditError] = check_gaze(plan, brief, strict=strict)
    declared = _declared_shots(script)
    if not declared or plan is None:
        return findings

    margin = max(int(round(float(tolerance_seconds) * int(fps))), 1)
    planned = list(plan.shots)

    # R015 —— 镜号数量与顺序
    if len(planned) != len(declared):
        findings.append(_finding(
            Severity.ERROR, RULE_COUNT,
            f"分镜表声明了 {len(declared)} 个镜号，计划里只有 "
            f"{len(planned)} 个镜头",
            target="plan",
            suggestion="补齐缺失的镜号；镜号数量与顺序是硬约束"))

    # R015 —— 逐镜时长（按顺序对齐：声明的第 n 个镜号 ↔ 计划的第 n 个镜头）
    for index, item in enumerate(declared):
        if index >= len(planned):
            break
        shot = planned[index]
        if item.declared_seconds is None:
            continue
        expected = frames_from_seconds(item.declared_seconds, fps)
        actual = int(shot.duration_frames)
        if abs(actual - expected) > margin:
            findings.append(_finding(
                Severity.ERROR, RULE_DURATION,
                f"镜号{item.shot_number} 声明 "
                f"{item.declared_seconds:g} 秒（{expected} 帧），"
                f"计划给的是 {actual} 帧（{_shot_seconds(shot, fps):g} 秒）",
                target=shot.shot_id,
                suggestion="时长以剧本声明为准"))

    # R015 —— 景别提示（映射是有损启发式，因此只告警并附上原文）
    for index, item in enumerate(declared):
        if index >= len(planned) or not item.shot_type:
            continue
        shot = planned[index]
        actual_type = str(shot.shot_type)
        if actual_type.upper() != item.shot_type:
            distance_text = item.field("拍摄距离") or item.shot_type
            findings.append(_finding(
                Severity.WARNING, RULE_SHOT_TYPE,
                f"镜号{item.shot_number} 声明的拍摄距离是「{distance_text}」"
                f"（对应 {item.shot_type}），计划给的是 {actual_type}",
                target=shot.shot_id,
                suggestion="景别以剧本声明为准；确有理由改变时请说明"))

    # R016 —— 台词逐字一致
    for index, item in enumerate(declared):
        if index >= len(planned):
            break
        shot = planned[index]
        declared_texts = [str(dialogue.text or "").strip()
                          for dialogue in item.dialogues
                          if str(dialogue.text or "").strip()]
        if not declared_texts:
            continue
        actual_texts = {str(entry.get("text") or "").strip()
                        for entry in (shot.dialogues or [])}
        for text in declared_texts:
            if text not in actual_texts:
                findings.append(_finding(
                    Severity.ERROR, RULE_DIALOGUE,
                    f"镜号{item.shot_number} 的台词在计划里找不到："
                    f"「{text}」",
                    target=shot.shot_id,
                    suggestion="台词必须逐字沿用剧本，不得改写或丢弃"))
        declared_set = set(declared_texts)
        for text in sorted(actual_texts - declared_set):
            if text:
                findings.append(_finding(
                    Severity.WARNING, RULE_DIALOGUE,
                    f"镜号{item.shot_number} 出现了剧本没有的台词：「{text}」",
                    target=shot.shot_id,
                    suggestion="剧本没有的台词应删掉，除非确有必要"))

    return findings


def compliance_report(plan: Plan, script, *, fps: int = FPS,
                      tolerance_seconds: float = TOLERANCE_SECONDS,
                      brief=None, audit_level=None
                      ) -> Dict[str, Any]:
    """``script_compliance.json`` 的内容：逐条列出声明 → 落实 → 偏差。"""
    declared = _declared_shots(script)
    findings = check_compliance(plan, script, fps=fps,
                                tolerance_seconds=tolerance_seconds,
                                brief=brief, audit_level=audit_level)
    planned = list(plan.shots) if plan is not None else []

    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(declared):
        shot = planned[index] if index < len(planned) else None
        expected = (frames_from_seconds(item.declared_seconds, fps)
                    if item.declared_seconds is not None else None)
        rows.append({
            "declared_shot_number": item.shot_number,
            "declared_seconds": item.declared_seconds,
            "declared_frames": expected,
            "declared_target": item.declared_dialogue_seconds,
            "declared_shot_type": item.shot_type,
            "declared_characters": list(item.characters),
            "declared_dialogues": [dialogue.text for dialogue in item.dialogues],
            "plan_shot_id": shot.shot_id if shot is not None else None,
            "plan_frames": int(shot.duration_frames) if shot is not None else None,
            "plan_shot_type": str(shot.shot_type) if shot is not None else None,
            "plan_dialogues": [str(entry.get("text") or "")
                               for entry in (shot.dialogues or [])]
            if shot is not None else [],
            "frames_delta": (int(shot.duration_frames) - expected)
            if (shot is not None and expected is not None) else None,
        })

    declared_total = getattr(script, "declared_total_seconds", None)
    plan_total = sum(int(shot.duration_frames) for shot in planned)
    return {
        "ok": not any(item.is_error for item in findings),
        "declared_shot_count": len(declared),
        "plan_shot_count": len(planned),
        "declared_total_seconds": declared_total,
        "plan_total_seconds": round(plan_total / float(fps), 3),
        "fps": int(fps),
        "brief_source": (getattr(brief, "source", "") if brief is not None
                         else ""),
        "rows": rows,
        "findings": [item.to_dict() for item in findings],
    }
