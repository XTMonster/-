"""逐镜对白帧预算（§4.4）：数字必须来自引擎的单一真源，并真的进提示词。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long5/`）：
阶段 B1 是**唯一**给对白排帧的地方（`emit_shot_draft` 的
`dialogues[].start_frame/end_frame`），而它的提示词只说"对白必须落在镜头
时长内，并留出收尾余量"——既没给每句要几帧，也没给那 12 帧余量是多少。
结果 26 个镜头踩 S6，其中 24 个是**结构性不可行**的（引擎自己的估算就要
94–470 帧，计划只给了 48–96 帧）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.enums import ShotType  # noqa: E402
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.layer1_input.dialogue_timing import (  # noqa: E402
    DIALOGUE_GAP,
    DIALOGUE_TAIL_FRAMES,
    FPS,
    detect_emotion,
    estimate_dialogue_frames,
)
from block_director.layer5_orchestrator.dialogue_budget import (  # noqa: E402
    shot_dialogue_budget,
)


def shot_with(lines, *, duration, pins=None) -> ShotPlan:
    return ShotPlan(
        shot_id="shot_001", intent="推进", shot_type=ShotType.MS,
        duration_frames=duration,
        dialogues=[{"character_id": "char_001", "text": text,
                    "start_frame": 0, "end_frame": 0} for text in lines],
        dialogue_pins=list(pins or []),
    )


#: long5 的 shot_064：10 句台词塞在 3 秒（72 帧）里。
SHOT_064_LINES = [
    "我先上船。", "等等我。", "别拖了。", "这一次我听你的。", "走吧。",
    "照顾好自己。", "你也是。", "再见。", "再见。", "船要开了。",
]


def test_per_line_frames_come_from_the_single_source():
    shot = shot_with(["我先上船。", "别拖了。"], duration=240)
    budget = shot_dialogue_budget(shot)
    assert [line.text for line in budget.lines] == ["我先上船。", "别拖了。"]
    for line in budget.lines:
        expected = estimate_dialogue_frames(
            line.text, detect_emotion("", line.text))
        assert line.frames == expected
        assert line.source == "引擎估算"


def test_tail_and_gap_come_from_the_same_constants_as_the_audit():
    budget = shot_dialogue_budget(shot_with(["走吧。"], duration=96))
    assert budget.tail_frames == DIALOGUE_TAIL_FRAMES
    assert budget.gap_frames == int(round(DIALOGUE_GAP * FPS))
    assert budget.latest_allowed_end == 96 - DIALOGUE_TAIL_FRAMES


def test_shot_064_is_reported_infeasible_not_merely_mistimed():
    """这一条把这个缺陷的**性质**钉住：不是"差几帧"，是"根本装不下"。"""
    budget = shot_dialogue_budget(
        shot_with(SHOT_064_LINES, duration=72))
    assert budget.fits is False
    assert budget.required_frames > 72
    assert budget.overflow_frames == budget.required_frames - 72
    assert budget.spare_frames == 0
    #: 10 句里排得下的远少于 10 句——这正是"必须挪到别的镜头"的依据。
    assert 0 <= budget.max_lines < len(SHOT_064_LINES)
    text = budget.render()
    assert "装不下" in text
    assert f"超出 {budget.overflow_frames} 帧" in text
    assert str(budget.required_frames) in text
    assert f"第 {budget.latest_allowed_end} 帧" in text


def test_a_shot_that_fits_says_so_with_numbers():
    budget = shot_dialogue_budget(shot_with(["走吧。"], duration=96))
    assert budget.fits is True
    assert budget.spare_frames > 0
    text = budget.render()
    assert "装得下" in text
    assert f"{DIALOGUE_TAIL_FRAMES} 帧" in text


def test_declared_seconds_beat_the_speech_rate_estimate():
    """剧本写了时长就以剧本为准（§4.4 的 script_first），并如实标注来源。"""
    shot = shot_with(["我先上船。"], duration=240,
                     pins=[{"declared_s": 2.0, "speaker_raw": "米迦尔"}])
    budget = shot_dialogue_budget(shot)
    assert budget.lines[0].source == "剧本声明"
    assert budget.lines[0].frames == int(round(2.0 * FPS))


def test_misaligned_pins_do_not_lend_another_lines_declaration():
    """钉住的条数与台词条数不一致时不猜：一律退回引擎估算。"""
    shot = shot_with(["我先上船。", "别拖了。"], duration=240,
                     pins=[{"declared_s": 2.0, "speaker_raw": "米迦尔"}])
    budget = shot_dialogue_budget(shot)
    assert [line.source for line in budget.lines] == ["引擎估算", "引擎估算"]


def test_unscheduled_dialogue_still_gets_a_budget():
    """台词还没分配（阶段 A 只给了 `dialogue_ids`）时，B1 自己挑台词——
    那时唯一能给的预算就是"最后一句最晚结束在哪一帧 + 一句话最多几个字"。"""
    budget = shot_dialogue_budget(shot_with([], duration=48))
    assert budget.lines == []
    text = budget.render()
    assert f"第 {budget.latest_allowed_end} 帧以内" in text
    assert budget.single_line_char_cap() > 0
    assert f"最多 {budget.single_line_char_cap()} 个汉字" in text


def test_the_char_cap_uses_the_same_speech_rate_as_the_estimator():
    budget = shot_dialogue_budget(shot_with([], duration=120))
    cap = budget.single_line_char_cap()
    assert estimate_dialogue_frames("字" * cap) <= budget.latest_allowed_end
    assert estimate_dialogue_frames("字" * (cap + 1)) > budget.latest_allowed_end


def test_the_long_golden_plan_exposes_a_budget_for_every_shot():
    """长基线夹具（≥61 镜）每一镜都要算得出预算，不能有镜头卡住。"""
    import json

    fixture = ROOT / "fixtures" / "mock_llm_responses" / "plan_long.json"
    plan = Plan.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
    assert len(plan.shots) >= 61
    for shot in plan.shots:
        budget = shot_dialogue_budget(shot)
        assert budget.duration_frames == shot.duration_frames
        assert budget.latest_allowed_end >= 0
