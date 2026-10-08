"""v1.6 C2（FR-A1 / D-10）：环境方位闭集映射表的纯层判定。

``scene_executor.py`` 顶层 import bpy，pytest 环境无法直接导入。与
``tests/test_tool_bindings_env.py`` 同一招：给 ``bpy`` /
``collection_router`` / ``transaction`` 塞最小占位后**按文件路径直接加载**
模块源码，只测它的纯层部分（映射表 / 尺寸档 / 非法值问题 / finding 形状）。

判据刻意全部外生：闭集取自 ``contracts/brief.py``（C1 的单一真源），
映射表逐格对拍钉死的期望值——表漂一点这里就红（TDD §3.4）。
"""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path

from block_director.contracts.audit import ENV_FINDING_CODE, env_finding
from block_director.contracts.brief import (
    SPACE_DIRECTIONS,
    SPACE_DISTANCES,
    SPACE_SIZES,
)
from block_director.contracts.enums import ErrorCode
from block_director.contracts.errors import USER_MESSAGES, user_message

ROOT = Path(__file__).resolve().parents[1]


def _stub_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_scene_executor() -> types.ModuleType:
    """按路径加载 scene_executor.py（占位 bpy 等三个 bpy 侧依赖，用后即清）。"""
    name = "block_director.layer3_engine.scene_executor"
    path = ROOT / "block_director" / "layer3_engine" / "scene_executor.py"
    created: list = []
    if "block_director.layer3_engine" not in sys.modules:
        parent = types.ModuleType("block_director.layer3_engine")
        parent.__path__ = [str(path.parent)]
        sys.modules["block_director.layer3_engine"] = parent
        created.append("block_director.layer3_engine")
    if "bpy" not in sys.modules:
        bpy_stub = _stub_module("bpy")
        #: ``from bpy.types import Object`` 需要这个属性；注解是懒求值的，
        #: 占位只要可导入即可。
        bpy_stub.types = _stub_module("bpy.types", Object=object)
        created.extend(["bpy", "bpy.types"])
    router = _stub_module(
        "block_director.layer3_engine.collection_router",
        mark_as_guide=lambda obj: obj,
        route_to_content=lambda obj: obj)
    created.append(router.__name__)
    transaction = _stub_module("block_director.layer3_engine.transaction")

    class _Transaction:
        def __init__(self, label: str) -> None:
            self.label = label

        def __enter__(self) -> "_Transaction":
            return self

        def __exit__(self, *_args) -> bool:
            return False

    transaction.Transaction = _Transaction
    created.append(transaction.__name__)

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        #: 不留脏占位：test_package_surface 断言契约层不引入 bpy（读 sys.modules），
        #: 这里加载完必须把占位清掉，否则该判据会按运行顺序随机红。
        for stub in [*created, name]:
            sys.modules.pop(stub, None)
    return module


_scene_executor = _load_scene_executor()
ENVIRONMENT_OFFSETS = _scene_executor.ENVIRONMENT_OFFSETS
ENVIRONMENT_SIZE_DIMS = _scene_executor.ENVIRONMENT_SIZE_DIMS
ENVIRONMENT_OCCLUDERS = _scene_executor.ENVIRONMENT_OCCLUDERS
ENVIRONMENT_SKY_COLOR = _scene_executor.ENVIRONMENT_SKY_COLOR
ENVIRONMENT_OCCLUDER_COLOR = _scene_executor.ENVIRONMENT_OCCLUDER_COLOR
environment_offset = _scene_executor.environment_offset
environment_dimensions = _scene_executor.environment_dimensions
environment_item_placement = _scene_executor.environment_item_placement


def _radius(vector) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in vector))


# --------------------------------------------------------------------------- #
# 1. 映射表：18 对 (direction, distance) 一格不缺、逐格钉死
# --------------------------------------------------------------------------- #
def test_offset_table_covers_every_direction_distance_pair():
    assert len(ENVIRONMENT_OFFSETS) == len(SPACE_DIRECTIONS) * len(SPACE_DISTANCES)
    for direction in SPACE_DIRECTIONS:
        for distance in SPACE_DISTANCES:
            offset = ENVIRONMENT_OFFSETS.get((direction, distance))
            assert offset is not None, (direction, distance)
            assert len(offset) == 3
            assert all(isinstance(float(value), float) for value in offset)


