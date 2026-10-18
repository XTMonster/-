"""场景空间数据摘要（vlm-feedback 卡 V11；纯层，禁止 import bpy）。

把 bpy 侧 :func:`layer3_engine.frustum_sampler.sample_spatial` 采到的
``SpatialFrame`` 序列折成多模态模型可读的**几何测量事实**：

* 元素 vs 相机：相机坐标系深度（沿前向距离）、水平/竖直偏角、视锥内外、
  NDC 中心；角色另算**朝向相对相机**的夹角（0°=正对镜头，90°=侧身，
  180°=背对）与**画面朝向**（朝画左/画右/无）；
* 元素之间（角色两两、角色 vs 道具/墙）：3D 与水平距离、B 相对 A 朝向的
  方位角（A 是否面向 B）、谁离相机更近（深度序）、画面左右序；
* 碰撞箱：每对元素的 AABB 间隙 ``gap``（各轴分离量的最大值；三轴都重叠时
  为负的最小重叠量＝穿透深度）。``gap<0`` ⇒ ``penetrating``；
  ``0<=gap<collision_margin`` ⇒ ``too_close``；其余 ``clear``。
  ``collision_margin`` 的单一真源是这里的 :data:`COLLISION_MARGIN`
  （``rule_checker`` 从本模块导入，数值 0.2 不变）；
* 文本渲染（优先级：碰撞/穿透 > 相机参数行 > 每角色一行 > 关系行；整行
  追加、超长整行舍弃）与首/中/末三帧的画面摘要（``framing_digest``）。

坐标约定：世界系米、Z 向上；NDC [0,1]，(0,0) 左下；角度一律度。输出浮点
统一 3 位小数、全部可 ``json.dumps``。NDC 中心由针孔相机公式推导，等价于
``world_to_camera_view`` 在镜头 shift=0 时的结果（构建器默认相机 shift=0）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .composition import SubjectBox
from .frustum_metrics import HEAD_FRACTION, FrameSample, head_box, safe_area_bounds

Vec = Tuple[float, float, float]

#: 碰撞告警/摘要用的 AABB 间隙阈值（米）。单一真源：``rule_checker`` 从本模块
#: 导入，数值与 v1.2 §11.1 R002 的 0.2 一字不差。
COLLISION_MARGIN: float = 0.2

#: 视锥边界判定的角度容差（度）。
ANGLE_EPS_DEG: float = 1e-6
#: 画面朝向分类的点积容差（无量纲）。
FACING_EPS: float = 1e-6


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _length(a: Vec) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vec) -> Vec:
    length = _length(a)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / length, a[1] / length, a[2] / length)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _r3(value: Any) -> Any:
    """递归把浮点折成 3 位小数（JSON 友好，NaN/Inf 不进）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {key: _r3(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_r3(item) for item in value]
    return value


# --------------------------------------------------------------------------- #
# 数据 DTO（bpy 侧只填数，serde 往返见 tests/test_scene_digest.py）
# --------------------------------------------------------------------------- #
@dataclass
class SpatialCamera:
    """一帧的相机模型（透视）。``forward/up`` 为单位向量。"""
    position: Vec
    forward: Vec
    up: Vec
    lens_mm: float
    sensor_width: float
    sensor_height: float
    sensor_fit: str
    render_width: int
    render_height: int
    #: 完整旋转（空间理解/设计快照：四元数 + 欧拉 + 顺序）。None = 未采样。
    rotation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position": list(self.position),
            "forward": list(self.forward),
            "up": list(self.up),
            "lens_mm": self.lens_mm,
            "sensor_width": self.sensor_width,
            "sensor_height": self.sensor_height,
            "sensor_fit": self.sensor_fit,
            "render_width": self.render_width,
            "render_height": self.render_height,
            "rotation": (dict(self.rotation)
                         if isinstance(self.rotation, dict) else None),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpatialCamera":
        rotation = data.get("rotation")
        return cls(
            position=tuple(data["position"]),
            forward=tuple(data["forward"]),
            up=tuple(data["up"]),
            lens_mm=float(data["lens_mm"]),
            sensor_width=float(data["sensor_width"]),
            sensor_height=float(data["sensor_height"]),
            sensor_fit=str(data["sensor_fit"]),
            render_width=int(data["render_width"]),
            render_height=int(data["render_height"]),
            rotation=(dict(rotation) if rotation is not None else None),
        )


@dataclass
class SpatialElement:
    """一帧里的一个元素（角色/道具/墙）。``facing`` 只有角色有。

    ``rotation`` / ``motion`` / ``gaze`` 是空间理解/设计快照新增的**可空**字段
    （旧字段全保留、None 时序列化输出键值为 None，与 ``facing`` 同口径）：

    * ``rotation``：``{"quaternion": [w,x,y,z], "euler": [x,y,z],
      "order": "XYZ"}``；
    * ``motion``：设计/观测两侧形状由快照契约定义，这里只做透传 dict；
    * ``gaze``：只有角色有，``{"target_id": str|None, "direction": [x,y,z]}``。
    """
    id: str
    kind: str                          # character / prop / wall
    aabb_min: Vec
    aabb_max: Vec
    center: Vec
    facing: Optional[Vec] = None
    rotation: Optional[Dict[str, Any]] = None
    motion: Optional[Dict[str, Any]] = None
    gaze: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "aabb_min": list(self.aabb_min),
            "aabb_max": list(self.aabb_max),
            "center": list(self.center),
            "facing": list(self.facing) if self.facing is not None else None,
            "rotation": (dict(self.rotation)
                         if isinstance(self.rotation, dict) else None),
            "motion": (dict(self.motion)
                       if isinstance(self.motion, dict) else None),
            "gaze": (dict(self.gaze)
                     if isinstance(self.gaze, dict) else None),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpatialElement":
        facing = data.get("facing")
        rotation = data.get("rotation")
        motion = data.get("motion")
        gaze = data.get("gaze")
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            aabb_min=tuple(data["aabb_min"]),
            aabb_max=tuple(data["aabb_max"]),
            center=tuple(data["center"]),
            facing=tuple(facing) if facing is not None else None,
            rotation=(dict(rotation) if rotation is not None else None),
            motion=(dict(motion) if motion is not None else None),
            gaze=(dict(gaze) if gaze is not None else None),
        )


