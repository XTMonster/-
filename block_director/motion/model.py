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

from ..cinema.anchor import DEFAULT_PROFILE as _PROFILE
from ..contracts.enums import ErrorCode

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
    #: v1.5（执行文档 v1.5 / TDD §3.1）：**语义级入场/出场**。它们不是新的
    #: 运动学，"从画外进画"与"走出画面"落到同一条 base 通道上（root.location
    #: ＋ root.rotation_z）。生产者 = 拍点表的 `enter_from`/`exit_frame`，
    #: 起点/终点由 `beat_compiler` 折算成画外锚点坐标后**仍然走 walk_to**；
    #: 这里登记它们，是为了"任何出现在 ACTION_TYPES 里的动作，引擎都演得出来"
    #: ——否则模型在 `actions[]` 里直写一个语义动词，构建期就是
    #: `未知动作类型`（整轮 ERROR，本项目已付过两次代价的形状）。
    "enter_from": LAYER_BASE,
    "exit_frame": LAYER_BASE,
    "turn_body": LAYER_BASE,
    "jump": LAYER_BASE,
    "body_tilt": LAYER_BODY,
    "fall_down": LAYER_BODY,
    "sit": LAYER_BODY,
    "stand": LAYER_BODY,
    #: v1.5：**道具交互**（TDD §4.4）。道具对象自己的关键帧由构建器负责
    #: （`scene_executor` 的 `create_prop` 侧），角色这一侧只需要一次定向的
    #: 上身动作（body 层）——没有第四种手臂通道，所以不定新层。
    "place_prop": LAYER_BODY,
    "pick_up": LAYER_BODY,
    "hand_to": LAYER_BODY,
    "turn_head": LAYER_HEAD,
    "look_at": LAYER_HEAD,
    "nod": LAYER_HEAD,
    "shake_head": LAYER_HEAD,
}

#: v1.5（TDD §3.1）：**语义级**动词的两组。它们的定义登记在本模块（红线 R-7 的
#: 单一真源），`contracts/beats.py` 从 `ACTION_TYPES` 导入整个词表，不另抄一份。
ENTRANCE_ACTIONS: Tuple[str, ...] = ("enter_from", "exit_frame")
PROP_ACTIONS: Tuple[str, ...] = ("place_prop", "pick_up", "hand_to")

#: 全部合法动作类型（单一真源：工具 schema 与校验都从这里取）
ACTION_TYPES: Tuple[str, ...] = tuple(LAYER_OF)

#: **每个动作类型允许的 `params` 键**（单一真源）。
#:
#: 为什么要有这张表：这些键原先只散落在下面的 `params.get(...)` 调用里，
#: 而计划/草案的工具 schema 把 `params` 声明成**自由形状**（`{"type": "object"}`）。
#: 于是模型写一个引擎不认识的键（实测：`body_tilt` 配 `{"amount": 15}`）时，
#: schema 放行、构建期才由 `body_tilt_params()` 报 `E_MOTION_001` ——
#: **整轮真实运行直接变成 ERROR**（§4.4 步骤 2 全白跑）。
#: 把表放到这里之后，schema 与校验都从它渲染：非法键在 **emit 时**就被拒，
#: 由工具错误回给模型重试，而不是把整轮打死。
ACTION_PARAMS: Dict[str, Tuple[str, ...]] = {
    "walk_to": ("speed", "from", "from_", "target_position", "to", "bob"),
    "run_to": ("speed", "from", "from_", "target_position", "to", "bob"),
    #: v1.5 语义级入场/出场：与 walk_to 同一套位置参数（起点/终点），
    #: 起点缺省 = 角色当前位置，终点缺省 = 起点（**不动**，不替 LLM 猜目的地）。
    "enter_from": ("speed", "from", "from_", "target_position", "to", "bob"),
    "exit_frame": ("speed", "from", "from_", "target_position", "to", "bob"),
    #: v1.5 道具交互：`prop` 是**自由字符串**（道具名/锚点名），不是数值；
    #: `angle_deg` 控制角色那一次前倾的幅度（缺省 8°）。
    "place_prop": ("prop", "angle_deg", "toward"),
    "pick_up": ("prop", "angle_deg", "toward"),
    "hand_to": ("prop", "angle_deg", "toward"),
    "turn_body": ("angle_deg", "angle", "degrees"),
    "turn_head": ("angle_deg", "angle", "degrees"),
    "look_at": ("yaw_deg", "pitch_deg"),
    "body_tilt": ("angle_deg", "angle", "degrees", "axis", "toward"),
    "fall_down": ("direction_deg", "drop"),
    "sit": ("drop", "leg_fold_deg", "lean_deg"),
    "stand": ("drop", "leg_fold_deg", "lean_deg"),
    "nod": ("cycles",),
    "shake_head": ("cycles",),
    "jump": ("height", "base_z", "leg_tuck_deg"),
}

