"""每分镜决策树：纯层骨架（无 bpy）。

设计文档 ``per_shot_decision_tree_design.md`` §3.3-§3.4 / §6 阶段 0。

红线：本模块不得 import ``bpy``；允许 import ``contracts/``、
``motion/model.py``、``cinema/framing.py``、``cinema/axis.py`` 的纯函数。

规则真源一律从既有模块导入，不在这里抄第二份：
- ``cinema.framing.CAMERA_SIDES`` → ``camera.side`` 闭集；
- ``cinema.camera_motion.MOVEMENT_UNITS``（键与 ``enums.MOVEMENT_TYPES`` 锁定同源）
  → ``camera.movements[].type`` 闭集与 ``amount`` 数值域；
- ``motion.model.ACTION_PARAMS`` / ``ACTION_PARAM_ALIASES`` → 动作键与等价键归一；
- ``cinema.axis.axis_state`` → 逐镜轴侧 ``±1``（无注入时用纯函数预测；
  主路径由驱动注入运行时锁定值，两个输入枚举都在这里校验）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..cinema.camera_motion import MOVEMENT_UNITS
from ..cinema.framing import CAMERA_SIDES
from ..contracts.enums import StrEnum
from ..contracts.plan import Plan, ShotPlan
from ..motion.model import (
    ACTION_PARAMS,
    ACTION_PARAM_ALIASES,
    ACTION_TYPES,
    action_param_problems,
    normalize_action_params,
    unknown_action_params,
)


class TreeBuildError(ValueError):
    """决策树构建期的结构错误（节点判域、注入值、真源漂移）。"""


class Verdict(StrEnum):
    """投影结果三态。"""

    ACCEPT = "accept"             # 提议本来就在合法空间
    PROJECTED = "projected"       # 提议越界，已投影到最近合法值
    REJECTED = "rejected"         # 提议与剧本硬约束冲突，不投影，退回


@dataclass(frozen=True)
class DecisionNode:
    key: str
    kind: str                     # script_hard / rule / action_space / soft_advice
    priority: int                 # 0 = 最高（剧本硬节点），越大越软
    reason: str
    source: str
    allowed: Optional[Tuple[str, ...]] = None
    range: Optional[Tuple[float, float]] = None

    def __post_init__(self) -> None:
        if (self.allowed is None) == (self.range is None):
            raise TreeBuildError(
                f"{self.key}: allowed 与 range 必须恰有一个非空"
                f"（allowed={self.allowed!r}, range={self.range!r}）")
        if self.allowed is not None and not self.allowed:
            raise TreeBuildError(f"{self.key}: allowed 不得为空元组")
        if self.range is not None:
            low, high = self.range
            if low > high:
                raise TreeBuildError(f"{self.key}: range 下限不得大于上限")


@dataclass(frozen=True)
class ProjectionRecord:
    shot_id: str
    stage: str                    # draft / react / repair
    node_key: str
    original: Any
    projected: Any
    verdict: Verdict
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "stage": self.stage,
            "node_key": self.node_key,
            "original": self.original,
            "projected": self.projected,
            "verdict": str(self.verdict),
            "reason": self.reason,
        }


@dataclass
class ShotDecisionTree:
    shot_id: str
    nodes: Tuple[DecisionNode, ...] = ()
    legal_space: Dict[str, Tuple[Any, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for node in self.nodes or ():
            if (node.allowed is None) == (node.range is None):
                raise TreeBuildError(
                    f"{node.key}: allowed 与 range 必须恰有一个非空")


def _iter_movement_keys() -> Tuple[str, ...]:
    """``MOVEMENT_UNITS`` 的键（与 ``MOVEMENT_TYPES`` 同源，见模块红线）。"""
    return tuple(MOVEMENT_UNITS)


def _clamp(value: Any, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


#: P2 动作/运镜闭集的「无歧义」编辑距离门槛。模型常见词形变体
#: （空格/连字符/单字符差异，如 "dolly in" → "dolly_in"）距离 ≤ 1–2；
#: 完全无关的自由文本（"fly to the moon" 最近 12、"finger_snap"
#: 最近 9）远超该值。只有词形归一后的前缀命中或 ≤ 该门槛的近邻才投影，
#: 其余 REJECTED（设计文档 §3.4 P2「无歧义才投影」）。
ACTION_SPACE_FUZZY_MAX_EDIT = 2


def _normalize_token_text(text: str) -> str:
    """词形归一：小写 + 非字母数字/中日韩字符压成下划线。

    "front-right, same 180° side as shot_004" → ``front_right_same_180_side_…``；
    "dolly in" → ``dolly_in``；"伊恩同侧（延续 shot_008 轴侧，不越轴）"
    → ``伊恩同侧_延续_shot_008_…``。前缀匹配在归一后做，保证
    ``front`` 不会先于 ``front_right`` 吞掉连字符变体。
    """
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)


def _project_side(node: DecisionNode, original: Any) -> Any:
    """轴侧/方向枚举投影：词形归一 + 最长前缀优先 + 编辑距离找最近合法值。

    P1（``camera.side`` 等规则节点）：归一后的前缀命中最长候选，否则
    编辑距离兜底投影到最近合法 token（设计 §3.4 P1）。
    P2（``action_type``/``movements[].type`` 等动作空间节点）：归一后
    前缀命中或编辑距离 ≤ 门槛才投影，否则返回 None（调用方 REJECTED，
    设计 §3.4 P2「无歧义才投影」）。

    语义冲突分支（camera.side 轴侧收窄）：``original`` 是全局
    ``CAMERA_SIDES`` 的精确 token 但不在本镜合法闭集（如轴侧 ±1 时
    back 系恒在反侧 = 越轴）→ 返回 None，调用方 REJECTED 原样退回。
    这里不投影，因为改写成 front 系会静默改变导演意图、绕过 R001
    越轴红线；P1 的「投影到最近合法 token」只针对词形/自由文本变体
    （``'side'``、``'front-right, same 180°...'``），不针对语义冲突。
    """
    allowed = node.allowed or ()
    text = str(original or "").strip().lower()
    if not text or not allowed:
        return None
    #: 含糊的 "side"（r6 实证样例：模型写整句中文/半枚举）→ 收敛到
    #: 两个无歧义侧向之一，而不是退化成任意最近串。
    if node.key == "camera.side" and text == "side":
        return "left" if "left" in allowed else "right"
    normalized = _normalize_token_text(text)
    if node.key == "camera.side":
        for global_token in CAMERA_SIDES:
            if normalized == global_token and global_token not in allowed:
                #: 精确全局 token 但被本镜闭集收窄 → 语义冲突，REJECTED。
                return None
    #: 最长前缀优先：先试长候选（front_right/back_left），避免
    #: front/back 短前缀抢先把连字符变体吞成单侧。
    for candidate in sorted(allowed, key=len, reverse=True):
        if normalized.startswith(candidate):
            return candidate
    best = min(allowed, key=lambda c: _edit_distance(normalized, c))
    if node.kind == "action_space":
        if _edit_distance(normalized, best) > ACTION_SPACE_FUZZY_MAX_EDIT:
            return None
    return best


def _edit_distance(a: str, b: str) -> int:
    """朴素 Levenshtein 编辑距离（候选集 ≤ 9，足够快）。"""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _axis_sides_from_plan(plan: Optional[Plan]) -> Dict[str, int]:
    """用 ``axis_state`` 的顺序状态机预判每镜轴侧（无注入真源）。"""
    from ..cinema.axis import (
        SIDE_NEGATIVE,
        SIDE_POSITIVE,
        Axis,
        axis_from_points,
        axis_state,
    )

    shots = list(getattr(plan, "shots", []) or [])
    if not shots:
        return {}
    environment = dict(getattr(plan, "environment", None) or {})
    anchors = list(environment.get("anchors") or [])
    first_left = ""
    first_right = ""
    initial: Dict[str, Sequence[float]] = {}
    for index, shot in enumerate(shots):
        for character_id in (shot.characters or []):
            if character_id not in initial:
                initial[character_id] = (
                    float(index % 2), float(len(initial) % 2))
    if len(initial) >= 2:
        ids = list(initial)
        first_left, first_right = ids[0], ids[1]
    axis: Axis
    if first_left and first_right:
        axis = axis_from_points(
            initial[first_left], initial[first_right],
            a_label=first_left, b_label=first_right)
    else:
        axis = Axis(start=(0.0, 0.0), end=(1.0, 0.0),
                    established_side=SIDE_POSITIVE)
    sides = axis_state(axis, plan, initial)
    return {shot_id: int(side) for shot_id, side in sides.items()}


def _axis_sides_for(axis_side: Optional[int], shot_type: str) -> Tuple[str, ...]:
    """按轴侧/镜头类型返回该镜 ``camera.side`` 合法闭集。

    真源是 ``cinema.station.camera_direction`` 的**双人镜/单人都成立**语义
    （复算证：``axis_side=±1`` 时 front 系 —— front / front_left /
    front_right / left / right /（OTS/POV 追加 over_shoulder）—— 落在
    已确立轴侧，back 系恒在反侧；单人镜 ``_honour_the_established_side``
    也会把方向镜像到已确立侧）。设计文档 §3.4「正面两侧各取一个候选」。

    - ``axis_side`` ∈ {+1, -1}：front 系 5 个；OTS/POV 追加 ``over_shoulder``；
    - 其余（0 / None）：全 9 个 token（无轴 / 空镜豁免）。
    """
    if axis_side is None or int(axis_side) not in (-1, 1):
        return tuple(CAMERA_SIDES)
    sides = ["front", "front_left", "front_right", "left", "right"]
    if str(shot_type or "").upper() in ("OTS", "POV"):
        sides.append("over_shoulder")
    return tuple(sides)


def build_tree(shot: ShotPlan, plan: Optional[Plan] = None, *,
               contract: Any = None,
               axis_side: Optional[int] = None) -> ShotDecisionTree:
    """为单个分镜构建决策树。"""
    if axis_side is not None and int(axis_side) not in (-1, 0, 1):
        raise TreeBuildError(
            f"axis_side 必须是 -1/0/1（0 = 无轴/空镜豁免），"
            f"收到 {axis_side!r}")
    shot_id = str(getattr(shot, "shot_id", ""))
    characters = [str(item) for item in (getattr(shot, "characters", None) or [])]
    shot_type = str(getattr(shot, "shot_type", "") or "")
    camera = dict(getattr(shot, "camera", None) or {})
    actions = [dict(item) for item in (getattr(shot, "actions", None) or [])]

    has_subject = bool(characters)
    if not has_subject:
        #: 空镜：无关系线，不做轴侧闭集（全部 9 个合法 token 仍可用）。
        side_set = list(CAMERA_SIDES)
    elif axis_side is not None:
        side_set = list(_axis_sides_for(axis_side, shot_type))
    else:
        side_set = list(_axis_sides_for(
            _axis_sides_from_plan(plan).get(str(getattr(shot, "shot_id", "")), 0),
            shot_type))

    movement_set = list(_iter_movement_keys())
    action_set = list(ACTION_TYPES)
    target_set = list(characters)
    environment = dict(getattr(plan, "environment", None) or {}) if plan else {}
    for anchor in (environment.get("anchors") or []):
        if isinstance(anchor, dict):
            name = anchor.get("name") or anchor.get("id")
            if name:
                target_set.append(str(name))

    nodes: List[DecisionNode] = [
        DecisionNode(
            key="camera.side",
            kind="rule",
            priority=1,
            reason="机位侧别必须在轴规则/取景合法闭集内",
            source="cinema.framing.CAMERA_SIDES + axis_state",
            allowed=tuple(side_set),
        ),
        DecisionNode(
            key="camera.lens",
            kind="rule",
            priority=1,
            reason="焦段必须在引擎支持范围 8–300mm",
            source="cinema/lens",
            range=(8.0, 300.0),
        ),
        DecisionNode(
            key="camera.movements.type",
            kind="action_space",
            priority=2,
            reason="运镜类型必须在引擎 24 种封闭清单内",
            source="cinema.camera_motion.MOVEMENT_UNITS",
            allowed=tuple(movement_set),
        ),
        DecisionNode(
            key="action_type",
            kind="action_space",
            priority=2,
            reason="动作类型必须在引擎动作词表内",
            source="motion.model.ACTION_TYPES",
            allowed=tuple(action_set),
        ),
    ]
    #: 空镜没有合法 target：不建节点（allowed 为空元组是构建期错误）。
    if target_set:
        nodes.append(
            DecisionNode(
                key="action.look_at.target",
                kind="script_hard",
                priority=0,
                reason="look_at 的目标必须是本镜出场角色或场景锚点，"
                       "不接受自由文本坐标",
                source="motion.model.ACTION_PARAMS[look_at] + shot.characters",
                allowed=tuple(target_set),
            ))
    for movement, (unit, low, high) in MOVEMENT_UNITS.items():
        nodes.append(
            DecisionNode(
                key=f"camera.movements.{movement}.amount",
                kind="rule",
                priority=1,
                reason=f"运镜 {movement} 的幅度必须在 {unit} "
                       f"[{low}, {high}] 内",
                source="cinema.camera_motion.MOVEMENT_UNITS",
                range=(low, high),
            ))

    legal_space: Dict[str, Tuple[Any, ...]] = {
        "camera.side": tuple(side_set),
        "camera.lens": (8.0, 300.0),
        "movement": tuple(movement_set),
        "action_type": tuple(action_set),
        "camera.movements.type": tuple(movement_set),
    }
    if target_set:
        legal_space["look_at.target"] = tuple(target_set)
    for movement, (unit, low, high) in MOVEMENT_UNITS.items():
        legal_space[f"camera.movements.{movement}.amount"] = (low, high)

    #: §3.5.4：连续键的来源与盒边界（与树共用同一真源）。树把可微调连续键
    #: 附带导出为 ``opt_variables``：agent 的 x0 只能在这些登记键里取，
    #: 提示词渲染同样来自这里（单一真源）。``scale`` 只是步长**建议基准**
    #: （区间典型跨度 / 20），agent 显式决定实际 ``step_scale``——优化器
    #: 不自动推导兜底（§3.5.3 红线）。
    from .continuous_optimizer import OptVariable  # 纯层，无 bpy，无循环依赖

    opt_variables: List[OptVariable] = [
        OptVariable(key="camera.lens", low=8.0, high=300.0, unit="毫米",
                    scale=(300.0 - 8.0) / 20.0, step=1.0),
    ]
    for movement, (unit, low, high) in MOVEMENT_UNITS.items():
        step = 1.0 if unit == "度" else 0.05 if unit == "米" else 1.0
        opt_variables.append(OptVariable(
            key=f"camera.movements.{movement}.amount",
            low=float(low), high=float(high), unit=unit,
            scale=(float(high) - float(low)) / 20.0, step=step))
    legal_space["opt_variables"] = tuple(opt_variables)

    return ShotDecisionTree(shot_id=shot_id, nodes=tuple(nodes),
                            legal_space=legal_space)


def _project_value(node: DecisionNode, original: Any) -> Tuple[Any, Verdict]:
    if node.allowed is not None:
        if original in node.allowed:
            return original, Verdict.ACCEPT
        if node.kind == "script_hard":
            #: P0 硬约束：剧本/角色目标越界不投影，原样退回由调用方重试。
            return original, Verdict.REJECTED
        projected = _project_side(node, original)
        if projected in node.allowed:
            return projected, Verdict.PROJECTED
        return original, Verdict.REJECTED
    #: 数值域：先 clamp（不自由文本投影）
    low, high = node.range  # type: ignore[misc]
    try:
        value = float(original)
    except (TypeError, ValueError):
        return original, Verdict.REJECTED
    clamped = _clamp(value, low, high)
    if abs(clamped - value) < 1e-9:
        return original, Verdict.ACCEPT
    return clamped, Verdict.PROJECTED


def _look_at_angle_keys(alias_to: Dict[str, Dict[str, str]]) -> List[str]:
    """``look_at`` 规范角度键与其无歧义别名的并集（从真源推导，不手抄）。"""
    keys = ["yaw_deg", "pitch_deg"]
    for alias, canonical in (alias_to or {}).get("look_at", {}).items():
        if canonical in ("yaw_deg", "pitch_deg"):
            keys.append(alias)
    return keys


def project(tree: ShotDecisionTree, proposal: Dict[str, Any], *,
            stage: str) -> Tuple[Dict[str, Any], List[ProjectionRecord]]:
    """把提议投影到该镜合法空间；返回 (投影后提议, 审计记录)。"""
    shot_id = tree.shot_id
    records: List[ProjectionRecord] = []
    def _copy(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): _copy(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_copy(item) for item in value]
        return value

    projected = _copy(proposal)

    def _record(node_key: str, original: Any, value: Any,
                verdict: Verdict, reason: str) -> None:
        """ACCEPT 不写审计；PROJECTED/REJECTED 都必须留下记录。"""
        if verdict == Verdict.ACCEPT:
            return
        records.append(ProjectionRecord(
            shot_id=shot_id, stage=stage, node_key=node_key,
            original=original, projected=value, verdict=verdict,
            reason=reason))

    nodes: Dict[str, DecisionNode] = {node.key: node for node in tree.nodes}
    side_node = nodes.get("camera.side")
    lens_node = nodes.get("camera.lens")
    movement_type_node = nodes.get("camera.movements.type")
    action_type_node = nodes.get("action_type")
    target_node = nodes.get("action.look_at.target")

    #: P1 规则：camera.side / camera.lens 顶层
    camera = projected.get("camera")
    if isinstance(camera, dict) and side_node is not None:
        if "side" in camera:
            value, verdict = _project_value(side_node, camera["side"])
            _record("camera.side", camera["side"], value, verdict,
                    side_node.reason)
            if verdict == Verdict.PROJECTED:
                camera["side"] = value
    if isinstance(camera, dict) and lens_node is not None:
        if "lens" in camera:
            value, verdict = _project_value(lens_node, camera["lens"])
            _record("camera.lens", camera["lens"], value, verdict,
                    lens_node.reason)
            if verdict == Verdict.PROJECTED:
                camera["lens"] = value

    #: 嵌套：movements[].type / movements[].amount / actions[].action_type
    #: / actions[].params（含 look_at.target 与等价键归一）。
    for movement in (camera.get("movements") if isinstance(camera, dict)
                     else None) or []:
        if not isinstance(movement, dict):
            continue
        if "type" in movement and movement_type_node is not None:
            value, verdict = _project_value(movement_type_node,
                                            movement["type"])
            _record("camera.movements.type", movement["type"], value,
                    verdict, movement_type_node.reason)
            if verdict == Verdict.PROJECTED:
                movement["type"] = value
        amount_key = f"camera.movements.{movement.get('type', '')}.amount"
        amount_node = nodes.get(amount_key)
        if "amount" in movement and amount_node is not None:
            value, verdict = _project_value(amount_node, movement["amount"])
            _record(amount_key, movement["amount"], value, verdict,
                    amount_node.reason)
            if verdict == Verdict.PROJECTED:
                movement["amount"] = value

    for action in projected.get("actions") or []:
        if not isinstance(action, dict):
            continue
        kind = str((action.get("action_type") or "")).strip()
        if not kind:
            continue
        if "action_type" in action and action_type_node is not None:
            value, verdict = _project_value(action_type_node,
                                            kind)
            _record("action_type", kind, value, verdict,
                    action_type_node.reason)
            if verdict != Verdict.ACCEPT:
                continue
        #: 工具 schema 的动作项**顶层**只允许 target_position
        #: （walk_to/run_to 用；其余动作写顶层 target_position 是
        #: 与参数位置错位，按工具 schema 原样 REJECTED，不挪进 params）。
        if (kind not in ("walk_to", "run_to")
                and "target_position" in action
                and action["target_position"] is not None):
            _record("actions[*].target_position",
                    action["target_position"], None, Verdict.REJECTED,
                    f"emit_shot_draft: {kind} 不允许在动作顶层出现 "
                    "target_position（walk_to/run_to 才在顶层；其余动作走 "
                    "params）")
            continue
        params = action.get("params")
        if not isinstance(params, dict):
            continue
        #: P3 等价键归一（angle_deg → yaw_deg）——无审计，只影响键名。
        #: 用 ``motion.model.normalize_action_params``（公开函数，返回新 dict），
        #: 不在这里抄第二份别名表。
        params = normalize_action_params(kind, params)
        action["params"] = params
        #: G8-C 互斥字段：look_at 同时写 target 与角度 → 丢弃全部角度键
        #: （含别名），留一条 PROJECTED 审计。判域与
        #: ``action_param_problems`` 同源（不手抄角度键名）。
        if kind == "look_at" and "target" in params:
            angle_keys = _look_at_angle_keys(ACTION_PARAM_ALIASES)
            dual = [key for key in angle_keys if key in params]
            if dual:
                original = {key: params[key] for key in dual}
                for key in dual:
                    params.pop(key, None)
                _record("action.look_at.dual_write", original, None,
                        Verdict.PROJECTED,
                        "look_at 不能同时写 target 与 yaw_deg/pitch_deg"
                        "（无隐式优先级）：target 由编译层按角色位置折算成角度")
        #: 键集过滤（P2/P3）：``ACTION_PARAMS[kind]`` 之外的 params 键
        #: 丢弃并逐键留审计。真源 = ``motion.model``，不抄第二份。
        for key in unknown_action_params(kind, params):
            value = params.pop(key, None)
            _record("actions[*].params", {key: value}, None,
                    Verdict.PROJECTED,
                    f"{kind} 不认识的参数 [{key}]")
        #: 取值判域（闭集/数值/坐标形状）——与解析期同源。发现问题的键
        #: 照 ``action_param_problems`` 原样拒绝（不猜值、不投影取值）。
        for problem in action_param_problems(kind, params):
            _record("actions[*].params", dict(params), None,
                    Verdict.REJECTED, str(problem))
        if "target" in params and target_node is not None:
            value, verdict = _project_value(target_node, params["target"])
            _record("action.look_at.target", params["target"], value,
                    verdict, target_node.reason)
            if verdict == Verdict.PROJECTED:
                params["target"] = value

    return projected, records


def render_legal_space(tree: ShotDecisionTree) -> str:
    """渲染该镜合法动作空间（供提示词注入，稳定可断言）。"""
    lines = [f"镜 {tree.shot_id} 合法动作空间："]
    for key, values in tree.legal_space.items():
        if key == "opt_variables":
            #: §3.5.4：连续键对象由优化工具 schema 单独消费，不在这里按
            #: 二元组渲染（它是一整组 OptVariable，不是单个数值域）。
            continue
        if isinstance(values, tuple) and values and isinstance(values[0], str):
            lines.append(f"- {key}: {' / '.join(str(v) for v in values)}")
        else:
            low, high = values
            lines.append(f"- {key}: [{low}, {high}]")
    return "\n".join(lines)
