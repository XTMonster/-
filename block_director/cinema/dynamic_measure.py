"""打斗/动态多角色测量（spec 4.3 B+ 的最小落地切片）。

纯层、确定性、无 bpy。只报告几何与运动事实；不裁决动作观赏性，不设新通过门限。

设计（对应 spec 4.3.1-4.3.6）：
* 轨迹采样：把采样帧按角色归档，世界/NDC 坐标 + 朝向，首尾不丢；
* 速度档：按相邻世界位移/帧间隔分档（描述用，非通过门限）；
* 方向反转/出画/回冲：NDC 越界与朝向符号翻转 → 事件；
* 分层遮挡：按 subject/occluder/part/class/visible_ratio 归因，不猜声明；
* 银幕左右序状态机：NDC x 关系翻转 → visible/neutral/unbridged 三类；
* 高动态采样：事件帧附近标记 dense（轨迹加速）；
* 只读：不创建对象，不回写场景；报告可 JSON 序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence


# --------------------------------------------------------------------------- #
# 输入 DTO（demo：合成采样帧与遮挡声明；正式实现由 bpy 适配层填充）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Sample:
    frame: int
    character_id: str
    world_x: float
    world_y: float = 0.0
    world_z: float = 0.0
    ndc_x: float = 0.0
    ndc_y: float = 0.0
    facing_x: float = 0.0


@dataclass(frozen=True)
class OcclusionEvent:
    frame: int
    subject: str
    occluder: str
    occluder_class: str
    part: str
    visible_ratio: float


@dataclass(frozen=True)
class FightScene:
    samples: Sequence[Sample]
    occlusions: Sequence[OcclusionEvent] = ()
    shot_id: str = ""
    frame_range: tuple = (1, 1)


# --------------------------------------------------------------------------- #
# 输出 DTO
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TrackPoint:
    frame: int
    ndc_x: float
    ndc_y: float
    speed_band: str
    direction: str
    world_x: float = 0.0
    world_y: float = 0.0
    world_z: float = 0.0


@dataclass(frozen=True)
class CharacterTrack:
    character_id: str
    frames: Sequence[TrackPoint] = ()
    bands: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DynamicEvent:
    kind: str
    frame: int
    character_id: str = ""
    detail: str = ""


@dataclass(frozen=True)
class OcclusionSummary:
    subject: str
    occluder: str
    occluder_class: str
    part: str
    visible_ratio: float
    declared: bool = False


@dataclass(frozen=True)
class ScreenOrderFlip:
    kind: str
    frame: int
    character_a: str = ""
    character_b: str = ""
    detail: str = ""


@dataclass(frozen=True)
class SamplingSummary:
    step: int = 1
    dense_frames: List[int] = field(default_factory=list)
    total_frames: int = 0
    truncated: bool = False
    truncate_reason: str = ""


@dataclass(frozen=True)
class DynamicReport:
    shot_id: str
    trajectory: Dict[str, CharacterTrack]
    events: List[DynamicEvent]
    occlusion_summary: List[OcclusionSummary]
    screen_order_flips: List[ScreenOrderFlip]
    sampling: SamplingSummary

    def to_dict(self) -> dict:
        return {
            "shot_id": self.shot_id,
            "trajectory": {
                cid: {
                    "character_id": cid,
                    "bands": track.bands,
                    "frames": [f.__dict__ for f in track.frames],
                }
                for cid, track in self.trajectory.items()
            },
            "events": [e.__dict__ for e in self.events],
            "occlusion_summary": [o.__dict__ for o in self.occlusion_summary],
            "screen_order_flips": [f.__dict__ for f in self.screen_order_flips],
            "sampling": self.sampling.__dict__,
        }


# --------------------------------------------------------------------------- #
# 速度档
# --------------------------------------------------------------------------- #
def _speed_band(dx: float, dt: int) -> str:
    """按相邻世界位移/帧间隔分档：静止/慢/快/冲刺（描述用，非通过门限）。"""
    per_frame = abs(dx) / max(dt, 1)
    if per_frame < 0.1:
        return "静止"
    if per_frame < 0.5:
        return "慢"
    if per_frame < 1.0:
        return "快"
    return "冲刺"


def _as_sample(item) -> Sample:
    """把 dict 或 Sample 统一成 Sample（正式实现由 bpy 适配层填充）。"""
    if isinstance(item, Sample):
        return item
    return Sample(
        frame=int(item["frame"]),
        character_id=str(item["character_id"]),
        world_x=float(item.get("world_x", 0.0)),
        world_y=float(item.get("world_y", 0.0)),
        world_z=float(item.get("world_z", 0.0)),
        ndc_x=float(item.get("ndc_x", 0.0)),
        ndc_y=float(item.get("ndc_y", 0.0)),
        facing_x=float(item.get("facing_x", 0.0)),
    )


def _as_occlusion(item) -> OcclusionEvent:
    """把 dict 或 OcclusionEvent 统一成 OcclusionEvent。"""
    if isinstance(item, OcclusionEvent):
        return item
    return OcclusionEvent(
        frame=int(item["frame"]),
        subject=str(item["subject"]),
        occluder=str(item["occluder"]),
        occluder_class=str(item.get("occluder_class", "unknown")),
        part=str(item.get("part", "unknown")),
        visible_ratio=float(item.get("visible_ratio", 0.0)),
    )


# --------------------------------------------------------------------------- #
# 主分析
# --------------------------------------------------------------------------- #
def analyze_fight(scene: FightScene) -> DynamicReport:
    samples_by_char: Dict[str, List[Sample]] = {}
    for raw in scene.samples:
        s = _as_sample(raw)
        samples_by_char.setdefault(s.character_id, []).append(s)

    trajectory: Dict[str, CharacterTrack] = {}
    events: List[DynamicEvent] = []
    dense: set[int] = set()

    for cid, samples in samples_by_char.items():
        samples = sorted(samples, key=lambda s: s.frame)
        points: List[TrackPoint] = []
        bands: Dict[str, int] = {}
        was_off_frame: bool = False
        for i, s in enumerate(samples):
            prev = samples[i - 1] if i > 0 else None
            if prev is not None:
                dx = s.world_x - prev.world_x
                band = _speed_band(dx, s.frame - prev.frame)
                # 方向反转：朝向或行进方向符号翻转
                if (prev.facing_x > 1e-6 and s.facing_x < -1e-6) or \
                   (prev.facing_x < -1e-6 and s.facing_x > 1e-6):
                    events.append(DynamicEvent("direction_change", s.frame, cid,
                                               f"{prev.facing_x:+.0f}→{s.facing_x:+.0f}"))
                    dense.add(s.frame)
                if dx < -1e-6 or dx > 1e-6:
                    dense.add(s.frame)
            else:
                band = "静止"
            bands[band] = bands.get(band, 0) + 1
            direction = "右" if s.facing_x > 1e-6 else ("左" if s.facing_x < -1e-6 else "中")
            points.append(TrackPoint(s.frame, s.ndc_x, s.ndc_y, band, direction,
                                     s.world_x, s.world_y, s.world_z))

            # 出画 / 回冲
            off_frame = s.ndc_x < 0.0 or s.ndc_x > 1.0
            if off_frame:
                events.append(DynamicEvent("exit_frame", s.frame, cid,
                                           f"ndc_x={s.ndc_x:.2f}"))
                dense.add(s.frame)
            elif was_off_frame:
                events.append(DynamicEvent("reentry_frame", s.frame, cid,
                                           f"ndc_x={s.ndc_x:.2f}"))
                dense.add(s.frame)
            was_off_frame = off_frame
        trajectory[cid] = CharacterTrack(cid, tuple(points), dict(bands))

    # 遮挡归因（直接采用输入声明，不猜测）；同 subject/occluder/part 合并帧段
    occlusion_summary: List[OcclusionSummary] = []
    occ_group: Dict[tuple, list] = {}
    for raw in scene.occlusions:
        o = _as_occlusion(raw)
        key = (o.subject, o.occluder, o.occluder_class, o.part)
        occ_group.setdefault(key, []).append(o)
    for key, group in occ_group.items():
        subject, occluder, cls, part = key
        frames = sorted(o.frame for o in group)
        occlusion_summary.append(OcclusionSummary(
            subject, occluder, cls, part,
            round(sum(o.visible_ratio for o in group) / len(group), 3),
            declared=True))

    # 银幕左右序状态机：两侧角色 NDC x 关系翻转
    flips = _screen_order_flips(scene)
    for f in flips:
        dense.add(f.frame)

    # 高动态采样：事件帧附近加密（此处仅标记，不重采样）
    dense_frames = sorted(dense)
    truncate_reason = ""
    truncated = len(events) > 50 or len(dense_frames) > 60
    if truncated:
        truncate_reason = "事件/加密帧过多，已截断（保留前 50 事件、前 60 加密帧）"

    sampling = SamplingSummary(step=1, dense_frames=dense_frames[:60],
                               total_frames=scene.frame_range[1],
                               truncated=truncated,
                               truncate_reason=truncate_reason)
    return DynamicReport(scene.shot_id, trajectory, events[:50],
                         occlusion_summary, flips, sampling)


def _screen_order_flips(scene: FightScene) -> List[ScreenOrderFlip]:
    """逐帧维护两侧角色的左右序，翻转且无可见换位/中性桥 → unbridged_flip。"""
    normalized = [_as_sample(raw) for raw in scene.samples]
    characters = sorted({s.character_id for s in normalized})
    if len(characters) < 2:
        return []
    a, b = characters[0], characters[1]
    by_frame: Dict[int, Dict[str, Sample]] = {}
    for s in normalized:
        by_frame.setdefault(s.frame, {})[s.character_id] = s

    flips: List[ScreenOrderFlip] = []
    prev_order: Optional[str] = None
    prev_frame: Optional[int] = None
    for frame in sorted(by_frame):
        sa, sb = by_frame[frame].get(a), by_frame[frame].get(b)
        #: 任一侧缺席或**出画**（ndc 越界）时，左右序不可测量：
        #: 出画角色仍在队伍里会制造"越界→翻转→回画再翻转"的假事件。
        off_a = sa is None or not (0.0 <= sa.ndc_x <= 1.0)
        off_b = sb is None or not (0.0 <= sb.ndc_x <= 1.0)
        if off_a or off_b:
            continue
        order = "left" if sa.ndc_x < sb.ndc_x else "right"
        if (prev_order is not None and order != prev_order
                and prev_frame is not None and frame == prev_frame + 1):
            # 打斗 demo：以无可见换位直接判 unbridged_flip；
            # 仅在连续帧内翻转才判；正式实现由“是否在镜内发生可见换位/中性桥”决定。
            flips.append(ScreenOrderFlip("unbridged_flip", frame, a, b,
                                         f"左右序 {prev_order}→{order}"))
        prev_order = order
        prev_frame = frame
    return flips


# --------------------------------------------------------------------------- #
# 报告渲染
# --------------------------------------------------------------------------- #
def render_dynamic_report(report: DynamicReport) -> str:
    lines = [f"战斗动态读数（{report.shot_id}，共 {report.sampling.total_frames} 帧）："]
    for cid, track in report.trajectory.items():
        bands = " / ".join(f"{k}×{v}" for k, v in track.bands.items())
        lines.append(f"- {cid}：速度档 {bands}；轨迹 {len(track.frames)} 采样点")
    if report.events:
        lines.append("事件：")
        for e in report.events[:12]:
            lines.append(f"  - 帧{e.frame} {e.kind} {e.character_id} {e.detail}")
    if report.occlusion_summary:
        lines.append("遮挡归因：")
        for o in report.occlusion_summary:
            lines.append(f"  - {o.subject} 被 {o.occluder}（{o.occluder_class}）"
                         f"挡 {o.part}，平均可见 {o.visible_ratio:.0%}，声明={o.declared}")
    if report.screen_order_flips:
        lines.append("银幕左右序：")
        for f in report.screen_order_flips:
            lines.append(f"  - 帧{f.frame} {f.kind} {f.character_a}/{f.character_b} {f.detail}")
    if report.sampling.truncated:
        lines.append(f"（截断：{report.sampling.truncate_reason}）")
    return "\n".join(lines)
