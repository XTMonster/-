"""纯层网格可见性：视锥裁剪、面可见面积比、NDC 投影、角色部位归属。

相机约定与 ``cinema/framing.py`` 一致：世界系、米、Z 向上；画面 NDC
[0,1]，(0,0) 左下；相机看向 ``forward``。标准算法：Gribb–Hartmann 视锥
平面 ＋ Sutherland–Hodgman 多边形裁剪 ＋ 透视投影。
"""

from __future__ import annotations

import pytest

from block_director.cinema import mesh_visibility as MV
from block_director.cinema.anchor import DEFAULT_PROFILE

# 相机：原点看向 -Z，vfov=90°，aspect=1，near=1，far=100。
_CAMERA = {
    "position": (0.0, 0.0, 0.0),
    "forward": (0.0, 0.0, -1.0),
    "up": (0.0, 1.0, 0.0),
    "vfov_deg": 90.0,
    "aspect": 1.0,
    "near": 1.0,
    "far": 100.0,
}


def _frustum():
    return MV.frustum_from_camera(**_CAMERA)


def test_body_parts_follow_the_frozen_profile_bands():
    profile = DEFAULT_PROFILE
    assert MV.part_of_point((0, 0.1, 0), profile) == "腿"
    assert MV.part_of_point((0, profile.hip_z + 0.01, 0), profile) == "躯干"
    assert MV.part_of_point((0, profile.head_center_z, 0), profile) == "头"
    assert MV.part_of_point((0, -0.01, 0), profile) == "未知"
    assert MV.part_of_point((0, profile.head_top_z + 0.01, 0), profile) == "未知"


def test_vertex_frustum_classification():
    frustum = _frustum()
    assert MV.vertex_in_frustum(frustum, (0.0, 0.0, -2.0))
    assert not MV.vertex_in_frustum(frustum, (0.0, 0.0, 2.0))   # 机后
    assert not MV.vertex_in_frustum(frustum, (3.0, 0.0, -2.0))  # 右出界
    assert not MV.vertex_in_frustum(frustum, (0.0, 3.0, -2.0))  # 上出界
    assert not MV.vertex_in_frustum(frustum, (0.0, 0.0, -200.0))  # 远出界
    assert not MV.vertex_in_frustum(frustum, (0.0, 0.0, -0.5))  # 近出界


def test_face_visibility_fraction_is_analytic():
    frustum = _frustum()
    triangle = [(1.0, 0.0, -2.0), (3.0, 0.0, -2.0), (3.0, 2.0, -2.0)]
    fraction, clipped = MV.face_visibility(frustum, triangle)
    # 深度 2 处右界 x=2：裁剩 (1,0),(2,0),(2,1)，面积 0.5 / 原 2
    assert fraction == pytest.approx(0.25, abs=1e-6)
    assert len(clipped) == 3
    assert MV.face_visibility(frustum,
                              [(0, 0, -2), (1, 0, -2), (0, 1, -2)])[0] == 1.0
    assert MV.face_visibility(frustum,
                              [(0, 0, 2), (1, 0, 2), (0, 1, 2)])[0] == 0.0


def test_ndc_projection_uses_the_repo_01_convention():
    camera = MV.camera_basis(**_CAMERA)
    assert MV.project_ndc(camera, (0.0, 0.0, -2.0)) == \
        pytest.approx((0.5, 0.5))
    assert MV.project_ndc(camera, (2.0, 0.0, -2.0))[0] == \
        pytest.approx(1.0)
    assert MV.project_ndc(camera, (0.0, 2.0, -2.0))[1] == \
        pytest.approx(1.0)
    assert MV.project_ndc(camera, (0.0, 0.0, 2.0)) is None  # 机后


