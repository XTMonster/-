"""缺陷 C（T1）：agent 工具改动与用户手动改动分离。

回读（sync_from_blender）只认"用户改动"——对象既与插件基线不同（dirty）
又没有 agent 写入标记。agent 挪过的位置不得固化进 initial_location。

本文件只测纯层契约（contracts/edit_policy.py，禁止 import bpy）；
bpy 侧行为由 blender 探针 tools/blender_tests/test_agent_edit_probe.py 覆盖。
"""

from __future__ import annotations

from block_director.contracts.edit_policy import (
    AGENT_EDITED_KEY,
    readback_candidates,
    should_readback,
)


def test_agent_edited_key_is_single_source():
    #: 场景同步与工具层只能引用这一个键名，不许各抄一份。
    assert AGENT_EDITED_KEY == "bd_agent_edited"


def test_should_readback_only_user_edits():
    #: dirty 且非 agent 写入 → 用户改动，回读。
    assert should_readback(dirty=True, agent_edited=False) is True
    #: dirty 但 agent 写入 → 不回读。
    assert should_readback(dirty=True, agent_edited=True) is False
    #: 与基线一致 → 无改动，不回读。
    assert should_readback(dirty=False, agent_edited=False) is False
    assert should_readback(dirty=False, agent_edited=True) is False


def test_should_readback_falsy_semantics():
    #: 空串/0 视作"无标记"：dirty 为真时是用户改动。
    assert should_readback(dirty=1, agent_edited="") is True
    assert should_readback(dirty=0, agent_edited="") is False


def test_readback_candidates_excludes_agent_edited_sorted_stable():
    dirty = ["shot_003", "shot_001", "shot_002"]
    agent_edited = ["shot_002", "shot_004"]
    assert readback_candidates(dirty, agent_edited) == ["shot_001", "shot_003"]


def test_readback_candidates_edge_cases():
    assert readback_candidates([], ["x"]) == []
    assert readback_candidates(["a"], []) == ["a"]
    assert readback_candidates(["b", "a"], ["a", "a"]) == ["b"]
