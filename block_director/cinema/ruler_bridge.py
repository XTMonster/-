"""空间尺生产桥（转正）：旧审核采样 → 六层评测台采样对象。

把插件已采集的画面事实（``frustum_sampler.FrameSample``、计划里的
``ShotPlan``）折成 ``evaluation_protocol`` 的采样对象，喂六层评测台：

* :func:`build_intent` —— ``ShotPlan`` → ``IntentContract``（意图/景别/
  视线/运镜/道具/拍点）；
* :func:`build_shot_sample` —— 单镜 probe 采样 → ``ShotSample``
  （内容关键帧 = 首/中/末，动作关键帧 = 起点/接触/反应）；
* :func:`build_sequence_sample` —— 全场按排片器顺序 → ``SequenceSample``。

纯层模块：不 import bpy / mathutils。probe 采样帧号必须是**排片器绝对帧**
（与 ``schedule.shot_ranges`` 同口径）；动作事件帧号按帧值就近取采样本。
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..contracts.plan import Plan, ShotPlan
from .evaluation_protocol import (
    ActionFrame,
    ContentFrame,
    FrameSample,
    IntentContract,
    ProjectedSubject,
    SequenceSample,
    ShotSample,
    middle_frame,
)
from .schedule import shot_ranges


# --------------------------------------------------------------------------- #
# intent 桥
# --------------------------------------------------------------------------- #
def _movement_types(shot: ShotPlan) -> Tuple[str, ...]:
    out: List[str] = []
    for item in (shot.camera or {}).get("movements") or []:
        if isinstance(item, dict) and item.get("type"):
            out.append(str(item["type"]))
    return tuple(out)


def _gaze_target(shot: ShotPlan) -> Optional[str]:
    for item in (shot.gaze or []):
        if not isinstance(item, dict):
            continue
        if item.get("to"):
            return str(item["to"])
    return None


def _beats(shot: ShotPlan) -> Tuple[str, ...]:
    out: List[str] = []
    for item in (shot.beats or []):
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "")
        verb = str(item.get("verb") or "")
        target = str(item.get("target") or "")
        if subject and verb:
            out.append(f"{subject} {verb} {target}".rstrip())
    return tuple(out)


def _props(shot: ShotPlan) -> Tuple[str, ...]:
    out: List[str] = []
    for item in (shot.actions or []):
        if not isinstance(item, dict):
            continue
        params = item.get("params") or {}
        if isinstance(params, dict) and params.get("target"):
            out.append(str(params["target"]))
        elif item.get("target"):
            out.append(str(item["target"]))
    seen: set[str] = set()
    return tuple(name for name in out if not (name in seen or seen.add(name)))


def build_intent(shot: Optional[ShotPlan]) -> Optional[IntentContract]:
    """把镜头的计划意图折成评测台意图契约；无镜头返回 None。"""
    if shot is None:
        return None
    return IntentContract(
        shot_id=str(shot.shot_id),
        intent=str(getattr(shot, "intent", "") or ""),
        subject=(str(shot.characters[0]) if shot.characters else ""),
        shot_type=str(shot.shot_type),
        beats=_beats(shot),
        gaze_target=_gaze_target(shot),
        camera_movements=_movement_types(shot),
        props=_props(shot),
    )


# --------------------------------------------------------------------------- #
# probe 采样桥
# --------------------------------------------------------------------------- #
def _as_eval_frame(shot: ShotPlan, frame: int,
                   probes: Sequence[Any],
                   lens: Optional[float]) -> FrameSample:
    """把一个绝对帧号上的同帧 probe 采样合成一个评测帧。"""
    subjects: List[ProjectedSubject] = []
    for probe in probes:
        box = getattr(probe, "box", None)
        if box is None:
            continue
        kind = "prop" if getattr(probe, "kind", "") == "prop" else "character"
        subjects.append(ProjectedSubject(
            subject_id=str(getattr(probe, "subject", "") or ""),
            box=box,
            kind=kind,
            visible_ratio=float(getattr(probe, "visible_ratio", 1.0) or 1.0),
        ))
    return FrameSample(
        frame=int(frame),
        subjects=tuple(subjects),
        shot_id=str(shot.shot_id),
        lens=float(lens) if lens is not None else 35.0,
    )


def _nearest(probes: Sequence[Any], frame: int) -> Optional[Any]:
    """在采样里找最接近目标帧的那一条（按帧号距离）。"""
    if not probes:
        return None
    return min(probes, key=lambda p: abs(int(getattr(p, "frame", 0)) - frame))


def _action_frames(shot: ShotPlan) -> List[Tuple[int, int, int]]:
    """从计划动作事件抽取 ``(start, contact, reaction_end)`` 三帧三元组。"""
    out: List[Tuple[int, int, int]] = []
    for item in (shot.actions or []):
        if not isinstance(item, dict):
            continue
        params = item.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        start = int(item.get("start_frame") or params.get("start_frame") or 0)
        contact = int(item.get("contact_frame")
                      or params.get("contact_frame") or 0)
        end = int(item.get("reaction_end_frame")
                  or params.get("reaction_end_frame") or 0)
        if start > 0 and contact > start and end > contact:
            out.append((start, contact, end))
    return out


def build_shot_sample(shot: ShotPlan, probes: Sequence[Any], *,
                      frame_range: Tuple[int, int],
                      fps: int = 24,
                      lens: Optional[float] = None) -> ShotSample:
    """把一镜的 probe 采样折成评测台 ``ShotSample``。

    ``probes`` 是 ``frustum_sampler.FrameSample`` 列表（允许跨帧、跨主体）；
    ``frame_range`` 是该镜的**绝对帧范围**（由排片器给）。内容关键帧 =
    首帧/中帧/末帧（就近取采样本），动作关键帧 = 起点/接触/反应三帧。
    """
    if not probes:
        raise ValueError(f"{shot.shot_id} 没有可用的帧采样")
    first, last = int(frame_range[0]), int(frame_range[1])
    mid = middle_frame(first, last)
    if lens is None:
        lens = float((shot.camera or {}).get("lens") or 35.0)

    by_frame: Dict[int, List[Any]] = {}
    for probe in probes:
        by_frame.setdefault(int(getattr(probe, "frame", 0)), []).append(probe)

    def frame_at(target: int) -> FrameSample:
        # 有同帧用同帧，没有就取离得最近的采样本（同帧对象复用，保内容/动作
        # 帧的证据帧号与样本一致）。
        nearest = _nearest(probes, target)
        if nearest is not None and int(getattr(nearest, "frame", 0)) == target:
            return _as_eval_frame(shot, target,
                                  by_frame.get(target, [nearest]), lens)
        return _as_eval_frame(shot, target, [nearest], lens) \
            if nearest is not None else _as_eval_frame(shot, target, [], lens)

    content_frames = tuple(frame_at(f) for f in sorted({first, mid, last}))
    content_frame_numbers = [f.frame for f in content_frames]
    if len(set(content_frame_numbers)) < 3 or content_frames[0].frame != first \
            or content_frames[-1].frame != last:
        # 采样不足：用实际可用的逐帧补偿（首/末必须有——排片器保证镜头至少 1 帧）
        raise ValueError(
            f"{shot.shot_id} 内容关键帧无法覆盖 {first}..{last}（采样帧 "
            f"{sorted({int(getattr(p, 'frame', 0)) for p in probes})}）")

    actions: List[ActionFrame] = []
    base = first - 1
    for start, contact, end in _action_frames(shot):
        try:
            actions.append(ActionFrame(
                shot_id=str(shot.shot_id),
                start=frame_at(start + base),
                contacts=(frame_at(contact + base),),
                reaction_end=frame_at(end + base),
            ))
        except ValueError:
            # 动作帧顺序或越界由评测层如实缺（动作层会报"缺动作关键帧"），
            # 不在这里伪造接触帧。
            continue

    return ShotSample(
        shot_id=str(shot.shot_id),
        frame_range=(first, last),
        content=ContentFrame.from_shot(
            str(shot.shot_id), (first, last), content_frames),
        actions=tuple(actions),
    )


def build_sequence_sample(plan: Plan,
                          samples_by_shot: Mapping[str, Sequence[Any]], *,
                          fps: int = 24,
                          lens_by_shot: Optional[Mapping[str, float]] = None
                          ) -> SequenceSample:
    """按排片器顺序把全场镜头折成 ``SequenceSample``。

    每一镜在计划里都必须有采样（缺镜直接报错——序列级指标需要整条链的
    画面事实，缺一镜会让连续性读数失真）。帧范围由排片器
    ``schedule.shot_ranges`` 统一给出，保证相邻镜不重叠、顺序正确。
    """
    ranges = shot_ranges(plan)
    shots: List[ShotSample] = []
    for shot in plan.shots:
        probes = samples_by_shot.get(str(shot.shot_id))
        if not probes:
            raise ValueError(
                f"{shot.shot_id} 没有帧采样，无法构建镜头序列")
        frame_range = ranges.get(str(shot.shot_id))
        if frame_range is None:
            raise ValueError(f"{shot.shot_id} 没有排片帧范围")
        lens = None
        if lens_by_shot is not None:
            lens = lens_by_shot.get(str(shot.shot_id))
        shots.append(build_shot_sample(
            shot, list(probes), frame_range=frame_range,
            fps=fps, lens=lens))
    return SequenceSample(shots=tuple(shots))
