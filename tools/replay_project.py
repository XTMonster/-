"""按审计日志确定性重放（执行文档 v1.2 §14.4）。

不调用 LLM：读 ``audit_log.jsonl`` → 按计划建场景 → 顺序重放工具调用。
加 ``--export`` 就顺带重出交付包，即"改代码后零成本重渲"。

用法：
  blender --background --factory-startup --python tools/replay_project.py -- \
      --project <项目目录> [--export]
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
    parser = argparse.ArgumentParser(prog="replay_project")
    parser.add_argument("--project", required=True, help="项目目录（含 audit_log.jsonl）")
    parser.add_argument("--export", action="store_true", help="重放后导出交付包")
    return parser.parse_args(rest)


def _emit(payload) -> None:
    print("BLOCKDIRECTOR_REPLAY " + json.dumps(payload, ensure_ascii=False))


def main() -> int:
    args = parse_args(sys.argv)

    import block_director
    block_director.register()

    from block_director.contracts.cast import SceneSpec
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.driver import default_registry
    from block_director.layer9_persistence import ReplayError, replay

    registry = default_registry()
    register_all_scene_tools(registry)
    project_dir = Path(args.project)

    def build(plan, spec):
        return build_scene(plan, spec or SceneSpec.from_plan(plan),
                           clear_scene=True).to_dict()

    try:
        report = replay(project_dir, registry, builder=build)
    except ReplayError as exc:
        _emit({"ok": False, "reason": f"{type(exc).__name__}: {exc}"})
        return 1

    payload = report.to_dict()
    if args.export and report.ok and report.plan is not None:
        from block_director.layer8_delivery import export_project
        from block_director.settings import get_config

        delivery = export_project(report.plan, build_summary=report.summary,
                                  out_dir=project_dir,
                                  config=get_config().delivery,
                                  project=report.plan.scene_heading or "BlockDirector")
        payload["export"] = delivery.to_dict()

    _emit(payload)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
