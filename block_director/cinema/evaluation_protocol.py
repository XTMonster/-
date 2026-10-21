"""空间尺多维评测的统一采样对象与三类结论（主 spec §3.1/§3.2/§7）。

纯 Python 类型层，不依赖 bpy。评测台（Ticket 04–11）一律以这里的
采样对象承载画面事实，输出统一 Measurement / Finding / Prescription。

术语约定（用户 2026-10-13 裁决）：只使用「内容关键帧 / 动作关键帧」，
不接受混用「关键帧」指代两者。

对象关系（§3.1）：
* FrameSample    —— 镜头中的一个采样帧（相机 + 角色/道具 + 投影盒 + 可见性）；
* ContentFrame   —— 内容关键帧：按镜头内容覆盖选取，至少含首帧、中帧、末帧；
* ActionFrame    —— 动作关键帧：动作起点、接触点、反应结束；
* ShotSample     —— 内容关键帧与动作关键帧的并集，至少含首/中/末帧 + 全部接触帧；
* SequenceSample —— 按剪辑顺序排列的相邻镜头集合；
* IntentContract —— 剧本/分镜声明的镜头意图。

输出契约（§3.1/§7）：
* Measurement：指标名、原始值、归一化分数、目标区间、证据帧、置信度；
* Finding：失败项 + 严重度（fatal/error/warning/note）；
* Prescription：component/severity/current/target/allowed_tools/
  direction/expected_effect，与 §7 JSON 逐字段一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from .composition import SubjectBox


# --------------------------------------------------------------------------- #
# 严重度
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    """失败严重度（§5.3）。"""

    FATAL = "fatal"        # 必须修复，不能只用 warning 通过
    ERROR = "error"        # 镜头不通过，允许处方后复测
    WARNING = "warning"    # 不阻断交付，进入报告与回归比较
    NOTE = "note"          # 仅记录设计信息


def middle_frame(first: int, last: int) -> int:
    """镜头的规范中帧：``(first + last) // 2``（确定性，向下取整）。"""
    return (int(first) + int(last)) // 2


# --------------------------------------------------------------------------- #
# 单帧采样
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProjectedSubject:
    """帧内的一个角色/道具投影：包围盒 + 可见比例。"""

    subject_id: str
    box: SubjectBox
    kind: str = "character"       # character / prop
    visible_ratio: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in ("character", "prop"):
            raise ValueError(f"subject kind 必须是 character/prop：{self.kind!r}")
        if not 0.0 <= self.visible_ratio <= 1.0:
            raise ValueError("visible_ratio 必须在 [0,1] 区间")


@dataclass(frozen=True)
class FrameSample:
    """镜头中的一个采样帧（§3.1）：相机、角色、道具、投影盒、可见性。"""

    frame: int
    subjects: Tuple[ProjectedSubject, ...] = ()
    camera_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    camera_forward: Tuple[float, float, float] = (0.0, 0.0, -1.0)
    camera_up: Tuple[float, float, float] = (0.0, 1.0, 0.0)
    vfov_deg: float = 35.0
    aspect: float = 16.0 / 9.0
    lens: float = 35.0
    roll_deg: float = 0.0
    shot_id: str = ""

    def __post_init__(self) -> None:
        if int(self.frame) <= 0:
            raise ValueError("frame 必须 >= 1")
        if self.vfov_deg <= 0.0 or self.aspect <= 0.0:
            raise ValueError("vfov/aspect 必须为正")

    def subject(self, subject_id: str) -> Optional[ProjectedSubject]:
        """按 id 取投影；缺省返回 None（帧里没有该主体）。"""
        for item in self.subjects:
            if item.subject_id == subject_id:
                return item
        return None


# --------------------------------------------------------------------------- #
# 内容关键帧 / 动作关键帧 / 镜头采样 / 镜头序列采样
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ContentFrame:
    """内容关键帧：按镜头内容覆盖选取的采样帧，至少包含首帧、中帧、末帧。"""

    shot_id: str
    frame_range: Tuple[int, int]
    frames: Tuple[FrameSample, ...]

    def __post_init__(self) -> None:
        first, last = self.frame_range
        if first > last:
            raise ValueError("frame_range 必须 first <= last")
        if len(self.frames) < 3:
            raise ValueError("内容关键帧至少需要首帧、中帧、末帧 3 个采样帧")
        numbers = [f.frame for f in self.frames]
        if numbers != sorted(numbers) or len(set(numbers)) != len(numbers):
            raise ValueError("内容关键帧必须按帧号严格递增且不重复")
        if numbers[0] != first or numbers[-1] != last:
            raise ValueError("内容关键帧必须覆盖镜头的首帧与末帧")
        if middle_frame(first, last) not in numbers:
            raise ValueError(f"内容关键帧缺少规范中帧 {middle_frame(first, last)}")
        if numbers[0] < first or numbers[-1] > last:
            raise ValueError("内容关键帧帧号超出镜头帧范围")

    @classmethod
    def from_shot(cls, shot_id: str, frame_range: Sequence[int],
                  frames: Sequence[FrameSample]) -> "ContentFrame":
        """按镜头帧范围构造内容关键帧（校验首/中/末覆盖）。"""
        return cls(shot_id=shot_id, frame_range=tuple(frame_range),
                   frames=tuple(frames))


