"""v1.7 卡 J2：R021 / R022 / R023 相机运动 warning（TDD §13.3）。

三条规则共用 ``movement_samples`` 产物（与 I2 同源）：

- R021：相邻采样段航向角差 > 30°（对齐 R010 词汇）记 1 次突变；
  突变数 + 该镜声明运镜条目数 ≥ ``guard.compound_motion_max`` → 建议拆镜；
- R022：采样没有 up 分量，用右向量等价判定（视线 × 天顶）；视线与天顶夹角
  < 5° 的退化帧跳过；投影符号翻转 → 告警；
- R023：位置二阶差分 × fps²（**单位 m/s²**）峰值超 ``guard.cam_accel_max``。

照 ``tests/test_r020_scale.py`` 的 stub 加载模式：rule_checker 顶层 import
bpy，pytest 环境无法直接导入；这里按文件路径加载并撤桩。纯计算函数直接
喂构造好的 samples；``_check_*`` 系列用 monkeypatch 替换采样源，避免依赖
Blender 场景对象。
"""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import pytest

from block_director.contracts.audit import SkippedFinding
from block_director.contracts.config import AppConfig
from block_director.contracts.rule_catalog import RULES

ROOT = Path(__file__).resolve().parents[1]


class FakeVec:
    """mathutils.Vector 的极简替身（只支撑 rule_checker 顶层导入）。"""

    def __init__(self, values=(0.0, 0.0, 0.0)):
        self._values = [float(v) for v in values]

    def __getitem__(self, index):
        return self._values[index]

    def copy(self):
        return FakeVec(self._values)


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


rule_checker = _load_rule_checker()


@dataclass
class FakeShot:
    shot_id: str
    camera: Dict[str, Any] = field(default_factory=dict)


class FakeContext:
    """只支撑 J2 的 ``_check_*``：shot 查找与 subjects_for 空集。"""

    def __init__(self, shots: List[FakeShot]):
        self.plan = types.SimpleNamespace(shots=shots)

    def shot(self, shot_id):
        for shot in self.plan.shots:
            if shot.shot_id == shot_id:
                return shot
        return None

    def subjects_for(self, shot_id=""):
        return []


def _samples_with_positions(positions):
    """把一组 3D 位置转成 ``[{frame, position, look_at}]`` 采样（look_at 恒定）。"""
    return [{"frame": 1 + index * 10, "position": tuple(pos), "look_at": (0.0, 0.0, 0.0)}
            for index, pos in enumerate(positions)]


def _stub_samples(samples):
    rule_checker._camera_motion_samples = lambda shot_id, context=None: samples


def test_r021_turn_detected():
    """已知折线（90° 单次突变）＋ 2 条声明运镜 → 恰好 1 条 R021 warning。"""
    shot = FakeShot(shot_id="shot_001",
                    camera={"movements": [{"type": "track_right"},
                                          {"type": "track_left"}]})
    context = FakeContext([shot])
    samples = _samples_with_positions([(0.0, 0.0, 0.0),
                                       (2.0, 0.0, 0.0),
                                       (2.0, 2.0, 0.0)])
    _stub_samples(samples)
    rule_checker.configure_camera_limits(8.0, compound_max=2, fps=24)
    rule_checker.configure_rules_disabled([])
    findings = rule_checker._check_motion_complexity("shot_001", context=context)
    r021 = [item for item in findings if item.rule == "R021"]
    assert len(r021) == 1
    assert "拆镜" in r021[0].message
    # 单条直线运动（declared=1，突变 0）不触发
    straight = FakeShot(shot_id="shot_002",
                        camera={"movements": [{"type": "track_right"}]})
    clean_ctx = FakeContext([straight])
    _stub_samples(_samples_with_positions([(0.0, 0.0, 0.0),
                                           (1.0, 0.0, 0.0),
                                           (2.0, 0.0, 0.0)]))
    assert rule_checker._check_motion_complexity("shot_002", context=clean_ctx) == []