def test_offset_table_is_pinned_to_the_contract_values():
    expected = {
        ("front", "near"): (0.0, 3.0, 1.2),
        ("front", "mid"): (0.0, 7.0, 1.2),
        ("front", "far"): (0.0, 14.0, 1.2),
        ("back", "near"): (0.0, -3.0, 1.2),
        ("back", "mid"): (0.0, -7.0, 1.2),
        ("back", "far"): (0.0, -14.0, 1.2),
        ("left", "near"): (-3.0, 0.0, 1.2),
        ("left", "mid"): (-7.0, 0.0, 1.2),
        ("left", "far"): (-14.0, 0.0, 1.2),
        ("right", "near"): (3.0, 0.0, 1.2),
        ("right", "mid"): (7.0, 0.0, 1.2),
        ("right", "far"): (14.0, 0.0, 1.2),
        ("above", "near"): (0.0, 0.0, 3.0),
        ("above", "mid"): (0.0, 0.0, 7.0),
        ("above", "far"): (0.0, 0.0, 14.0),
        ("ground", "near"): (1.5, 1.5, 0.5),
        ("ground", "mid"): (5.0, -5.0, 0.5),
        ("ground", "far"): (10.0, 10.0, 0.5),
    }
    assert ENVIRONMENT_OFFSETS == expected


def test_distance_bands_hold_for_every_pair():
    """near≤4m / mid≤10m / far>10m（相对场景中心的欧氏距离，TDD §3.4）。"""
    for (direction, distance), offset in ENVIRONMENT_OFFSETS.items():
        radius = _radius(offset)
        if distance == "near":
            assert radius <= 4.0, (direction, distance, radius)
        elif distance == "mid":
            assert radius <= 10.0, (direction, distance, radius)
        else:
            assert radius > 10.0, (direction, distance, radius)


def test_lookups_are_deterministic_and_return_the_same_values():
    for key, offset in ENVIRONMENT_OFFSETS.items():
        again = environment_offset(*key)
        assert again is not None
        assert tuple(again) == tuple(offset)
    for size, dims in ENVIRONMENT_SIZE_DIMS.items():
        again = environment_dimensions(size)
        assert again is not None
        assert tuple(again) == tuple(dims)


# --------------------------------------------------------------------------- #
# 2. 尺寸档：s / m / l 一格不缺、取值钉死、全为正
# --------------------------------------------------------------------------- #
def test_size_table_covers_every_size_and_is_positive():
    assert set(ENVIRONMENT_SIZE_DIMS) == set(SPACE_SIZES)
    for size, dims in ENVIRONMENT_SIZE_DIMS.items():
        assert len(dims) == 3
        assert all(float(value) > 0.0 for value in dims), (size, dims)


def test_size_table_is_pinned_to_the_contract_values():
    assert ENVIRONMENT_SIZE_DIMS == {
        "s": (1.0, 1.0, 1.0),
        "m": (2.5, 2.5, 2.5),
        "l": (6.0, 6.0, 4.0),
    }


# --------------------------------------------------------------------------- #
# 3. 骨架常量：四向遮挡体 + 天空底色
# --------------------------------------------------------------------------- #
def test_skeleton_occluders_cover_all_four_sides_at_the_ring():
    sides = [entry[0] for entry in ENVIRONMENT_OCCLUDERS]
    assert sides == ["N", "S", "E", "W"]
    for side, position, size in ENVIRONMENT_OCCLUDERS:
        assert len(position) == 3 and len(size) == 3
        assert _radius(position[:2]) >= 11.0, (side, position)
        assert all(float(value) > 0.0 for value in size), (side, size)


def test_sky_color_is_a_finite_rgb_triple():
    assert len(ENVIRONMENT_SKY_COLOR) == 3
    assert all(0.0 <= float(value) <= 1.0 for value in ENVIRONMENT_SKY_COLOR)


