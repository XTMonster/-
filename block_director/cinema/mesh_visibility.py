"""纯层网格可见性：顶点/面 × 相机视锥 + 角色部位归属（不 import bpy）。

用户 2026-10-11 需求：算出"哪些顶点与面能被相机看见，各属于角色哪个部位"，
供默认的多模态评委（VLM 评审）拿结构化证据，而不是只有全身 AABB。

算法（教科书标准）：

* 视锥平面：由相机基（右/上/前）与 fov 直接构造六个半空间
  （等价于 Gribb–Hartmann 从视图投影矩阵抽取平面），世界系、米、Z 向上；
* 顶点分类：六平面同时满足 ``n·p + d ≥ 0`` 即在锥内；
* 面的可见面积比：Sutherland–Hodgman 逐平面裁剪，面积用
  ``0.5·|Σ p_i × p_{i+1}|``（平面多边形通用，三角/四边形都可）；
* NDC 投影：透视投影，画幅 [0,1]、(0,0) 左下（与全仓口径一致）；
* 部位归属：按冻结几何 ``cinema/anchor.py::CharacterProfile`` 的竖直带
  ——``[0, hip_z)`` 腿、``[hip_z, torso_top_z)`` 躯干、
  ``[torso_top_z, head_top_z]`` 头，带外为"未知"。

遮挡（"被前景挡住"）不在本模块：那是射线求交/光栅化问题，由下一层
（bpy ray_cast 或独立三角形求交器）补充；本模块只回答"在不在视锥内、
投影到哪"。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .anchor import DEFAULT_PROFILE, CharacterProfile
from .composition import thirds_deviation

Point = Tuple[float, float, float]
Plane = Tuple[Tuple[float, float, float], float]

PART_LEGS = "腿"
PART_TORSO = "躯干"
PART_HEAD = "头"
PART_UNKNOWN = "未知"
PART_LABELS: Tuple[str, ...] = (PART_LEGS, PART_TORSO, PART_HEAD, PART_UNKNOWN)

#: 遮挡者语义类别（面级归属的闭集）。bpy 侧把 ray_cast 命中对象折成这五类；
#: 角色/道具可带 id 后缀（``"角色:char_002"``），按完整字符串聚合。
OCCLUDER_CHARACTER = "角色"
OCCLUDER_CROWD = "群众"
OCCLUDER_PROP = "道具"
OCCLUDER_VFX = "特效"
OCCLUDER_ENVIRONMENT = "环境"
OCCLUDER_UNKNOWN = "未知遮挡物"
OCCLUDER_CLASSES: Tuple[str, ...] = (
    OCCLUDER_CHARACTER, OCCLUDER_CROWD, OCCLUDER_PROP, OCCLUDER_VFX,
    OCCLUDER_ENVIRONMENT, OCCLUDER_UNKNOWN,
)

_EPS = 1e-9


@dataclass(frozen=True)
class CameraBasis:
    """相机基：``right × up == forward``（右手系），forward 是看向方向。"""
    position: Point
    right: Tuple[float, float, float]
    up: Tuple[float, float, float]
    forward: Tuple[float, float, float]
    vfov_deg: float
    aspect: float
    near: float
    far: float

    @property
    def focal(self) -> float:
        """投影焦距 ``1/tan(vfov/2)``（NDC 单位高度的一半 = focal）。"""
        return 1.0 / math.tan(math.radians(self.vfov_deg) / 2.0)


@dataclass(frozen=True)
class Frustum:
    """六个半空间：``n·p + d ≥ 0`` 表示在锥内。"""
    planes: Tuple[Plane, ...]
    near: float
    far: float


def _dot(a, b) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _sub(a, b) -> Tuple[float, float, float]:
    return (float(a[0] - b[0]), float(a[1] - b[1]), float(a[2] - b[2]))


def _add(a, b) -> Tuple[float, float, float]:
    return (float(a[0] + b[0]), float(a[1] + b[1]), float(a[2] + b[2]))


def _scale(a, s: float) -> Tuple[float, float, float]:
    return (float(a[0] * s), float(a[1] * s), float(a[2] * s))


def _cross(a, b) -> Tuple[float, float, float]:
    return (float(a[1] * b[2] - a[2] * b[1]),
            float(a[2] * b[0] - a[0] * b[2]),
            float(a[0] * b[1] - a[1] * b[0]))


def _normalize(a) -> Tuple[float, float, float]:
    length = math.sqrt(_dot(a, a))
    if length < _EPS:
        raise ValueError("零向量不能归一（相机基退化）")
    return _scale(a, 1.0 / length)


def camera_basis(*, position: Sequence[float], forward: Sequence[float],
                 up: Sequence[float], vfov_deg: float, aspect: float,
                 near: float, far: float) -> CameraBasis:
    """世界系相机基；``forward`` 与 ``up`` 平行时抛错（不猜）。"""
    pos = (float(position[0]), float(position[1]), float(position[2]))
    f = _normalize(forward)
    u = _normalize(up)
    right = _normalize(_cross(f, u))
    true_up = _cross(right, f)
    return CameraBasis(position=pos, right=right, up=true_up, forward=f,
                       vfov_deg=float(vfov_deg), aspect=float(aspect),
                       near=float(near), far=float(far))


def _plane(normal, point) -> Plane:
    n = _normalize(normal)
    return n, -_dot(n, point)


def frustum_from_camera(*, position, forward, up, vfov_deg, aspect,
                        near, far) -> Frustum:
    """六个半空间（世界系）。深度沿 ``forward``，``near/far`` 为正。"""
    basis = camera_basis(position=position, forward=forward, up=up,
                         vfov_deg=vfov_deg, aspect=aspect, near=near, far=far)
    c = basis.position
    f, r, u = basis.forward, basis.right, basis.up
    tangent_x = math.tan(math.radians(basis.vfov_deg) / 2.0) * basis.aspect
    tangent_y = math.tan(math.radians(basis.vfov_deg) / 2.0)
    near_plane = _plane(f, _add(c, _scale(f, basis.near)))
    far_plane = _plane(_scale(f, -1.0), _add(c, _scale(f, basis.far)))
    right_plane = _plane(_sub(_scale(f, tangent_x), r), c)
    left_plane = _plane(_add(_scale(f, tangent_x), r), c)
    top_plane = _plane(_sub(_scale(f, tangent_y), u), c)
    bottom_plane = _plane(_add(_scale(f, tangent_y), u), c)
    return Frustum(planes=(near_plane, far_plane, right_plane, left_plane,
                           top_plane, bottom_plane), near=float(near),
                    far=float(far))


def vertex_in_frustum(frustum: Frustum, point: Sequence[float],
                      eps: float = _EPS) -> bool:
    """六平面同时 ``n·p + d ≥ -eps`` 即锥内（含边界）。"""
    return all(_dot(n, point) + d >= -eps for n, d in frustum.planes)


def vertices_in_frustum(frustum: Frustum,
                        points: Sequence[Sequence[float]]) -> List[bool]:
    return [vertex_in_frustum(frustum, point) for point in points]


def project_ndc(basis: CameraBasis, point: Sequence[float]
                ) -> Optional[Tuple[float, float]]:
    """世界点 → NDC [0,1]，(0,0) 左下；``depth < near`` 返回 None。"""
    delta = _sub(tuple(point), basis.position)
    z = _dot(delta, basis.forward)
    if z < basis.near - _EPS:
        return None
    x = _dot(delta, basis.right) * basis.focal / (basis.aspect * z)
    y = _dot(delta, basis.up) * basis.focal / z
    return (0.5 + 0.5 * float(x), 0.5 + 0.5 * float(y))


def clip_polygon(frustum: Frustum,
                 polygon: Sequence[Point]) -> Optional[List[Point]]:
    """Sutherland–Hodgman：对六个平面依次裁剪；空 → None。"""
    current: List[Point] = [tuple(float(v) for v in p) for p in polygon]
    if len(current) < 3:
        return None
    for normal, offset in frustum.planes:
        if not current:
            return None
        output: List[Point] = []
        previous = current[-1]
        previous_inside = _dot(normal, previous) + offset >= -_EPS
        for point in current:
            inside = _dot(normal, point) + offset >= -_EPS
            if inside != previous_inside:
                denom = _dot(normal, _sub(point, previous))
                if abs(denom) > _EPS:
                    t = -(_dot(normal, previous) + offset) / denom
                    t = min(1.0, max(0.0, t))
                    output.append(_add(previous,
                                       _scale(_sub(point, previous), t)))
            if inside:
                output.append(point)
            previous, previous_inside = point, inside
        current = output
    return current or None


def polygon_area(polygon: Sequence[Point]) -> float:
    """平面多边形的面积：``0.5·|Σ p_i × p_{i+1}|``（三角/四边形通用）。"""
    if len(polygon) < 3:
        return 0.0
    total = (0.0, 0.0, 0.0)
    for index, point in enumerate(polygon):
        total = _add(total, _cross(tuple(point), tuple(polygon[
            (index + 1) % len(polygon)])))
    return 0.5 * math.sqrt(_dot(total, total))


def face_visibility(frustum: Frustum, face: Sequence[Point]
                    ) -> Tuple[float, List[Point]]:
    """一个面的可见面积比（裁剪后面积 / 原面积）与裁剪后的多边形。"""
    original = polygon_area(face)
    clipped = clip_polygon(frustum, face)
    if not clipped:
        return 0.0, []
    if original < _EPS:
        return 0.0, []
    return min(1.0, polygon_area(clipped) / original), clipped


def part_of_point(point: Sequence[float],
                  profile: CharacterProfile = DEFAULT_PROFILE) -> str:
    """按冻结几何的竖直带判部位；带外（地下/头顶之上）＝"未知"。

    边界归属（半开区间）：``hip_z`` 归躯干（腿顶盖）、``torso_top_z`` 归
    躯干（躯干顶盖/头球南极点所在平面）；头带从 ``torso_top_z`` **以上**
    开始。
    """
    y = float(point[1])
    if 0.0 - _EPS <= y < profile.hip_z:
        return PART_LEGS
    if profile.hip_z <= y <= profile.torso_top_z + _EPS:
        return PART_TORSO
    if profile.torso_top_z < y <= profile.head_top_z + _EPS:
        return PART_HEAD
    return PART_UNKNOWN


def _face_part(face_indices: Sequence[int],
               vertex_parts: Sequence[str]) -> str:
    counts: Dict[str, int] = {}
    for index in face_indices:
        part = vertex_parts[index]
        counts[part] = counts.get(part, 0) + 1
    best = max(counts, key=lambda key: (counts[key], -PART_LABELS.index(key)))
    return best


def mesh_visibility_report(*, position, forward, up, vfov_deg, aspect,
                           near, far, vertices: Sequence[Sequence[float]],
                           faces: Sequence[Sequence[int]],
                           profile: CharacterProfile = DEFAULT_PROFILE,
                           visible_at: Optional[Callable[[Point], bool]] = None,
                           occluder_at: Optional[
                               Callable[[Point], Optional[str]]] = None,
                           ) -> Dict:
    """网格 × 相机的可见性汇总（供多模态评委的结构化读数）。

    返回：顶点可见计数与比例、面可见面积比、按部位（腿/躯干/头/未知）聚合的
    顶点可见数与面积比、每部位的可见顶点 NDC 包围盒。面引用越界顶点时该面
    按 0 面积跳过（不抛错，如实少算）。
    顶点可见数与面积比、每部位的可见顶点 NDC 包围盒。``visible_at`` 是**面级
    遮挡 oracle**（纯层不自带射线：由 bpy 侧 ``scene.ray_cast`` 注入）——给了
    就按“面重心的首交是否属于主体”标出被前景挡住的面积。``occluder_at`` 是
    更强的同源 oracle：返回 ``None`` = 可见/被主体自己挡住，返回类别字符串 =
    被该类别的面挡住（``"角色"``/``"群众"``/``"道具"``/``"特效"``/``"环境"``
    /``"未知遮挡物"``，可带 id 后缀）。两者都给时 ``occluder_at`` 优先。
    面引用越界顶点时该面按 0 面积跳过（不抛错，如实少算）。
    """
    basis = camera_basis(position=position, forward=forward, up=up,
                         vfov_deg=vfov_deg, aspect=aspect, near=near, far=far)
    frustum = frustum_from_camera(position=position, forward=forward, up=up,
                                  vfov_deg=vfov_deg, aspect=aspect,
                                  near=near, far=far)
    points = [tuple(float(v) for v in item) for item in vertices]
    inside = vertices_in_frustum(frustum, points)
    parts = [part_of_point(point, profile) for point in points]
    face_areas = [polygon_area([points[i] for i in face
                                if 0 <= i < len(points)])
                  if all(0 <= i < len(points) for i in face) else 0.0
                  for face in faces]
    total_area = sum(face_areas)

    per_part: Dict[str, Dict] = {
        label: {"vertices_total": 0, "vertices_visible": 0,
                "face_area": 0.0, "visible_area": 0.0,
                "occluded_area": 0.0,
                "occlusion_by_class": {}, "ndc_bbox": None}
        for label in PART_LABELS}
    all_classes: Dict[str, float] = {}
    for index, (part, point) in enumerate(zip(parts, points)):
        entry = per_part[part]
        entry["vertices_total"] += 1
        if inside[index]:
            entry["vertices_visible"] += 1
            ndc = project_ndc(basis, point)
            if ndc is not None:
                bbox = entry["ndc_bbox"]
                entry["ndc_bbox"] = (
                    (ndc[0], ndc[1], ndc[0], ndc[1]) if bbox is None else
                    (min(bbox[0], ndc[0]), min(bbox[1], ndc[1]),
                     max(bbox[2], ndc[0]), max(bbox[3], ndc[1])))
    for face, area in zip(faces, face_areas):
        if area <= 0.0 or not all(0 <= i < len(points) for i in face):
            continue
        part = _face_part(face, parts)
        fraction, _ = face_visibility(
            frustum, [points[i] for i in face])
        per_part[part]["face_area"] += area
        per_part[part]["visible_area"] += area * fraction
        if (visible_at is not None or occluder_at is not None) \
                and fraction > 0.0:
            centroid = tuple(sum(points[i][axis] for i in face)
                             / len(face) for axis in range(3))
            occluder: Optional[str] = None
            if occluder_at is not None:
                label = occluder_at(centroid)
                if label is not None:
                    occluder = str(label)
            elif visible_at is not None and not visible_at(centroid):
                occluder = OCCLUDER_UNKNOWN
            if occluder:
                blocked = area * fraction
                per_part[part]["occluded_area"] += blocked
                per_part[part]["occlusion_by_class"][occluder] = (
                    per_part[part]["occlusion_by_class"].get(occluder, 0.0)
                    + blocked)
                all_classes[occluder] = all_classes.get(occluder, 0.0) + blocked

    out_parts: Dict[str, Dict] = {}
    for label, entry in per_part.items():
        if entry["vertices_total"] == 0 and entry["face_area"] <= 0.0:
            continue
        out_parts[label] = {
            "vertices_total": entry["vertices_total"],
            "vertices_visible": entry["vertices_visible"],
            "visible_area_fraction": round(
                entry["visible_area"] / entry["face_area"], 6)
            if entry["face_area"] > 0.0 else 0.0,
            "occluded_area_fraction": round(
                entry["occluded_area"] / entry["face_area"], 6)
            if entry["face_area"] > 0.0 else 0.0,
            "occlusion_by_class": {
                cls: round(area / entry["face_area"], 6)
                for cls, area in entry["occlusion_by_class"].items()}
            if entry["face_area"] > 0.0 else {},
            "ndc_bbox": entry["ndc_bbox"],
        }
    visible_area = sum(entry["visible_area"] for entry in per_part.values())
    occluded_area = sum(entry["occluded_area"]
                        for entry in per_part.values())
    return {
        "vertices_total": len(points),
        "vertices_visible": sum(inside),
        "vertices_visible_ratio": round(
            sum(inside) / len(points), 6) if points else 0.0,
        "faces_total": len(faces),
        "faces_fully_visible": sum(
            1 for face in faces
            if all(0 <= i < len(points) for i in face)
            and face_visibility(frustum, [points[i] for i in face])[0]
            >= 1.0 - 1e-6),
        "visible_area_fraction": round(
            visible_area / total_area, 6) if total_area > 0.0 else 0.0,
        "occluded_area_fraction": round(
            occluded_area / total_area, 6) if total_area > 0.0 else 0.0,
        "occlusion_by_class": {
            cls: round(area / total_area, 6)
            for cls, area in sorted(
                all_classes.items(), key=lambda pair: (-pair[1], pair[0]))}
        if total_area > 0.0 else {},
        "parts": out_parts,
    }


def render_report(report: Dict, subject: str = "角色",
                  *, occlusion_declared: Optional[bool] = None) -> str:
    """把汇总折成一段中文读数，供多模态评委的提示注入。"""
    semantic = ""
    if occlusion_declared is not None:
        semantic = ("已声明前景遮挡" if occlusion_declared
                    else "未声明前景遮挡")
    lines = [f"{subject} 几何可见性（{semantic}）："
             f"可见顶点 {report['vertices_visible']}/"
             f"{report['vertices_total']}，可见面积比 "
             f"{report['visible_area_fraction']:.4f}，"
             f"被遮挡面积比 {report.get('occluded_area_fraction', 0.0):.4f}。"]
    for label in PART_LABELS:
        entry = report["parts"].get(label)
        if not entry:
            continue
        bbox = entry["ndc_bbox"]
        box_text = ("无投影" if bbox is None else
                    f"NDC x[{bbox[0]:.2f},{bbox[2]:.2f}] "
                    f"y[{bbox[1]:.2f},{bbox[3]:.2f}]")
        thirds_text = ""
        if bbox is not None:
            cx = 0.5 * (bbox[0] + bbox[2])
            cy = 0.5 * (bbox[1] + bbox[3])
            thirds_text = f"，中心九宫格偏差 {thirds_deviation(cx, cy):.3f}"
        lines.append(f"{label}：顶点 {entry['vertices_visible']}/"
                     f"{entry['vertices_total']}，可见面积比 "
                     f"{entry['visible_area_fraction']:.4f}，被遮挡面积比 "
                     f"{entry.get('occluded_area_fraction', 0.0):.4f}，"
                     f"{box_text}"
                     f"{thirds_text}。")
    by_class = report.get("occlusion_by_class") or {}
    if by_class:
        classes = "、".join(
            f"{cls} {fraction:.4f}" for cls, fraction in by_class.items())
        lines.append(f"遮挡来源（占主体总面积比）：{classes}。")
    return "\n".join(lines)


__all__ = [
    "CameraBasis", "Frustum", "camera_basis", "frustum_from_camera",
    "vertex_in_frustum", "vertices_in_frustum", "project_ndc",
    "clip_polygon", "polygon_area", "face_visibility", "part_of_point",
    "mesh_visibility_report", "render_report", "PART_LABELS",
    "OCCLUDER_CLASSES", "OCCLUDER_CHARACTER", "OCCLUDER_CROWD",
    "OCCLUDER_PROP", "OCCLUDER_VFX", "OCCLUDER_ENVIRONMENT",
    "OCCLUDER_UNKNOWN",
]
