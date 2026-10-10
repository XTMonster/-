"""小助手精灵资产校验器（v1.7 卡 C3，TDD §6.1）。

纯 stdlib，不 import bpy、不引 PIL。检查 ``web/assets/assistant/frames.json``：

* 每个 clip 的 PNG 存在，IHDR 尺寸 = (base_size × frames, base_size)；
* 帧数 ≥ 2；
* clip 名合法（``[a-z_]+``）；
* ``CLIP_BY_STATE`` 的每个值都有对应 clip（**import contracts，不抄映射**）；
* 帧表里不存在映射值域之外的多余 clip。

挂接方式：pytest 包装 ``tests/test_assistant_assets.py``（importlib 载入，
先例 ``tests/test_assertion_hygiene.py``），不占 Blender 探针名额。
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DIR = ROOT / "web" / "assets" / "assistant"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CLIP_NAME = re.compile(r"^[a-z_]+$")


def png_size(path: Path) -> Tuple[int, int]:
    """读 IHDR 固定字节得 (宽, 高)；不是合法 PNG 头抛 ValueError。"""
    with path.open("rb") as fh:
        head = fh.read(24)
    if len(head) < 24 or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        raise ValueError(f"{path.name}: 不是合法 PNG（缺签名或 IHDR）")
    return struct.unpack(">II", head[16:24])


def check(assets_dir: Optional[Path] = None) -> List[str]:
    """返回问题清单；空表 = 通过。

    映射值域从 ``contracts/assistant.py`` import（不抄映射）。延迟到这里 import：
    让 ``png_size`` 等结构工具在 A1 落地前也可被测；A1 缺席时本函数照常抛
    ImportError（不吞、不回落到本地副本）。
    """
    from block_director.contracts.assistant import CLIP_BY_STATE

    assets_dir = Path(assets_dir or DEFAULT_DIR)
    table_path = assets_dir / "frames.json"
    if not table_path.is_file():
        return [f"缺帧表 {table_path}"]
    try:
        table = json.loads(table_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"frames.json 不是合法 JSON：{exc}"]

    problems: List[str] = []
    base = table.get("base_size")
    clips = table.get("clips")
    if not isinstance(base, int) or base <= 0:
        problems.append(f"base_size 非正整数：{base!r}")
        return problems
    if not isinstance(clips, dict) or not clips:
        return problems + ["clips 缺失或为空"]

    for name, spec in sorted(clips.items()):
        if not CLIP_NAME.match(name):
            problems.append(f"clip 名非法：{name!r}")
        frames = spec.get("frames") if isinstance(spec, dict) else None
        if not isinstance(frames, int) or frames < 2:
            problems.append(f"{name}: 帧数须 ≥2（实为 {frames!r}）")
            continue
        png = assets_dir / str(spec.get("file", ""))
        if not png.is_file():
            problems.append(f"{name}: 缺精灵表文件 {png.name}")
            continue
        try:
            width, height = png_size(png)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if (width, height) != (base * frames, base):
            problems.append(f"{name}: 尺寸 {width}×{height} ≠ 期望 {base * frames}×{base}")

    wanted = set(CLIP_BY_STATE.values())
    for missing in sorted(wanted - set(clips)):
        problems.append(f"映射用到的 clip 缺资产：{missing}")
    for extra in sorted(set(clips) - wanted):
        problems.append(f"帧表里有映射值域之外的 clip：{extra}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="校验小助手精灵资产")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)
    problems = check(args.dir)
    for p in problems:
        print(f"[FAIL] {p}")
    if not problems:
        print("[OK] assistant assets")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