@dataclass(frozen=True)
class ActionFrame:
    """动作关键帧：动作起点、接触点、反应结束（§3.1）。"""

    shot_id: str
    start: FrameSample
    contacts: Tuple[FrameSample, ...]
    reaction_end: FrameSample

    def __post_init__(self) -> None:
        if not self.contacts:
            raise ValueError("动作关键帧至少需要一个接触帧")
        contacts = sorted(f.frame for f in self.contacts)
        if len(set(contacts)) != len(contacts):
            raise ValueError("动作接触帧帧号必须不重复")
        if self.start.frame >= contacts[0]:
            raise ValueError("动作起点帧必须早于接触帧")
        if contacts[-1] >= self.reaction_end.frame:
            raise ValueError("反应结束帧必须晚于所有接触帧")

    @property
    def contact_frames(self) -> Tuple[FrameSample, ...]:
        return self.contacts


@dataclass(frozen=True)
class ShotSample:
    """镜头采样：内容关键帧与动作关键帧的并集（§3.1）。

    不变量：至少包含首帧、中帧、末帧以及所有动作接触帧；所有帧号落在
    ``frame_range`` 内。``frames`` 按帧号升序去重返回并集。
    """

    shot_id: str
    frame_range: Tuple[int, int]
    content: ContentFrame
    actions: Tuple[ActionFrame, ...] = ()

    def __post_init__(self) -> None:
        first, last = self.frame_range
        if self.content.shot_id != self.shot_id:
            raise ValueError("内容关键帧的 shot_id 与镜头采样不一致")
        if tuple(self.content.frame_range) != tuple(self.frame_range):
            raise ValueError("内容关键帧帧范围与镜头采样不一致")
        numbers = [f.frame for f in self.content.frames]
        for action in self.actions:
            if action.shot_id != self.shot_id:
                raise ValueError("动作关键帧的 shot_id 与镜头采样不一致")
            numbers.extend(f.frame for f in (
                action.start, *action.contacts, action.reaction_end))
        if any(n < first or n > last for n in numbers):
            raise ValueError("采样帧号超出镜头帧范围")

    @property
    def frames(self) -> Tuple[FrameSample, ...]:
        """内容关键帧与动作关键帧的并集，按帧号升序去重。"""
        by_frame: Dict[int, FrameSample] = {}
        for frame in self.content.frames:
            by_frame[frame.frame] = frame
        for action in self.actions:
            for frame in (action.start, *action.contacts, action.reaction_end):
                by_frame[frame.frame] = frame
        return tuple(by_frame[n] for n in sorted(by_frame))

    @property
    def contact_frames(self) -> Tuple[FrameSample, ...]:
        """全部动作接触帧（顺序与声明一致）。"""
        out: List[FrameSample] = []
        for action in self.actions:
            out.extend(action.contacts)
        return tuple(out)


@dataclass(frozen=True)
class SequenceSample:
    """镜头序列采样：按剪辑顺序排列的相邻镜头集合（§3.1）。"""

    shots: Tuple[ShotSample, ...]

    def __post_init__(self) -> None:
        if not self.shots:
            raise ValueError("镜头序列至少需要一个镜头")
        previous_end: Optional[int] = None
        previous_id: Optional[str] = None
        for shot in self.shots:
            if shot.shot_id == previous_id:
                raise ValueError(f"镜头 id 重复：{shot.shot_id}")
            if previous_end is not None and shot.frame_range[0] <= previous_end:
                raise ValueError(
                    f"镜头 {shot.shot_id} 与上一镜重叠或顺序颠倒")
            previous_end = shot.frame_range[1]
            previous_id = shot.shot_id