def _box(vertices, faces, x, z, y0, y1):
    base = len(vertices)
    vertices += [(x[0], y0, z[0]), (x[1], y0, z[0]),
                 (x[1], y0, z[1]), (x[0], y0, z[1]),
                 (x[0], y1, z[0]), (x[1], y1, z[0]),
                 (x[1], y1, z[1]), (x[0], y1, z[1])]
    v = base
    faces += [[v, v + 1, v + 2, v + 3], [v + 4, v + 7, v + 6, v + 5],
              [v, v + 4, v + 5, v + 1], [v + 1, v + 5, v + 6, v + 2],
              [v + 2, v + 6, v + 7, v + 3], [v + 3, v + 7, v + 4, v]]


def test_mesh_report_aggregates_visible_geometry_per_body_part():
    profile = DEFAULT_PROFILE
    vertices, faces = [], []
    _box(vertices, faces, (-0.12, 0.12), (-0.12, 0.12), 0.0, 0.3)      # 腿
    _box(vertices, faces, (-0.25, 0.25), (-0.25, 0.25),
         profile.hip_z + 0.01, profile.torso_top_z - 0.01)             # 躯干
    _box(vertices, faces, (-0.2, 0.2), (-0.2, 0.2),
         profile.torso_top_z + 0.01, profile.head_top_z - 0.05)        # 头
    camera = {
        "position": (0.0, 3.0, 1.2),
        "forward": MV._normalize((-0.0, -2.1, -0.6)),
        "up": (0.0, 0.0, 1.0),
        "vfov_deg": 60.0,
        "aspect": 16.0 / 9.0,
        "near": 0.5,
        "far": 20.0,
    }
    report = MV.mesh_visibility_report(vertices=vertices, faces=faces,
                                       profile=profile, **camera)
    assert report["vertices_total"] == 24
    # 相机位于 y=1.2 高度俯视：头顶两个上角（y=1.65）在视锥上方，22/24 才正确
    assert report["vertices_visible"] == 22
    assert report["visible_area_fraction"] >= 0.9
    for part in ("腿", "躯干", "头"):
        entry = report["parts"][part]
        assert entry["vertices_total"] == 8
        expected_visible = 6 if part == "头" else 8
        assert entry["vertices_visible"] == expected_visible
        if part == "腿":
            assert entry["visible_area_fraction"] == pytest.approx(1.0,
                                                                  abs=1e-6)
        assert entry["ndc_bbox"] is not None
    assert "未知" not in report["parts"]


def test_mesh_report_handles_empty_and_degenerate_input():
    report = MV.mesh_visibility_report(
        vertices=[], faces=[], **_CAMERA)
    assert report["vertices_total"] == 0
    assert report["visible_area_fraction"] == 0.0
    assert report["parts"] == {}
    # 面引用越界顶点：跳过该面，不崩
    report = MV.mesh_visibility_report(
        vertices=[(0, 0, -2)], faces=[[0, 1, 2]], **_CAMERA)
    assert report["faces_total"] == 1
    assert report["visible_area_fraction"] == 0.0


def test_render_report_carries_the_thirds_deviation_for_the_judge():
    report = {
        "vertices_visible": 3, "vertices_total": 4,
        "visible_area_fraction": 0.75,
        "parts": {
            "头": {"vertices_visible": 3, "vertices_total": 4,
                  "visible_area_fraction": 0.75,
                  "ndc_bbox": (1.0 / 3.0, 1.0 / 3.0,
                               2.0 / 3.0, 2.0 / 3.0)},
        },
    }
    text = MV.render_report(report, subject="米迦尔")
    assert "米迦尔" in text
    assert "中心九宫格偏差" in text
    assert "头：顶点 3/4" in text