def test_occluder_color_stays_darker_than_the_cast_palette():
    """立面必须暗于角色最暗色（luma ≈ 0.54）。

    实测回归：0.66 / 0.34 灰会吃掉 test_phase1_scene 的"角色让画面变亮"
    冻结判据（阈值 0.02，HEAD 基线 delta=0.042）；只有贴近交付背景
    （0.10/0.11/0.14）的深立面能保住它。
    """
    assert ENVIRONMENT_OCCLUDER_COLOR == (0.12, 0.12, 0.16)
    luma = (0.2126 * ENVIRONMENT_OCCLUDER_COLOR[0]
            + 0.7152 * ENVIRONMENT_OCCLUDER_COLOR[1]
            + 0.0722 * ENVIRONMENT_OCCLUDER_COLOR[2])
    assert luma < 0.20


# --------------------------------------------------------------------------- #
# 4. 非法值 → 问题（finding 的 reason），绝不猜坐标 / 尺寸
# --------------------------------------------------------------------------- #
def _entry(**overrides):
    entry = {"label": "拱廊拱顶", "direction": "above", "distance": "near",
             "size": "l", "mood": "蓝绿色铸钢雕花铁艺"}
    entry.update(overrides)
    return entry


def test_valid_item_places_at_the_table_position_and_size():
    offset, dims, problems = environment_item_placement(_entry())
    assert problems == []
    assert tuple(offset) == (0.0, 0.0, 3.0)
    assert tuple(dims) == ENVIRONMENT_SIZE_DIMS["l"]


def test_every_valid_pair_places_through_the_resolver():
    for (direction, distance), offset in ENVIRONMENT_OFFSETS.items():
        for size in SPACE_SIZES:
            got_offset, got_dims, problems = environment_item_placement(
                _entry(direction=direction, distance=distance, size=size))
            assert problems == [], (direction, distance, size)
            assert tuple(got_offset) == tuple(offset)
            assert tuple(got_dims) == tuple(ENVIRONMENT_SIZE_DIMS[size])


def test_each_invalid_closed_field_is_reported_and_nothing_is_guessed():
    for key, value in (("direction", "画面后方"), ("distance", "遥远"),
                       ("size", "xl")):
        offset, dims, problems = environment_item_placement(
            _entry(**{key: value}))
        assert offset is None and dims is None, (key, value)
        assert any(key in problem and repr(value) in problem
                   for problem in problems), (key, value, problems)


def test_a_missing_closed_field_is_reported_not_invented():
    offset, dims, problems = environment_item_placement({"label": "摊位"})
    assert offset is None and dims is None
    assert len(problems) == 3
    assert all("闭集" in problem for problem in problems)


def test_a_non_dict_item_is_a_problem_not_a_guess():
    offset, dims, problems = environment_item_placement(["not", "a", "dict"])
    assert offset is None and dims is None
    assert any("对象" in problem for problem in problems)


def test_the_where_prefix_identifies_the_item():
    _offset, _dims, problems = environment_item_placement(
        _entry(direction="画面后方"), where="environment[3]")
    assert any(problem.startswith("environment[3].") for problem in problems)


# --------------------------------------------------------------------------- #
# 5. E_ENV_001 已登记：审计契约、ErrorCode、用户文案三处一致
# --------------------------------------------------------------------------- #
def test_env_finding_shape_and_code_registration():
    line = env_finding("远处海面", "direction 取值 '画面后方' 不在闭集")
    assert line == ("E_ENV_001: 远处海面: "
                    "direction 取值 '画面后方' 不在闭集")
    assert ENV_FINDING_CODE == str(ErrorCode.ENV_001)
    assert ErrorCode.ENV_001 in USER_MESSAGES


def test_env_001_user_message_is_actionable_and_formattable():
    message = user_message(ErrorCode.ENV_001, label="拱廊拱顶",
                           reason="direction 取值 '画面后方' 不在闭集")
    assert "拱廊拱顶" in message
    assert "front" in message and "near" in message and "s" in message
