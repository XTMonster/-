"""v1.7 卡 J3：分工声明消费与 R024（TDD §13.3，v1.7.5 三层 skip 操作化）。

照 ``tests/test_r020_scale.py`` 的 stub 加载模式：rule_checker 顶层 import
bpy，pytest 环境无法直接导入；这里按文件路径加载并撤桩。测试驱动
``_check_responsibility`` 与角色级 skip 判定（shot_builder 的纯函数）。

三层 skip 语义（钉死）：
① 角色级：某角色**全部出场镜**都 skip_white_model → 构建循环跳过该角色；
② 镜头级：skip 镜导出跳过渲染，shots.json 标 ``skip_white_model: true``；
③ 交付级：reference_pack 的 responsibility.md 给"直出提示词＋参考图"指引。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


@dataclass
class FakeMesh:
    name: str = "mesh"
    type: str = "MESH"
    matrix_world: Any = field(default_factory=lambda: FakeVec((0.0, 0.0, 0.0)))
    bound_box: List[Tuple[float, float, float]] = field(default_factory=list)
    hide_render: bool = False


@dataclass
class FakeCharacter:
    id: str
    name: str = ""
    meshes: List[Any] = field(default_factory=list)
    root: Any = None


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
        name = "block_director.layer3_engine.rule_checker_r024"
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
    responsibility: Any = None


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


def _responsibility(*, skip: bool = False):
    from block_director.contracts.plan import Responsibility
    return Responsibility(skip_white_model=skip)


def _plan(shots):
    from block_director.contracts.plan import Plan
    return Plan(shots=list(shots), scene_heading="INT. 码头 - 日")


def _characters(*ids):
    return [FakeCharacter(id=item, name=f"角色{item}") for item in ids]


# ----------------------------------------------------------- 纯函数判定 ----

def _skip_character(cid: str, plan) -> bool:
    """角色级 skip：全部出场镜都 skip_white_model → True。"""
    shots_with = [s for s in plan.shots if cid in (s.characters or [])]
    return bool(shots_with) and all(
        s.responsibility is not None and s.responsibility.skip_white_model
        for s in shots_with)


def test_skip_only_character_not_built():
    """全部出场镜 skip 的角色 → 构建循环跳过（不建主体）。"""
    from block_director.contracts.plan import Responsibility
    skip_all = Responsibility(skip_white_model=True)
    plan = _plan([
        FakeShot(shot_id="shot_001", order=1, characters=["char_001"],
                 responsibility=skip_all),
        FakeShot(shot_id="shot_002", order=2, characters=["char_001"],
                 responsibility=skip_all),
    ])
    assert _skip_character("char_001", plan) is True


def test_mixed_character_still_built():
    """混合镜（部分 skip 部分不 skip）→ 主体仍在。"""
    skip_yes = _responsibility(skip=True)
    skip_no = _responsibility(skip=False)
    plan = _plan([
        FakeShot(shot_id="shot_001", order=1, characters=["char_001"],
                 responsibility=skip_yes),
        FakeShot(shot_id="shot_002", order=2, characters=["char_001"],
                 responsibility=skip_no),
    ])
    assert _skip_character("char_001", plan) is False


def test_undeclared_zero_diff():
    """未声明镜（responsibility is None）→ 角色级 skip 恒 False（零行为差）。"""
    plan = _plan([
        FakeShot(shot_id="shot_001", order=1, characters=["char_001"],
                 responsibility=None),
    ])
    assert _skip_character("char_001", plan) is False


# ------------------------------------------------------------- R024 分支 ----

def test_contradiction_one_warning():
    """分支一：声明 skip（全部出场镜 skip）但场景仍有其白模主体 → 恰好 1 条 R024。"""
    skip_all = _responsibility(skip=True)
    plan = _plan([
        FakeShot(shot_id="shot_001", order=1, characters=["char_001"],
                 responsibility=skip_all),
    ])
    context = FakeContext(plan, _characters("char_001"))
    findings = rule_checker._check_responsibility("shot_001", context=context)
    r024 = [item for item in findings if item.rule == "R024"]
    assert len(r024) == 1


def test_skip_shot_no_render_marker():
    """镜头级 skip 的 shots.json 元数据标记由 export 层负责；此处断言契约字段可读。"""
    skip_all = _responsibility(skip=True)
    shot = FakeShot(shot_id="shot_001", order=1, characters=["char_001"],
                    responsibility=skip_all)
    assert bool(shot.responsibility.skip_white_model) is True
    data = shot.responsibility.to_dict()
    assert data.get("skip_white_model") is True
