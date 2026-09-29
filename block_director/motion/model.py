"""动作库与动作混合的纯计算模型（执行文档 v1.2 §9.6 / §9.7）。

设计要点：

1. **一个动作会展开成多条"分层轨道"**。``walk_to`` 既要平移根节点（base 层）
   又要摆动双腿（legs 层），展开后各层互不写同一通道，跨层合成就退化成
   简单的通道并集——这正是 §9.7"不同层可同时播放"能成立的原因。
2. **同层动作串行**，相邻动作在 ``BLEND_FRAMES`` 帧内交叉淡化（权重线性
   归一化），对应 §9.7 的"6 帧交叉淡入淡出"。
3. **冲突是语义问题，不是数值问题**。"边走边倒地"数值上完全可算，但语义
   荒谬，所以由 §9.7 的冲突表显式拒绝。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

FPS = 24
BLEND_FRAMES = 6
DEG = math.pi / 180.0

# ---------------------------------------------------------------- 通道与层
CH_ROOT_LOC = "root.location"
CH_ROOT_ROT_Z = "root.rotation_z"
CH_BODY_ROT_X = "body.rotation_x"
CH_BODY_ROT_Y = "body.rotation_y"
CH_HEAD_ROT_X = "head.rotation_x"
CH_HEAD_ROT_Z = "head.rotation_z"
CH_LEG_L = "leg.L.rotation_x"
CH_LEG_R = "leg.R.rotation_x"

LAYER_BASE = "base"
LAYER_BODY = "body"
LAYER_HEAD = "head"
LAYER_LEGS = "legs"

ALL_LAYERS = (LAYER_BASE, LAYER_BODY, LAYER_HEAD, LAYER_LEGS)

CHANNEL_OWNER: Dict[str, str] = {
    CH_ROOT_LOC: LAYER_BASE,
    CH_ROOT_ROT_Z: LAYER_BASE,
    CH_BODY_ROT_X: LAYER_BODY,
    CH_BODY_ROT_Y: LAYER_BODY,
    CH_HEAD_ROT_X: LAYER_HEAD,
    CH_HEAD_ROT_Z: LAYER_HEAD,
    CH_LEG_L: LAYER_LEGS,
    CH_LEG_R: LAYER_LEGS,
}

# §9.6 的动作 → 主层（用于同层串行判定与冲突提示）
LAYER_OF: Dict[str, str] = {
    "walk_to": LAYER_BASE,
    "run_to": LAYER_BASE,
    "turn_body": LAYER_BASE,
    "jump": LAYER_BASE,
    "body_tilt": LAYER_BODY,
    "fall_down": LAYER_BODY,
    "sit": LAYER_BODY,
    "stand": LAYER_BODY,
    "turn_head": LAYER_HEAD,
    "look_at": LAYER_HEAD,
    "nod": LAYER_HEAD,
    "shake_head": LAYER_HEAD,
}

#: 全部合法动作类型（单一真源：工具 schema 与校验都从这里取）
ACTION_TYPES: Tuple[str, ...] = tuple(LAYER_OF)

# §9.7 冲突仲裁表：语义矛盾的动作组合一律拒绝，而不是算出怪动作
FORBIDDEN_PAIRS = frozenset({
    frozenset({"walk_to", "fall_down"}),
    frozenset({"run_to", "fall_down"}),
    frozenset({"walk_to", "jump"}),
    frozenset({"run_to", "jump"}),
    frozenset({"fall_down", "jump"}),
})

HEAD_LIMIT_Z = 90 * DEG      # §9.3：头部水平 ±90°
HEAD_LIMIT_X = 30 * DEG      # §9.3：点头 ±30°


# ---------------------------------------------------------------- 基础工具
def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease(t: float) -> float:
    """smoothstep：缓入缓出（§9.7 中间段 BEZIER EASE_IN_OUT 的数值等价）。"""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _progress(frame: int, start: int, end: int) -> float:
    if end <= start:
        return 1.0
    return _clamp((frame - start) / float(end - start), 0.0, 1.0)


def _pick(params: Dict, *names: str, default=None):
    """取参数时容忍 ``from`` / ``from_`` 这类写法（``from`` 是关键字）。"""
    for name in names:
        if name in params and params[name] is not None:
            return params[name]
    return default


@dataclass
class ActionRequest:
    """一个高层动作请求（LLM/剧本层面的表述）。"""

    action_type: str
    start_frame: int
    end_frame: int
    params: Dict = field(default_factory=dict)
    character_id: str = ""
    action_id: str = ""

    @property
    def layer(self) -> str:
        return LAYER_OF.get(self.action_type, LAYER_BASE)


@dataclass
class MotionSpec:
    """一条分层轨道：在 [start, end] 帧上给若干通道提供数值。"""

    action_type: str
    layer: str
    channels: Tuple[str, ...]
    start_frame: int
    end_frame: int
    pose_fn: Callable[[int], Dict[str, object]]
    blend_in: int = BLEND_FRAMES
    blend_out: int = BLEND_FRAMES
    action_id: str = ""


# ---------------------------------------------------------------- 姿态函数
def _walk_root(start: int, end: int, source: Sequence[float],
               target: Sequence[float], rate: float, bob: float,
               lean: float) -> Callable[[int], Dict[str, object]]:
    sx, sy = float(source[0]), float(source[1])
    tx, ty = float(target[0]), float(target[1])
    dx, dy = tx - sx, ty - sy
    distance = math.hypot(dx, dy)
    # 角色正面是局部 +Y，绕 Z 旋转 θ 后世界朝向为 (-sin θ, cos θ)；
    # 要让朝向等于移动方向 (dx, dy)，θ 必须取 atan2(-dx, dy)。
    # v1.2 用的是 atan2(dx, dy)，会把 X 分量镜像，于是目标带 X 偏移时
    # 角色"倒着走"（面朝运动的反方向）。与 facing_to_rotation_z 同源修正。
    facing = math.atan2(-dx, dy) if distance > 1e-9 else None
    span = max(end - start, 1)
    steps = max(span / FPS * rate, 0.5)

    def pose(frame: int) -> Dict[str, object]:
        t = _progress(frame, start, end)
        z = bob * math.sin(2 * math.pi * steps * t)
        values: Dict[str, object] = {"root.location": (_lerp(sx, tx, t),
                                                       _lerp(sy, ty, t), z)}
        if facing is not None:
            # 面朝方向也在动作内缓入：所有姿态函数都必须从"中立 0"起步，
            # 否则接管冻结语义会把它当成"本来就是这个角度"而抵消掉。
            values[CH_ROOT_ROT_Z] = facing * _ease(t)
        return values

    return pose


def _leg_swing(start: int, end: int, rate: float,
               amplitude_deg: float) -> Callable[[int], Dict[str, object]]:
    span = max(end - start, 1)
    steps = max(span / FPS * rate, 0.5)
    amplitude = amplitude_deg * DEG

    def pose(frame: int) -> Dict[str, object]:
        t = _progress(frame, start, end)
        angle = amplitude * math.sin(2 * math.pi * steps * t)
        return {CH_LEG_L: angle, CH_LEG_R: -angle}

    return pose


def _root_rotation(start: int, end: int, angle: float,
                   use_absolute: bool) -> Callable[[int], Dict[str, object]]:
    def pose(frame: int) -> Dict[str, object]:
        t = _ease(_progress(frame, start, end))
        return {CH_ROOT_ROT_Z: angle * t}

    return pose


def _body_tilt(start: int, end: int, angle: float,
               axis: str) -> Callable[[int], Dict[str, object]]:
    channel = CH_BODY_ROT_X if axis == "x" else CH_BODY_ROT_Y

    def pose(frame: int) -> Dict[str, object]:
        t = _ease(_progress(frame, start, end))
        return {channel: angle * t}

    return pose


def _fall_down(start: int, end: int,
               direction_deg: float) -> Callable[[int], Dict[str, object]]:
    """三阶段：失稳（0→20%）→ 倒地（20%→70%）→ 稳定（70%→100%）。"""
    total = max(end - start, 1)
    stages = ((0.0, 0.2, 0.0, 0.25), (0.2, 0.7, 0.25, 1.0), (0.7, 1.0, 1.0, 1.0))

    def pose(frame: int) -> Dict[str, object]:
        t = _progress(frame, start, end)
        for lo, hi, a, b in stages:
            if lo <= t <= hi:
                local = (t - lo) / max(hi - lo, 1e-9)
                amount = _lerp(a, b, _ease(local))
                break
        else:
            amount = 1.0
        return {CH_BODY_ROT_X: math.radians(direction_deg) * amount}

    return pose


def _root_drop(start: int, end: int, drop: float,
               reverse: bool = False) -> Callable[[int], Dict[str, object]]:
    """高度偏移：坐下是 ``0 → -drop``，站起是 ``0 → +drop``。

    两者都是**相对**量——配合 compose 的接管冻结语义，先 sit 后 stand
    会精确回到地面，而不是各自从 0 重算。
    """
    def pose(frame: int) -> Dict[str, object]:
        t = _ease(_progress(frame, start, end))
        return {"root.location": (0.0, 0.0, (drop if reverse else -drop) * t)}

    return pose


def _leg_fold(start: int, end: int, angle_deg: float,
              reverse: bool = False) -> Callable[[int], Dict[str, object]]:
    """腿部收放：坐下折起 ``0 → +angle``，站起放下 ``0 → -angle``。"""
    angle = angle_deg * DEG

    def pose(frame: int) -> Dict[str, object]:
        t = _ease(_progress(frame, start, end))
        signed = -angle if reverse else angle
        return {CH_LEG_L: signed * t, CH_LEG_R: signed * t}

    return pose


def _leg_tuck(start: int, end: int,
              angle_deg: float) -> Callable[[int], Dict[str, object]]:
    """跳跃收腿：半程收起、落地放回。"""
    angle = angle_deg * DEG

    def pose(frame: int) -> Dict[str, object]:
        t = _progress(frame, start, end)
        value = angle * math.sin(math.pi * t)
        return {CH_LEG_L: value, CH_LEG_R: value}

    return pose


def _head_track(start: int, end: int, yaw: float,
                pitch: float) -> Callable[[int], Dict[str, object]]:
    def pose(frame: int) -> Dict[str, object]:
        t = _ease(_progress(frame, start, end))
        return {CH_HEAD_ROT_Z: _clamp(yaw * t, -HEAD_LIMIT_Z, HEAD_LIMIT_Z),
                CH_HEAD_ROT_X: _clamp(pitch * t, -HEAD_LIMIT_X, HEAD_LIMIT_X)}

    return pose


def _head_oscillate(start: int, end: int, cycles: int, amplitude_deg: float,
                    channel: str) -> Callable[[int], Dict[str, object]]:
    amplitude = amplitude_deg * DEG
    limit = HEAD_LIMIT_X if channel == CH_HEAD_ROT_X else HEAD_LIMIT_Z

    def pose(frame: int) -> Dict[str, object]:
        t = _progress(frame, start, end)
        angle = amplitude * math.sin(2 * math.pi * cycles * t)
        return {channel: _clamp(angle, -limit, limit)}

    return pose


def _jump_root(start: int, end: int, height: float,
               base_z: float) -> Callable[[int], Dict[str, object]]:
    def pose(frame: int) -> Dict[str, object]:
        t = _progress(frame, start, end)
        z = base_z + height * math.sin(math.pi * t)
        return {"root.location": (0.0, 0.0, z)}

    return pose


# ---------------------------------------------------------------- 动作展开
_SPEED_RATE = {"walk": 1.0, "run": 2.0}
_SPEED_AMPLITUDE = {"walk": 25.0, "run": 30.0}


def expand(request: ActionRequest) -> List[MotionSpec]:
    """把一个动作展开成分层轨道（§9.6/§9.7 的实现基础）。"""
    kind = request.action_type
    start, end = int(request.start_frame), int(request.end_frame)
    params = dict(request.params or {})
    action_id = request.action_id or f"{kind}_{start}"
    specs: List[MotionSpec] = []

    def add(layer: str, channels: Sequence[str], pose_fn,
            blend_in: int = BLEND_FRAMES,
            blend_out: int = BLEND_FRAMES) -> None:
        specs.append(MotionSpec(action_type=kind, layer=layer,
                                channels=tuple(channels), start_frame=start,
                                end_frame=end, pose_fn=pose_fn,
                                blend_in=blend_in, blend_out=blend_out,
                                action_id=action_id))

    if kind in ("walk_to", "run_to"):
        speed = str(params.get("speed", "walk" if kind == "walk_to" else "run"))
        rate = _SPEED_RATE.get(speed, 1.0)
        amplitude = _SPEED_AMPLITUDE.get(speed, 25.0)
        source = _pick(params, "from", "from_", default=(0.0, 0.0, 0.0))
        target = _pick(params, "target_position", "to", default=(0.0, 0.0, 0.0))
        bob = float(params.get("bob", 0.03)) * (1.5 if kind == "run_to" else 1.0)
        add(LAYER_BASE, (CH_ROOT_LOC, CH_ROOT_ROT_Z),
            _walk_root(start, end, source, target, rate, bob, 0.0))
        add(LAYER_LEGS, (CH_LEG_L, CH_LEG_R),
            _leg_swing(start, end, rate, amplitude))
        if kind == "run_to":
            add(LAYER_BODY, (CH_BODY_ROT_X,),
                _body_tilt(start, end, 10.0 * DEG, "x"))

    elif kind == "turn_body":
        angle = float(params.get("angle_deg", 90.0)) * DEG
        add(LAYER_BASE, (CH_ROOT_ROT_Z,), _root_rotation(start, end, angle, True))

    elif kind == "turn_head":
        yaw = _clamp(float(params.get("angle_deg", 45.0)) * DEG,
                     -HEAD_LIMIT_Z, HEAD_LIMIT_Z)
        add(LAYER_HEAD, (CH_HEAD_ROT_Z,), _head_track(start, end, yaw, 0.0))

    elif kind == "look_at":
        yaw = _clamp(float(params.get("yaw_deg", 30.0)) * DEG,
                     -HEAD_LIMIT_Z, HEAD_LIMIT_Z)
        pitch = _clamp(float(params.get("pitch_deg", 0.0)) * DEG,
                       -HEAD_LIMIT_X, HEAD_LIMIT_X)
        add(LAYER_HEAD, (CH_HEAD_ROT_X, CH_HEAD_ROT_Z),
            _head_track(start, end, yaw, pitch))

    elif kind == "body_tilt":
        axis = str(params.get("axis", "x")).lower()
        angle = float(params.get("angle_deg", 15.0)) * DEG
        add(LAYER_BODY, (CH_BODY_ROT_X if axis == "x" else CH_BODY_ROT_Y,),
            _body_tilt(start, end, angle, axis))

    elif kind == "fall_down":
        direction = float(params.get("direction_deg", 90.0))
        drop = float(params.get("drop", 0.35))
        add(LAYER_BODY, (CH_BODY_ROT_X,), _fall_down(start, end, direction))
        add(LAYER_BASE, (CH_ROOT_LOC,), _root_drop(start, end, drop))

    elif kind in ("sit", "stand"):
        drop = float(params.get("drop", 0.2))
        fold = float(params.get("leg_fold_deg", 45.0))
        lean = float(params.get("lean_deg", 5.0))
        standing_up = kind == "stand"
        add(LAYER_BASE, (CH_ROOT_LOC,),
            _root_drop(start, end, drop, reverse=standing_up))
        add(LAYER_LEGS, (CH_LEG_L, CH_LEG_R),
            _leg_fold(start, end, fold, reverse=standing_up))
        add(LAYER_BODY, (CH_BODY_ROT_X,),
            _body_tilt(start, end, lean * DEG * (1.0 if not standing_up else -1.0), "x"))

    elif kind == "nod":
        cycles = int(params.get("cycles", 2))
        add(LAYER_HEAD, (CH_HEAD_ROT_X,),
            _head_oscillate(start, end, cycles, 10.0, CH_HEAD_ROT_X))

    elif kind == "shake_head":
        cycles = int(params.get("cycles", 2))
        add(LAYER_HEAD, (CH_HEAD_ROT_Z,),
            _head_oscillate(start, end, cycles, 15.0, CH_HEAD_ROT_Z))

    elif kind == "jump":
        height = float(params.get("height", 0.3))
        base_z = float(params.get("base_z", 0.0))
        tuck = float(params.get("leg_tuck_deg", 20.0))
        add(LAYER_BASE, (CH_ROOT_LOC,), _jump_root(start, end, height, base_z))
        add(LAYER_LEGS, (CH_LEG_L, CH_LEG_R),
            _leg_tuck(start, end, tuck))

    else:
        raise ValueError(f"未知动作类型: {kind}")

    return specs


# ---------------------------------------------------------------- 冲突与合成
def check_conflicts(requests: Iterable[ActionRequest]) -> List[str]:
    """按 §9.7 仲裁表返回冲突说明；空列表表示可安全排布。"""
    items = list(requests)
    problems: List[str] = []

    for i, a in enumerate(items):
        for b in items[i + 1:]:
            pair = frozenset({a.action_type, b.action_type})
            # 语义矛盾的组合只有在**时间上重叠**时才是真冲突；
            # §9.7 给的补救方式本身就是"先结束一个再做另一个"。
            overlaps = (a.start_frame < b.end_frame and b.start_frame < a.end_frame)
            if pair in FORBIDDEN_PAIRS and overlaps:
                problems.append(
                    f"{a.action_type}({a.start_frame}-{a.end_frame}) 与 "
                    f"{b.action_type}({b.start_frame}-{b.end_frame}) 语义冲突："
                    f"请先结束其中一个动作，或改用兼容动作")

    # 同层串行：同层动作的时间轴不得重叠（blend 窗口不允许重叠到数据竞争）
    by_layer: Dict[str, List[ActionRequest]] = {}
    for item in items:
        for spec in expand(item):
            by_layer.setdefault(spec.layer, []).append(item)
    for layer, entries in by_layer.items():
        ordered = sorted({id(e): e for e in entries}.values(),
                         key=lambda e: e.start_frame)
        for previous, current in zip(ordered, ordered[1:]):
            # 同层必须**顺序**执行：后一个动作从冻结的层状态接管，
            # 因此两条动作的生效区间不得相互穿插。
            if current.start_frame < previous.end_frame:
                problems.append(
                    f"{layer} 层动作时间重叠：{previous.action_type}"
                    f"({previous.start_frame}-{previous.end_frame}) 与 "
                    f"{current.action_type}({current.start_frame}-{current.end_frame})，"
                    f"同层动作必须串行；动作结束后仍有 {BLEND_FRAMES} 帧"
                    f"的交叉淡化窗口用于平滑接管")
    return problems


def _zero_like(value: object) -> object:
    return tuple(0.0 for _ in value) if isinstance(value, tuple) else 0.0


def _weight_at(spec: MotionSpec, frame: int) -> float:
    """动作在其尾窗（blend_out）内逐渐让位给下一个动作。

    头窗刻意**不**淡化：后来的动作必须从冻结的层状态接管，
    否则会在起手处把前面动作的成果抹掉。
    """
    if spec.start_frame <= frame <= spec.end_frame:
        return 1.0
    if spec.end_frame < frame <= spec.end_frame + spec.blend_out and spec.blend_out > 0:
        remaining = (spec.end_frame + spec.blend_out) - frame
        return max(remaining / spec.blend_out, 1e-6)
    return 0.0


def compose(requests: Iterable[ActionRequest],
            base_pose: Optional[Dict[str, object]] = None
            ) -> Dict[int, Dict[str, object]]:
    """把一组动作合成为逐帧姿态：``{frame: {channel: value}}``。

    核心语义是**接管冻结**：当一个动作在某层生效时，它记住该层此前的姿态
    作为基线，其后输出 ``基线 + (当前姿态 - 起手姿态)``。这样多个动作叠在
    同一层上会自然累积（转身 90° 再转身 90° = 180°），而不是各自从 0 重来。

    ``base_pose`` 是该角色**当前的真实姿态**（比如摆位、既有朝向）。
    不传就从零开始；传了才能保证"坐下"不会把角色从 (0.75,0,0) 拽回原点。
    """
    specs: List[MotionSpec] = []
    for request in requests:
        specs.extend(expand(request))
    if not specs:
        return {}

    start = min(spec.start_frame for spec in specs)
    end = max(spec.end_frame + spec.blend_out for spec in specs)
    by_layer: Dict[str, List[MotionSpec]] = {}
    for spec in specs:
        by_layer.setdefault(spec.layer, []).append(spec)

    for layer, layer_specs in by_layer.items():
        for spec in layer_specs:
            for channel in spec.channels:
                owner = CHANNEL_OWNER.get(channel)
                if owner is not None and owner != layer:
                    raise ValueError(
                        f"通道 {channel} 属于 {owner} 层，却被 {layer} 层的 "
                        f"{spec.action_type} 写入")

    trace: Dict[int, Dict[str, object]] = {}
    layer_state: Dict[str, Dict[str, object]] = {layer: {} for layer in by_layer}
    if base_pose:
        for channel, value in base_pose.items():
            owner = CHANNEL_OWNER.get(channel)
            if owner in layer_state:
                layer_state[owner][channel] = value
    frozen_base: Dict[str, Dict[str, object]] = {}

    for frame in range(start, end + 1):
        frame_pose: Dict[str, object] = {}
        for layer, layer_specs in by_layer.items():
            current = layer_state[layer]
            active = [(spec, _weight_at(spec, frame)) for spec in layer_specs
                      if _weight_at(spec, frame) > 0]
            if not active:
                continue
            acc: Dict[str, object] = {}
            total: Dict[str, float] = {}
            for spec, weight in active:
                key = spec.action_id
                if key not in frozen_base:
                    frozen_base[key] = dict(current)      # 冻结接管前的层状态
                base = frozen_base[key]
                raw = spec.pose_fn(frame)
                raw_start = spec.pose_fn(spec.start_frame)
                for channel, value in raw.items():
                    baseline = base.get(channel, _zero_like(value))
                    origin = raw_start.get(channel, _zero_like(value))
                    if isinstance(value, tuple):
                        absolute = tuple(b + v - o
                                         for b, v, o in zip(baseline, value, origin))  # type: ignore[arg-type]
                    else:
                        absolute = baseline + value - origin  # type: ignore[operator]
                    previous = acc.get(channel)
                    if previous is None:
                        acc[channel] = (tuple(v * weight for v in absolute)
                                        if isinstance(absolute, tuple)
                                        else absolute * weight)
                    elif isinstance(absolute, tuple):
                        acc[channel] = tuple(p + v * weight
                                             for p, v in zip(previous, absolute))  # type: ignore[arg-type]
                    else:
                        acc[channel] = previous + absolute * weight  # type: ignore[operator]
                    total[channel] = total.get(channel, 0.0) + weight

            composed: Dict[str, object] = {}
            for channel, value in acc.items():
                weight_sum = total.get(channel, 0.0)
                if weight_sum <= 0:
                    composed[channel] = value
                elif isinstance(value, tuple):
                    composed[channel] = tuple(v / weight_sum for v in value)  # type: ignore[union-attr]
                else:
                    composed[channel] = value / weight_sum  # type: ignore[operator]
            layer_state[layer] = composed
            frame_pose.update(composed)
        trace[frame] = frame_pose
    return trace