@dataclass
class SpatialFrame:
    """一帧的相机 + 元素集合。"""
    frame: int
    shot_id: str
    camera: SpatialCamera
    elements: List[SpatialElement] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame,
            "shot_id": self.shot_id,
            "camera": self.camera.to_dict(),
            "elements": [element.to_dict() for element in self.elements],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpatialFrame":
        return cls(
            frame=int(data["frame"]),
            shot_id=str(data["shot_id"]),
            camera=SpatialCamera.from_dict(data["camera"]),
            elements=[SpatialElement.from_dict(item)
                      for item in data["elements"]],
        )


# --------------------------------------------------------------------------- #
# 几何事实
# --------------------------------------------------------------------------- #
def camera_fov_degrees(camera: SpatialCamera) -> Tuple[float, float]:
    """透视相机的 ``(水平视场角, 竖直视场角)``（度）。

    与 Blender 口径一致：``AUTO``/``HORIZONTAL`` 以 sensor_width 定水平视场角，
    ``VERTICAL`` 以 sensor_height 定竖直视场角；另一轴由渲染宽高比推出。
    """
    lens = float(camera.lens_mm)
    width = float(camera.sensor_width)
    height = float(camera.sensor_height)
    render_w = int(camera.render_width)
    render_h = int(camera.render_height)
    if lens <= 0.0 or width <= 0.0 or height <= 0.0:
        raise ValueError(
            f"非法相机参数：lens={lens} sensor={width}x{height}，必须为正数")
    if render_w <= 0 or render_h <= 0:
        raise ValueError(
            f"非法渲染分辨率：{render_w}x{render_h}，必须为正整数")
    aspect = float(render_w) / float(render_h)
    if str(camera.sensor_fit or "AUTO").upper() == "VERTICAL":
        vertical = 2.0 * math.degrees(math.atan2(height, 2.0 * lens))
        horizontal = 2.0 * math.degrees(
            math.atan2(height * aspect, 2.0 * lens))
    else:                                # AUTO 与 HORIZONTAL 同宽基准
        horizontal = 2.0 * math.degrees(math.atan2(width, 2.0 * lens))
        vertical = 2.0 * math.degrees(
            math.atan2(width / aspect, 2.0 * lens))
    return horizontal, vertical


