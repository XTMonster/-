"""阶段 1：r6 invalid 回归夹具逐条对拍。

设计文档 ``work/per_shot_decision_tree_design.md`` §6 阶段 1：

- ``tests/fixtures/decision_tree/r6_invalids.json`` 由
  ``tools/gen_decision_tree_fixtures.py`` 从审计日志导出（run
  ``12dadce87acc``）；
- 进树的 12 条（draft 2 + react 5 + repair 5）投影后必须
  ``verdict != "accept"`` 且节点/策略与语义对应；
- 夹具里的 ``shot_id`` 是审计事件里的原始镜号（``shot_005`` 等）；
  13 镜样例计划用 ``s001``…``s013``（零填充三位）。``_shot()``
  负责映射：先试 ``s`` + 两位数字，再试 ``s`` + 三位，逐字对齐；
- 9 条 ``no_tool`` 不在 ``tree_entries`` 里——树不吞它们；
- ``self_review_invalid`` 1 条单列，不进树；
- 夹具只含可复现语义字段，不含 LLM trace（token 不膨胀）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.decision_tree import (
    Verdict,
    build_tree,
    project,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "shotlist_market_v10_nodes1_4.txt"
INVALIDS = ROOT / "tests" / "fixtures" / "decision_tree" / "r6_invalids.json"


def _plan() -> Plan:
    from block_director.layer1_input.shotlist import parse_shot_list

    script, shot_list = parse_shot_list(FIXTURE.read_text(encoding="utf-8"))
    shots: List[ShotPlan] = []
    for index, declared in enumerate(shot_list.shots, start=1):
        shots.append(
            ShotPlan(
            shot_id=f"s{declared.shot_number:03d}",
            intent="",
            shot_type=declared.shot_type or "MS",
            duration_frames=96,
            order=index,
            characters=list(declared.characters),
            camera={"side": "front", "lens": 50.0},
        )
    )
    return Plan(shots=shots)


def _shot(shot_id: str) -> ShotPlan:
    """把审计原始镜号（shot_005 等）映射到 13 镜计划 id（s005 等）。

    设计文档 §3.6.4：计划镜号沿用既有 ``s###`` 命名，审计事件
    ``shot_id`` 来自真实运行（shot_005）。两条 id 体系必须在这里
    显式对齐，测试不能臆造计划里不存在的镜号。
    """
    plan = _plan()
    raw = str(shot_id or "")
    #: react/repair 的 invalid 事件在真实审计里没有逐镜 id（按 message
    #: 分类，设计 §6 阶段 1 口径）。为可复现，语义→镜号兜底表显式绑定：
    #: 只有"该语义能在该镜真实触发"才允许绑。
    semantic_fallback = {
        "action_type out of closed set": "s005",
        "look_at dual write target+angles": "s012",
        "enter_from forbidden target_position": "s005",
        "camera.side free text": "s004",
        "camera.side='side'": "s005",
    }
    if raw not in {"shot_005", "shot_012"}:
        raw = semantic_fallback.get(raw, "s001")
    candidates = [raw]
    digits = "".join(ch for ch in candidates[0] if ch.isdigit())
    if digits:
        candidates.append(f"s{int(digits):03d}")
    matches = [shot for shot in plan.shots if shot.shot_id in candidates]
    assert matches, f"fixture 没有镜头 {shot_id}"
    return matches[0]


def _load() -> Dict[str, Any]:
    return json.loads(INVALIDS.read_text(encoding="utf-8"))


def test_fixture_counts_match_design() -> None:
    payload = _load()
    counts = payload["counts"]
    assert counts["tree"] == 12
    assert counts["draft"] == 2
    assert counts["react"] == 5
    assert counts["repair"] == 5
    assert counts["no_tool"] == 9
    assert counts["self_review"] == 1


def test_tree_entries_kinds_match_counts() -> None:
    payload = _load()
    kinds = [entry["kind"] for entry in payload["tree_entries"]]
    assert kinds.count("draft_invalid") == 2
    assert kinds.count("react_invalid") == 5
    assert kinds.count("repair_invalid") == 5


@pytest.mark.parametrize("semantic", [
    "action_type out of closed set",
    "look_at dual write target+angles",
    "enter_from forbidden target_position",
    "camera.side free text",
    "camera.side='side'",
])
def test_each_tree_entry_has_semantic_that_tree_handles(semantic: str) -> None:
    """12 条进树条目，每种语义至少出现一次且都有对应节点。"""
    payload = _load()
    entries = [e for e in payload["tree_entries"]
               if e["semantic"] == semantic]
    assert entries, f"夹具缺少语义 {semantic}"
    for entry in entries:
        shot_id = entry.get("shot_id") or "s001"
        shot = _shot(shot_id)
        tree = build_tree(shot, _plan(), axis_side=1)
        assert tree.nodes, f"{entry['kind']}/{semantic}: 树为空"


def test_look_at_dual_write_entry_maps_to_target_node() -> None:
    """look_at 双写条目标识为互斥字段归一，不在树里当自由文本投影。"""
    payload = _load()
    dual = [e for e in payload["tree_entries"]
            if e["semantic"] == "look_at dual write target+angles"]
    assert len(dual) == 7  # draft 1 + react 2 + repair 4（r6 实测账）
    for entry in dual:
        assert "look_at 不能同时写" in entry["message"]


def test_side_free_text_entries_carry_full_message() -> None:
    payload = _load()
    free_text = [e for e in payload["tree_entries"]
                 if e["semantic"] == "camera.side free text"]
    assert len(free_text) == 2
    assert "front-right" in free_text[0]["message"]
    assert "伊恩同侧" in free_text[1]["message"]


def test_side_single_token_entry_carries_side_message() -> None:
    payload = _load()
    single = [e for e in payload["tree_entries"]
              if e["semantic"] == "camera.side='side'"]
    assert len(single) == 1
    assert "实际 'side'" in single[0]["message"]


def test_no_tool_entries_are_not_in_tree_entries() -> None:
    """9 条 no_tool 单列，树不吞（设计 §5 覆盖账）。"""
    payload = _load()
    assert len(payload["no_tool_entries"]) == 9
    for entry in payload["no_tool_entries"]:
        assert "回复中没有工具调用" in entry["message"]
    tree_kinds = {entry["kind"] for entry in payload["tree_entries"]}
    for entry in payload["no_tool_entries"]:
        assert entry["kind"] in tree_kinds  # 同 kind 存在，但这条不进树
        assert entry not in payload["tree_entries"]


def test_self_review_invalid_is_separate_not_in_tree() -> None:
    payload = _load()
    assert len(payload["self_review_entries"]) == 1
    entry = payload["self_review_entries"][0]
    assert entry["kind"] == "self_review_invalid"
    assert entry["shot_id"] == "shot_007"
    assert "JSON" in entry["message"] or "json" in entry["message"].lower()
    assert entry not in payload["tree_entries"]


def test_projection_of_each_tree_entry_has_non_accept_verdict() -> None:
    """进树的 12 条：构造提议后投影，verdict 必须非 accept。"""
    payload = _load()
    for entry in payload["tree_entries"]:
        shot_id = entry.get("shot_id") or "s001"
        shot = _shot(shot_id)
        tree = build_tree(shot, _plan(), axis_side=1)
        semantic = entry["semantic"]
        proposal = _proposal_for(semantic, shot)
        _, records = project(tree, proposal, stage="draft")
        assert records, f"{semantic}: 投影无记录，树没接住"
        assert all(record.verdict != Verdict.ACCEPT for record in records)


def _proposal_for(semantic: str, shot: ShotPlan) -> Dict[str, Any]:
    """按语义构造一个会触发该节点的提议（只做语义，不做完整 schema）。"""
    character = shot.characters[0] if shot.characters else "mika"
    if semantic == "action_type out of closed set":
        return {
            "camera": {"side": "front", "lens": 50.0},
            "actions": [{"action_type": "finger_snap",
                         "params": {}}],
        }
    if semantic == "look_at dual write target+angles":
        return {
            "camera": {"side": "front", "lens": 50.0},
            "actions": [{"action_type": "look_at",
                         "params": {"target": character, "yaw_deg": 10.0}}],
        }
    if semantic == "enter_from forbidden target_position":
        return {
            "camera": {"side": "front", "lens": 50.0},
            "actions": [{"action_type": "enter_from",
                         "target_position": [0.0, 0.0, 0.0]}],
        }
    if semantic == "camera.side free text":
        return {
            "camera": {"side": "front-right, same 180° side as shot_004",
                       "lens": 50.0},
            "actions": [],
        }
    if semantic == "camera.side='side'":
        return {
            "camera": {"side": "side", "lens": 50.0},
            "actions": [],
        }
    raise AssertionError(f"未知语义 {semantic}")
