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


def _crowd_from_script(parsed, crowd_config):
    """分镜表里写了群众才生成群众代理（v1.3 §3.6）。"""
    if parsed is None or crowd_config is None:
        return []
    from block_director.contracts.cast import crowd_from_script

    # v1.4 X17：``crowd.enabled`` 三态直接透传（None = 按剧本声明）。
    return crowd_from_script(parsed, enabled=crowd_config.enabled,
                             max_instances=int(crowd_config.max_instances),
                             mode=str(crowd_config.mode),
                             seed=int(crowd_config.seed))


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
    parser.add_argument("--max-llm-calls", type=int, default=0,
                        help="本次运行的 LLM 调用硬上限（§12.6）。本地模型"
                             "返工多，常需放大；0 表示不限")
    parser.add_argument("--preset", default="",
                        help="交付分辨率预设（hd16x9/fhd16x9/square/vertical）；"
                             "v1.4 §4.4 步骤 1 需要它来对齐像素阈值")
    return parser.parse_args(rest)


def main() -> int:
    args = parse_args(sys.argv)

    import block_director
    block_director.register()          # 走真实注册路径（含主线程登记与配置加载）

    from block_director.layer5_orchestrator.headless_runner import run_headless
    from block_director.layer5_orchestrator.driver import DriverLimits

    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.scene_state import collect_scene_state
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.driver import default_registry
    from block_director.layer5_orchestrator.human_gate import AutoGate
    from block_director.observation.state import format_scene_state

    script = ""
    parsed = None
    if args.script:
        path = Path(args.script)
        if path.exists():
            script = path.read_text(encoding="utf-8", errors="replace")
            try:
                from block_director.layer1_input import (
                    apply_deterministic_coreferences,
                    parse_script,
                )
                parsed = parse_script(path)
                # v1.3 P0-3：共指消解此前从未被真实链路调用（§4.3 是死代码）。
                # 先接上确定性的一面；代词消解交给 Stage S 的模型判断。
                merged = apply_deterministic_coreferences(parsed)
                print("BLOCKDIRECTOR_PARSE " + json.dumps(
                    {"format": parsed.source_format, "title": parsed.title,
                     "scenes": len(parsed.scenes),
                     "dialogues": parsed.dialogue_count,
                     "characters": parsed.character_names,
                     "needs_llm_structure": parsed.needs_llm_structure,
                     "coreference_merged": merged},
                    ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 - 解析失败要让人看见
                print(f"BLOCKDIRECTOR_WARN 剧本解析失败，将退回原文：{exc}")
        else:
            print(f"BLOCKDIRECTOR_WARN 剧本不存在: {path}")

    builder = None
    crowd: list = []
    from block_director.settings import get_config
    from block_director.contracts.enums import DeliveryPreset

    config = get_config()
    if args.preset:
        # v1.4 §4.4 步骤 1：只有写进配置，--preset 才真的改变本次导出分辨率
        # （与 tools/run_export.py:98-99 同款）。写错取值就明确报错。
        config.delivery.preset = DeliveryPreset(args.preset)

    registry = default_registry(max_shots=int(config.orchestration.max_shots))
    register_all_scene_tools(registry)

    if args.build:
        from block_director.layer3_engine.shot_builder import BpySceneBuilder

        crowd_config = config.crowd
        crowd = _crowd_from_script(parsed, crowd_config)
        if crowd:
            print("BLOCKDIRECTOR_CROWD " + json.dumps(
                {"entries": crowd,
                 "total": sum(item["count"] for item in crowd)},
                ensure_ascii=False))
        builder = BpySceneBuilder(clear_scene=True, crowd=crowd)

    summary = run_headless(
        script,
        offline=args.offline,
        project_dir=Path(args.out) if args.out else None,
        config=config,
        max_wall_s=args.wall,
        builder=builder,
        registry=registry,
        auditor=(BpyShotAuditor(audit_level=config.audit.level)
                 if builder is not None else None),
        human_gate=AutoGate(),      # headless 无界面：逐条记为 skipped 以便审计
        scene_state_provider=lambda: format_scene_state(
            collect_scene_state(detailed=False)),
        parsed_script=parsed,
        limits=DriverLimits(llm_timeout_s=args.llm_timeout,
                            max_llm_calls=args.max_llm_calls),
    )

    if args.save and summary.get("success") and summary.get("plan"):
        from block_director.layer5_orchestrator.headless_runner import (
            save_run_project,
        )

        spec = builder.spec if builder is not None else None
        saved = save_run_project(summary, out_dir=Path(args.save), spec=spec,
                                 crowd=crowd)
        #: 落盘时的校验结论随标记一起打出来——"存了个文件"与"存了个能打开的
        #: 文件"是两件事，调用方（人/链）不该等到 rebuild 才知道。
        print("BLOCKDIRECTOR_SAVED " + json.dumps(
            {"path": str(saved.path), "validation": saved.validation},
            ensure_ascii=False))

    export_failed = False
    if args.export and summary.get("success") and summary.get("plan"):
        # §15 的核心验收：**一条命令**从剧本产出干净的分镜参考视频。
        # 这里直接导出，场景还活在内存里——不必先落盘再重建。
        from pathlib import Path as _Path

        from block_director.contracts.plan import Plan
        from block_director.layer8_delivery import export_project

        out_dir = _Path(args.export_dir) if args.export_dir else (
            _Path(args.out) if args.out else _Path.cwd())
        plan_obj = Plan.from_dict(summary["plan"])
        report = export_project(plan_obj, build_summary=summary.get("build"),
                                out_dir=out_dir,
                                config=config.delivery,
                                compliance=summary.get("compliance"),
                                llm_calls=int(summary.get("llm_calls") or 0),
                                #: §3.3 的契约字段：`shots.json.retrieval_calls` 必须
                                #: 是**这一次运行**的检索调用数。此前 headless 这条路
                                #: 一个都不传（只有 `run_export.py` 与 UI 面板传），
                                #: 于是每次真实运行写出来的都是 0——实测 2026-10-03：
                                #: `knowledge.retrieval_calls = 7` 而顶层写着 0，
                                #: `tests/test_manifest_fields.py` 现在有一条契约断言
                                #: 钉住"传了 llm_calls 就必须传 retrieval_calls"。
                                retrieval_calls=int(
                                    summary.get("retrieval_calls") or 0),
                                crowd=crowd,
                                parsed=parsed,
                                timing_overrides=summary.get(
                                    "timing_overrides"),
                                action_conflicts=(summary.get("build") or {})
                                .get("action_conflicts"),
                                audit_pass_rate=summary.get("audit_pass_rate"),
                                knowledge_provenance=summary.get(
                                    "knowledge_provenance"),
                                #: 交付清单自带索引代际（§4.1b 的 Q5 只在真实运行上判，
                                #: 而"这份运行是哪一代索引"必须能从证据文件本身读出来）。
                                knowledge=summary.get("knowledge"),
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