#: 全部动作允许的键的并集（给工具 schema 用：声明成 `properties` ＋
#: `additionalProperties: False`，就能在**解析期**挡住"任何动作都不认识的键"）。
ALL_ACTION_PARAM_KEYS: Tuple[str, ...] = tuple(
    sorted({key for keys in ACTION_PARAMS.values() for key in keys}))


def unknown_action_params(kind: str, params) -> List[str]:
    """这个动作类型**不认识**的 `params` 键（空列表 = 合法）。纯函数，可单测。"""
    allowed = ACTION_PARAMS.get(str(kind or "").strip())
    if allowed is None:
        return []
    return sorted(set(params or {}) - set(allowed))


#: 取值是**坐标**的键：必须是 2–3 个数字的序列（`[x, y]` 或 `[x, y, z]`）。
#: 2026-10-07 实测（长剧本那一跑，`docs/evidence/20261007-v15-long/`）：模型把
#: `enter_from` 的 `from` 写成了自由字符串 `"screen_left"`，而当时这几个键在
#: `_NON_NUMERIC_KEYS` 里 ⇒ 解析期判**合法**，一路走到构建期的
#: `motion/model.py::_walk_root` → `float(source[0])` → `float("s")` ⇒ **整轮 64 镜
#: 一起 ERROR**（与 `axis='forward'` 那次是同一个形状：能修的口子留在了解析期之后）。
#: 坐标不是自由文本，所以它必须在解析期就查"是不是坐标"。
_COORDINATE_KEYS = frozenset({"from", "from_", "target_position", "to"})
#: 取值是自由字符串的键：数值与坐标检查对它们都不适用（`prop` 是道具名/锚点名）。
_FREE_STRING_KEYS = frozenset({"prop"})
#: 取值是**闭集**的键（在函数里拼，因为这些表定义在本模块后半段）。
_CLOSED_VALUE_KEYS = frozenset({"speed", "axis"})

#: ``toward`` 的方向词闭集（单一真源）：``_axis_from_toward`` 判域、
#: ``action_param_domains`` 报给提示词，两处不各抄一份。方向量
#: ``[x, y]``/``[x, y, z]`` 也是合法取值（主分量定轴），不在词表里。
TOWARD_WORDS = ("x", "y", "left", "right", "side", "leftward",
                "rightward", "front", "back", "forward")


def action_param_domains() -> Dict[str, Tuple[str, ...]]:
    """闭集取值的键 → 允许的取值。

    **一份真源，两处消费**：解析期的 `action_param_problems` 用它判合法，
    逐镜提示词用它告诉模型能写什么（否则模型写 `axis='forward'` 这种合理同义词，
    到构建期才炸——实测把 64 镜的一整轮打成 ERROR）。
    """
    return {"speed": tuple(sorted(_SPEED_RATE)), "axis": ("x", "y"),
            "toward": TOWARD_WORDS}


