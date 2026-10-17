"""Level 1 确定性规则校验（执行文档 v1.2 §11.1）。

零延迟、不可跳过，返回结构化 :class:`AuditError` 供定向修复回灌（§18.3）。

已实现：R001 轴线、R004 视锥、R005 在画、R006 帧范围、R007 引用、
R002 空间碰撞、R003 动作时间轴、R008 地面、R009 景别距离、R010 30° 规则，
    以及构图质量门（§7.1 B3 明确把"构图"列为通过条件，因此未高于阈值
    （<=，等于也不算过）按 ERROR 处理，而不是只给警告；用户 2026-10-18
    裁决：构图分必须严格高于 80）。

**待补（依赖 Layer 1）**：R011 对白容纳——它需要对白计时（§4.4），而计划里
目前只带 dialogue_ids、不带对白的时间轴。
"""

from __future__ import annotations

import math
from typing import Any, Dict, FrozenSet, List, Tuple

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from ..cinema.axis import (
    AXIS_DRIFT_DEG,
    Axis,
    ScreenOrderState,
    ScreenSample,
    axis_state,
    axis_violation,
    crossing_events,
    current_line,
    drift_is_bridged,
    flipped_screen_directions,
    shared_characters,
    thirty_degree_violation,
    update_order,
)
from ..cinema.framing import SHOT_FRAME, required_distance
from ..cinema.composition import PASS_SCORE
from ..layer1_input.dialogue_timing import DIALOGUE_TAIL_FRAMES
from ..contracts.audit import AuditError, AuditResult, SkippedFinding
from ..contracts.enums import Severity
from ..utils.aabb import AABB, union
from ..utils.logger import get_logger

from ..utils.threading_guard import main_thread_only

log = get_logger("rules")

GROUND_EPS = 0.02
DISTANCE_TOLERANCE = 0.25
FRAME_MARGIN = 0.05
COLLISION_MARGIN = 0.2
OBSTACLE_PREFIXES = ("BD_Wall_", "BD_Prop_")

#: v1.7 F1：被关闭的规则号（模块级注入——不 import 插件侧 settings 单例，
#: layer3 反向依赖包根会成环且不可测）。审核入口在每次 check 前同步。
_RULES_DISABLED: FrozenSet[str] = frozenset()
#: v1.7 J1（R020）：跨镜包围盒世界高度漂移阈值（模块级注入，照 F1 模式——
#: 不 import 插件侧 settings 单例）。默认与 ``GuardConfig.scale_drift`` 一致。
_SCALE_DRIFT: float = 0.05
#: v1.7 J2（R021–R023）：相机运动阈值的模块级注入（照 J1 模式，由审核入口
#: 在 check 前同步）。默认与 ``GuardConfig`` 一致。
_CAM_ACCEL_MAX: float = 8.0        # R023，单位 m/s²（待实测校准）
_COMPOUND_MOTION_MAX: int = 2      # R021 单镜复合运动上限
_ANIMATION_FPS: int = 24           # R023 单位换算用（config.animation.fps）
#: v1.7 J4（R025）：实测运镜数据总开关（模块级注入，照 F1/J1/J2 模式）。
#: 默认关——关时 ``_measured_camera`` 不产数据、``AuditResult`` 不出
#: ``measured_camera`` 键（零形状差纪律）。
_PROMPT_CONFLICT_CHECK: bool = False

#: R021 航向突变角阈值（度），对齐 R010 的 30° 词汇。
MOVE_HEADING_TURN_DEG: float = 30.0
#: R022 退化帧判据：视线与天顶（ẑ）夹角小于此角度时右向量叉积无定义，跳过。
ROLL_DEGENERATE_DEG: float = 5.0


def configure_rules_disabled(rules: Any) -> None:
    """同步本次审核的禁用规则集合（空集合 = 全规则生效，零行为差）。"""
    global _RULES_DISABLED
    _RULES_DISABLED = frozenset(str(item) for item in (rules or ()))


def configure_scale_drift(value: Any) -> None:
    """同步 R020 的漂移阈值（审核入口在 check 前调用，与 F1 同一注入模式）。"""
    global _SCALE_DRIFT
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.05
    _SCALE_DRIFT = parsed if 0.0 < parsed < 1.0 else 0.05


def configure_camera_limits(accel_max: Any = None, *,
                            compound_max: Any = None,
                            fps: Any = None) -> None:
    """同步 R021–R023 的相机运动阈值与单位换算帧率（J2，审核入口注入）。

    照 ``configure_scale_drift`` 的模式：非法值回落默认，绝不 raise——
    config 层的 CFG_174/CFG_175 负责启动前拦下非法配置。
    """
    global _CAM_ACCEL_MAX, _COMPOUND_MOTION_MAX, _ANIMATION_FPS
    try:
        parsed_accel = float(accel_max)
    except (TypeError, ValueError):
        parsed_accel = 8.0
    _CAM_ACCEL_MAX = parsed_accel if parsed_accel > 0.0 else 8.0
    try:
        parsed_compound = int(compound_max)
    except (TypeError, ValueError):
        parsed_compound = 2
    _COMPOUND_MOTION_MAX = parsed_compound if parsed_compound >= 1 else 2
    try:
        parsed_fps = int(fps)
    except (TypeError, ValueError):
        parsed_fps = 24
    _ANIMATION_FPS = parsed_fps if parsed_fps >= 1 else 24


def configure_prompt_conflict_check(enabled: Any = None) -> None:
    """同步 R025 的实测运镜开关注入（J4，审核入口在 check 前调用）。

    照 ``configure_scale_drift`` 的模式：非法值回落默认（关），绝不 raise。
    """
    global _PROMPT_CONFLICT_CHECK
    try:
        parsed = bool(enabled)
    except Exception:
        parsed = False
    _PROMPT_CONFLICT_CHECK = parsed


def _finding(severity: Severity, rule: str, code: str, message: str,
             target: str = "", suggestion: str = "") -> AuditError:
    if rule in _RULES_DISABLED:
        return SkippedFinding(rule=rule)
    return AuditError(rule=rule, code=code, severity=severity, target=target,
                      message=message, suggestion=suggestion)


def _error(rule: str, code: str, message: str, target: str = "",
           suggestion: str = "") -> AuditError:
    return _finding(Severity.ERROR, rule, code, message, target, suggestion)


def _warning(rule: str, code: str, message: str, target: str = "",
             suggestion: str = "") -> AuditError:
    return _finding(Severity.WARNING, rule, code, message, target, suggestion)


def _in_frame(point) -> bool:
    return (-FRAME_MARGIN <= point.x <= 1.0 + FRAME_MARGIN
            and -FRAME_MARGIN <= point.y <= 1.0 + FRAME_MARGIN)


def _character_positions(characters):
    positions = []
    for character in characters:
        root = getattr(character, "root", None)
        if root is not None:
            positions.append(root.matrix_world.translation.copy())
    return positions


#: 判定"机位是否落在轴线上"（§6.2 的中性桥梁）。放在模块层：`check_shot` 里的
#: 同款导入是函数内的局部导入，本文件的模块级辅助函数看不到它。
def _camera_is_neutral(axis, camera) -> bool:
    from .cinema_engine.axis_controller import check_camera_neutral

    return check_camera_neutral(axis, camera) is not None


def _crossing_map(context) -> Dict[str, Any]:
    """配对换位表（纯计划推算），算一次缓存在 context 上。"""
    cached = getattr(context, "_crossing_map", None)
    if cached is not None:
        return cached
    spec = getattr(context, "spec", None)
    plan = getattr(context, "plan", None)
    axis = getattr(context, "axis", None)
    if spec is None or plan is None or axis is None:
        return {}
    initial: Dict[str, Tuple[float, float, float]] = {}
    for member in getattr(spec, "cast", []) or []:
        location = tuple(getattr(member, "initial_location", (0.0, 0.0, 0.0)))
        initial[str(getattr(member, "id", ""))] = location
        name = str(getattr(member, "name", "") or "")
        if name:
            initial[name] = location
    events = crossing_events(axis, plan, initial)
    context._crossing_map = events
    return events


def _pair_screen_order(context, camera, characters) -> List[Tuple[str, float]]:
    """这两个角色在**当前帧**的屏幕 X（归一化视口，0=左、1=右）。"""
    scene = bpy.context.scene
    out: List[Tuple[str, float]] = []
    for character in characters[:2]:
        root = getattr(character, "root", None)
        if root is None:
            continue
        point = world_to_camera_view(scene, camera,
                                     root.matrix_world.translation)
        out.append((str(character.id), float(point.x)))
    return out


