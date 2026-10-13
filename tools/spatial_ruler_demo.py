"""空间尺最小可运行 demo。

用法: python tools/spatial_ruler_demo.py

演示"AI 怎么通过算法读懂空间"：
  1. 用一个"头顶留白过多"的包围盒构造构图报告（纯几何，无 Blender）；
  2. 生成可执行处方（tool + tool_args）；
  3. 用 validate_args 证明这些处方参数确实能被工具 schema 接受；
  4. 打印 AI 实际会看到的那段"尺子读数"。
"""
from __future__ import annotations

import sys
from pathlib import Path

# Windows 控制台默认按 ANSI/GBK 解释输出；强制 UTF-8，避免中文乱码。
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 允许从仓库根目录直接执行 `python tools/spatial_ruler_demo.py`。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.composition import SubjectBox, evaluate_composition
from block_director.cinema.prescription import (
    build_prescriptions,
    render_ruler_report,
)
from block_director.layer5_orchestrator.tool_schema import validate_args


ACTION_TOOL_SCHEMAS = {
    "move_camera": {
        "type": "object", "additionalProperties": False,
        "required": ["movement_type", "start_frame", "end_frame"],
        "properties": {
            "camera_id": {"type": "string"},
            "movement_type": {"type": "string", "enum": ["dolly_in", "dolly_out",
                                                         "truck_left", "truck_right",
                                                         "pan"]},
            "amount": {"type": "number", "minimum": 0, "maximum": 180},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "move_character": {
        "type": "object", "additionalProperties": False,
        "required": ["character_id", "target_position", "start_frame", "end_frame"],
        "properties": {
            "character_id": {"type": "string"},
            "target_position": {"type": "array", "minItems": 3, "maxItems": 3,
                                "items": {"type": "number"}},
            "speed": {"type": "string", "enum": ["walk", "run"]},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "reframe": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "shot_id": {"type": "string"},
            "shot_type": {"type": "string", "enum": ["MS"]},
            "lens": {"type": "number", "minimum": 8, "maximum": 300},
        },
    },
}


def main() -> int:
    # 1. 一个"头顶留白过多、主体偏下"的包围盒（NDC，0-1，左下原点）
    box = SubjectBox(name="小明", left=0.24, right=0.42, top=0.60,
                     bottom=0.35, facing=1.0)
    report = evaluate_composition([box])
    prescriptions = build_prescriptions(report)

    # 2. 证明每个处方的 tool_args 都能被现有工具 schema 接受
    print("== 处方参数 schema 校验 ==")
    for p in prescriptions:
        schema = ACTION_TOOL_SCHEMAS.get(p.tool)
        problems = validate_args(schema, p.tool_args) if schema else ["未知工具"]
        print(f"{p.component}: {p.tool}({p.tool_args}) -> "
              f"{'通过' if not problems else problems}")

    print("\n== AI 实际看到的尺子读数 ==")
    print(render_ruler_report(report, prescriptions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
