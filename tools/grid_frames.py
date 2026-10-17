"""九宫格诊断帧批量生成：给多模态评委看图用的带网格副本。

用法：
    python tools/grid_frames.py <输入目录> <输出目录> [--color r,g,b] [--thickness 2]

只依赖 stdlib + ``block_director.overlay.grid_frame``；不修改原图，
输出目录下同名生成 ``*_grid.png``。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.overlay.grid_frame import grid_frame  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--color", default="0,255,0")
    parser.add_argument("--thickness", type=int, default=3)
    parser.add_argument("--alpha", type=int, default=180)
    args = parser.parse_args()
    color = tuple(int(part) for part in args.color.split(","))
    if len(color) != 3 or any(not 0 <= part <= 255 for part in color):
        parser.error("--color 必须是 r,g,b（0-255）")
    source = pathlib.Path(args.input_dir)
    target = pathlib.Path(args.output_dir)
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in sorted(source.glob("*.png")):
        data = path.read_bytes()
        annotated = grid_frame(data, color=color, thickness=args.thickness,
                               alpha=args.alpha)
        out = target / f"{path.stem}_grid.png"
        out.write_bytes(annotated)
        written += 1
        print(out)
    print(f"wrote {written} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
