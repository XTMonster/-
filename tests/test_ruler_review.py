"""空间尺生产整合层（转正）：六层评测汇总成 RulerReview。

钉住：
* 逐镜跑 geometry/attention/action/cinema/robustness，序列跑 continuity；
* 六层分 / overview 用 ``metric_registry.layer_score/overview_score`` 计算，
  缺测分量按 0 计（"缺证不能凭空通过"）；
* H1–H6 硬门从各层 findings.gate 收拢，命中即 ``hard_gates`` 非空；
* 处方从各层 ``build_prescriptions`` 收拢，统一为
  component/severity/current/target/allowed_tools/direction/expected_effect。
"""

from __future__ import annotations

from block_director.cinema.composition import SubjectBox
from block_director.cinema.frustum_metrics import FrameSample as ProbeFrame
from block_director.cinema.metrics_geometry import evaluate as geometry_evaluate
from block_director.cinema.ruler_review import run_ruler_review, run_shot_review
from block_director.contracts.enums import ShotType
from block_director.contracts.plan import Plan, ShotPlan


def _probe(frame: int, shot_id: str, visible: float = 1.0,
           left: float = 0.4, right: float = 0.6,
           top: float = 0.8, bottom: float = 0.2) -> ProbeFrame:
    return ProbeFrame(
        frame=frame, subject="hero",
        box=SubjectBox(name="hero", left=left, right=right,
                       top=top, bottom=bottom, facing=1.0),
        visible_ratio=visible, shot_id=shot_id)


def _shot(shot_id: str = "shot_001", duration: int = 120,
          order: int = 1, intent: str = "推进主线") -> ShotPlan:
    return ShotPlan(
        shot_id=shot_id, intent=intent, shot_type=ShotType.MS,
        duration_frames=duration, order=order, characters=["hero"],
        camera={"lens": 35.0, "movements": [
            {"type": "dolly_in", "amount": 1.0,
             "start_frame": 0, "end_frame": duration}]})


def _good_samples(shot: ShotPlan) -> list:
    """主体完整、合理居中、未遮挡的三帧采样（期望全层通过）。"""
    first = shot.duration_frames // 2 - 1
    last = shot.duration_frames
    return [_probe(first, shot.shot_id),
            _probe(shot.duration_frames // 2, shot.shot_id),
            _probe(last, shot.shot_id)]


def _bad_samples(shot: ShotPlan) -> list:
    """主体出画/贴边（edge_clearance / framing 类失败的反例）。"""
    first = shot.duration_frames // 2 - 1
    last = shot.duration_frames
    return [
        _probe(first, shot.shot_id, left=0.92, right=1.4,
               top=1.05, bottom=0.95),
        _probe(shot.duration_frames // 2, shot.shot_id,
               left=0.92, right=1.4, top=1.05, bottom=0.95),
        _probe(last, shot.shot_id, left=0.92, right=1.4,
               top=1.05, bottom=0.95),
    ]


# --------------------------------------------------------------------------- #
# 结构
# --------------------------------------------------------------------------- #
def test_run_ruler_review_returns_full_shape():
    shot = _shot()
    plan = Plan(shots=[shot])
    review = run_ruler_review(
        plan, {"shot_001": _good_samples(shot)}, fps=24)
    assert review.shot_id == "shot_001"
    assert set(review.layer_scores) == {
        "geometry", "attention", "action", "continuity",
        "cinema", "robustness"}
    assert 0.0 <= review.overview <= 100.0
    assert isinstance(review.hard_gates, set)
    assert isinstance(review.findings, tuple)
    assert isinstance(review.measurements, tuple)
    assert isinstance(review.prescriptions, tuple)


def test_run_ruler_review_overview_weights_match_registry():
    from block_director.cinema.metric_registry import LAYER_WEIGHTS_DEFAULT
    shot = _shot()
    plan = Plan(shots=[shot])
    review = run_ruler_review(
        plan, {"shot_001": _good_samples(shot)}, fps=24)
    expected = sum(
        LAYER_WEIGHTS_DEFAULT[layer] * review.layer_scores[layer]
        for layer in LAYER_WEIGHTS_DEFAULT)
    assert review.overview == expected


# --------------------------------------------------------------------------- #
# 硬门与失败
# --------------------------------------------------------------------------- #
def test_run_ruler_review_good_samples_no_hard_gate():
    shot = _shot()
    plan = Plan(shots=[shot])
    review = run_ruler_review(
        plan, {"shot_001": _good_samples(shot)}, fps=24)
    assert review.hard_gates == set()


def test_run_ruler_review_bad_samples_geometry_finding():
    shot = _shot()
    plan = Plan(shots=[shot])
    review = run_ruler_review(
        plan, {"shot_001": _bad_samples(shot)}, fps=24)
    assert review.findings, "出画的主体必须产生至少一条失败项"
    components = {f.component for f in review.findings}
    assert any(name in components for name in
               ("edge_clearance", "screen_size", "framing"))


def test_run_ruler_review_prescriptions_only_for_failures():
    shot = _shot()
    plan = Plan(shots=[shot])
    review = run_ruler_review(
        plan, {"shot_001": _bad_samples(shot)}, fps=24)
    for prescription in review.prescriptions:
        assert prescription.severity in ("fatal", "error")
        assert prescription.component


# --------------------------------------------------------------------------- #
# 逐镜审核（CHECKING 阶段）：continuity 如实标缺，不编造序列级读数
# --------------------------------------------------------------------------- #
def test_run_shot_review_marks_continuity_unverified():
    """逐镜审核没有全场镜头链，continuity 层必须 0 分 + NOTE finding，
    且硬门只收 H1/H2/H4/H5（H3/H6 属序列级，绝不凭空放行）。"""
    shot = _shot()
    plan = Plan(shots=[shot])
    review = run_shot_review(
        plan, "shot_001", _good_samples(shot), fps=24)
    # 五层照常评分，continuity 如实标缺。
    assert review.layer_scores["continuity"] == 0.0
    assert any(f.component == "continuity"
               and f.severity.value == "note"
               and "未核验" in f.message
               for f in review.findings), \
        "逐镜审核必须留一条 continuity 未核验的 NOTE，不得编造读数"
    # 逐镜入口不可能断言 H3/H6，只能收序列级可判的分层门。
    assert not (review.hard_gates & {"H3", "H6"})


def test_run_ruler_review_missing_samples_raises():
    import pytest
    shot = _shot()
    plan = Plan(shots=[shot])
    with pytest.raises(ValueError):
        run_ruler_review(plan, {}, fps=24)
