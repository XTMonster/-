"""v1.7 卡 I2：运镜文字化器（手算夹具对拍 + 24 词表 + 边界）。"""

from __future__ import annotations

from block_director.cinema.camera_narration import (
    MOVEMENT_VERB,
    narrate,
)
from block_director.contracts.enums import MOVEMENT_TYPES, Movement


def _samples(points, movement=None, lens=None):
    return [{"frame": index, "position": list(point),
             "look_at": [0.0, 0.0, 0.0],
             "lens": lens[index] if isinstance(lens, list) else lens,
             "movement": movement}
            for index, point in enumerate(points)]


def test_dolly_in():
    #: 引擎朝向约定 front=facing（framing.py:363）。卡片夹具写"朝 +Y"与断言
    #: "含前"在该约定下矛盾（+Y 朝向下相机 (0,-4) 在正后方）；按断言取
    #: facing=-Y（相机在主体正前），相机坐标照卡片原值。
    text = narrate(_samples([(0.0, -4.0, 1.6), (0.0, -1.5, 1.6)],
                            movement="dolly_in"),
                   (0.0, 0.0, 0.0), (0.0, -1.0, 0.0))
    assert "前" in text
    assert "推进" in text


def test_truck():
    #: 主体面朝 +Y，相机在正前方横向（X）移动：前左 → 前右。
    text = narrate(_samples([(2.0, 2.0, 1.6), (-2.0, 2.0, 1.6)],
                            movement="track_right"),
                   (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert "前左" in text
    assert "前右" in text


def test_arc_180():
    points = [(0.0, 4.0, 1.6), (4.0, 0.0, 1.6), (0.0, -4.0, 1.6)]
    text = narrate(_samples(points, movement="orbit_cw"),
                   (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert text.startswith("从前")
    assert "到后" in text


def test_static():
    text = narrate(_samples([(0.0, 3.0, 1.6), (0.0, 3.01, 1.6)], lens=50.0),
                   (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert text == "固定机位"


def test_zoom_not_static():
    text = narrate(_samples([(0.0, 3.0, 1.6), (0.0, 3.01, 1.6)],
                            lens=[24.0, 50.0]),
                   (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert "变焦" in text
    assert "固定机位" not in text


def test_verb_table_covers_enums():
    assert set(MOVEMENT_VERB) == {item.value for item in Movement}
    assert len(MOVEMENT_VERB) == 24
    assert MOVEMENT_TYPES == tuple(item.value for item in Movement)


def test_multi_subject_anchor_is_caller_side():
    #: 质心锚点由调用方算好传入，函数行为与单主体等价（不内部再分主体）。
    centroid = (1.0, 0.0, 0.0)
    text = narrate(_samples([(1.0, -3.0, 1.6), (1.0, -1.0, 1.6)],
                            movement="dolly_in"),
                   centroid, (0.0, -1.0, 0.0))
    assert "推进" in text