def action_param_problems(kind: str, params) -> List[str]:
    """这个动作的 `params` 有什么问题（**键与取值**都查）；空列表 = 合法。

    为什么要有它（2026-10-03 的 64 镜真跑）：`unknown_action_params` 只挡"键不
    认识"。把动作参数表写进提示词之后，草案**从 2 条有效变成 61 条有效**——然后
    整轮死在构建期：

        MotionParamError: E_MOTION_001：body_tilt 的 axis 只能是 x / y（当前 'forward'）

    `axis` 是闭集、`angle_deg` 必须是数字，这些**在解析期就能问**，不该留到构建期
    把 64 镜的计划与 64 条草案一起作废（与本项目已经付过两次代价的"键不认识"
    完全同一个形状）。判据与构建期**同源**：`body_tilt` 直接调它自己的正规化函数，
    `speed` 直接读 `_SPEED_RATE`。
    """
    kind = str(kind or "").strip()
    params = dict(params or {})
    problems: List[str] = []
    unknown = unknown_action_params(kind, params)
    if unknown:
        problems.append(f"{kind} 不认识的参数 {unknown}")
        return problems
    if kind == "body_tilt":
        try:
            body_tilt_params(params)
        except MotionParamError as exc:
            problems.append(str(exc))
        return problems
    for key in sorted(_COORDINATE_KEYS & set(params)):
        problems.extend(coordinate_problems(kind, key, params[key]))
    #: 闭集取值表：`speed` 的取值域直接读构建期用的那张表（单一真源）。
    domains = action_param_domains()
    for key, value in params.items():
        #: prop 类动作的 ``toward`` 走构建期同一条 ``_axis_from_toward`` 判域
        #: （方向量或方向词闭集），不放进下面的"必须是数字"分支——否则会造出
        #: "执行接受、解析拒绝"的假 invalid（v3 真跑 GLM 写 toward='left' 这类
        #: 合法方向词被误拒）。
        if key == "toward" and kind in PROP_ACTIONS:
            continue
        domain = domains.get(key) if key in _CLOSED_VALUE_KEYS else None
        if domain is not None:
            if str(value).strip().lower() not in domain:
                problems.append(
                    f"{kind} 的 {key} 只能是 {'/'.join(domain)}（当前 {value!r}）")
            continue
        if key in _COORDINATE_KEYS or key in _FREE_STRING_KEYS:
            continue
        try:
            float(value)
        except (TypeError, ValueError):
            problems.append(f"{kind} 的 {key} 必须是数字（当前 {value!r}）")
    if kind in PROP_ACTIONS and params.get("toward") is not None:
        try:
            _axis_from_toward(params["toward"])
        except MotionParamError as exc:
            problems.append(str(exc))
        except (TypeError, ValueError):
            problems.append(
                f"{kind} 的 toward 必须是方向量或方向词"
                f"（当前 {params['toward']!r}）")
    return problems


def coordinate_problems(kind: str, key: str, value) -> List[str]:
    """坐标键的取值检查：``[x, y]`` / ``[x, y, z]``，每个分量都得是数字。纯函数。

    与构建期**同源**（`motion/model.py::_walk_root` 直接 `float(p[0])/float(p[1])`），
    所以这里判合法的东西构建期一定吃得住。
    """
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return [f"{kind} 的 {key} 必须是坐标（2–3 个数字的数组，当前 {value!r}）"]
    if not 2 <= len(value) <= 3:
        return [f"{kind} 的 {key} 必须是坐标（2–3 个数字，当前 {list(value)!r}）"]
    for index, item in enumerate(value):
        try:
            float(item)
        except (TypeError, ValueError):
            return [f"{kind} 的 {key} 第 {index + 1} 个分量不是数字（当前 {item!r}）"]
    return []

