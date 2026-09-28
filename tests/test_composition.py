"""§10.4 构图评分公式的纯计算测试。"""

from __future__ import annotations

import pytest

from block_director.cinema.composition import (
    PASS_SCORE,
    WEIGHTS,
    SubjectBox,
    evaluate_composition,
)


def good_box(**overrides) -> SubjectBox:
    """一个六项都基本合格的包围盒：站在左三分线、朝向画面内侧。"""
    values = dict(name="小明", left=0.24, right=0.42, top=1.0 - 0.07,
                  bottom=0.35, facing=1.0)
    values.update(overrides)
    return SubjectBox(**values)


def test_weights_match_document():
    assert WEIGHTS == {"headroom": 0.15, "lead_room": 0.20, "rule_of_thirds": 0.15,
                       "balance": 0.15, "occlusion": 0.25, "framing": 0.10}
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_good_framing_scores_high():
    report = evaluate_composition([good_box()])
    assert report.passed, report.to_dict()
    assert report.score >= PASS_SCORE


def test_no_subject_scores_zero():
    report = evaluate_composition([])
    assert report.score == 0.0
    assert report.suggestions


def test_too_much_headroom_is_penalised():
    report = evaluate_composition([good_box(top=0.60)])
    assert report.items["headroom"].score < 1.0
    assert "留白过多" in report.items["headroom"].suggestion


def test_cropped_head_is_penalised():
    report = evaluate_composition([good_box(top=1.02)])
    assert report.items["headroom"].score < 1.0
    assert "头顶被切" in report.items["headroom"].suggestion


def test_lead_room_rewards_space_in_facing_direction():
    facing_right_at_left = evaluate_composition([good_box()])
    facing_right_at_right = evaluate_composition(
        [good_box(left=0.62, right=0.80, facing=1.0)])
    assert (facing_right_at_left.items["lead_room"].score
            > facing_right_at_right.items["lead_room"].score)


def test_subject_facing_out_of_frame_gets_zero_lead_room():
    box = SubjectBox(name="小明", left=0.02, right=0.10, top=0.9, bottom=0.4,
                     facing=-1.0)
    report = evaluate_composition([box])
    assert report.items["lead_room"].score == 0.0


def test_thirds_scores_better_than_center():
    on_thirds = evaluate_composition([good_box(left=0.30, right=0.40,
                                               top=0.80, bottom=0.45)])
    at_center = evaluate_composition([good_box(left=0.45, right=0.55,
                                               top=0.62, bottom=0.37)])
    assert (on_thirds.items["rule_of_thirds"].score
            > at_center.items["rule_of_thirds"].score)


def test_balance_rewards_symmetric_subjects():
    left = good_box(name="A", left=0.18, right=0.34)
    right = good_box(name="B", left=0.66, right=0.82, facing=-1.0)
    symmetric = evaluate_composition([left, right])
    one_sided = evaluate_composition([left, good_box(name="B", left=0.10,
                                                     right=0.26, facing=-1.0)])
    assert symmetric.items["balance"].score > one_sided.items["balance"].score


def test_occlusion_is_the_heaviest_penalty():
    clean = evaluate_composition([good_box()], occluded={"小明": False})
    blocked = evaluate_composition([good_box()], occluded={"小明": True})
    assert clean.items["occlusion"].score == 1.0
    assert blocked.items["occlusion"].score == 0.0
    # 分数按 0.1 取整，比较时留出舍入余量
    assert clean.score - blocked.score == pytest.approx(
        WEIGHTS["occlusion"] * 100, abs=0.11)
    assert any("遮挡" in s for s in blocked.suggestions)


def test_single_subject_on_thirds_is_not_penalised_for_balance():
    """把唯一主体放在三分线交点是正确构图，不该被重心规则惩罚。"""
    report = evaluate_composition([good_box()])
    assert report.items["balance"].score == 1.0
    assert not report.items["balance"].suggestion


def test_partial_occlusion_is_less_severe_than_full():
    left = good_box(name="A", left=0.18, right=0.34)
    right = good_box(name="B", left=0.66, right=0.82, facing=-1.0)
    one_blocked = evaluate_composition([left, right], occluded={"A": True})
    both_blocked = evaluate_composition([left, right],
                                        occluded={"A": True, "B": True})
    assert one_blocked.items["occlusion"].score > both_blocked.items["occlusion"].score


def test_subject_out_of_frame_penalises_framing():
    outside = SubjectBox(name="小明", left=-0.4, right=-0.1, top=0.9,
                         bottom=0.4, facing=1.0)
    report = evaluate_composition([outside])
    assert report.items["framing"].score == 0.0
    assert any("出画" in s for s in report.suggestions)


def test_expected_height_mismatch_is_flagged():
    report = evaluate_composition([good_box()], expected_height=0.1)
    assert report.items["framing"].score < 1.0
    assert report.items["framing"].suggestion


def test_report_serialises():
    data = evaluate_composition([good_box()]).to_dict()
    assert set(data) == {"score", "passed", "items", "suggestions"}
    assert set(data["items"]) == set(WEIGHTS)
