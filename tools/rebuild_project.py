"""从项目文件重建场景（执行文档 v1.2 §14.2）。

这是"改一镜、重出一镜"的基础：加载 SDL → 还原计划与场景设定 → 重建场景；
加 ``--export`` 就顺带重出交付包，全程不再调用 LLM。

用法：
  blender --background --factory-startup --python tools/rebuild_project.py -- \
      --project <项目目录> [--export]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args(argv):
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="rebuild_project")
    parser.add_argument("--project", required=True, help="项目目录")
    parser.add_argument("--export", action="store_true", help="重建后导出交付包")
    return parser.parse_args(rest)


def main() -> int:
    args = parse_args(sys.argv)

    import block_director
    block_director.register()

    from block_director.layer2_sdl import sdl_to_plan, sdl_to_spec
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer9_persistence import load_project
    from block_director.settings import get_config

    # 绝对化：Blender 内 ``bpy.path.abspath("//")`` 在未保存 .blend 时为空串，
    # 相对路径的渲染产物会落到进程工作目录之外（实测跑到 C:\runs\...）。
    project_dir = Path(os.path.abspath(args.project))
    try:
        loaded = load_project(project_dir)
    except Exception as exc:  # noqa: BLE001 - 加载失败要让人看见原因
        print("BLOCKDIRECTOR_REBUILD " + json.dumps(
            {"ok": False, "reason": f"{type(exc).__name__}: {exc}"},
            ensure_ascii=False))
        return 1

    if not loaded.ok:
        print("BLOCKDIRECTOR_REBUILD " + json.dumps(
            {"ok": False, "reason": "项目校验未通过",
             "errors": [item.to_dict() for item in loaded.findings
                        if item.is_error]}, ensure_ascii=False))
        return 1

    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()

    payload = {"ok": True, "project": str(loaded.path),
               "notes": loaded.notes,
               "shots": summary["shots"],
               "total_frames": summary["total_frames"],
               "characters": summary["characters"],
               "warnings": summary["warnings"]}

    if args.export:
        from block_director.layer8_delivery import export_project

        report = export_project(plan, build_summary=summary,
                                out_dir=project_dir, config=get_config().delivery,
                                project=loaded.sdl.name)
        payload["export"] = report.to_dict()

    print("BLOCKDIRECTOR_REBUILD " + json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