def test_r021_clean_project_zero():
    """无声明运镜（空 movements）→ 零采样零误报。"""
    shot = FakeShot(shot_id="shot_001", camera={"movements": []})
    context = FakeContext([shot])
    _stub_samples([])
    assert rule_checker._check_motion_complexity("shot_001", context=context) == []
    assert rule_checker._check_roll_flip("shot_001", context=context) == []
    assert rule_checker._check_camera_accel("shot_001", context=context) == []


def test_r022_roll_flip_detected():
    """视线从 0° 转到 200°（越过头侧）：右向量投影符号翻转 → 恰好 1 条 R022。"""
    samples = [
        {"frame": 1, "position": (0.0, 0.0, 0.0),
         "look_at": (math.cos(math.radians(0.0)), math.sin(math.radians(0.0)), 0.0)},
        {"frame": 24, "position": (0.0, 0.0, 0.0),
         "look_at": (math.cos(math.radians(100.0)), math.sin(math.radians(100.0)), 0.0)},
        {"frame": 48, "position": (0.0, 0.0, 0.0),
         "look_at": (math.cos(math.radians(200.0)), math.sin(math.radians(200.0)), 0.0)},
    ]
    flips = rule_checker._roll_flip_frames(samples, subject_pos=(1.0, 0.0, 0.0))
    assert flips, "0°→100°→200° 应有右向量投影翻转"
    assert flips[0] == 48
    shot = FakeShot(shot_id="shot_001",
                    camera={"movements": [{"type": "pan_left", "amount": 200.0,
                                           "start_frame": 1, "end_frame": 48}]})
    context = FakeContext([shot])
    _stub_samples(samples)
    findings = rule_checker._check_roll_flip("shot_001", context=context)
    r022 = [item for item in findings if item.rule == "R022"]
    assert len(r022) == 1


def test_r022_degenerate_frames_skipped():
    """视线沿天顶（ẑ）的退化帧跳过：无退化+无翻转 → 零误报。"""
    samples = [
        {"frame": 1, "position": (0.0, 0.0, 0.0), "look_at": (0.0, 0.0, 1.0)},
        {"frame": 24, "position": (0.0, 0.0, 0.0), "look_at": (0.0, 0.0, 1.0)},
    ]
    assert rule_checker._roll_flip_frames(samples, subject_pos=(1.0, 0.0, 0.0)) == []


def test_r023_unit_conversion_hand_calculated():
    """R023 单位换算手算对拍：fps=24 时"静止→1 m 阶跃"的二阶差分。

    p = [(0,0,0), (0,0,0), (1,0,0)] → 中心点二阶差分 = (1 − 2·0 + 0) = 1 m；
    a = 1 × 24² = 576 m/s²。（声明禁止归一化值，这里显式钉死物理单位。）
    """
    samples = _samples_with_positions([(0.0, 0.0, 0.0),
                                       (0.0, 0.0, 0.0),
                                       (1.0, 0.0, 0.0)])
    peak, frame = rule_checker._peak_acceleration(samples, fps=24)
    assert frame == samples[1]["frame"]
    assert abs(peak - 576.0) < 1e-6


def test_r023_accel_warning_and_zero():
    """阶跃采样峰值超阈值 → 恰好 1 条 R023；直线匀速 → 零误报。"""
    shot = FakeShot(shot_id="shot_001",
                    camera={"movements": [{"type": "dolly_in", "amount": 1.0,
                                           "start_frame": 1, "end_frame": 48}]})
    context = FakeContext([shot])
    _stub_samples(_samples_with_positions([(0.0, 0.0, 0.0),
                                           (0.0, 0.0, 0.0),
                                           (1.0, 0.0, 0.0)]))
    rule_checker.configure_camera_limits(8.0, compound_max=2, fps=24)
    rule_checker.configure_rules_disabled([])
    findings = rule_checker._check_camera_accel("shot_001", context=context)
    r023 = [item for item in findings if item.rule == "R023"]
    assert len(r023) == 1
    assert "m/s²" in r023[0].message
    _stub_samples(_samples_with_positions([(0.0, 0.0, 0.0),
                                           (1.0, 0.0, 0.0),
                                           (2.0, 0.0, 0.0)]))
    assert rule_checker._check_camera_accel("shot_001", context=context) == []


