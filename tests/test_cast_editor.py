"""§13.1 角色管理的纯逻辑测试（id 分配）。

``next_character_id`` 放在契约层（而不是 ``layer3_engine``），因此这条测试
在 Blender 之外也能跑——这也正是它被搬过去的原因。
"""

from __future__ import annotations

from block_director.contracts.cast import next_character_id


def test_first_id_is_char_001():
    assert next_character_id([]) == "char_001"


def test_ids_fill_the_lowest_gap():
    assert next_character_id(["char_001", "char_002"]) == "char_003"
    assert next_character_id(["char_001", "char_003"]) == "char_002"
    assert next_character_id(["char_002", "char_003"]) == "char_001"


def test_ids_grow_beyond_the_width():
    ids = [f"char_{index:03d}" for index in range(1, 100)]
    assert next_character_id(ids) == "char_100"


def test_unrelated_and_malformed_ids_are_ignored():
    assert next_character_id(["小明", "char_abc", "", "char_2"]) == "char_001"
    assert next_character_id(["char_1"]) == "char_002"     # 位数不固定也能认出