def _shot_screen_state(context, camera, shot, characters) -> ScreenOrderState:
    """本镜首帧的银幕左右序状态（B5）：画面 X ＋ 头部朝向投影 → 状态机。

    ``characters`` 只取前两位（对话配对，与旧口径一致）；朝向读不到的角色
    记中性 0——顺序判定本身不需要朝向，朝向只用于桥接判定与证据展示。
    """
    pairs = _pair_screen_order(context, camera, characters[:2])
    facing = screen_facing_for(shot, context=context, camera=camera)
    samples = [
        ScreenSample(character_id=str(character_id),
                     screen_x=float(screen_x),
                     facing_x=float(facing.get(str(character_id), 0.0)))
        for character_id, screen_x in pairs
    ]
    return update_order(ScreenOrderState(), samples)


def _screen_polarity_flip(context, camera, shot, characters) -> str:
    """相邻两人镜：这一对的**屏幕左右顺序**有没有在没人看见时翻转。

    v1.6 B5（FR-C6 / D-14）：判定输入换成 ``cinema/axis`` 的银幕左右序状态机。
    每一镜首帧把"画面 X ＋ 头部朝向投影"折成 ``ScreenOrderState``，前后两镜交给
    ``axis_violation(prev, cur, bridge_ok)`` 比较。``bridge_ok`` 只认中间镜头的
    合法桥接——看得见的换位（两人同框时走过去，老口径保留）、骑轴机位（§6.2）、
    以及 B5 新增的中性镜（**双方** facing_sign 全 0：正/背对相机）。计划的
    ``axis_note`` 文本自述不参与判定（降级为展示文本）。
    """
    if context is None or context.plan is None or context.axis is None:
        return ""
    if len(characters) < 2:
        return ""                      # 单人镜的方向连续性归 R019；中性机位另有告警
    order = [str(item.shot_id) for item in context.plan.shots]
    if shot.shot_id not in order:
        return ""
    index = order.index(shot.shot_id)
    previous = None
    previous_index = -1
    for position in range(index - 1, -1, -1):
        candidate = context.plan.shots[position]
        if len([cid for cid in candidate.characters
                if cid in {character.id for character in characters}]) >= 2:
            previous, previous_index = candidate, position
            break
    if previous is None:
        return ""
    scene = bpy.context.scene
    restore = scene.frame_current
    previous_camera = context.camera_for(previous.shot_id)
    if previous_camera is None:
        return ""
    previous_characters = [context.character(cid) for cid in previous.characters]
    previous_start, _end = shot_frame_span(previous.shot_id, context)
    scene.frame_set(int(previous_start))
    bpy.context.view_layer.update()
    previous_state = _shot_screen_state(context, previous_camera,
                                        previous, previous_characters)
    scene.frame_set(int(restore))
    bpy.context.view_layer.update()
    current_state = _shot_screen_state(context, camera, shot, characters)
    pair = set(previous_state.left_to_right)
    #: 翻转判定交给纯状态机；桥接只看**中间**的镜头。
    events = _crossing_map(context)
    live = current_line(context.axis, _character_xy_by_label(context))
    bridge_ok = False
    for position in range(previous_index + 1, index + 1):
        bridge = context.plan.shots[position]
        bridge_id = str(bridge.shot_id)
        event = events.get(bridge_id)
        if event is not None and event.visible:
            bridge_ok = True
            break
        bridge_camera = context.camera_for(bridge_id)
        if bridge_camera is None:
            continue
        bridge_characters = [context.character(cid) for cid in bridge.characters]
        bridge_start, _bridge_end = shot_frame_span(bridge_id, context)
        scene.frame_set(int(bridge_start))
        bpy.context.view_layer.update()
        bridge_state = _shot_screen_state(context, bridge_camera,
                                          bridge, bridge_characters)
        neutral_camera = _camera_is_neutral(live, bridge_camera)
        scene.frame_set(int(restore))
        bpy.context.view_layer.update()
        if neutral_camera:
            bridge_ok = True
            break
        #: B5 新增：中性镜（双方朝向符号全 0）也是合法桥接。
        if pair and pair <= set(bridge_state.facing_sign) \
                and all(bridge_state.facing_sign[cid] == 0 for cid in pair):
            bridge_ok = True
            break
    warning = axis_violation(previous_state, current_state, bridge_ok)
    if warning is None:
        return ""
    return (f"银幕左右关系在 {previous.shot_id} → {shot.shot_id} 的剪辑点上翻转"
            f"（{'、'.join(previous_state.left_to_right)} → "
            f"{'、'.join(current_state.left_to_right)}），"
            f"而中间没有任何镜头把这次换位拍出来")


def _axis_sides(context) -> Dict[str, int]:
    """规则用的逐镜轴侧 ＝ **构建器摆机位时用的那张表**（计划期近似），缓存一份。

    两条路（会诊 ①，2026-10-04）：

    * **建场景前**：没有机位，`crossing_events` 退回计划期近似（连线转角 ≥90°）——
      构建器就是按这张表摆机位的（`shot_builder._axis_for_placement`）；
    * **相机建好之后**：会诊 ① 第 5 步要求"拿真机位重算并 diff"。**实测后回退**：
      两张表在 `long9` 上分歧 38 镜，若按真机位的表判，会多出 **29 条**"机位在错侧"，
      而**独立的**画面左右序判据（`_screen_polarity_flip`）只证实其中 **2 条**——
      那是**自指回路**（机位是照近似摆的，再用它去翻侧、又拿同一张表判机位），
      不是更准的判据。所以真机位表只用于**报告分歧**（`_axis_sides_exact`）。
      证据 `docs/evidence/20261004-r001-v20/`，逐条见 §七十三。
    """
    base = getattr(context, "axis", None)
    plan = getattr(context, "plan", None)
    if base is None or plan is None:
        return {}
    shots = list(getattr(plan, "shots", []) or [])
    #: 构建器**实际用过**的表（顺序状态机，`shot_builder._axis_for_placement` 边摆边写）。
    #: 相机是照它摆的，规则就该照它判——这才是"两张表"的正当关系。
    used = dict(getattr(context, "_axis_sides_used", None) or {})
    if used and len(used) >= len(shots):
        cached = getattr(context, "_axis_sides", None)
        if cached is not None:
            return cached
        sides = {name: int(side) for name, side in used.items()}
        context._axis_sides = sides
        return sides
    planned = axis_state(base, plan, _initial_positions(context))
    if not used:
        context._axis_sides = planned
        return planned
    #: 还在建（只摆了前几镜）：用"已摆过的实际侧别 ＋ 其余的计划期近似"拼一份，
    #: **不缓存**——否则第一镜的审核会把不完整的表钉死给后面所有镜头。
    merged = dict(planned)
    merged.update({name: int(side) for name, side in used.items()})
    return merged


def _axis_sides_exact(context) -> Dict[str, int]:
    """用**真机位**重算的轴侧表（会诊 ① 的精确判据）——只用来报告分歧，不当判据。"""
    cached = getattr(context, "_axis_sides_camera", None)
    if cached is not None:
        return cached
    base = getattr(context, "axis", None)
    plan = getattr(context, "plan", None)
    if base is None or plan is None:
        return {}
    initial = _initial_positions(context)
    cameras = _built_camera_positions(context, plan)
    sides = (axis_state(base, plan, initial, cameras) if cameras
             else dict(_axis_sides(context)))
    context._axis_sides_camera = sides
    return sides


def _initial_positions(context) -> Dict[str, Tuple[float, float, float]]:
    """剧本起始站位，键同时给 id 与显示名（`crossing_events` 的两套键都认）。"""
    initial: Dict[str, Tuple[float, float, float]] = {}
    spec = getattr(context, "spec", None)
    for member in (getattr(spec, "cast", []) if spec is not None else []) or []:
        location = tuple(getattr(member, "initial_location", (0.0, 0.0, 0.0)))
        initial[str(getattr(member, "id", ""))] = location
        name = str(getattr(member, "name", "") or "")
        if name:
            initial[name] = location
    return initial


def _built_camera_positions(context,
                            plan) -> Dict[str, Tuple[float, float, float]]:
    """每一镜**切入点**的机位坐标；读不到相机（这一镜还没建）就跳过。

    机位是**逐帧**的（运镜会移动它），所以逐镜换帧读一次、最后还原当前帧——
    审核不许把副作用留给渲染。
    """
    scene = bpy.context.scene
    restore = int(scene.frame_current)
    out: Dict[str, Tuple[float, float, float]] = {}
    try:
        for shot in getattr(plan, "shots", []) or []:
            shot_id = str(shot.shot_id)
            camera = context.camera_for(shot_id)
            if camera is None:
                continue
            start, _end = shot_frame_span(shot_id, context)
            scene.frame_set(int(start))
            bpy.context.view_layer.update()
            position = camera.matrix_world.translation
            out[shot_id] = (float(position.x), float(position.y), float(position.z))
    finally:
        scene.frame_set(restore)
        bpy.context.view_layer.update()
    return out