# --------------------------------------------------------------------------- #
# 意图契约
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IntentContract:
    """剧本/分镜声明的镜头意图（§3.1），供意图层与连续性层比对。"""

    shot_id: str
    intent: str = ""                      # 例如「建立环境」「突出攻击者」
    subject: str = ""                     # 本镜意图主体
    shot_type: str = ""                   # 声明景别
    beats: Tuple[str, ...] = ()           # 节拍描述（按剧本顺序）
    gaze_target: Optional[str] = None     # 视线目标 id
    axis_side: Optional[str] = None       # 声明的轴侧（positive/negative）
    declared_exit_frame: int = 0          # 声明离场帧（0 = 未声明）
    camera_movements: Tuple[str, ...] = ()  # 声明运镜
    props: Tuple[str, ...] = ()           # 关键道具 id

    def to_dict(self) -> Dict[str, object]:
        return {
            "shot_id": self.shot_id,
            "intent": self.intent,
            "subject": self.subject,
            "shot_type": self.shot_type,
            "beats": list(self.beats),
            "gaze_target": self.gaze_target,
            "axis_side": self.axis_side,
            "declared_exit_frame": self.declared_exit_frame,
            "camera_movements": list(self.camera_movements),
            "props": list(self.props),
        }


# --------------------------------------------------------------------------- #
# 输出契约：Measurement / Finding / Prescription / EvaluationOutput
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TargetInterval:
    """目标区间：``min/max`` 任一可缺省；``contains`` 判是否达标。

    端点默认包含以保持既有指标语义。严格下界（例如构图分量必须
    ``> 0.8``）通过 ``min_inclusive=False`` 显式表达，不能用浮点 epsilon
    或其他近似边界冒充数学开区间。
    """

    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_inclusive: bool = True
    max_inclusive: bool = True

    def contains(self, value: float) -> bool:
        if self.min_value is not None:
            if value < self.min_value:
                return False
            if value == self.min_value and not self.min_inclusive:
                return False
        if self.max_value is not None:
            if value > self.max_value:
                return False
            if value == self.max_value and not self.max_inclusive:
                return False
        return True

    def to_dict(self) -> Dict[str, object]:
        out: Dict[str, object] = {}
        if self.min_value is not None:
            out["min"] = self.min_value
            if not self.min_inclusive:
                out["min_inclusive"] = False
        if self.max_value is not None:
            out["max"] = self.max_value
            if not self.max_inclusive:
                out["max_inclusive"] = False
        return out


@dataclass(frozen=True)
class Measurement:
    """统一测量：指标名、原始值、归一化分数、目标区间、证据帧、置信度。"""

    metric: str
    raw_value: float
    score: float
    target: TargetInterval
    evidence_frames: Tuple[int, ...] = ()
    confidence: float = 1.0
    evidence_grade: str = "demo"          # demo / production / plumbing

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score 必须在 [0,1] 区间")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence 必须在 [0,1] 区间")

    def to_dict(self) -> Dict[str, object]:
        return {
            "metric": self.metric,
            "raw_value": round(float(self.raw_value), 6),
            "score": round(float(self.score), 6),
            "target": self.target.to_dict(),
            "evidence_frames": list(self.evidence_frames),
            "confidence": round(float(self.confidence), 6),
            "evidence_grade": self.evidence_grade,
        }


@dataclass(frozen=True)
class Finding:
    """失败项：分量 + 严重度 + 证据帧（§3.1/§3.2）。"""

    component: str
    severity: Severity
    message: str
    evidence_frames: Tuple[int, ...] = ()
    gate: Optional[str] = None             # 联动 H1–H6 编号

    def to_dict(self) -> Dict[str, object]:
        return {
            "component": self.component,
            "severity": self.severity.value,
            "message": self.message,
            "evidence_frames": list(self.evidence_frames),
            "gate": self.gate,
        }


@dataclass(frozen=True)
class Prescription:
    """处方目标契约（§7 JSON）：只描述可执行方向、参数范围与预期影响。"""

    component: str
    severity: Severity
    current: float
    target: TargetInterval
    allowed_tools: Tuple[str, ...] = ()
    direction: str = ""
    expected_effect: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "component": self.component,
            "severity": self.severity.value,
            "current": round(float(self.current), 6),
            "target": self.target.to_dict(),
            "allowed_tools": list(self.allowed_tools),
            "direction": self.direction,
            "expected_effect": list(self.expected_effect),
        }


