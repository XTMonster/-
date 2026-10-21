"""运行时世界坐标 JSON 契约（R11 / T4，纯层，禁止 import bpy）。

``runtime_world_state.json`` 是 agent 与审查共用的**世界坐标单一真源**：
场景构建后与每次 agent 工具改动后实时重写；查询工具读数必须与它一致
（1e-4 容差），不一致报 ``E_WORLD_STATE_DIVERGED`` 并刷新重读。

Payload 形状（与 spatial_design / spatial_observation 同口径，单位 m / mm）：

.. code-block:: json

    {
      "schema_version": "runtime-world/v1",
      "characters": {"char_001": {"position": [x, y, z],
                                  "facing": [x, y, z]}},
      "cameras": {"shot_001": {"position": [x, y, z],
                               "target": [x, y, z],
                               "lens_mm": 50.0}},
      "props": {"silver_coin": {"position": [x, y, z],
                                "rotation_z": 0.0}},
      "anchors": {"生蚝摊": {"position": [x, y, z]}}
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .audit import canonical_fingerprint

WORLD_STATE_SCHEMA_VERSION = "runtime-world/v1"

#: runtime_world_state.json 的固定文件名（单一真源，bpy 侧/驱动器/探针共用）。
RUNTIME_WORLD_STATE_FILENAME = "runtime_world_state.json"

#: 一致性校验失败的错误码（单一真源，工具/探针引用它，不各抄一份）。
E_WORLD_STATE_DIVERGED = "E_WORLD_STATE_DIVERGED"

#: 世界坐标容差（米 / mm；与 spec R11 的 1e-4 一字不动）。
WORLD_STATE_TOLERANCE = 1e-4

#: Physical state a rebuilt Blockout scene must reproduce.  Render staging is
#: an observation-only overlay produced by preview rendering; it is neither
#: stored in the rebuilt runtime world nor usable as proof of physical state.
PHYSICAL_WORLD_STATE_KEYS = (
    "schema_version",
    "characters",
    "cameras",
    "props",
    "anchors",
    "shot_states",
)


def normalize_world_state(value: Any) -> Any:
    """Return the semantic JSON form used for exact world-state identity.

    Blender can emit ``-0.0`` after a rotation even when the physical value is
    zero.  JSON preserves that sign and therefore changes a content hash while
    the world state is unchanged.  Canonicalise only this equivalent numeric
    representation; all non-zero values remain exact (no tolerance is applied).
    """
    if isinstance(value, Mapping):
        return {
            key: normalize_world_state(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [normalize_world_state(item) for item in value]
    if isinstance(value, float) and value == 0.0:
        return 0.0
    return value


def world_state_fingerprint(world_state: Any) -> str:
    """Hash a world state after signed-zero normalisation."""
    return canonical_fingerprint(normalize_world_state(world_state))


def physical_world_state_projection(
    world_state: Mapping[str, Any],
) -> Dict[str, Any]:
    """Project only state that a rebuilt Blender scene can reproduce."""
    return {
        key: normalize_world_state(world_state[key])
        for key in PHYSICAL_WORLD_STATE_KEYS
        if key in world_state
    }


def physical_world_state_fingerprint(world_state: Mapping[str, Any]) -> str:
    """Fingerprint the restorable physical projection of a world state."""
    return canonical_fingerprint(physical_world_state_projection(world_state))


def world_state_target_path(audit_dir) -> Optional[Path]:
    """R11：运行时世界坐标 JSON 的落盘路径（审计目录的**父目录**）。

    ``audit_dir`` 是 runs/ 审计目录（``audit_log.jsonl``/``llm_trace.jsonl``
    所在处）；JSON 与它同级、落在运行根目录，方便人与审查取用。
    ``None`` 输入（纯层/无审计目录）返回 ``None``，调用方如实跳过。
    """
    if not audit_dir:
        return None
    return Path(audit_dir).parent / RUNTIME_WORLD_STATE_FILENAME


def floats_close(a: Sequence[float], b: Sequence[float],
                 tol: float = WORLD_STATE_TOLERANCE) -> bool:
    """两个坐标序列是否在容差内一致（长度不同必拒）。"""
    return len(a) == len(b) and all(
        abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def _max_delta(a: Sequence[float], b: Sequence[float]) -> float:
    common = min(len(a), len(b))
    if not common:
        return float("inf")
    return max(abs(float(a[i]) - float(b[i])) for i in range(common))


def divergence_report(payload: Dict[str, Any],
                      live: Dict[str, Any],
                      tol: float = WORLD_STATE_TOLERANCE) -> List[Dict[str, Any]]:
    """按 characters/cameras/props/anchors 四表逐 id 逐键比对，返回差值清单。

    每条 ``{"path", "expected", "actual", "max_delta"}``；一致时返回空表。
    ``max_delta`` 以每条路径内全部数值的最大绝对差为准。
    """
    findings: List[Dict[str, Any]] = []
    for table in ("characters", "cameras", "props", "anchors"):
        expected_table = payload.get(table) or {}
        actual_table = live.get(table) or {}
        for entity_id in sorted(set(expected_table) | set(actual_table)):
            expected = dict(expected_table.get(entity_id) or {})
            actual = dict(actual_table.get(entity_id) or {})
            for key in sorted(set(expected) | set(actual)):
                expected_value = expected.get(key)
                actual_value = actual.get(key)
                if isinstance(expected_value, (list, tuple)) and isinstance(
                        actual_value, (list, tuple)):
                    if floats_close(list(expected_value), list(actual_value),
                                    tol):
                        continue
                    findings.append({
                        "path": f"{table}.{entity_id}.{key}",
                        "expected": [float(v) for v in expected_value],
                        "actual": [float(v) for v in actual_value],
                        "max_delta": round(_max_delta(expected_value,
                                                      actual_value), 6),
                    })
                elif isinstance(expected_value, (int, float)) and isinstance(
                        actual_value, (int, float)):
                    delta = abs(float(expected_value) - float(actual_value))
                    if delta > tol:
                        findings.append({
                            "path": f"{table}.{entity_id}.{key}",
                            "expected": float(expected_value),
                            "actual": float(actual_value),
                            "max_delta": round(delta, 6),
                        })
                elif expected_value != actual_value:
                    findings.append({
                        "path": f"{table}.{entity_id}.{key}",
                        "expected": expected_value,
                        "actual": actual_value,
                        "max_delta": float("inf"),
                    })
    return findings


def merge_observed_world_into_reference(
    reference: Dict[str, Any],
    world_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """把实测世界坐标合并进粗排参考 JSON（用户 2026-10-21 裁决：
    JSON 世界坐标要实时更新）。

    这是"设计 JSON 与实测世界坐标脱节"的修复：agent 在细排阶段用
    ``place_character``/``move_character``/``setup_camera``/``reframe``
    修改 Blender 场景后，``runtime_world_state.json`` 已有真实坐标，但粗排
    reference 还停在计划默认站位（2026-10-21 真跑：伊恩实测 -1.6、参考
    JSON 还是 -0.3，构图 20 分）。本函数按实测值合并进 reference：

    * 角色 position/facing 有实测值即覆盖（provenance 标 observed）；
    * 相机 position/target/lens 有实测值即覆盖（provenance 标 observed）；
    * 道具/锚点 position 有实测值即覆盖（provenance 标 observed）；
    * 无实测值的实体保持原样（不猜、不删）。

    ``reference`` 原地深拷贝返回，不污染输入。纯函数，可单测（不依赖 bpy）。
    """
    import copy

    observed = dict(world_state or {})
    merged = copy.deepcopy(reference)
    observed_chars = {str(k): v for k, v in
                      (observed.get("characters") or {}).items()}
    if observed_chars:
        for char in merged.get("characters") or []:
            name = str(char.get("name") or "")
            entry = observed_chars.get(name)
            if not isinstance(entry, Mapping):
                continue
            if isinstance(entry.get("position"), (list, tuple)) \
                    and len(entry["position"]) >= 3:
                char["position"] = {
                    "x": round(float(entry["position"][0]), 4),
                    "y": round(float(entry["position"][1]), 4),
                    "z": round(float(entry["position"][2]), 4),
                }
                char["provenance"] = "observed_world_state"
            if isinstance(entry.get("facing"), (list, tuple)) \
                    and len(entry["facing"]) >= 3:
                char["facing"] = [
                    round(float(entry["facing"][0]), 4),
                    round(float(entry["facing"][1]), 4),
                    round(float(entry["facing"][2]), 4),
                ]

    observed_cams = {str(k): v for k, v in
                     (observed.get("cameras") or {}).items()}
    if observed_cams:
        for intent in merged.get("camera_intents") or []:
            shot_id = str(intent.get("shot_id") or "")
            entry = observed_cams.get(shot_id)
            if not isinstance(entry, Mapping):
                continue
            if isinstance(entry.get("position"), (list, tuple)) \
                    and len(entry["position"]) >= 3:
                intent["position"] = [
                    round(float(entry["position"][0]), 4),
                    round(float(entry["position"][1]), 4),
                    round(float(entry["position"][2]), 4),
                ]
                intent["provenance"] = "observed_world_state"
            if isinstance(entry.get("target"), (list, tuple)) \
                    and len(entry["target"]) >= 3:
                intent["target"] = [
                    round(float(entry["target"][0]), 4),
                    round(float(entry["target"][1]), 4),
                    round(float(entry["target"][2]), 4),
                ]
            lens = entry.get("lens_mm")
            if isinstance(lens, (int, float)):
                intent["lens"] = round(float(lens), 4)

    observed_props = {str(k): v for k, v in
                      (observed.get("props") or {}).items()}
    if observed_props:
        for prop in merged.get("props") or []:
            pid = str(prop.get("id") or "")
            entry = observed_props.get(pid)
            if isinstance(entry, Mapping) \
                    and isinstance(entry.get("position"), (list, tuple)) \
                    and len(entry["position"]) >= 3:
                prop["position"] = [
                    round(float(entry["position"][0]), 4),
                    round(float(entry["position"][1]), 4),
                    round(float(entry["position"][2]), 4),
                ]
                prop["provenance"] = "observed_world_state"

    observed_anchors = {str(k): v for k, v in
                        (observed.get("anchors") or {}).items()}
    if observed_anchors:
        for anchor in merged.get("anchors") or []:
            label = str(anchor.get("label") or "")
            entry = observed_anchors.get(label)
            if isinstance(entry, Mapping) \
                    and isinstance(entry.get("position"), (list, tuple)) \
                    and len(entry["position"]) >= 3:
                anchor["position"] = [
                    round(float(entry["position"][0]), 4),
                    round(float(entry["position"][1]), 4),
                    round(float(entry["position"][2]), 4),
                ]
                anchor["resolved"] = True
                anchor["provenance"] = "observed_world_state"

    if observed_chars or observed_cams or observed_props or observed_anchors:
        merged.setdefault("notes", []).append(
            "已合并 runtime_world_state 实测坐标（observed_world_state），"
            "覆盖计划默认站位/相机，保证设计 JSON 与实测世界坐标同源")
    return merged