def _axis_state_divergence(context, shot_id: str) -> str:
    """计划期近似与真机位表从哪里开始分道扬镳——**只报第一处**（会诊 ① 第 5 步）。

    逐镜都报会把修复回路淹掉（`long9` 上 38 镜都分歧），所以只写**第一个**分歧镜
    并给出总数：分歧本身是"构建器的近似该升级了"的信号，不是这一镜的错。
    """
    planned = _axis_sides(context)
    exact = _axis_sides_exact(context)
    if not planned or not exact:
        return ""
    divergent = [name for name in planned if exact.get(name) != planned.get(name)]
    if not divergent or str(shot_id) != divergent[0]:
        return ""
    return (f"轴侧表分歧（只报第一处）：构建器的计划期近似与**真机位**重算的表在 "
            f"{len(divergent)} 镜上不一致，本镜是第一个（近似 {planned[str(shot_id)]:+d}"
            f"、真机位 {exact.get(str(shot_id)):+d}）。判据仍按近似判——实测按真机位判"
            f"会多出 29 条『机位在错侧』，而画面左右序那条独立判据只证实其中 2 条"
            f"（2026-10-04，`docs/evidence/20261004-r001-v20/`）")


def _camera_on_wrong_side(context, camera, shot_id: str) -> str:
    """机位是不是跑到**摆位时那条线**的另一侧去了（相对这一镜该待的侧别）。

    G2 v4 实测：这条判据此前拿**走位后的当前连线**量相机、却拿**摆位时**的表
    当期望——角色走位把线转过去之后，没挪过的机位被误判"机位自己摆错"（一整跑
    460 次 error，修复回路因此振荡 455 次回滚）。修正：参照线优先取构建器记录
    的摆位线（``shot_builder._axis_for_placement`` 写入
    ``context._axis_lines_used``），两者同源；走位跨线不在这里判，由
    ``crossing_events`` / ``_axis_rebuild`` 那条"看得见与否"的机制负责。
    没有记录线（手工场景/旧工程）时退回当前连线，行为不变。
    """
    base = getattr(context, "axis", None)
    if base is None:
        return ""
    live = current_line(base, _character_xy_by_label(context))
    expected = int(_axis_sides(context).get(str(shot_id), live.established_side))
    position = camera.matrix_world.translation
    xy = (float(position.x), float(position.y))
    recorded = dict(getattr(context, "_axis_lines_used", None) or {}).get(
        str(shot_id))
    if recorded and len(recorded) == 2:
        line = Axis(start=tuple(recorded[0]), end=tuple(recorded[1]),
                    established_side=live.established_side,
                    left_label=live.left_label, right_label=live.right_label)
    else:
        line = live
    side = line.side_of(xy)
    if side == 0 or side == expected:
        return ""
    return (f"机位在两人连线的另一侧（连线 {line.start}→{line.end}，"
            f"该待在第 {expected:+d} 侧、实际在第 {side:+d} 侧）："
            "这是机位自己摆错，把相机移回该侧即可")


def _axis_rebuild(context, camera) -> Dict[str, Any]:
    """轴线被走位重建了多少度、以及这次重建**有没有被拍出来**（会诊 A2/A3）。

    * `angle`：**规范首镜线** 与 **当前派生线** 的夹角（两条线都由几何给出，
      与被检的"构建器挑了哪条法线"无关）；
    * `bridged`：这次重建有没有合法交代——① **本镜机位中性**（落在线上，§6.2 的
      桥梁，逐镜成立），或 ② **看得见的旋转累计**覆盖了超出阈值的漂移
      （`cinema/axis.drift_is_bridged` 的记账；那条"有**过一次**可见换位就赦免"的
      存在性判定被会诊 F1 证伪：它同时放过暗重建与误判可见慢漂移）。

    **试过但没落地**（2026-10-04，§七十七）：把两边都换成"相对**上一个已交代的锚**"
    （`cinema/axis.drift_report` —— 纯函数、带 3 条守门，留着当积木）。方向更自洽
    （现在这一版是"全片可见旋转累计"对"相对首镜线的漂移"，两边参照系不一致），
    但实测三份冻结工程的 R001 由 13／40／7 变成 **33／41／26**、逐镜通过由
    28／9／24 变成 **22／9／12**，而**没有任何独立判据**证实多出来的那些是真的越轴
    ——和 §七十三 的 F1 回退同一形状：没有独立佐证就不换判据。
    """
    base = getattr(context, "axis", None)
    if base is None:
        return {"angle": 0.0, "bridged": True, "note": ""}
    live = current_line(base, _character_xy_by_label(context))
    if live.length < 1e-6 or base.length < 1e-6:
        return {"angle": 0.0, "bridged": True, "note": ""}
    dx0, dy0 = base.direction
    dx1, dy1 = live.direction
    if (dx0, dy0) == (0.0, 0.0) or (dx1, dy1) == (0.0, 0.0):
        return {"angle": 0.0, "bridged": True, "note": ""}
    cosine = max(-1.0, min(1.0, dx0 * dx1 + dy0 * dy1))
    angle = math.degrees(math.acos(cosine))
    #: **记账**（会诊 F1）：不是"曾经有过一次可见换位就赦免"，而是"看得见的旋转
    #: 累计"要覆盖**超出阈值**的那部分漂移。
    visible_deg = sum(event.rotated_deg
                      for event in _crossing_map(context).values()
                      if event.visible)
    bridged = drift_is_bridged(angle, visible_deg, _camera_is_neutral(live, camera))
    note = (f"轴线已被走位重建：规范首镜线 {base.start}→{base.end} 与当前派生线 "
            f"{live.start}→{live.end} 相差 {angle:.0f}°"
            f"（≥{AXIS_DRIFT_DEG:.0f}°）")
    return {"angle": angle, "bridged": bridged, "note": note}


def _character_xy_by_label(context) -> Dict[str, Tuple[float, float]]:
    """场景里每个角色**此刻**的 XY，键同时给 id 与显示名。"""
    spots: Dict[str, Tuple[float, float]] = {}
    for character_id, character in (getattr(context, "characters", {}) or {}).items():
        root = getattr(character, "root", None)
        if root is None:
            continue
        xy = (float(root.matrix_world.translation.x),
              float(root.matrix_world.translation.y))
        spots[str(character_id)] = xy
        name = str(getattr(character, "name", "") or "")
        if name:
            spots[name] = xy
    return spots


def _unseen_crossing_note(context, shot_id: str) -> str:
    """这一镜之前有没有**看不出来**的换位（只拍一个人的镜头里绕过去）。

    `cinema/axis.crossing_events` 是纯计划推算（不读机位），所以这条说明
    **不会**变成"构建器自己出题自己判"：它讲的是计划里的走位编排，
    由修复回路去改**走位**（或补一个中性机位），而不是动机位。
    """
    if context is None or context.plan is None or context.axis is None:
        return ""
    spec = getattr(context, "spec", None)
    if spec is None:
        return ""
    initial = {}
    for member in getattr(spec, "cast", []) or []:
        location = tuple(getattr(member, "initial_location", (0.0, 0.0, 0.0)))
        initial[str(getattr(member, "id", ""))] = location
        name = str(getattr(member, "name", "") or "")
        if name:
            initial[name] = location
    events = crossing_events(context.axis, context.plan, initial)
    if not events:
        return ""
    order = [str(item.shot_id) for item in context.plan.shots]
    if shot_id not in order:
        return ""
    index = order.index(shot_id)
    for candidate in reversed(order[: index + 1]):
        event = events.get(candidate)
        if event is None or event.visible:
            continue
        return (f"（换位是**看不见**的：{event.people[0]} 与 {event.people[1]} 的连线"
                f"在 {candidate} 翻了头，而那一镜没有让两人同框——把这次换位放进"
                f"一个两人同框的镜头，或在中间插一个 §6.2 的中性机位）")
    return ""


def _crossed_the_axis(axis, character) -> bool:
    """这个角色是不是已经站到**轴线的另一侧**（相对已确立的基准侧）。

    只看角色**自己**站在哪：轴线上（``SIDE_UNKNOWN``）不算跨线——两人相对而立
    时单人机位本来就落在轴线上（§6.2 的 `axis_neutral`）。
    """
    root = getattr(character, "root", None)
    if root is None or axis is None:
        return False
    side = axis.side_of((float(root.matrix_world.translation.x),
                         float(root.matrix_world.translation.y)))
    return side != 0 and side != int(axis.established_side)


def _world_aabb(obj) -> AABB:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return AABB(minimum=(min(c.x for c in corners), min(c.y for c in corners),
                         min(c.z for c in corners)),
                maximum=(max(c.x for c in corners), max(c.y for c in corners),
                         max(c.z for c in corners)))


def _character_aabb(character):
    boxes = [_world_aabb(obj) for obj in getattr(character, "meshes", [])
             if obj.type == "MESH"]
    return union(boxes) if boxes else None


