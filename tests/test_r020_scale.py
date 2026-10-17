"""v1.7 卡 J1：R020 跨镜包围盒世界高度漂移（收窄版，TDD §13.3）。

照 ``tests/test_rules_disabled.py`` 的 stub 加载模式：rule_checker 顶层
import bpy，pytest 环境无法直接导入；这里按文件路径加载并撤桩。测试驱动
``_check_scale_drift`` 需要一个能给出 ``_character_aabb`` 的最小 context。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from block_director.contracts.audit import SkippedFinding

ROOT = Path(__file__).resolve().parents[1]


class FakeVec:
    """mathutils.Vector 的极简替身：只支持构造、索引、copy。"""

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
    """matrix_world：按当前帧读身高表缩放 bound_box 角点。

    ``heights_by_frame`` 映射 ``frame -> 身高``；模拟"同一角色在不同镜首帧
    有不同的包围盒高度"。``_check_scale_drift`` 会 frame_set 到首镜/本镜
    各自首帧再量高，因此能读到两个不同高度。
    """

    def __init__(self, heights_by_frame):
        self.heights_by_frame = heights_by_frame

    def __matmul__(self, other):
        frame = int(_BPY.context.scene.frame_current)
        scale = self.heights_by_frame.get(frame, 1.0)
        return FakeVec([float(v) * scale for v in other])


@dataclass
class FakeMesh:
    name: str = "mesh"
    type: str = "MESH"
    matrix_world: Any = field(default_factory=lambda: FakeMatrix(1.0))
    bound_box: List[Tuple[float, float, float]] = field(default_factory=list)
    hide_render: bool = False


@dataclass
class FakeCharacter:
    id: str
    name: str = ""
    meshes: List[Any] = field(default_factory=list)
    root: Any = None


def _make_mesh(box_min=(0.0, 0.0, 0.0), box_max=(1.0, 1.0, 1.8),
               heights_by_frame=None):
    mm = FakeMatrix(heights_by_frame or {})
    box = [
        (box_min[0], box_min[1], box_min[2]),
        (box_max[0], box_min[1], box_min[2]),
        (box_min[0], box_max[1], box_min[2]),
        (box_max[0], box_max[1], box_min[2]),
        (box_min[0], box_min[1], box_max[2]),
        (box_max[0], box_min[1], box_max[2]),
        (box_min[0], box_max[1], box_max[2]),
        (box_max[0], box_max[1], box_max[2]),
    ]
    return FakeMesh(matrix_world=mm, bound_box=box)


def _load_rule_checker():
    stub_names = ("bpy", "bpy_extras", "bpy_extras.object_utils", "mathutils")
    prior = {name: sys.modules.get(name) for name in stub_names}
    try:
        bpy_module = types.ModuleType("bpy")
        scene = types.SimpleNamespace(frame_current=1)

        def frame_set(frame):
            scene.frame_current = int(frame)

        scene.frame_set = frame_set
        bpy_module.context = types.SimpleNamespace(
            scene=scene,
            view_layer=types.SimpleNamespace(update=lambda: None))
        global _BPY
        _BPY = bpy_module
        sys.modules["bpy"] = bpy_module
        bpy_extras = types.ModuleType("bpy_extras")
        object_utils = types.ModuleType("bpy_extras.object_utils")
        object_utils.world_to_camera_view = lambda *args, **kwargs: (0.0, 0.0, 0.0)
        bpy_extras.object_utils = object_utils
        sys.modules["bpy_extras"] = bpy_extras
        sys.modules["bpy_extras.object_utils"] = object_utils
        mathutils = types.ModuleType("mathutils")
        mathutils.Vector = FakeVec
        sys.modules["mathutils"] = mathutils
        name = "block_director.layer3_engine.rule_checker"
        path = ROOT / "block_director" / "layer3_engine" / "rule_checker.py"
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


_BPY: Any = None
rule_checker = _load_rule_checker()


@dataclass
class FakeShot:
    shot_id: str
    order: int
    intent: str = "x"
    shot_type: str = "MS"
    duration_frames: int = 48
    characters: List[str] = field(default_factory=list)
    dialogues: List[Any] = field(default_factory=list)
    camera: Dict[str, Any] = field(default_factory=dict)


class FakeContext:
    def __init__(self, plan, characters):
        self.plan = plan
        self.characters = {ch.id: ch for ch in characters}
        self.schedule = {shot.shot_id: (1, 48) for shot in plan.shots}
        self.cameras = {}
        self.shot_types = {}
        self.axis = None
        self.spec = None
        self.current_shot_id = ""

    def character(self, character_id):
        return self.characters.get(character_id)

    def character_list(self):
        return list(self.characters.values())

    def subjects_for(self, shot_id=""):
        shot = self.shot(shot_id)
        if shot is None:
            return []
        ids = [str(item) for item in (shot.characters or [])]
        return [self.characters[item] for item in ids if item in self.characters]

    def shot(self, shot_id=""):
        key = shot_id or self.current_shot_id
        for shot in self.plan.shots:
            if shot.shot_id == key:
                return shot
        return None

    def camera_for(self, shot_id=""):
        return self.cameras.get(shot_id or self.current_shot_id)


def _two_shot_plan(character1_in_both=True):
    from block_director.contracts.plan import Plan

    first = FakeShot(
        shot_id="shot_001", order=1,
        characters=["char_001"] if character1_in_both else [])
    second = FakeShot(
        shot_id="shot_002", order=2, characters=["char_001"])
    plan = Plan(shots=[first, second], scene_heading="INT. 码头 - 日")
    return plan


def _context_with_drift(drift: float):
    """首镜首帧高 1.8m，第二镜首帧按 drift 放大（frame 1 vs frame 49）。"""
    plan = _two_shot_plan()
    heights_by_frame = {1: 1.0, 49: 1.0 + drift}
    character = FakeCharacter(
        id="char_001", name="小明",
        meshes=[_make_mesh(heights_by_frame=heights_by_frame)])
    context = FakeContext(plan, [character])
    # 首镜首帧 1，第二镜首帧 49（首镜 48 帧）。
    context.schedule = {"shot_001": (1, 48), "shot_002": (49, 96)}
    return context


def test_injected_drift_one_warning():
    context = _context_with_drift(drift=0.2)   # 1.8 * 1.2 = 2.16
    rule_checker.configure_scale_drift(0.05)
    findings = rule_checker._check_scale_drift("shot_002", context=context)
    r020 = [item for item in findings if item.rule == "R020"]
    assert len(r020) == 1
    assert "shot_001" in r020[0].message and "shot_002" in r020[0].message


def test_clean_project_zero():
    context = _context_with_drift(drift=0.0)
    rule_checker.configure_scale_drift(0.05)
    findings = rule_checker._check_scale_drift("shot_002", context=context)
    r020 = [item for item in findings if item.rule == "R020"]
    assert r020 == []


def test_first_appearance_skipped():
    """首出场镜不报（没有基线可比对）。"""
    context = _context_with_drift(drift=0.5)
    rule_checker.configure_scale_drift(0.05)
    findings = rule_checker._check_scale_drift("shot_001", context=context)
    r020 = [item for item in findings if item.rule == "R020"]
    assert r020 == []


def test_disabled_via_f1():
    """configure_rules_disabled({"R020"}) → SkippedFinding。"""
    rule_checker.configure_rules_disabled(["R020"])
    rule_checker.configure_scale_drift(0.05)
    try:
        context = _context_with_drift(drift=0.5)
        findings = rule_checker._check_scale_drift("shot_002", context=context)
        assert findings
        assert all(isinstance(item, SkippedFinding) for item in findings)
    finally:
        rule_checker.configure_rules_disabled([])
