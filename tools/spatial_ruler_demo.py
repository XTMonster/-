"""空间尺最小可运行 demo。

用法: python tools/spatial_ruler_demo.py

演示"AI 怎么通过算法读懂空间"：
  1. 用一个"头顶留白过多"的包围盒构造构图报告（纯几何，无 Blender）；
  2. 生成新契约处方（只给方向：component / severity / current / target /
     allowed_tools / direction / expected_effect，不含 tool / tool_args）；
  3. 用 validate_prescription 证明处方方向合法、allowed_tools 在工具闭集内；
  4. 用 prescription.py 的正式 render_ruler_report 打印 AI 实际会看到的那段
     "尺子读数"（不含工具名/参数/"建议执行"，防答案泄漏）。
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
    detect_pollution,
    render_ruler_report,
    validate_prescription,
)


def main() -> int:
    # 1. 一个"头顶留白过多、主体偏下"的包围盒（NDC，0-1，左下原点）
    box = SubjectBox(name="小明", left=0.24, right=0.42, top=0.60,
                     bottom=0.35, facing=1.0)
    report = evaluate_composition([box])
    prescriptions = build_prescriptions(report)

    # 2. 证明每个处方方向合法、allowed_tools 都在工具闭集内
    print("== 处方方向校验 ==")
    for p in prescriptions:
        ok, why = validate_prescription(p)
        print(f"{p.component}: direction={p.direction!r} "
              f"allowed_tools={p.allowed_tools} -> "
              f"{'通过' if ok else why}")

    print("\n== AI 实际看到的尺子读数 ==")
    text = render_ruler_report(report, prescriptions)
    print(text)
    leak = detect_pollution(text)
    print(f"\n防污染检查：{'干净' if leak is None else f'泄漏 {leak}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
