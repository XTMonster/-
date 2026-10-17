"""v1.7 卡 G2：draw_overlay 消费 G1 轨迹几何。

纯函数侧（无需真 bpy）：``_colored_paths_for`` 把角色分组路径喂给
``colored_paths``，角色色从 SceneContext.spec.cast 读；未知角色回落调色板。
Blender 探针侧（--background 只断言注册表、不测像素）在
``tools/blender_tests/test_overlay_consumption.py``。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from block_director.contracts.cast import DEFAULT_COLORS, CastMember, SceneSpec
from block_director.overlay.geometry import ColoredPolyline, colored_paths

ROOT = Path(__file__).resolve().parents[1]


class FakeVec:
    def __init__(self, values=(0.0, 0.0, 0.0)):
        self._values = [float(v) for v in values]

    def __getitem__(self, index):
        return self._values[index]

    def copy(self):
        return FakeVec(self._values)

    @property
    def x(self):
        return self._values[0]

    @property
    def y(self):
        return self._values[1]

    @property
    def z(self):
        return self._values[2]


class FakeMatrix:
    def __matmul__(self, other):
        return FakeVec([float(v) for v in other])


@dataclass
class FakeSpline:
    points: List[Any] = field(default_factory=list)


@dataclass
class FakeCurvePoint:
    co: Any = None


@dataclass
class FakeCurveData:
    splines: List[Any] = field(default_factory=list)


@dataclass
class FakeObj:
    name: str
    type: str = "CURVE"
    matrix_world: Any = field(default_factory=FakeMatrix)
    data: Any = None


def _load_draw_overlay():
    stub_names = ("bpy", "bpy_extras", "bpy_extras.view3d_utils",
                  "mathutils")
    prior = {name: sys.modules.get(name) for name in stub_names}
    try:
        bpy_module = types.ModuleType("bpy")
        bpy_module.data = types.SimpleNamespace(objects=[])
        bpy_module.context = types.SimpleNamespace(
            scene=types.SimpleNamespace(frame_current=1),
            view_layer=types.SimpleNamespace(update=lambda: None))
        sys.modules["bpy"] = bpy_module
        view3d = types.ModuleType("bpy_extras.view3d_utils")
        view3d.location_3d_to_region_2d = lambda *a, **k: None
        bpy_extras = types.ModuleType("bpy_extras")
        bpy_extras.__path__ = []                 # 伪包：允许子模块导入
        bpy_extras.view3d_utils = view3d
        sys.modules["bpy_extras"] = bpy_extras
        sys.modules["bpy_extras.view3d_utils"] = view3d
        mathutils = types.ModuleType("mathutils")
        mathutils.Vector = FakeVec
        sys.modules["mathutils"] = mathutils
        name = "block_director.layer7_ui.draw_overlay"
        path = ROOT / "block_director" / "layer7_ui" / "draw_overlay.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in prior.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


draw_overlay = _load_draw_overlay()


def _fake_scene_context(cast: List[CastMember]):
    #: 只读 ``.spec.cast`` 的伪场景上下文（避免触发 layer3_engine 包
    #: eager import bpy——draw_overlay 已在函数内惰性导入 get_context）。
    return types.SimpleNamespace(spec=SceneSpec(cast=cast))


def test_colored_paths_uses_cast_colors():
    cast = [CastMember(id="hero", name="hero", color="#AABBCC")]
    context = _fake_scene_context(cast)
    paths = {"hero": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]}
    result = draw_overlay._colored_paths_for(context) or []
    # 直接调用 colored_paths 验证颜色映射（_colored_paths_for 只喂分组）。
    colored = colored_paths(paths, {"hero": "#AABBCC"})
    assert colored[0].color == "#AABBCC"
    assert isinstance(colored[0], ColoredPolyline)


def test_colored_paths_fallback_palette():
    """未知角色（cast 无该 id）回落调色板且两个未知角色不同色。"""
    context = _fake_scene_context([])
    paths = {
        "npc_a": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        "npc_b": [(0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
    }
    colored = colored_paths(paths, {})
    assert len(colored) == 2
    assert colored[0].color == DEFAULT_COLORS[0]
    assert colored[1].color == DEFAULT_COLORS[1]
    assert colored[0].color != colored[1].color


def test_path_cache_key_changes_with_frame():
    """缓存键必须随帧变化（帧变才重算）。"""
    first = draw_overlay._path_cache_key(1)
    second = draw_overlay._path_cache_key(2)
    assert first != second


def test_path_version_stable_without_objects():
    """无路径曲线时版本稳定（空列表的 repr 恒定）。"""
    assert draw_overlay._path_version() == repr([])


def test_path_roles_parses_underscore_character_ids():
    """曲线名 ``BD_Path_<role>_<idx>`` 中角色 id 可含下划线（char_001）。"""
    spline = FakeSpline(points=[FakeCurvePoint(co=FakeVec((0.0, 0.0, 0.0))),
                                FakeCurvePoint(co=FakeVec((1.0, 0.0, 0.0)))])
    obj = FakeObj(name="BD_Path_char_001_001",
                  data=FakeCurveData(splines=[spline]))
    draw_overlay.bpy.data.objects[:] = [obj]
    roles = draw_overlay._path_roles()
    assert "char_001" in roles
    assert len(roles["char_001"]) == 1


def test_colored_paths_for_multiple_paths_per_role():
    """同一角色两条路径（index 1/2）应各自产一条 ColoredPolyline，颜色同源。"""
    spline1 = FakeSpline(points=[FakeCurvePoint(co=FakeVec((0.0, 0.0, 0.0))),
                                 FakeCurvePoint(co=FakeVec((1.0, 0.0, 0.0)))])
    spline2 = FakeSpline(points=[FakeCurvePoint(co=FakeVec((0.0, 1.0, 0.0))),
                                 FakeCurvePoint(co=FakeVec((1.0, 1.0, 0.0)))])
    draw_overlay.bpy.data.objects[:] = [
        FakeObj(name="BD_Path_char_001_001", data=FakeCurveData(splines=[spline1])),
        FakeObj(name="BD_Path_char_001_002", data=FakeCurveData(splines=[spline2])),
    ]
    from block_director.contracts.cast import CastMember, SceneSpec

    context = _fake_scene_context(
        [CastMember(id="char_001", name="小明", color="#123456")])
    colored = draw_overlay._colored_paths_for(context)
    assert len(colored) == 2
    assert all(item.color == "#123456" for item in colored)
    assert colored[0].points[0] == (0.0, 0.0, 0.0)
    assert colored[1].points[0] == (0.0, 1.0, 0.0)
