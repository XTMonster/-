"""缺陷 A（T5）：局部主体框——"掌中银币大特写"按道具评分。

剧本声明 ``framing_target=prop`` 时，道具在画内评分必须 >80；道具出画时
硬闸成立（≤20，语义与整身主体一致）。纯层测试；Blender 侧实拍见
``tools/blender_tests/test_local_subject_probe.py``。
"""

from __future__ import annotations

from block_director.cinema.composition import PASS_SCORE, SubjectBox
from block_director.cinema.composition import evaluate_composition


def _coin_box(**overrides) -> SubjectBox:
    """银币局部框：左三分线、无朝向、高度占比 0.65（ECU 满幅约 1.0）。"""
    values = dict(name="coin", left=0.24, right=0.42, top=0.95,
                  bottom=0.30, facing=0.0, provenance="measured")
    values.update(overrides)
    return SubjectBox(**values)


def _body_box(**overrides) -> SubjectBox:
    values = dict(name="偷盗者", left=0.02, right=0.98, top=0.98,
                  bottom=0.02, facing=1.0)
    values.update(overrides)
    return SubjectBox(**values)


def test_prop_in_frame_passes_strictly_above_80():
    """银币在画内：按道具框评分，严格 >80。"""
    report = evaluate_composition(
        [_body_box(), _coin_box()], primary="coin",
        expected_height=1.0, headroom_applies=False)
    assert report.score > PASS_SCORE, report.to_dict()


def test_prop_out_of_frame_hard_cap_applies():
    """银币出画：硬闸对局部主体成立，≤20（不因"道具小"躲过闸门）。"""
    outside = _coin_box(left=1.40, right=1.60, top=1.50, bottom=0.90)
    report = evaluate_composition([_body_box(), outside], primary="coin",
                                  expected_height=1.0,
                                  headroom_applies=False)
    assert outside.inside_ratio() <= 0.05
    assert report.score <= 20.0, report.to_dict()
    assert report.items["framing"].score == 0.0


def test_without_primary_whole_body_anchor_drags_below_threshold():
    """对抗：无局部主体语义时同一机位（银币在画内）仍修不过。"""
    report = evaluate_composition([_body_box(), _coin_box()],
                                  expected_height=1.0,
                                  headroom_applies=False)
    assert report.score <= PASS_SCORE, report.to_dict()


def test_prop_primary_survives_taller_visible_character():
    """道具框是主锚：即使整身角色框更高更大，评分仍以道具为准。"""
    report = evaluate_composition(
        [_body_box(), _coin_box()], primary="coin",
        expected_height=1.0, headroom_applies=False)
    assert report.items["rule_of_thirds"].score > 0.8
    assert report.score > PASS_SCORE
