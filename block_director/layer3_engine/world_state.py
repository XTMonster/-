"""运行时世界状态 JSON 刷新与一致性（R11 / T4，bpy 侧）。

``runtime_world_state.json`` 是 agent 与审查共用的**世界坐标单一真源**：

* 刷新时机：场景构建完成（``note_build`` 之后）、每次 agent 工具改动成功、
  ``revert_shot`` 之后；
* 一致性：查询工具先 :func:`ensure_consistent`——live 与 JSON 差 >1e-4 时
  刷新并记 ``E_WORLD_STATE_DIVERGED``，绝不把矛盾读数喂给模型。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import bpy

from ..contracts.world_state import (
    E_WORLD_STATE_DIVERGED,
    WORLD_STATE_SCHEMA_VERSION,
    divergence_report,
    merge_observed_world_into_reference as _contracts_merge,
    normalize_world_state,
)
from ..utils.logger import get_logger
from ..utils.geometry import rotation_z_to_facing
from .character_system import get_facing

log = get_logger("world-state")

PROP_OBJECT_PREFIX = "BD_Prop_"
ANCHOR_OBJECT_PREFIX = "BD_Anchor_"
CAMERA_TARGET_PREFIX = "BD_CamTarget_"
BLOCKOUT_OBJECT_PREFIX = "BD_Blockout_"


def _vec3(value) -> List[float]:
    return [round(float(value[0]), 6), round(float(value[1]), 6),
            round(float(value[2]), 6)]


def collect_world_state(context) -> Dict[str, Any]:
    """从当前 Blender 场景采集角色/相机/prop/锚点世界坐标（m / mm）。"""
    characters: Dict[str, Any] = {}
    for cid, character in (getattr(context, "characters", None) or {}).items():
        root = getattr(character, "root", None)
        if root is None:
            continue
        characters[str(cid)] = {
            "position": _vec3(root.matrix_world.translation),
            "facing": _vec3(get_facing(character)),
        }
    cameras: Dict[str, Any] = {}
    for shot_id, camera in (getattr(context, "cameras", None) or {}).items():
        target_obj = bpy.data.objects.get(f"{CAMERA_TARGET_PREFIX}{shot_id}")
        target = (target_obj.matrix_world.translation
                  if target_obj is not None
                  else camera.matrix_world.translation)
        lens = float(getattr(getattr(camera, "data", None), "lens", 50.0)
                     or 50.0)
        cameras[str(shot_id)] = {
            "position": _vec3(camera.matrix_world.translation),
            "target": _vec3(target),
            "lens_mm": round(lens, 3),
        }
    props: Dict[str, Any] = {}
    for obj in bpy.data.objects:
        name = str(obj.name or "")
        if name.startswith(PROP_OBJECT_PREFIX):
            props[name[len(PROP_OBJECT_PREFIX):]] = {
                "position": _vec3(obj.matrix_world.translation),
                "rotation_z": round(float(obj.rotation_euler[2]), 6),
            }
    anchors: Dict[str, Any] = {}
    for obj in bpy.data.objects:
        name = str(obj.name or "")
        if name.startswith(ANCHOR_OBJECT_PREFIX):
            anchors[name[len(ANCHOR_OBJECT_PREFIX):]] = {
                "position": _vec3(obj.matrix_world.translation),
            }
    return normalize_world_state({
        "schema_version": WORLD_STATE_SCHEMA_VERSION,
        "characters": characters,
        "cameras": cameras,
        "props": props,
        "anchors": anchors,
    })


def _collect_blockout_tables(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Collect world tables at the scene's current evaluated frame."""
    bpy.context.view_layer.update()
    characters: Dict[str, Any] = {}
    props: Dict[str, Any] = {}
    anchors: Dict[str, Any] = {}
    for primitive in manifest.get("primitives") or []:
        obj = bpy.data.objects.get(
            f"{BLOCKOUT_OBJECT_PREFIX}{primitive.get('id')}")
        if obj is None:
            continue
        source = dict(primitive.get("source") or {})
        source_kind = str(source.get("type") or "")
        source_id = str(source.get("id") or primitive.get("id") or "")
        if not source_id:
            continue
        position = _vec3(obj.matrix_world.translation)
        if source_kind == "character":
            characters[source_id] = {
                "position": position,
                "facing": _vec3(
                    rotation_z_to_facing(obj.matrix_world.to_euler().z)),
            }
        elif source_kind == "prop":
            props[source_id] = {
                "position": position,
                "rotation_z": round(float(obj.matrix_world.to_euler().z), 6),
            }
        else:
            anchors[source_id] = {"position": position}
    cameras: Dict[str, Any] = {}
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        camera_id = str(camera.get("camera_id") or f"cam_{shot_id}")
        obj = bpy.data.objects.get(f"{BLOCKOUT_OBJECT_PREFIX}{camera_id}")
        if obj is None:
            continue
        target_obj = bpy.data.objects.get(
            f"{BLOCKOUT_OBJECT_PREFIX}CamTarget_{shot_id}")
        target = (target_obj.matrix_world.translation
                  if target_obj is not None
                  else obj.matrix_world.translation)
        cameras[shot_id] = {
            "position": _vec3(obj.matrix_world.translation),
            "target": _vec3(target),
            "lens_mm": round(float(
                getattr(getattr(obj, "data", None), "lens", 50.0) or 50.0), 3),
        }
    return {
        "characters": characters,
        "cameras": cameras,
        "props": props,
        "anchors": anchors,
    }


