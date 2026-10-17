"""空间尺生产桥（Ticket 转正）：旧审核采样 → 六层评测台采样对象。

钉住：
* ``build_intent``：把 ``ShotPlan`` 的意图/景别/视线/运镜折成
  ``evaluation_protocol.IntentContract``；
* ``build_shot_sample``：把 ``frustum_sampler.FrameSample`` 按帧聚合进
  ``evaluation_protocol.FrameSample``（多主体 + 相机信息），并构造
  ``ShotSample``（内容关键帧 = 首/中/末；动作关键帧 = 起点/接触/反应）；
* ``build_sequence_sample``：按计划顺序组装 ``SequenceSample``。

纯层模块，禁止 import bpy。
"""

from __future__ import annotations

import pytest

from block_director.cinema.composition import SubjectBox
from block_director.cinema.evaluation_protocol import (
    ActionFrame,
    ContentFrame,
    FrameSample as EvalFrameSample,
    IntentContract,
    SequenceSample,
    ShotSample,
)
from block_director.cinema.frustum_metrics import FrameSample as ProbeFrame
from block_director.cinema.ruler_bridge import (
    build_intent,
    build_sequence_sample,
    build_shot_sample,
)
from block_director.contracts.enums import ShotType
from block_director.contracts.plan import Plan, ShotPlan


def _probe_frame(frame: int, shot_id: str = "shot_001",
                 subject: str = "hero", visible: float = 1.0,
                 left: float = 0.4, right: float = 0.6,
                 top: float = 0.8, bottom: float = 0.2,
                 behind: bool = False) -> ProbeFrame:
    return ProbeFrame(
        frame=frame, subject=subject,
        box=SubjectBox(name=subject, left=left, right=right,
                       top=top, bottom=bottom, facing=1.0),
        visible_ratio=visible, behind_camera=behind, shot_id=shot_id)


def _shot(shot_id: str = "shot_001", duration: int = 120) -> ShotPlan:
    return ShotPlan(
        shot_id=shot_id, intent="推进主线", shot_type=ShotType.MS,
        duration_frames=duration, order=1, characters=["hero"],
        gaze=[{"from": "hero", "to": "enemy"}],
        camera={"lens": 35.0, "movements": [
            {"type": "dolly_in", "amount": 1.0,
             "start_frame": 0, "end_frame": duration}]},
        actions=[{
            "action_type": "punch", "character_id": "hero",
            "params": {"target": "enemy"},
            "start_frame": 20, "contact_frame": 30, "reaction_end_frame": 40,
        }])


def _samples(shot: ShotPlan, offset: int = 0) -> list:
    """首/中/末三帧 + 动作起点/接触/反应六帧的 probe 采样。"""
    frames = [1, shot.duration_frames // 2, shot.duration_frames,
              20, 30, 40]
    return [_probe_frame(f + offset, shot_id=shot.shot_id) for f in frames]


# --------------------------------------------------------------------------- #
# build_intent
# --------------------------------------------------------------------------- #
def test_build_intent_carries_intent_and_shot_type():
    intent = build_intent(_shot())
    assert intent.shot_id == "shot_001"
    assert intent.intent == "推进主线"
    assert intent.shot_type == "MS"


def test_build_intent_carries_gaze_and_movements():
    intent = build_intent(_shot())
    assert intent.gaze_target == "enemy"
    assert intent.camera_movements == ("dolly_in",)


def test_build_intent_carries_props_and_beats():
    shot = _shot()
    shot.beats = [{"subject": "hero", "verb": "punch", "target": "enemy"}]
    shot.vfx = [{"id": "vfx_01", "type": "spark", "position": [0, 0, 0],
                 "size": 1.0, "start_frame": 30, "end_frame": 40}]
    intent = build_intent(shot)
    assert intent.props == ("enemy",)
    assert intent.beats == ("hero punch enemy",)


def test_build_intent_empty_when_shot_missing():
    intent = build_intent(None)
    assert intent is None


