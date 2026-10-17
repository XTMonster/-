"""纠正候选纯函数（vlm-feedback 卡 V5）。

把几何告警（``contracts/guard.py::GuardWarning``）与 VLM 结构化问题
（``vlm-review/v2`` 的 issue 形状 ``{kind, subject, frame, suggested_tool}``）
按 ``(kind, subject)`` 合成最多 ``limit`` 条**纠正候选**，并渲染成修复提示里的
一段文字。

VLM 只作提示、永远不进门（不影响 passed/score）：候选的 ``advisory`` 字段
标出哪些是纯 VLM 意见；几何证据复用 ``repair.py::guard_warning_line`` 的
同一份实现（单一真源，不另写一套数值格式化）。

纯层：不 import bpy / driver / react，不做任何 I/O。缺必要键 / 坏值一律
:class:`ValueError`（不静默补默认）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from ..contracts.guard import Confidence, GuardWarning, Severity
from .repair import guard_warning_line


#: guard 告警类型 → VLM issue kind（卡 V5 映射表，逐行钉死）。
GUARD_KIND_MAP: Dict[str, str] = {
    "edge_clip": "subject_cut_by_edge",
    "subject_out_of_frame": "subject_cut_by_edge",
    "framing_too_loose": "subject_too_small",
    "lead_room_short": "lead_room_wrong",
    "occlusion": "occluded",
    "subject_not_visible": "occluded",
    "framing_too_tight": "shot_size_mismatch",
    "size_drift": "shot_size_mismatch",
}

#: 候选排序：both > geometry > vlm。
_SOURCE_RANK: Dict[str, int] = {"both": 0, "geometry": 1, "vlm": 2}
#: 同 source 内：error > warning > advisory。
_SEVERITY_RANK: Dict[str, int] = {"error": 0, "warning": 1, "advisory": 2}

#: 几何告警 dict 的必要键（等价于 GuardWarning.to_dict() 的子集）。
_GEOMETRY_REQUIRED = ("type", "subject", "severity", "frame_range", "evidence")
#: VLM issue dict 的必要键（vlm-review/v2 正常化后的形状）。
_VLM_REQUIRED = ("kind", "subject", "frame", "suggested_tool")


def kind_for_guard(guard_type: str) -> str:
    """guard 告警类型 → VLM issue kind；映射表之外的保留原名。"""
    return GUARD_KIND_MAP.get(guard_type, guard_type)


def _severity_value(value: Any) -> str:
    """把 Severity 枚举或合法字符串折成 ``error/warning/info``；其余报错。"""
    if isinstance(value, Severity):
        return value.value
    if isinstance(value, str) and value in ("error", "warning", "info"):
        return value
    raise ValueError(f"非法 severity：{value!r}（合法值：error/warning/info）")


def _coerce_list(items: Any, what: str) -> List[Any]:
    """None ⇒ []；可迭代 ⇒ list；不可迭代 ⇒ ValueError。"""
    if items is None:
        return []
    try:
        return list(items)
    except TypeError:
        raise ValueError(f"{what} 必须是可迭代序列：{items!r}") from None


def _geometry_fields(item: Any) -> Dict[str, Any]:
    """GuardWarning 对象或等价 dict ⇒ 归一化字段 dict；缺键/坏值 ⇒ ValueError。"""
    if isinstance(item, GuardWarning):
        guard_type = item.type
        if not isinstance(guard_type, str) or not guard_type:
            raise ValueError(f"几何告警 type 必须是非空字符串：{guard_type!r}")
        return {
            "type": guard_type,
            "subject": str(item.subject),
            "severity": _severity_value(item.severity),
            "frame_range": tuple(item.frame_range),
            "evidence": dict(item.evidence),
        }
    if not isinstance(item, dict):
        raise ValueError(f"几何告警必须是 GuardWarning 或等价 dict：{item!r}")
    missing = [key for key in _GEOMETRY_REQUIRED if key not in item]
    if missing:
        raise ValueError(f"几何告警缺少必要键：{', '.join(missing)}")
    guard_type = item["type"]
    if not isinstance(guard_type, str) or not guard_type:
        raise ValueError(f"几何告警 type 必须是非空字符串：{guard_type!r}")
    subject = item["subject"]
    if not isinstance(subject, str):
        raise ValueError(f"几何告警 subject 必须是字符串：{subject!r}")
    frame_range = item["frame_range"]
    if (not isinstance(frame_range, (tuple, list))
            or len(frame_range) != 2):
        raise ValueError(
            f"几何告警 frame_range 必须是长度为 2 的 (start, end)："
            f"{frame_range!r}")
    evidence = item["evidence"]
    if not isinstance(evidence, dict):
        raise ValueError(f"几何告警 evidence 必须是 dict：{evidence!r}")
    return {
        "type": guard_type,
        "subject": subject,
        "severity": _severity_value(item["severity"]),
        "frame_range": tuple(frame_range),
        "evidence": dict(evidence),
    }


def _vlm_fields(item: Any) -> Dict[str, Any]:
    """VLM issue dict ⇒ 归一化字段 dict；缺键/坏值 ⇒ ValueError。"""
    if not isinstance(item, dict):
        raise ValueError(f"VLM issue 必须是 dict：{item!r}")
    missing = [key for key in _VLM_REQUIRED if key not in item]
    if missing:
        raise ValueError(f"VLM issue 缺少必要键：{', '.join(missing)}")
    kind = item["kind"]
    if not isinstance(kind, str) or not kind:
        raise ValueError(f"VLM issue kind 必须是非空字符串：{kind!r}")
    subject = item["subject"]
    if not isinstance(subject, str):
        raise ValueError(f"VLM issue subject 必须是字符串：{subject!r}")
    frame = item["frame"]
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise ValueError(f"VLM issue frame 必须是整数：{frame!r}")
    tool = item["suggested_tool"]
    if not isinstance(tool, str):
        raise ValueError(f"VLM issue suggested_tool 必须是字符串：{tool!r}")
    return {"kind": kind, "subject": subject, "frame": frame,
            "suggested_tool": tool}


def _geometry_evidence(entry: Dict[str, Any]) -> str:
    """同键几何告警的证据：复用 ``repair.guard_warning_line``，多条用 ``；`` 连接。"""
    parts: List[str] = []
    for item in entry["geometry"]:
        warning = GuardWarning(
            shot_id="", frame_range=tuple(item["frame_range"]),
            type=item["type"], subject=item["subject"],
            evidence=dict(item["evidence"]),
            severity=Severity(item["severity"]),
            confidence=Confidence.HIGH)
        parts.append(guard_warning_line(warning))
    return "；".join(parts)


def _vlm_evidence(entry: Dict[str, Any]) -> str:
    """同键 VLM issue 的证据：每条 ``VLM: 第{frame}帧``，多条用 ``；`` 连接。"""
    return "；".join(f"VLM: 第{item['frame']}帧" for item in entry["vlm"])


def build_correction_candidates(guard_warnings: Iterable[Any],
                                vlm_issues: Iterable[Any], *,
                                limit: int = 3) -> List[Dict[str, Any]]:
    """把几何告警与 VLM 问题合成最多 ``limit`` 条纠正候选（纯函数）。

    - 几何告警只取 severity 为 error/warning 的，info 丢弃；非法 severity
      报错。合并键 ``(kind, subject)``：同键 ⇒ ``source="both"``，只几何 ⇒
      ``"geometry"``，只 VLM ⇒ ``"vlm"``。
    - severity：几何取最重（error > warning）；纯 VLM 为 ``"advisory"``。
      ``advisory == (source == "vlm")``。suggested_tool 取 VLM 第一条非空
      建议，纯几何为空串。
    - evidence：几何用 :func:`repair.guard_warning_line` 的同款文本；VLM 写
      ``VLM: 第{frame}帧``；both 用 ``；`` 连接。
    - 排序：both > geometry > vlm；同 source 内 error > warning > advisory；
      再按首次出现顺序（稳定）。
    - ``limit`` 截断到上限；``limit < 1`` / 非整数 ⇒ :class:`ValueError`。
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 必须是 >=1 的整数：{limit!r}")
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    sequence = 0
    for raw in _coerce_list(guard_warnings, "guard_warnings"):
        item = _geometry_fields(raw)
        if item["severity"] == "info":
            continue
        key = (kind_for_guard(item["type"]), item["subject"])
        sequence += 1
        if key not in groups:
            groups[key] = {
                "kind": key[0], "subject": key[1], "source": "geometry",
                "severity": item["severity"], "geometry": [item],
                "vlm": [], "first": sequence,
            }
            order.append(key)
        else:
            entry = groups[key]
            entry["geometry"].append(item)
            if item["severity"] == "error":
                entry["severity"] = "error"
    for raw in _coerce_list(vlm_issues, "vlm_issues"):
        item = _vlm_fields(raw)
        key = (item["kind"], item["subject"])
        sequence += 1
        if key not in groups:
            groups[key] = {
                "kind": key[0], "subject": key[1], "source": "vlm",
                "severity": "advisory", "geometry": [], "vlm": [item],
                "first": sequence,
            }
            order.append(key)
        else:
            entry = groups[key]
            entry["source"] = "both"
            entry["vlm"].append(item)
    payload: List[Tuple[int, Dict[str, Any]]] = []
    for key in order:
        entry = groups[key]
        geometry_part = (_geometry_evidence(entry)
                         if entry["geometry"] else "")
        vlm_part = _vlm_evidence(entry) if entry["vlm"] else ""
        tool = next((item["suggested_tool"] for item in entry["vlm"]
                     if item["suggested_tool"]), "")
        payload.append((entry["first"], {
            "kind": entry["kind"],
            "subject": entry["subject"],
            "source": entry["source"],
            "advisory": entry["source"] == "vlm",
            "severity": entry["severity"],
            "suggested_tool": tool,
            "evidence": "；".join(
                part for part in (geometry_part, vlm_part) if part),
        }))
    payload.sort(key=lambda pair: (
        _SOURCE_RANK[pair[1]["source"]],
        _SEVERITY_RANK[pair[1]["severity"]],
        pair[0]))
    return [item for _, item in payload[:limit]]


