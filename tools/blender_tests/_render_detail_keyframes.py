"""细排场景逐镜代表帧渲染（视觉 QA 用，不作为验收判据）。

与 ``detail_pipeline`` 同一路径：冻结 manifest -> 重建体块场景 -> 应用细排
节拍 -> 逐镜取中帧渲染 PNG。用法：

  blender --background --factory-startup --python tools/blender_tests/_render_detail_keyframes.py -- \
      --coarse <coarse 目录> --detail <detail 目录> --out <帧输出目录>
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
    parser.add_argument("--coarse", required=True)
    parser.add_argument("--detail", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(args)


def main() -> None:
    args = _parse()
    coarse_dir = Path(args.coarse)
    detail_dir = Path(args.detail)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(
        (coarse_dir / "blockout_manifest.json").read_text(encoding="utf-8"))
    detail_shots = json.loads(
        (detail_dir / "detail_shots.json").read_text(encoding="utf-8"))
    if isinstance(detail_shots, dict):
        detail_shots = detail_shots.get("shots") or []

    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    from block_director.layer3_engine.detail_scene import apply_detail_beats

    build_blockout_scene(manifest, clear_scene=True)
    apply_detail_beats(detail_shots, manifest)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.fps = 24
    scene.render.film_transparent = False

    written: list[str] = []
    for camera in manifest.get("cameras") or []:
        shot_id = str(camera.get("shot_id") or "")
        camera_obj = bpy.data.objects.get(
            f"BD_Blockout_{camera.get('camera_id')}")
        if camera_obj is not None:
            scene.camera = camera_obj
        start = int(camera.get("start_frame") or 1)
        end = int(camera.get("end_frame") or start)
        mid = (start + end) // 2
        scene.frame_set(mid)
        bpy.context.view_layer.update()
        out_path = out_dir / f"shot_{shot_id}_mid_{mid:04d}.png"
        scene.render.filepath = str(out_path)
        bpy.ops.render.render(write_still=True)
        written.append(str(out_path))
        print(f"OK {shot_id} frame={mid} -> {out_path}")

    print("DETAIL_KEYFRAME_DONE " + json.dumps(written, ensure_ascii=False))


if __name__ == "__main__":
    main()