# --------------------------------------------------------------------------- #
# build_shot_sample
# --------------------------------------------------------------------------- #
def test_build_shot_sample_aggregates_frames_by_frame_number():
    shot = _shot()
    samples = _samples(shot)
    sample = build_shot_sample(shot, samples, frame_range=(1, 120), fps=24)
    assert isinstance(sample, ShotSample)
    assert sample.shot_id == "shot_001"
    assert sample.frame_range == (1, shot.duration_frames)
    # 内容关键帧 = 首/中/末（probe 的 1/60/120）
    content_frames = [f.frame for f in sample.content.frames]
    assert content_frames == [1, 60, 120]
    assert len(sample.actions) == 1


def test_build_shot_sample_action_frames_are_ordered():
    shot = _shot()
    sample = build_shot_sample(shot, _samples(shot),
                               frame_range=(1, 120), fps=24)
    action = sample.actions[0]
    assert isinstance(action, ActionFrame)
    assert action.start.frame == 20
    assert action.contacts[0].frame == 30
    assert action.reaction_end.frame == 40
    # 并集按帧号升序去重
    frames = [f.frame for f in sample.frames]
    assert frames == sorted(set(frames))
    assert 20 in frames and 30 in frames and 40 in frames


def test_build_shot_sample_frame_has_multi_subjects_and_camera():
    shot = _shot()
    samples = [
        ProbeFrame(frame=1, subject="hero",
                   box=SubjectBox("hero", 0.4, 0.6, 0.8, 0.2, facing=1.0),
                   visible_ratio=1.0, shot_id="shot_001"),
        ProbeFrame(frame=1, subject="enemy",
                   box=SubjectBox("enemy", 0.7, 0.9, 0.7, 0.3, facing=-1.0),
                   visible_ratio=0.9, shot_id="shot_001"),
        ProbeFrame(frame=60, subject="hero",
                   box=SubjectBox("hero", 0.4, 0.6, 0.8, 0.2, facing=1.0),
                   visible_ratio=1.0, shot_id="shot_001"),
        ProbeFrame(frame=120, subject="hero",
                   box=SubjectBox("hero", 0.4, 0.6, 0.8, 0.2, facing=1.0),
                   visible_ratio=1.0, shot_id="shot_001"),
    ]
    sample = build_shot_sample(shot, samples, frame_range=(1, 120), fps=24)
    first = sample.content.frames[0]
    assert isinstance(first, EvalFrameSample)
    subjects = {s.subject_id: s for s in first.subjects}
    assert "hero" in subjects and "enemy" in subjects
    assert subjects["hero"].box.height == pytest.approx(0.6)
    assert subjects["enemy"].visible_ratio == 0.9
    assert first.lens == 35.0


def test_build_shot_sample_empty_samples_raises():
    with pytest.raises(ValueError):
        build_shot_sample(_shot(), [], frame_range=(1, 120), fps=24)


# --------------------------------------------------------------------------- #
# build_sequence_sample
# --------------------------------------------------------------------------- #
def test_build_sequence_sample_orders_shots():
    shot1 = _shot("shot_001", duration=120)
    shot2 = _shot("shot_002", duration=96)
    shot2.order = 2
    plan = Plan(shots=[shot1, shot2])
    samples1 = _samples(shot1)
    # shot_002 的绝对帧范围从 121 开始（排片器）；probe 采样用绝对帧号。
    samples2 = _samples(shot2, offset=120)
    seq = build_sequence_sample(
        plan, {"shot_001": samples1, "shot_002": samples2}, fps=24)
    assert isinstance(seq, SequenceSample)
    assert [s.shot_id for s in seq.shots] == ["shot_001", "shot_002"]
    # 排片器给绝对帧范围：shot_001 = [1, 120]，shot_002 = [121, 216]
    assert seq.shots[0].frame_range == (1, 120)
    assert seq.shots[1].frame_range == (121, 216)
    assert seq.shots[1].frame_range[0] == seq.shots[0].frame_range[1] + 1


def test_build_sequence_sample_missing_shot_samples_skips_none_and_fails():
    shot1 = _shot("shot_001", duration=120)
    shot2 = _shot("shot_002", duration=96)
    plan = Plan(shots=[shot1, shot2])
    with pytest.raises(ValueError):
        build_sequence_sample(
            plan, {"shot_001": _samples(shot1)}, fps=24)
