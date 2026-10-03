"""运镜 `amount` 的**单位**必须告诉模型（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long5/`）：
草案 schema 里 `movements[].amount` 只有一个 `0–180` 的范围、**没有单位**，
模型按"度数"的直觉给 `dolly_in` 写了 **12**——而平移类的单位是**米**，
于是机位真的前推 **12 米、穿过主体**：

```
shot_004（MCU）：相机 (1.147, 2.047) → (-7.338, -6.438)  ← 位移 ≈12 m
                 构图分 54.0 → 27.6（headroom 0、framing 0.234）
```

同一份文档里三个单位并存（平移米／旋转度／变焦毫米），不写出来必然撞车。
本文件钉：单位表是**单一真源**、覆盖全部运镜、提示词逐条列出、模型能读到的
取值范围与 `DEFAULT_AMOUNTS` 不矛盾。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema import camera_motion as CM  # noqa: E402
from block_director.contracts.enums import MOVEMENT_TYPES  # noqa: E402
from block_director.layer5_orchestrator import editor as E  # noqa: E402


def test_every_movement_has_a_unit_and_a_typical_range():
    assert set(CM.MOVEMENT_UNITS) == set(MOVEMENT_TYPES)
    for name, (unit, low, high) in CM.MOVEMENT_UNITS.items():
        assert unit in ("米", "度", "毫米"), (name, unit)
        assert 0 < low <= high, (name, low, high)
        #: 默认值必须落在自己那一类里（否则"没写 amount"的镜头也会离谱）。
        assert low <= CM.DEFAULT_AMOUNTS[name] <= high, (
            name, CM.DEFAULT_AMOUNTS[name], (low, high))


def test_the_three_units_are_actually_distinct():
    """反面对照：如果表里全是同一个单位，这条修复就没有意义。"""
    units = {unit for unit, _low, _high in CM.MOVEMENT_UNITS.values()}
    assert units == {"米", "度", "毫米"}
    assert CM.MOVEMENT_UNITS["dolly_in"][0] == "米"
    assert CM.MOVEMENT_UNITS["pan_left"][0] == "度"
    assert CM.MOVEMENT_UNITS["zoom_in"][0] == "毫米"


def test_the_prompt_lists_every_movement_with_its_unit():
    from block_director.contracts.enums import ShotType
    from block_director.contracts.plan import Plan, ShotPlan

    plan = Plan(shots=[ShotPlan(shot_id="shot_001", intent="推进",
                                shot_type=ShotType.MS, duration_frames=48)])
    system = E.build_editor_payload(plan.shots[0], plan).messages[0].content
    assert "{movement_units}" not in system, "占位符没被替换"
    for name, (unit, low, high) in CM.MOVEMENT_UNITS.items():
        assert f"`{name}`" in system, f"{name} 没进提示词"
    assert "单位=**米**" in system and "单位=**度**" in system
    assert "单位=**毫米**" in system
    #: 那一跑写出来的具体数字（12）在米制里必须在"典型区间"里被判为超范围：
    assert not (CM.MOVEMENT_UNITS["dolly_in"][1]
                <= 12 <= CM.MOVEMENT_UNITS["dolly_in"][2])


def test_the_draft_schema_still_carries_something_for_amount():
    """schema 侧不改成 per-type（JSON Schema 没有条件式），但枚举/范围必须还在。"""
    move = E.EMIT_SHOT_DRAFT_PARAMETERS["properties"]["camera"]["properties"][
        "movements"]["items"]
    assert move["properties"]["type"]["enum"] == list(MOVEMENT_TYPES)
    assert move["properties"]["amount"]["minimum"] == 0
