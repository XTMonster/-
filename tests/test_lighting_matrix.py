"""灯光语义 → 预设矩阵（执行文档 v1.5 卡 P3-T3 / TDD §4.5）。纯 Python。"""

from __future__ import annotations

from block_director.cinema.lighting import (
    DEFAULT_LIGHTING_PRESET,
    LIGHT_DIRECTION_VARIANTS,
    LIGHT_MATRIX,
    LIGHTING_PRESET_NAMES,
    resolve_lighting,
    resolve_lighting_preset,
)
from block_director.contracts.beats import LightSpec


def test_every_matrix_cell_points_at_an_existing_preset():
    """矩阵里出现的预设名必须落在键名契约里（引擎侧的键集由 Blender 探针双向对拍）。"""
    for cell, preset in LIGHT_MATRIX.items():
        assert preset in LIGHTING_PRESET_NAMES, cell


def test_the_matrix_covers_the_documented_grid():
    """TDD §4.5 的表：4 个时间 × 4 个情绪组 = 16 格，一格不缺。"""
    assert len(LIGHT_MATRIX) == 16
    for time_of_day in ("day", "night", "dusk", "dawn"):
        for column in ("bright", "neutral", "shade", "soft"):
            assert (time_of_day, column) in LIGHT_MATRIX


def test_each_row_of_the_published_table_matches_the_matrix():
    """把 TDD §4.5 的表逐格抄成断言——表漂了这里就红。"""
    expected = {
        ("day", "bright"): "outdoor_sun",
        ("day", "neutral"): "clay_studio",
        ("day", "gloomy"): "indoor_soft",
        ("day", "tense"): "indoor_soft",
        ("day", "soft"): "indoor_soft",
        ("night", "bright"): "studio3p",
        ("night", "neutral"): "night",
        ("night", "gloomy"): "night",
        ("night", "tense"): "night",
        ("night", "soft"): "night",
        ("dusk", "bright"): "outdoor_sun",
        ("dusk", "neutral"): "indoor_soft",
        ("dusk", "gloomy"): "indoor_soft",
        ("dawn", "bright"): "outdoor_sun",
        ("dawn", "neutral"): "indoor_soft",
        ("dawn", "gloomy"): "indoor_soft",
    }
    for (time_of_day, mood), preset in expected.items():
        got = resolve_lighting_preset(
            {"time_of_day": time_of_day, "mood": mood})
        assert got == preset, (time_of_day, mood)


def test_light_spec_objects_are_accepted():
    assert resolve_lighting_preset(LightSpec(time_of_day="night",
                                             mood="gloomy")) == "night"


def test_an_empty_declaration_is_the_default_and_says_nothing():
    preset, notes = resolve_lighting({})
    assert preset == DEFAULT_LIGHTING_PRESET
    assert notes == []
    assert resolve_lighting(LightSpec())[1] == []


def test_an_unknown_value_falls_back_and_records_why():
    preset, notes = resolve_lighting({"time_of_day": "midnight", "mood": "bright"})
    assert preset == DEFAULT_LIGHTING_PRESET
    assert len(notes) == 1 and "time_of_day" in notes[0]


def test_a_half_declared_light_falls_back_and_records_why():
    """只有一半定位不到矩阵格——回落并说明，不猜时间也不猜情绪。"""
    preset, notes = resolve_lighting({"mood": "bright"})
    assert preset == DEFAULT_LIGHTING_PRESET
    assert len(notes) == 1 and "time_of_day" in notes[0]
    preset, notes = resolve_lighting({"time_of_day": "night"})
    assert preset == DEFAULT_LIGHTING_PRESET
    assert len(notes) == 1 and "mood" in notes[0]


def test_key_direction_without_a_variant_is_ignored_and_recorded():
    """现状是空变体表：声明方向不改变预设，但必须留下"我忽略了它"。"""
    assert LIGHT_DIRECTION_VARIANTS == {}
    preset, notes = resolve_lighting({"time_of_day": "day", "mood": "bright",
                                      "key_direction": "back"})
    assert preset == "outdoor_sun"
    assert len(notes) == 1 and "无对应预设变体" in notes[0]


def test_key_direction_applies_once_a_variant_exists():
    """变体表是唯一的开关：填一格就生效，函数本身不动。"""
    variants = {("outdoor_sun", "back"): "clay_studio"}
    preset, notes = resolve_lighting(
        {"time_of_day": "day", "mood": "bright", "key_direction": "back"},
        variants=variants)
    assert preset == "clay_studio"
    assert notes and "变体" in notes[0]


def test_an_invalid_key_direction_is_recorded():
    _preset, notes = resolve_lighting({"time_of_day": "day", "mood": "bright",
                                       "key_direction": "sideways"})
    assert notes and "key_direction" in notes[0]


def test_the_five_original_presets_are_untouched():
    """既有五键是引擎的底座，矩阵只做映射——一个键都不许改名或删除。"""
    for key in ("clay_studio", "indoor_soft", "outdoor_sun", "night",
                "studio3p"):
        assert key in LIGHTING_PRESET_NAMES
    assert len(set(LIGHTING_PRESET_NAMES)) == 5
