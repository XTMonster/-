"""九宫格图像版（用户 2026-10-11）：把视口同源的 ``thirds_grid()`` 画进
渲染帧。纯 stdlib（zlib PNG），Blender 自带 Python 可直接用。
"""

from __future__ import annotations

import pytest

from block_director.overlay import grid_frame as GF
from block_director.overlay.geometry import thirds_grid


def _solid_rgb(width, height, rgb=(20, 20, 20)):
    return GF.encode_png(width, height, 3,
                         [bytes(rgb) * width for _ in range(height)])


def test_png_round_trip_is_lossless():
    width, height = 4, 3
    rows = [bytes([r, g, b]) * width for (r, g, b) in
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)]]
    data = GF.encode_png(width, height, 3, rows)
    out_w, out_h, channels, out_rows = GF.decode_png(data)
    assert (out_w, out_h, channels) == (width, height, 3)
    assert out_rows == rows


def test_grid_lines_land_on_the_thirds_of_the_pixels():
    width = height = 12
    data = GF.grid_frame(_solid_rgb(width, height), color=(0, 255, 0),
                         thickness=2, alpha=255)
    _, _, _, rows = GF.decode_png(data)

    def pixel(x, y):
        return tuple(rows[y][x * 3:x * 3 + 3])

    # 12 × 1/3 = 4、12 × 2/3 = 8：厚度 2 ⇒ 第 4、5 与第 8、9 列/行是线
    assert pixel(4, 6) == (0, 255, 0)
    assert pixel(5, 6) == (0, 255, 0)
    assert pixel(8, 6) == (0, 255, 0)
    assert pixel(6, 4) == (0, 255, 0)
    assert pixel(6, 8) == (0, 255, 0)
    # 网格之外仍是底色
    assert pixel(1, 1) == (20, 20, 20)


def test_grid_segments_come_from_the_viewport_source():
    drawn = GF.grid_segments()
    assert drawn == thirds_grid()


def test_unsupported_png_is_reported_not_guessed():
    with pytest.raises(ValueError):
        GF.decode_png(b"\x89PNG\r\n\x1a\n not-a-real-png")


def test_grid_frame_file_writes_a_copy_and_keeps_the_original(tmp_path):
    source = tmp_path / "shot_001.png"
    source.write_bytes(_solid_rgb(12, 12))
    original = source.read_bytes()
    out = GF.grid_frame_file(str(source), alpha=255)
    assert out == str(tmp_path / "shot_001_grid.png")
    assert source.read_bytes() == original        # 原图不动
    data = GF.decode_png(open(out, "rb").read())
    assert data[2] == 3
    assert tuple(data[3][6][4 * 3:4 * 3 + 3]) == (0, 255, 0)