def test_disabled_via_f1():
    """configure_rules_disabled({"R021","R022","R023"}) → SkippedFinding（F1 联动）。"""
    shot = FakeShot(shot_id="shot_001",
                    camera={"movements": [{"type": "track_right"},
                                          {"type": "track_left"}]})
    context = FakeContext([shot])
    # 三条各自需要触发样本：R021 用折线、R022 用绕行视线、R023 用位移阶跃。
    corner_samples = _samples_with_positions([(0.0, 0.0, 0.0),
                                              (2.0, 0.0, 0.0),
                                              (2.0, 2.0, 0.0)])
    pan_samples = [
        {"frame": 1, "position": (0.0, 0.0, 0.0),
         "look_at": (math.cos(math.radians(0.0)), math.sin(math.radians(0.0)), 0.0)},
        {"frame": 24, "position": (0.0, 0.0, 0.0),
         "look_at": (math.cos(math.radians(100.0)), math.sin(math.radians(100.0)), 0.0)},
        {"frame": 48, "position": (0.0, 0.0, 0.0),
         "look_at": (math.cos(math.radians(200.0)), math.sin(math.radians(200.0)), 0.0)},
    ]
    step_samples = _samples_with_positions([(0.0, 0.0, 0.0),
                                            (0.0, 0.0, 0.0),
                                            (1.0, 0.0, 0.0)])
    rule_checker.configure_rules_disabled(["R021", "R022", "R023"])
    try:
        for fn, samples in (
                (rule_checker._check_motion_complexity, corner_samples),
                (rule_checker._check_roll_flip, pan_samples),
                (rule_checker._check_camera_accel, step_samples)):
            _stub_samples(samples)
            findings = fn("shot_001", context=context)
            assert findings, f"{fn.__name__} 应产出 SkippedFinding"
            assert all(isinstance(item, SkippedFinding) for item in findings)
    finally:
        rule_checker.configure_rules_disabled([])


def test_configure_limits_fallbacks():
    """非法注入回落默认（配置层 CFG_174/175 负责启动前拦截，这里只保不 raise）。"""
    rule_checker.configure_camera_limits(-3.0, compound_max=0, fps=0)
    assert rule_checker._CAM_ACCEL_MAX == 8.0
    assert rule_checker._COMPOUND_MOTION_MAX == 2
    assert rule_checker._ANIMATION_FPS == 24
    rule_checker.configure_camera_limits(12.5, compound_max=4, fps=30)
    assert rule_checker._CAM_ACCEL_MAX == 12.5
    assert rule_checker._COMPOUND_MOTION_MAX == 4
    assert rule_checker._ANIMATION_FPS == 30


def test_config_defaults_and_validation():
    """CFG_174（accel 必须为正）/CFG_175（compound ≥1）与默认值。"""
    cfg = AppConfig()
    assert cfg.guard.cam_accel_max == 8.0
    assert cfg.guard.compound_motion_max == 2
    bad = AppConfig()
    bad.guard.cam_accel_max = -1.0
    assert "CFG_174" in {item.code for item in bad.errors()}
    bad2 = AppConfig()
    bad2.guard.compound_motion_max = 0
    assert "CFG_175" in {item.code for item in bad2.errors()}
    # 默认配置不该报出这两条
    assert "CFG_174" not in {item.code for item in cfg.errors()}
    assert "CFG_175" not in {item.code for item in cfg.errors()}


def test_catalog_has_r021_023():
    """rule_catalog 追加三行（R021/R022/R023，全 warning）。"""
    ids = {item["id"]: item for item in RULES}
    for rule_id in ("R021", "R022", "R023"):
        assert rule_id in ids
        assert ids[rule_id]["severity"] == "warning"
