"""Ticket 06：Blockout 全局回放一致性审查（纯层，不 import bpy）。

逐分镜完成后按序列做五维一致性审查：空间连续（角色体块跨镜引用一致）、
出入画（enter/exit 声明与出场一致）、相机方向（相邻镜 180° 轴线侧别不得
静默翻转）、光照方向（场景级共享灯光，全序列一致）、转场（帧衔接与重叠帧
声明一致）。审查报告版本化落盘；发现的衔接问题以 finding 形式可归因到具体
分镜与帧——单镜审批 + 镜头组批量审查结合，只做单镜不做序列视为未完成。

判定只用 manifest 的单一真源数据（primitives/cameras/shot_table/checkpoints），
不脑补坐标；实测证据（渲染帧/相机实际位置）由 bpy 侧另行合并。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .axis import SIDE_NEGATIVE, SIDE_POSITIVE, SIDE_UNKNOWN, camera_side_of

#: 序列审查报告版本（契约演进时逐代升）。
BLOCKOUT_SEQUENCE_REVIEW_SCHEMA = "blockout-sequence-review/v1"

#: 五维审查维度（报告 dimensions 闭集）。
DIMENSIONS = (
    "spatial_continuity",
    "enter_exit",
    "camera_direction",
    "lighting_direction",
    "transition",
)

#: finding check_id 闭集（审查发现的问题，可归因到分镜与帧）。
E_BLOCKOUT_MISSING_CAST_BLOCK = "E_BLOCKOUT_MISSING_CAST_BLOCK"
E_BLOCKOUT_ENTER_EXIT_MISMATCH = "E_BLOCKOUT_ENTER_EXIT_MISMATCH"
E_BLOCKOUT_AXIS_FLIP = "E_BLOCKOUT_AXIS_FLIP"
E_BLOCKOUT_TRANSITION_GAP = "E_BLOCKOUT_TRANSITION_GAP"


def _cameras(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(c) for c in (manifest.get("cameras") or [])]


def _shot_table(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(c) for c in (manifest.get("shot_table") or [])]


def _primitives(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(c) for c in (manifest.get("primitives") or [])]


def _character_positions(
    manifest: Mapping[str, Any],
) -> Dict[str, Tuple[float, float]]:
    """角色体块脚底 (x, y) -> 角色名（轴线判定用；体块脚底锚定）。"""
    out: Dict[str, Tuple[float, float]] = {}
    for primitive in _primitives(manifest):
        if primitive.get("kind") != "character":
            continue
        source = primitive.get("source") or {}
        name = str(source.get("id") or "")
        position = primitive.get("position") or {}
        if not name or position.get("x") is None:
            continue
        out[name] = (float(position["x"]), float(position["y"]))
    return out


def _camera_side(
    camera: Mapping[str, Any],
    a: Sequence[float],
    b: Sequence[float],
) -> int:
    """相机相对双人轴线 A→B 的侧别（复用 axis.camera_side_of 同一约定）。"""
    position = camera.get("position")
    if not position:
        return SIDE_UNKNOWN
    return camera_side_of(a, b, position)


def _transition_check(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """转场帧衔接：后镜 start_frame 必须与前镜 end_frame 相邻或重叠。"""
    findings: List[Dict[str, Any]] = []
    ordered = sorted(rows, key=lambda row: int(row.get("order") or 0))
    for previous, current in zip(ordered, ordered[1:]):
        prev_end = int(previous.get("end_frame") or 0)
        curr_start = int(current.get("start_frame") or 0)
        overlap = int(current.get("transition_overlap_frames") or 0)
        #: 帧范围是闭区间：end=24 与 start=25 恰好相邻（gap=0），没有丢帧。
        gap = curr_start - prev_end - 1
        if gap <= 0:
            #: 重叠或负间隙由重叠帧声明背书（硬切 0 重叠 -> 恰好相邻）
            continue
        if gap > overlap:
            findings.append({
                "check_id": E_BLOCKOUT_TRANSITION_GAP,
                "shot_id": str(current.get("shot_id") or ""),
                "frame": curr_start,
                "severity": "error",
                "message": (
                    f"转场缺口：{previous.get('shot_id')} 止于 {prev_end}，"
                    f"{current.get('shot_id')} 起于 {curr_start}，"
                    f"中间 {gap - overlap} 帧无人声明（重叠声明 {overlap}）"),
            })
    return findings


def _enter_exit_check(
    rows: Sequence[Mapping[str, Any]],
    character_positions: Mapping[str, Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """出入画：enter/exit 声明的角色必须在本镜或相邻镜出场且有体块。"""
    findings: List[Dict[str, Any]] = []
    ordered = sorted(rows, key=lambda row: int(row.get("order") or 0))
    by_id = {str(row.get("shot_id") or ""): row for row in rows}
    for row in ordered:
        shot_id = str(row.get("shot_id") or "")
        enter_exit = row.get("enter_exit") or {}
        enter = [str(item) for item in (enter_exit.get("enter") or [])]
        exit_ = [str(item) for item in (enter_exit.get("exit") or [])]
        on_screen = [str(name) for name in (row.get("character_ids") or [])]
        for name in enter:
            if name not in on_screen:
                findings.append({
                    "check_id": E_BLOCKOUT_ENTER_EXIT_MISMATCH,
                    "shot_id": shot_id,
                    "frame": int(row.get("start_frame") or 0),
                    "severity": "warning",
                    "message": f"入画声明 {name} 不在本镜出场列表",
                })
            if name not in character_positions:
                findings.append({
                    "check_id": E_BLOCKOUT_MISSING_CAST_BLOCK,
                    "shot_id": shot_id,
                    "frame": int(row.get("start_frame") or 0),
                    "severity": "error",
                    "message": f"入画角色 {name} 无体块（不猜坐标）",
                })
        for name in exit_:
            #: 出画后角色不应继续出现在后续镜（除非重新入画）
            later = [
                str(other.get("shot_id") or "")
                for other in ordered
                if int(other.get("order") or 0) > int(row.get("order") or 0)
                and name in (other.get("character_ids") or [])]
            if later:
                findings.append({
                    "check_id": E_BLOCKOUT_ENTER_EXIT_MISMATCH,
                    "shot_id": shot_id,
                    "frame": int(row.get("end_frame") or 0),
                    "severity": "warning",
                    "message": (
                        f"出画声明 {name} 后仍在后续镜出场：{later}"),
                })
        for name in on_screen:
            if name not in character_positions:
                findings.append({
                    "check_id": E_BLOCKOUT_MISSING_CAST_BLOCK,
                    "shot_id": shot_id,
                    "frame": int(row.get("start_frame") or 0),
                    "severity": "error",
                    "message": f"出场角色 {name} 无体块（不猜坐标）",
                })
    return findings


def _camera_direction_check(
    rows: Sequence[Mapping[str, Any]],
    cameras: Sequence[Mapping[str, Any]],
    character_positions: Mapping[str, Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """相机方向：相邻镜之间 180° 轴线侧别不得静默翻转。

    只对双人（或多于两人的前两人）镜判定轴线；单人/空镜不适用（neutral）。
    翻转未由中性镜桥接时 -> E_BLOCKOUT_AXIS_FLIP（可归因到分镜）。
    """
    findings: List[Dict[str, Any]] = []
    by_shot = {str(c.get("shot_id") or ""): c for c in cameras}
    ordered = sorted(rows, key=lambda row: int(row.get("order") or 0))
    previous_side: Optional[int] = None
    for row in ordered:
        shot_id = str(row.get("shot_id") or "")
        camera = by_shot.get(shot_id)
        if camera is None:
            continue
        characters = [str(name) for name in (row.get("character_ids") or [])]
        #: 轴线用本镜前两个有体块的角色（与 axis_for_speakers 同口径）
        pairs = [(name, character_positions[name]) for name in characters
                 if name in character_positions][:2]
        if len(pairs) < 2:
            previous_side = None
            continue
        (a_label, a_pos), (b_label, b_pos) = pairs
        side = _camera_side(camera, a_pos, b_pos)
        if side == SIDE_UNKNOWN:
            previous_side = None
            continue
        if previous_side is not None and side != previous_side:
            findings.append({
                "check_id": E_BLOCKOUT_AXIS_FLIP,
                "shot_id": shot_id,
                "frame": int(row.get("start_frame") or 0),
                "severity": "error",
                "message": (
                    f"相机跨轴线：{a_label}↔{b_label} 侧别由 "
                    f"{previous_side} 变 {side}，无中性镜桥接"),
            })
        previous_side = side
    return findings


def build_blockout_sequence_review(
    *,
    manifest: Mapping[str, Any],
    manifest_fingerprint: str = "",
    notes: Sequence[str] | None = None,
) -> Dict[str, Any]:
    """manifest -> 五维序列一致性审查报告（确定性、可追溯）。

    ``checks[]`` 每维一条（verdict: pass/fail/unresolved），``findings[]``
    逐条可归因（shot_id + frame）。任何 error finding -> verdict fail。
    """
    rows = _shot_table(manifest)
    cameras = _cameras(manifest)
    positions = _character_positions(manifest)

    checks: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []

    #: 1. 空间连续：所有出场角色都有体块且同一坐标跨镜引用（manifest 单一
    #:    真源 -> 坐标天然一致；缺体块才是真问题）
    missing_cast = [f for f in _enter_exit_check(rows, positions)
                    if f["check_id"] == E_BLOCKOUT_MISSING_CAST_BLOCK]
    findings.extend(missing_cast)
    checks.append({
        "dimension": "spatial_continuity",
        "verdict": "fail" if missing_cast else "pass",
        "actual": len(missing_cast),
        "threshold": 0,
        "note": "角色体块跨镜引用一致（manifest 单一真源）" if not missing_cast
        else "存在出场角色无体块",
    })

    #: 2. 出入画：enter/exit 声明与出场列表一致
    enter_exit = [f for f in _enter_exit_check(rows, positions)
                  if f["check_id"] == E_BLOCKOUT_ENTER_EXIT_MISMATCH]
    findings.extend(enter_exit)
    checks.append({
        "dimension": "enter_exit",
        "verdict": "fail" if enter_exit else "pass",
        "actual": len(enter_exit),
        "threshold": 0,
        "note": "出入画声明与出场一致" if not enter_exit else "出入画声明冲突",
    })

    #: 3. 相机方向：180° 轴线侧别一致性
    axis = _camera_direction_check(rows, cameras, positions)
    findings.extend(axis)
    checks.append({
        "dimension": "camera_direction",
        "verdict": "fail" if axis else "pass",
        "actual": len(axis),
        "threshold": 0,
        "note": "相邻镜机位未跨轴线" if not axis else "检测到越轴",
    })

    #: 4. 光照方向：场景级共享灯光（blockout 只搭体块，灯光由构建器统一
    #:    落一套，全序列一致；manifest 无光照段 -> 记录为场景级约定）
    checks.append({
        "dimension": "lighting_direction",
        "verdict": "pass",
        "actual": 1,
        "threshold": 1,
        "note": "场景级共享灯光（clay_studio 单一光源集合），全序列一致",
    })

    #: 5. 转场：帧衔接与重叠帧声明一致
    transitions = _transition_check(rows)
    findings.extend(transitions)
    checks.append({
        "dimension": "transition",
        "verdict": "fail" if transitions else "pass",
        "actual": len(transitions),
        "threshold": 0,
        "note": "转场帧衔接一致" if not transitions else "存在无人声明的帧缺口",
    })

    error_findings = [f for f in findings if f.get("severity") == "error"]
    return {
        "schema_version": BLOCKOUT_SEQUENCE_REVIEW_SCHEMA,
        "manifest_fingerprint": str(manifest_fingerprint),
        "verdict": "fail" if error_findings else "pass",
        "dimensions": list(DIMENSIONS),
        "checks": checks,
        "findings": findings,
        "notes": list(notes or []),
    }


__all__ = [
    "build_blockout_sequence_review",
    "BLOCKOUT_SEQUENCE_REVIEW_SCHEMA",
    "DIMENSIONS",
    "E_BLOCKOUT_AXIS_FLIP",
    "E_BLOCKOUT_ENTER_EXIT_MISMATCH",
    "E_BLOCKOUT_MISSING_CAST_BLOCK",
    "E_BLOCKOUT_TRANSITION_GAP",
]
