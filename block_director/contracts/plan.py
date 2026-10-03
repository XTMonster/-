"""分镜计划契约（执行文档 v1.2 §7.2 / §16.1）。

``ShotPlan`` 是阶段 A 的产物，也是 ``emit_plan`` 工具的参数形态。
放在 contracts 下是为了让插件侧与 sidecar 侧共享同一份定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional

from .enums import SHOT_TYPES, ShotType

FPS = 24

#: ``shot_id`` 会被直接拼进导出路径
#: （``blockout_<shot_id>.mp4`` / ``first_frames/<shot_id>.png`` /
#: ``depth_shot_<shot_id>/``），所以它**不是**自由文本：
#: 合同边界必须把它限制在一个安全的字符集里。旧实现照单全收，
#: 于是计划里写 ``../../../../Users/Public/x`` 就能把文件写到导出目录之外
#: （LLM 输出、手改的 project.bdproj、重放的旧日志都是入口）。
SHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


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
    #: v1.4：台词钉住的证据链（§3.3 的 ``dialogue_pins[]``）。元素形如
    #: ``{shot_number, speaker_raw, speaker_status, declared_s, model_text,
    #: applied_s}``。生产者 = driver，消费者 = RK-7 的三方对拍。
    dialogue_pins: List[Dict[str, Any]] = field(default_factory=list)

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
            "declared_shot_number": self.declared_shot_number,
            "declared_camera_move": self.declared_camera_move,
            "dialogue_pins": [dict(item) for item in self.dialogue_pins],
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
            declared_shot_number=int(data.get("declared_shot_number") or 0),
            declared_camera_move=str(data.get("declared_camera_move") or ""),
            dialogue_pins=[dict(item)
                           for item in (data.get("dialogue_pins") or [])
                           if isinstance(item, dict)],
        )


@dataclass
class Plan:
    """整场计划：镜头序列 + 连续性备注。"""

    shots: List[ShotPlan] = field(default_factory=list)
    continuity_notes: List[str] = field(default_factory=list)
    scene_heading: str = ""

    @property
    def total_frames(self) -> int:
        return sum(s.duration_frames for s in self.shots)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene_heading": self.scene_heading,
            "continuity_notes": list(self.continuity_notes),
            "shots": [s.to_dict() for s in self.shots],
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
        )
