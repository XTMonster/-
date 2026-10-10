"""拍点表与三个镜头级规格（执行文档 v1.5 TDD §3.1/§3.4/§3.5/§3.6）。

**命名消歧（重要）**：``contracts/brief.py::SceneBrief.beats`` 是**叙事节拍**
（``{id, summary, participants, emotion, function}``，阶段 S 对剧本的理解产物）；
本模块的 :class:`ShotBeat` 是**执行拍点**（一镜内的动作时刻表：归一化时机
``t`` ＋ 动词 ＋ 目标 ＋ 节奏）。两者概念不同、生产者不同、消费者不同，
**不得互相喂入、不得合并**。类名刻意用 ``ShotBeat`` 而不是 ``Beat``，
防止与 ``SceneBrief.beats`` 在阅读和维护时混淆。``ShotPlan`` 上的字段名仍叫
``beats``（JSON 契约面简洁），但那些元素是**执行拍点**，不是叙事节拍。

为什么要有拍点层（调研报告 §2/§4）：连续数值（帧号、坐标）不可枚举、不可语义
校验，是幻觉温床；把"什么时候做什么"降成"归一化时机 ＋ 有限动词表"，帧号交给
求解器换算（``layer5_orchestrator/beat_compiler.py``），单镜的修改粒度也从
"重算整段帧号"降到"改一个 t"。

纯 Python，**不 import bpy**（红线 R-1）。动词词表的单一真源是
``motion/model.py``（红线 R-7）——本模块**导入**它，不另抄一份。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..motion.model import ACTION_TYPES, ENTRANCE_ACTIONS, PROP_ACTIONS
from ..motion.targets import looks_like_coordinate_string, target_kind

#: 每镜拍点的**上限**（与 TDD §3.1 的不变量、emit_shot_draft 的 maxItems 同源）。
#: schema 里写 8，校验器也用同一个常量——两处各写一个"8"就会漂。
MAX_BEATS = 8

#: 可执行动词的**全部**合法取值。**导入** ``motion/model.py::ACTION_TYPES``
#: （红线 R-7）：语义动词（``enter_from``/``exit_frame``/``place_prop``/``pick_up``
#: /``hand_to``）的定义也登记在那一张表里，此处不手抄。
BEAT_VERBS = ACTION_TYPES

#: ``face_to`` 的**闭集**取值（角色 id 也合法，因此这一列不是"完全闭集"）。
FACE_TO_VALUES: tuple = ("screen_left", "screen_right", "camera", "away")

#: ``pace`` 的闭集（空 = 缺省 ``normal``）。
PACE_VALUES: tuple = ("slow", "normal", "brisk")

#: 灯光语义的闭集（TDD §3.4）。LLM 只写这三个语义字段，
#: 灯具参数（energy/color/size）永不开放——那由预设矩阵决定（§4.5）。
TIME_OF_DAY_VALUES: tuple = ("day", "night", "dusk", "dawn")
LIGHT_MOOD_VALUES: tuple = ("bright", "neutral", "gloomy", "tense", "soft")
KEY_DIRECTION_VALUES: tuple = ("front", "side", "back")

#: 构图声明的闭集（TDD §3.5）。
COMPOSITION_RULES: tuple = (
    "thirds", "center", "symmetry", "diagonal", "frame_within_frame", "lead_room")
SUBJECT_POSITIONS: tuple = ("left_third", "right_third", "center")

#: 破例辩护的动作闭集（TDD §3.6）。
RULE_ACTIONS: tuple = ("follow", "break")


def _default_curve() -> str:
    """``ShotBeat.curve`` 的缺省词（单一真源 = ``contracts/rhythm.py::DEFAULT_CURVE``）。

    ``rhythm.py`` 顶部 ``from .beats import PACE_VALUES``，所以本模块只能在
    **函数体内**反向 import 它（模块级 import 会成环：beats → rhythm → beats）。
    """
    from .rhythm import DEFAULT_CURVE
    return DEFAULT_CURVE


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _target_value(value: Any) -> Any:
    """``ShotBeat.target`` 的反序列化（G8-C）。

    结构化目标（``{"character": id}`` / ``{"point": [x, y, z]}``）原样保留，
    其余照旧压成字符串——历史响应与既有调用方逐字节不变。
    """
    if isinstance(value, dict):
        return dict(value)
    return _text(value)


@dataclass
class ShotBeat:
    """一镜内部的**一个执行拍点**（不是 ``SceneBrief.beats`` 的叙事节拍）。"""

    t: float = 0.0                       # 归一化时机，0.0–1.0，镜内单调不减
    subject: str = ""                    # character_id；必须在 cast 里
    verb: str = ""                       # 枚举，见 BEAT_VERBS
    #: 锚点名 / character_id / {"character": id} / {"point": [x, y, z]}（G8-C）。
    target: Any = ""
    face_to: str = ""                    # 角色 id / screen_left / screen_right / camera / away
    pace: str = ""                       # slow / normal / brisk；空 = normal
    #: v1.6 D2（FR-B3）：速度曲线词（闭集真源 = ``contracts/rhythm.py::CURVE_VALUES``，
    #: 缺省 smooth）。LLM 只写词，插值/位移轮廓由编译层确定性折出。
    curve: str = field(default_factory=_default_curve)
    react: str = ""                      # 情绪反应标签（自由短文本，仅注释用）

    def to_dict(self) -> Dict[str, Any]:
        return {"t": float(self.t), "subject": self.subject, "verb": self.verb,
                "target": self.target, "face_to": self.face_to,
                "pace": self.pace, "curve": self.curve, "react": self.react}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShotBeat":
        payload = data or {}
        return cls(t=_as_float(payload.get("t")),
                   subject=_text(payload.get("subject")),
                   verb=_text(payload.get("verb")),
                   target=_target_value(payload.get("target")),
                   face_to=_text(payload.get("face_to")),
                   pace=_text(payload.get("pace")),
                   curve=_text(payload.get("curve")) or _default_curve(),
                   react=_text(payload.get("react")))


@dataclass
class LightSpec:
    """场级**灯光语义**（TDD §3.4）。空字符串 = 不声明该维度。"""

    time_of_day: str = ""       # day / night / dusk / dawn
    mood: str = ""              # bright / neutral / gloomy / tense / soft
    key_direction: str = ""     # front / side / back

    def to_dict(self) -> Dict[str, Any]:
        return {"time_of_day": self.time_of_day, "mood": self.mood,
                "key_direction": self.key_direction}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LightSpec":
        payload = data or {}
        return cls(time_of_day=_text(payload.get("time_of_day")),
                   mood=_text(payload.get("mood")),
                   key_direction=_text(payload.get("key_direction")))

    @property
    def is_empty(self) -> bool:
        return not (self.time_of_day or self.mood or self.key_direction)


@dataclass
class CompositionSpec:
    """构图声明（TDD §3.5）。空 = 求解器默认（**零行为差**）。"""

    rule: str = ""
    subject_position: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "subject_position": self.subject_position}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompositionSpec":
        payload = data or {}
        return cls(rule=_text(payload.get("rule")),
                   subject_position=_text(payload.get("subject_position")))

    @property
    def is_empty(self) -> bool:
        return not (self.rule or self.subject_position)


@dataclass
class RuleJustification:
    """破例辩护（TDD §3.6）：这一镜引用/有意违反哪条规则、为什么。"""

    rule: str = ""
    action: str = "follow"      # follow / break
    reason: str = ""
    precedent: str = ""         # 破例先例（影片/案例 id）；break 时建议填

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "action": self.action,
                "reason": self.reason, "precedent": self.precedent}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleJustification":
        payload = data or {}
        return cls(rule=_text(payload.get("rule")),
                   action=_text(payload.get("action")) or "follow",
                   reason=_text(payload.get("reason")),
                   precedent=_text(payload.get("precedent")))


# --------------------------------------------------------------------------- #
# 校验（纯函数，返回问题清单而不抛异常——与契约层既有风格一致）
# --------------------------------------------------------------------------- #
def _coerce_beats(beats: Iterable[Any]) -> List[ShotBeat]:
    out: List[ShotBeat] = []
    for item in beats or []:
        if isinstance(item, ShotBeat):
            out.append(item)
        elif isinstance(item, dict):
            out.append(ShotBeat.from_dict(item))
    return out


def validate_beats(beats: Sequence[Any], characters: Sequence[str] = (),
                   anchors: Optional[Sequence[str]] = None,
                   full_cast: Optional[Sequence[str]] = None) -> List[str]:
    """TDD §3.1 的全部不变量；返回问题清单（空 = 合法）。

    参数语义（这一层刻意区分"未知"与"空"）：

    * ``characters`` 为空 ⇒ 剧组未知 ⇒ **跳过** subject/target/face_to 的成员检查
      （否则离线替身与单测会拿到一堆假问题）；
    * ``anchors`` 为 ``None`` ⇒ 锚点表未知 ⇒ 跳过 target 的锚点那一半；
      给一个（哪怕空的）序列 ⇒ 按真实表校验。
    * ``full_cast`` 为 ``None``（G8-C 之前的调用）⇒ target 的成员检查**逐字节
      不变**；给了全剧组表 ⇒ target 可以是任何全剧组角色（含场外角色）或
      结构化目标 ``{"character": id}`` / ``{"point": [x, y, z]}``，而
      ``subject`` 仍必须在本镜 ``characters`` 里。屏幕相对词照旧拒绝；
      坐标字符串（``'[2,0,0]'`` / ``'1.15,0'``）拒绝并提示改用
      ``{"point": [x, y, z]}``。

    不变量：``t ∈ [0,1]``；同一 subject 的拍点按 ``t`` 单调不减；``subject``
    非空且（表已知时）在 cast 里；``target`` 非空时（表已知时）能在锚点表或 cast
    里解析；``face_to``/``pace`` 非空时落在各自闭集内（``face_to`` 另允许角色 id）；
    ``curve`` 落在 ``contracts/rhythm.py::CURVE_VALUES`` 闭集内（空 = 缺省 smooth）；
    拍点数 ≤ MAX_BEATS。
    """
    problems: List[str] = []
    items = _coerce_beats(beats)
    if len(items) > MAX_BEATS:
        problems.append(f"拍点数 {len(items)} 超过上限 {MAX_BEATS}")

    known_cast = {str(item) for item in (characters or []) if str(item)}
    known_anchors: Optional[set] = None
    if anchors is not None:
        known_anchors = {str(item) for item in anchors if str(item)}
    known_full_cast: Optional[set] = None
    if full_cast is not None:
        known_full_cast = {str(item) for item in full_cast if str(item)}

    from .rhythm import curve_problems
    last_t: Dict[str, float] = {}
    for index, beat in enumerate(items, start=1):
        where = f"第 {index} 个拍点"
        if not (0.0 <= float(beat.t) <= 1.0):
            problems.append(f"{where}的 t={beat.t} 不在 [0,1] 内")
        if not beat.subject:
            problems.append(f"{where}缺少 subject")
        elif known_cast and beat.subject not in known_cast:
            problems.append(f"{where}的 subject={beat.subject!r} 不在本镜角色里")
        if beat.verb not in BEAT_VERBS:
            problems.append(
                f"{where}的 verb={beat.verb!r} 不在动词闭集内"
                f"（合法取值：{'、'.join(BEAT_VERBS)}）")
        if known_full_cast is not None:
            problems.extend(_target_problems(beat.target, known_full_cast,
                                             known_anchors, where))
        else:
            #: G8-C：未传 full_cast 时这段**逐字节不动**（`_text` 对字符串是
            #: 恒等，只是让结构化 dict 目标退回旧的字符串化行为，不会 TypeError）。
            target_text = _text(beat.target)
            if target_text and known_cast and target_text not in known_cast \
                    and known_anchors is not None \
                    and target_text not in known_anchors:
                problems.append(
                    f"{where}的 target={target_text!r} "
                    f"既不在角色表也不在锚点表里")
        if beat.face_to and beat.face_to not in FACE_TO_VALUES \
                and not (known_cast and beat.face_to in known_cast):
            problems.append(
                f"{where}的 face_to={beat.face_to!r} 不在闭集内"
                f"（{'、'.join(FACE_TO_VALUES)}）也不是角色 id")
        if beat.pace and beat.pace not in PACE_VALUES:
            problems.append(
                f"{where}的 pace={beat.pace!r} 不在闭集内（{'、'.join(PACE_VALUES)}）")
        problems += curve_problems(beat.curve, f"{where}.curve")
        if beat.subject:
            previous = last_t.get(beat.subject)
            if previous is not None and float(beat.t) < previous - 1e-9:
                problems.append(
                    f"{where}的 t={beat.t} 早于同一角色（{beat.subject}）"
                    f"上一个拍点的 t={previous}：同一角色的拍点必须按 t 单调不减")
            last_t[beat.subject] = max(previous if previous is not None else 0.0,
                                      float(beat.t))
    return problems


def _target_problems(target: Any, full_cast: set, anchors: Optional[set],
                     where: str) -> List[str]:
    """传了 ``full_cast`` 时的 target 判域（G8-C）。"""
    if target is None or target == "":
        return []
    if isinstance(target, dict):
        kind = target_kind(target)
        if kind == "character":
            character_id = str(target["character"]).strip()
            if character_id not in full_cast:
                return [f"{where}的 target={target!r} 的角色不在全剧组里"
                        f"（合法：全剧组内的角色 id）"]
            return []
        if kind == "point":
            return []
        return [f"{where}的 target={target!r} 不是合法目标："
                f"{{'character': id}} 或 {{\"point\": [x, y, z]}}"]
    text = str(target or "").strip()
    if not text:
        return []
    if looks_like_coordinate_string(text):
        return [f"{where}的 target={text!r} 看起来像坐标，"
                f"请写成 {{\"point\": [x, y, z]}}"]
    if text in full_cast:
        return []
    if anchors is not None and text in anchors:
        return []
    if anchors is None:
        return [f"{where}的 target={text!r} 不在全剧组角色里"
                f"（锚点表未提供）"]
    return [f"{where}的 target={text!r} 既不在全剧组角色里也不在锚点表里"]


def validate_light_spec(spec: Any) -> List[str]:
    """灯光语义三字段的闭集校验；空串合法（= 不声明）。"""
    data = spec.to_dict() if isinstance(spec, LightSpec) else dict(spec or {})
    problems: List[str] = []
    for key, domain in (("time_of_day", TIME_OF_DAY_VALUES),
                        ("mood", LIGHT_MOOD_VALUES),
                        ("key_direction", KEY_DIRECTION_VALUES)):
        value = _text(data.get(key))
        if value and value not in domain:
            problems.append(f"light.{key}={value!r} 不在闭集内（{'、'.join(domain)}）")
    return problems


def validate_composition_spec(spec: Any) -> List[str]:
    """构图声明的闭集校验；空串合法（= 求解器默认）。"""
    data = (spec.to_dict() if isinstance(spec, CompositionSpec)
            else dict(spec or {}))
    problems: List[str] = []
    rule = _text(data.get("rule"))
    if rule and rule not in COMPOSITION_RULES:
        problems.append(
            f"composition.rule={rule!r} 不在闭集内（{'、'.join(COMPOSITION_RULES)}）")
    position = _text(data.get("subject_position"))
    if position and position not in SUBJECT_POSITIONS:
        problems.append(
            f"composition.subject_position={position!r} 不在闭集内"
            f"（{'、'.join(SUBJECT_POSITIONS)}）")
    return problems


def validate_justifications(items: Sequence[Any]) -> List[str]:
    """破例辩护的校验：``rule`` 非空、``action`` 闭集、``break`` 必填 ``reason``。"""
    problems: List[str] = []
    for index, item in enumerate(items or [], start=1):
        data = (item.to_dict() if isinstance(item, RuleJustification)
                else dict(item or {}))
        where = f"第 {index} 条辩护"
        rule = _text(data.get("rule"))
        action = _text(data.get("action")) or "follow"
        if not rule:
            problems.append(f"{where}缺少 rule")
        if action not in RULE_ACTIONS:
            problems.append(
                f"{where}的 action={action!r} 不在闭集内（{'、'.join(RULE_ACTIONS)}）")
        if action == "break" and not _text(data.get("reason")):
            problems.append(f"{where}声明破例却没写 reason")
    return problems


def reconcile_justifications(justifications: Sequence[Any],
                             detected_rules: Sequence[str]) -> Dict[str, Any]:
    """把**声明**的破例辩护与**实测**的违规对拍（TDD §5.4 / 卡 P4-T4）。

    它是纯函数：输入一边是计划里这一镜的 ``rule_justifications``（LLM 声明
    "我遵守/我有意违反哪条规则"），另一边是审核器这一次真的报出来的规则
    （``AuditResult.errors``/``warnings`` 的 ``rule``）。输出**只记录、不设门**
    ——"要不要拿它当门"是 OPEN_ITEMS D11 的议题，须用户裁决（红线 R-5）。

    四个派生集合（TDD §5.4 的命名，一个不改）：

    * ``declared_breaks``：声明 ``action=break`` 的规则集；
    * ``detected_violations``：审核器实际报出的规则集；
    * ``undeclared_violations = detected − declared_breaks``：**没说就破了**——
      这是最该被人看到的一栏；
    * ``declared_but_clean = declared_breaks − detected``：**说了却没破**
      （模型过度自我辩护，或审核器没测到）。

    比对是**字面相等**：``rule`` 写的是边 id / 规则名，审核器报的是 ``R001``
    这种规则名——不做模糊匹配（猜名字正是 F2 要堵的洞）。顺序按输入出现顺序
    去重，保证同一输入两次调用逐字节相同。

    ``declared_follows`` 是额外的一栏（声明遵守了哪些）：它不参与上面两个差集，
    只在交付清单里留痕，让"引用过哪些规则"可对拍（PRD FR-8 的"规则的最大价值
    不在被遵守，而在被引用"）。
    """
    declared_breaks: List[str] = []
    declared_follows: List[str] = []
    for item in justifications or []:
        data = (item.to_dict() if isinstance(item, RuleJustification)
                else dict(item or {}))
        rule = _text(data.get("rule"))
        if not rule:
            continue
        if (_text(data.get("action")) or "follow") == "break":
            if rule not in declared_breaks:
                declared_breaks.append(rule)
        elif rule not in declared_follows:
            declared_follows.append(rule)

    detected: List[str] = []
    for rule in detected_rules or []:
        text = _text(rule)
        if text and text not in detected:
            detected.append(text)

    return {
        "declared_breaks": declared_breaks,
        "declared_follows": declared_follows,
        "detected_violations": detected,
        "undeclared_violations": [r for r in detected
                                  if r not in declared_breaks],
        "declared_but_clean": [r for r in declared_breaks
                               if r not in detected],
    }


__all__ = [
    "ShotBeat", "LightSpec", "CompositionSpec", "RuleJustification",
    "BEAT_VERBS", "MAX_BEATS", "FACE_TO_VALUES", "PACE_VALUES",
    "TIME_OF_DAY_VALUES", "LIGHT_MOOD_VALUES", "KEY_DIRECTION_VALUES",
    "COMPOSITION_RULES", "SUBJECT_POSITIONS", "RULE_ACTIONS",
    "ENTRANCE_ACTIONS", "PROP_ACTIONS",
    "validate_beats", "validate_light_spec", "validate_composition_spec",
    "validate_justifications", "reconcile_justifications",
]
