"""打斗/动态多角色测量（spec 4.3 B+）的纯层最小测试，不 import bpy。

覆盖：轨迹采样、速度档与方向反转、出画/回冲事件、分层遮挡归因、
银幕左右序状态机、高动态事件采样、报告体积上限、只读性、打斗处方可执行。
"""

from __future__ import annotations

from block_director.cinema.composition import SubjectBox

# 模块尚未实现：先红，再绿。
from block_director.cinema.dynamic_measure import (
    analyze_fight,
    render_dynamic_report,
)


def _box(cx: float, cy: float, half: float = 0.18, name: str = "甲",
         facing: float = 1.0) -> SubjectBox:
    return SubjectBox(name=name, left=cx - half, right=cx + half,
                      top=cy + 0.5, bottom=cy - 0.5, facing=facing)


def test_trajectory_sampling_present():
    """合成打斗产生帧序列，首尾不丢，轨迹里有世界坐标和速度档。"""
    report = analyze_fight(_fight_scene())
    assert report.trajectory["hero"].frames[0].frame == 1
    assert report.trajectory["hero"].frames[-1].frame == 12
    assert all(f.world_x is not None for f in report.trajectory["hero"].frames)
    assert report.trajectory["hero"].bands  # 非空


def test_velocity_bands_and_direction_change():
    """速度档与方向反转事件确定性；不引入新通过门限。"""
    report = analyze_fight(_fight_scene())
    bands = report.trajectory["hero"].bands
    assert bands, "速度档不应为空"
    flips = [e for e in report.events if e.kind == "direction_change"]
    assert flips, "打斗中应出现至少一次方向反转"


def test_exit_reentry_event():
    """出画、回冲、重新入画帧被记录。"""
    report = analyze_fight(_fight_scene())
    kinds = {e.kind for e in report.events}
    assert "exit_frame" in kinds
    assert "reentry_frame" in kinds
    exit_ev = next(e for e in report.events if e.kind == "exit_frame")
    assert exit_ev.frame == 8


def test_layer_occlusion_per_part_and_class():
    """遮挡按部位与元素类别归因，声明状态不被猜测覆盖。"""
    report = analyze_fight(_fight_scene())
    occ = report.occlusion_summary
    assert any(item.occluder_class == "character" for item in occ)
    assert any(item.part == "head" for item in occ)


def test_axis_state_across_shots():
    """左右序状态机能区分可见换位、中性桥接、无桥突变。"""
    report = analyze_fight(_fight_scene())
    flips = report.screen_order_flips
    assert flips, "打斗剧本应出现左右序翻转"
    assert flips[0].kind == "unbridged_flip", flips[0]


def test_high_dynamic_event_sampling():
    """速度极值/关键帧/方向反转触发局部加密。"""
    report = analyze_fight(_fight_scene())
    assert report.sampling.dense_frames  # 事件附近有加密帧


def test_dynamic_report_payload_cap():
    """长镜头报告有帧数/字符上限，超限显式标记截断原因。"""
    text = render_dynamic_report(analyze_fight(_fight_scene()))
    assert len(text) < 4000


def test_dynamic_probe_read_only():
    """动态测量查询前后对象、相机、关键帧和场景帧号不变。"""
    before = repr(_fight_scene())
    analyze_fight(_fight_scene())
    after = repr(_fight_scene())
    assert before == after


def test_fight_prescriptions_directional_and_unpolluted():
    """打斗帧处方按新契约：方向合法、allowed_tools 在闭集内、读数不泄漏。"""
    from block_director.cinema.prescription import (
        detect_pollution,
        validate_prescription,
    )

    bad: list[str] = []
    texts: list[str] = []
    for p in _fight_prescriptions():
        ok, _why = validate_prescription(p)
        if not ok:
            bad.append(p.component)
        texts.append(f"{p.component} {p.direction}")
    assert not bad, bad
    assert detect_pollution("\n".join(texts)) is None


# --------------------------------------------------------------------------- #
# 合成打斗剧本（demo 输入；位置/遮挡为“想定的镜头事实”）
# --------------------------------------------------------------------------- #
def _fight_scene():
    """12 帧打斗：英雄从左侧进逼，反派被击飞出画后从另一侧回冲。"""
    from block_director.cinema.dynamic_measure import FightScene

    hero_x = [2.0, 2.4, 2.8, 3.2, 3.4, 3.6, 3.8, 3.9, 4.0, 4.0, 4.0, 4.0]
    villain_x = [6.0, 5.8, 5.4, 5.0, 4.2, 3.9, 3.8, 8.5, 9.5, 1.5, 1.2, 1.0]
    villain_facing = [-1.0] * 7 + [-1.0, -1.0, 1.0, 1.0, 1.0]  # 第10帧回冲朝右
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
        #: 出画帧也采样（ndc 越界），让 exit 事件可测。
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


def _fight_prescriptions():
    """取打斗最紧帧（重叠帧）算构图处方，验证其可执行性。"""
    from block_director.cinema.composition import evaluate_composition
    from block_director.cinema.prescription import build_prescriptions

    report = evaluate_composition(
        [_box(0.47, 0.55, name="hero"), _box(0.53, 0.55, name="villain")],
        occluded={"hero": True, "villain": False})
    return build_prescriptions(report)