def thirds_cell(x: float, y: float) -> str:
    """九宫格格位（``top_left`` … ``bottom_right``）；出画坐标夹回画面。"""
    xc = _clamp(float(x), 0.0, 1.0)
    yc = _clamp(float(y), 0.0, 1.0)
    col = "left" if xc < 1.0 / 3.0 else ("center" if xc < 2.0 / 3.0
                                          else "right")
    row = "bottom" if yc < 1.0 / 3.0 else ("middle" if yc < 2.0 / 3.0
                                            else "top")
    return f"{row}_{col}"


def aabb_gap(a_min: Vec, a_max: Vec, b_min: Vec, b_max: Vec) -> float:
    """两 AABB 的间隙：正=分离距离，0=接触，负=三轴全重叠时的 -穿透深度。"""
    separations = [max(a_min[i] - b_max[i], b_min[i] - a_max[i])
                   for i in range(3)]
    return max(separations)


def collision_state(gap: float, margin: float) -> str:
    """间隙 → 三态：``penetrating`` / ``too_close`` / ``clear``。"""
    if gap < 0.0:
        return "penetrating"
    if gap < margin:
        return "too_close"
    return "clear"


def _ndc_from_angles(h_deg: float, v_deg: float, hf: float,
                     vf: float) -> Tuple[float, float]:
    """偏角 → NDC 中心（针孔公式；shift=0 时与 ``world_to_camera_view`` 同值）。"""
    x, y = 0.5, 0.5
    half_h = math.tan(math.radians(hf / 2.0))
    if half_h > 0.0 and math.isfinite(half_h):
        x = 0.5 + math.tan(math.radians(h_deg)) / (2.0 * half_h)
    half_v = math.tan(math.radians(vf / 2.0))
    if half_v > 0.0 and math.isfinite(half_v):
        y = 0.5 + math.tan(math.radians(v_deg)) / (2.0 * half_v)
    return x, y


def _screen_facing(facing: Vec, right: Vec) -> str:
    projection = _dot(_normalize(facing), right)
    if projection > FACING_EPS:
        return "right"
    if projection < -FACING_EPS:
        return "left"
    return "none"


def _pair_rows(elements: List[SpatialElement]
               ) -> List[Tuple[int, int]]:
    """配对：角色两两 + 角色 vs 道具/墙（道具×道具、道具×墙不配）。"""
    characters = [index for index, element in enumerate(elements)
                  if element.kind == "character"]
    others = [index for index, element in enumerate(elements)
              if element.kind in ("prop", "wall")]
    rows: List[Tuple[int, int]] = []
    for first in range(len(characters)):
        for second in range(first + 1, len(characters)):
            rows.append((characters[first], characters[second]))
    for character in characters:
        for other in others:
            rows.append((character, other))
    return rows


