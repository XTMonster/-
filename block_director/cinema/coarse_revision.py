"""粗排处方生成器与应用器（Ticket 01/02，纯层，不 import bpy）。

输入 BlockoutReport（findings + 每镜 composition/occlusion/on_screen 数值）与
粗编排参考 JSON，输出**结构化粗排处方**列表。处方格式：

``{prescription_id, scope, shot_id, entity, component, axis, direction,
magnitude, current_value, target_value, derived_from, applied}``

原则（处方生成）：

* 只消费空间尺/BlockoutReport 的结构化输出，不在粗排修正层凭空猜坐标；
* 每条处方都可追溯到一条 check/finding（``derived_from``）；
* 量级由 actual/threshold 差与实体当前值推导，确定性可复算。

原则（处方应用）：

* 修改只发生在粗编排参考 JSON，不写 Blender 场景；
* 每条应用记录含 before/after 与指纹；两次应用逐位一致；
* 未知实体/未知轴返回显式未应用记录，不吞错。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from block_director.contracts.coarse_reference import (
    coarse_reference_content_fingerprint,
    effective_shot_reference,
    set_shot_character_position,
)
from .blockout_report import E_BLOCKOUT_FRAMING_TARGET_OCCLUDED
from ..contracts.quality import COMPOSITION_PASS_SCORE

E_BLOCKOUT_EMPTY_WALL = "E_BLOCKOUT_EMPTY_WALL"
E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED = "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED"

def resolve_prop_ref(ref: str, prop_ids: Sequence[str]) -> Optional[str]:
    """拍对象道具引用 -> 场景道具 id 的确定性解析（别名/包含匹配）。

    剧本/计划里拍对象引用（``framing_target.ref``）与 LLM brief 的道具 id
    可能不是逐字一致：final12 真跑里 ref=``银币``，而 brief props id=
    ``银币-金子``（剧本"银币化为金子"，一个道具两个状态，LLM 命名成了
    复合 id）——精确匹配失败让 shot_002 恒报
    ``E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED``，处方层也没有对应的可执行
    修正，修正循环只能空转 blocked。

    规则（确定性、不猜）：

    * 精确匹配（``prop_id == ref``）优先；
    * 精确不中时，唯一"包含/前后缀"候选（``ref in prop_id`` 或
      ``prop_id in ref``，且候选数 == 1）才解析；
    * 多候选/零候选一律返回 None（不脑补，宁保持 unresolved 也不乱指）。
    * 同一 id 重复出现（如 ``_target_block_name`` 把 ``source.id`` 与去
      ``prop_`` 前缀的原始 id 各入列一次，任一 ``prop_<id>`` 形状的道具都会
      自带重复项）不构成"多候选"——候选按首次出现去重后再判唯一。

    纯函数，两次调用逐位一致；``coarse_revision`` 与
    ``blockout_preview._target_block_name`` 共用，保证处方与投影判据同一
    解析口径（否则处方修了、判据仍 unresolved）。
    """
    ref = str(ref or "").strip()
    if not ref:
        return None
    #: 候选先去重（保序）：同一物理道具被客户端重复入列时，重复项不是
    #: 独立候选；去重后再判"唯一"，避免 ``prop_银币-金子`` 这类常规形状
    #: 的道具永远因自带重复而解析失败（final12 实测 shot_002 报
    #: ``E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED`` 的根因）。
    seen: List[str] = []
    for pid in (prop_ids or []):
        text = str(pid or "")
        if text and text not in seen:
            seen.append(text)
    prop_ids = seen
    exact = [pid for pid in prop_ids if str(pid or "") == ref]
    if len(exact) == 1:
        return str(exact[0])
    candidates = [
        str(pid) for pid in (prop_ids or [])
        if ref in str(pid or "") or str(pid or "") in ref
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _vec3(value: Any) -> Dict[str, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return {"x": float(value[0]), "y": float(value[1]),
                    "z": float(value[2])}
        except (TypeError, ValueError):
            return None
    if isinstance(value, Mapping):
        try:
            return {"x": float(value.get("x", 0.0)),
                    "y": float(value.get("y", 0.0)),
                    "z": float(value.get("z", 0.0))}
        except (TypeError, ValueError):
            return None
    return None


def _to_list(value: Mapping[str, float]) -> List[float]:
    """写回参考 JSON 用列表形状（与 spatial_design/blockout 同源）。"""
    return [round(float(value["x"]), 4), round(float(value["y"]), 4),
            round(float(value["z"]), 4)]


def _distance(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    return ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2
            + (a["z"] - b["z"]) ** 2) ** 0.5


def _subject_centroid(reference: Mapping[str, Any],
                      shot_id: str) -> Dict[str, float] | None:
    """该镜主体（角色/道具）的瞄准质心。

    R2 Ticket 10（真跑 20261019-r2-market-coin-accept-3）：OTS/双人镜声明
    了 ``framing_target.kind=character`` 时，空墙处方必须瞄**声明主体**，
    而不是全体出场角色的中点——否则 shot_007（伊恩+米迦尔、拍米迦尔）的
    处方永远修到两人中间，收敛不了。

    R2 缺陷（20261019-r2-market-coin-final2）：``kind=prop`` 时旧实现只认
    角色，银币特写空墙处方瞄到持币角色整身质心，循环永远修不对拍对象。
    道具坐标来自粗排世界参考 JSON 的 ``props[].position``（银币手持坐标
    [0.22, 0.25, 0.91]），直接用世界坐标作瞄准点。

    无声明时退回全员角色质心（旧行为）。
    """
    reference = effective_shot_reference(reference, shot_id)
    shot = next((s for s in reference.get("shots") or []
                 if str(s.get("shot_id") or "") == shot_id), None)
    all_names: List[str] = []
    names: List[str] = []
    if shot is not None:
        all_names = [str(n) for n in (shot.get("characters") or [])]
    framing_target = shot.get("framing_target") if shot is not None else None
    if isinstance(framing_target, Mapping) \
            and str(framing_target.get("kind") or "") == "prop":
        ref = str(framing_target.get("ref") or "")
        prop_ids = [str(p.get("id") or "") for p in (reference.get("props") or [])]
        resolved = resolve_prop_ref(ref, prop_ids)
        if resolved is not None:
            for prop in reference.get("props") or []:
                if str(prop.get("id") or "") != resolved:
                    continue
                pos = _vec3(prop.get("position"))
                if pos is None:
                    break
                #: 道具 z_anchor=center：体块中心即瞄准点，不再加 0.9 躯干偏移。
                return {"x": pos["x"], "y": pos["y"], "z": pos["z"]}
        return None
    if isinstance(framing_target, Mapping) \
            and str(framing_target.get("kind") or "") == "character":
        ref = str(framing_target.get("ref") or "")
        if ref:
            names = [ref]
    if not names:
        names = list(all_names)
    points: List[Dict[str, float]] = []
    for char in reference.get("characters") or []:
        if str(char.get("name") or "") not in names:
            continue
        pos = _vec3(char.get("position"))
        if pos is None:
            continue
        points.append({"x": pos["x"], "y": pos["y"], "z": pos["z"] + 0.9})
    #: 声明主体不在角色表（脏引用）时退回全员质心，别让空墙处方凭空消失——
    #: 宁可修到组中心，也不让 gate 因"处方缺失"永远阻塞。
    if not points and names != all_names:
        for char in reference.get("characters") or []:
            if str(char.get("name") or "") not in all_names:
                continue
            pos = _vec3(char.get("position"))
            if pos is None:
                continue
            points.append({"x": pos["x"], "y": pos["y"],
                           "z": pos["z"] + 0.9})
    if not points:
        return None
    return {"x": sum(p["x"] for p in points) / len(points),
            "y": sum(p["y"] for p in points) / len(points),
            "z": sum(p["z"] for p in points) / len(points)}


def _camera_of(reference: Mapping[str, Any],
               shot_id: str) -> Dict[str, Any] | None:
    return next((c for c in reference.get("camera_intents") or []
                 if str(c.get("shot_id") or "") == shot_id), None)


def _findings_by_shot(report: Mapping[str, Any]) -> Dict[str, List[Mapping]]:
    result: Dict[str, List[Mapping]] = {}
    for finding in report.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        result.setdefault(str(finding.get("shot_id") or ""), []).append(finding)
    return result


def _checks_by_shot(report: Mapping[str, Any]) -> Dict[str, Dict[str, Mapping]]:
    result: Dict[str, Dict[str, Mapping]] = {}
    for check in report.get("checks") or []:
        if not isinstance(check, Mapping):
            continue
        sid = str(check.get("shot_id") or "")
        result.setdefault(sid, {})[str(check.get("check_id") or "")] = check
    return result


def _applied_component_count(reference: Mapping[str, Any],
                             shot_id: str,
                             component: str) -> int:
    """统计该镜历史已应用的某类相机处方次数（读参考 JSON 的 revisions 留痕）。

    E_FOREGROUND_OCCLUSION 需要渐进策略（先拉远、再绕行、再反向绕行），
    判定依据落在处方产生的 revisions 留痕上——同一真源，两次可复算。
    """
    count = 0
    for revision in reference.get("revisions") or []:
        for record in revision.get("prescriptions") or []:
            if not record.get("applied"):
                continue
            if str(record.get("shot_id") or "") != shot_id:
                continue
            if str(record.get("component") or "") == component:
                count += 1
    return count


def _applied_prescription_count(reference: Mapping[str, Any],
                                shot_id: str,
                                prescription_id: str) -> int:
    """Count applied revisions for one exact prescription family."""
    count = 0
    for revision in reference.get("revisions") or []:
        for record in revision.get("prescriptions") or []:
            if not record.get("applied"):
                continue
            if str(record.get("shot_id") or "") != shot_id:
                continue
            if str(record.get("prescription_id") or "") == prescription_id:
                count += 1
    return count


def _strafe_position(position: Mapping[str, float],
                     target: Mapping[str, float],
                     sign: int) -> Dict[str, float]:
    """相机沿视线水平垂直方向侧移（绕行前景遮挡体，z 高度不变）。

    粗排世界坐标是 ``x/y`` 地面、``z`` 高度。视线水平分量 (dx, dy, 0)，
    其水平垂直方向为 (-dy, dx, 0) 归一化后
    乘侧移量 * sign；量级与该镜视线距离挂钩（与拉远 15% 同级）。
    视线垂直（horiz≈0）时无水平分量可侧移，退回原位避免除零。
    """
    dx = target["x"] - position["x"]
    dy = target["y"] - position["y"]
    horiz = (dx * dx + dy * dy) ** 0.5
    if horiz < 1e-9:
        return {"x": position["x"], "y": position["y"], "z": position["z"]}
    perp_x = -dy / horiz
    perp_y = dx / horiz
    amount = 0.15 * max(_distance(position, target), 1e-6)
    return {"x": position["x"] + perp_x * amount * sign,
            "y": position["y"] + perp_y * amount * sign,
            "z": position["z"]}


def _occluder_geometry(reference: Mapping[str, Any],
                       occluder_id: str,
                       shot_id: str | None = None) -> Dict[str, float] | None:
    """occluder 主体 id -> 世界坐标（空间尺 OcclusionEvent 归因的坐标侧）。

    遮挡体优先按角色解析（可动站位），其次按道具解析（场景内实体）。
    解析不到返回 None——处方不脑补坐标，宁退回交替绕行。
    """
    resolved = (effective_shot_reference(reference, shot_id)
                if shot_id else reference)
    for char in resolved.get("characters") or []:
        if str(char.get("name") or "") == occluder_id:
            pos = _vec3(char.get("position"))
            if pos is not None:
                return pos
            return None
    for prop in resolved.get("props") or []:
        if str(prop.get("id") or "") == occluder_id:
            pos = _vec3(prop.get("position"))
            if pos is not None:
                return pos
            return None
    return None


def _strafe_sign_towards_free_side(position: Mapping[str, float],
                                   target: Mapping[str, float],
                                   occluder_pos: Mapping[str, float]) -> int:
    """绕行方向：远离遮挡体的一侧（几何求解，替代固定 right/left 交替）。

    视线在 ``x/y`` 地面的水平分量 (dx, dy, 0)，右手垂直方向为
    (-dy, dx, 0)/len。遮挡体
    相对相机向量在该垂直方向上的投影符号决定"遮挡体在哪一侧"；相机应向
    相反侧绕行（sign = -sign(proj)）。投影近零（遮挡体恰在视线轴上）时
    退回 +1（首轮固定方向，避免除零/零判）。
    """
    dx = target["x"] - position["x"]
    dy = target["y"] - position["y"]
    horiz = (dx * dx + dy * dy) ** 0.5
    if horiz < 1e-9:
        return 1
    perp_x, perp_y = -dy / horiz, dx / horiz
    ox = occluder_pos["x"] - position["x"]
    oy = occluder_pos["y"] - position["y"]
    projection = ox * perp_x + oy * perp_y
    if abs(projection) < 1e-9:
        return 1
    return -1 if projection > 0 else 1


def _character_separation_prescriptions(
    reference: Mapping[str, Any],
    shot_id: str,
    checks: Mapping[str, Mapping],
) -> List[Dict[str, Any]]:
    """composition fail 时的站位错开处方（用户 2026-10-21 裁决：
    粗排处方要"随机应变调整到合理"，站位/遮挡是纯几何，可计算求解）。

    真跑形状：默认站位把米迦尔/伊恩都放在 (-0.3,0,0) 重叠，构图 20 分。
    相机怎么动都白搭——先把重叠/互挡角色沿视线水平垂直方向错开，再交给
    相机处方。确定性、可追溯：

    * 只处理同镜出场的角色，找出所有**水平距离 < 阈值**（重叠/几乎重合）
      的角色对；
    * 每对中"后声明的"角色沿视线水平垂直方向平移，方向选远离对方的一侧
      （自由侧），量级 = 角色半径和 + 社交间距（可复算）；
    * 平移只在 XY 地面（z 高度不变），避免把角色推入地下或空中。

    返回 ``scope=character`` 的处方列表；无重叠角色对返回空表。
    """
    from .anchor import DEFAULT_PROFILE

    reference = effective_shot_reference(reference, shot_id)
    camera = _camera_of(reference, shot_id)
    if camera is None:
        return []
    position = _vec3(camera.get("position"))
    target = _vec3(camera.get("target"))
    if position is None or target is None:
        return []
    shot = next((s for s in reference.get("shots") or []
                 if str(s.get("shot_id") or "") == shot_id), None)
    names = [str(n) for n in (shot.get("characters") or [])] if shot else []
    if not names:
        return []
    chars = {str(c.get("name") or ""): c
             for c in reference.get("characters") or []}
    entries: List[Dict[str, Any]] = []
    for name in names:
        char = chars.get(name)
        if char is None:
            continue
        pos = _vec3(char.get("position"))
        if pos is not None:
            entries.append({"name": name, "char": char, "pos": pos})
    if len(entries) < 2:
        return []

    radius = float(DEFAULT_PROFILE.chest_z or 0.4) * 0.5
    min_gap = radius * 2.0 + 0.6          # 重叠 + 最小社交间隔
    prescriptions: List[Dict[str, Any]] = []
    seen_pairs = set()
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i], entries[j]
            key = tuple(sorted((a["name"], b["name"])))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            dx = b["pos"]["x"] - a["pos"]["x"]
            dy = b["pos"]["y"] - a["pos"]["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist >= min_gap:
                continue
            # 视线水平垂直方向（相机空间 lateral）
            view_x = target["x"] - position["x"]
            view_y = target["y"] - position["y"]
            horiz = (view_x * view_x + view_y * view_y) ** 0.5
            if horiz < 1e-9:
                continue
            perp_x, perp_y = -view_y / horiz, view_x / horiz
            # 自由侧：让"后声明"角色远离"先声明"角色
            sign = 1
            projection = (a["pos"]["x"] - b["pos"]["x"]) * perp_x \
                + (a["pos"]["y"] - b["pos"]["y"]) * perp_y
            if projection > 0:
                sign = -1
            amount = (min_gap - dist) * 0.5 + 0.25
            new_pos = {
                "x": round(b["pos"]["x"] + perp_x * amount * sign, 4),
                "y": round(b["pos"]["y"] + perp_y * amount * sign, 4),
                "z": b["pos"]["z"],
            }
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_separate_character",
                "scope": "character", "shot_id": shot_id,
                "entity": b["name"],
                "component": "character_position",
                "axis": "position",
                "direction": "right" if sign > 0 else "left",
                "magnitude": round(amount, 4),
                "current_value": b["pos"],
                "target_value": new_pos,
                "derived_from": {
                    "check_id": "composition",
                    "actual": (checks.get("composition") or {}).get("actual"),
                    "threshold": (checks.get("composition") or {}).get(
                        "threshold"),
                    "verdict": "fail",
                    "message": (
                        f"角色 {a['name']} 与 {b['name']} 水平间距 "
                        f"{dist:.2f}m < {min_gap:.2f}m，站位重叠导致构图低分；"
                        f"沿视线横向错开"),
                },
                "applied": False,
            })
    return prescriptions


def build_coarse_prescriptions(
    *,
    report: Mapping[str, Any],
    reference: Mapping[str, Any],
    only_hard: bool = False,
) -> List[Dict[str, Any]]:
    """从 BlockoutReport + 粗编排参考 JSON 生成结构化粗排处方。

    规则（确定性，全部可追溯）：

    1. ``E_BLOCKOUT_EMPTY_WALL`` error finding -> 该镜相机 target 指向主体质心
       （``component=target, direction=towards_subject``）；
    2. ``on_screen`` check fail（主体几乎出画）-> 相机沿视线拉远 10%
       （``component=distance, direction=out``）；
    3. ``composition`` check fail -> 相机沿视线推近 10%
       （``component=distance, direction=in``；同一镜已有拉远处方则不重复）；
    4. ``occlusion`` check fail（可见比低于 0.5）-> 相机抬高
       （``component=position.z, direction=up``，量级 ∝ (1 - actual)）。
    5. ``E_FOREGROUND_OCCLUSION`` error -> 相机沿视线拉远 15%，让前景体块
       与主体重新建立可读间隔；该处方属于硬伤，粗排循环必须执行。渐进策略：
       该镜尚未拉远 -> 拉远 15%（旧行为）；已拉远仍被挡 -> 横向绕行
       （``component=strafe``，沿视线水平垂直方向侧移）；已绕行仍被挡 ->
       反向绕行（sign 交替，读 revisions 留痕判定，不凭空猜）。
    6. ``E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED`` error -> 拍对象可解析时相机
       target 指向该对象世界坐标（与 empty_wall 同款）；不可解析时产出
       ``unresolved=True`` 的显式未应用处方（``applied=False`` + 明确 reason），
       让修正循环如实收敛、不空转。

    ``only_hard=True`` 时只产出 error finding（E_BLOCKOUT_EMPTY_WALL）处方：
    粗排修正循环只修硬伤；构图/遮挡/出画软处方留给细排阶段（T06）。
    """
    prescriptions: List[Dict[str, Any]] = []
    findings_by_shot = _findings_by_shot(report)
    checks_by_shot = _checks_by_shot(report)

    for shot_id, findings in findings_by_shot.items():
        camera = _camera_of(reference, shot_id)
        if camera is None:
            continue  #: 未知镜不产凭空处方
        for finding in findings:
            check_id = str(finding.get("check_id") or "")
            if check_id == "E_SUBJECT_AREA_OVERFLOW":
                position = _vec3(camera.get("position"))
                target = _vec3(camera.get("target"))
                if position is None or target is None:
                    continue
                distance = max(_distance(position, target), 1e-6)
                direction_vec = {k: (target[k] - position[k]) / distance
                                 for k in ("x", "y", "z")}
                pull = 0.15 * distance
                new_position = {k: position[k] - direction_vec[k] * pull
                                for k in ("x", "y", "z")}
                prescriptions.append({
                    "prescription_id": f"p_coarse_{shot_id}_foreground_occlusion",
                    "scope": "camera", "shot_id": shot_id,
                    "entity": str(camera.get("camera_id") or f"cam_{shot_id}"),
                    "component": "distance", "axis": "distance",
                    "direction": "out", "magnitude": round(pull, 4),
                    "current_value": {"position": position, "target": target},
                    "target_value": {"position": new_position, "target": target},
                    "derived_from": {
                        "check_id": check_id,
                        "severity": str(finding.get("severity") or ""),
                        "message": str(finding.get("message") or ""),
                    },
                    "applied": False,
                })
                continue
            if check_id == "E_FOREGROUND_OCCLUSION":
                position = _vec3(camera.get("position"))
                target = _vec3(camera.get("target"))
                if position is None or target is None:
                    continue
                distance = max(_distance(position, target), 1e-6)
                pulled = _applied_component_count(
                    reference, shot_id, "distance")
                strafed = _applied_component_count(
                    reference, shot_id, "strafe")
                occluders = [str(x) for x in
                             (finding.get("occluders") or []) if x]
                occluder_pos = None
                occluder_entity = None
                if occluders:
                    #: 空间尺 OcclusionEvent 归因：取首个可解析遮挡体的
                    #: 世界坐标；多个遮挡体时仍按首个（确定性、不猜）。
                    for occluder_id in occluders:
                        pos = _occluder_geometry(
                            reference, occluder_id, shot_id=shot_id)
                        if pos is not None:
                            occluder_pos = pos
                            occluder_entity = occluder_id
                            break
                if pulled == 0:
                    #: 尚未拉远：旧行为沿视线拉远 15%
                    direction_vec = {
                        k: (target[k] - position[k]) / distance
                        for k in ("x", "y", "z")}
                    pull = 0.15 * distance
                    new_position = {
                        k: position[k] - direction_vec[k] * pull
                        for k in ("x", "y", "z")}
                    prescriptions.append({
                        "prescription_id":
                            f"p_coarse_{shot_id}_foreground_occlusion",
                        "scope": "camera", "shot_id": shot_id,
                        "entity": str(camera.get("camera_id")
                                      or f"cam_{shot_id}"),
                        "component": "distance", "axis": "distance",
                        "direction": "out",
                        "magnitude": round(pull, 4),
                        "current_value": {"position": position,
                                          "target": target},
                        "target_value": {"position": new_position,
                                         "target": target},
                        "derived_from": {
                            "check_id": check_id,
                            "severity": str(finding.get("severity") or ""),
                            "message": str(finding.get("message") or ""),
                        },
                        "applied": False,
                    })
                else:
                    if occluder_entity is not None and occluder_pos is not None \
                            and any(
                                str(c.get("name") or "") == occluder_entity
                                for c in reference.get("characters") or []):
                        #: 遮挡体是可动角色：直接平移站位到视线轴外——
                        #: 空间尺 _REPAIR 的方向（move_character）落到粗排
                        #: 参考 JSON，比只绕相机更接近"调整站位到合理"。
                        sign = _strafe_sign_towards_free_side(
                            position, target, occluder_pos)
                        lateral = _strafe_position(
                            position, target, sign)
                        #: 角色沿相机侧移方向平移视线距离的 0.2 倍
                        amount = 0.2 * distance
                        dx = lateral["x"] - position["x"]
                        dy = lateral["y"] - position["y"]
                        move_len = (dx * dx + dy * dy) ** 0.5 or 1.0
                        new_char_pos = {
                            "x": round(occluder_pos["x"]
                                       + dx / move_len * amount, 4),
                            "y": round(occluder_pos["y"]
                                       + dy / move_len * amount, 4),
                            "z": occluder_pos["z"],
                        }
                        prescriptions.append({
                            "prescription_id":
                                f"p_coarse_{shot_id}_clear_occluder",
                            "scope": "character", "shot_id": shot_id,
                            "entity": occluder_entity,
                            "component": "character_position",
                            "axis": "position",
                            "direction": (
                                "right" if sign > 0 else "left"),
                            "magnitude": round(amount, 4),
                            "current_value": occluder_pos,
                            "target_value": new_char_pos,
                            "derived_from": {
                                "check_id": check_id,
                                "severity":
                                    str(finding.get("severity") or ""),
                                "message": str(finding.get("message") or ""),
                                "occluders": occluders,
                            },
                            "applied": False,
                        })
                    else:
                        #: 遮挡体非可动角色（道具/锚点/解析不到）：相机
                        #: 绕行，方向由几何算出（远离遮挡体侧），不再固定
                        #: right/left 交替（交替在第二轮会撤销第一轮成果）。
                        if occluder_pos is not None:
                            sign = _strafe_sign_towards_free_side(
                                position, target, occluder_pos)
                        else:
                            sign = 1 if strafed % 2 == 0 else -1
                        new_position = _strafe_position(
                            position, target, sign)
                        prescriptions.append({
                            "prescription_id": f"p_coarse_{shot_id}_strafe",
                            "scope": "camera", "shot_id": shot_id,
                            "entity": str(camera.get("camera_id")
                                          or f"cam_{shot_id}"),
                            "component": "strafe", "axis": "strafe",
                            "direction": (
                                "right" if sign > 0 else "left"),
                            "magnitude": round(
                                _distance(position, new_position), 4),
                            "current_value": {"position": position,
                                              "target": target},
                            "target_value": {"position": new_position,
                                             "target": target},
                            "derived_from": {
                                "check_id": check_id,
                                "severity":
                                    str(finding.get("severity") or ""),
                                "message": str(finding.get("message") or ""),
                                "occluders": occluders,
                            },
                            "applied": False,
                        })
                continue
            if check_id == E_BLOCKOUT_FRAMING_TARGET_OCCLUDED:
                position = _vec3(camera.get("position"))
                target = _vec3(camera.get("target"))
                if position is None or target is None:
                    continue
                distance = max(_distance(position, target), 1e-6)
                prescription_id = (
                    f"p_coarse_{shot_id}_framing_target_occluded")
                applied_repairs = _applied_prescription_count(
                    reference, shot_id, prescription_id)
                if applied_repairs == 0:
                    component = "distance"
                    direction = "out"
                    direction_vec = {
                        k: (target[k] - position[k]) / distance
                        for k in ("x", "y", "z")
                    }
                    pull = 0.15 * distance
                    new_position = {
                        k: position[k] - direction_vec[k] * pull
                        for k in ("x", "y", "z")
                    }
                else:
                    component = "strafe"
                    sign = 1 if applied_repairs % 2 == 1 else -1
                    direction = "right" if sign > 0 else "left"
                    pull = 0.15 * distance
                    new_position = _strafe_position(position, target, sign)
                prescriptions.append({
                    "prescription_id": prescription_id,
                    "scope": "camera", "shot_id": shot_id,
                    "entity": str(camera.get("camera_id")
                                  or f"cam_{shot_id}"),
                    "component": component, "axis": component,
                    "direction": direction,
                    "magnitude": round(pull, 4),
                    "current_value": {
                        "position": position,
                        "target": target,
                    },
                    "target_value": {
                        "position": new_position,
                        "target": target,
                    },
                    "derived_from": {
                        "check_id": check_id,
                        "severity": str(finding.get("severity") or ""),
                        "message": str(finding.get("message") or ""),
                    },
                    "applied": False,
                })
                continue
            if check_id == E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED:
                target = _subject_centroid(reference, shot_id)
                if target is not None:
                    current = _vec3(camera.get("target"))
                    if current is not None:
                        prescriptions.append({
                            "prescription_id":
                                f"p_coarse_{shot_id}_framing_target",
                            "scope": "camera", "shot_id": shot_id,
                            "entity": str(camera.get("camera_id")
                                          or f"cam_{shot_id}"),
                            "component": "target", "axis": "target",
                            "direction": "towards_subject",
                            "magnitude": round(_distance(current, target), 4),
                            "current_value": dict(current),
                            "target_value": target,
                            "derived_from": {
                                "check_id": check_id,
                                "severity":
                                    str(finding.get("severity") or ""),
                                "message": str(finding.get("message") or ""),
                            },
                            "applied": False,
                        })
                else:
                    #: 不可解析：显式未应用处方触发循环收敛，不空转
                    prescriptions.append({
                        "prescription_id":
                            f"p_coarse_{shot_id}_framing_target_unresolved",
                        "scope": "camera", "shot_id": shot_id,
                        "entity": str(camera.get("camera_id")
                                      or f"cam_{shot_id}"),
                        "component": "target", "axis": "target",
                        "direction": "unresolved",
                        "magnitude": 0.0,
                        "current_value": None,
                        "target_value": None,
                        "unresolved": True,
                        "reason": (
                            f"拍对象未解析：shot {shot_id} 的 framing_target "
                            f"无法解析为任何角色/道具世界坐标（计划引用与"
                            f"道具 id 脱节或参考 JSON 缺该实体坐标），需补缺"
                            f"主体或回写实测坐标后重试"),
                        "derived_from": {
                            "check_id": check_id,
                            "severity": str(finding.get("severity") or ""),
                            "message": str(finding.get("message") or ""),
                        },
                        "applied": False,
                    })
                continue
            if check_id != E_BLOCKOUT_EMPTY_WALL:
                continue
            target = _subject_centroid(reference, shot_id)
            if target is None:
                continue
            current = _vec3(camera.get("target"))
            if current is None:
                continue
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_empty_wall",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "target", "axis": "target",
                "direction": "towards_subject",
                "magnitude": round(_distance(current, target), 4),
                "current_value": dict(current),
                "target_value": target,
                "derived_from": {
                    "check_id": str(finding.get("check_id")),
                    "severity": str(finding.get("severity") or ""),
                    "message": str(finding.get("message") or ""),
                },
                "applied": False,
            })

    for shot_id, checks in checks_by_shot.items():
        if only_hard:
            break  #: 软指标处方不在粗排修正循环中使用
        camera = _camera_of(reference, shot_id)
        if camera is None:
            continue
        position = _vec3(camera.get("position"))
        target = _vec3(camera.get("target"))
        if position is None or target is None:
            continue

        already_distance = any(
            p["shot_id"] == shot_id and p["component"] == "distance"
            for p in prescriptions)

        on_screen = checks.get("on_screen")
        if (on_screen and on_screen.get("verdict") == "fail"
                and not already_distance):
            distance = max(_distance(position, target), 1e-6)
            direction_vec = {k: (target[k] - position[k]) / distance
                             for k in ("x", "y", "z")}
            pull = 0.1 * distance
            new_position = {k: position[k] - direction_vec[k] * pull
                            for k in ("x", "y", "z")}
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_pull_back",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "distance", "axis": "distance",
                "direction": "out",
                "magnitude": round(pull, 4),
                "current_value": {"position": position, "target": target},
                "target_value": {"position": new_position, "target": target},
                "derived_from": {
                    "check_id": "on_screen",
                    "actual": on_screen.get("actual"),
                    "threshold": on_screen.get("threshold"),
                    "verdict": "fail",
                },
                "applied": False,
            })
            already_distance = True

        composition = checks.get("composition")
        if (composition and composition.get("verdict") == "fail"
                and not already_distance):
            #: 先出站位错开处方（重叠/互挡角色沿视线横向错开），再退相机
            #: 推近——站位是构图低分的根因，相机只能补偿不能根治
            #: （用户 2026-10-21 裁决：随机应变调整到合理，用结构化数据
            #: 控制角色路线，纯计算可模拟）。
            prescriptions.extend(_character_separation_prescriptions(
                reference, shot_id, checks))
            distance = max(_distance(position, target), 1e-6)
            direction_vec = {k: (target[k] - position[k]) / distance
                             for k in ("x", "y", "z")}
            push = 0.1 * distance
            new_position = {k: position[k] + direction_vec[k] * push
                            for k in ("x", "y", "z")}
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_push_in",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "distance", "axis": "distance",
                "direction": "in",
                "magnitude": round(push, 4),
                "current_value": {"position": position, "target": target},
                "target_value": {"position": new_position, "target": target},
                "derived_from": {
                    "check_id": "composition",
                    "actual": composition.get("actual"),
                    "threshold": composition.get("threshold"),
                    "verdict": "fail",
                },
                "applied": False,
            })

        occlusion = checks.get("occlusion")
        if (occlusion and occlusion.get("verdict") == "fail"
                and not any(p["shot_id"] == shot_id
                            and p["component"] in {
                                "position.z", "position.y"}
                            for p in prescriptions)):
            actual = float(occlusion.get("actual") or 0.0)
            raise_by = min(0.6, max(0.1, (1.0 - actual) * 0.8))
            prescriptions.append({
                "prescription_id": f"p_coarse_{shot_id}_raise_cam",
                "scope": "camera", "shot_id": shot_id,
                "entity": str(camera.get("camera_id")
                              or f"cam_{shot_id}"),
                "component": "position.z", "axis": "z",
                "direction": "up",
                "magnitude": round(raise_by, 4),
                "current_value": position["z"],
                "target_value": round(position["z"] + raise_by, 4),
                "derived_from": {
                    "check_id": "occlusion",
                    "actual": occlusion.get("actual"),
                    "threshold": occlusion.get("threshold"),
                    "verdict": "fail",
                },
                "applied": False,
            })

    return prescriptions


def _apply_target(camera: Dict[str, Any], target_value: Any) -> None:
    if not isinstance(target_value, Mapping):
        raise ValueError("target 处方缺 target_value 坐标")
    camera["target"] = _to_list(target_value)


def _apply_distance(camera: Dict[str, Any], target_value: Any) -> None:
    position = (target_value or {}).get("position")
    if not isinstance(position, Mapping):
        raise ValueError("distance 处方缺 target_value.position")
    camera["position"] = _to_list(position)


def _apply_position_y(camera: Dict[str, Any], target_value: Any) -> None:
    """旧版处方兼容：历史记录把“抬高相机”误写成 ``position.y``。"""
    if not isinstance(camera.get("position"), (list, tuple)):
        raise ValueError("position 必须为列表 [x,y,z] 才能改 y")
    position = list(camera["position"])
    position[1] = round(float(target_value), 4)
    camera["position"] = position


def _apply_position_z(camera: Dict[str, Any], target_value: Any) -> None:
    """按 Blender 世界坐标抬高相机：``position[2]`` 是高度。"""
    if not isinstance(camera.get("position"), (list, tuple)):
        raise ValueError("position 必须为列表 [x,y,z] 才能改 z")
    position = list(camera["position"])
    position[2] = round(float(target_value), 4)
    camera["position"] = position


def _apply_character_position(reference: Dict[str, Any], shot_id: str,
                              entity: str, target_value: Any,
                              *, reason: str = "") -> None:
    """Write one shot's local character staging.

    The scene-wide ``characters[].position`` is a continuity baseline, not
    scratch space for the currently repaired shot.  Local staging therefore
    lives in ``shot_staging[shot_id][entity]`` and is resolved only when that
    shot is previewed, measured or has its camera re-solved.
    """
    if not isinstance(target_value, Mapping):
        raise ValueError("character_position 处方缺 target_value 坐标")
    set_shot_character_position(
        reference,
        shot_id=str(shot_id),
        name=str(entity),
        position=target_value,
        provenance="agent_local_revision",
        reason=reason,
    )


def _resolve_camera_intents_after_character_moves(
    reference: Dict[str, Any],
    moved_entities_by_shot: Mapping[str, Sequence[str]],
) -> set[str]:
    """角色局部站位变化后，只重解该镜依赖角色的机位。

    粗排处方按旧空间生成，角色错开后旧 camera target 仍指向旧站位。
    后续 ``push_in`` / ``pull_back`` 只沿旧视线推拉，无法修正横向瞄准，
    会在同一构图分附近振荡。这里复用空间设计层的唯一机位求解器，并把
    求解结果覆盖回受影响镜头；未移动角色的镜头保持既有构图修正。
    """
    if not moved_entities_by_shot:
        return set()
    affected: List[str] = []
    for shot_id, names in moved_entities_by_shot.items():
        moved = {str(name) for name in names if str(name)}
        shot = next(
            (item for item in reference.get("shots") or []
             if isinstance(item, Mapping)
             and str(item.get("shot_id") or "") == str(shot_id)),
            None,
        )
        if shot is not None and moved:
            shot_names = {
                str(name) for name in (shot.get("characters") or [])}
            framing = shot.get("framing_target")
            if isinstance(framing, Mapping) and framing.get("ref"):
                shot_names.add(str(framing.get("ref")))
            if shot_names & moved:
                affected.append(str(shot_id))
    if not affected:
        return set()

    from .spatial_design import resolve_camera_intents

    resolved_by_shot: Dict[str, Dict[str, Any]] = {}
    for shot_id in sorted(set(affected)):
        effective = effective_shot_reference(reference, shot_id)
        partial = effective
        partial["shots"] = [
            dict(shot) for shot in (effective.get("shots") or [])
            if str(shot.get("shot_id") or "") == shot_id
        ]
        resolved = resolve_camera_intents(partial)
        for intent in resolved.get("camera_intents") or []:
            if str(intent.get("shot_id") or "") == shot_id:
                resolved_by_shot[shot_id] = dict(intent)
    if not resolved_by_shot:
        return set()
    reference["camera_intents"] = [
        resolved_by_shot.get(str(intent.get("shot_id") or ""), intent)
        for intent in (reference.get("camera_intents") or [])
    ]
    reference.setdefault("notes", []).append(
        "角色站位移动后重解相关镜头机位："
        + "、".join(
            f"{shot_id}:{'/'.join(sorted(set(names)))}"
            for shot_id, names in sorted(moved_entities_by_shot.items()))
        + " -> " + "、".join(sorted(set(affected))))
    return set(affected)


_APPLIERS = {
    "target": _apply_target,
    "distance": _apply_distance,
    "strafe": _apply_distance,
    "position.y": _apply_position_y,
    "position.z": _apply_position_z,
}


def apply_coarse_prescriptions(
    reference: Mapping[str, Any],
    prescriptions: List[Dict[str, Any]],
    *,
    revision_id: str = "",
    round_no: int = 1,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """把处方应用到粗编排参考 JSON，落 revision 留痕。

    返回 ``(new_reference, applied_records)``。``new_reference`` 是深拷贝后
    修改的结果（不污染输入）；``revisions[]`` 追加一条修订记录
    （before/after 指纹 + 逐条处方结果）。未知实体/未知轴记录
    ``applied=False`` 与原因，不抛错、不吞错、不修改。
    """
    import copy

    new_ref = copy.deepcopy(reference)
    by_shot = {str(c.get("shot_id") or ""): c
               for c in new_ref.get("camera_intents") or []}
    records: List[Dict[str, Any]] = []
    moved_entities_by_shot: Dict[str, List[str]] = {}
    for p in prescriptions:
        shot_id = str(p.get("shot_id") or "")
        component = str(p.get("component") or "")
        camera = by_shot.get(shot_id)
        record: Dict[str, Any] = {
            "prescription_id": p.get("prescription_id"),
            "shot_id": shot_id,
            "component": component,
            "applied": False,
            "before": None,
            "after": None,
            "reason": "",
        }
        if p.get("unresolved"):
            #: 拍对象不可解析（E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED 处方）：
            #: 显式未应用 + 明确 reason，不经过应用器、不吞错，让修正循环
            #: 如实收敛（宁可 blocked 也不凭空指向错误坐标）。
            record["reason"] = str(
                p.get("reason") or "拍对象未解析，处方不可执行")
            records.append(record)
            continue
        if camera is None:
            record["reason"] = f"未知 shot_id：{shot_id}"
            records.append(record)
            continue
        applier = _APPLIERS.get(component)
        if component == "character_position":
            try:
                record["before"] = {
                    "position": copy.deepcopy(
                        next(
                            (c.get("position")
                             for c in effective_shot_reference(
                                 new_ref, shot_id).get("characters") or []
                             if str(c.get("name") or "")
                             == str(p.get("entity") or "")),
                            None,
                        )),
                }
                _apply_character_position(
                    new_ref, shot_id, str(p.get("entity") or ""),
                    p.get("target_value"),
                    reason=str(
                        p.get("reason")
                        or (p.get("derived_from") or {}).get("message")
                        or ""))
                record["after"] = {
                    "position": copy.deepcopy(
                        next(
                            (c.get("position")
                             for c in effective_shot_reference(
                                 new_ref, shot_id).get("characters") or []
                             if str(c.get("name") or "")
                             == str(p.get("entity") or "")),
                            None,
                        )),
                }
                same = record["before"].get("position") == \
                    record["after"].get("position")
                if same:
                    record["applied"] = False
                    record["no_op"] = True
                    record["reason"] = "零变化处方：应用前后世界坐标一致"
                else:
                    record["applied"] = True
                    moved_entities_by_shot.setdefault(shot_id, []).append(
                        str(p.get("entity") or ""))
            except (TypeError, ValueError) as exc:
                record["reason"] = f"应用失败：{exc}"
            records.append(record)
            continue
        if applier is None:
            record["reason"] = f"未知 component：{component}"
            records.append(record)
            continue
        try:
            record["before"] = {
                "position": copy.deepcopy(camera.get("position")),
                "target": copy.deepcopy(camera.get("target")),
            }
            applier(camera, p.get("target_value"))
            record["after"] = {
                "position": copy.deepcopy(camera.get("position")),
                "target": copy.deepcopy(camera.get("target")),
            }
            before = record["before"]
            after = record["after"]
            same_position = before.get("position") == after.get("position")
            same_target = before.get("target") == after.get("target")
            if same_position and same_target:
                #: R2-F6：处方应用后世界坐标零变化（如 target 已指向质心），
                #: 不再计 applied；标记 no_op 交给修正循环做收敛判定，避免在
                #: 无实质修改的空转上耗完修正轮数预算。
                record["applied"] = False
                record["no_op"] = True
                record["reason"] = "零变化处方：应用前后世界坐标一致"
            else:
                #: Provenance follows the mutation that actually won.  A
                #: camera field copied from the script stays
                #: ``script_declaration`` only until an approved agent
                #: prescription changes its physical value.
                camera["provenance"] = "agent_local_revision"
                camera["revision_reason"] = str(
                    p.get("reason")
                    or (p.get("derived_from") or {}).get("message")
                    or p.get("prescription_id")
                    or "")
                record["applied"] = True
        except (TypeError, ValueError) as exc:
            record["reason"] = f"应用失败：{exc}"
        records.append(record)

    affected_shots = _resolve_camera_intents_after_character_moves(
        new_ref, moved_entities_by_shot)
    if affected_shots:
        final_by_shot = {
            str(intent.get("shot_id") or ""): intent
            for intent in (new_ref.get("camera_intents") or [])
        }
        for record in records:
            if (not record.get("applied")
                    or record["shot_id"] not in affected_shots
                    or record["component"] == "character_position"):
                continue
            final = final_by_shot.get(record["shot_id"]) or {}
            record["attempted_after"] = record.get("after")
            record["after"] = {
                "position": copy.deepcopy(final.get("position")),
                "target": copy.deepcopy(final.get("target")),
            }
            record["applied"] = False
            record["superseded"] = True
            record["reason"] = (
                "同轮角色站位移动后已按新主体位置重解机位，"
                "按旧站位生成的相机处方不构成最终状态")
    if records:
        new_ref.setdefault("revisions", []).append({
            "revision_id": str(revision_id or "deterministic-replay"),
            "round": int(round_no),
            "fingerprint_before": coarse_reference_content_fingerprint(
                reference),
            "fingerprint_after": coarse_reference_content_fingerprint(
                new_ref),
            "prescriptions": records,
        })
    return new_ref, records


__all__ = ["build_coarse_prescriptions", "apply_coarse_prescriptions",
           "effective_shot_reference",
           "resolve_prop_ref", "_occluder_geometry",
           "_strafe_sign_towards_free_side",
           "E_BLOCKOUT_EMPTY_WALL", "E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED",
           "COMPOSITION_PASS_SCORE"]