def _render_item(item: Dict[str, Any], shot_id: str) -> str:
    """一条候选 → 一行 ``- 镜 …｜subject｜kind｜evidence``（含标记后缀）。"""
    line = (f"- 镜 {shot_id}｜{item['subject']}｜{item['kind']}｜"
            f"{item.get('evidence', '')}")
    if item.get("advisory"):
        line += "（仅供参考）"
    tool = str(item.get("suggested_tool", "") or "")
    if tool:
        line += f"｜建议工具 {tool}"
    return line


def render_candidates(candidates: Iterable[Any], shot_id: str, *,
                      max_chars: int = 300) -> str:
    """把候选渲染成修复提示里的一段文字。

    空 ⇒ ``""``。否则首行 ``【视觉复核｜镜 <shot_id>】``，每条一行
    ``- 镜 <shot_id>｜<subject>｜<kind>｜<evidence>``；advisory 加
    （仅供参考）、有 tool 加｜建议工具。

    总长 ≤ ``max_chars``：整条追加，放不下的那条起整条舍弃（不再继续追加
    更靠后的条目）；连第一条都放不下 ⇒ 只返回首行。
    """
    items = _coerce_list(candidates, "candidates")
    if not items:
        return ""
    header = f"【视觉复核｜镜 {shot_id}】"
    lines = [header]
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"纠正候选必须是 dict：{item!r}")
        if not all(isinstance(item.get(key), str)
                   for key in ("subject", "kind")):
            raise ValueError(f"纠正候选缺少 subject/kind：{item!r}")
        line = _render_item(item, shot_id)
        candidate = lines + [line]
        if sum(len(part) for part in candidate) + len(candidate) - 1 \
                <= max_chars:
            lines.append(line)
        else:
            break
    return "\n".join(lines)
