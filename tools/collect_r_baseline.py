"""J 阶段冻结基线采集（v1.7 附录 X1 / 卡 H3-③）。

对一份已落盘的冻结工程（含 ``project.bdproj`` 的目录）：
  1. ``load_project`` 读工程（走与 ``rebuild_project.py`` 相同的迁移/校验链）；
  2. ``build_scene`` 重建场景（clear_scene=True，不调 LLM）；
  3. 逐镜 ``BpyShotAuditor().audit()``，统计 R020–R025 的 warning/error 数；
  4. 输出 ``BLOCKDIRECTOR_BASELINE <json>`` 单行标记（含各规则计数与 shot 明细）。

用法：
  blender --background --factory-startup --python tools/collect_r_baseline.py -- \
      --project <含 project.bdproj 的目录> [--label market4]

纪律：
  - 只记录、不判红（A-V2-2）：脚本从不改阈值、不跳过规则；
  - 输出形状固定，供 H3 汇总表直接消费；
  - 纯 stdlib + 包内模块，不引第三方。
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

#: H3 汇总表关心的规则号（J1–J4 引入）。
TARGET_RULES = ("R020", "R021", "R022", "R023", "R024", "R025")


def parse_args(argv) -> argparse.Namespace:
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="collect_r_baseline")
    parser.add_argument("--project", required=True, help="含 project.bdproj 的目录")
    parser.add_argument("--label", default="", help="证据表里的工程别名")
    parser.add_argument("--out", default="", help="额外把 JSON 落盘到此路径")
    return parser.parse_args(rest)


def main() -> int:
    args = parse_args(sys.argv)

    import block_director
    block_director.register()

    from block_director.layer2_sdl import sdl_to_plan, sdl_to_spec
    from block_director.layer3_engine.shot_builder import build_scene
    from block_director.layer3_engine.scene_context import get_context
    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer9_persistence import load_project

    project_dir = Path(os.path.abspath(args.project))
    loaded = load_project(project_dir)
    plan = sdl_to_plan(loaded.sdl)
    spec = sdl_to_spec(loaded.sdl)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()

    context = get_context()
    if context is None:
        print("BLOCKDIRECTOR_BASELINE " + json.dumps(
            {"ok": False, "reason": "build_scene 后无场景上下文"},
            ensure_ascii=False))
        return 1

    auditor = BpyShotAuditor()
    shot_ids = list(context.cameras or {})
    per_shot: dict = {}
    totals: dict = {rule: {"warning": 0, "error": 0} for rule in TARGET_RULES}
    for shot_id in shot_ids:
        result = auditor.audit(str(shot_id))
        counts = {rule: {"warning": 0, "error": 0} for rule in TARGET_RULES}
        for item in list(result.warnings) + list(result.errors):
            rule = str(item.rule or "")
            if rule not in TARGET_RULES:
                continue
            key = "error" if item.is_error else "warning"
            counts[rule][key] += 1
            totals[rule][key] += 1
        per_shot[str(shot_id)] = {
            "passed": bool(result.passed),
            "rules": counts,
        }

    payload = {
        "ok": True,
        "label": args.label or project_dir.name,
        "project": str(project_dir),
        "shots_built": int(summary.get("shots", 0)),
        "shots_audited": len(shot_ids),
        "target_rules": list(TARGET_RULES),
        "totals": totals,
        "per_shot": per_shot,
    }
    line = "BLOCKDIRECTOR_BASELINE " + json.dumps(payload, ensure_ascii=False)
    print(line)
    if args.out:
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
