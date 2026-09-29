"""镜头清单 shots.json（执行文档 v1.2 §15.4）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ..contracts.plan import Plan

FPS = 24


def generated_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_manifest(plan: Plan, *,
                   build_summary: Optional[Dict[str, Any]] = None,
                   resolution: Sequence[int] = (1280, 720),
                   fps: int = FPS,
                   project: str = "BlockDirector",
                   style: str = "",
                   generated_at: Optional[str] = None,
                   llm_calls: int = 0,
                   retrieval_calls: int = 0,
                   crowd: Optional[Sequence[Dict[str, Any]]] = None,
                   parsed=None,
                   timing_overrides: Optional[Sequence[Dict[str, Any]]] = None,
                   action_conflicts: Optional[Sequence[Dict[str, Any]]] = None,
                   audit_pass_rate: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Any]:
    """把分镜计划与构建结果拼成交付用清单。

    v1.4 R45：``llm_calls`` / ``retrieval_calls`` / ``crowd{}`` 三个字段的
    生产**提前到 P9.4**——P9.4 的 RK-18、P13 的 "``llm_calls`` ≤ 528" 与
    P12 的 RK-16 都要读它们，而此前 manifest 一个都不写。

    v1.4 P15（§3.3）：补齐交付字段 schema。逐镜字段是 ``declared{}`` /
    ``labels{}`` / ``movements[]``，跨镜字段是 ``crowd{}`` /
    ``timing_overrides[]`` / ``action_conflicts[]`` / ``dialogue_pins[]`` /
    ``audit_pass_rate{}``。
    """
    results = {r.get("shot_id"): r for r in
               (build_summary or {}).get("results", [])}
    label_offsets = dict(((build_summary or {}).get("label_report") or {})
                         .get("offsets") or {})
    declarations = _declarations(parsed)

    shots: List[Dict[str, Any]] = []
    cursor = 1
    for order, shot in enumerate(plan.shots, start=1):
        result = results.get(shot.shot_id, {})
        declared = declarations.get(order - 1)
        start = int(result.get("start_frame", cursor))
        end = int(result.get("end_frame", start + shot.duration_frames - 1))
        cursor = end + 1
        shots.append({
            "shot_id": shot.shot_id,
            "order": shot.order or order,
            "intent": shot.intent,
            "shot_type": str(shot.shot_type),
            "start_frame": start,
            "end_frame": end,
            "duration_frames": end - start + 1,
            "duration_seconds": round((end - start + 1) / fps, 3),
            "video_file": f"blockout_{shot.shot_id}.mp4",
            "first_frame": f"first_frames/{shot.shot_id}.png",
            "camera": {
                "name": result.get("camera", f"BD_Cam_{shot.shot_id}"),
                "position": result.get("camera_position"),
                "lens": result.get("lens"),
            },
            "characters": list(shot.characters),
            "dialogue_ids": list(shot.dialogue_ids),
            "action_types": [str(a.get("action_type")) for a in shot.actions],
            "axis_note": shot.axis_note,
            "continuity_in": shot.continuity_in,
            "degraded": bool(result.get("warnings")),
            "warnings": list(result.get("warnings", [])),
            # ---- v1.4 P15（§3.3）的逐镜字段 ----
            "declared": _declared_payload(declared, shot),
            "labels": _labels_payload(shot, label_offsets),
            "movements": _movements_payload(shot, declared),
        })

    return {
        "project": project,
        "fps": fps,
        "resolution": list(resolution),
        "style": style,
        "generated_at": generated_at or generated_now(),
        "scene_heading": plan.scene_heading,
        "total_frames": sum(s["duration_frames"] for s in shots),
        "llm_calls": int(llm_calls or 0),
        "retrieval_calls": int(retrieval_calls or 0),
        "crowd": {
            "entries": [dict(item) for item in (crowd or [])],
            "total": sum(int(item.get("count") or 0)
                         for item in (crowd or [])),
        },
        "timing_overrides": [dict(item) for item in (timing_overrides or [])],
        "action_conflicts": [dict(item) for item in (action_conflicts or [])],
        "dialogue_pins": [dict(pin) for shot in plan.shots
                          for pin in (getattr(shot, "dialogue_pins", None)
                                      or [])],
        "audit_pass_rate": dict(audit_pass_rate or {
            "numerator": 0, "denominator": 0, "rules": [],
            "sampled_frames": 0, "exempt_shots": []}),
        "shots": shots,
    }


def _declarations(parsed) -> Dict[int, Any]:
    """分镜表声明：``{index: ParsedShotDeclaration}``（按镜序）。"""
    if parsed is None:
        return {}
    return {index: item for index, item in
            enumerate(getattr(parsed, "declared_shots", []) or [])}


def _declared_payload(declaration, shot) -> Dict[str, Any]:
    """§3.3 的 ``declared{}``：**全部可空**，没有声明时逐字段为 ``None``。"""
    payload = {
        "shot_number": None, "camera_number": None, "technique": None,
        "transition": None, "location": None, "time": None, "lighting": None,
        "sfx": None, "declared_duration_s": None,
    }
    if declaration is None:
        pinned = int(getattr(shot, "declared_shot_number", 0) or 0)
        payload["shot_number"] = pinned or None
        return payload
    payload.update({
        "shot_number": int(getattr(declaration, "shot_number", 0) or 0) or None,
        "camera_number": declaration.field("机号") or None,
        "technique": declaration.field("拍摄手法") or None,
        "transition": declaration.field("技巧") or None,
        "location": declaration.field("地点") or None,
        "time": declaration.field("时间") or None,
        "lighting": declaration.field("灯光") or None,
        "sfx": declaration.field("音效") or None,
        "declared_duration_s": getattr(declaration, "declared_seconds", None),
    })
    return payload


def _labels_payload(shot, offsets: Dict[str, Any]) -> Dict[str, Any]:
    """§3.3 的 ``labels{}``：``{char_id: {text, anchor_z, offset_px}}``。"""
    payload: Dict[str, Any] = {}
    for character_id in shot.characters or []:
        entry = offsets.get(str(character_id))
        if entry is None:
            continue
        payload[str(character_id)] = {
            "text": str(entry.get("text") or ""),
            "anchor_z": entry.get("anchor_z"),
            "offset_px": [0.0, float(entry.get("applied_offset_px") or 0.0)],
            "offset_reason": str(entry.get("offset_reason") or "none"),
        }
    return payload


def _movements_payload(shot, declaration) -> List[Dict[str, Any]]:
    """§3.3 的 ``movements[]``：``source`` 只用 R46 的统一词表。

    本版还没有知识层（P14 才接），所以来源只有两种：剧本**声明**的运镜
    （``declared``）与计划自己排的（``planned``）。P14 之后 ``theory`` /
    ``experience`` / ``lesson`` / ``case`` 由知识 trace 填。
    """
    items = []
    declared_move = str(getattr(declaration, "camera_move", "") or "")
    for raw in (getattr(shot, "camera", None) or {}).get("movements", []) or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or raw.get("kind") or "")
        if not kind:
            continue
        source = "declared" if declared_move and kind == declared_move \
            else "planned"
        items.append({
            "kind": kind,
            "start_frame": int(raw.get("start_frame") or 1),
            "end_frame": int(raw.get("end_frame") or shot.duration_frames),
            "source": source,
        })
    return items
