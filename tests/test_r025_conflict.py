"""v1.7 卡 J4：R025 提示词-白模矛盾检测（TDD §13.3，默认关）。

校验层（``rule_checker``）只产**实测数据**（``measured_camera``），文本矛盾
判断归 LLM 裁决层（review 的 ``prompt_conflict`` 字段）。开关默认关 ⇒ 全链
零形状差：``_measured_camera`` 不出键、review payload 逐字节不变。

照 ``tests/test_r020_scale.py`` 的 stub 加载模式：rule_checker 顶层 import
bpy，pytest 环境无法直接导入；这里按文件路径加载并撤桩。测试驱动
``_measured_camera`` 与开关注入；driver 层的 R025 warning 消费走
``tests/test_driver_review.py`` 的 transport 模式。
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
    """mathutils.Vector 的极简替身：支持构造、索引、copy、matmul。"""

    def __init__(self, values=(0.0, 0.0, 0.0)):
        self._values = [float(v) for v in values]

    def __getitem__(self, index):
        return self._values[index]

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(self._values)

    def copy(self):
        return FakeVec(self._values)

    def __matmul__(self, other):
        #: 只做分量乘法（参数朝向量/右向量都形如 (x,y,z)）。
        return FakeVec([self._values[i] * float(other[i])
                        for i in range(min(len(self._values), len(other)))])

    def __add__(self, other):
        return FakeVec([self._values[i] + float(other[i])
                        for i in range(len(self._values))])

    def __sub__(self, other):
        return FakeVec([self._values[i] - float(other[i])
                        for i in range(len(self._values))])

    @property
    def x(self):
        return self._values[0]

    @property
    def y(self):
        return self._values[1]

    @property
    def z(self):
        return self._values[2]


class FakeCamera:
    """matrix_world 只提供 translation；to_quaternion 给单位四元数。"""

    def __init__(self, position=(0.0, -5.0, 1.6)):
        self.matrix_world = types.SimpleNamespace(
            translation=FakeVec(position),
            to_quaternion=self.to_quaternion)

    def to_quaternion(self):
        return FakeVec((1.0, 0.0, 0.0, 0.0))


@dataclass
class FakeCharacter:
    id: str
    name: str = ""
    meshes: List[Any] = field(default_factory=list)
    root: Any = None


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


def _load_rule_checker():
    stub_names = ("bpy", "bpy_extras", "bpy_extras.object_utils", "mathutils")
    prior = {name: sys.modules.get(name) for name in stub_names}
    #: ``_measured_camera`` 的函数内 ``from .character_system...`` 会触发真实
    #: ``layer3_engine/__init__.py``（bpy 依赖链），pytest 环境必炸。这里
    #: 预注册一个假 ``character_system`` 包（真实 Blender 运行时不受影响——
    #: 那里包已初始化、get_facing 正常）。
    prior.setdefault("block_director.layer3_engine", None)
    stub_pkgs = ("block_director.layer3_engine.character_system",
                 "block_director.layer3_engine.character_system.character_factory")
    for name in stub_pkgs:
        prior[name] = sys.modules.get(name)
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
        layer3_pkg = types.ModuleType("block_director.layer3_engine")
        layer3_pkg.__path__ = []        # 让 ``import`` 认为这是已初始化包
        sys.modules[layer3_pkg.__name__] = layer3_pkg
        cs_pkg = types.ModuleType(
            "block_director.layer3_engine.character_system")
        cf_mod = types.ModuleType(
            "block_director.layer3_engine.character_system.character_factory")

        def _fake_get_facing(character):
            return (0.0, 1.0, 0.0)

        cf_mod.get_facing = _fake_get_facing
        cs_pkg.character_factory = cf_mod
        sys.modules[cs_pkg.__name__] = cs_pkg
        sys.modules[cf_mod.__name__] = cf_mod
        name = "block_director.layer3_engine.rule_checker_r025"
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


def _plan_with_movement(movement: str = "track_right", amount: float = 3.0):
    from block_director.contracts.plan import Plan

    shot = FakeShot(
        shot_id="shot_001", order=1, characters=["char_001"],
        camera={"movements": [
            {"type": movement, "amount": amount,
             "start_frame": 1, "end_frame": 48}]})
    plan = Plan(shots=[shot], scene_heading="INT. 码头 - 日")
    return plan


def _context():
    plan = _plan_with_movement()
    character = FakeCharacter(id="char_001", name="小明",
                              root=types.SimpleNamespace(
                                  matrix_world=types.SimpleNamespace(
                                      translation=FakeVec((0.0, 0.0, 0.0)))))
    context = FakeContext(plan, [character])
    context.cameras = {"shot_001": FakeCamera(position=(0.0, -5.0, 1.6))}
    return context


def test_disabled_no_measured_key():
    """默认关：_measured_camera 返回 None（零形状差，不出键）。"""
    rule_checker.configure_prompt_conflict_check(False)
    try:
        context = _context()
        assert rule_checker._measured_camera("shot_001", context=context) is None
    finally:
        rule_checker.configure_prompt_conflict_check(False)


def test_measured_data_in_audit():
    """开关开：_measured_camera 产出 narration/start/end。"""
    rule_checker.configure_prompt_conflict_check(True)
    try:
        context = _context()
        measured = rule_checker._measured_camera(
            "shot_001", context=context, facing=(0.0, 1.0, 0.0))
        assert measured is not None
        assert "narration" in measured and "start" in measured and "end" in measured
        assert isinstance(measured["narration"], str) and measured["narration"]
        assert isinstance(measured["start"], str) and isinstance(measured["end"], str)
    finally:
        rule_checker.configure_prompt_conflict_check(False)


def test_no_movement_zero():
    """开关开但本镜无采样：返回 None（零误报）。"""
    rule_checker.configure_prompt_conflict_check(True)
    try:
        from block_director.contracts.plan import Plan
        shot = FakeShot(shot_id="shot_001", order=1, characters=["char_001"])
        plan = Plan(shots=[shot], scene_heading="INT. 码头 - 日")
        character = FakeCharacter(id="char_001", name="小明",
                                  root=types.SimpleNamespace(
                                      matrix_world=types.SimpleNamespace(
                                          translation=FakeVec((0.0, 0.0, 0.0)))))
        context = FakeContext(plan, [character])
        context.cameras = {"shot_001": FakeCamera(position=(0.0, -5.0, 1.6))}
        assert rule_checker._measured_camera(
            "shot_001", context=context, facing=(0.0, 1.0, 0.0)) is None
    finally:
        rule_checker.configure_prompt_conflict_check(False)


# ----------------------------------------------------- driver 层 R025 消费 ----

def test_driver_r025_warning_on_prompt_conflict():
    """R025：LLM 在 submit_review 里报 prompt_conflict → 恰好 1 条 R025 审计事件。

    走 ``tests/test_driver_review.py`` 的 transport 模式：REVIEW 回合返回带
    ``prompt_conflict`` 的结论，驱动器的 ``_finish_review`` 落一条 R025
    warning（只记录，不改通过与否）。
    """
    import json

    from block_director.contracts.audit import AuditResult
    from block_director.contracts.config import AppConfig
    from block_director.contracts.enums import Purpose
    from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.states import DriverState
    from block_director.layer6_audit.audit_logger import AuditLogger

    from test_driver import InlineThread
    from test_driver_builder import RecordingBuilder, SCRIPT
    from test_driver_guards import _registry
    from test_driver_repair import FakeAuditor

    class ConflictReviewTransport:
        """计划/修复照旧（复用 RepairingTransport 逻辑），REVIEW 带矛盾。"""

        def __init__(self):
            self.payloads = []
            self.chat_calls = 0
            self._editor_index = 0

        def chat(self, payload, timeout=120.0):
            self.payloads.append(payload)
            if payload.purpose is Purpose.REVIEW:
                self.chat_calls += 1
                arguments = json.dumps({
                    "verdict": "ok",
                    "notes": "通过但发现矛盾",
                    "prompt_conflict": "文字说从左到右，实测是从右到左",
                }, ensure_ascii=False)
                return ChatReply(tool_calls=[ToolCall(
                    id=f"review_{self.chat_calls}",
                    function=FunctionCall(name="submit_review",
                                          arguments=arguments))])
            from test_driver_repair import RepairingTransport
            return RepairingTransport().chat(payload, timeout)

    config = AppConfig()
    config.orchestration.self_review = True
    config.audit.human_gate_on_plan = False
    transport = ConflictReviewTransport()
    auditor = FakeAuditor([AuditResult(passed=True, target="shot_001")])
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, registry=_registry(),
                          builder=RecordingBuilder(),
                          thread_factory=InlineThread, config=config,
                          auditor=auditor)
    assert driver.run_to_completion() is DriverState.DONE

    events = [e for e in driver.audit.recent() if e.kind == "R025"]
    assert len(events) == 1
    assert events[0].level == "warning"
    assert "从左到右" in events[0].message


def test_driver_no_r025_when_enabled_off():
    """默认关（不传 prompt_conflict_check）：无矛盾 → 0 条 R025。"""
    import json

    from block_director.contracts.audit import AuditResult
    from block_director.contracts.config import AppConfig
    from block_director.contracts.enums import Purpose
    from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.states import DriverState
    from block_director.layer6_audit.audit_logger import AuditLogger

    from test_driver import InlineThread
    from test_driver_builder import RecordingBuilder, SCRIPT
    from test_driver_guards import _registry
    from test_driver_repair import FakeAuditor

    class CleanReviewTransport:
        def __init__(self):
            self.payloads = []
            self.chat_calls = 0
            self._editor_index = 0

        def chat(self, payload, timeout=120.0):
            self.payloads.append(payload)
            if payload.purpose is Purpose.REVIEW:
                self.chat_calls += 1
                arguments = json.dumps({"verdict": "ok", "notes": "通过"},
                                       ensure_ascii=False)
                return ChatReply(tool_calls=[ToolCall(
                    id=f"review_{self.chat_calls}",
                    function=FunctionCall(name="submit_review",
                                          arguments=arguments))])
            from test_driver_repair import RepairingTransport
            return RepairingTransport().chat(payload, timeout)

    config = AppConfig()
    config.orchestration.self_review = True
    config.audit.human_gate_on_plan = False
    transport = CleanReviewTransport()
    auditor = FakeAuditor([AuditResult(passed=True, target="shot_001")])
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, registry=_registry(),
                          builder=RecordingBuilder(),
                          thread_factory=InlineThread, config=config,
                          auditor=auditor)
    assert driver.run_to_completion() is DriverState.DONE
    assert not [e for e in driver.audit.recent() if e.kind == "R025"]
