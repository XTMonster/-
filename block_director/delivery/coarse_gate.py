"""headless 粗排 gate 判定（R2-F1，纯层、无 bpy）。

UI 全管线用 ``pipeline_ui_inputs.coarse_is_ready`` 判粗排是否放行；headless
执行链必须用**同一判定**（单一真源），粗排未过时确定性阻止进细排。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def run_coarse_gate_decision(
    report: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """把粗排 pipeline_report 折成 headless 可消费的 gate 判定。

    与 ``coarse_is_ready`` 同口径：``coarse=pass`` 且 ``baseline=frozen``
    才放行；未跑/未过/缺 baseline 一律 blocked（不静默跳过）。
    """
    from block_director.layer5_orchestrator.pipeline_ui_inputs import (
        coarse_is_ready,
    )

    ready = bool(report) and coarse_is_ready(report)
    return {
        "ready": ready,
        "blocked": not ready,
        "gates": dict((report or {}).get("gates") or {}),
        "artifacts": dict((report or {}).get("artifacts") or {}),
    }


#: R2 空计划漏洞（final5 实锤）：模型把剧本角色表丢空、计划 characters=[]，
#: 粗排门因"空镜豁免"放行，细排构图 0.0。预检错误码：
E_PLAN_NO_SUBJECT = "E_PLAN_NO_SUBJECT"
E_PLAN_CAST_DROP = "E_PLAN_CAST_DROP"


def _plan_items(plan: Any) -> List[Any]:
    """兼容 ``Plan`` 对象与 dict 的镜头列表。"""
    shots = getattr(plan, "shots", None)
    if shots is None and isinstance(plan, Mapping):
        shots = plan.get("shots")
    if shots is None:
        return []
    return list(shots)


def _shot_chars(shot: Any) -> List[str]:
    """镜头角色：兼容 dataclass 与 dict。"""
    chars = getattr(shot, "characters", None)
    if chars is None and isinstance(shot, Mapping):
        chars = shot.get("characters")
    return [str(c) for c in (chars or []) if c]


def _shot_framing_target(shot: Any) -> Any:
    """镜头拍对象：兼容 dataclass 与 dict。"""
    target = getattr(shot, "framing_target", None)
    if target is None and isinstance(shot, Mapping):
        target = shot.get("framing_target")
    return target if isinstance(target, Mapping) else None


def _declared_roles(parsed: Any, brief: Any = None) -> List[str]:
    """剧本声明侧角色：以 ``cast_declarations``（【角色锚】）为唯一真源。

    brief 的 speakers/space 属 LLM/确定性抽取的**推断**，可能带别名或
    漏人，不参与 error 判据（避免误报）；只在解析结果缺失时作为补充来源。
    """
    roles = []
    if parsed is not None:
        roles = [str(n) for n
                 in (getattr(parsed, "cast_declarations", None) or []) if n]
    if roles:
        return roles
    if brief is not None:
        for key in ("speakers", "space"):
            for item in (getattr(brief, key, None) or []):
                if not isinstance(item, Mapping):
                    continue
                name = item.get("speaker") or item.get("character")
                if name and str(name) not in roles:
                    roles.append(str(name))
    return roles


def plan_integrity_findings(
    plan: Any,
    parsed: Any = None,
    brief: Any = None,
) -> List[Dict[str, Any]]:
    """粗排门前的计划完整性预检（纯层、无 bpy）。

    堵住"模型用空计划绕过粗排门"的洞（final5 真跑实锤：剧本角色锚声明
    米迦尔/伊恩/偷盗者，计划 characters=[] 且 reference 无主体 -> 四镜
    全走 ``empty_shot`` 豁免 -> 粗排 gate 零修正一轮 approved -> 细排
    构图 0.0）。判据只依赖**确定性声明**，不猜：

    * 剧本角色锚非空但计划全片无任何角色/拍对象/道具主体 ->
      :data:`E_PLAN_NO_SUBJECT`（error）；
    * 剧本角色锚非空、计划有主体，但没有一个主体能对应角色锚声明 ->
      :data:`E_PLAN_CAST_DROP`（error；提示模型若用了角色 id 就改回
      角色锚名字或显式声明映射，可回溯修复，不是判死）。
    * 剧本无角色锚声明 -> 不判（空镜剧本合法，不加戏）。
    """
    declared = _declared_roles(parsed, brief)
    declared = [name for name in declared if name]
    if not declared:
        return []

    planned: List[str] = []
    for shot in _plan_items(plan):
        planned.extend(_shot_chars(shot))
        target = _shot_framing_target(shot)
        if target is not None and target.get("ref"):
            planned.append(str(target["ref"]))
    planned = [name for name in planned if name]

    if not planned:
        return [{
            "check_id": E_PLAN_NO_SUBJECT,
            "severity": "error",
            "shot_id": "plan",
            "message": (
                f"剧本角色锚声明 {len(declared)} 个角色"
                f"（{'、'.join(declared)}），但计划全片没有任何角色/拍对象/"
                f"道具主体——疑似脱轨空计划，粗排门不放行。"),
        }]

    def _matches(declared_name: str, candidate: str) -> bool:
        a, b = declared_name, candidate
        return a == b or (len(a) >= 2 and len(b) >= 2
                          and (a in b or b in a))

    hit = any(any(_matches(name, cand) for cand in planned)
              for name in declared)
    if not hit:
        return [{
            "check_id": E_PLAN_CAST_DROP,
            "severity": "error",
            "shot_id": "plan",
            "message": (
                f"剧本角色锚声明 {len(declared)} 个角色"
                f"（{'、'.join(declared)}），但计划里的角色/拍对象"
                f"（{'、'.join(sorted(planned))}）没有一个对应这些名字；"
                f"若计划使用了角色 id，请改回角色锚声明名或显式声明"
                f"id→名字映射。"),
        }]
    return []


def merge_integrity_decision(
    decision: Dict[str, Any],
    findings: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """把预检 findings 并入粗排 gate 判定：有 error 一律 blocked。"""
    if not findings:
        return decision
    payload = dict(decision.get("payload") or {})
    payload["findings"] = list(payload.get("findings") or []) + list(findings)
    reasons = [str(f.get("message") or "")
               for f in findings if str(f.get("severity") or "") == "error"]
    return {
        "ready": False,
        "blocked": True,
        "reason": ("计划未兑现剧本角色/主体声明，禁止进入细排："
                   + "；".join(reasons)),
        "gates": dict(decision.get("gates") or {}),
        "artifacts": dict(decision.get("artifacts") or {}),
        "payload": payload,
        "integrity": [dict(f) for f in findings],
    }
