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

    #: D1 逐镜路径：原跑走 prepare_scene → 每镜 rebuild_shot，重放必须
    #: 镜像同一条构建序列（replay() 按 scene_prepared 事件自动选逐镜分支）。
    from block_director.layer3_engine.shot_builder import BpySceneBuilder
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.driver import default_registry
    from block_director.layer9_persistence import ReplayError, replay

    registry = default_registry()
    register_all_scene_tools(registry)
    project_dir = Path(args.project)

    try:
        report = replay(project_dir, registry,
                        builder=BpySceneBuilder(clear_scene=True))
    except ReplayError as exc:
        _emit({"ok": False, "reason": f"{type(exc).__name__}: {exc}"})
        return 1

    payload = report.to_dict()
    if args.export and report.ok and report.plan is not None:
        from block_director.layer8_delivery import export_project
        from block_director.layer5_orchestrator.ruler_observation import (
            build_observation_from_log,
        )
        from block_director.layer5_orchestrator.headless_runner import (
            spatial_export_args,
        )
        from block_director.layer9_persistence import read_audit_log
        from block_director.settings import get_config

        #: 空间尺观测（Ticket 06）：重放自动复用同一路径——只读 audit_log + 
        #: build_summary 折出观测（无 LLM 调用），随重导出落 ruler_observation.json。
        ruler_observation = build_observation_from_log(
            read_audit_log(project_dir), report.plan, brief=report.brief,
            build_summary=report.summary, fps=24,
            run_context={"source_run": report.brief_source or "replay",
                         "status": "replayed",
                         "shots": len(report.plan.shots)},
            observation_id=f"obs-replay-{Path(project_dir).name}")
        delivery = export_project(report.plan, build_summary=report.summary,
                                  out_dir=project_dir,
                                  config=get_config().delivery,
                                  brief=report.brief,
                                  ruler_observation=ruler_observation,
                                  **spatial_export_args(report.summary),
                                  project=report.plan.scene_heading or "BlockDirector")
        payload["export"] = delivery.to_dict()

    _emit(payload)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
