"""九宫格图像版（用户 2026-10-11）：把三分线画进渲染帧，喂给多模态评委。

只依赖 stdlib（zlib + struct），因此**Blender 自带 Python 也能跑**（PNG 的
IDAT 就是 zlib 流）。支持 8-bit RGB / RGBA、非隔行；其它形状（调色板、
16-bit、隔行）如实报 ValueError，不猜。

网格线段与视口叠加**同源**：``overlay.geometry.thirds_grid()``。
"""

from __future__ import annotations

import struct
import zlib
from typing import List, Sequence, Tuple

import pathlib

from .geometry import thirds_grid

_SIGNATURE = b"\x89PNG\r\n\x1a\n"

Segment2D = Tuple[Tuple[float, float], Tuple[float, float]]


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _channels_of(color_type: int) -> int:
    if color_type == 2:
        return 3
    if color_type == 6:
        return 4
    raise ValueError(f"不支持的 PNG color_type={color_type}（只支持 RGB/RGBA）")


def decode_png(data: bytes) -> Tuple[int, int, int, List[bytes]]:
    """解出 ``(width, height, channels, rows)``；rows 是去滤波后的原始字节行。"""
    if not data.startswith(_SIGNATURE):
        raise ValueError("不是 PNG 文件")
    offset = len(_SIGNATURE)
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = \
                struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break
    if None in (width, height, bit_depth, color_type, interlace):
        raise ValueError("PNG 缺少 IHDR")
    if bit_depth != 8 or interlace != 0:
        raise ValueError(f"只支持 8-bit 非隔行 PNG（bit_depth={bit_depth}, "
                         f"interlace={interlace}）")
    channels = _channels_of(color_type)
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    expected = (stride + 1) * height
    if len(raw) < expected:
        raise ValueError(f"PNG 数据不足：{len(raw)} < {expected}")
    rows: List[bytes] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor:cursor + stride])
        cursor += stride
        for index in range(stride):
            left = line[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            value = line[index]
            if filter_type == 0:
                pass
            elif filter_type == 1:
                value = (value + left) & 0xFF
            elif filter_type == 2:
                value = (value + up) & 0xFF
            elif filter_type == 3:
                value = (value + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                value = (value + _paeth(left, up, up_left)) & 0xFF
            else:
                raise ValueError(f"非法 PNG filter 类型 {filter_type}")
            line[index] = value
        rows.append(bytes(line))
        previous = line
    return width, height, channels, rows


def encode_png(width: int, height: int, channels: int,
               rows: Sequence[bytes]) -> bytes:
    """8-bit 无滤波 PNG 编码（IHDR + 单个 IDAT + IEND）。"""
    if channels not in (3, 4):
        raise ValueError(f"只支持 RGB/RGBA，channels={channels}")
    color_type = 2 if channels == 3 else 6
    if len(rows) != height or any(len(row) != width * channels for row in rows):
        raise ValueError("行数与每行字节数必须与 width/height/channels 一致")
    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (_SIGNATURE + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def grid_segments() -> List[Segment2D]:
    """九宫格线段（NDC [0,1]，左下原点）——与视口叠加同一份真源。"""
    return list(thirds_grid())


def _draw_segment(pixels: bytearray, width: int, height: int, channels: int,
                  segment: Segment2D, color: Tuple[int, int, int],
                  thickness: int, alpha: int) -> None:
    (x0, y0), (x1, y1) = segment
    px0 = round(min(x0, x1) * (width - 1))
    px1 = round(max(x0, x1) * (width - 1))
    py0 = height - 1 - round(max(y0, y1) * (height - 1))
    py1 = height - 1 - round(min(y0, y1) * (height - 1))
    low = max(0, (int(thickness) - 1) // 2)
    high = max(0, int(thickness) // 2)
    for py in range(max(0, py0 - low), min(height, py1 + high + 1)):
        for px in range(max(0, px0 - low), min(width, px1 + high + 1)):
            base = (py * width + px) * channels
            for channel in range(3):
                source = pixels[base + channel]
                pixels[base + channel] = (
                    color[channel] * alpha + source * (255 - alpha)) // 255


def grid_frame(data: bytes, *, color: Tuple[int, int, int] = (0, 255, 0),
               thickness: int = 2, alpha: int = 180) -> bytes:
    """把九宫格画进一张 PNG，返回新 PNG 字节；原图不改。"""
    width, height, channels, rows = decode_png(data)
    pixels = bytearray().join(rows)
    for segment in grid_segments():
        _draw_segment(pixels, width, height, channels, segment, color,
                      thickness, alpha)
    out_rows = [bytes(pixels[y * width * channels:(y + 1) * width * channels])
                for y in range(height)]
    return encode_png(width, height, channels, out_rows)


def grid_frame_file(path, *, color: Tuple[int, int, int] = (0, 255, 0),
                    thickness: int = 3, alpha: int = 180,
                    suffix: str = "_grid") -> str:
    """给一个 PNG 文件写出带九宫格的副本，返回新路径；原文件不动。"""
    source = pathlib.Path(path)
    data = source.read_bytes()
    out = source.with_name(f"{source.stem}{suffix}.png")
    out.write_bytes(grid_frame(data, color=color, thickness=thickness,
                               alpha=alpha))
    return str(out)


__all__ = ["decode_png", "encode_png", "grid_segments", "grid_frame",
           "grid_frame_file"]
