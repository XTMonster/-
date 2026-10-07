"""把 13 张首帧拼成一张总览图（只读产物，不改任何东西）。

标签用 ASCII 编号（PIL 默认字体没有中文字形，硬写中文会变成方块）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
COLS, CELL = 4, 480


def main() -> int:
    files = sorted(SRC.glob("shot_*.png"))
    rows = (len(files) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * CELL, rows * (CELL * 9 // 16 + 22)), "black")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(files):
        image = Image.open(path).convert("RGB")
        image.thumbnail((CELL, CELL * 9 // 16))
        x = (index % COLS) * CELL
        y = (index // COLS) * (CELL * 9 // 16 + 22)
        sheet.paste(image, (x, y))
        draw.text((x + 6, y + CELL * 9 // 16 + 4), path.stem, fill="white")
    sheet.save(OUT)
    print(f"wrote {OUT} ({sheet.width}x{sheet.height}) from {len(files)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