# §9.7 冲突仲裁表：语义矛盾的动作组合一律拒绝，而不是算出怪动作
FORBIDDEN_PAIRS = frozenset({
    frozenset({"walk_to", "fall_down"}),
    frozenset({"run_to", "fall_down"}),
    frozenset({"walk_to", "jump"}),
    frozenset({"run_to", "jump"}),
    frozenset({"fall_down", "jump"}),
    #: v1.5：入场/出场是**移动**（同一条 base 通道），与"摔/跳"重叠在语义上
    #: 同样荒谬——"一边倒地一边从门外走进来"改时间点也还是荒谬。
    frozenset({"enter_from", "fall_down"}),
    frozenset({"exit_frame", "fall_down"}),
    frozenset({"enter_from", "jump"}),
    frozenset({"exit_frame", "jump"}),
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
        # v1.4 RK-6：行走的起伏必须**非负**——它是"抬脚时身体升高"，不是
        # "身体沉到地面以下"。旧式 ``bob · sin(…)`` 会把根节点压到 −bob
        # （实测 −0.033 m），R008/RK-6 的"行走段 min_z ≥ −0.02"当场失败。
        z = bob * 0.5 * (1.0 - math.cos(2 * math.pi * steps * t))
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
    """高度偏移：坐下是 ``0 → -drop``，站起是 ``-drop → 0``（**绝对落地点**）。

    v1.4 BW-4a：旧的站起分支写的是 ``0 → +drop``（**相对量**），于是"单独一个
    stand"会把根节点抬到地面上方 ``drop``——角色**悬空**。现在站起段的末关键帧
    恒为 ``0``（= 地面），与 sit 的末值 ``-drop`` 首尾相接。
    """
    def pose(frame: int) -> Dict[str, object]:
        t = _ease(_progress(frame, start, end))
        z = -drop * (1.0 - t) if reverse else -drop * t
        return {"root.location": (0.0, 0.0, z)}

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

#: 角色眼睛的高度，用于计算头部俯仰角。v1.4 P10：从 §2.1 的冻结 profile
#: 派生（旧值 1.10 是 v1.3 的几何；``motion/`` 是纯层，不能 import bpy）。
EYE_Z_DEFAULT = _PROFILE.eye_z


class MotionParamError(ValueError):
    """姿态参数不合规（v1.4 BW-1）。

    旧实现遇到不认识的键**静默取默认值**——``take``/``open``/``push`` 写的
    ``{"degrees": 12.0}`` 被完全吃掉，身体倾斜从头到尾没发生过，而没有任何
    地方会报错。现在未知键直接抛出，工具层把它变成一条观察文本回灌给模型。
    """

    def __init__(self, message: str,
                 code: ErrorCode = ErrorCode.MOTION_001) -> None:
        super().__init__(f"{code}：{message}")
        self.code = code


#: v1.4 BW-1：``body_tilt`` 的**允许键表**（同义词 → 规范键）。
#: ``angle_deg`` / ``angle`` / ``degrees`` 是同一个量的三种写法；
#: ``axis`` / ``toward`` 是定向的两种写法。
BODY_TILT_KEYS = ("angle_deg", "angle", "degrees", "axis", "toward")


def _axis_from_toward(toward) -> str:
    """把"朝某个物体倾"的方向量转成旋转轴。

    纯几何、可复现：主分量在 X 上就绕 X 倾，在 Y 上就绕 Y 倾。
    """
    if isinstance(toward, (list, tuple)) and len(toward) >= 2:
        dx = abs(float(toward[0]))
        dy = abs(float(toward[1]))
        return "x" if dx >= dy else "y"
    name = str(toward or "").strip().lower()
    if name in TOWARD_WORDS:
        return "y" if name in ("y", "left", "right", "side",
                               "leftward", "rightward") else "x"
    raise MotionParamError(f"无法理解的 toward 取值：{toward!r}")


def body_tilt_params(params: Dict[str, Any]) -> Tuple[float, str]:
    """把 ``body_tilt`` 的参数正规化成 ``(angle_deg, axis)``。

    未知键 → :class:`MotionParamError`（不静默取默认值）。
    """
    unknown = sorted(set(params or {}) - set(BODY_TILT_KEYS))
    if unknown:
        raise MotionParamError(
            f"body_tilt 不认识的姿态参数：{'、'.join(unknown)}；"
            f"允许的键是 {'、'.join(BODY_TILT_KEYS)}")
    angle = params.get("angle_deg")
    if angle is None:
        angle = params.get("angle")
    if angle is None:
        angle = params.get("degrees", 15.0)
    axis = str(params.get("axis") or "").strip().lower()
    if not axis and params.get("toward") is not None:
        axis = _axis_from_toward(params["toward"])
    if not axis:
        axis = "x"
    if axis not in ("x", "y"):
        raise MotionParamError(f"body_tilt 的 axis 只能是 x / y（当前 {axis!r}）")
    try:
        return float(angle), axis
    except (TypeError, ValueError) as exc:
        raise MotionParamError(f"body_tilt 的角度必须是数字：{angle!r}") from exc


def head_track_angles(origin: Sequence[float], facing: Sequence[float],
                      target: Sequence[float]
                      ) -> Tuple[float, float, str]:
    """目标相对**身体朝向**的头部偏角，返回 ``(yaw_deg, pitch_deg, 说明)``。

    头部只有 ±90°（``HEAD_LIMIT_Z``）与 ±30°（``HEAD_LIMIT_X``），
    所以：

    * 偏角会被钳位到头部活动范围；
    * 目标落在身后（|偏角| > 90°）时给出一句说明——这时必须转身体，
      光扭头是转不过去的（"看向彼此"要由 root 朝向承担主体）。

    纯函数，可单测。bpy 侧只需把当前位置/朝向喂进来。
    """
    ox, oy, oz = (float(origin[0]), float(origin[1]),
                  float(origin[2]) if len(origin) > 2 else 0.0)
    tx, ty, tz = (float(target[0]), float(target[1]),
                  float(target[2]) if len(target) > 2 else oz)
    fx, fy = float(facing[0]), float(facing[1])

    dx, dy = tx - ox, ty - oy
    horizontal = math.hypot(dx, dy)
    if horizontal < 1e-9 and abs(tz - oz) < 1e-9:
        return 0.0, 0.0, "目标与角色重合，头部保持不动"

    # 身体朝向的绝对角度（θ 使 (0,1) 转到 facing，见 utils.geometry）
    if math.hypot(fx, fy) < 1e-9:
        fx, fy = 0.0, 1.0
    body = math.atan2(-fx, fy)
    desired = math.atan2(-dx, dy) if horizontal > 1e-9 else body
    delta = math.atan2(math.sin(desired - body), math.cos(desired - body))

    note = ""
    if abs(delta) > HEAD_LIMIT_Z + 1e-9:
        note = ("目标在身体后方：头部只有 ±90°，请先用 turn_body / "
                "face_character 把身体转过去")
    yaw = _clamp(delta, -HEAD_LIMIT_Z, HEAD_LIMIT_Z)

    pitch = 0.0
    if horizontal > 1e-9:
        pitch = math.atan2(tz - (oz + EYE_Z_DEFAULT), horizontal)
    if abs(pitch) > HEAD_LIMIT_X:
        pitch = _clamp(pitch, -HEAD_LIMIT_X, HEAD_LIMIT_X)
    return math.degrees(yaw), math.degrees(pitch), note


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

    elif kind in ENTRANCE_ACTIONS:
        #: v1.5（TDD §3.1/§4.1）：语义级入场/出场 = 一条 base 通道上的走位。
        #: **终点缺省 = 起点**（即"不动"），而不是原点——不替 LLM 猜目的地
        #: （`shot_builder.action_requests` 对 walk_to 用的是同一纪律：
        #: 缺 target_position 就告警并跳过）。真正的起点/终点由 `beat_compiler`
        #: 按画外锚点折算，那条路走 walk_to（编译目标是 `walk_to`）。
        speed = str(params.get("speed", "walk"))
        rate = _SPEED_RATE.get(speed, 1.0)
        amplitude = _SPEED_AMPLITUDE.get(speed, 25.0)
        source = _pick(params, "from", "from_", default=(0.0, 0.0, 0.0))
        target = _pick(params, "target_position", "to", default=source)
        bob = float(params.get("bob", 0.03))
        add(LAYER_BASE, (CH_ROOT_LOC, CH_ROOT_ROT_Z),
            _walk_root(start, end, source, target, rate, bob, 0.0))
        add(LAYER_LEGS, (CH_LEG_L, CH_LEG_R),
            _leg_swing(start, end, rate, amplitude))

    elif kind in PROP_ACTIONS:
        #: v1.5（TDD §4.4）：道具交互的**角色那一侧**——一次定向的上身动作。
        #: 道具对象的关键帧由构建器写（`scene_executor`），不在纯层里。
        #: `prop` 只作语义标注（缺省空串 = 没有具名道具，不报错）。
        angle = float(params.get("angle_deg", 8.0)) * DEG
        toward = params.get("toward")
        axis = _axis_from_toward(toward) if toward is not None else "x"
        add(LAYER_BODY, (CH_BODY_ROT_X if axis == "x" else CH_BODY_ROT_Y,),
            _body_tilt(start, end, angle, axis))

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
        # v1.4 BW-1：走**允许键表**——`degrees`/`angle`/`angle_deg` 同义，
        # `toward` 与 `axis` 同义；未知键直接报 E_MOTION_001，不静默取默认。
        angle_deg, axis = body_tilt_params(params)
        angle = angle_deg * DEG
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


def stagger_conflicts(requests: Iterable[ActionRequest], *,
                      gap: int = BLEND_FRAMES) -> Tuple[List[ActionRequest],
                                                        List[Dict[str, Any]]]:
    """把**同层重叠**的动作自动错开，返回 ``(调整后的动作, 留痕)``（v1.4 US-17）。

    v1.3 的 ``check_conflicts`` 只会**拒绝**（抛 ``ValueError``），于是"同一角色
    把两个动作挤在同一段帧里"整条镜头直接失败——真实模型排出来的时间轴常常
    差一两帧，人看到的却是"这一镜根本没法渲"。

    这里给的是**确定性错开**：同层动作按起始帧排序，后一个的起点被推到
    ``前一个的结束帧 + gap``；语义禁忌对（§9.7 的 ``FORBIDDEN_PAIRS``）**不
    自动错开**——"边走边倒地"改时间点也还是荒谬，必须由模型换动作。所以：

    * 同层重叠 → 错开并留痕（每条 ``{character_id?, layer, pair, overlap_frames,
      applied_shift}``）；
    * 语义禁忌 → 原样保留，交给 :func:`check_conflicts` 报错。
    """
    items = list(requests)
    adjusted: List[ActionRequest] = []
    events: List[Dict[str, Any]] = []
    by_layer: Dict[str, List[int]] = {}
    for index, item in enumerate(items):
        adjusted.append(item)
        for spec in expand(item):
            by_layer.setdefault(spec.layer, []).append(index)

    for layer, indexes in by_layer.items():
        ordered = sorted(indexes, key=lambda i: adjusted[i].start_frame)
        for previous_index, current_index in zip(ordered, ordered[1:]):
            previous = adjusted[previous_index]
            current = adjusted[current_index]
            if current.start_frame >= previous.end_frame:
                continue
            if frozenset({previous.action_type,
                          current.action_type}) in FORBIDDEN_PAIRS:
                # 语义禁忌（§9.7）不是时间问题：把"边走边摔"挪开几帧依然荒谬，
                # 必须由模型换动作。留给 check_conflicts 报错。
                continue
            overlap = previous.end_frame - current.start_frame
            shift = overlap + max(int(gap), 0)
            adjusted[current_index] = ActionRequest(
                action_type=current.action_type,
                start_frame=current.start_frame + shift,
                end_frame=current.end_frame + shift,
                params=dict(current.params or {}),
                character_id=current.character_id,
                action_id=current.action_id,
            )
            events.append({
                "layer": layer,
                "character_id": str(current.character_id
                                    or (current.params or {}).get(
                                        "character_id") or ""),
                "pair": [previous.action_type, current.action_type],
                "overlap_frames": int(overlap),
                "applied_shift": int(shift),
                "frame": int(current.start_frame),
            })
    return adjusted, events


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
    #: 冻结基线必须**逐 (层, 动作)** 存。一个请求会展开成好几个层的 spec，
    #: 它们共用同一个 ``action_id``（``stand`` → base + legs + body）——只按
    #: ``action_id`` 存的话，**先被遍历到的那个层**会替其它层冻住基线，
    #: 于是 base 层的 ``root.location`` 在别的层里查不到，``_zero_like`` 把
    #: 角色瞬移到世界原点（实测 2026-10-03：`伊恩` 一整天站在 (0,0,0)，
    #: 与 `米迦尔` 重叠；`stand` 还会把根节点抬到地面上方 drop —— 正是
    #: BW-4a 修过的"悬空"从另一条路径上复发）。
    frozen_base: Dict[Tuple[str, str], Dict[str, object]] = {}

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
                key = (spec.layer, spec.action_id)
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
            #: **逐通道**累积，而不是"用本帧算出的通道整份替换层状态"。
            #: v1.4 缺陷（2026-10-03 长剧本真跑暴露）：``turn_body`` 只写
            #: ``root.rotation_z``，替换式写法会把该层的 ``root.location``
            #: 从状态里删掉；此后 ``sit``/``stand``/``walk_to`` 冻结接管时
            #: 读到的基线里没有摆位，于是角色被瞬移到世界原点——两人重叠、
            #: 构图门整片判红。未被本帧任何动作写入的通道必须**原样带过**。
            layer_state[layer] = {**current, **composed}
            frame_pose.update(composed)
        trace[frame] = frame_pose
    return trace
