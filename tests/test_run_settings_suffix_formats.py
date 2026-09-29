"""v1.4 US-1③：面板的剧本格式说明串与 ``SUFFIX_FORMATS`` 同源。

v1.3 的面板写死了一句 "（.fountain/.txt/.fdx/.pdf）"，实测漏了 ``.md`` 与
``.text``。用户在面板上看到的就是这句，于是"面板不支持 .md"的错误印象
一直存在。修法不是再手写一句（那还会漂），而是让说明串**派生**自
``layer1_input.script_parser.SUFFIX_FORMATS``（单一真源）。

落点是**无 bpy** 的 ``layer7_ui/run_settings.py``：``panel_main.py`` 顶层
``import bpy``，纯层单测进不去。
"""

from __future__ import annotations

from block_director.layer1_input.script_parser import SUFFIX_FORMATS
from block_director.layer7_ui.run_settings import SUFFIX_HELP, suffix_help


def test_help_covers_every_supported_suffix():
    for suffix in SUFFIX_FORMATS:
        assert suffix in SUFFIX_HELP, suffix


def test_help_is_a_sentence_not_a_dict_repr():
    assert "{" not in SUFFIX_HELP and "}" not in SUFFIX_HELP
    assert "'" not in SUFFIX_HELP
    assert SUFFIX_HELP.startswith("支持的剧本格式")


def test_negative_a_new_suffix_shows_up_without_editing_the_string():
    """负例：往源表里加一个后缀，说明串必须自动跟上。"""
    rendered = suffix_help({".fountain": "fountain", ".xyz": "text"})
    assert ".xyz" in rendered and ".fountain" in rendered


def test_negative_a_hand_written_string_would_fail_this():
    """负例：把说明串改成与源表不一致（旧面板那句）→ 必须断言失败。"""
    stale = "导入的剧本文件（.fountain/.txt/.fdx/.pdf）"
    assert any(suffix not in stale for suffix in SUFFIX_FORMATS)
    assert SUFFIX_HELP != stale
