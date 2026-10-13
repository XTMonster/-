"""评测台 fix 类任务对拍的 demo 工具 schema（Ticket 03b 本地夹具）。

正式工具 schema 的真源在 ``layer3_engine/tool_bindings`` 的注册表里；本模块
只是空间尺外挂评测台（AB 台）的**本地夹具**：它只用于 fix 类任务对拍
"工具参数可执行性"，是 03a 收敛前 ``prescription.py`` 同名常量的评测台侧
迁移。这里与真源可能漂移，所以 03b 加了不变量测试：本夹具的工具名必须是
``contracts.tools.ACTION_TOOLS`` 的子集（见 tests/test_spatial_ruler_ab.py）。
"""
from __future__ import annotations

from typing import Any, Dict


DEMO_ACTION_TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "move_camera": {
        "type": "object", "additionalProperties": False,
        "required": ["movement_type", "start_frame", "end_frame"],
        "properties": {
            "camera_id": {"type": "string"},
            "movement_type": {"type": "string", "enum": [
                "dolly_in", "dolly_out", "truck_left", "truck_right", "pan"]},
            "amount": {"type": "number", "minimum": 0, "maximum": 180},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "move_character": {
        "type": "object", "additionalProperties": False,
        "required": ["character_id", "target_position", "start_frame",
                     "end_frame"],
        "properties": {
            "character_id": {"type": "string"},
            "target_position": {"type": "array", "minItems": 3, "maxItems": 3,
                                "items": {"type": "number"}},
            "speed": {"type": "string", "enum": ["walk", "run"]},
            "start_frame": {"type": "integer", "minimum": 1},
            "end_frame": {"type": "integer", "minimum": 1},
        },
    },
    "reframe": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "shot_id": {"type": "string"},
            "shot_type": {"type": "string", "enum": ["MS"]},
            "lens": {"type": "number", "minimum": 8, "maximum": 300},
        },
    },
}


def demo_args_for(tool: str) -> Dict[str, Any]:
    """demo schema 下最小的可执行参数样本（仅 ground truth/mock 用，不进提示）。

    mock 判官与 fix 地面真值用它构造"参数可执行"的答案；它永远不出现在任何
    一臂的提示文本里（防作弊红线）。
    """
    if tool == "move_camera":
        return {"movement_type": "pan", "amount": 6,
                "start_frame": 1, "end_frame": 48}
    if tool == "move_character":
        return {"character_id": "甲", "target_position": [0.5, 0.0, 0.0],
                "start_frame": 1, "end_frame": 48}
    if tool == "reframe":
        return {"shot_type": "MS", "lens": 50}
    return {}