def test_occlusion_oracle_marks_blocked_faces_and_render_reports_it():
    profile = DEFAULT_PROFILE
    vertices, faces = [], []
    _box(vertices, faces, (-0.2, 0.2), (-0.2, 0.2),
         profile.torso_top_z + 0.01, profile.head_top_z - 0.05)  # 头
    camera = {
        "position": (0.0, 3.0, 1.4),
        "forward": MV._normalize((0.0, -2.1, -0.3)),
        "up": (0.0, 0.0, 1.0),
        "vfov_deg": 60.0,
        "aspect": 16.0 / 9.0,
        "near": 0.5,
        "far": 20.0,
    }
    # oracle：让“头”这一组里**完整在锥内**的那一面被前景挡住
    blocked = {tuple(face) for face in faces
               if sum(vertices[i][2] for i in face) / len(face) > 0.15}

    def visible_at(point):
        centroid_key = (round(point[0], 6), round(point[1], 6),
                        round(point[2], 6))
        return all(
            tuple(round(sum(vertices[i][axis] for i in face) / len(face), 6)
                  for axis in range(3)) != centroid_key
            for face in blocked)

    report = MV.mesh_visibility_report(vertices=vertices, faces=faces,
                                       profile=profile,
                                       visible_at=visible_at, **camera)
    assert report["occluded_area_fraction"] > 0.0
    head = report["parts"]["头"]
    assert head["occluded_area_fraction"] > 0.0
    text = MV.render_report(report, subject="米迦尔",
                            occlusion_declared=False)
    assert "被遮挡面积比" in text
    assert "未声明前景遮挡" in text


def test_occluder_at_attributes_blocked_area_by_class():
    profile = DEFAULT_PROFILE
    vertices, faces = [], []
    _box(vertices, faces, (-0.2, 0.2), (-0.2, 0.2),
         profile.torso_top_z + 0.01, profile.head_top_z - 0.05)  # 头
    camera = {
        "position": (0.0, 3.0, 1.4),
        "forward": MV._normalize((0.0, -2.1, -0.3)),
        "up": (0.0, 0.0, 1.0),
        "vfov_deg": 60.0,
        "aspect": 16.0 / 9.0,
        "near": 0.5,
        "far": 20.0,
    }
    # 面重心 z>0.15 的算"环境"挡住；其余可见。两个类别各有若干面。
    def occluder_at(point):
        if point[2] > 0.15:
            return "环境"
        return None

    report = MV.mesh_visibility_report(
        vertices=vertices, faces=faces, profile=profile,
        occluder_at=occluder_at, **camera)
    classes = report["occlusion_by_class"]
    assert set(classes) == {"环境"}
    assert classes["环境"] == pytest.approx(
        report["occluded_area_fraction"], abs=1e-6)
    head = report["parts"]["头"]
    assert head["occlusion_by_class"]["环境"] == pytest.approx(
        head["occluded_area_fraction"], abs=1e-6)
    text = MV.render_report(report, subject="米迦尔",
                            occlusion_declared=False)
    assert "遮挡来源（占主体总面积比）：环境" in text
    assert "未声明前景遮挡" in text


def test_occluder_at_precedes_visible_at_and_none_is_visible():
    profile = DEFAULT_PROFILE
    vertices, faces = [], []
    _box(vertices, faces, (-0.2, 0.2), (-0.2, 0.2),
         profile.torso_top_z + 0.01, profile.head_top_z - 0.05)
    camera = {
        "position": (0.0, 3.0, 1.4),
        "forward": MV._normalize((0.0, -2.1, -0.3)),
        "up": (0.0, 0.0, 1.0),
        "vfov_deg": 60.0,
        "aspect": 16.0 / 9.0,
        "near": 0.5,
        "far": 20.0,
    }
    # visible_at 说全挡；occluder_at 说全可见 ⇒ occluder_at 优先。
    report = MV.mesh_visibility_report(
        vertices=vertices, faces=faces, profile=profile,
        visible_at=lambda point: False,
        occluder_at=lambda point: None, **camera)
    assert report["occluded_area_fraction"] == 0.0
    assert report["occlusion_by_class"] == {}


def test_occluder_classes_are_a_closed_vocabulary():
    assert MV.OCCLUDER_CLASSES == (
        "角色", "群众", "道具", "特效", "环境", "未知遮挡物")
    report = {
        "vertices_visible": 1, "vertices_total": 1,
        "visible_area_fraction": 1.0,
        "occluded_area_fraction": 0.0, "occlusion_by_class": {},
        "parts": {},
    }
    assert "遮挡来源" not in MV.render_report(
        report, subject="米迦尔", occlusion_declared=True)
