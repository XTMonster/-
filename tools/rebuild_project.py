"""从项目文件重建场景（执行文档 v1.2 §14.2）。

这是"改一镜、重出一镜"的基础：加载 SDL → 还原计划与场景设定 → 重建场景；
加 ``--export`` 就顺带重出交付包，全程不再调用 LLM。

v1.5：**校验不过的项目照样重建**。校验结果照样逐条跑、逐条带回来（`validation`
字段 ＋ 一行 ``BLOCKDIRECTOR_REBUILD_WARN``），但它不再是一道闸门——理由是
2026-10-03 的真跑：64 镜跑完后 `project.bdproj` 里带 26 条 S6，
而"最容易需要修的工程"恰好就是这些带 finding 的工程。真正的交付门在
``export_project`` 的渲染审计那一步。

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


def rebuild_verdict(loaded) -> dict:
    """重建前的结论：**报告**校验结果，但不据此拒绝重建。

    纯函数（``loaded`` 是 :class:`LoadedProject`），因此策略本身可以被
    pytest 直接钉住，而不必启动 Blender。
    """
    from block_director.contracts.evidence import evidence_status_text
    from block_director.layer9_persistence import validation_report

    report = validation_report(loaded)
    return {"proceed": True,
            "blocked_reason": "",
            "validation": report,
            "evidence": dict(loaded.evidence_status),
            "evidence_text": evidence_status_text(loaded.evidence_status)}


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

    verdict = rebuild_verdict(loaded)
    report = verdict["validation"]
    if report["errors"]:
        print("BLOCKDIRECTOR_REBUILD_WARN " + json.dumps(
            {"validation": "failed", "errors": len(report["errors"]),
             "rules": report["rules"],
             "detail": [f"{item.get('rule')} {item.get('target')}: "
                        f"{item.get('message')}"
                        for item in report["errors"][:8]],
             "note": "仍然重建；闸门在 export_project 的渲染审计"},
            ensure_ascii=False))

    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()

    payload = {"ok": True, "project": str(loaded.path),
               "notes": loaded.notes,
               "shots": summary["shots"],
               "total_frames": summary["total_frames"],
               "characters": summary["characters"],
               "warnings": summary["warnings"],
               "validation": report,
               "evidence": verdict["evidence"],
               "evidence_text": verdict["evidence_text"]}

    if args.export:
        from block_director.layer8_delivery import export_project

        report = export_project(plan, build_summary=summary,
                                out_dir=project_dir, config=get_config().delivery,
                                brief=getattr(loaded.sdl, "brief", None),
                                project=loaded.sdl.name)
        payload["export"] = report.to_dict()

    print("BLOCKDIRECTOR_REBUILD " + json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
