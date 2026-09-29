"""v1.4 D-1：行内台词不许被"字段"整行吃掉。

真实分镜表里非常常见的一种写法是::

    画面内容：米迦尔上前一步。米迦尔：“我先上船。”（约3秒）

v1.3 的 ``DIALOGUE_RE`` 只匹配**行首**，于是这行被 ``FIELD_RE`` 当成
``画面内容`` 整条收走——台词凭空消失，R016 也就永远发现不了它。
"""

from __future__ import annotations

from pathlib import Path

from block_director.layer1_input import parse_script

ROOT = Path(__file__).resolve().parents[1]
NODE5 = ROOT / "fixtures" / "script_node5_8_lines.md"


def test_inline_dialogue_is_recorded_with_its_declared_duration():
    script = parse_script(NODE5)
    first = script.declared_shots[0]
    texts = [item.text for item in first.dialogues]
    assert "我先上船。" in texts and "别去。" in texts
    declared = {item.character: item.declared_seconds
                for item in first.dialogues}
    assert declared["米迦尔"] == 3.0


def test_inline_speakers_become_known_speakers():
    """拿不到说话人名单，"角色：米迦尔、伊恩"就会被整条丢掉。"""
    script = parse_script(NODE5)
    assert set(script.character_names) >= {"米迦尔", "伊恩"}
    assert "米迦尔" in script.declared_shots[0].characters
    assert "伊恩" in script.declared_shots[0].characters


def test_field_text_is_still_kept_verbatim():
    """台词被抽出来之后，``画面内容`` 原文仍要留在字段里（它是拍摄依据）。"""
    script = parse_script(NODE5)
    body = script.declared_shots[0].field("画面内容")
    assert "米迦尔上前一步" in body


def test_line_start_dialogue_still_works():
    """回归：整行就是一句台词时（原来的唯一形态）路径不变。"""
    from block_director.layer1_input import parse_shot_list

    script, _shot_list = parse_shot_list(
        "镜号：1\n预估时长：3秒\n画面内容：\u5bf9\u5cd9\u3002\n"
        "\u7c73\u8fe6\u5c14\uff1a\u201c\u6211\u5728\u3002\u201d\uff08\u7ea62\u79d2\uff09\n")
    assert script.dialogue_count == 1
    dialogue = script.scenes[0].dialogues[0]
    assert dialogue.text == "我在。"
    assert dialogue.declared_seconds == 2.0
