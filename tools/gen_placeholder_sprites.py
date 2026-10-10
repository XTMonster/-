"""生成小助手「米迦尔」Q 版像素精灵表（v1.7 卡 C3，TDD §6.1 / PRD §3.7）。

纯 stdlib：PNG 用 ``zlib`` + ``struct`` 手写（IHDR / IDAT / IEND），不引 PIL。
每个 clip 一张横向精灵表：宽 = 48 × frames、高 = 48、8 bit RGB。

形象取自 ``docs/ui-assistant/assets/mikael_reference.jpg`` 的特征：青色主毛、
紫色耳尖与尾纹、额头黄色闪电纹、白色口鼻与肚皮、橙色瞳。角色像素**只用**
PRD §3.7 的五色；背景是一张深色像素卡片（RGB 无透明通道，卡片边框让它在
任何底色上都是一个完整的"小窗"）。

每个 clip 是一个真正的动作循环（不是同一张图上下浮动）：

=========== ===== ==================================================
clip        帧数  动作
=========== ===== ==================================================
sleep       6     趴着睡，呼吸起伏，Z 字逐个飘起
read        6     坐着捧书，视线向下，书页翻动
think       8     托腮，思考泡从小到大冒出，泡里问号闪
think_wait  8     抬头望，头顶三个点轮流亮起，尾巴慢摇
build       6     把方块从地上举过头顶再放到右侧方块堆
inspect     6     举放大镜左右扫，眼睛跟着看
fix         6     挥扳手敲，命中帧迸火星
ask         4     举手，头顶问号上下弹
pack        6     把物件推进纸箱，盖上箱盖
celebrate   8     蹲→起跳→落地，双手举高，星星绽开
dizzy       6     侧倒，蚊香眼，头顶星星绕圈
sit         4     坐着，尾巴左右摇，偶尔眨眼
=========== ===== ==================================================

输出是确定性的（无时间戳、无随机），重复运行逐字节相同。

用法::

    python tools/gen_placeholder_sprites.py            # 写到 web/assets/assistant/
    python tools/gen_placeholder_sprites.py --out DIR
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import zlib
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "web" / "assets" / "assistant"

BASE = 48
FPS = 12

#: PRD §3.7 设定图取样五色（与 web/pixel.css 的 --bd-* 变量同值）。
PALETTE: Dict[str, str] = {
    "cyan": "#2EC4E6",
    "purple": "#3B1D5A",
    "yellow": "#F6C90E",
    "white": "#F2F2F0",
    "orange": "#E8791A",
}
#: 卡片底色与边框：不属于角色，所以不进 PALETTE（校验"角色只用五色"时排除）。
CARD_BG = "#14101f"
CARD_EDGE = "#2a2140"

Color = Tuple[int, int, int]


def _rgb(hex_color: str) -> Color:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


C = _rgb(PALETTE["cyan"])
P = _rgb(PALETTE["purple"])
Y = _rgb(PALETTE["yellow"])
W = _rgb(PALETTE["white"])
O = _rgb(PALETTE["orange"])
BG = _rgb(CARD_BG)
EDGE = _rgb(CARD_EDGE)


# ---------------------------------------------------------------- 栅格工具

class Layer:
    """48×48 的角色图层；None = 透明（最后合成到卡片上）。"""

    def __init__(self) -> None:
        self.px: List[List[Optional[Color]]] = [[None] * BASE for _ in range(BASE)]

    def put(self, x: float, y: float, c: Color) -> None:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < BASE and 0 <= yi < BASE:
            self.px[yi][xi] = c

    def rect(self, x0: float, y0: float, x1: float, y1: float, c: Color) -> None:
        for y in range(int(round(y0)), int(round(y1)) + 1):
            for x in range(int(round(x0)), int(round(x1)) + 1):
                self.put(x, y, c)

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, c: Color) -> None:
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                    self.put(x, y, c)

    def line(self, x0: float, y0: float, x1: float, y1: float, c: Color, width: int = 1) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
        for i in range(steps + 1):
            t = i / steps
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            if width <= 1:
                self.put(x, y, c)
            else:
                self.ellipse(x, y, width / 2, width / 2, c)

    def glyph(self, rows: List[str], x0: int, y0: int, c: Color) -> None:
        for dy, row in enumerate(rows):
            for dx, ch in enumerate(row):
                if ch == "#":
                    self.put(x0 + dx, y0 + dy, c)

    def outline(self, c: Color) -> None:
        """给所有非空像素描一圈 4 邻域外轮廓（像素画的"墨线"）。"""
        add = []
        for y in range(BASE):
            for x in range(BASE):
                if self.px[y][x] is not None:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < BASE and 0 <= ny < BASE and self.px[ny][nx] not in (None, c):
                        add.append((x, y))
                        break
        for x, y in add:
            self.px[y][x] = c


GLYPH_Q = [".##.", "#..#", "...#", "..#.", "....", "..#."]
GLYPH_Z = ["###", "..#", ".#.", "#..", "###"]
GLYPH_STAR = ["..#..", ".###.", "#####", ".###.", "..#.."]
GLYPH_SPARK = ["#.#", ".#.", "#.#"]


# ---------------------------------------------------------------- 角色

def draw_tail(L: Layer, base_x: float, base_y: float, angle: float) -> None:
    """尾巴：从身体右后方伸出，angle 为相对竖直的摆角（弧度）。末段紫纹。"""
    tip_x = base_x + 7 * math.sin(angle) + 3
    tip_y = base_y - 9 * math.cos(angle)
    mid_x, mid_y = (base_x + tip_x) / 2 + 2, (base_y + tip_y) / 2 + 1
    L.line(base_x, base_y, mid_x, mid_y, C, width=3)
    L.line(mid_x, mid_y, tip_x, tip_y, C, width=3)
    L.ellipse(tip_x, tip_y, 1.6, 1.6, P)


def draw_head(L: Layer, cx: float, cy: float, eyes: str, look: Tuple[int, int] = (0, 0),
              mouth: str = "dot") -> None:
    # 耳朵（青色三角，紫色耳尖）
    for side in (-1, 1):
        ex = cx + side * 7
        for i in range(6):
            half = max(0, 3 - i // 2)
            L.rect(ex - half, cy - 7 - i, ex + half, cy - 7 - i, C if i < 3 else P)
    L.ellipse(cx, cy, 11, 9, C)                        # 头
    L.ellipse(cx, cy + 4, 5.5, 3.2, W)                 # 口鼻
    L.glyph(["#.", ".#", "#.", ".#"], int(cx) - 1, int(cy) - 8, Y)  # 额头闪电纹
    lx, ly = look
    for side in (-1, 1):
        ex, ey = int(cx + side * 5), int(cy - 1)
        if eyes == "open":
            L.rect(ex - 1 + lx, ey - 1 + ly, ex + 1 + lx, ey + 1 + ly, O)
            L.put(ex - 1 + lx, ey - 1 + ly, W)
        elif eyes == "closed":
            L.rect(ex - 1, ey + 1, ex + 1, ey + 1, P)
        elif eyes == "happy":
            L.put(ex - 1, ey + 1, P)
            L.put(ex, ey, P)
            L.put(ex + 1, ey + 1, P)
        elif eyes == "swirl":
            L.rect(ex - 1, ey - 1, ex + 1, ey + 1, P)
            L.put(ex, ey, O)
    L.put(cx, cy + 3, P)                               # 鼻头
    if mouth == "open":
        L.rect(cx - 1, cy + 5, cx + 1, cy + 6, P)
    elif mouth == "smile":
        L.put(cx - 2, cy + 5, P)
        L.rect(cx - 1, cy + 6, cx + 1, cy + 6, P)
        L.put(cx + 2, cy + 5, P)


def draw_sitting(L: Layer, dy: float = 0.0, eyes: str = "open", look=(0, 0), tail: float = 0.4,
                 paw_l: Tuple[float, float] = (16, 37), paw_r: Tuple[float, float] = (32, 37),
                 mouth: str = "dot", squash: float = 0.0) -> None:
    """坐姿。坐标都是绝对像素；dy 整体上下移（跳/呼吸），squash>0 压扁身体（蓄力）。"""
    body_y = 35 + dy + squash
    draw_tail(L, 31, body_y + 3, tail)
    L.ellipse(19, 42 + dy, 3, 2, C)                    # 后脚
    L.ellipse(29, 42 + dy, 3, 2, C)
    L.ellipse(24, body_y, 9 + squash, 8 - squash, C)   # 身体
    L.ellipse(24, body_y + 2, 5, 5 - squash, W)        # 肚皮
    for (px, py), sx in ((paw_l, 19), (paw_r, 29)):    # 前臂＋爪
        L.line(sx, body_y - 3, px, py + dy, C, width=3)
        L.ellipse(px, py + dy, 2, 2, W)
    draw_head(L, 24, 22 + dy + squash, eyes, look, mouth)


def draw_lying(L: Layer, breathe: float = 0.0, eyes: str = "closed", tilt: int = 0) -> None:
    """趴姿（睡觉/晕倒）：头在左、身体横在右；tilt 让头歪向地面。"""
    L.ellipse(28, 39 - breathe, 13, 5 + breathe, C)    # 身体
    L.ellipse(28, 41, 8, 2.5, W)                       # 肚皮（侧露）
    L.line(40, 39, 45, 35 - breathe, C, width=3)       # 尾巴平放
    L.ellipse(45, 34 - breathe, 1.6, 1.6, P)
    L.ellipse(14, 43, 3, 1.6, W)                       # 前爪
    draw_head(L, 14, 34 + tilt, eyes)


# ---------------------------------------------------------------- 道具

def bubble(L: Layer, cx: float, cy: float, rx: float, ry: float) -> None:
    L.ellipse(cx, cy, rx, ry, W)


def draw_block(L: Layer, x: float, y: float) -> None:
    L.rect(x - 3, y - 3, x + 3, y + 3, Y)
    L.rect(x - 1, y - 1, x + 1, y + 1, O)


# ---------------------------------------------------------------- 各 clip 的逐帧动作

FrameFn = Callable[[Layer, int, int], None]


def f_sleep(L: Layer, f: int, n: int) -> None:
    breathe = 1.0 if f in (1, 2, 3) else 0.0
    draw_lying(L, breathe=breathe, eyes="closed")
    for k in range(3):                                  # Z 字逐个飘起
        phase = (f - k * 2) % n
        if phase < 4:
            L.glyph(GLYPH_Z, 28 + k * 5 + phase, 22 - k * 5 - phase * 2, Y if k % 2 else W)


def f_read(L: Layer, f: int, n: int) -> None:
    draw_sitting(L, eyes="open", look=(0, 1), tail=0.3 + 0.1 * math.sin(f / n * math.tau),
                 paw_l=(18, 34), paw_r=(30, 34))
    L.rect(16, 31, 32, 38, W)                           # 摊开的书
    L.rect(24, 31, 24, 38, P)                           # 书脊
    for row in (33, 35):
        L.rect(18, row, 22, row, P)
        L.rect(26, row, 30, row, P)
    flip = f % 3                                        # 翻页：一张纸从右扫到左
    if flip == 1:
        L.rect(25, 29, 29, 31, W)
    elif flip == 2:
        L.rect(19, 29, 23, 31, W)


def f_think(L: Layer, f: int, n: int) -> None:
    draw_sitting(L, eyes="open", look=(1, -1), tail=0.5, paw_l=(16, 37), paw_r=(27, 28))
    grow = min(f, 5)                                    # 思考泡逐帧长大
    if grow >= 1:
        bubble(L, 33, 15, 1.2, 1.2)
    if grow >= 2:
        bubble(L, 36, 11, 1.8, 1.8)
    if grow >= 3:
        bubble(L, 40, 6, 2 + grow * 0.6, 2 + grow * 0.4)
    if f >= 5 and f % 2 == 1:
        L.glyph(GLYPH_Q, 38, 3, P)


def f_think_wait(L: Layer, f: int, n: int) -> None:
    draw_sitting(L, eyes="open", look=(0, -1), tail=0.6 * math.sin(f / n * math.tau))
    lit = f % 4                                         # 三个点轮流亮，第 4 拍全暗
    for k in range(3):
        L.ellipse(16 + k * 8, 5, 1.6, 1.6, Y if k == lit else W)


def f_build(L: Layer, f: int, n: int) -> None:
    # 方块轨迹：地面(左) → 胸前 → 头顶 → 头顶 → 右侧堆 → 回到放好
    path = [(12, 40), (18, 32), (24, 8), (30, 8), (40, 34), (40, 34)]
    bx, by = path[f]
    paws = {0: ((14, 38), (32, 37)), 1: ((18, 33), (28, 33)), 2: ((20, 12), (28, 12)),
            3: ((26, 12), (34, 12)), 4: ((34, 35), (38, 33)), 5: ((16, 37), (32, 37))}[f]
    squash = 1.0 if f in (0, 4) else 0.0
    draw_sitting(L, eyes="open" if f != 2 else "happy", look=(1 if f >= 3 else -1, 0),
                 paw_l=paws[0], paw_r=paws[1], squash=squash)
    draw_block(L, 40, 41)                               # 已经堆好的方块
    draw_block(L, bx, by)


def f_inspect(L: Layer, f: int, n: int) -> None:
    sweep = [-6, -3, 0, 3, 6, 3][f]
    draw_sitting(L, eyes="open", look=(1 if sweep > 0 else -1 if sweep < 0 else 0, 0),
                 paw_r=(30 + sweep, 26))
    lx, ly = 33 + sweep, 21                             # 放大镜：镜框黄、镜片白、手柄紫
    L.ellipse(lx, ly, 4.5, 4.5, Y)
    L.ellipse(lx, ly, 3, 3, W)
    L.line(lx - 3, ly + 3, 30 + sweep, 26, P, width=2)


def f_fix(L: Layer, f: int, n: int) -> None:
    angles = [0.9, 0.5, 0.0, -0.7, 0.0, 0.5]            # 扳手从右上方挥下，命中右下方块
    a = angles[f]
    hx, hy = 34, 30
    tx, ty = hx + 10 * math.cos(a), hy - 10 * math.sin(a)
    draw_sitting(L, eyes="open" if f != 3 else "closed", look=(1, 1), paw_r=(hx, hy))
    draw_block(L, 40, 41)                               # 被修的方块
    L.line(hx, hy, tx, ty, P, width=2)                  # 扳手柄
    L.ellipse(tx, ty, 2.2, 2.2, W)                      # 扳手头
    if f == 3:                                          # 命中帧迸火星
        L.glyph(GLYPH_SPARK, 41, 33, Y)
        L.glyph(GLYPH_SPARK, 44, 36, O)


def f_ask(L: Layer, f: int, n: int) -> None:
    up = [0, -1, -2, -1][f]
    draw_sitting(L, eyes="open", look=(0, -1), paw_r=(34, 14 + up),
                 mouth="open" if f in (1, 2) else "dot")
    L.glyph(GLYPH_Q, 38, 5 + up * 2, Y)


def f_pack(L: Layer, f: int, n: int) -> None:
    item_x = [18, 24, 30, 36, 38, 38][f]
    draw_sitting(L, eyes="open", look=(1, 1), paw_l=(item_x - 4, 38), paw_r=(item_x - 2, 34))
    L.rect(34, 36, 45, 44, O)                           # 纸箱
    L.rect(34, 36, 45, 36, P)
    if f < 4:
        draw_block(L, item_x, 38)
        L.line(34, 36, 31, 30, O, width=2)              # 敞开的盖板
        L.line(45, 36, 47, 30, O, width=2)
    else:                                               # 箱盖合上
        lid = 33 + (5 - f)
        L.rect(34, lid, 45, lid + 2, O)
        L.rect(39, lid, 40, lid + 2, Y)                 # 胶带


def f_celebrate(L: Layer, f: int, n: int) -> None:
    hop = [0, 1, -3, -7, -9, -7, -3, 0][f]              # 蹲(+1) → 起跳 → 落地
    squash = 1.5 if f in (1, 7) else 0.0
    arms_up = f in (2, 3, 4, 5, 6)
    paw_l, paw_r = ((8, 12), (40, 12)) if arms_up else ((16, 37), (32, 37))
    draw_sitting(L, dy=min(hop, 0), eyes="happy", tail=0.8, paw_l=paw_l, paw_r=paw_r,
                 mouth="smile", squash=squash)
    for k, (sx, sy) in enumerate(((5, 10), (40, 6), (6, 30), (42, 26))):
        if (f + k) % 3 != 2:                            # 星星错拍闪
            L.glyph(GLYPH_STAR if (f + k) % 2 else GLYPH_SPARK, sx, sy, Y if k % 2 else O)


def f_dizzy(L: Layer, f: int, n: int) -> None:
    draw_lying(L, eyes="swirl", tilt=1)
    for k in range(3):                                  # 头顶星星绕圈
        a = (f / n + k / 3) * math.tau
        L.glyph(GLYPH_SPARK, int(13 + 8 * math.cos(a)) - 1, int(22 + 3 * math.sin(a)) - 1, Y)


def f_sit(L: Layer, f: int, n: int) -> None:
    tail = [0.9, 0.3, -0.3, 0.3][f]
    draw_sitting(L, eyes="closed" if f == 2 else "open", tail=tail)


CLIPS: Dict[str, Tuple[int, FrameFn]] = {
    "sleep":      (6, f_sleep),
    "read":       (6, f_read),
    "think":      (8, f_think),
    "think_wait": (8, f_think_wait),
    "build":      (6, f_build),
    "inspect":    (6, f_inspect),
    "fix":        (6, f_fix),
    "ask":        (4, f_ask),
    "pack":       (6, f_pack),
    "celebrate":  (8, f_celebrate),
    "dizzy":      (6, f_dizzy),
    "sit":        (4, f_sit),
}


# ---------------------------------------------------------------- 合成与写盘

def render_frame(fn: FrameFn, f: int, n: int) -> List[List[Color]]:
    layer = Layer()
    fn(layer, f, n)
    layer.outline(P)
    frame: List[List[Color]] = []
    for y in range(BASE):
        row: List[Color] = []
        for x in range(BASE):
            edge = x in (0, BASE - 1) or y in (0, BASE - 1)
            px = layer.px[y][x]
            row.append(EDGE if edge else (px if px is not None else BG))
        frame.append(row)
    return frame


def _png(width: int, height: int, rows: List[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8 bit, RGB
    raw = b"".join(b"\x00" + row for row in rows)                  # filter type 0
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def render_clip(frames: int, fn: FrameFn) -> bytes:
    strips = [render_frame(fn, f, frames) for f in range(frames)]
    rows = [bytes(v for fr in strips for px in fr[y] for v in px) for y in range(BASE)]
    return _png(BASE * frames, BASE, rows)


def build(out_dir: Path) -> Dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    clips: Dict[str, Dict[str, object]] = {}
    for name, (frames, fn) in CLIPS.items():
        filename = f"{name}.png"
        (out_dir / filename).write_bytes(render_clip(frames, fn))
        clips[name] = {"file": filename, "frames": frames, "loop": True}
    table = {"base_size": BASE, "fps": FPS, "palette": PALETTE, "clips": clips}
    (out_dir / "frames.json").write_text(
        json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return table


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    table = build(args.out)
    print(f"[OK] {len(table['clips'])} clips -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
