"""180° 轴线与 30° 规则（执行文档 v1.2 §10.3 / R001 / R010）。

坐标系 Z-up：轴线方向与"起点到相机"向量做叉积，取 **Z 分量**的符号即可
判定相机在轴线哪一侧——这正是 §10.3 的算法。本模块把它做成纯函数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from ..contracts.enums import SHOT_TYPES

EPS = 1e-9

SIDE_POSITIVE = 1
SIDE_NEGATIVE = -1
SIDE_UNKNOWN = 0

#: 机位相对已确立轴线的三种状态（§10.3 / R001）
AXIS_CORRECT = "correct"
AXIS_NEUTRAL = "neutral"
AXIS_CROSSED = "crossed"

# §10.5 的景别由紧到松，用于 R010 的"景别变化至少一档"
SHOT_SIZE_ORDER: Tuple[str, ...] = ("ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS")

# R010：相邻镜头机位角差小于该值时，必须有景别变化
MIN_ANGLE_DEG = 30.0

#: 规范首镜线与走位派生线相差多少度就认为"轴线被走位重建了"（R001，v1.9）。
#: 放在这里而不是规则里：它是**判据本身的参数**，纯函数与规则共用同一个数。
AXIS_DRIFT_DEG = 30.0

#: 配对连线在某一镜里转过小于这个角度时当作数值噪声（不产生换位事件）。
CROSSING_MIN_DEG = 0.5


@dataclass(frozen=True)
class Axis:
    """一条轴线：两人连线 + 已确立的基准侧。"""

    start: Tuple[float, float]
    end: Tuple[float, float]
    established_side: int = SIDE_POSITIVE
    left_label: str = ""
    right_label: str = ""

    @property
    def direction(self) -> Tuple[float, float]:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        norm = math.hypot(dx, dy)
        if norm < EPS:
            return (0.0, 0.0)
        return (dx / norm, dy / norm)

    @property
    def length(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    def side_of(self, point: Sequence[float]) -> int:
        """返回点在轴线的哪一侧：+1 / -1 / 0（落在轴线上）。"""
        dx, dy = self.direction
        if dx == 0.0 and dy == 0.0:
            return SIDE_UNKNOWN
        tx = float(point[0]) - self.start[0]
        ty = float(point[1]) - self.start[1]
        cross_z = dx * ty - dy * tx
        if cross_z > EPS:
            return SIDE_POSITIVE
        if cross_z < -EPS:
            return SIDE_NEGATIVE
        return SIDE_UNKNOWN

    def is_correct_side(self, point: Sequence[float]) -> bool:
        return self.side_of(point) == self.established_side

    def to_dict(self) -> Dict[str, Any]:
        return {"start": list(self.start), "end": list(self.end),
                "established_side": self.established_side,
                "left_label": self.left_label, "right_label": self.right_label}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Axis":
        return cls(start=tuple(data["start"]), end=tuple(data["end"]),
                   established_side=int(data.get("established_side", SIDE_POSITIVE)),
                   left_label=str(data.get("left_label", "")),
                   right_label=str(data.get("right_label", "")))


def axis_from_points(a: Sequence[float], b: Sequence[float],
                     a_label: str = "", b_label: str = "") -> Axis:
    """用两点连线构造轴线（尚未确立基准侧）。"""
    return Axis(start=(float(a[0]), float(a[1])),
                end=(float(b[0]), float(b[1])),
                left_label=a_label, right_label=b_label)


def axis_for_speakers(positions: Sequence[Tuple[Sequence[float], str]]
                      ) -> Optional[Axis]:
    """以当前说话的两人为轴线；第三人及以后不参与（§10.3 多人轴线）。"""
    if len(positions) < 2:
        return None
    (first, first_label), (second, second_label) = positions[0], positions[1]
    axis = axis_from_points(first, second, first_label, second_label)
    return axis if axis.length > EPS else None


@dataclass(frozen=True)
class CrossingEvent:
    """一次配对连线的变化（纯计划推算的结果）。

    * `rotated_deg`：这一镜里连线转过的角度（大 = 走位把它重建了）；
    * `flip`：转过 90° 以上 ⇒ **左右真的换了个儿**（侧别要翻）；
    * `visible`：这一镜里两人**同框**（观众看得见这次变化 ⇒ 合法桥接）。
    """

    shot_id: str
    visible: bool          # 变化是不是发生在**两人同框**的那一镜里
    people: Tuple[str, str]
    rotated_deg: float = 0.0
    flip: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"shot_id": self.shot_id, "visible": bool(self.visible),
                "people": list(self.people),
                "rotated_deg": round(float(self.rotated_deg), 1),
                "flip": bool(self.flip)}


def crossing_events(axis: Axis, plan, initial: Dict[str, Sequence[float]]
                    ) -> Dict[str, CrossingEvent]:
    """逐镜推算：这一镜里配对连线**翻了个儿**没有、以及翻的时候看不看得见。

    为什么（2026-10-04，GLM 5.3 会诊 F2/F4 ＋ `work/_r001_classify_probe.py`）：
    R001 的假阳性/真阳性都要说清"换位是**看得见的**（两人同框时走过去 ⇒ 合法重建）
    还是**看不见的**（在只拍一个人的镜头里绕过去 ⇒ 越轴）。判据本身不动，
    但修复回路必须知道该改什么：前者不用改，后者要把换位放进两人同框的镜头、
    或按 §6.2 插一个中性机位。

    算法（纯计划＋接力位置，**不读机位**——读了就成"构建器自己出题自己判"）：
    以轴线的方向 `d` 为参考，看配对两点在 `d` 的**法线**上的差 `cross(d, B−A)`
    是否在某一镜里换了号；换号即"线翻了个儿"。`visible` 取该镜的
    `shot.characters` 里是否**两人都在**（画面的"看得见"由计划的出场声明给出，
    与 `SceneBrief.gaze` 同一层的意图数据）。
    """
    from .schedule import travelled_positions

    left, right = axis.left_label, axis.right_label
    if not left or not right:
        return {}
    before = travelled_positions(plan, dict(initial))
    direction = axis.direction
    if direction == (0.0, 0.0):
        return {}
    out: Dict[str, CrossingEvent] = {}
    previous_sign = 0
    shots = list(getattr(plan, "shots", []) or [])
    for index, shot in enumerate(shots):
        shot_id = str(shot.shot_id)
        start = before.get(shot_id) or {}
        #: 这一镜**结束时**的位置 ≈ 下一镜开始时（接力函数的口径）。
        following = before.get(str(shots[index + 1].shot_id)) if index + 1 < len(shots) else None
        end = following or _after_own_walks(shot, start)
        a_start, b_start = start.get(left), start.get(right)
        a_end, b_end = end.get(left), end.get(right)
        if not (a_start and b_start and a_end and b_end):
            continue
        #: 连线在这一镜里转了多少度（配对两点自己就是线，所以只能比**方向**）。
        rotated = _rotation_deg(a_start, b_start, a_end, b_end)
        #: 小于半度的差是数值噪声（走位精确停在目标上时仍会差一点点）。
        if rotated >= CROSSING_MIN_DEG:
            out[shot_id] = CrossingEvent(
                shot_id=shot_id,
                visible=len([cid for cid in (shot.characters or [])
                             if str(cid) in (left, right)]) >= 2,
                people=(left, right),
                rotated_deg=rotated,
                flip=rotated >= 90.0)
    return out


def _rotation_deg(a_start: Sequence[float], b_start: Sequence[float],
                  a_end: Sequence[float], b_end: Sequence[float]) -> float:
    """配对连线在这一镜里转过多少度（0–180）。"""
    fx0, fy0 = float(b_start[0]) - float(a_start[0]), float(b_start[1]) - float(a_start[1])
    fx1, fy1 = float(b_end[0]) - float(a_end[0]), float(b_end[1]) - float(a_end[1])
    n0 = math.hypot(fx0, fy0)
    n1 = math.hypot(fx1, fy1)
    if n0 < EPS or n1 < EPS:
        return 0.0
    cosine = max(-1.0, min(1.0,
                           (fx0 / n0) * (fx1 / n1) + (fy0 / n0) * (fy1 / n1)))
    return math.degrees(math.acos(cosine))


def _after_own_walks(shot, positions: Dict[str, Sequence[float]]
                     ) -> Dict[str, Sequence[float]]:
    """最后一镜没有"下一镜"可用时：把这一镜自己的行走终点算进去。"""
    out = dict(positions)
    for raw in getattr(shot, "actions", None) or []:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("action_type") or "") not in ("walk_to", "run_to"):
            continue
        character_id = str(raw.get("character_id") or "")
        params = dict(raw.get("params") or {})
        target = params.get("target_position") or raw.get("target_position")
        if character_id and isinstance(target, (list, tuple)) and len(target) >= 2:
            out[character_id] = (float(target[0]), float(target[1]))
    return out


def axis_state(axis: Axis, plan, initial: Dict[str, Sequence[float]]
               ) -> Dict[str, int]:
    """逐镜的**轴侧状态机**（纯函数）：每一镜机位该待在当前连线的哪一侧。

    第一原理（GLM 5.3 会诊 A3，2026-10-04）：**合法的状态机只能建立在可观测量上**；
    冻结线是"会失真的隐藏状态"——走位一动就与真实锚点脱钩。所以：

    * **线**每镜从两人**当前**坐标派生（`current_line`）；
    * **侧**继承，只在**合法桥接**处翻转——首版只认一种：**看得见的换位**
      （`crossing_events` 里 `visible=True`，即两人同框时走过去）。会诊 A1 还列了
      另外三种（摄影机自身跨轴、主体转向形成新轴、插入无方向镜头）；它们需要
      画面/机位信息，由规则侧用**已经建好的相机**补判（那仍然是可观测量），
      不在这个纯函数里假装知道。

    产物 `{shot_id: ±1}` 给构建器与规则**共用**；规则另有一条独立内容
    （"规范首镜线 vs 当前派生线"的偏差），所以两边不会退化成自证。
    """
    sides: Dict[str, int] = {}
    if not axis.left_label or not axis.right_label:
        return sides
    events = crossing_events(axis, plan, initial)
    side = int(axis.established_side) or SIDE_POSITIVE
    for shot in getattr(plan, "shots", []) or []:
        shot_id = str(shot.shot_id)
        sides[shot_id] = side
        event = events.get(shot_id)
        if event is not None and event.visible and event.flip:
            #: 看得见的换位 ⇒ 观众看到并接受这次重建：此后从另一侧继续。
            side = -side
    return sides


def drift_is_bridged(angle_deg: float, visible_deg: float, neutral: bool) -> bool:
    """轴线被走位重建了 `angle_deg` 度——这次重建**有没有被交代过去**。

    会诊 F1（GLM 5.3，2026-10-04，`docs/evidence/20261004-glm-consult-v19b/`）挑的是
    **记账**：原来写成"历史上**有过一次**看得见且转过 ≥5° 的事件就赦免"，那是存在性
    判定，与本次漂移的量级完全脱钩——

    * **放过**：一次 6° 的可见换位，洗白后来 53° 的暗重建（观众只见过 6°）；
    * **误判**：全程同框、每步 4°、累计 100° 的**可见**慢漂移，一条 ≥5° 的事件都
      没有，于是被判越轴——尽管观众全程看着这条线转。

    正确形状是"**赦免额对得上欠账额**"：阈值内（≤ `AXIS_DRIFT_DEG`）的漂移本来就
    免费，超出阈值的部分要由**看得见的旋转累计**偿付。本镜机位中性（§6.2 的桥梁）
    是逐镜成立的交代，直接算数。
    """
    if neutral:
        return True
    return visible_deg >= max(0.0, angle_deg - AXIS_DRIFT_DEG)


def current_line(axis: Axis, positions: Dict[str, Sequence[float]]) -> Axis:
    """把轴线的**线**更新到两人**此刻**的连线；侧别（`established_side`）继承。

    为什么需要（2026-10-04 实测 ＋ GLM 5.3 会诊 F1/F4）：`long12` 的 27 条 R001 里
    **26 条**的"越轴"其实是**整场走到布景的另一处**——伊恩走到 (6.9,−6.5)、
    米迦尔走到 (−1.8,−2.4) 之后就再没动过，而轴线还是首镜那条 ⇒ 后面每一镜都被
    判越轴。工艺上 180° 约束的是**覆盖**（机位怎么摆），不是**调度**（人怎么走）：
    人走到哪，线跟到哪；真正要继承的不变量是**屏幕上的左右关系**（侧别）。

    `positions` 按 `left_label`/`right_label` 取（少一个就原样返回）。**标签顺序保持**
    不变：两人互换左右位置时 `side_of` 自然翻号，**真正的越轴仍然会被判出来**。
    """
    left = positions.get(axis.left_label)
    right = positions.get(axis.right_label)
    if left is None or right is None:
        return axis
    if math.hypot(float(left[0]) - float(right[0]),
                  float(left[1]) - float(right[1])) < EPS:
        return axis
    return Axis(start=(float(left[0]), float(left[1])),
                end=(float(right[0]), float(right[1])),
                established_side=axis.established_side,
                left_label=axis.left_label, right_label=axis.right_label)


def establish_axis(axis: Axis, camera: Sequence[float]) -> Axis:
    """用**首镜机位**确立基准侧（§10.3：首镜决定整场方向感）。"""
    side = axis.side_of(camera)
    if side == SIDE_UNKNOWN:
        side = SIDE_POSITIVE      # 机位正好落在轴线上：退化为 +1，由调用方告警
    return Axis(start=axis.start, end=axis.end, established_side=side,
                left_label=axis.left_label, right_label=axis.right_label)


def axis_status(axis: Axis, camera: Sequence[float]) -> str:
    """机位相对轴线的状态：``correct`` / ``neutral`` / ``crossed``。

    ``neutral`` = 机位恰好落在轴线上，画面没有左右信息。它不是"越轴"，
    而是 §6.2 ``axis_neutral`` 卡片定义的跨轴桥梁。
    """
    side = axis.side_of(camera)
    if side == SIDE_UNKNOWN:
        return AXIS_NEUTRAL
    return AXIS_CORRECT if side == axis.established_side else AXIS_CROSSED


def axis_violation(axis: Axis, camera: Sequence[float]) -> Optional[str]:
    """**越轴**时返回中文建议；合规与中性机位都返回 ``None``（R001）。

    v1.3 修正：v1.2 把"机位落在轴线上"也判为违规。但中性镜头在
    §6.2 的 ``axis_neutral`` 卡片里是**合法**的跨轴桥梁，而且两人相对而立
    （"互相看向对方"）时，任何单人正反打的机位都必然落在轴线上——按旧判据
    这类镜头永远无法通过审核。现在中性不再是违规，改为由
    :func:`axis_neutral_note` 给出的提示（R001 降级为 warning）；
    真正跨到另一侧仍然报错。
    """
    if axis_status(axis, camera) == AXIS_CROSSED:
        return ("相机位置违反 180° 轴线规则，可能导致角色左右方向混乱。"
                "建议将相机移到轴线另一侧，或插入中性镜头过渡。")
    return None


def axis_neutral_note(axis: Axis, camera: Sequence[float]) -> Optional[str]:
    """中性机位的提示文本；非中性返回 ``None``。"""
    if axis_status(axis, camera) != AXIS_NEUTRAL:
        return None
    return ("机位落在轴线上（中性镜头）：画面没有明确的左右信息，"
            "可以作为跨轴桥梁，但连续使用会失去空间感。")


# --------------------------------------------------------------------------- #
# R010：30° 规则
# --------------------------------------------------------------------------- #
def shot_size_index(shot_type: str) -> int:
    key = str(shot_type).upper()
    return SHOT_SIZE_ORDER.index(key) if key in SHOT_SIZE_ORDER else -1


def shot_size_changed(previous: str, current: str) -> bool:
    """两个景别是否至少差一档。"""
    a, b = shot_size_index(previous), shot_size_index(current)
    if a < 0 or b < 0:
        return False
    return abs(a - b) >= 1


def camera_angle_deg(previous_camera: Sequence[float],
                     current_camera: Sequence[float],
                     target: Sequence[float]) -> float:
    """相邻两次机位相对被摄目标的夹角（度）。"""
    ax = float(previous_camera[0]) - float(target[0])
    ay = float(previous_camera[1]) - float(target[1])
    bx = float(current_camera[0]) - float(target[0])
    by = float(current_camera[1]) - float(target[1])
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na < EPS or nb < EPS:
        return 0.0
    cos_value = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(cos_value))


def thirty_degree_violation(previous_camera: Sequence[float],
                            current_camera: Sequence[float],
                            target: Sequence[float],
                            previous_shot: str,
                            current_shot: str) -> Optional[str]:
    """R010：角差不足 30° 且景别未变化 → 判为跳切隐患。"""
    angle = camera_angle_deg(previous_camera, current_camera, target)
    if angle >= MIN_ANGLE_DEG or shot_size_changed(previous_shot, current_shot):
        return None
    return (f"相邻镜头机位角差仅 {angle:.1f}°（< {MIN_ANGLE_DEG:.0f}°）"
            f"且景别未变化（{previous_shot} → {current_shot}），"
            f"看起来像跳切。建议改变机位角度，或至少变化一档景别。")


def shot_types() -> Tuple[str, ...]:
    return SHOT_TYPES


# --------------------------------------------------------------------------- #
# R019：银幕方向连续性（v1.4 §3.4，替代死字段 screen_direction）
# --------------------------------------------------------------------------- #
#: 判定"符号翻转"时的中性死区：|dot| 小于它视为中性（画面里看不出朝向）。
SCREEN_DIRECTION_EPS = 1e-3


def shared_characters(previous: Sequence[str],
                      current: Sequence[str]) -> list:
    """相邻两镜**都显式声明**的角色 id（保持前一镜的顺序）。"""
    current_set = {str(item) for item in (current or [])}
    return [str(item) for item in (previous or []) if str(item) in current_set]


def flipped_screen_directions(previous_facing: Dict[str, float],
                              current_facing: Dict[str, float],
                              character_ids: Sequence[str],
                              *, eps: float = SCREEN_DIRECTION_EPS) -> list:
    """返回在相邻两镜之间**银幕方向符号翻转**的角色 id。

    只对 ``character_ids``（＝两镜都显式声明、且两镜都算得出朝向）里的角色
    判定；任一镜的 ``|dot| < eps``（中性）都不算翻转——"翻转"必须有左右两侧。
    """
    flipped: list = []
    for character_id in character_ids:
        key = str(character_id)
        before = previous_facing.get(key)
        now = current_facing.get(key)
        if before is None or now is None:
            continue
        if abs(before) < eps or abs(now) < eps:
            continue
        if before * now < 0:
            flipped.append(key)
    return flipped
