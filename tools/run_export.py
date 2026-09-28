"""端到端：剧本 → 分镜计划 → 场景 → 交付包（Phase 6）。

用法：
  blender --background --factory-startup --python tools/run_export.py -- \
      --offline --out <目录> [--preset hd16x9] [--camera-traj] [--script <剧本>]

产物（<目录>/export/）：分镜 mp4、首帧 PNG、shots.json、prompts.md、README.md。
输出：一行 ``BLOCKDIRECTOR_EXPORT {json}``。
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
    parser = argparse.ArgumentParser(prog="run_export")
    parser.add_argument("--script", default="", help="剧本文件路径")
    parser.add_argument("--out", default="", help="输出目录")
    parser.add_argument("--preset", default="hd16x9")
    parser.add_argument("--appearance", default="clay")
    parser.add_argument("--offline", dest="offline", action="store_true", default=True)
    parser.add_argument("--sidecar", dest="offline", action="store_false")
    parser.add_argument("--camera-traj", dest="camera_traj", action="store_true")
    parser.add_argument("--wall", type=float, default=300.0)
    return parser.parse_args(rest)


def main() -> int:
    args = parse_args(sys.argv)

    import block_director
    block_director.register()

    from block_director.contracts.config import AppConfig
    from block_director.contracts.enums import Appearance, DeliveryPreset
    from block_director.layer3_engine.shot_builder import BpySceneBuilder
    from block_director.layer5_orchestrator.headless_runner import run_headless
    from block_director.layer8_delivery import export_project
    from block_director.settings import get_config
    from block_director.utils.paths import default_project_root

    script = ""
    if args.script:
        path = Path(args.script)
        if path.exists():
            script = path.read_text(encoding="utf-8", errors="replace")
        else:
            print(f"BLOCKDIRECTOR_WARN 剧本不存在: {path}")

    out_dir = Path(args.out) if args.out else default_project_root() / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    from block_director.layer3_engine.scene_state import collect_scene_state
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.driver import default_registry
    from block_director.layer5_orchestrator.human_gate import AutoGate
    from block_director.observation.state import format_scene_state

    registry = default_registry()
    register_all_scene_tools(registry)

    summary = run_headless(script, offline=args.offline, project_dir=out_dir,
                           max_wall_s=args.wall,
                           builder=BpySceneBuilder(clear_scene=True),
                           registry=registry,
                           auditor=BpyShotAuditor(),
                           human_gate=AutoGate(),
                           scene_state_provider=lambda: format_scene_state(
                               collect_scene_state(detailed=False)))
    if not summary.get("success") or not summary.get("built"):
        print("BLOCKDIRECTOR_EXPORT " + json.dumps(
            {"ok": False, "reason": "运行或构建失败", "summary": summary},
            ensure_ascii=False))
        return 1

    config = get_config()
    config.delivery.preset = DeliveryPreset(args.preset)
    config.delivery.appearance = Appearance(args.appearance)
    config.delivery.export_camera_traj = bool(args.camera_traj)

    from block_director.contracts.plan import Plan
    plan = Plan.from_dict(summary.get("plan") or {"shots": []})
    if not plan.shots:
        print("BLOCKDIRECTOR_EXPORT " + json.dumps(
            {"ok": False, "reason": "运行没有产出分镜计划"}, ensure_ascii=False))
        return 1

    report = export_project(plan, build_summary=summary.get("build"),
                            out_dir=out_dir, config=config.delivery,
                            project="BlockDirector")
    payload = report.to_dict()
    payload["summary"] = {"state": summary.get("state"),
                          "shots": summary.get("shots"),
                          "total_frames": summary.get("total_frames")}
    print("BLOCKDIRECTOR_EXPORT " + json.dumps(payload, ensure_ascii=False))
    return 0 if report.ok else 1

if __name__ == "__main__":
    sys.exit(main())
