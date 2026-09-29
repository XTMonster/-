"""v1.4 X17：``crowd.enabled`` 是三态，优先级 显式 false > 剧本声明 > 默认关。

v1.3 的 ``enabled: bool = False`` 让"没写"与"显式关闭"无法区分，
``bool(crowd_config.enabled)`` 会把剧本里写明的"约三十名商贩"一并抹掉。
"""

from __future__ import annotations

from pathlib import Path

from block_director.contracts.cast import crowd_from_script
from block_director.contracts.config import CrowdConfig
from block_director.layer1_input import parse_script

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "fixtures" / "shotlist_market.md"


def test_default_is_none_not_false():
    assert CrowdConfig().enabled is None


def test_none_follows_the_script_declaration():
    script = parse_script(MARKET)
    result = crowd_from_script(script, enabled=None, max_instances=40)
    assert result and result[0]["count"] == 30


def test_explicit_false_wins_over_the_declaration():
    script = parse_script(MARKET)
    assert crowd_from_script(script, enabled=False, max_instances=40) == []


def test_explicit_true_still_requires_a_declaration():
    """强制开启也只按剧本来——不能凭空造出群众。"""
    from block_director.layer1_input.model import ParsedScript

    quiet = ParsedScript()
    assert quiet.declared_shots == []
    assert crowd_from_script(quiet, enabled=True) == []