def _first_appearance_shot(character_id: str, context) -> Optional[str]:
    """该角色在计划里**顺序第一镜**（首出场镜）的 shot_id；查不到返回 None。"""
    plan = getattr(context, "plan", None)
    if plan is None:
        return None
    for shot in (plan.shots or []):
        declared = [str(item) for item in (getattr(shot, "characters", None) or [])]
        if character_id in declared:
            return str(shot.shot_id)
    return None


def _check_scale_drift(shot_id: str, context=None,
                       scale_drift: Optional[float] = None) -> List[AuditError]:
    """R020：同一角色跨镜包围盒世界高度漂移告警（J1，warning 级）。

    与**首出场镜**（plan.shots 顺序第一镜）的包围盒世界高度比对；本镜就是
    首出场镜时跳过。每角色每镜至多 1 条，经 ``_finding`` 产出自动吃 F1 开关。
    帧切换复用 ``shot_frame_span``＋还原模式，审核不留副作用。
    """
    threshold = float(scale_drift) if scale_drift is not None else _SCALE_DRIFT
    if context is None or context.plan is None:
        return []
    scene = bpy.context.scene
    original_frame = int(scene.frame_current)
    findings: List[AuditError] = []
    for character in context.subjects_for(shot_id) or []:
        character_id = str(getattr(character, "id", ""))
        if not character_id:
            continue
        first_shot = _first_appearance_shot(character_id, context)
        if not first_shot or first_shot == shot_id:
            continue                        # 首出场镜没有基线可比对
        h0 = _height_at(first_shot, character, context)
        h = _height_at(shot_id, character, context)
        if h0 is None or h is None or h0 <= 1e-9:
            continue
        drift = abs(h - h0) / h0
        if drift > threshold:
            findings.append(_warning(
                "R020", "E_SPACE_001",
                f"{character_id} 跨镜包围盒世界高度漂移：首镜 {first_shot} 高 "
                f"{h0:.2f}m → 本镜 {shot_id} 高 {h:.2f}m（相对差 "
                f"{drift:.1%} > {threshold:.0%}）",
                target=character_id,
                suggestion="保持同一角色的世界高度跨镜一致（几何 1.70 冻结）"))
    if scene.frame_current != original_frame:
        scene.frame_set(original_frame)
        bpy.context.view_layer.update()
    return findings


#: v1.7 J3（R024）：白名单外的 root 动画通道仅作告警，不改行为。
#: 与 `body_tilt` 允许键表同源约束（见 character_system 的 BW-1 键表），
#: 这里独立列出避免 import 任何 bpy 侧的纯函数。
_ANIMATION_WHITELIST = {
    "location", "rotation_euler",
    "location.x", "location.y", "location.z",
    "rotation_euler.x", "rotation_euler.y", "rotation_euler.z",
    "body_tilt", "body_tilt.x", "body_tilt.y", "body_tilt.z",
}


def _check_responsibility(shot_id: str, context=None) -> List[AuditError]:
    """R024：分工矛盾（v1.7 J3，warning 级，E_ANIM_001）。

    分支一（声明 skip 但场景有主体）：某角色**全部出场镜**都
    ``responsibility.skip_white_model=true``，但场景里仍存在其白模主体
    （``context.characters`` 含该 id）→ 恰好 1 条；
    分支二（白名单外动画通道）：root 的 ``animation_data.action.fcurves``
    ``data_path`` 全集超出白名单（含形态键/pose 骨骼通道）→ 恰好 1 条。
    每镜每角色至多 1 条。
    """
    findings: List[AuditError] = []
    if context is None or context.plan is None:
        return findings
    shot = context.shot(shot_id)
    if shot is None:
        return findings
    responsibility = getattr(shot, "responsibility", None)
    if responsibility is None:
        return findings                       # 未声明镜零行为差

    # 分支一：本镜声明 skip 且该角色全部出场镜都 skip → 若场景仍有主体则矛盾。
    skip_ids: List[str] = []
    if bool(getattr(responsibility, "skip_white_model", False)):
        for character_id in (shot.characters or []):
            shots_with = [
                s for s in context.plan.shots
                if character_id in (s.characters or [])]
            all_skip = bool(shots_with) and all(
                getattr(s.responsibility, "skip_white_model", False)
                for s in shots_with)
            if all_skip:
                skip_ids.append(str(character_id))
    for character_id in skip_ids:
        if context.characters and character_id in context.characters:
            findings.append(_warning(
                "R024", "E_ANIM_001",
                f"{character_id} 声明 skip_white_model（全部出场镜跳过白模），"
                f"但场景仍存在其白模主体对象",
                target=character_id,
                suggestion="删除该角色的主体，或撤销其 skip_white_model 声明"))

    # 分支二：白名单外动画通道（root 的 fcurves data_path 全集）。
    for character_id in (shot.characters or []):
        character = (context.character(character_id)
                     if context.character else None)
        root = getattr(character, "root", None)
        if root is None:
            continue
        action = getattr(getattr(root, "animation_data", None), "action", None)
        if action is None:
            continue
        paths = set()
        for fcurve in getattr(action, "fcurves", []) or []:
            data_path = str(getattr(fcurve, "data_path", "") or "").strip()
            if data_path:
                paths.add(data_path)
        forbidden = sorted(paths - _ANIMATION_WHITELIST)
        if forbidden:
            findings.append(_warning(
                "R024", "E_ANIM_001",
                f"{character_id} 的动画通道超出白名单：{forbidden[:3]}"
                f"{'…' if len(forbidden) > 3 else ''}",
                target=character_id,
                suggestion="白模只允许 root 的 location/rotation_euler 与 "
                           "契约允许的 body_tilt 键表"))
    return findings


def _camera_motion_samples(shot_id: str, context=None) -> List[Dict[str, Any]]:
    """把本镜声明的运镜展开成采样序列（J2，与 I2 同源：``movement_samples`` 产物）。

    无声明运镜/无相机/声明非法时返回空列表（零采样零误报）。起点从场景
    相机的当前机位与朝向推导（look_at 取前方 ``LOOK_AT_DISTANCE``），
    每条声明逐条展开后按帧排序合并。纯计算在 ``cinema/camera_motion``，
    这里只做参数组装——不写关键帧、不留副作用。
    """
    shot = context.shot(shot_id) if context else None
    camera = context.camera_for(shot_id) if context else None
    if shot is None or camera is None:
        return []
    movements = (shot.camera or {}).get("movements") or []
    if not movements:
        return []
    from ..cinema.camera_motion import LOOK_AT_DISTANCE, movement_samples

    position = tuple(float(v) for v in camera.matrix_world.translation)
    rotation = camera.matrix_world.to_quaternion()
    forward = rotation @ Vector((0.0, 0.0, -1.0))
    look_at = tuple(position[i] + float(forward[i]) * LOOK_AT_DISTANCE
                    for i in range(3))
    samples: List[Dict[str, Any]] = []
    for raw in movements:
        if not isinstance(raw, dict):
            continue
        movement = str(raw.get("type") or raw.get("movement") or "").strip()
        amount = float(raw.get("amount") or 0.0)
        start = int(raw.get("start_frame") or 1)
        end = int(raw.get("end_frame") or 0)
        if not movement or end <= start:
            continue
        try:
            plan = movement_samples(
                position, look_at, movement, amount, start, end, samples=3,
                seed=int(raw.get("seed") or 0))
        except ValueError:
            continue            # 声明非法：与 I2 同款跳过，不静默改值
        samples.extend(plan)
    samples.sort(key=lambda item: int(item["frame"]))
    return samples


def _measured_camera(shot_id: str, context=None,
                     *, facing: Optional[Sequence[float]] = None
                     ) -> Optional[Dict[str, Any]]:
    """v1.7 J4（R025）：把本镜实测运镜文字化（I2 的 narrate）＋起终方位。

    数据源与 R021-R023 同源（``_camera_motion_samples``）。无采样/无主体/
    开关关（``_PROMPT_CONFLICT_CHECK`` 默认 False）/``narrate`` 不可用
    （缺模块或例外）时返回 None ⇒ 调用方不出键（零形状差）。
    只产数据、不做语义判断——文本矛盾判断归 review 层的 LLM 裁决。
    """
    if not _PROMPT_CONFLICT_CHECK:
        return None
    samples = _camera_motion_samples(shot_id, context)
    if not samples:
        return None
    context = context or get_context()
    subjects = context.subjects_for(shot_id) if context else []
    if not subjects:
        return None
    anchor = (0.0, 0.0, 0.0)
    root = getattr(subjects[0], "root", None)
    if root is not None:
        anchor = tuple(float(v) for v in root.matrix_world.translation)
        try:
            if facing is None:
                from .character_system.character_factory import get_facing
                facing = tuple(float(v) for v in get_facing(subjects[0]))
        except Exception:
            facing = (0.0, 1.0, 0.0)
    if facing is None:
        facing = (0.0, 1.0, 0.0)
    try:
        from ..cinema.camera_narration import _bearing, narrate
        narration = narrate(samples, anchor, facing)
        start_token = _bearing(anchor, facing, samples[0]["position"])
        end_token = _bearing(anchor, facing, samples[-1]["position"])
    except Exception:
        return None
    if not narration or narration == "固定机位" and len(samples) < 2:
        return None
    if not start_token or not end_token:
        return None
    return {
        "narration": str(narration),
        "start": str(start_token),
        "end": str(end_token),
    }


