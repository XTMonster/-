"""在 Blender 内 headless 运行一次预演（Phase 0：空转链路端到端）。

用法：
  blender --background --factory-startup --python tools/run_headless.py -- --offline
  blender --background --python tools/run_headless.py -- --script fixtures/x.fountain --out E:\\tmp

输出：一行 ``BLOCKDIRECTOR_RESULT {json}`` 与退出码（0 = DONE，1 = 其他）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args(argv):
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="run_headless")
    parser.add_argument("--script", default="", help="剧本文件路径")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", dest="offline", action="store_true",
                      default=True, help="离线自检（默认）")
    mode.add_argument("--sidecar", dest="offline", action="store_false",
                      help="使用 sidecar 而不是离线自检")
    parser.add_argument("--out", default="", help="运行输出目录")
    parser.add_argument("--wall", type=float, default=180.0, help="墙上时间上限（秒）")
    parser.add_argument("--build", action="store_true",
                        help="把分镜计划落成真实场景（角色/相机/关键帧/剪切标记）")
    return parser.parse_args(rest)


def main() -> int:
    args = parse_args(sys.argv)

    import block_director
    block_director.register()          # 走真实注册路径（含主线程登记与配置加载）

    from block_director.layer5_orchestrator.headless_runner import run_headless

    builder = None
    if args.build:
        from block_director.layer3_engine.shot_builder import BpySceneBuilder
        builder = BpySceneBuilder(clear_scene=True)

    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.scene_state import collect_scene_state
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.driver import default_registry
    from block_director.observation.state import format_scene_state

    registry = default_registry()
    register_all_scene_tools(registry)

    script = ""
    if args.script:
        path = Path(args.script)
        if path.exists():
            script = path.read_text(encoding="utf-8", errors="replace")
        else:
            print(f"BLOCKDIRECTOR_WARN 剧本不存在: {path}")

    summary = run_headless(
        script,
        offline=args.offline,
        project_dir=Path(args.out) if args.out else None,
        max_wall_s=args.wall,
        builder=builder,
        registry=registry,
        auditor=BpyShotAuditor() if builder is not None else None,
        scene_state_provider=lambda: format_scene_state(
            collect_scene_state(detailed=False)),
    )
    print("BLOCKDIRECTOR_RESULT " + json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
