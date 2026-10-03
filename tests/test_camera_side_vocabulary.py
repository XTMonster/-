"""`camera.side` 必须是**闭集**，而且只有一份真源（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long4/`）：
B1 草案的 schema 把 `camera.side` 写成裸的 `{"type": "string"}`（场景工具那侧
**另有一份手抄的枚举**），于是模型写了整句中文——

    "轴线同侧，米迦尔侧前方，较前一镜角度变化大于 30°，中景平视，50mm"

而 `framing.side_vector()` 对未知取值**静默折成 `front`**（`table.get(side, table["front"])`）。
后果不是"这一镜偏一点"：**64 个镜头的机位全成了"正面"**，构图分中位从 **82.7 掉到
58.4**、64/64 镜判失败、每一镜都烧完修复与精修。

本文件钉三件事：唯一真源、两处 schema 都带枚举、提示词把取值逐字列出来。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema import framing as F  # noqa: E402
from block_director.layer5_orchestrator import editor as E  # noqa: E402
from block_director.layer5_orchestrator.tool_schema import validate_args  # noqa: E402


def test_the_vocabulary_is_one_closed_set():
    assert len(F.CAMERA_SIDES) == 9
    assert "front" in F.CAMERA_SIDES and "over_shoulder" in F.CAMERA_SIDES
    #: 表与常量同源：`side_vector` 内部会当场断言，这里再确认一次语义没变。
    assert F.side_vector((0.0, 1.0), "left") == (-1.0, -0.0) or \
        F.side_vector((0.0, 1.0), "left")[0] < 0


def test_both_schemas_carry_the_same_enum():
    draft_side = E.EMIT_SHOT_DRAFT_PARAMETERS["properties"]["camera"][
        "properties"]["side"]
    assert draft_side.get("enum") == list(F.CAMERA_SIDES), (
        "B1 草案的 side 必须是闭集——裸 string 就是那次 64/64 判失败的入口")


def test_a_chinese_sentence_is_rejected_at_parse_time():
    """现场写的那句中文必须**在解析期**被挡（否则求解器静默折成 front）。"""
    payload = {"shot_id": "shot_001", "shot_type": "MS",
               "actions": [], "dialogues": [],
               "camera": {"side": "轴线同侧，米迦尔侧前方，角度变化大于 30°"},
               "gaze": [], "vfx": [], "prompt": ""}
    problems = validate_args(E.EMIT_SHOT_DRAFT_PARAMETERS, payload)
    assert any("side" in item for item in problems), problems
    ok = dict(payload)
    ok["camera"] = {"side": "front_left"}
    assert validate_args(E.EMIT_SHOT_DRAFT_PARAMETERS, ok) == []


def test_the_prompt_lists_the_values_verbatim():
    from block_director.contracts.enums import ShotType
    from block_director.contracts.plan import Plan, ShotPlan

    plan = Plan(shots=[ShotPlan(shot_id="shot_001", intent="推进",
                                shot_type=ShotType.MS, duration_frames=48)])
    system = E.build_editor_payload(plan.shots[0], plan).messages[0].content
    for value in F.CAMERA_SIDES:
        assert f"`{value}`" in system, f"{value} 没告诉模型"
    assert "{sides}" not in system and "{side_count}" not in system


def test_the_scene_tool_reads_the_same_source():
    """场景工具那份枚举**不许再手抄**——它必须就是 `CAMERA_SIDES`。"""
    source = (ROOT / "block_director" / "layer3_engine"
              / "tool_bindings.py").read_text(encoding="utf-8")
    assert "list(CAMERA_SIDES)" in source
    assert "CAMERA_SIDES" in source
    #: 反面对照：手抄的九个字面量不该再出现。
    assert '"over_shoulder"]' not in source
    json.dumps(list(F.CAMERA_SIDES))
