"""§4 剧本解析层测试：Fountain / FDX / 纯文本 / 对白计时。"""

from __future__ import annotations

import pytest

from block_director.layer1_input import (
    ScriptParseError,
    detect_format,
    estimate_dialogue_frames,
    parse_fdx,
    parse_fountain,
    parse_script,
    parse_text,
    schedule_dialogues,
)
from block_director.layer1_input.dialogue_timing import detect_emotion

CHINESE_FOUNTAIN = """\
Title: 咖啡馆的下午

INT. 咖啡馆 - 日

小明坐在靠窗的位置，手里拿着一封信。

小明
（低声）
她还是没有回信。

小红
别等了。

EXT. 街道 - 夜

小明走出门，抬头看了看天。
"""

LATIN_FOUNTAIN = """\
FADE IN:

INT. COFFEE SHOP - DAY

A man sits by the window.

MING
(quietly)
She never wrote back.

CUT TO:

EXT. STREET - NIGHT

He steps outside.
"""

FDX = """<?xml version="1.0" encoding="UTF-8"?>
<FinalDraft DocumentType="Script">
  <Content>
    <Paragraph Type="Scene Heading"><Text>INT. 咖啡馆 - 日</Text></Paragraph>
    <Paragraph Type="Action"><Text>小明坐下。</Text></Paragraph>
    <Paragraph Type="Character"><Text>小明</Text></Paragraph>
    <Paragraph Type="Parenthetical"><Text>（低声）</Text></Paragraph>
    <Paragraph Type="Dialogue"><Text>她还是没有回信。</Text></Paragraph>
    <Paragraph Type="Transition"><Text>CUT TO:</Text></Paragraph>
    <Paragraph Type="Character"><Text>小红</Text></Paragraph>
    <Paragraph Type="Dialogue"><Text>别等了。</Text></Paragraph>
  </Content>
</FinalDraft>
"""


# --------------------------------------------------------------------------- #
# Fountain
# --------------------------------------------------------------------------- #
def test_fountain_splits_scenes_and_extracts_elements():
    script = parse_fountain(CHINESE_FOUNTAIN)
    assert script.title == "咖啡馆的下午"
    assert len(script.scenes) == 2
    first, second = script.scenes
    assert first.heading == "INT. 咖啡馆 - 日"
    assert first.interior_exterior == "INT"
    assert first.location == "咖啡馆" and first.time_of_day == "日"
    assert len(first.actions) == 1
    assert len(first.dialogues) == 2
    assert second.location == "街道" and second.interior_exterior == "EXT"
    assert script.character_names == ["小明", "小红"]


def test_fountain_attaches_parentheticals():
    first = parse_fountain(CHINESE_FOUNTAIN).scenes[0]
    opening = first.dialogues[0]
    assert opening.character == "小明"
    assert opening.parenthetical == "低声"
    assert opening.text == "她还是没有回信。"
    assert first.dialogues[1].character == "小红"


def test_fountain_cast_anchor_names_survive_without_dialogue():
    #: iteration-fix T9：角色锚里点名的角色即使没有台词也必须进角色表，
    #: 否则模型的计划一带上他就会被 CAST_001 拒掉（伊恩只出镜不说话）。
    text = """Title: 市场

EXT. 码头 - 白天

【角色锚】米迦尔：兽人，只有四根手指的兽爪。伊恩：年轻男性，衣着朴素。偷盗者：身形瘦削。

【场景锚】第十四街区码头市场，白天晴天。

偷盗者
我发财了！

"""
    script = parse_fountain(text)
    assert script.character_names == ["米迦尔", "伊恩", "偷盗者"]
    assert script.cast_declarations == ["米迦尔", "伊恩", "偷盗者"]


def test_fountain_cast_anchor_multiline_format():
    #: fixtures 的写法：`【角色锚】` 独占一行，后续每行 `名字：描述`。
    text = """Title: 市场

EXT. 码头 - 白天

【角色锚】
米迦尔：兽人，只有四根手指的兽爪。
伊恩：年轻男性，衣着朴素。
偷盗者：身形瘦削的成年男性。

【场景锚】第十四街区码头市场。

偷盗者
我发财了！

"""
    script = parse_fountain(text)
    assert script.character_names == ["米迦尔", "伊恩", "偷盗者"]


def test_fountain_scene_anchor_text_is_collected():
    """R2-F5：剧本【场景锚】块原文要保留进解析结果。

    真跑里粗排参考 JSON 的 anchors=0，因为场景锚文本在解析层就丢了；
    粗排管线拿不到它，银币摊/生蚝摊/海面等导演声明的主体无法落世界坐标，
    shot_002 银币特写变成空墙。场景锚是导演的明确声明（不是猜），
    必须从剧本确定性提取，交给粗排/世界坐标求解。
    """
    text = """Title: 市场

EXT. 码头 - 白天

【角色锚】米迦尔：兽人，只有四根手指的兽爪。伊恩：年轻男性，衣着朴素。偷盗者：身形瘦削。

【场景锚】第十四街区码头市场，白天晴天，日光从画面深处的海面方向打来；市场内摊位、生蚝摊、围栏错落，纵深分明。

偷盗者
我发财了！

"""
    script = parse_fountain(text)
    assert script.scene_anchor_texts
    joined = "".join(script.scene_anchor_texts)
    assert "生蚝摊" in joined
    assert "银币摊" in joined or "摊位" in joined
    assert "海面" in joined


def test_fountain_does_not_mistake_action_for_a_cue():
    """动作行带句读、且较长，不能被当成角色名。"""
    first = parse_fountain(CHINESE_FOUNTAIN).scenes[0]
    assert all(d.character in ("小明", "小红") for d in first.dialogues)
    assert "小明坐在靠窗的位置，手里拿着一封信。" in first.actions[0].text


