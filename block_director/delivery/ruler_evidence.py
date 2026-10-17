"""空间尺观测交付证据（Ticket 06 纯层）。

把计划级处方、逐镜几何测量、compliance 判定折成一份完整的
``ruler_observation.json`` bundle（契约四族：shot_specs / camera_specs /
measurements / verdicts / prescriptions），并负责把摘要挂进 ``shots.json``
（``build_manifest`` 的 ``ruler_observation`` 顶层键）。

本模块无 bpy：只做形状组装与校验，写盘在 ``layer8_delivery/export_director.py``。
``validate_bundle`` 的发现原样返回，坏数据不静默——调用方负责记录与处置。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..contracts.plan import Plan
from ..contracts.spatial_ruler import validate_bundle


SCHEMA_VERSION = "spatial-ruler-observation/v2"
FPS = 24


def shot_specs_from_plan(plan: Plan) -> List[Dict[str, Any]]:
    """每镜一条 shot_spec（声明侧 + 计划侧；无声明字段时按计划值显式给出）。"""
    specs: List[Dict[str, Any]] = []
    for order, shot in enumerate(plan.shots, start=1):
        specs.append({
            "shot_id": str(shot.shot_id),
            "order": order,
            "declared": {
                "duration_frames": int(
                    getattr(shot, "declared_duration_frames", 0)
                    or shot.duration_frames),
                "characters": list(shot.characters),
                "shot_type": str(shot.shot_type),
            },
            "planned": {
                "duration_frames": int(shot.duration_frames),
                "characters": list(shot.characters),
                "shot_type": str(shot.shot_type),
                "intent": str(getattr(shot, "intent", "") or ""),
            },
        })
    return specs


def camera_specs_from_results(plan: Plan,
                              build_summary: Optional[Dict[str, Any]]
                              ) -> List[Dict[str, Any]]:
    """每镜一条 camera_spec（摆位事实来自 build_summary，来源 plan_intent）。"""
    results = {r.get("shot_id"): r for r in
               ((build_summary or {}).get("results") or [])}
    specs: List[Dict[str, Any]] = []
    for shot in plan.shots:
        result = results.get(shot.shot_id) or {}
        position = result.get("camera_position")
        specs.append({
            "shot_id": str(shot.shot_id),
            "shot_type": str(shot.shot_type),
            "lens": result.get("lens"),
            "frame_height": None,
            "distance": None,
            "side": None,
            "direction": None,
            "position": ([float(x) for x in position]
                         if position is not None else None),
            "target": None,
            "camera_height": None,
            "aim_offset_x": None,
            "aim_offset_y": None,
            "sensor_width": 36.0,
            "aspect": 16.0 / 9.0,
            "clamped": False,
            "source": "plan_intent",
            "note": "相机摆位来自构建结果（build_summary.result），"
                    "实测几何以 measurements 的 blender_geometry 为准",
        })
    return specs


def map_compliance_verdicts(compliance: Optional[Dict[str, Any]]
                            ) -> List[Dict[str, Any]]:
    """把 compliance findings 折成契约 verdict（数值对键显式出现、可空）。"""
    verdicts: List[Dict[str, Any]] = []
    for index, finding in enumerate(
            ((compliance or {}).get("findings") or [])):
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "warning")
        verdicts.append({
            "verdict_id": f"v_{finding.get('rule')}_{index}",
            "shot_id": str(finding.get("target") or ""),
            "transition_id": None,
            "rule_code": str(finding.get("rule") or ""),
            "status": "repair" if severity == "error" else "warning",
            "severity": severity,
            "expected": None,
            "actual": None,
            "threshold": None,
            "unit": "none",
            "evidence": [],
            "provenance": "plan_intent",
            "message": str(finding.get("message") or ""),
            "suggestion": str(finding.get("suggestion") or ""),
        })
    return verdicts


def assemble_bundle(
    *,
    observation_id: str,
    run_context: Dict[str, Any],
    plan: Plan,
    measurements: Sequence[Dict[str, Any]],
    verdicts: Sequence[Dict[str, Any]],
    prescriptions: Sequence[Dict[str, Any]],
    build_summary: Optional[Dict[str, Any]] = None,
    plugin_adapter: Optional[Dict[str, Any]] = None,
    observation_request: Optional[Dict[str, Any]] = None,
    registry: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """组装并校验一份观测 bundle；返回 ``(bundle, findings)``。"""
    bundle: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": observation_id,
        "run_context": dict(run_context),
        "plugin_adapter": plugin_adapter or {
            "consumer": "BlockDirector.audit",
            "phase": ["pre_build", "post_build"],
            "blocking_policy": {"error": "blocks", "warning": "persists"},
            "integration_status": "partial_plan_level_only",
        },
        "observation_request": observation_request or {
            "targets": [{"shot_id": str(shot.shot_id)}
                        for shot in plan.shots],
            "coordinate_system": "normalized_screen_0_1",
            "fps": FPS,
        },
        "registry": registry or {"rules": {}, "guard": {}, "composition": {}},
        "shot_specs": shot_specs_from_plan(plan),
        "camera_specs": camera_specs_from_results(plan, build_summary),
        "measurements": [dict(item) for item in measurements],
        "verdicts": [dict(item) for item in verdicts],
        "prescriptions": [dict(item) for item in prescriptions],
    }
    return bundle, validate_bundle(bundle)
