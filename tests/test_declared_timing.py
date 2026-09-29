"""诉求 6：语速以剧本声明为准（v1.3）。

实测背景：一份声明总时长 33 秒的分镜表被 3 字/秒的估算拉成 39.54 秒，
镜头 4 从 6 秒变 8 秒、镜头 6 从 7 秒变 11.5 秒。
"""

from __future__ import annotations

import pytest

from block_director.layer1_input import (
    estimate_dialogue_frames,
    parse_text,
    render_timing_table,
    schedule_dialogues,
)
from block_director.layer1_input.timing import (
    DeclaredTiming,
    extract_declared_seconds,
    frames_from_seconds,
)

#: 用户剧本里的六句台词，时长由剧本声明。
DECLARED_LINES = (
    ("米迦尔", "伊恩，这里就交给我吧！", 3.0),
    ("伊恩", "好的，那你多小心一些。", 3.0),
    ("米迦尔", "放心吧。", 1.0),
    ("米迦尔", "看我怎么惩罚他，让他砰的一声，嘻嘻。", 4.0),
    ("偷盗者", "怎么回事，不应该只是普通的银币么？", 3.0),
    ("偷盗者", "哈哈，一定是命运眷顾，我发财了！", 4.0),
)


def _annotated_fountain() -> str:
    parts = ["INT. 码头市场 - 午后", ""]
    for speaker, text, seconds in DECLARED_LINES:
        parts += [speaker, f"{text}（约{seconds:g}秒）", ""]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 抽取
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected_text,expected_seconds", [
    ("好的，那你多小心一些。（约3秒）", "好的，那你多小心一些。", 3.0),
    ('"伊恩，这里就交给我吧！"（约3秒）', '"伊恩，这里就交给我吧！"', 3.0),
    ("放一百个心。(2.5s)", "放一百个心。", 2.5),
    ("走着瞧（约 4 秒）", "走着瞧", 4.0),
])
def test_extract_declared_seconds(text, expected_text, expected_seconds):
    cleaned, seconds = extract_declared_seconds(text)
    assert cleaned == expected_text
    assert seconds == pytest.approx(expected_seconds)


@pytest.mark.parametrize("text", [
    "（低声）你还在听吗。",          # 表演提示不是时长
    "你还在听吗。",
    "3秒",
    "他说了 3 秒（但这不是时长声明）",
    "",
])
def test_non_declarations_are_left_alone(text):
    cleaned, seconds = extract_declared_seconds(text)
    assert cleaned == text
    assert seconds is None


def test_frames_from_seconds_rounds_and_keeps_a_floor():
    assert frames_from_seconds(3.0) == 72
    assert frames_from_seconds(2.5) == 60
    assert frames_from_seconds(0.01) == 1


# --------------------------------------------------------------------------- #
# 解析：注释被抽走，台词文本保持干净
# --------------------------------------------------------------------------- #
def test_fountain_records_the_declaration_and_cleans_the_text():
    script = parse_text(_annotated_fountain())
    dialogues = [d for scene in script.scenes for d in scene.dialogues]
    assert len(dialogues) == len(DECLARED_LINES)
    for dialogue, (speaker, text, seconds) in zip(dialogues, DECLARED_LINES):
        assert dialogue.character == speaker
        assert dialogue.text == text            # 注释不留在台词里
        assert dialogue.declared_seconds == pytest.approx(seconds)


# --------------------------------------------------------------------------- #
# 优先级：声明覆盖引擎估算
# --------------------------------------------------------------------------- #
def test_declared_duration_overrides_the_speed_estimate():
    text = "伊恩，这里就交给我吧！"
    engine = estimate_dialogue_frames(text, timing_source="engine")
    declared = estimate_dialogue_frames(text, declared_seconds=3.0)
    assert engine != declared
    assert declared == 72                       # 3 秒 × 24fps
    assert engine > declared                    # 3 字/秒算出来更长


def test_timing_source_engine_ignores_declarations():
    text = "伊恩，这里就交给我吧！"
    assert estimate_dialogue_frames(text, declared_seconds=3.0,
                                    timing_source="engine") == \
        estimate_dialogue_frames(text, timing_source="engine")


def test_schedule_uses_the_declared_durations():
    script = parse_text(_annotated_fountain())
    dialogues = [d for scene in script.scenes for d in scene.dialogues]
    spans = schedule_dialogues(dialogues)
    lengths = [end - start + 1 for start, end in spans]
    assert lengths == [frames_from_seconds(seconds)
                       for _speaker, _text, seconds in DECLARED_LINES]
    # 声明值确实比引擎估算短（这正是 33 秒 vs 39.5 秒的差距来源）
    engine_lengths = [end - start + 1 for start, end in
                      schedule_dialogues(
                          [d for scene in parse_text(_annotated_fountain())
                           .scenes for d in scene.dialogues],
                          timing_source="engine")]
    assert sum(lengths) < sum(engine_lengths)


# --------------------------------------------------------------------------- #
# 注入给规划模型的表必须标明来源
# --------------------------------------------------------------------------- #
def test_timing_table_marks_the_declared_entries():
    script = parse_text(_annotated_fountain())
    table = render_timing_table(script)
    rows = [line for line in table.splitlines() if line.startswith("- ")]
    assert len(rows) == len(DECLARED_LINES)
    assert all("剧本声明" in line for line in rows)   # 六句全部有声明
    assert "6 句的时长由剧本声明" in table


def test_timing_table_falls_back_to_the_engine_when_nothing_is_declared():
    script = parse_text("INT. 房间 - 日\n\n小明\n你还在听吗。\n")
    table = render_timing_table(script)
    rows = [line for line in table.splitlines() if line.startswith("- ")]
    assert rows and all("引擎估算" in line for line in rows)
    assert "剧本声明" not in table


def test_declared_timing_serialises():
    item = DeclaredTiming(scope="dialogue", seconds=3.0, ref="d1",
                          source_index=4, raw="（约3秒）")
    assert item.frames == 72
    assert item.to_dict()["scope"] == "dialogue"