def _heading_turn_count(samples: Sequence[Dict[str, Any]]) -> int:
    """R021：相邻采样段航向角差（卷绕 ±180°）> ``MOVE_HEADING_TURN_DEG`` 的突变次数。"""
    positions = [sample.get("position") for sample in samples
                 if sample.get("position") is not None]
    headings: List[float] = []
    for index in range(len(positions) - 1):
        dx = float(positions[index + 1][0]) - float(positions[index][0])
        dy = float(positions[index + 1][1]) - float(positions[index][1])
        if abs(dx) + abs(dy) <= 1e-9:
            continue
        headings.append(math.atan2(dy, dx))
    turns = 0
    for previous, current in zip(headings, headings[1:]):
        delta = current - previous
        while delta > math.pi:
            delta -= 2.0 * math.pi
        while delta < -math.pi:
            delta += 2.0 * math.pi
        if abs(delta) > math.radians(MOVE_HEADING_TURN_DEG):
            turns += 1
    return turns


def _roll_flip_frames(samples: Sequence[Dict[str, Any]],
                      subject_pos: Optional[Sequence[float]] = None
                      ) -> List[int]:
    """R022：右向量（视线 × 天顶）在主体相对方位上的投影符号翻转帧号。

    采样没有 up 分量，用右向量等价判定：``r = normalize(look_at − position)
    × ẑ``；视线与 ẑ 夹角 < ``ROLL_DEGENERATE_DEG`` 的帧跳过（退化帧，叉积
    无定义）。无主体方位时按右向量自身的 y 符号（等价于主体在相机正前方）。
    """
    signs: List[float] = []
    flips: List[int] = []
    for sample in samples:
        p, look = sample.get("position"), sample.get("look_at")
        if p is None or look is None:
            continue
        fwd = (float(look[0]) - float(p[0]),
               float(look[1]) - float(p[1]),
               float(look[2]) - float(p[2]))
        length = math.sqrt(sum(c * c for c in fwd))
        if length <= 1e-9:
            continue
        fwd = (fwd[0] / length, fwd[1] / length, fwd[2] / length)
        if fwd[2] > math.cos(math.radians(ROLL_DEGENERATE_DEG)):
            continue                        # 视线几乎沿天顶：退化帧跳过
        right = (fwd[1], -fwd[0])           # fwd × ẑ（x 分量，y 分量）
        if subject_pos is not None:
            dx = float(subject_pos[0]) - float(p[0])
            dy = float(subject_pos[1]) - float(p[1])
            dlen = math.sqrt(dx * dx + dy * dy)
            if dlen <= 1e-9:
                continue
            sign = 1.0 if (right[0] * dx + right[1] * dy) >= 0.0 else -1.0
        else:
            sign = 1.0 if right[1] >= 0.0 else -1.0
        if signs and signs[-1] != sign:
            flips.append(int(sample["frame"]))
        signs.append(sign)
    return flips


def _peak_acceleration(samples: Sequence[Dict[str, Any]], fps: int
                       ) -> Tuple[float, Optional[int]]:
    """R023：位置二阶差分 × fps² 的峰值（**单位 m/s²**，禁止归一化值）。

    返回 ``(峰值, 帧号)``；无二阶差分（采样 <3）或无运动时 ``(0.0, None)``。
    """
    positions = [sample.get("position") for sample in samples
                 if sample.get("position") is not None]
    peak = 0.0
    peak_frame: Optional[int] = None
    factor = float(fps) * float(fps)
    for index in range(1, len(positions) - 1):
        p_prev, p_here, p_next = positions[index - 1], positions[index], positions[index + 1]
        ax = (float(p_next[0]) - 2.0 * float(p_here[0]) + float(p_prev[0])) * factor
        ay = (float(p_next[1]) - 2.0 * float(p_here[1]) + float(p_prev[1])) * factor
        az = (float(p_next[2]) - 2.0 * float(p_here[2]) + float(p_prev[2])) * factor
        magnitude = math.sqrt(ax * ax + ay * ay + az * az)
        if magnitude > peak:
            peak = magnitude
            peak_frame = int(samples[index]["frame"])
    return (peak, peak_frame) if peak > 0.0 else (0.0, None)


def _shot_subject_position(shot_id: str, context=None) -> Optional[Tuple[float, ...]]:
    """本镜主体中心（角色根点均值），供 R022 的投影符号判定；无角色返回 None。"""
    if context is None:
        return None
    roots = []
    for character in context.subjects_for(shot_id) or []:
        root = getattr(character, "root", None)
        if root is not None:
            roots.append(root.matrix_world.translation)
    if not roots:
        return None
    center = sum(roots, Vector()) / len(roots)
    return tuple(float(v) for v in center)


def _check_motion_complexity(shot_id: str, context=None) -> List[AuditError]:
    """R021（warning）：突变数 + 声明运镜条目数 ≥ 复合运动上限 → 建议拆镜。"""
    samples = _camera_motion_samples(shot_id, context)
    if not samples:
        return []
    shot = context.shot(shot_id) if context else None
    declared = len((shot.camera or {}).get("movements") or []) \
        if shot is not None else 0
    turns = _heading_turn_count(samples)
    if turns + declared < _COMPOUND_MOTION_MAX:
        return []
    return [_warning(
        "R021", "E_CAM_001",
        f"{shot_id} 相机轨迹有 {turns} 次 >{MOVE_HEADING_TURN_DEG:.0f}° 航向突变，"
        f"加上 {declared} 条声明运镜（复合 {turns + declared} ≥ "
        f"{_COMPOUND_MOTION_MAX}），建议拆镜",
        target=shot_id,
        suggestion="把大转弯/多次变向拆成独立镜头，每镜一个明确方向")]


def _check_roll_flip(shot_id: str, context=None) -> List[AuditError]:
    """R022（warning）：右向量投影符号翻转（疑似 up 翻转）。"""
    samples = _camera_motion_samples(shot_id, context)
    if not samples:
        return []
    flips = _roll_flip_frames(samples, _shot_subject_position(shot_id, context))
    if not flips:
        return []
    detail = (f"共 {len(flips)} 处" if len(flips) > 1
              else f"翻转帧 {flips[0]}")
    return [_warning(
        "R022", "E_CAM_001",
        f"{shot_id} 相机右向量（视线×天顶）投影符号在 {detail} 翻转，"
        "疑似 up 翻转",
        target=shot_id,
        suggestion="检查相机是否滚转越过天顶；跟拍建议改用斯坦尼康级平稳路径")]


def _check_camera_accel(shot_id: str, context=None) -> List[AuditError]:
    """R023（warning）：相机采样加速度峰值超限（单位 m/s²）。"""
    samples = _camera_motion_samples(shot_id, context)
    if not samples:
        return []
    peak, frame = _peak_acceleration(samples, _ANIMATION_FPS)
    if frame is None or peak <= _CAM_ACCEL_MAX:
        return []
    return [_warning(
        "R023", "E_CAM_001",
        f"{shot_id} 相机采样加速度峰值 {peak:.2f} m/s² 超过 "
        f"{_CAM_ACCEL_MAX:.2f} m/s²（第 {frame} 帧）",
        target=shot_id,
        suggestion="把急推/急移放缓，或拆成两段运镜（阈值待实测校准）")]


def _height_at(shot_id: str, character, context) -> Optional[float]:
    """角色在指定镜头首帧的包围盒世界高度；失败返回 None 且还原帧。"""
    scene = bpy.context.scene
    original = int(scene.frame_current)
    start, _end = shot_frame_span(shot_id, context)
    try:
        if start != original:
            scene.frame_set(start)
            bpy.context.view_layer.update()
        box = _character_aabb(character)
        return float(box.maximum[2] - box.minimum[2]) if box is not None else None
    finally:
        if scene.frame_current != original:
            scene.frame_set(original)
            bpy.context.view_layer.update()


def _obstacles() -> Dict[str, AABB]:
    """墙体与道具的包围盒（按 §21.1 命名约定识别）。"""
    found: Dict[str, AABB] = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        if obj.name.startswith(OBSTACLE_PREFIXES):
            found[obj.name] = _world_aabb(obj)
    return found


