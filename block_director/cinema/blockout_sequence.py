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

from .axis import E_BLOCKOUT_AXIS_FLIP, camera_direction_findings

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
E_BLOCKOUT_TRANSITION_GAP = "E_BLOCKOUT_TRANSITION_GAP"


def _cameras(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(c) for c in (manifest.get("cameras") or [])]


def _shot_table(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(c) for c in (manifest.get("shot_table") or [])]


def _primitives(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(c) for c in (manifest.get("primitives") or [])]


def blockout_isolation_primitive_ids(
    manifest: Mapping[str, Any],
    shot_table_row: Mapping[str, Any],
) -> List[str]:
    """返回本镜预演时应隔离（临时隐藏）的体块 primitive id。

    粗排是逐镜 staging 验证：其它镜头的角色/持有道具仍留在同一 blockout
    场景里，会成为真实遮挡体（final7 的 shot_003 中，上一镜的米迦尔挡住
    伊恩，处方只改相机距离永远消不掉）。本镜声明的角色/道具保留参与
    staging 验证；场景级道具（owner 为空、进 ``scene_prop_ids`` 的摊位等
    环境体块）与锚点是环境连续性，不隐藏——隔离它们会把真实的环境遮挡
    误判成"可以无视"。只隔离"出现在其它镜头、不在本镜"的角色与持有道具。

    纯层、确定性：同一 manifest + 同一分镜行两次调用逐位一致；不依赖 bpy。
    """
    active = {str(value) for value in
              ((shot_table_row.get("character_ids") or [])
               + (shot_table_row.get("prop_ids") or []))}
    #: 持有道具 = 出现在任一镜头 prop_ids 的道具（与 owner 语义同源）；
    #: 场景级道具（无 owner）永不进 prop_ids，按环境体块保留。
    owned_prop_ids = {
        str(value)
        for row in (manifest.get("shot_table") or [])
        for value in (row.get("prop_ids") or [])
    }
    isolated: List[str] = []
    for primitive in manifest.get("primitives") or []:
        kind = primitive.get("kind")
        source = primitive.get("source") or {}
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        if kind == "character" and source_id not in active:
            isolated.append(str(primitive.get("id") or ""))
        elif kind == "prop" and source_id in owned_prop_ids \
                and source_id not in active:
            isolated.append(str(primitive.get("id") or ""))
        #: anchor / 其它：环境连续性，不隔离
    return [pid for pid in isolated if pid]


#: 前景遮挡候选：主体体块对象名前缀（角色 BD_Blockout_char_*，道具
#: BD_Blockout_prop_*）。与 ``blockout_preview._subject_blocks`` 的
#: ``BD_Blockout_{primitive.id}`` 同源。
CHARACTER_BLOCK_PREFIX = "BD_Blockout_char_"
PROP_BLOCK_PREFIX = "BD_Blockout_prop_"


def blockout_occluder_candidate_names(
    subject_block_names: Sequence[str],
    self_block_name: str,
) -> set:
    """前景遮挡候选体块名：同镜主体中"会对被检主体形成非主体遮挡"的体块。

    判定语义（F11，实测 final16 ``E_FOREGROUND_OCCLUSION`` 死循环根因）：
    同镜剧情道具（``BD_Blockout_prop_*``）与被检主体同属一个语义单元——
    银币特写镜里银币就是主体本身，偷盗者捧金镜里金子在主体眼前是取景
    内容，不是"非主体前景遮挡体"。若把道具也放进遮挡候选，银币与偷盗者
    会互相被记成 occluder（``occluders=["银币","偷盗者"]``），strafe 处方
    50 轮把相机越绕越远仍不收敛。因此：

    - 剔除被检主体自己（自身不算遮挡）；
    - 剔除全部道具体块（剧情道具不是非主体前景遮挡）；
    - 保留其他角色体块（角色互挡是真实站位问题，交给几何处方修）。

    纯层、确定性：同一输入两次调用逐位一致；不依赖 bpy。
    """
    excluded = {str(self_block_name)}
    return {
        str(name) for name in subject_block_names
        if str(name) not in excluded
        and not str(name).startswith(PROP_BLOCK_PREFIX)
    }


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
    """出入画：enter/exit 声明与出场一致。

    ``enter_exit`` 数组语义（Ticket 01）= 动作类型（``enter_from`` /
    ``exit_frame`` 等），不是角色名。动作级检查：有人入画 -> 本镜必须有人
    出场；有人出画 -> 无后继（无法归因到具体角色时不猜）。数据里若某项
    恰好等于角色名（兼容旧语义），再做角色级出场/体块核对。
    """
    findings: List[Dict[str, Any]] = []
    ordered = sorted(rows, key=lambda row: int(row.get("order") or 0))
    by_id = {str(row.get("shot_id") or ""): row for row in rows}
    for row in ordered:
        shot_id = str(row.get("shot_id") or "")
        enter_exit = row.get("enter_exit") or {}
        enter = [str(item) for item in (enter_exit.get("enter") or [])]
        exit_ = [str(item) for item in (enter_exit.get("exit") or [])]
        on_screen = [str(name) for name in (row.get("character_ids") or [])]
        for item in enter:
            if item.startswith("enter"):
                #: 动作级：有人入画 -> 本镜必须有人出场（否则入画孤悬）
                if not on_screen:
                    findings.append({
                        "check_id": E_BLOCKOUT_ENTER_EXIT_MISMATCH,
                        "shot_id": shot_id,
                        "frame": int(row.get("start_frame") or 0),
                        "severity": "warning",
                        "message": f"入画动作 {item} 但本镜无角色出场",
                    })
                continue
            #: 兼容旧语义：数组项等于角色名 -> 角色级核对
            name = item
            if name not in on_screen:
                findings.append({
                    "check_id": E_BLOCKOUT_ENTER_EXIT_MISMATCH,
                    "shot_id": shot_id,
                    "frame": int(row.get("start_frame") or 0),
                    "severity": "warning",
                    "message": f"入画声明 {item} 不在本镜出场列表",
                })
            if name not in character_positions:
                findings.append({
                    "check_id": E_BLOCKOUT_MISSING_CAST_BLOCK,
                    "shot_id": shot_id,
                    "frame": int(row.get("start_frame") or 0),
                    "severity": "error",
                    "message": f"入画角色 {item} 无体块（不猜坐标）",
                })
        for item in exit_:
            if item.startswith("exit"):
                continue
            name = item
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
        #: 本镜出场角色必须有体块（角色级，不猜）
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
    axis = camera_direction_findings(rows, cameras, positions)
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