def spatial_digest(frames: Sequence[SpatialFrame], *,
                   collision_margin: float) -> Dict[str, Any]:
    """逐帧折几何测量事实；输出可 ``json.dumps``，浮点 3 位。"""
    margin = float(collision_margin)
    out_frames: List[Dict[str, Any]] = []
    for spatial_frame in frames:
        camera = spatial_frame.camera
        hf, vf = camera_fov_degrees(camera)
        position = camera.position
        forward = _normalize(camera.forward)
        up = _normalize(camera.up)
        right = _normalize(_cross(forward, up))

        elements: List[Dict[str, Any]] = []
        depths: Dict[str, float] = {}
        ndc_x: Dict[str, float] = {}
        for element in spatial_frame.elements:
            center = element.center
            to_element = _sub(center, position)
            depth = _dot(to_element, forward)
            h_deg = math.degrees(
                math.atan2(_dot(to_element, right), _dot(to_element, forward)))
            v_deg = math.degrees(
                math.atan2(_dot(to_element, up), _dot(to_element, forward)))
            in_frustum = (depth > 0.0
                          and abs(h_deg) <= hf / 2.0 + ANGLE_EPS_DEG
                          and abs(v_deg) <= vf / 2.0 + ANGLE_EPS_DEG)
            ndc = _ndc_from_angles(h_deg, v_deg, hf, vf)
            entry: Dict[str, Any] = {
                "id": element.id,
                "kind": element.kind,
                "aabb": {"min": element.aabb_min,
                         "max": element.aabb_max},
                "center": center,
                "depth_m": depth,
                "off_axis_deg": {"horizontal": h_deg, "vertical": v_deg},
                "in_frustum": in_frustum,
                "ndc_center": [ndc[0], ndc[1]],
                "facing_vs_camera_deg": None,
                "screen_facing": None,
            }
            if element.kind == "character" and element.facing is not None:
                facing = _normalize(element.facing)
                if _length(facing) > 1e-12:
                    to_camera = _normalize(_sub(position, center))
                    cosine = _clamp(_dot(facing, to_camera), -1.0, 1.0)
                    entry["facing_vs_camera_deg"] = math.degrees(
                        math.acos(cosine))
                    entry["screen_facing"] = _screen_facing(facing, right)
            elements.append(entry)
            depths[element.id] = depth
            ndc_x[element.id] = ndc[0]

        pairs: List[Dict[str, Any]] = []
        for first, second in _pair_rows(spatial_frame.elements):
            a = spatial_frame.elements[first]
            b = spatial_frame.elements[second]
            delta = _sub(b.center, a.center)
            distance_3d = _length(delta)
            distance_horizontal = math.hypot(delta[0], delta[1])
            azimuth: Optional[float] = None
            a_faces_b: Optional[bool] = None
            if a.facing is not None:
                facing = _normalize(a.facing)
                if _length(facing) > 1e-12 and distance_3d > 1e-12:
                    cosine = _clamp(_dot(facing, delta) / distance_3d,
                                    -1.0, 1.0)
                    azimuth = math.degrees(math.acos(cosine))
                    a_faces_b = azimuth <= 90.0 + ANGLE_EPS_DEG
            depth_a, depth_b = depths[a.id], depths[b.id]
            if depth_a <= depth_b:
                depth_order = [a.id, b.id]
            else:
                depth_order = [b.id, a.id]
            if ndc_x[a.id] <= ndc_x[b.id]:
                screen_order = [a.id, b.id]
            else:
                screen_order = [b.id, a.id]
            gap = aabb_gap(a.aabb_min, a.aabb_max, b.aabb_min, b.aabb_max)
            pairs.append({
                "a": a.id, "b": b.id,
                "distance_3d_m": distance_3d,
                "distance_horizontal_m": distance_horizontal,
                "azimuth_deg": azimuth,
                "a_faces_b": a_faces_b,
                "depth_order": depth_order,
                "screen_order": screen_order,
                "gap_m": gap,
                "state": collision_state(gap, margin),
            })

        out_frames.append({
            "frame": spatial_frame.frame,
            "camera": {
                "position": position,
                "forward": forward,
                "up": up,
                "lens_mm": camera.lens_mm,
                "sensor": {"width": camera.sensor_width,
                           "height": camera.sensor_height,
                           "fit": camera.sensor_fit},
                "render": {"width": camera.render_width,
                           "height": camera.render_height},
                "fov_degrees": {"horizontal": hf, "vertical": vf},
            },
            "elements": elements,
            "pairs": pairs,
        })

    return _r3({
        "conventions": {
            "world": "meters, Z-up",
            "ndc": "[0,1], (0,0)=bottom-left",
            "angles": "degrees",
            "float_places": 3,
        },
        "frames": out_frames,
    })


_STATE_LABELS = {"penetrating": "穿透", "too_close": "过近"}


