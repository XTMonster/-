"""§7.6 循环检测测试。"""

from __future__ import annotations

from block_director.layer5_orchestrator.loop_detector import LoopDetector


def test_no_report_when_working_normally():
    detector = LoopDetector()
    detector.record("setup_camera", {"shot_id": "shot_001"})
    detector.record("place_character", {"character_id": "char_001"})
    assert detector.detect() is None


def test_repeated_identical_calls_are_flagged():
    detector = LoopDetector(repeat_threshold=3)
    for _ in range(3):
        detector.record("setup_camera", {"shot_id": "shot_001"})
    report = detector.detect()
    assert report is not None and report.kind == "repeat"
    assert "setup_camera" in report.message


def test_same_tool_with_different_args_is_not_a_repeat():
    detector = LoopDetector(repeat_threshold=3)
    for index in range(3):
        detector.record("setup_camera", {"shot_id": f"shot_{index:03d}"})
    assert detector.detect() is None


def test_query_only_streak_is_flagged():
    detector = LoopDetector(query_streak_limit=3)
    for _ in range(3):
        detector.record("get_scene_state", {})
    report = detector.detect()
    assert report is not None and report.kind == "query_only"


def test_modifying_call_resets_the_query_streak():
    # 这里只验证"连续查询计数"，把重复调用阈值调高以免干扰
    detector = LoopDetector(query_streak_limit=3, repeat_threshold=99)
    detector.record("get_scene_state", {})
    detector.record("get_scene_state", {})
    detector.record("place_character", {"character_id": "char_001"})
    detector.record("get_scene_state", {})
    assert detector.detect() is None


def test_oscillation_is_flagged():
    detector = LoopDetector(oscillation_window=4, repeat_threshold=99,
                            query_streak_limit=99)
    for name, args in (("setup_camera", {"a": 1}), ("place_character", {"b": 2}),
                       ("setup_camera", {"a": 1}), ("place_character", {"b": 2})):
        detector.record(name, args)
    report = detector.detect()
    assert report is not None and report.kind == "oscillation"


def test_reset_clears_history():
    detector = LoopDetector(repeat_threshold=2)
    detector.record("nod", {})
    detector.record("nod", {})
    assert detector.detect() is not None
    detector.reset()
    assert detector.detect() is None
    assert detector.stats["calls"] == 0
