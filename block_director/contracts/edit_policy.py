"""缺陷 C：agent 工具改动与用户手动改动的判定策略（纯层，禁止 import bpy）。

单一真源：``AGENT_EDITED_KEY`` 是 Blender 对象上的标记键名，scene_sync 与
tool_bindings 只能从这里引用，不许再各抄一份键名（2026-10-19 kimi-k3 真跑
实证：agent 挪过的位置被回读成"用户改动"固化进 initial_location）。
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

#: 对象属性键名：标记"这是 agent 工具写入"，回读时必须排除。
AGENT_EDITED_KEY = "bd_agent_edited"


def should_readback(dirty: bool, agent_edited: bool) -> bool:
    """一个对象是否属于"用户改动"（回读保留的候选）。

    判据：与插件基线不同（dirty）**且**不是 agent 工具写入（agent_edited）。
    两者同真才回读；agent 写入不回读，历史位置可回退可覆盖。
    """
    return bool(dirty and not agent_edited)


def readback_candidates(dirty_ids: Sequence[str],
                        agent_edited_ids: Iterable[str]) -> List[str]:
    """回读候选 = dirty 名单去掉 agent 写入对象，结果按 id 排序稳定。"""
    excluded = set(agent_edited_ids)
    return sorted(str(item) for item in dirty_ids if item not in excluded)
