"""检索种子接线（执行文档 v1.5 卡 P4-T5 / TDD §5.7）。

两档新种子：`构图=`（有闭集，能核）与 `光线=`（`VALUE_DOMAINS` 是 `None`，
核不了 ⇒ 今天一个都不写）。本文件钉三件事：

* 闭集**内**的取值真的发出去（`构图=lead_room`）；
* 闭集**外**的取值一个字都不发（不造死值）；
* `光线` 的通路结构在（候选取得到），但**没有闭集就不落串**——将来闭集/别名表
  落地时，这条用例会**明确地**红掉，提醒去更新读数口径（而不是悄悄开始发种子）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.beats import COMPOSITION_RULES  # noqa: E402
from block_director.knowledge.hypergraph import VALUE_DOMAINS  # noqa: E402
from block_director.layer5_orchestrator import scene_contract as SC  # noqa: E402


def _shot(**overrides):
    class Shot:
        shot_type = "MS"
        intent_type = "铺垫"
        declared_camera_move = "dolly_in"
        camera = {"lens": 50.0, "movements": []}
        actions = []
        vfx = []
        dialogues = []
        composition = {}

    for key, value in overrides.items():
        setattr(Shot, key, value)
    return Shot()


def _keys(query: str) -> set:
    return {part.split("=", 1)[0].strip()
            for part in str(query).split("；") if "=" in part}


# --------------------------------------------------------------------------- #
# 构图：有闭集 ⇒ 核得动
# --------------------------------------------------------------------------- #
def test_only_the_values_that_live_in_the_consumers_closed_set_are_emitted():
    in_domain = VALUE_DOMAINS["composition_rule"]
    for value in COMPOSITION_RULES:
        query = SC.shot_constraint_query(_shot(composition={"rule": value}))
        if value in in_domain:
            assert f"构图={value}" in query, value
        else:
            assert "构图" not in query, (value, query)


def test_an_empty_composition_declaration_writes_no_seed():
    assert "构图" not in SC.shot_constraint_query(_shot())
    assert "构图" not in SC.shot_constraint_query(
        _shot(composition={"rule": "", "subject_position": "left_third"}))


def test_the_composition_seed_does_not_displace_other_keys():
    base = SC.shot_constraint_query(_shot())
    with_seed = SC.shot_constraint_query(
        _shot(composition={"rule": "lead_room"}))
    assert _keys(with_seed) == _keys(base) | {"构图"}
    #: 其余键值逐字不变（新种子是**增**一档，不是重排/覆盖）。
    for part in base.split("；"):
        assert part in with_seed.split("；")


# --------------------------------------------------------------------------- #
# 光线：没有闭集 ⇒ 一个都不写（通路结构在，但不猜）
# --------------------------------------------------------------------------- #
def test_the_lighting_candidates_are_read_from_the_plan_environment():
    assert SC._light_candidates(
        {"light": {"time_of_day": "night", "mood": "gloomy"}}) == \
        ["night", "gloomy", "night/gloomy"]
    assert SC._light_candidates({"light": {"key_direction": "side"}}) == ["side"]
    #: 形状不对时既不猜也不崩。
    for broken in (None, {}, {"light": None}, {"light": "night"}, "night", 3):
        assert SC._light_candidates(broken) == []


def test_the_lighting_seed_is_not_written_while_the_domain_is_undeclared():
    assert VALUE_DOMAINS.get("lighting") is None, (
        "`VALUE_DOMAINS['lighting']` 不再是 `None`：闭集落地了 ⇒ 这条用例必须"
        "按新口径重写（以及 G4 的读数口径），不许当它还是旧的")
    query = SC.shot_constraint_query(
        _shot(), environment={"light": {"time_of_day": "night",
                                        "mood": "gloomy",
                                        "key_direction": "side"}})
    assert "光线" not in query
    assert query == SC.shot_constraint_query(_shot())


def test_the_query_stays_deterministic_with_the_environment_supplied():
    environment = {"light": {"time_of_day": "day", "mood": "bright"}}
    first = SC.shot_constraint_query(_shot(), environment=environment)
    second = SC.shot_constraint_query(_shot(), environment=environment)
    assert first == second