def _action_ranges(context) -> Dict[str, List[Tuple[int, int, str]]]:
    """逐角色的全局动作区间：``{character_id: [(start, end, label)]}``。"""
    ranges: Dict[str, List[Tuple[int, int, str]]] = {}
    if context is None or context.plan is None:
        return ranges
    for shot in context.plan.shots:
        start, end = context.schedule.get(shot.shot_id, (1, shot.duration_frames))
        for index, raw in enumerate(shot.actions or [], start=1):
            if not isinstance(raw, dict):
                continue
            character_id = str(raw.get("character_id") or "")
            if not character_id:
                continue
            #: 与构建器**同一个**折帧函数（单一真源）：动作被夹进它自己那一镜，
            #: 否则这里会报出场景里并不存在的"跨镜重叠"（实测 run8：64/64 镜、
            #: 487 条 R003，样例是 shot_055 的动作"溢出"到 shot_056）。
            from ..cinema.schedule import action_frame_window

            absolute_start, absolute_end = action_frame_window(
                start, int(shot.duration_frames), int(raw.get("start_frame") or 1),
                int(raw.get("end_frame") or shot.duration_frames))
            label = f"{shot.shot_id}#{index} {raw.get('action_type')}"
            ranges.setdefault(character_id, []).append(
                (absolute_start, absolute_end, label))
    return ranges


def _overlapping_pairs(items: List[Tuple[int, int, str]]):
    ordered = sorted(items)
    for index, (start_a, end_a, label_a) in enumerate(ordered):
        for start_b, end_b, label_b in ordered[index + 1:]:
            if start_b < end_a and start_b <= end_b:
                yield label_a, label_b


@main_thread_only("check_shot")
def shot_frame_span(shot_id: str, context=None) -> Tuple[int, int]:
    """这一镜在时间轴上的 ``(起, 止)``；拿不到就退回 ``(1, 1)``。

    带运镜的镜头在不同帧上的机位不同，规则必须说明"在**哪一帧**上判"。
    """
    context = context or get_context()
    if context is not None:
        span = context.schedule.get(shot_id)
        if span:
            return int(span[0]), int(span[1])
    return 1, 1


