"""v1.4 D-2 / D-3：别名与群众数量的声明侧口径。

* **D-3**：``莉莉安娜（贵妇）`` 的括注是**别名**，正式名只有一个——旧实现
  整段比对，于是同一个人变成零个角色（或两个）。
* **D-2**：``无路人入镜`` 判 0；``约三十名商贩`` 判 30。两个分句必须分开判，
  而且"约/近/共"是**数量修饰词**、不是否定词。
"""

from __future__ import annotations

from pathlib import Path

from block_director.contracts.cast import (
    crowd_from_script,
    parse_chinese_number,
)
from block_director.layer1_input import parse_script
from block_director.layer1_input.shotlist import split_alias

ROOT = Path(__file__).resolve().parents[1]
NODE5 = ROOT / "fixtures" / "script_node5_8_lines.md"
MARKET = ROOT / "fixtures" / "shotlist_market.md"


def test_split_alias_takes_the_parenthetical_as_alias():
    assert split_alias("莉莉安娜（贵妇）") == ("莉莉安娜", "贵妇")
    assert split_alias("伊恩") == ("伊恩", "")
    assert split_alias("莉莉安娜(B贵妇)") == ("莉莉安娜", "B贵妇")


def test_named_character_keeps_one_canonical_identity():
    script = parse_script(NODE5)
    shots = script.declared_shots
    assert "莉莉安娜" in shots[1].characters
    assert "莉莉安娜（贵妇）" not in shots[1].characters
    assert script.character_aliases.get("莉莉安娜") == ["贵妇"]


def test_chinese_numbers_are_parsed():
    assert parse_chinese_number("三十") == 30
    assert parse_chinese_number("二十五") == 25
    assert parse_chinese_number("一百二十") == 120
    assert parse_chinese_number("两") == 2
    assert parse_chinese_number("十") == 10
    assert parse_chinese_number("很多") is None


def test_negated_clause_yields_no_crowd_but_the_positive_one_does():
    """D-2 的分句对照：一句话里"无路人"与"约三十名商贩"互不影响。"""
    script = parse_script(NODE5)
    crowd = crowd_from_script(script, enabled=None, max_instances=40)
    assert crowd and crowd[0]["count"] == 30


def test_market_fixture_still_reads_30_people():
    """回归：既有的市场剧本是 30 名路人（§1.6 #12 依赖它）。"""
    script = parse_script(MARKET)
    crowd = crowd_from_script(script, enabled=None, max_instances=40)
    assert crowd and crowd[0]["count"] == 30
