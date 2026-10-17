"""vlm-feedback 卡 V11：场景空间数据摘要（cinema/spatial_digest.py）纯层测试。

钉死：

* FOV 三种 sensor_fit 的解析解；非法镜头参数报错；
* 元素 vs 相机：深度 / 水平竖直偏角 / 视锥内外 / NDC 中心（构造已知相机与点）；
* 角色朝向相对相机 0/90/180°、画面朝向（左/右/无）；
* A 面向 B 的方位角与 ``a_faces_b`` 的 90° 边界；
* 深度序与画面左右序；
* AABB 间隙三态（分离/接触/穿透）与穿透深度、margin 边界；
* 安全区告警（frustum_metrics）：越出边/最大越出量/持续判据/离场豁免/完全出画豁免；
* 角色×角色穿透告警（frustum_metrics）：持续判据、去重、证据；
* 九宫格九格；DTO serde 往返；json 往返；文本渲染优先级与整行舍弃；
* 配置键默认值与 overlay 常量相等、guard_config_from 透传、(0,1] 校验；
* ``rule_checker`` 的 COLLISION_MARGIN 改为从本模块导入（AST 对拍）；
* framing digest 首/中/末三帧选择与安全区判定；scene_digest 合并形状。

本文件不 import bpy / rule_checker（后者在纯 pytest 里不可导入），rule_checker
的常量来源用 AST 对拍。
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from block_director.cinema.composition import SubjectBox
from block_director.cinema.frustum_metrics import (
    HEAD_FRACTION,
    DeclaredShot,
    FrameSample,
    GuardConfig,
    compare_with_intent,
    detect_events,
    guard_config_from,
    safe_area_bounds,
)
from block_director.cinema.spatial_digest import (
    COLLISION_MARGIN,
    SpatialCamera,
    SpatialElement,
    SpatialFrame,
    aabb_gap,
    camera_fov_degrees,
    collision_state,
    framing_digest,
    render_spatial_digest,
    scene_digest,
    spatial_digest,
    thirds_cell,
)
from block_director.contracts.config import AppConfig
from block_director.contracts.guard import (
    WARNING_TYPES,
    Confidence,
    Severity,
)
from block_director.overlay.geometry import ACTION_SAFE, TITLE_SAFE

ROOT = Path(__file__).resolve().parents[1]


def _camera(lens=18.0, sensor_w=36.0, sensor_h=24.0, fit="AUTO",
            pos=(0.0, 0.0, 0.0), forward=(0.0, 0.0, -1.0),
            up=(0.0, 1.0, 0.0), render_w=1280, render_h=720):
    return SpatialCamera(position=pos, forward=forward, up=up, lens_mm=lens,
                         sensor_width=sensor_w, sensor_height=sensor_h,
                         sensor_fit=fit, render_width=render_w,
                         render_height=render_h)


def _element(kind="character", center=(0.0, 0.0, -10.0), facing=None,
             aabb_min=(-0.5, -0.5, -10.5), aabb_max=(0.5, 0.5, -9.5),
             id=None):
    return SpatialElement(id=id or kind, kind=kind, aabb_min=aabb_min,
                          aabb_max=aabb_max, center=center, facing=facing)


def _frame(camera=None, elements=None, frame=7, shot="shot_001"):
    return SpatialFrame(frame=frame, shot_id=shot,
                        camera=camera or _camera(),
                        elements=elements or [_element()])


def _box(left, right, bottom, top, facing=0.0):
    return SubjectBox("a", left=left, right=right, top=top, bottom=bottom,
                      facing=facing)


def _seq(b, frames, subject="a", shot="shot_001", visible=1.0, behind=False,
         collisions=None):
    return [FrameSample(f, subject, b, visible, behind, shot,
                        collisions=list(collisions or [])) for f in frames]


# ---------------------------------------------------------------- FOV 解析解
def test_camera_fov_horizontal_auto_and_vertical_fits():
    cam = _camera(lens=36.0, sensor_w=36.0, sensor_h=18.0, fit="AUTO",
                  render_w=3600, render_h=1800)     # aspect = 2.0
    hf, vf = camera_fov_degrees(cam)
    assert hf == pytest.approx(2 * math.degrees(math.atan(18.0 / 36.0)))
    assert vf == pytest.approx(2 * math.degrees(math.atan(9.0 / 36.0)))
    horizontal = _camera(lens=36.0, sensor_w=36.0, sensor_h=18.0,
                         fit="HORIZONTAL", render_w=3600, render_h=1800)
    assert camera_fov_degrees(horizontal) == pytest.approx((hf, vf))
    vertical = _camera(lens=36.0, sensor_w=36.0, sensor_h=18.0,
                       fit="VERTICAL", render_w=3600, render_h=1800)
    vhf, vvf = camera_fov_degrees(vertical)
    assert vvf == pytest.approx(2 * math.degrees(math.atan(9.0 / 36.0)))
    assert vhf == pytest.approx(2 * math.degrees(math.atan(18.0 / 36.0)))


def test_camera_fov_rejects_bad_parameters():
    for bad in (_camera(lens=0.0), _camera(sensor_w=0.0),
                _camera(sensor_h=0.0), _camera(render_h=0)):
        with pytest.raises(ValueError):
            camera_fov_degrees(bad)


# ---------------------------------------------------------------- 元素 vs 相机
def _digest_one(camera, elements):
    return spatial_digest([_frame(camera=camera, elements=elements)],
                          collision_margin=0.2)["frames"][0]


def test_depth_off_axis_and_frustum_membership_are_analytic():
    # lens 18 / sensor 36×36 / aspect 1 → 水平与竖直半视场都是 45°。
    cam = _camera(lens=18.0, sensor_w=36.0, sensor_h=36.0, render_w=1,
                  render_h=1)
    hf, vf = camera_fov_degrees(cam)
    assert hf == pytest.approx(90.0) and vf == pytest.approx(90.0)
    on_axis = _element(id="on_axis", center=(0.0, 0.0, -10.0))
    right_edge = _element(id="right_edge", center=(10.0, 0.0, -10.0))
    outside = _element(id="outside", center=(10.1, 0.0, -10.0))
    above = _element(id="above", center=(0.0, 5.0, -10.0))
    behind = _element(id="behind", center=(0.0, 0.0, 10.0))
    frame = _digest_one(cam, [on_axis, right_edge, outside, above, behind])
    by_id = {item["id"]: item for item in frame["elements"]}
    assert by_id["on_axis"]["depth_m"] == pytest.approx(10.0, abs=1e-3)
    assert by_id["on_axis"]["off_axis_deg"] == {
        "horizontal": pytest.approx(0.0, abs=1e-3),
        "vertical": pytest.approx(0.0, abs=1e-3),
    }
    assert by_id["on_axis"]["ndc_center"] == [
        pytest.approx(0.5, abs=1e-3), pytest.approx(0.5, abs=1e-3)]
    assert by_id["right_edge"]["off_axis_deg"]["horizontal"] == \
        pytest.approx(45.0, abs=1e-3)
    assert by_id["right_edge"]["in_frustum"] is True
    assert by_id["outside"]["in_frustum"] is False
    assert by_id["above"]["off_axis_deg"]["vertical"] == \
        pytest.approx(math.degrees(math.atan(0.5)), abs=1e-3)
    assert by_id["behind"]["in_frustum"] is False
    assert by_id["behind"]["depth_m"] < 0.0


def test_facing_relative_to_camera_zero_ninety_one_eighty():
    cam = _camera(pos=(0.0, -5.0, 0.0), forward=(0.0, 1.0, 0.0),
                  up=(0.0, 0.0, 1.0))
    toward = _element(id="toward", center=(0.0, 0.0, 0.0),
                      facing=(0.0, -1.0, 0.0))
    profile = _element(id="profile", center=(0.0, 0.0, 0.0),
                       facing=(1.0, 0.0, 0.0))
    away = _element(id="away", center=(0.0, 0.0, 0.0),
                    facing=(0.0, 1.0, 0.0))
    frame = _digest_one(cam, [toward, profile, away])
    by_id = {item["id"]: item for item in frame["elements"]}
    assert by_id["toward"]["facing_vs_camera_deg"] == pytest.approx(
        0.0, abs=1e-3)
    assert by_id["profile"]["facing_vs_camera_deg"] == pytest.approx(
        90.0, abs=1e-3)
    assert by_id["away"]["facing_vs_camera_deg"] == pytest.approx(
        180.0, abs=1e-3)
    assert by_id["toward"]["screen_facing"] == "none"
    assert by_id["profile"]["screen_facing"] == "right"


def test_screen_facing_left_right_and_none():
    cam = _camera(pos=(0.0, -5.0, 0.0), forward=(0.0, 1.0, 0.0),
                  up=(0.0, 0.0, 1.0))
    frame = _digest_one(cam, [_element(facing=(1.0, 0.0, 0.0)),
                              _element(facing=(-1.0, 0.0, 0.0)),
                              _element(facing=(0.0, -1.0, 0.0))])
    assert [item["screen_facing"] for item in frame["elements"]] == [
        "right", "left", "none"]


# ---------------------------------------------------------------- 元素之间
def _pair_digest(camera, a, b):
    frame = _digest_one(camera, [a, b])
    assert len(frame["pairs"]) == 1
    return frame["pairs"][0]


def test_azimuth_and_a_faces_b_ninety_degree_boundary():
    cam = _camera()
    a = _element(id="a", kind="character", center=(0.0, 0.0, -10.0),
                 facing=(1.0, 0.0, 0.0))
    b_front = _element(id="b", kind="character", center=(1.0, 0.0, -10.0))
    b_side = _element(id="b", kind="character", center=(0.0, 1.0, -10.0))
    b_back = _element(id="b", kind="character", center=(-1.0, 0.0, -10.0))
    front = _pair_digest(cam, a, b_front)
    assert front["azimuth_deg"] == pytest.approx(0.0, abs=1e-3)
    assert front["a_faces_b"] is True
    side = _pair_digest(cam, a, b_side)
    assert side["azimuth_deg"] == pytest.approx(90.0, abs=1e-3)
    assert side["a_faces_b"] is True            # 90° 边界算面向
    back = _pair_digest(cam, a, b_back)
    assert back["azimuth_deg"] == pytest.approx(180.0, abs=1e-3)
    assert back["a_faces_b"] is False


def test_depth_and_screen_order():
    cam = _camera()
    a = _element(id="a", center=(0.0, 0.0, -5.0))
    b = _element(id="b", center=(1.0, 0.0, -10.0))
    pair = _pair_digest(cam, a, b)
    assert pair["distance_3d_m"] == pytest.approx(
        math.sqrt(1.0 + 25.0), abs=1e-3)
    assert pair["distance_horizontal_m"] == pytest.approx(1.0, abs=1e-3)
    assert pair["depth_order"] == ["a", "b"]     # a 更近
    assert pair["screen_order"] == ["a", "b"]    # a 更靠左（x 小）


def test_pair_set_is_characters_plus_character_vs_prop_or_wall():
    cam = _camera()
    a = _element(id="a", kind="character")
    b = _element(id="b", kind="character")
    prop = _element(id="p", kind="prop", center=(2.0, 0.0, -10.0))
    wall = _element(id="w", kind="wall", center=(3.0, 0.0, -10.0))
    frame = _digest_one(cam, [a, b, prop, wall])
    keys = sorted((item["a"], item["b"]) for item in frame["pairs"])
    assert keys == [("a", "b"), ("a", "p"), ("a", "w"),
                    ("b", "p"), ("b", "w")]


# ---------------------------------------------------------------- 碰撞箱
def test_aabb_gap_separated_touching_and_penetrating():
    assert aabb_gap((0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3)) == \
        pytest.approx(1.0)
    assert aabb_gap((0, 0, 0), (1, 1, 1), (1, 0, 0), (2, 1, 1)) == \
        pytest.approx(0.0)                       # 仅接触面
    assert aabb_gap((0, 0, 0), (2, 1, 1), (1, 0, 0), (3, 1, 1)) == \
        pytest.approx(-1.0)                      # 穿透深度 = 最小重叠量


def test_collision_state_margin_boundary():
    assert collision_state(-0.01, 0.2) == "penetrating"
    assert collision_state(0.0, 0.2) == "too_close"
    assert collision_state(0.199, 0.2) == "too_close"
    assert collision_state(0.2, 0.2) == "clear"   # gap == margin 不算过近
    assert collision_state(0.5, 0.2) == "clear"


def test_digest_pair_gap_and_state_use_margin():
    cam = _camera()
    a = _element(id="a", kind="character",
                 aabb_min=(0, 0, 0), aabb_max=(2, 1, 1), center=(1, 0.5, 0.5))
    b = _element(id="b", kind="character",
                 aabb_min=(1, 0, 0), aabb_max=(3, 1, 1), center=(2, 0.5, 0.5))
    pair = _pair_digest(cam, a, b)
    assert pair["gap_m"] == pytest.approx(-1.0, abs=1e-3)
    assert pair["state"] == "penetrating"
    separated = _element(id="c", kind="character",
                         aabb_min=(3, 0, 0), aabb_max=(4, 1, 1),
                         center=(3.5, 0.5, 0.5))
    close = _pair_digest(cam, a, separated)
    assert close["gap_m"] == pytest.approx(1.0, abs=1e-3)
    assert close["state"] == "clear"


# ---------------------------------------------------------------- 告警：安全区
def _cfg(sustain=12):
    cfg = GuardConfig(sustain_frames=sustain)
    return cfg


def test_safe_area_bounds_match_the_inset_definition():
    low, high = safe_area_bounds(0.93)
    assert low == pytest.approx(0.035) and high == pytest.approx(0.965)


def test_safe_area_breach_reports_edges_exceedance_and_sustain():
    # 头部盒顶 0.99 越过 action 0.93 上界（0.965），越出 0.025。
    inside = _box(0.4, 0.6, 0.1, 0.9)
    breach = _box(0.4, 0.6, 0.1, 0.99)
    short = _seq(inside, [1, 5]) + _seq(breach, [9]) + _seq(inside, [13])
    assert "safe_area_breach" not in {
        w.type for w in compare_with_intent(
            short, DeclaredShot("shot_001", "MLS", "a"), _cfg())}
    long = _seq(inside, [1]) + _seq(breach, [5, 9, 13, 17]) + _seq(inside, [21])
    found = [w for w in compare_with_intent(
        long, DeclaredShot("shot_001", "MLS", "a"), _cfg())
        if w.type == "safe_area_breach"]
    assert len(found) == 1
    warning = found[0]
    assert warning.frame_range == (5, 17)
    assert warning.severity is Severity.WARNING
    assert warning.confidence is Confidence.HIGH
    assert warning.evidence["edges"] == ["top"]
    assert warning.evidence["exceed_max"] == pytest.approx(0.025)
    head_h = 0.89 * HEAD_FRACTION
    assert warning.evidence["exceed_ratio"] == pytest.approx(
        0.025 / head_h, abs=1e-4)                 # evidence 四舍五入到 4 位
    assert warning.evidence["safe_area_action"] == pytest.approx(0.93)


def test_safe_area_breach_is_skipped_when_fully_out_of_frame():
    breach = _box(0.4, 0.6, 0.1, 0.99)
    out = _box(1.2, 1.4, 0.1, 0.99)
    samples = _seq(breach, [1, 5, 9, 13, 17])
    kinds = {w.type for w in compare_with_intent(
        samples, DeclaredShot("shot_001", "MLS", "a"), _cfg(sustain=4))}
    assert "safe_area_breach" in kinds
    out_samples = _seq(out, [1, 5, 9, 13, 17])
    out_kinds = {w.type for w in compare_with_intent(
        out_samples, DeclaredShot("shot_001", "MLS", "a"), _cfg(sustain=4))}
    assert "safe_area_breach" not in out_kinds


def test_safe_area_breach_is_not_judged_after_declared_exit():
    breach = _box(0.4, 0.6, 0.1, 0.99)
    declared = DeclaredShot("shot_001", "MLS", "a", declared_exit_frame=10)
    after_exit = _seq(breach, [11, 13, 15, 17, 19])
    after_kinds = {w.type for w in compare_with_intent(
        after_exit, declared, _cfg(sustain=4))}
    assert "safe_area_breach" not in after_kinds   # 全部落在声明离场之后
    before_exit = _seq(breach, [1, 5, 9])
    before_kinds = {w.type for w in compare_with_intent(
        before_exit, declared, _cfg(sustain=4))}
    assert "safe_area_breach" in before_kinds      # 离场前仍照常判定


def test_multiple_edges_and_worst_exceedance_are_evidence():
    corner = _box(0.01, 0.99, 0.0, 0.99)
    samples = _seq(corner, [1, 5, 9, 13, 17])
    found = [w for w in compare_with_intent(
        samples, DeclaredShot("shot_001", "MLS", "a"), _cfg(sustain=4))
        if w.type == "safe_area_breach"]
    assert len(found) == 1
    edges = sorted(found[0].evidence["edges"])
    assert edges == ["left", "right", "top"]
    assert found[0].evidence["exceed_max"] == pytest.approx(0.035 - 0.01)


# ---------------------------------------------------------------- 告警：碰撞
def test_element_collision_requires_sustained_penetration():
    collision = {"pair": ["a", "b"], "gap": -0.2}
    clear = {"pair": ["a", "b"], "gap": 0.5}
    box = _box(0.4, 0.6, 0.1, 0.9)
    short = _seq(box, [1, 5, 9], collisions=[collision])
    assert not [w for w in detect_events(short, _cfg())
                if w.type == "element_collision"]
    long = _seq(box, [1, 5, 9, 13, 17], collisions=[collision])
    found = [w for w in detect_events(long, _cfg())
             if w.type == "element_collision"]
    assert len(found) == 1
    warning = found[0]
    assert warning.frame_range == (1, 17)
    assert warning.subject == "a|b"
    assert warning.evidence["pair"] == ["a", "b"]
    assert warning.evidence["penetration_depth"] == pytest.approx(0.2)
    assert warning.severity is Severity.WARNING
    assert not [w for w in detect_events(
        _seq(box, [1, 5, 9, 13, 17], collisions=[clear]), _cfg())
        if w.type == "element_collision"]


def test_element_collision_is_deduplicated_across_both_subjects():
    collision = {"pair": ["b", "a"], "gap": -0.1}
    box = _box(0.4, 0.6, 0.1, 0.9)
    both = (_seq(box, [1, 5, 9, 13, 17], subject="a",
                 collisions=[collision])
            + _seq(box, [1, 5, 9, 13, 17], subject="b",
                   collisions=[collision]))
    found = [w for w in detect_events(both, _cfg())
             if w.type == "element_collision"]
    assert len(found) == 1 and found[0].subject == "a|b"


# ---------------------------------------------------------------- 九宫格
def test_thirds_grid_covers_all_nine_cells():
    cells = {
        (0.1, 0.1): "bottom_left", (0.5, 0.1): "bottom_center",
        (0.9, 0.1): "bottom_right", (0.1, 0.5): "middle_left",
        (0.5, 0.5): "middle_center", (0.9, 0.5): "middle_right",
        (0.1, 0.9): "top_left", (0.5, 0.9): "top_center",
        (0.9, 0.9): "top_right",
    }
    for (x, y), cell in cells.items():
        assert thirds_cell(x, y) == cell, (x, y)
    assert thirds_cell(1.0 / 3.0, 1.0 / 3.0) == "middle_center"
    assert thirds_cell(2.0 / 3.0, 2.0 / 3.0) == "top_right"
    assert thirds_cell(-1.0, 2.0) == "top_left"   # 出画坐标夹进九宫格


# ---------------------------------------------------------------- serde 与 json
def test_spatial_dtos_round_trip_through_json():
    frame = _frame(camera=_camera(), elements=[
        _element(id="char_a", kind="character", facing=(0.0, 0.0, -1.0)),
        _element(id="prop_x", kind="prop"),
    ])
    restored = SpatialFrame.from_dict(
        json.loads(json.dumps(frame.to_dict())))
    assert restored.to_dict() == frame.to_dict()


def test_digest_is_json_serializable_and_rounds_to_three_places():
    frame = _frame(camera=_camera(), elements=[_element()])
    digest = spatial_digest([frame], collision_margin=0.2)
    text = json.dumps(digest, ensure_ascii=False)
    loaded = json.loads(text)
    assert loaded["conventions"]["world"] == "meters, Z-up"
    element = loaded["frames"][0]["elements"][0]
    assert element["depth_m"] == pytest.approx(10.0, abs=1e-3)


# ---------------------------------------------------------------- 文本渲染
def test_render_priority_and_whole_line_dropping():
    cam = _camera()
    a = _element(id="a", kind="character",
                 aabb_min=(0, 0, 0), aabb_max=(2, 1, 1),
                 center=(1, 0.5, 0.5), facing=(1.0, 0.0, 0.0))
    b = _element(id="b", kind="character",
                 aabb_min=(1, 0, 0), aabb_max=(3, 1, 1),
                 center=(2, 0.5, 0.5), facing=(1.0, 0.0, 0.0))
    digest = spatial_digest([_frame(camera=cam, elements=[a, b])],
                            collision_margin=0.2)
    rendered = render_spatial_digest(digest, max_chars=200)
    lines = rendered.splitlines()
    assert lines[0].startswith("[帧7] 碰撞 a-b:")
    assert any(line.startswith("[帧7] 相机 ") for line in lines)
    assert any(line.startswith("[帧7] a: depth=") for line in lines)
    assert len(rendered) <= 200
    # 放不下的整行舍弃：碰撞行 + 相机行 + 一条角色行都在 200 预算内，
    # 关系行被整行丢弃、绝不截半行。
    assert not any("[帧7] a-b: 3d=" in line for line in lines)
    assert render_spatial_digest(digest, max_chars=0) == ""


def test_render_keeps_whole_lines_and_honours_the_cap():
    digest = spatial_digest([_frame()], collision_margin=0.2)
    for cap in (40, 41, 80, 1200):
        rendered = render_spatial_digest(digest, max_chars=cap)
        assert len(rendered) <= cap
        assert all(len(line) <= cap for line in rendered.splitlines())


# ---------------------------------------------------------------- 配置与常量
def test_warning_types_include_the_v11_additions():
    assert "safe_area_breach" in WARNING_TYPES
    assert "element_collision" in WARNING_TYPES
    assert len(set(WARNING_TYPES)) == len(WARNING_TYPES)


def test_safe_area_defaults_equal_overlay_constants_in_both_configs():
    cfg = AppConfig().guard
    assert cfg.safe_area_action == pytest.approx(ACTION_SAFE) == 0.93
    assert cfg.safe_area_title == pytest.approx(TITLE_SAFE) == 0.90
    runtime = guard_config_from(AppConfig())
    assert runtime.safe_area_action == pytest.approx(0.93)
    assert runtime.safe_area_title == pytest.approx(0.90)
    assert GuardConfig().safe_area_action == pytest.approx(0.93)


def test_safe_area_keys_validate_inside_zero_one_closed():
    cfg = AppConfig()
    assert "CFG_216" not in {issue.code for issue in cfg.validate()}
    cfg.guard.safe_area_action = 1.0
    assert "CFG_216" not in {issue.code for issue in cfg.validate()}
    cfg.guard.safe_area_action = 0.0
    assert "CFG_216" in {issue.code for issue in cfg.validate()}
    cfg = AppConfig()
    cfg.guard.safe_area_title = 1.2
    assert "CFG_216" in {issue.code for issue in cfg.validate()}


def test_collision_margin_is_the_single_source_for_rule_checker():
    assert COLLISION_MARGIN == 0.2
    source = (ROOT / "block_director" / "layer3_engine"
              / "rule_checker.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node for node in tree.body
               if isinstance(node, ast.ImportFrom)]
    margin_import = [node for node in imports
                     if "COLLISION_MARGIN" in {a.name for a in node.names}]
    assert margin_import, "rule_checker 必须从纯层导入 COLLISION_MARGIN"
    assert margin_import[0].module.endswith(".spatial_digest")
    assignments = [node for node in tree.body
                   if isinstance(node, ast.Assign)]
    local = [node for node in assignments
             if any(getattr(t, "id", "") == "COLLISION_MARGIN"
                    for t in node.targets)]
    assert not local, "rule_checker 不得再本地定义 COLLISION_MARGIN"


# ---------------------------------------------------------------- framing/scene
def test_framing_digest_picks_first_middle_and_last_frame():
    samples = []
    for frame in (1, 5, 9, 13, 17):
        samples.append(FrameSample(
            frame, "a", _box(0.4, 0.6, 0.1, 0.9), 1.0, False, "shot_001"))
    digest = framing_digest(samples, safe_action=0.93, safe_title=0.90)
    records = digest["subjects"]["a"]
    assert [item["frame"] for item in records] == [1, 9, 17]
    first = records[0]
    assert first["thirds"] == "middle_center"
    assert first["in_frame"] is True
    assert first["in_action_safe"] is True and first["in_title_safe"] is True
    assert first["screen_height_ratio"] == pytest.approx(0.8, abs=1e-3)


def test_framing_digest_reports_safe_area_breach_and_fewer_frames():
    breach = _box(0.4, 0.6, 0.1, 0.99)
    digest = framing_digest(_seq(breach, [3, 7]), safe_action=0.93,
                            safe_title=0.90)
    records = digest["subjects"]["a"]
    assert [item["frame"] for item in records] == [3, 7]
    assert all(item["in_action_safe"] is False for item in records)
    assert all(item["in_title_safe"] is False for item in records)
    behind = FrameSample(5, "a", _box(0.4, 0.6, 0.1, 0.9), 0.0, True,
                         "shot_001")
    single = framing_digest([behind], safe_action=0.93, safe_title=0.90)
    assert [item["frame"] for item in single["subjects"]["a"]] == [5]
    assert single["subjects"]["a"][0]["behind_camera"] is True


def test_scene_digest_combines_framing_and_spatial():
    sample = FrameSample(7, "a", _box(0.4, 0.6, 0.1, 0.9), 1.0, False,
                         "shot_001")
    digest = scene_digest([sample], [_frame()], safe_action=0.93,
                          safe_title=0.90, collision_margin=0.2)
    assert set(digest) == {"framing", "spatial"}
    assert digest["framing"]["subjects"]["a"][0]["frame"] == 7
    assert digest["spatial"]["frames"][0]["frame"] == 7
    json.dumps(digest, ensure_ascii=False)
