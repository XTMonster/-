"""评测协议类型层（Ticket 01）的测试：统一采样对象 -> 测量 -> 失败项。

覆盖主 spec（docs/SPEC_空间尺多维评测扩展_v1.0.md）§3.1/§3.2/§7：
* 单帧采样 / 内容关键帧 / 动作关键帧 / 镜头采样 / 镜头序列采样 / 意图契约；
* Measurement（指标名、原始值、归一化分数、目标区间、证据帧、置信度）；
* Finding（严重度 fatal/error/warning/note）；
* Prescription 目标契约（component/severity/current/target/
  allowed_tools/direction/expected_effect），与 §7 JSON 逐字段一致。
术语严格使用「内容关键帧 / 动作关键帧」；纯层不 import bpy。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from block_director.cinema.composition import SubjectBox
from block_director.cinema.evaluation_protocol import (
    ActionFrame,
    ContentFrame,
    EvaluationOutput,
    Finding,
    FrameSample,
    IntentContract,
    Measurement,
    Prescription,
    ProjectedSubject,
    SequenceSample,
    Severity,
    ShotSample,
    TargetInterval,
    middle_frame,
    smoke_evaluate,
)


MODULE_PATH = Path(inspect.getfile(smoke_evaluate)).resolve()


# --------------------------------------------------------------------------- #
# 构造助手（demo 输入，evidence_grade=demo）
# --------------------------------------------------------------------------- #
def _subject(subject_id: str, left: float, right: float, top: float,
             bottom: float, visible: float = 1.0,
             kind: str = "character") -> ProjectedSubject:
    return ProjectedSubject(
        subject_id=subject_id,
        kind=kind,
        box=SubjectBox(name=subject_id, left=left, right=right, top=top,
                       bottom=bottom, facing=1.0),
        visible_ratio=visible,
    )


def _frame(frame: int, visible: float = 1.0) -> FrameSample:
    return FrameSample(
        frame=frame,
        shot_id="shot_001",
        subjects=(_subject("hero", 0.24, 0.42, 0.93, 0.35, visible),),
    )


def _content(shot_id: str = "shot_001",
             frame_range: tuple = (1, 5)) -> ContentFrame:
    first, last = frame_range
    middle = middle_frame(first, last)
    return ContentFrame.from_shot(
        shot_id=shot_id,
        frame_range=frame_range,
        frames=(_frame(first), _frame(middle), _frame(last)),
    )


def _action() -> ActionFrame:
    return ActionFrame(
        shot_id="shot_001",
        start=_frame(2),
        contacts=(_frame(4, visible=0.0),),
        reaction_end=_frame(5),
    )


def _shot(actions: tuple = ()) -> ShotSample:
    return ShotSample(
        shot_id="shot_001",
        frame_range=(1, 5),
        content=_content(),
        actions=actions,
    )


def _intent() -> IntentContract:
    return IntentContract(
        shot_id="shot_001",
        intent="突出攻击者",
        subject="hero",
        shot_type="MS",
        beats=("攻击发起", "接触命中", "受击反应"),
    )


def _measurement() -> Measurement:
    return Measurement(
        metric="smoke_primary_visibility",
        raw_value=0.75,
        score=0.75,
        target=TargetInterval(min_value=0.70),
        evidence_frames=(1, 3, 4, 5),
        confidence=1.0,
        evidence_grade="demo",
    )


def _prescription() -> Prescription:
    return Prescription(
        component="contact_point_visibility",
        severity=Severity.FATAL,
        current=0.21,
        target=TargetInterval(min_value=0.70),
        allowed_tools=("move_character", "move_camera"),
        direction="separate_subjects",
        expected_effect=("silhouette_separation", "action_readability"),
    )


# --------------------------------------------------------------------------- #
# 类型层与纯层约束
# --------------------------------------------------------------------------- #
def test_protocol_module_is_bpy_free():
    """协议类型层不得 import bpy（纯层红线）。"""
    text = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert "bpy" not in [name.split(".")[0] for name in imports]


def test_terms_use_content_and_action_keyframes_in_smoke_output():
    """冒烟输出必须用「内容关键帧 / 动作关键帧」，不出现裸「关键帧」。"""
    out = smoke_evaluate(_shot(actions=(_action(),)), _intent())
    assert "内容关键帧" in out.render()
    assert "动作关键帧" in out.render()


# --------------------------------------------------------------------------- #
# 采样对象的不变量
# --------------------------------------------------------------------------- #
def test_content_frame_requires_first_middle_and_last():
    first, middle, last = 1, 3, 5
    content = ContentFrame.from_shot(
        shot_id="shot_001", frame_range=(first, last),
        frames=(_frame(first), _frame(middle), _frame(last)))
    assert [f.frame for f in content.frames] == [1, 3, 5]

    with pytest.raises(ValueError):
        ContentFrame.from_shot(
            shot_id="shot_001", frame_range=(1, 5),
            frames=(_frame(1), _frame(2), _frame(5)))  # 缺中帧

    with pytest.raises(ValueError):
        ContentFrame.from_shot(
            shot_id="shot_001", frame_range=(1, 5),
            frames=(_frame(1), _frame(3), _frame(5), _frame(5)))  # 帧号重复


def test_action_frame_requires_contact_between_start_and_reaction_end():
    action = _action()
    assert action.start.frame < action.contacts[0].frame
    assert action.contacts[0].frame < action.reaction_end.frame

    with pytest.raises(ValueError):
        ActionFrame(
            shot_id="shot_001",
            start=_frame(4),
            contacts=(_frame(2),),  # 接触帧必须晚于起点
            reaction_end=_frame(5),
        )


def test_shot_sample_union_contains_contact_frames():
    shot = _shot(actions=(_action(),))
    frames = [f.frame for f in shot.frames]
    assert frames == [1, 2, 3, 4, 5]
    assert 4 in frames  # 动作接触帧
    assert 1 in frames and 3 in frames and 5 in frames  # 首/中/末


def test_sequence_sample_requires_ordered_adjacent_shots():
    a = _shot()
    b = ShotSample(
        shot_id="shot_002",
        frame_range=(6, 10),
        content=_content("shot_002", frame_range=(6, 10)),
    )
    seq = SequenceSample(shots=(a, b))
    assert seq.shots[0].shot_id == "shot_001"

    with pytest.raises(ValueError):
        SequenceSample(shots=(b, a))  # 顺序颠倒


# --------------------------------------------------------------------------- #
# Measurement / Finding / Prescription
# --------------------------------------------------------------------------- #
def test_measurement_fields_and_target_range():
    m = _measurement()
    assert m.metric == "smoke_primary_visibility"
    assert m.raw_value == 0.75
    assert 0.0 <= m.score <= 1.0
    assert m.target.contains(0.80)
    assert not m.target.contains(0.60)
    assert m.target.to_dict() == {"min": 0.70}


def test_finding_severity_vocabulary():
    assert [item.value for item in Severity] == [
        "fatal", "error", "warning", "note"]
    finding = Finding(
        component="contact_point_visibility",
        severity=Severity.FATAL,
        message="接触帧主体完全不可见",
        evidence_frames=(4,),
        gate="H2",
    )
    assert finding.severity is Severity.FATAL
    assert finding.gate == "H2"


def test_prescription_matches_section7_json():
    p = _prescription()
    assert p.to_dict() == {
        "component": "contact_point_visibility",
        "severity": "fatal",
        "current": 0.21,
        "target": {"min": 0.70},
        "allowed_tools": ["move_character", "move_camera"],
        "direction": "separate_subjects",
        "expected_effect": ["silhouette_separation", "action_readability"],
    }


# --------------------------------------------------------------------------- #
# 冒烟链路：镜头采样 -> 测量 -> 失败项
# --------------------------------------------------------------------------- #
def test_smoke_evaluate_produces_measurement_and_finding():
    shot = _shot(actions=(_action(),))
    out = smoke_evaluate(shot, _intent())
    assert isinstance(out, EvaluationOutput)
    assert out.measurements
    assert out.findings
    assert out.findings[0].severity is Severity.FATAL


def test_smoke_evaluate_is_deterministic():
    first = smoke_evaluate(_shot(actions=(_action(),)), _intent())
    second = smoke_evaluate(_shot(actions=(_action(),)), _intent())
    assert first.to_dict() == second.to_dict()