def audit_frames(shot_id: str, context=None) -> List[int]:
    """镜头首 / 中 / 尾三帧（去重，单帧镜头只返回一帧）。"""
    start, end = shot_frame_span(shot_id, context)
    middle = start + max((end - start) // 2, 0)
    return sorted({int(start), int(middle), int(end)})


def screen_facing_for(shot, *, context=None, camera=None):
    """本镜**显式声明**的每个角色在屏幕上的朝向（相机右轴的投影点积）。

    v1.4 §3.4：R012（同框正反打）与新增的 R019（银幕方向连续性）**共用**这一
    份计算，不再各自算一遍局部变量。返回值是 ``{character_id: dot}``：
    ``dot > 0`` 表示角色朝向画面右侧，``< 0`` 朝左，``≈ 0`` 中性。

    只统计 ``shot.characters`` 里**显式声明**、且真的在场景里的角色——
    v1.3 的 R012 走 ``SceneContext.subjects_for``，后者在镜头没写角色时
    回退成整个剧组（X9），于是"没声明角色"的空镜也会被拉进正反打判定。
    """
    from .character_system import get_facing

    if shot is None or context is None:
        return {}
    camera = camera or context.camera_for(getattr(shot, "shot_id", ""))
    if camera is None:
        return {}
    right = camera.matrix_world.to_quaternion() @ Vector((1.0, 0.0, 0.0))
    flat_right = Vector((right.x, right.y, 0.0))
    if flat_right.length <= 1e-6:
        return {}
    flat_right.normalize()
    result: Dict[str, float] = {}
    for character_id in (getattr(shot, "characters", None) or []):
        character = context.character(character_id)
        if character is None:
            continue
        facing = get_facing(character)
        flat = Vector((float(facing[0]), float(facing[1]), 0.0))
        if flat.length <= 1e-6:
            continue
        flat.normalize()
        result[str(character_id)] = flat.dot(flat_right)
    return result


@main_thread_only("continuity_snapshot")
def continuity_snapshot(shot_id: str, context=None) -> Dict[str, Any]:
    """整场连续性快照（v1.7 卡 I3，reference_pack 的 continuity.json 数据源）。

    返回 ``{"shot_id", "left", "right", "facing", "note"}``：屏幕左右分组按
    ``_pair_screen_order`` 的归一化屏幕 X（``x < 0.5`` → left，否则 right），
    facing 与 ``screen_facing_for`` 同源。缺镜头/缺相机不 raise，返回空结构
    （诚实留缺，不猜）。判定落在本镜**首帧**，结束后还原帧号——审核不该
    改变场景状态（与 ``check_shot`` 同一纪律）。
    """
    from .scene_context import get_context

    context = context or get_context()
    snapshot: Dict[str, Any] = {
        "shot_id": shot_id,
        "left": [],
        "right": [],
        "facing": {},
        "note": "",
    }
    if context is None:
        return snapshot
    characters = context.subjects_for(shot_id)
    camera = context.camera_for(shot_id)
    shot = context.shot(shot_id)
    if not characters or camera is None or shot is None:
        return snapshot

    scene = bpy.context.scene
    original_frame = int(scene.frame_current)
    frame_start, _frame_end = shot_frame_span(shot_id, context)
    if frame_start != original_frame:
        scene.frame_set(frame_start)
    bpy.context.view_layer.update()
    try:
        pairs = _pair_screen_order(context, camera, characters[:2])
        left: List[str] = []
        right: List[str] = []
        for character_id, screen_x in pairs:
            if float(screen_x) < 0.5:
                left.append(str(character_id))
            else:
                right.append(str(character_id))
        facing = screen_facing_for(shot, context=context, camera=camera)
        return {
            "shot_id": shot_id,
            "left": left,
            "right": right,
            "facing": {str(key): float(value)
                       for key, value in (facing or {}).items()},
            "note": "",
        }
    finally:
        if scene.frame_current != original_frame:
            scene.frame_set(original_frame)
            bpy.context.view_layer.update()


@main_thread_only("check_shot")
def check_shot(shot_id: str, *, context=None,
               composition_threshold: float = PASS_SCORE,
               strict: bool = False) -> AuditResult:
    """对单个镜头跑全部已实现的 Level 1 规则。"""
    from .cinema_engine import (
        check_camera_neutral,
        evaluate_camera_composition,
    )
    from .scene_context import get_context

    context = context or get_context()
    scene = bpy.context.scene
    findings: List[AuditError] = []
    # v1.3：带运镜的镜头在不同帧上机位不同，规则必须说明判在哪一帧。
    # 判定统一落在**本镜首帧**，构图的通过门槛再额外取首/中/尾的最小值
    # （详见下方），结束后把帧号还原，绝不把审核的副作用留给渲染。
    original_frame = int(scene.frame_current)
    frame_start, frame_end = shot_frame_span(shot_id, context)
    if frame_start != original_frame:
        scene.frame_set(frame_start)
    bpy.context.view_layer.update()

    shot = context.shot(shot_id) if context else None
    camera = context.camera_for(shot_id) if context else None
    shot_type = context.shot_types.get(shot_id, "MS") if context else "MS"

    def finish(result: AuditResult) -> AuditResult:
        """规则评估完必须还原帧号——审核不该改变场景的状态。"""
        if scene.frame_current != original_frame:
            scene.frame_set(original_frame)
            bpy.context.view_layer.update()
        return result

    # 判定必须基于**本镜头的角色**：特写镜头不该因为"另一个角色不在画里"
    # 而被判失败（Phase 5 首次跑 R003 的回归测试时就踩到了这个）。
    characters = []
    if shot is not None and context is not None:
        characters = context.subjects_for(shot_id)
    elif context is not None:
        characters = context.character_list

    # R007 引用完整 ---------------------------------------------------------
    for character_id in (shot.characters if shot else []):
        if context is None or context.character(character_id) is None:
            findings.append(_error(
                "R007", "E_SDL_001", f"镜头引用了不存在的角色 {character_id}",
                target=shot_id, suggestion="改用在场角色，或先把该角色加入场景"))
    if camera is None:
        findings.append(_error(
            "R007", "E_SDL_001", "该镜头没有可用相机", target=shot_id,
            suggestion="用 setup_camera 为该镜头建立机位"))
        return finish(AuditResult.from_findings(findings, target=shot_id))

    # R006 帧范围 -----------------------------------------------------------
    if shot is not None and shot.duration_frames <= 0:
        findings.append(_error(
            "R006", "E_SDL_001",
            f"镜头时长非法：{shot.duration_frames} 帧", target=shot_id,
            suggestion="时长必须为正整数帧"))

    # R001 轴线合规 ---------------------------------------------------------
    neutral_here = False
    if context is not None and context.axis is not None:
        #: **R001 = 观众看到的东西**（v1.9，GLM 5.3 会诊 A2/A3 的落地）：
        #: 判据从"相机在冻结线的哪一侧"换成"**相邻切点上两人的屏幕左右顺序有没有
        #: 在没人看见的情况下翻转**"。理由：前者会随走位脱钩（`long12` 里 26 条
        #: 都是"整场挪到布景另一处、线跟着转"），而后者正是观众真正感知到的量。
        #: 换位若是**看得见**的（两人同框走过去）或中间有 §6.2 的**中性机位**，
        #: 就是合法的轴线重建，不报。
        flip = _screen_polarity_flip(context, camera, shot, characters)
        if flip:
            findings.append(_error(
                "R001", "E_AXIS_001", flip, target=shot_id,
                suggestion="把这次左右互换拍成**看得见的换位**（两人同框时走过去），"
                           "或在中间插一个 §6.2 的中性机位；只挪机位修不动"))
        #: **轴线被重建而没人看见 ⇒ 越轴**（v1.9，会诊 A2 的独立性要求：
        #: 判据不能与被检实现同源）。量的是"**规范首镜线** vs **走位后的派生线**"
        #: 的偏差：构建器可以按派生线摆机位，但"这条重建有没有被拍出来"是它
        #: 无法自证的——桥接事件来自**计划里的走位编排**与**画面上是否中性**。
        rebuild = _axis_rebuild(context, camera)
        if rebuild["angle"] >= AXIS_DRIFT_DEG:
            if rebuild["bridged"]:
                findings.append(_warning(
                    "R001", "E_AXIS_001", rebuild["note"] + "（这次重建是**合法**的："
                    "画面里有换位或中性机位把它交代过去）", target=shot_id,
                    suggestion="确认这是一次有意的轴线重建；不需要改动"))
            else:
                findings.append(_error(
                    "R001", "E_AXIS_001", rebuild["note"] + "，而没有任何镜头把"
                    "这次重建拍出来", target=shot_id,
                    suggestion="把这次重建拍成**看得见的换位**（两人同框时走过去），"
                               "或在中间插一个 §6.2 的中性机位；只挪机位修不动"))
        #: 机位**自己**摆错了也要报（会诊 ②：判据是"机位相对**当前**连线的侧向符号"）。
        #: 这条盯的是求解器兜底、修复工具挪机位、用户手改机位这类**与被检实现无关**
        #: 的越轴——`tests/test_phase4_repair` 的 `setup_camera_fixes_the_violation`
        #: 就是它（相机摆错了，`setup_camera` 得能修好）。
        #: 空镜（无角色）画面里根本没有"两人左右关系"可看，"机位相对当前连线的
        #: 侧别"这条判据对它不成立（G2 v3 实测：shot_001 定场空镜被判 3 次
        #: E_AXIS_001 error，观众却什么都看不到）。v1.6 的"单人镜必须待在已确立
        #: 轴侧"语义不变——只豁免 characters 为空的镜头。
        wrong_side = (_camera_on_wrong_side(context, camera, shot_id)
                      if characters else "")
        if wrong_side:
            findings.append(_error(
                "R001", "E_AXIS_001", wrong_side, target=shot_id,
                suggestion="把相机移到当前连线的另一侧，或插入中性机位过渡"))
        #: 计划期近似 vs 真机位：**不一致要写出来**（会诊 ① 第 5 步）。
        #: 不写出来的话，"精确判据"就只是一条没人复核的暗路——构建器按近似的侧别
        #: 摆了机位，规则按真机位判，两者分道扬镳时观众看不出来、日志也看不出来。
        divergence = _axis_state_divergence(context, shot_id)
        if divergence:
            findings.append(_warning(
                "R001", "E_AXIS_001", divergence, target=shot_id,
                suggestion="这一镜两侧的表不一致：按真机位复核走位（要看得见的换位"
                           "或中性机位），别只信建场景前的近似"))
        # 中性机位（正好落在轴线上）不是越轴：§6.2 的 axis_neutral 卡片把它
        # 定义为合法的跨轴桥梁，而且两人相对而立时单人正反打的机位必然落在
        # 轴线上。v1.2 把它判成 R001 错误，等于让这类镜头永远无法通过审核。
        neutral_note = check_camera_neutral(context.axis, camera)
        if neutral_note:
            neutral_here = True
            findings.append(_warning(
                "R001", "E_AXIS_001", neutral_note, target=shot_id,
                suggestion="需要明确左右关系时把机位移离轴线；"
                           "中性机位适合作为跨轴过渡，不宜连续使用"))


    positions = _character_positions(characters)

    # R008 地面约束 + R005 角色在画 -----------------------------------------
    for character in characters:
        root = getattr(character, "root", None)
        if root is None:
            continue
        if root.matrix_world.translation.z < -GROUND_EPS:
            findings.append(_warning(
                "R008", "E_SPACE_001",
                f"角色 {character.id} 位于地面以下"
                f"（z={root.matrix_world.translation.z:.3f}）",
                target=character.id, suggestion="把角色抬回 z ≥ 0"))
        else:
            # v1.4 BW-4a：R008 必须是**双向**的。旧实现只看 root.z < -0.02，
            # 于是"站立的角色根节点被抬到地面上方"这种**悬空**完全抓不到
            # （BW-4 的现象就是它）。这里用网格的实际最低点判上界。
            box = _character_aabb(character)
            if box is not None and box.minimum[2] > GROUND_EPS:
                findings.append(_warning(
                    "R008", "E_SPACE_001",
                    f"角色 {character.id} 悬空：网格最低点 z="
                    f"{box.minimum[2]:.3f} 高于地面 {GROUND_EPS}",
                    target=character.id,
                    suggestion="把站姿的末关键帧写回绝对地面（z=0）"))
        point = world_to_camera_view(scene, camera,
                                     root.matrix_world.translation
                                     + Vector((0.0, 0.0, 0.9)))
        if not _in_frame(point):
            findings.append(_warning(
                "R005", "E_CAM_001",
                f"角色 {character.id} 不在画面内"
                f"（屏幕 {point.x:.2f}, {point.y:.2f}）",
                target=character.id,
                suggestion="调整机位，或让角色回到画面内"))

    # R004 相机视锥 ---------------------------------------------------------
    center = None
    if positions:
        center = sum(positions, Vector()) / len(positions)
        target_point = world_to_camera_view(scene, camera,
                                            center + Vector((0.0, 0.0, 0.9)))
        if not _in_frame(target_point):
            findings.append(_warning(
                "R004", "E_CAM_001", "镜头对准点落在相机视锥之外",
                target=shot_id, suggestion="重新对准被摄主体"))

    # R012 视线匹配（v1.3）：两人同框时必须形成正反打 ------------------------
    # v1.4 X9：只算**本镜显式声明**的角色（不再回退全剧组）。
    declared = [str(item) for item in (shot.characters if shot else [])]
    facing_map = screen_facing_for(shot, context=context, camera=camera)
    if len(declared) == 2 and len(facing_map) == 2:
        values = [facing_map[cid] for cid in declared]
        if values[0] * values[1] > 0:
            findings.append(_warning(
                "R012", "E_CAM_001",
                f"两人同框但屏幕朝向同号（{values[0]:+.2f} / "
                f"{values[1]:+.2f}），没有形成正反打",
                target=shot_id,
                suggestion="让两人相对而立（face_character），或改用单人镜"))
        heights = []
        for character_id in declared:
            head = getattr(context.character(character_id), "head_pivot", None) \
                if context is not None else None
            if head is not None:
                heights.append(head.matrix_world.translation.z)
        if len(heights) == 2 and abs(heights[0] - heights[1]) > 0.15:
            findings.append(_warning(
                "R012", "E_CAM_001",
                f"两人眼高差 {abs(heights[0] - heights[1]):.2f} m 超过 0.15 m，"
                f"正反打会看出高低差",
                target=shot_id, suggestion="把两人放在同一地面高度上"))

    # R019 银幕方向连续性（v1.4 §3.4，替代死字段 screen_direction） -----------
    # 相邻两镜、**同一角色**、且**两镜都显式声明了该角色**：屏幕朝向符号翻转
    # 且中间没有中性机位 → 观众会看到角色突然换边（越轴）。只在一镜里声明的
    # 角色**不参与**判定（负例见 RK-19）。
    if shot is not None and context is not None and context.plan is not None:
        order = [s.shot_id for s in context.plan.shots]
        if shot_id in order and order.index(shot_id) > 0:
            previous = context.plan.shots[order.index(shot_id) - 1]
            shared = shared_characters(previous.characters or [],
                                       shot.characters or [])
            previous_camera = context.camera_for(previous.shot_id)
            if shared and previous_camera is not None:
                previous_start, _ = shot_frame_span(previous.shot_id, context)
                scene.frame_set(previous_start)
                bpy.context.view_layer.update()
                previous_facing = screen_facing_for(previous, context=context,
                                                    camera=previous_camera)
                previous_neutral = (context.axis is not None
                                    and check_camera_neutral(context.axis,
                                                             previous_camera))
                scene.frame_set(frame_start)
                bpy.context.view_layer.update()
                if not (previous_neutral or neutral_here):
                    for character_id in flipped_screen_directions(
                            previous_facing, facing_map, shared):
                        before = previous_facing[character_id]
                        now = facing_map[character_id]
                        findings.append((_error if strict else _warning)(
                            "R019", "E_AXIS_001",
                            f"{character_id} 的银幕方向在第 "
                            f"{previous.shot_id} 与 {shot_id} 之间翻转"
                            f"（{before:+.2f} → {now:+.2f}），且中间没有"
                            f"中性机位过渡",
                            target=shot_id,
                            suggestion="让该角色保持同一侧，或插入一个"
                                       "中性（骑轴）机位再换边"))

    # R002 空间碰撞（角色 vs 墙体/道具，AABB 膨胀 0.2） --------------------
    obstacles = _obstacles()
    for character in characters:
        box = _character_aabb(character)
        if box is None:
            continue
        for name, obstacle_box in obstacles.items():
            if box.overlaps(obstacle_box, margin=COLLISION_MARGIN):
                findings.append(_error(
                    "R002", "E_SPACE_001",
                    f"角色 {character.id} 与 {name} 发生穿模",
                    target=character.id,
                    suggestion=f"把 {character.id} 移开，或缩小 {name} / 调整摆位"))

    # R003 动作时间轴（同一角色的动作不得重叠） ----------------------------
    for character_id, items in _action_ranges(context).items():
        if shot is not None and shot.characters \
                and character_id not in shot.characters:
            continue
        for label_a, label_b in _overlapping_pairs(items):
            #: **按镜收口**（2026-10-04 实测）：`_action_ranges` 读的是**整份
            #: 计划**，而这里原来只按角色过滤——于是一个镜头里的重叠会被**广播**
            #: 到每一张含该角色的镜头审计里。`long12` 里全片只有 **7 处**重叠，
            #: 却被记成 **312 条 / 64 镜全红**（同一条消息出现在 48 张审计里），
            #: 逐镜通过率直接塌成 0/64，修复回路也被同一句话灌满。
            #: 重叠的两个动作**都在同一镜里**（窗口已被 `action_frame_window`
            #: 夹进各自那一镜，跨镜重叠在构造上不可能），所以只要有一端
            #: 不属于当前镜，这条就不该由这一镜背。
            if shot_id and not any(
                    label.startswith(f"{shot_id}#")
                    for label in (label_a, label_b)):
                continue
            findings.append(_error(
                "R003", "E_SDL_001",
                f"角色 {character_id} 的动作时间重叠：{label_a} 与 {label_b}",
                target=character_id,
                suggestion="同一个角色的动作必须串行，请错开起止帧"))

    # R011 对白容纳：镜头时长必须装得下最晚的一句对白 + 收尾余量 -----------
    if shot is not None and shot.dialogues:
        latest = 0
        for item in shot.dialogues:
            if not isinstance(item, dict):
                continue
            latest = max(latest, int(item.get("end_frame") or 0))
        if latest and latest + DIALOGUE_TAIL_FRAMES > shot.duration_frames:
            findings.append(_error(
                "R011", "E_SDL_001",
                f"对白排到第 {latest} 帧，加上 {DIALOGUE_TAIL_FRAMES} 帧收尾余量"
                f"超出镜头时长 {shot.duration_frames} 帧",
                target=shot_id,
                suggestion="加长该镜头，或把对白前移/删减"))

    # R009 镜头距离与景别匹配 ----------------------------------------------
    frame = SHOT_FRAME.get(str(shot_type).upper())
    if frame is not None and center is not None:
        # v1.3：在**首帧**评估。带运镜的镜头其余帧的机位是刻意变化的，
        # 拿它们去比"景别期望距离"只会把合法的运动判成错误。
        actual = (camera.matrix_world.translation - center).length
        expected = required_distance(frame.frame_height, float(camera.data.lens))
        if expected > 0 and abs(actual - expected) / expected > DISTANCE_TOLERANCE:
            findings.append(_warning(
                "R009", "E_CAM_001",
                f"机位距离 {actual:.2f} 与 {shot_type} 的期望距离 "
                f"{expected:.2f} 相差超过 {DISTANCE_TOLERANCE:.0%}",
                target=shot_id, suggestion="按景别重新取景（setup_camera）"))

    # R010 30° 规则 ---------------------------------------------------------
    if context is not None and context.plan is not None and center is not None:
        order = [s.shot_id for s in context.plan.shots]
        if shot_id in order and order.index(shot_id) > 0:
            previous_id = order[order.index(shot_id) - 1]
            previous_camera = context.camera_for(previous_id)
            if previous_camera is not None:
                # v1.3：两个镜头各自取**自己首帧**的机位。带运镜时拿同一帧
                # 比较等于在比两个不相干的时刻，30° 规则会得出错误结论。
                previous_start, _ = shot_frame_span(previous_id, context)
                scene.frame_set(previous_start)
                bpy.context.view_layer.update()
                previous_position = \
                    previous_camera.matrix_world.translation.copy()
                previous_neutral = (context.axis is not None
                                    and check_camera_neutral(context.axis,
                                                             previous_camera))
                scene.frame_set(frame_start)
                bpy.context.view_layer.update()
                message = thirty_degree_violation(
                    previous_position,
                    camera.matrix_world.translation, center,
                    context.shot_types.get(previous_id, "MS"), shot_type)
                if message:
                    findings.append(_warning(
                        "R010", "E_AXIS_001", message, target=shot_id,
                        suggestion="改变机位角度，或至少变化一档景别"))
                # 连续中性镜头：单次中性是合法桥梁，连着用就没有左右关系了。
                if neutral_here and previous_neutral:
                    findings.append(_warning(
                        "R001", "E_AXIS_001",
                        f"{previous_id} 与 {shot_id} 都是中性机位（落在轴线上），"
                        f"连续使用会让观众失去左右关系的连续性",
                        target=shot_id,
                        suggestion="至少给其中一镜一个明确的轴线侧别"))

    # R020 跨镜比例一致性（v1.7 J1，warning 级） ----------------------------
    # 与首出场镜的包围盒世界高度比对；本镜就是首出场镜时跳过。每角色每镜
    # 至多 1 条；阈值由审核入口经 configure_scale_drift 注入（与 F1 同款）。
    findings.extend(_check_scale_drift(shot_id, context))

    # R021–R023 相机运动复杂度/翻转/加速度（v1.7 J2，warning 级） -----------
    # 三条共用 movement_samples 产物（与 I2 同源）；无声明运镜的镜头零采样
    # 零误报。阈值由审核入口经 configure_camera_limits 注入（照 J1 模式）。
    findings.extend(_check_motion_complexity(shot_id, context))
    findings.extend(_check_roll_flip(shot_id, context))
    findings.extend(_check_camera_accel(shot_id, context))

    # R024 分工矛盾（v1.7 J3，warning 级；声明 skip 仍建主体 / 白名单外通道）
    findings.extend(_check_responsibility(shot_id, context))

    # 构图质量门（§7.1 B3 把构图列为通过条件） -----------------------------
    composition = None
    if characters:
        # v1.3：取首 / 中 / 尾三帧的**最小值**。只看首帧，运镜后段把主体
        # 挤出画面的镜头照样能通过——那正是"运动"最容易出事的地方。
        if frame_start != frame_end:
            scene.frame_set(frame_start)
            bpy.context.view_layer.update()
        worst = None
        for sample in audit_frames(shot_id, context):
            scene.frame_set(sample)
            bpy.context.view_layer.update()
            report = evaluate_camera_composition(camera, characters,
                                                 shot_type=shot_type)
            if worst is None or report.score < worst.score:
                worst = report
        composition = worst
        #: 用户 2026-10-18 裁决：构图分必须**严格高于**阈值，
        #: score == composition_threshold 仍判失败（截至阈值）。
        if composition is not None and composition.score <= composition_threshold:
            detail = "；".join(composition.suggestions[:2]) or "请调整构图"
            findings.append(_error(
                "COMPOSITION", "E_CAM_001",
                f"构图评分 {composition.score:.1f}（首/中/尾最小值）未高于阈值 "
                f"{composition_threshold:.0f}",
                target=shot_id, suggestion=detail))

    #: v1.7 J4（R025）：校验层只产实测数据（measured_camera），语义矛盾判断
    #: 归 review 层（``guard.prompt_conflict_check`` 默认关 ⇒ 这里不出键）。
    measured = _measured_camera(shot_id, context)
    result = AuditResult.from_findings(
        findings, target=shot_id,
        score=composition.score if composition else None)
    result.measured_camera = measured
    return finish(result)