def render_spatial_digest(digest: Dict[str, Any], *,
                          max_chars: int = 1200) -> str:
    """把摘要渲染成提示文本。优先级：碰撞/穿透 > 相机参数行 > 每角色一行 >
    关系行；整行追加，放不下的整行舍弃（绝不截半行）。"""
    if max_chars <= 0:
        return ""
    tiers: List[List[str]] = [[], [], [], []]
    for frame in digest.get("frames", []):
        frame_no = frame["frame"]
        for pair in frame["pairs"]:
            if pair["state"] in _STATE_LABELS:
                tiers[0].append(
                    f"[帧{frame_no}] 碰撞 {pair['a']}-{pair['b']}: "
                    f"gap={pair['gap_m']}m, "
                    f"状态={_STATE_LABELS[pair['state']]}")
        camera = frame["camera"]
        position = camera["position"]
        tiers[1].append(
            f"[帧{frame_no}] 相机 pos=({position[0]},{position[1]},"
            f"{position[2]}) fov={camera['fov_degrees']['horizontal']}°x"
            f"{camera['fov_degrees']['vertical']}° "
            f"lens={camera['lens_mm']}mm")
        for element in frame["elements"]:
            if element["kind"] != "character":
                continue
            facing = element["facing_vs_camera_deg"]
            tiers[2].append(
                f"[帧{frame_no}] {element['id']}: depth={element['depth_m']}m "
                f"h={element['off_axis_deg']['horizontal']}° "
                f"v={element['off_axis_deg']['vertical']}° "
                f"ndc=({element['ndc_center'][0]},{element['ndc_center'][1]}) "
                f"facing_cam={facing}° screen={element['screen_facing']}")
        for pair in frame["pairs"]:
            azimuth = pair["azimuth_deg"]
            tiers[3].append(
                f"[帧{frame_no}] {pair['a']}-{pair['b']}: "
                f"3d={pair['distance_3d_m']}m "
                f"平面={pair['distance_horizontal_m']}m azimuth={azimuth}° "
                f"depth={pair['depth_order']} screen={pair['screen_order']}")

    lines: List[str] = []
    for tier in tiers:
        for line in tier:
            current = len("\n".join(lines)) if lines else 0
            cost = len(line) + (1 if lines else 0)
            if current + cost <= max_chars:
                lines.append(line)
    return "\n".join(lines)


def framing_digest(samples: Sequence[FrameSample], *, safe_action: float,
                   safe_title: float) -> Dict[str, Any]:
    """首/中/末三帧的画面摘要（每主体）。

    安全区判定用**头部盒**（``in_action_safe``/``in_title_safe``＝头盒完全
    落在动作/字幕安全区内）；``in_frame``＝全身盒至少一部分在画内。
    """
    grouped: Dict[str, List[FrameSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.subject, []).append(sample)
    action_low, action_high = safe_area_bounds(safe_action)
    title_low, title_high = safe_area_bounds(safe_title)
    subjects: Dict[str, List[Dict[str, Any]]] = {}
    for subject in sorted(grouped):
        seq = sorted(grouped[subject], key=lambda sample: sample.frame)
        picked: List[FrameSample] = []
        seen = set()
        for sample in (seq[0], seq[len(seq) // 2], seq[-1]):
            if sample.frame not in seen:
                seen.add(sample.frame)
                picked.append(sample)
        records: List[Dict[str, Any]] = []
        for sample in picked:
            box: SubjectBox = sample.box
            head_bottom, head_top = head_box(box)
            in_action = (action_low <= box.left and box.right <= action_high
                         and action_low <= head_bottom
                         and head_top <= action_high)
            in_title = (title_low <= box.left and box.right <= title_high
                        and title_low <= head_bottom and head_top <= title_high)
            records.append({
                "frame": sample.frame,
                "ndc_box": {"left": box.left, "right": box.right,
                            "top": box.top, "bottom": box.bottom},
                "head_box": {"left": box.left, "right": box.right,
                             "top": head_top, "bottom": head_bottom},
                "center": [box.center_x, box.center_y],
                "thirds": thirds_cell(box.center_x, box.center_y),
                "screen_height_ratio": box.height,
                "visible_ratio": sample.visible_ratio,
                "behind_camera": bool(sample.behind_camera),
                "in_frame": box.inside_ratio() > 0.0,
                "in_action_safe": in_action,
                "in_title_safe": in_title,
            })
        subjects[subject] = _r3(records)
    return {"subjects": subjects}


def scene_digest(samples: Sequence[FrameSample],
                 frames: Sequence[SpatialFrame], *, safe_action: float,
                 safe_title: float, collision_margin: float
                 ) -> Dict[str, Any]:
    """画面摘要 + 空间摘要合并为一个 ``scene_digest``。"""
    return {
        "framing": framing_digest(samples, safe_action=safe_action,
                                  safe_title=safe_title),
        "spatial": spatial_digest(frames,
                                  collision_margin=collision_margin),
    }
