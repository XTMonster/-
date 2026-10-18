"""从逐镜 mp4 抽出代表帧（视觉 QA 用，不作为验收判据）。

用 Blender 自带 Video Sequencer 解码 mp4 并渲染成 PNG；只做画面检查，
不参与 gate。用法：

  blender --background --factory-startup --python tools/blender_tests/_extract_keyframes_from_mp4.py -- \
      --dir <detail 输出目录> --out <帧输出目录>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402


def _parse() -> argparse.Namespace:
    argv = list(sys.argv)
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(args)


def main() -> None:
    args = _parse()
    detail_dir = Path(args.dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    detail_shots = json.loads(
        (detail_dir / "detail_shots.json").read_text(encoding="utf-8"))
    if isinstance(detail_shots, dict):
        detail_shots = detail_shots.get("shots") or []
    schedule = {d["shot_id"]: (int(d["start_frame"]), int(d["end_frame"]))
                for d in detail_shots}

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new("frame_extract_world")
    scene.world.use_nodes = False
    bpy.data.worlds["frame_extract_world"].color = (0.0, 0.0, 0.0)
    scene.sequence_editor_create()

    written: list[str] = []
    for index, (shot_id, (start, end)) in enumerate(sorted(schedule.items())):
        mp4 = detail_dir / "shot_videos" / f"blockout_{shot_id}.mp4"
        if not mp4.exists():
            print(f"SKIP {shot_id}: 缺 {mp4}")
            continue
        # 清掉上一镜的 strip，重挂本镜。
        scene.sequence_editor_clear()
        scene.sequence_editor_create()
        bpy.ops.sequencer.movie_strip_add(
            filepath=str(mp4), frame_start=1, channel=1, sound=False)
        mid = (start + end) // 2
        scene.frame_set(mid)
        out_path = out_dir / f"shot_{shot_id}_frame_{mid:03d}.png"
        scene.render.filepath = str(out_path)
        bpy.ops.render.render(write_still=True)
        written.append(str(out_path))
        print(f"OK {shot_id} frame={mid} -> {out_path}")

    print("KEYFRAME_EXTRACT_DONE " + json.dumps(written, ensure_ascii=False))


if __name__ == "__main__":
    main()
