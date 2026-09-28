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
    parser.add_argument("--save", default="",
                        help="运行成功后把项目（SDL）保存到该目录")
    parser.add_argument("--export", action="store_true",
                        help="运行成功后直接导出交付包（§15 的一条命令验收）")
    parser.add_argument("--export-dir", default="",
                        help="交付包目录；留空则用 <out>/export")
    parser.add_argument("--llm-timeout", type=float, default=120.0,
                        help="单次 LLM 调用超时（秒）。本地大模型常需放大到 600+")
    parser.add_argument("--max-llm-calls", type=int, default=8,
                        help="本次运行的 LLM 调用硬上限（§12.6）。本地模型"
                             "返工多，常需放大；0 表示不限")
    return parser.parse_args(rest)


def main() -> int:
    args = parse_args(sys.argv)

    import block_director
    block_director.register()          # 走真实注册路径（含主线程登记与配置加载）

    from block_director.layer5_orchestrator.headless_runner import run_headless
    from block_director.layer5_orchestrator.driver import DriverLimits

    builder = None
    if args.build:
        from block_director.layer3_engine.shot_builder import BpySceneBuilder
        builder = BpySceneBuilder(clear_scene=True)

    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.scene_state import collect_scene_state
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.driver import default_registry
    from block_director.layer5_orchestrator.human_gate import AutoGate
    from block_director.observation.state import format_scene_state

    registry = default_registry()
    register_all_scene_tools(registry)

    script = ""
    parsed = None
    if args.script:
        path = Path(args.script)
        if path.exists():
            script = path.read_text(encoding="utf-8", errors="replace")
            try:
                from block_director.layer1_input import parse_script
                parsed = parse_script(path)
                print("BLOCKDIRECTOR_PARSE " + json.dumps(
                    {"format": parsed.source_format, "title": parsed.title,
                     "scenes": len(parsed.scenes),
                     "dialogues": parsed.dialogue_count,
                     "characters": parsed.character_names,
                     "needs_llm_structure": parsed.needs_llm_structure},
                    ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 - 解析失败要让人看见
                print(f"BLOCKDIRECTOR_WARN 剧本解析失败，将退回原文：{exc}")
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
        human_gate=AutoGate(),      # headless 无界面：逐条记为 skipped 以便审计
        scene_state_provider=lambda: format_scene_state(
            collect_scene_state(detailed=False)),
        parsed_script=parsed,
        limits=DriverLimits(llm_timeout_s=args.llm_timeout,
                            max_llm_calls=args.max_llm_calls),
    )

    if args.save and summary.get("success") and summary.get("plan"):
        from block_director.contracts.plan import Plan
        from block_director.layer2_sdl import build_sdl, validate_sdl
        from block_director.layer9_persistence import save_project

        plan_obj = Plan.from_dict(summary["plan"])
        spec = builder.spec if builder is not None else None
        sdl = build_sdl(plan_obj, build_summary=summary.get("build"),
                        spec=spec, project_name=plan_obj.scene_heading
                        or "BlockDirector")
        findings = validate_sdl(sdl)
        path = save_project(Path(args.save), sdl)
        print("BLOCKDIRECTOR_SAVED " + json.dumps(
            {"path": str(path), "problems": len(findings),
             "scenes": len(sdl.scenes), "shots": len(sdl.shots)},
            ensure_ascii=False))

    export_failed = False
    if args.export and summary.get("success") and summary.get("plan"):
        # §15 的核心验收：**一条命令**从剧本产出干净的分镜参考视频。
        # 这里直接导出，场景还活在内存里——不必先落盘再重建。
        from pathlib import Path as _Path

        from block_director.contracts.plan import Plan
        from block_director.layer8_delivery import export_project
        from block_director.settings import get_config

        out_dir = _Path(args.export_dir) if args.export_dir else (
            _Path(args.out) if args.out else _Path.cwd())
        plan_obj = Plan.from_dict(summary["plan"])
        report = export_project(plan_obj, build_summary=summary.get("build"),
                                out_dir=out_dir,
                                config=get_config().delivery,
                                project=plan_obj.scene_heading or "BlockDirector")
        payload = report.to_dict()
        print("BLOCKDIRECTOR_EXPORT " + json.dumps(
            {"ok": report.ok, "aborted": report.aborted,
             "out_dir": report.out_dir, "files": len(report.files),
             "warnings": report.warnings, "reason": report.reason},
            ensure_ascii=False))
        export_failed = not report.ok

    print("BLOCKDIRECTOR_RESULT " + json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("success") and not export_failed else 1


if __name__ == "__main__":
    sys.exit(main())