def test_latin_fountain_uses_uppercase_cues():
    script = parse_fountain(LATIN_FOUNTAIN)
    assert len(script.scenes) == 2
    names = [d.character for scene in script.scenes for d in scene.dialogues]
    assert names == ["MING"]
    # 转场与 FADE IN 不应变成动作或角色
    texts = [a.text for scene in script.scenes for a in scene.actions]
    assert all("CUT TO" not in text and "FADE IN" not in text for text in texts)


def test_chinese_scene_marker_is_recognised():
    script = parse_fountain("第一场 咖啡馆 日\n\n小明：你好。\n")
    assert script.scenes[0].heading.startswith("第一场")


def test_fountain_without_headings_falls_back_to_one_scene():
    script = parse_text("小明起身。\n他走到门口。\n")
    assert script.needs_llm_structure is True
    assert len(script.scenes) == 1
    assert script.warnings


def test_digest_is_compact_and_structured():
    digest = parse_fountain(CHINESE_FOUNTAIN).digest()
    assert "2 场" in digest and "小明" in digest
    assert "【INT. 咖啡馆 - 日】" in digest
    assert "（低声）" in digest


# --------------------------------------------------------------------------- #
# FDX
# --------------------------------------------------------------------------- #
def test_fdx_uses_paragraph_types():
    script = parse_fdx(FDX)
    assert script.source_format == "fdx"
    assert len(script.scenes) == 1
    scene = script.scenes[0]
    assert scene.location == "咖啡馆"
    assert [d.character for d in scene.dialogues] == ["小明", "小红"]
    assert scene.dialogues[0].parenthetical == "低声"
    assert scene.dialogues[0].text == "她还是没有回信。"


def test_fdx_rejects_broken_xml():
    with pytest.raises(ValueError):
        parse_fdx("<FinalDraft><Content>")


# --------------------------------------------------------------------------- #
# 文件分派
# --------------------------------------------------------------------------- #
def test_detect_format_by_suffix(tmp_path):
    assert detect_format(tmp_path / "a.fountain") == "fountain"
    assert detect_format(tmp_path / "a.FDX") == "fdx"
    assert detect_format(tmp_path / "a.txt") == "text"
    assert detect_format(tmp_path / "a.pdf") == "pdf"
    with pytest.raises(ScriptParseError):
        detect_format(tmp_path / "a.docx")


def test_parse_script_reads_a_file(tmp_path):
    path = tmp_path / "scene.fountain"
    path.write_text(CHINESE_FOUNTAIN, encoding="utf-8")
    script = parse_script(path)
    # 文件里的 Title: 行优先于文件名
    assert script.title == "咖啡馆的下午"
    assert len(script.scenes) == 2


def test_filename_used_when_script_has_no_title(tmp_path):
    path = tmp_path / "scene.fountain"
    path.write_text("INT. 咖啡馆 - 日\n\n小明坐着。\n", encoding="utf-8")
    assert parse_script(path).title == "scene"


def test_parse_script_reports_missing_file(tmp_path):
    with pytest.raises(ScriptParseError) as excinfo:
        parse_script(tmp_path / "nope.fountain")
    assert "不存在" in str(excinfo.value)


def test_pdf_without_dependency_gives_guidance(tmp_path, monkeypatch):
    """缺 pdfplumber 时要给出可执行的安装指引，而不是静默降级。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pdfplumber":
            raise ImportError("no pdfplumber")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from block_director.layer1_input.script_parser import parse_pdf

    with pytest.raises(ScriptParseError) as excinfo:
        parse_pdf(tmp_path / "a.pdf")
    message = str(excinfo.value)
    assert "pip install pdfplumber" in message
    assert ".txt" in message


# --------------------------------------------------------------------------- #
# 对白计时（§4.4）
# --------------------------------------------------------------------------- #
def test_emotion_rate_direction_is_not_inverted():
    """v1.0 的缺陷：生气被算得更慢、悲伤被算得更快。这里锁死正确方向。"""
    line = "她还是没有回信。"
    normal = estimate_dialogue_frames(line, "normal")
    angry = estimate_dialogue_frames(line, "angry")
    sad = estimate_dialogue_frames(line, "sad")
    assert angry < normal, "生气应当说得更快、占更少帧"
    assert sad > normal, "悲伤应当说得更慢、占更多帧"


def test_emotion_detected_from_parenthetical():
    assert detect_emotion("（愤怒地）") == "angry"
    assert detect_emotion("", "他猛地喊道") == "angry"
    assert detect_emotion("（低声）") in ("sad", "whisper")
    assert detect_emotion("（平静地）") == "normal"


def test_longer_text_takes_longer():
    short = estimate_dialogue_frames("好。")
    long = estimate_dialogue_frames("她还是没有回信，我不知道该说什么才好。")
    assert long > short


def test_minimum_duration_is_enforced():
    assert estimate_dialogue_frames("好") >= 8


def test_english_timing_uses_word_rate():
    frames = estimate_dialogue_frames("She never wrote back to me.")
    assert 20 < frames < 200


def test_punctuation_adds_pauses():
    without = estimate_dialogue_frames("你好")
    with_pause = estimate_dialogue_frames("你好，。")
    assert with_pause > without


def test_schedule_dialogues_assigns_increasing_spans():
    script = parse_fountain(CHINESE_FOUNTAIN)
    spans = schedule_dialogues(script.scenes[0].dialogues, start_frame=1)
    assert len(spans) == 2
    (start_a, end_a), (start_b, end_b) = spans
    assert start_a == 1 and end_a >= start_a
    assert start_b > end_a + 1                 # 中间留了停顿
    assert script.scenes[0].dialogues[0].start_frame == start_a
    assert script.scenes[0].dialogues[0].emotion == "whisper"
