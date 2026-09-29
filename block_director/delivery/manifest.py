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
                   crowd: Optional[Sequence[Dict[str, Any]]] = None
                   ) -> Dict[str, Any]:
    """把分镜计划与构建结果拼成交付用清单。

    v1.4 R45：``llm_calls`` / ``retrieval_calls`` / ``crowd{}`` 三个字段的
    生产**提前到 P9.4**——P9.4 的 RK-18、P13 的 "``llm_calls`` ≤ 528" 与
    P12 的 RK-16 都要读它们，而此前 manifest 一个都不写。
    """
    results = {r.get("shot_id"): r for r in
               (build_summary or {}).get("results", [])}

    shots: List[Dict[str, Any]] = []
    cursor = 1
    for order, shot in enumerate(plan.shots, start=1):
        result = results.get(shot.shot_id, {})
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
        "shots": shots,
    }
