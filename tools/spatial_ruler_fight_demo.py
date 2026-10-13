"""空间尺 · 打斗剧情 demo。

用法: python tools/spatial_ruler_fight_demo.py

演示空间尺在打斗/高强度动作下的效果：轨迹、速度档、方向反转、出画/回冲、
分层遮挡、银幕左右序翻转，以及最紧帧的构图处方。
处方的可执行性按新契约（Ticket 03a）校验：只给方向与 allowed_tools，
不给具体工具名与参数，防止把修复答案泄漏给模型。
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.composition import SubjectBox, evaluate_composition
from block_director.cinema.dynamic_measure import (
    FightScene,
    analyze_fight,
    render_dynamic_report,
)
from block_director.cinema.prescription import (
    build_prescriptions,
    detect_pollution,
    render_ruler_report,
    validate_prescription,
)


def _box(cx: float, cy: float, half: float = 0.18, name: str = "甲",
         facing: float = 1.0) -> SubjectBox:
    return SubjectBox(name=name, left=cx - half, right=cx + half,
                      top=cy + 0.5, bottom=cy - 0.5, facing=facing)


def build_fight_scene() -> FightScene:
    """12 帧打斗：英雄进逼，反派被击飞出画后从另一侧回冲。"""
    hero_x = [2.0, 2.4, 2.8, 3.2, 3.4, 3.6, 3.8, 3.9, 4.0, 4.0, 4.0, 4.0]
    villain_x = [6.0, 5.8, 5.4, 5.0, 4.2, 3.9, 3.8, 8.5, 9.5, 1.5, 1.2, 1.0]
    villain_facing = [-1.0] * 7 + [-1.0, -1.0, 1.0, 1.0, 1.0]
    samples = []
    occlusions = []
    for i, frame in enumerate(range(1, 13), start=0):
        hx = hero_x[i]
        samples.append({
            "frame": frame, "character_id": "hero",
            "world_x": hx, "world_y": 0.0, "world_z": 1.7,
            "ndc_x": 0.5 + (hx - 4.0) / 6.0,
            "ndc_y": 0.55, "facing_x": 1.0,
        })
        vx = villain_x[i]
        samples.append({
            "frame": frame, "character_id": "villain",
            "world_x": vx, "world_y": 0.0, "world_z": 1.7,
            "ndc_x": 0.5 + (vx - 4.0) / 6.0,
            "ndc_y": 0.55, "facing_x": villain_facing[i],
        })
        if frame in (5, 6):
            occlusions.append({
                "frame": frame, "subject": "hero",
                "occluder": "villain", "occluder_class": "character",
                "part": "head", "visible_ratio": 0.3,
            })
    return FightScene(samples=samples, occlusions=occlusions,
                      shot_id="fight_01", frame_range=(1, 12))


def main() -> int:
    scene = build_fight_scene()
    report = analyze_fight(scene)

    print("== 打斗剧情 · 空间尺动态读数 ==")
    print(render_dynamic_report(report))

    # 最紧帧（第 5/6 帧重叠+遮挡）：构图处方
    tight = evaluate_composition(
        [_box(0.47, 0.55, name="hero"), _box(0.53, 0.55, name="villain")],
        occluded={"hero": True, "villain": False})
    prescriptions = build_prescriptions(tight)
    print("\n== 最紧帧（第5-6帧：重叠+头部被挡）构图处方 ==")
    for p in prescriptions:
        ok, why = validate_prescription(p)
        print(f"- {p.component}[{p.severity.value}] "
              f"方向校验：{'通过' if ok else why}")
    print("\n== AI 实际看到的尺子读数 ==")
    text = render_ruler_report(tight, prescriptions)
    print(text)
    leak = detect_pollution(text)
    print(f"\n防污染检查：{'干净' if leak is None else f'泄漏 {leak}'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
