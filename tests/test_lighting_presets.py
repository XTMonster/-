"""卡 G1（D-18）纯层测试：``key_direction`` 三个合法值各命中预设 ＋ side 变体登记。

对应 TDD v1.6 §8 的 ``tests/test_lighting_presets.py``：判据是**每个合法方向
都能解析出一个真预设**（不再有"已忽略"），且 ``side`` 变体确实登记在
``LIGHT_DIRECTION_VARIANTS`` 里。引擎侧灯位的方位角由 Blender 探针
``tools/blender_tests/test_lighting_presets.py`` 对拍，这里只验纯层。
"""

from __future__ import annotations

from block_director.cinema.lighting import (
    KEY_DIRECTION_AZIMUTH_DEG,
    LIGHT_DIRECTION_VARIANTS,
    LIGHT_MATRIX,
    LIGHTING_PRESET_NAMES,
    resolve_lighting,
)
from block_director.contracts.beats import KEY_DIRECTION_VALUES

BASE_PRESETS = ("clay_studio", "indoor_soft", "outdoor_sun", "night",
                "studio3p")
#: 矩阵键用的是内部列名（"shade"），resolve 的契约面只认公开 mood 闭集。
COLUMN_TO_MOOD = {"bright": "bright", "neutral": "neutral",
                  "shade": "gloomy", "soft": "soft"}


def test_side_variants_are_registered_for_every_base_preset():
    for base in BASE_PRESETS:
        assert (base, "side") in LIGHT_DIRECTION_VARIANTS, base


def test_every_base_preset_has_all_three_direction_variants():
    assert sorted(LIGHT_DIRECTION_VARIANTS) == sorted(
        (base, direction)
        for base in BASE_PRESETS for direction in KEY_DIRECTION_VALUES)


def test_every_variant_name_is_in_the_preset_contract():
    for variant in LIGHT_DIRECTION_VARIANTS.values():
        assert variant in LIGHTING_PRESET_NAMES, variant


def test_variant_names_encode_base_and_direction():
    for (base, direction), variant in LIGHT_DIRECTION_VARIANTS.items():
        assert variant == f"{base}_{direction}", (base, direction)


def test_every_legal_key_direction_resolves_to_a_preset():
    """每个矩阵格 × 每个合法方向都必须命中预设，且不许出现"已忽略"。"""
    for (time_of_day, column), _base in LIGHT_MATRIX.items():
        mood = COLUMN_TO_MOOD[column]
        for direction in KEY_DIRECTION_VALUES:
            preset, notes = resolve_lighting(
                {"time_of_day": time_of_day, "mood": mood,
                 "key_direction": direction})
            assert preset in LIGHTING_PRESET_NAMES, (time_of_day, mood,
                                                     direction)
            assert not any("已忽略" in note or "无对应预设变体" in note
                           for note in notes), notes
            assert any("变体" in note for note in notes), notes


def test_a_side_declaration_selects_the_side_variant():
    preset, notes = resolve_lighting(
        {"time_of_day": "day", "mood": "bright", "key_direction": "side"})
    assert preset == "outdoor_sun_side"
    assert notes == ["key_direction=side → 预设变体 outdoor_sun_side"]


def test_side_is_the_perpendicular_direction():
    """side 的主光方位角必须垂直于相机轴；front/back 落在相机轴上、彼此相反。"""
    assert sorted(KEY_DIRECTION_AZIMUTH_DEG) == sorted(KEY_DIRECTION_VALUES)
    for _direction, azimuth in KEY_DIRECTION_AZIMUTH_DEG.items():
        assert 0.0 <= azimuth < 360.0
    front = KEY_DIRECTION_AZIMUTH_DEG["front"]
    side = KEY_DIRECTION_AZIMUTH_DEG["side"]
    back = KEY_DIRECTION_AZIMUTH_DEG["back"]
    assert (front - side) % 360.0 in (90.0, 270.0)
    assert (back - side) % 360.0 in (90.0, 270.0)
    assert (front - back) % 360.0 == 180.0


def test_the_base_matrix_is_unchanged_by_direction():
    """不声明方向时依旧落在基础预设——变体只在声明方向时才生效。"""
    for (time_of_day, column), base in LIGHT_MATRIX.items():
        mood = COLUMN_TO_MOOD[column]
        preset, notes = resolve_lighting(
            {"time_of_day": time_of_day, "mood": mood})
        assert preset == base, (time_of_day, mood)
        assert notes == []


def test_an_illegal_direction_still_falls_back_and_records():
    preset, notes = resolve_lighting({"time_of_day": "day", "mood": "bright",
                                      "key_direction": "sideways"})
    assert preset == "outdoor_sun"
    assert len(notes) == 1
    assert "key_direction" in notes[0] and "闭集" in notes[0]
