"""v1.6 B4（D-12 / FR-C5）：CU/ECU 像素可测约束反解 + 同尺回读。

钉住四件事：

* CU 反解后回读必须落在头部占画高 55–75% 且头顶留白 3–10%（区间来自
  ``config.guard.size_bands`` 经 ``guard_config_from``，不另写常数）；
* "只剩眼睛"的过近 CU ⇒ ``framing_too_tight`` 且 evidence 含实测头部占比，
  回读判 out-of-band —— 不能再静默通过；
* 回读不一致时求解器调**距离档**（``距离 × 实测 ÷ 目标``），景别不降级；
* 确定性：同输入两次调用逐位相同；表缺失如实报错，不悄悄回退常数表。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from block_director.cinema.anchor import DEFAULT_PROFILE
from block_director.cinema.composition import SubjectBox
from block_director.cinema.framing import (
    ASPECT_16_9,
    SENSOR_WIDTH,
    head_band_target,
    readback_adjusted_distance,
    readback_shot_size,
    solve_framing,
)
from block_director.cinema.frustum_metrics import (
    DeclaredShot,
    FrameSample,
    compare_with_intent,
    frame_metrics,
    guard_config_from,
)
from block_director.contracts.config import AppConfig

#: 默认 ``config.guard.size_bands``（经 guard_config_from）——测试钉的是这张
#: config 表的确定性，而不是环境里用户改过的 config.yaml。
CFG = guard_config_from(AppConfig())
BANDS = {"head": dict(CFG.head_bands), "body": dict(CFG.body_bands)}

HEADROOM_DESIGN = 0.10          # framing.HEADROOM_DESIGN（§2.2 设计留白）


def camera(lens: float) -> SimpleNamespace:
    return SimpleNamespace(lens=float(lens), sensor_width=SENSOR_WIDTH,
                           aspect=ASPECT_16_9)


def projected_box(solution) -> SubjectBox:
    """按求解器输出模拟主体 NDC 全身盒（板式规则：头顶留白 = 设计值）。"""
    top = 1.0 - HEADROOM_DESIGN
    bottom = top - DEFAULT_PROFILE.total_height / solution.frame_height
    return SubjectBox("subject", left=0.40, right=0.60, top=top, bottom=bottom)


def eyes_only_box() -> SubjectBox:
    """E-video P0-3 的合成场景：全身盒高 3.3 倍画面（头球占画高 >1）。"""
    return SubjectBox("米迦尔", left=0.3, right=0.7, top=1.3, bottom=-2.0)


def test_cu_solve_reads_back_inside_55_to_75_with_headroom():
    solution = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "CU",
                             bands=BANDS)
    detected, in_band = readback_shot_size(camera(solution.lens),
                                           projected_box(solution), bands=BANDS)
    assert detected == "CU"
    assert in_band is True
    metrics = frame_metrics(projected_box(solution))
    lo, hi = BANDS["head"]["CU"]
    assert lo <= metrics["head_height_ratio"] <= hi
    assert metrics["head_height_ratio"] == pytest.approx((lo + hi) / 2.0)
    assert 0.03 <= metrics["headroom"] <= 0.10


def test_ecu_solve_reads_back_inside_its_band():
    solution = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "ECU",
                             bands=BANDS)
    detected, in_band = readback_shot_size(camera(solution.lens),
                                           projected_box(solution), bands=BANDS)
    assert detected == "ECU"
    assert in_band is True
    metrics = frame_metrics(projected_box(solution))
    lo, hi = BANDS["head"]["ECU"]
    assert lo <= metrics["head_height_ratio"] <= hi


def test_tight_series_stays_monotonic():
    #: 距离跨焦段不可比（CU 85mm / MCU 50mm）；景别松紧看**画面高度**。
    ecu = solve_framing((0, 0, 0), (0, 1, 0), "ECU", bands=BANDS)
    cu = solve_framing((0, 0, 0), (0, 1, 0), "CU", bands=BANDS)
    mcu = solve_framing((0, 0, 0), (0, 1, 0), "MCU", bands=BANDS)
    assert ecu.frame_height < cu.frame_height < mcu.frame_height


def test_eyes_only_cu_is_flagged_and_out_of_band():
    """只剩眼睛的 CU：framing_too_tight 带实测占比；回读不在 CU 区间。"""
    samples = [FrameSample(frame, "米迦尔", eyes_only_box(), 1.0, False,
                           "shot_002")
               for frame in range(1, 49, 4)]
    found = compare_with_intent(
        samples, DeclaredShot("shot_002", "CU", "米迦尔", "CU：面部特写"), CFG)
    tight = [w for w in found if w.type == "framing_too_tight"]
    assert len(tight) == 1
    assert tight[0].evidence["head_height_ratio"] > 1.0
    assert tight[0].evidence["expected_range"] == list(BANDS["head"]["CU"])
    assert tight[0].declared_intent == "CU：面部特写"

    detected, in_band = readback_shot_size(camera(85.0), eyes_only_box(),
                                           bands=BANDS)
    assert detected == "ECU"
    assert in_band is False


def test_out_of_band_readback_adjusts_the_distance_step_not_the_shot_type():
    base = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "CU", lens=85.0,
                         bands=BANDS)
    cam = camera(85.0)
    measured = frame_metrics(eyes_only_box())["head_height_ratio"]
    target = head_band_target("CU", BANDS["head"])
    expected = base.distance * measured / target
    assert readback_adjusted_distance(cam, eyes_only_box(), "CU",
                                      base.distance, bands=BANDS
                                      ) == pytest.approx(expected)

    fixed = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "CU", lens=85.0,
                          subject_box=eyes_only_box(), bands=BANDS)
    assert fixed.shot_type == "CU"                      # 不降级景别
    assert fixed.distance == pytest.approx(expected)
    assert any("距离档" in item for item in fixed.warnings)


def test_in_band_readback_leaves_the_distance_alone():
    base = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "CU", lens=85.0,
                         bands=BANDS)
    fixed = solve_framing((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), "CU", lens=85.0,
                          subject_box=projected_box(base), bands=BANDS)
    assert fixed.distance == pytest.approx(base.distance)
    assert not any("距离档" in item for item in fixed.warnings)


def test_the_solver_follows_config_bands_not_local_constants():
    """把 config 的 CU 区间换成 [0.60, 0.80] ⇒ 目标占比变 0.70、距离跟着变。"""
    custom = {"head": {**BANDS["head"], "CU": [0.60, 0.80]},
              "body": dict(BANDS["body"])}
    default = solve_framing((0, 0, 0), (0, 1, 0), "CU", bands=BANDS)
    overridden = solve_framing((0, 0, 0), (0, 1, 0), "CU", bands=custom)
    assert overridden.distance != pytest.approx(default.distance)
    metrics = frame_metrics(projected_box(overridden))
    assert 0.60 <= metrics["head_height_ratio"] <= 0.80
    assert metrics["head_height_ratio"] == pytest.approx(0.70)
    detected, in_band = readback_shot_size(camera(overridden.lens),
                                           projected_box(overridden),
                                           bands=custom)
    assert detected == "CU" and in_band is True


def test_readback_and_solver_are_deterministic():
    first = solve_framing((1.0, 2.0, 0.0), (0.0, 1.0, 0.0), "CU",
                          side="front_right", lens=85.0, bands=BANDS)
    second = solve_framing((1.0, 2.0, 0.0), (0.0, 1.0, 0.0), "CU",
                           side="front_right", lens=85.0, bands=BANDS)
    assert first == second
    box = projected_box(first)
    assert (readback_shot_size(camera(85.0), box, bands=BANDS)
            == readback_shot_size(camera(85.0), box, bands=BANDS))
    assert (readback_adjusted_distance(camera(85.0), eyes_only_box(), "CU",
                                       first.distance, bands=BANDS)
            == readback_adjusted_distance(camera(85.0), eyes_only_box(), "CU",
                                          first.distance, bands=BANDS))


def test_missing_bands_are_reported_not_silently_replaced():
    with pytest.raises(ValueError):
        readback_shot_size(camera(85.0), eyes_only_box(),
                           bands={"head": {}, "body": {}})
    with pytest.raises(ValueError):
        solve_framing((0, 0, 0), (0, 1, 0), "CU", bands={"head": {}, "body": {}})


def test_solver_uses_the_runtime_config_when_bands_are_omitted():
    """缺省 bands ⇒ 走 settings.get_config() → guard_config_from（唯一真源）。"""
    from block_director.settings import get_config

    runtime = guard_config_from(get_config())
    runtime_bands = {"head": dict(runtime.head_bands),
                     "body": dict(runtime.body_bands)}
    omitted = solve_framing((1.0, 2.0, 0.0), (0.0, 1.0, 0.0), "CU",
                            side="front_right")
    explicit = solve_framing((1.0, 2.0, 0.0), (0.0, 1.0, 0.0), "CU",
                             side="front_right", bands=runtime_bands)
    assert omitted.distance == pytest.approx(explicit.distance)
    assert omitted.frame_height == pytest.approx(explicit.frame_height)