def collect_blockout_world_state(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Collect current plus per-shot evaluated Blockout world state.

    A shared character can hold a different local position in each shot.
    Reading only the current object transform loses that fact and lets a
    revision in one shot disappear from observation and rollback evidence.
    Evaluate every shot at its start frame, retain the physical tables for that
    frame, then restore the caller's current frame.
    """
    scene = bpy.context.scene
    previous_frame = int(scene.frame_current)
    shot_states: Dict[str, Any] = {}
    try:
        for row in manifest.get("shot_table") or []:
            shot_id = str(row.get("shot_id") or "")
            if not shot_id:
                continue
            frame = int(row.get("start_frame") or 1)
            scene.frame_set(frame)
            shot_states[shot_id] = {
                "frame": frame,
                **_collect_blockout_tables(manifest),
            }
    finally:
        scene.frame_set(previous_frame)
        bpy.context.view_layer.update()
    tables = _collect_blockout_tables(manifest)
    return normalize_world_state({
        "schema_version": WORLD_STATE_SCHEMA_VERSION,
        **tables,
        "shot_states": shot_states,
    })


def world_state_path(context) -> Optional[Path]:
    raw = getattr(context, "world_state_path", None)
    return Path(raw) if raw else None


def write_world_state(context, payload: Optional[Dict[str, Any]] = None
                      ) -> Optional[Path]:
    """把 payload（默认现场采集）写进 ``runtime_world_state.json``。"""
    path = world_state_path(context)
    if path is None:
        return None
    payload = payload if payload is not None else collect_world_state(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def refresh_world_state(context) -> Dict[str, Any]:
    """场景构建后 / agent 工具改动后 / revert 后调用：实时重写 JSON。"""
    if context is None:
        return {}
    payload = collect_world_state(context)
    write_world_state(context, payload)
    return payload


def merge_observed_world_into_reference(
    reference: Dict[str, Any],
    world_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """bpy 侧转发：纯层实现见 contracts.world_state（单一真源）。"""
    return _contracts_merge(reference, world_state)


def ensure_consistent(context) -> List[Dict[str, Any]]:
    """查询工具调用前：live 与 JSON 差 >1e-4 时刷新并返回差值清单。

    返回空表 = 一致（或未登记路径）。非空 = 已刷新（JSON 现在是权威值），
    调用方应把 ``E_WORLD_STATE_DIVERGED`` 记进 notes，绝不用旧 JSON 读数。
    """
    if context is None:
        return []
    path = world_state_path(context)
    if path is None:
        return []
    live = collect_world_state(context)
    if not path.exists():
        write_world_state(context, live)
        return []
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("runtime_world_state.json 无法解析，已按现场重写")
        write_world_state(context, live)
        return []
    findings = divergence_report(stored, live)
    if findings:
        log.warning("世界坐标与 JSON 不一致：%d 处，已刷新",
                    len(findings))
        write_world_state(context, live)
    return findings


def note_divergence(context, findings: List[Dict[str, Any]]) -> None:
    """把不一致审计痕迹写进 context.notes（随场景状态进审计）。"""
    if not findings or context is None:
        return
    summary = "；".join(str(item["path"]) for item in findings[:5])
    context.notes.append(
        f"{E_WORLD_STATE_DIVERGED}：世界坐标与 runtime_world_state.json "
        f"不一致（{summary}），已刷新重读")