@dataclass(frozen=True)
class EvaluationOutput:
    """一次评测的输出：测量 + 失败项（+ 意图留痕）。"""

    shot_id: str
    measurements: Tuple[Measurement, ...] = ()
    findings: Tuple[Finding, ...] = ()
    intent: Optional[IntentContract] = None

    def render(self) -> str:
        """LLM 可读读数（术语固定使用「内容关键帧 / 动作关键帧」）。"""
        lines = [f"镜头 {self.shot_id} 评测读数："]
        if self.intent is not None:
            lines.append(f"- 声明意图：{self.intent.intent or '（未声明）'}")
        if self.measurements:
            lines.append("测量：")
            for m in self.measurements:
                lines.append(
                    f"  - {m.metric}：原始 {m.raw_value:.3f}，归一化 "
                    f"{m.score:.3f}，目标 {m.target.to_dict()}，"
                    f"证据帧 {m.evidence_frames}，置信度 {m.confidence:.2f}，"
                    f"证据等级 {m.evidence_grade}")
        if self.findings:
            lines.append("失败项：")
            for f in self.findings:
                gate = f"（硬门 {f.gate}）" if f.gate else ""
                lines.append(f"  - {f.component} [{f.severity.value}]{gate} "
                             f"{f.message}，证据帧 {f.evidence_frames}")
        lines.append("采样构成：内容关键帧 + 动作关键帧（首/中/末与接触帧并集）")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, object]:
        return {
            "shot_id": self.shot_id,
            "measurements": [m.to_dict() for m in self.measurements],
            "findings": [f.to_dict() for f in self.findings],
            "intent": self.intent.to_dict() if self.intent else None,
        }


# --------------------------------------------------------------------------- #
# 冒烟链路（Ticket 01）：构造镜头采样 -> 产出测量与失败项
# --------------------------------------------------------------------------- #
def smoke_evaluate(shot: ShotSample,
                   intent: Optional[IntentContract] = None
                   ) -> EvaluationOutput:
    """冒烟示例：用镜头采样的可见性事实产生测量与失败项。

    这不是正式指标（正式指标见 Ticket 02 注册表与 04–10 各层实现）；
    它只证明「镜头采样 -> Measurement/Finding」链路成立，确定性可复现，
    证据等级固定为 demo。
    """
    frames = shot.frames
    primary_id = _primary_character_id(shot)
    ratios: List[float] = []
    evidence: List[int] = []
    for frame in frames:
        evidence.append(frame.frame)
        item = frame.subject(primary_id)
        ratios.append(item.visible_ratio if item is not None else 0.0)
    raw = sum(ratios) / len(ratios) if ratios else 0.0

    measurements = (
        Measurement(
            metric="smoke_primary_visibility",
            raw_value=raw,
            score=raw,
            target=TargetInterval(min_value=0.70),
            evidence_frames=tuple(evidence),
            confidence=1.0,
            evidence_grade="demo",
        ),
    )

    findings: List[Finding] = []
    bad_contacts: List[int] = []
    for contact in shot.contact_frames:
        item = contact.subject(primary_id)
        visible = item.visible_ratio if item is not None else 0.0
        if visible < 0.70:
            bad_contacts.append(contact.frame)
    if bad_contacts:
        findings.append(Finding(
            component="contact_point_visibility",
            severity=Severity.FATAL,
            message=(f"动作接触帧 {bad_contacts} 攻击者/受击者不可辨"
                     f"（可见比例 < 0.70）"),
            evidence_frames=tuple(bad_contacts),
            gate="H2",
        ))
    return EvaluationOutput(shot_id=shot.shot_id,
                            measurements=measurements,
                            findings=tuple(findings),
                            intent=intent)


def _primary_character_id(shot: ShotSample) -> str:
    """画内最大的角色作主锚（与 composition 主锚语义同源），id 升序决胜。"""
    candidates: List[ProjectedSubject] = []
    seen: set[str] = set()
    for frame in shot.frames:
        for item in frame.subjects:
            if item.kind != "character" or item.subject_id in seen:
                continue
            seen.add(item.subject_id)
            candidates.append(item)
    if not candidates:
        return ""
    return max(candidates, key=lambda c: (c.box.inside_ratio() > 0.05,
                                          c.box.height,
                                          c.subject_id)).subject_id


__all__ = [
    "Severity", "middle_frame", "ProjectedSubject", "FrameSample",
    "ContentFrame", "ActionFrame", "ShotSample", "SequenceSample",
    "IntentContract", "TargetInterval", "Measurement", "Finding",
    "Prescription", "EvaluationOutput", "smoke_evaluate",
]
