"""分镜计划契约（执行文档 v1.2 §7.2 / §16.1）。

``ShotPlan`` 是阶段 A 的产物，也是 ``emit_plan`` 工具的参数形态。
放在 contracts 下是为了让插件侧与 sidecar 侧共享同一份定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .enums import SHOT_TYPES, ShotType

FPS = 24

#: ``shot_id`` 会被直接拼进导出路径
#: （``blockout_<shot_id>.mp4`` / ``first_frames/<shot_id>.png`` /
#: ``depth_shot_<shot_id>/``），所以它**不是**自由文本：
#: 合同边界必须把它限制在一个安全的字符集里。旧实现照单全收，
#: 于是计划里写 ``../../../../Users/Public/x`` 就能把文件写到导出目录之外
#: （LLM 输出、手改的 project.bdproj、重放的旧日志都是入口）。
SHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

#: framing_target 的闭集取值（T3 单一真源；schema 与提示从这里引用，不手抄）。
FRAMING_TARGET_KINDS = ("character", "prop")
FRAMING_TARGET_PARTS = ("hand", "face", "none")


def validate_shot_id(value: object, *, where: str = "shot_id") -> str:
    """校验并返回 ``shot_id``；非法一律抛 ``ValueError``（不做静默修正）。"""
    text = str(value or "")
    if not text:
        raise ValueError(f"{where} 不能为空")
    if not SHOT_ID_PATTERN.match(text) or ".." in text:
        raise ValueError(
            f"{where} 只能由字母/数字/下划线/短横线/点组成（1–64 字符），"
            f"且不得包含 '..'（当前 {text!r}）；它会被用作导出文件名")
    return text


def unknown_cast_members(ids: Sequence[str], roster: Sequence[str]) -> List[str]:
    """返回不在角色表中的 id（成员级；v1.6 A2 的草案入口也用它）。

    ``roster`` 同时包含角色名与已分配的内部 id（如 ``char_001``）。
    纯函数；不抛出异常。``roster`` 为空时**什么都拒绝**——调用方应像
    ``_accept_plan_chunk`` 那样先判 ``if roster:``（空表 = 没有角色表可查，
    语义是"未知"，不是"全不合法"）。
    """
    allowed = set(str(item) for item in (roster or ()) if item is not None)
    return sorted({str(cid) for cid in (ids or ()) if str(cid) not in allowed})


def unknown_cast_ids(plan: "Plan", roster: Sequence[str]) -> List[str]:
    """返回计划里出现、但不在角色表中的 id（v1.6 A2 / D-11）。

    判据与 :func:`unknown_cast_members` 同源——计划入口与草案入口核的是
    同一件事，不许各抄一份。
    """
    ids: List[str] = []
    for shot in (plan.shots or ()):
        ids.extend(shot.characters or ())
    return unknown_cast_members(ids, roster)


@dataclass
class Responsibility:
    """v1.7 §14.1（R-痛点 M5，P14 职责分区）：一镜的分工声明。

    ``None = 未声明``（≠ 全空），未声明镜全链零行为差。
    ``skip_white_model`` 的**执行语义**在卡 J3（本卡只落数据）。
    """

    white_model: List[str] = field(default_factory=list)  # 白模管：位置/机位/节奏…
    prompt: List[str] = field(default_factory=list)       # 移交提示词：动作细节/表情…
    ref_image: List[str] = field(default_factory=list)    # 移交参考图：外观/风格…
    skip_white_model: bool = False                        # 本镜跳过白模（P16）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "white_model": list(self.white_model),
            "prompt": list(self.prompt),
            "ref_image": list(self.ref_image),
            "skip_white_model": bool(self.skip_white_model),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Responsibility":
        return cls(
            white_model=[str(item) for item in
                         (data.get("white_model") or [])],
            prompt=[str(item) for item in (data.get("prompt") or [])],
            ref_image=[str(item) for item in (data.get("ref_image") or [])],
            skip_white_model=bool(data.get("skip_white_model") or False),
        )


@dataclass
class FramingTarget:
    """镜头"拍什么"声明（缺陷 A / R1，数据类真源）。

    ``kind=character`` 拍角色整体或局部部位（``part=hand|face|none``）；
    ``kind=prop`` 拍道具（``ref`` 为道具 id）。``anchor_offset`` 是可选的
    局部锚点偏移（无手部子网格时用锚点＋预设偏移，见 spec D1=A）。
    """

    kind: str = "character"                  # character | prop
    ref: str = ""                            # 角色 id 或道具 id
    part: str = "none"                       # hand | face | none
    anchor_offset: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": str(self.kind),
            "ref": str(self.ref),
            "part": str(self.part),
            "anchor_offset": (None if self.anchor_offset is None
                              else [float(v) for v in self.anchor_offset]),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FramingTarget":
        offset = data.get("anchor_offset")
        return cls(
            kind=str(data.get("kind") or "character"),
            ref=str(data.get("ref") or ""),
            part=str(data.get("part") or "none"),
            anchor_offset=([float(v) for v in offset] if offset else None),
        )


@dataclass
class ShotPlan:
    """一个镜头的计划。时长以帧为单位（唯一时长真源，§5.1）。"""

    shot_id: str
    intent: str
    shot_type: ShotType
    duration_frames: int
    order: int = 0
    characters: List[str] = field(default_factory=list)
    dialogue_ids: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    #: 对白时间轴（镜头内局部帧）：{character_id, text, start_frame, end_frame}
    dialogues: List[Dict[str, Any]] = field(default_factory=list)
    prompt: str = ""                 # 交付用：喂视频模型的镜头描述（§15.5）
    #: 相对取景请求（阶段 B1 产出）：{"side": ..., "lens": ...,
    #: "movements": [{"type", "amount", "start_frame", "end_frame", "seed"}]}。
    #: 距离与高度由 §10.6/§10.5 推导，不在这里覆盖；运镜由声明式消费落地（P7）。
    camera: Dict[str, Any] = field(default_factory=dict)
    axis_note: str = ""
    continuity_in: str = ""
    #: v1.3：谁看谁（``{from, to}``）。来源是阶段 S 的 SceneBrief 或 B1 的草案，
    #: R013 拿它与 SceneBrief 对拍。
    gaze: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.3：特效代理（``{id, type, position, size, start_frame, end_frame}``）。
    vfx: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.3：剧本声明的时长（帧）。**只作证据**，永不参与排片（§3.4 单一真源）。
    #: 它与 ``duration_frames`` 的差值就是 R015 的"声明 vs 落实"证据。
    declared_duration_frames: int = 0
    #: 剧本原句写的是“约X秒”时为 True。约数目标是可审计的规划下界：
    #: 可以为了容纳逐字台词延长，不得静默缩短；``duration_frames`` 仍是
    #: 唯一可执行时长真源。
    declared_duration_approximate: bool = False
    #: v1.4：分镜表声明的镜号（生产者 = P11 的 ``ParsedScript.declared_shots[]``，
    #: 按顺序钉入；模型的 ``emit_plan`` schema 里**没有**这个键）。
    #: 消费者 = R015/F4 的镜号/顺序/身份错位核对。
    declared_shot_number: int = 0
    #: v1.4 §2.3b（Q5 的入口形状）：分镜表声明的**拍摄手法**（生产者 =
    #: `ParsedShotDeclaration.camera_move`，按顺序钉入）。它是**检索前已知的
    #: 输入**，逐镜检索的契约串要拿它挂种子——引擎运镜词表里没有"固定"
    #: （锁机位＝不动），但**查询**词表里有 `运镜=固定`；不把声明留在这里，
    #: 锁机位的镜头在超图那一栏一个运镜种子都没有（实测 2026-10-03：
    #: `shotlist_market` 第 1 镜声明"固定镜头"，而发出的查询只有 `景别=MCU`）。
    declared_camera_move: str = ""
    #: v1.5 §2.3d T3（**意图轴**）：这一镜"导演/角色想干什么"的**闭集取值**
    #: （12 个中文值，唯一真源 = `knowledge/hypergraph.py::VALUE_DOMAINS["intent"]`）。
    #: 生产者 = 阶段 A 的 `emit_plan`（schema 里带 enum）；消费者 = 逐镜检索的
    #: 契约串（`shot_constraint_query` 的 `意图=` 键）。
    #: 为什么它是**计划决策**而不是自由文本：`INTENT_PACK`（意图×镜头语言）是
    #: 超图里被检索最多的一类边（实测 64 镜那一跑，shot 域 231/320 次命中的是它），
    #: 而 `意图=` 此前**从来不在发出的查询里**——检索只能靠"景别＋运镜"猜意图，
    #: 拿回来的"意图知识"与这一镜真正要做什么无关。闭集才能被机器对拍，
    #: 自由文本的 `intent` 仍然是人读的展示字段，两者不互相取代。
    intent_type: str = ""
    #: v1.4：台词钉住的证据链（§3.3 的 ``dialogue_pins[]``）。元素形如
    #: ``{shot_number, speaker_raw, speaker_status, declared_s, model_text,
    #: applied_s}``。生产者 = driver，消费者 = RK-7 的三方对拍。
    dialogue_pins: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.5 §3.7（P2-T2 / FR-1）：**执行拍点表**（一镜内的动作时刻表）。
    #: 元素形如 ``{t, subject, verb, target, face_to, pace, react}``，
    #: 数据类真源 = ``contracts/beats.py::ShotBeat``。**命名消歧**：这里的
    #: ``beats`` 是**执行拍点**，不是 ``contracts/brief.py::SceneBrief.beats``
    #: 的**叙事节拍**（概念／生产者／消费者都不同，不得互相喂入）。帧号由
    #: ``layer5_orchestrator/beat_compiler.py`` 从 ``t`` 换算，契约里不写帧号。
    beats: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.5 §3.5（P2-T2 / FR-10）：构图声明，数据类真源 =
    #: ``contracts/beats.py::CompositionSpec``（``{rule, subject_position}``）。
    #: 空 = 求解器默认（**零行为差**）。
    composition: Dict[str, Any] = field(default_factory=dict)
    #: v1.5 §3.6（P2-T2 / FR-8）：破例辩护，数据类真源 =
    #: ``contracts/beats.py::RuleJustification``（``{rule, action, reason,
    #: precedent}``）。审计对拍见 §5.4。
    rule_justifications: List[Dict[str, Any]] = field(default_factory=list)
    #: v1.7 §14.1（R-痛点 M5）：分工声明。None = 未声明（≠ 全空），
    #: 未声明镜全链零行为差。数据类真源 = :class:`Responsibility`。
    responsibility: Optional[Responsibility] = None
    #: 缺陷 A / R1：这一镜"拍谁"（角色/局部部位/道具）。None = 未声明
    #: （构图评分退回整身口径，零行为差）。
    framing_target: Optional[FramingTarget] = None

    @property
    def duration_seconds(self) -> float:
        return self.duration_frames / FPS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "order": self.order,
            "intent": self.intent,
            "shot_type": str(self.shot_type),
            "duration_frames": self.duration_frames,
            "characters": list(self.characters),
            "dialogue_ids": list(self.dialogue_ids),
            "actions": [dict(a) for a in self.actions],
            "dialogues": [dict(d) for d in self.dialogues],
            "prompt": self.prompt,
            "camera": dict(self.camera),
            "axis_note": self.axis_note,
            "continuity_in": self.continuity_in,
            "gaze": [dict(item) for item in self.gaze],
            "vfx": [dict(item) for item in self.vfx],
            "declared_duration_frames": self.declared_duration_frames,
            "declared_duration_approximate":
                bool(self.declared_duration_approximate),
            "declared_shot_number": self.declared_shot_number,
            "declared_camera_move": self.declared_camera_move,
            "intent_type": self.intent_type,
            "dialogue_pins": [dict(item) for item in self.dialogue_pins],
            "beats": [dict(item) for item in self.beats],
            "composition": dict(self.composition),
            "rule_justifications": [dict(item)
                                    for item in self.rule_justifications],
            #: 恒出键（v1.7.6 实测钉死）：serde 无条件序列化全部字段，
            #: 未声明时是 null、声明了是对象；from_plain 对缺失键落默认值，
            #: 旧 SDL/plan 文件零 error。
            "responsibility": (None if self.responsibility is None
                               else self.responsibility.to_dict()),
            "framing_target": (None if self.framing_target is None
                               else self.framing_target.to_dict()),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShotPlan":
        raw_type = str(data.get("shot_type", "MS")).upper()
        shot_type = ShotType(raw_type) if raw_type in SHOT_TYPES else ShotType.MS
        return cls(
            shot_id=validate_shot_id(data["shot_id"]),
            intent=str(data.get("intent", "")),
            shot_type=shot_type,
            duration_frames=int(data["duration_frames"]),
            order=int(data.get("order", 0)),
            characters=list(data.get("characters", []) or []),
            dialogue_ids=list(data.get("dialogue_ids", []) or []),
            actions=[dict(a) for a in (data.get("actions") or [])],
            dialogues=[dict(d) for d in (data.get("dialogues") or [])],
            prompt=str(data.get("prompt", "")),
            camera=dict(data.get("camera") or {}),
            axis_note=str(data.get("axis_note", "")),
            continuity_in=str(data.get("continuity_in", "")),
            gaze=[dict(item) for item in (data.get("gaze") or [])
                  if isinstance(item, dict)],
            vfx=[dict(item) for item in (data.get("vfx") or [])
                 if isinstance(item, dict)],
            declared_duration_frames=int(data.get("declared_duration_frames")
                                         or 0),
            declared_duration_approximate=bool(
                data.get("declared_duration_approximate") or False),
            declared_shot_number=int(data.get("declared_shot_number") or 0),
            declared_camera_move=str(data.get("declared_camera_move") or ""),
            intent_type=str(data.get("intent_type") or ""),
            dialogue_pins=[dict(item)
                           for item in (data.get("dialogue_pins") or [])
                           if isinstance(item, dict)],
            beats=[dict(item) for item in (data.get("beats") or [])
                   if isinstance(item, dict)],
            composition=dict(data.get("composition") or {}),
            rule_justifications=[dict(item)
                                 for item in (data.get("rule_justifications") or [])
                                 if isinstance(item, dict)],
            responsibility=(Responsibility.from_dict(data["responsibility"])
                            if isinstance(data.get("responsibility"), dict)
                            else None),
            framing_target=(FramingTarget.from_dict(data["framing_target"])
                            if isinstance(data.get("framing_target"), dict)
                            else None),
        )


@dataclass
class Plan:
    """整场计划：镜头序列 + 连续性备注。"""

    shots: List[ShotPlan] = field(default_factory=list)
    continuity_notes: List[str] = field(default_factory=list)
    scene_heading: str = ""
    #: v1.5 §3.2（P2-T2 / FR-2/FR-3）：**场级环境的契约宿主**。此前场级
    #: 环境（锚点、灯光语义）没有契约宿主，道具摆位只能靠坐标直写。
    #: 形状：``{"anchors": [SDLAnchor 的 dict 形...], "light": LightSpec 的
    #: dict 形}``。生产者 = 阶段 A 的 ``emit_plan``（场级信息密度低、一次生成
    #: 全场共用）；阶段 B1 **不得改写**它。缺省空 dict = 与 v1.4 逐字同行为。
    environment: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_frames(self) -> int:
        return sum(s.duration_frames for s in self.shots)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_heading": self.scene_heading,
            "continuity_notes": list(self.continuity_notes),
            "shots": [s.to_dict() for s in self.shots],
            "environment": dict(self.environment),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        shots = [ShotPlan.from_dict(s) for s in data.get("shots", [])]
        for index, shot in enumerate(shots, start=1):
            if not shot.order:
                shot.order = index
        return cls(
            shots=shots,
            continuity_notes=list(data.get("continuity_notes", []) or []),
            scene_heading=str(data.get("scene_heading", "")),
            environment=dict(data.get("environment") or {}),
        )


def timing_overrides_from_plan(plan: "Plan", *, fps: int = FPS
                               ) -> List[Dict[str, Any]]:
    """Derive auditable declared-vs-applied duration revisions from a plan.

    The plan is the durable source shared by resume, SDL and replay.  Keeping
    this derivation beside the wire contract prevents the driver and replay
    exporter from disagreeing about whether an approximate target was extended
    or an exact declaration drifted.
    """
    overrides: List[Dict[str, Any]] = []
    for shot in plan.shots:
        declared_frames = int(shot.declared_duration_frames or 0)
        if declared_frames <= 0:
            continue
        declared_s = declared_frames / float(fps)
        applied_s = round(int(shot.duration_frames) / float(fps), 3)
        if abs(applied_s - declared_s) <= 0.2:
            continue
        approximate = bool(shot.declared_duration_approximate)
        if approximate and applied_s >= declared_s:
            reason = (
                "规划级修订：约数时长目标"
                f" {declared_s:g}s 为容纳声明台词延长，"
                f"计划采用 {applied_s:g}s；原声明帧仍保留")
        elif approximate:
            reason = (
                "约数时长目标被缩短："
                f" {declared_s:g}s → {applied_s:g}s；"
                "须在进入粗排前修正")
        else:
            reason = "计划时长与精确声明不一致（R015 会单独报）"
        overrides.append({
            "shot_id": str(shot.shot_id),
            "shot_number": int(shot.declared_shot_number or shot.order),
            "declared_s": declared_s,
            "engine_s": None,
            "applied_s": applied_s,
            "declaration_kind": "approximate" if approximate else "exact",
            "reason": reason,
        })
    return overrides


#: 粗排通过后，B1 与后续修复只能细化这些镜头字段的**外围内容**
#: （动作、对白、提示词、相机请求等）；镜头身份仍由 R2 S2 冻结。
_COARSE_IDENTITY_SHOT_FIELDS = (
    "shot_id", "order", "shot_type", "characters", "framing_target",
)


def coarse_plan_identity_drift(approved: Any, current: Any) -> List[str]:
    """Return the frozen shot-identity fields that moved after coarse approval.

    A checkpoint is expected to evolve after the coarse gate: B1 adds actions,
    dialogue timing, prompts, gaze and camera intent, while repairs may refine
    those same fields.  Comparing the complete serialized plan therefore
    rejects a valid resume even though its physical coarse evidence still
    describes the same shots.  The coarse evidence is bound to the shot shell
    below; camera/manifest integrity is verified separately by fingerprints.
    """
    before = (approved.to_dict() if isinstance(approved, Plan)
              else dict(approved) if isinstance(approved, Mapping) else {})
    after = (current.to_dict() if isinstance(current, Plan)
             else dict(current) if isinstance(current, Mapping) else {})
    before_shots = list(before.get("shots") or [])
    after_shots = list(after.get("shots") or [])
    drift: List[str] = []
    if len(before_shots) != len(after_shots):
        drift.append(f"shots（{len(before_shots)} → {len(after_shots)}）")
    for index, (left, right) in enumerate(
            zip(before_shots, after_shots)):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            drift.append(f"shots[{index}]")
            continue
        for key in _COARSE_IDENTITY_SHOT_FIELDS:
            if left.get(key) != right.get(key):
                drift.append(f"shots[{index}].{key}")
    return drift
