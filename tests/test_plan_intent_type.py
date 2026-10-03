"""v1.5 §2.3d T3 的**意图轴**：计划带闭集意图 → 逐镜检索的契约串真的发 `意图=`。

为什么值得一组用例（背景见 `docs/knowledge/ACCEPTANCE_STATUS.md` §五十）：

* 超图里被检索最多的一类边是 `INTENT_PACK`（意图×景别×运镜）。实测 64 镜那一跑
  shot 域 320 次命中里 **231 次**是它——而 `意图=` **从来不在发出的查询里**，
  于是拿回来的"意图知识"与这一镜真正要做什么无关。这不是调参问题，是缺了一整个
  检索轴。
* 闭集必须**只有一个真源**：`knowledge/hypergraph.py::VALUE_DOMAINS["intent"]`。
  在 schema 里再抄一份，扩域那天两边就漂。
* 这条轴同时是 Q5 的 join 空间里**唯一**与引擎可表达空间完全重合的一族
  （oracle 里 176 条条目的 `q` 就是 `意图/景别/运镜`）。
"""

from __future__ import annotations

import json

from block_director.contracts.plan import Plan
from block_director.delivery.manifest import build_manifest
from block_director.knowledge.hypergraph import VALUE_DOMAINS
from block_director.layer5_orchestrator.planner import (
    EMIT_PLAN_TOOL_PARAMETERS,
    PLAN_SYSTEM_PROMPT,
)
from block_director.layer5_orchestrator.scene_contract import (
    SceneContract,
    shot_constraint_query,
)
from block_director.layer5_orchestrator.tool_schema import validate_args
from tools.knowledge.quality import _ShotView, plan_query_of_shot


def _shot(**overrides) -> dict:
    shot = {"shot_id": "shot_001", "order": 1, "intent": "推进对话",
            "intent_type": "推进", "shot_type": "MS", "duration_frames": 48,
            "characters": ["char_001"], "dialogue_ids": [], "prompt": "",
            "axis_note": "", "continuity_in": ""}
    shot.update(overrides)
    return shot


def _plan(shot: dict) -> Plan:
    return Plan.from_dict({"shots": [shot]})


def test_the_enum_has_exactly_one_source():
    """schema 里的意图闭集 == `VALUE_DOMAINS["intent"]`（不是抄的副本）。"""
    schema = EMIT_PLAN_TOOL_PARAMETERS["properties"]["shots"]["items"]
    assert schema["properties"]["intent_type"]["enum"] == list(
        VALUE_DOMAINS["intent"])
    #: 12 个值，且必须都是中文闭集里的取值（防止有人改成英文 id 之后两边都"过"）。
    assert len(VALUE_DOMAINS["intent"]) == 12
    assert all(isinstance(value, str) and value for value in VALUE_DOMAINS["intent"])


def test_the_schema_rejects_a_value_outside_the_closed_set():
    """闭集是**机器判据**：写错一个字就被挡回，不是"提示里说了"。"""
    bad = {"shots": [_shot(intent_type="紧张")]}          # 不在 12 值闭集里
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, bad)
    assert any("intent_type" in item for item in problems), problems
    good = {"shots": [_shot(intent_type="压迫")]}
    assert validate_args(EMIT_PLAN_TOOL_PARAMETERS, good) == []


def test_intent_type_stays_optional_for_older_plans():
    """旧计划（没有这个键）仍然合法——闸门加轴不等于把历史计划判非法。"""
    shot = _shot()
    del shot["intent_type"]
    assert validate_args(EMIT_PLAN_TOOL_PARAMETERS, {"shots": [shot]}) == []
    assert Plan.from_dict({"shots": [shot]}).shots[0].intent_type == ""


def test_the_prompt_actually_asks_for_the_closed_set():
    """提示词里必须要求逐字选闭集值：schema 允许 ≠ 模型会写。"""
    assert "intent_type" in PLAN_SYSTEM_PROMPT
    assert "闭集" in PLAN_SYSTEM_PROMPT


def test_the_query_carries_the_intent_and_omits_it_when_absent():
    """正向：`意图=` 进契约串；反向：**没写不许凭空加键**（空值造种子）。"""
    on = _plan(_shot(intent_type="压迫"))
    query = shot_constraint_query(on.shots[0])
    assert query.startswith("景别=MS；意图=压迫"), query

    off = _plan(_shot(intent_type=""))
    without = shot_constraint_query(off.shots[0])
    assert "意图=" not in without, without


def test_both_query_producers_agree_on_the_intent_axis():
    """两条生产者（计划 / ShotContract）必须逐字符一致，意图轴也不例外。"""
    plan = _plan(_shot(intent_type="揭示", shot_type="CU",
                       camera={"lens": "85mm", "movements": [{"type": "dolly_in"}]}))
    contract = SceneContract.from_plan(plan)
    assert (contract.shot("shot_001").constraint_query()
            == shot_constraint_query(plan.shots[0]))
    assert "意图=揭示" in contract.shot("shot_001").constraint_query()


def test_the_plan_round_trip_keeps_the_intent_axis():
    """进计划 → 出计划（to_dict/from_dict）不能丢——SDL/项目文件走这条路。"""
    plan = _plan(_shot(intent_type="回望"))
    again = Plan.from_dict(plan.to_dict())
    assert again.shots[0].intent_type == "回望"


def test_the_run_evidence_keeps_the_intent_axis_in_sync():
    """`shots.json` 必须落这个字段，否则 Q5 的 `derived` 重推串**每一镜都漂**。"""
    plan = _plan(_shot(intent_type="留白"))
    manifest = build_manifest(plan, build_summary={}, fps=24, project="t")
    record = manifest["shots"][0]
    assert record["intent_type"] == "留白"
    #: 重推串 == 真实会发出的串（同一生产者），意图轴在两边都在。
    assert plan_query_of_shot(record) == shot_constraint_query(plan.shots[0])
    assert _ShotView(record).intent_type == "留白"


def test_the_mock_plans_carry_the_axis():
    """夹具是链上真正跑的那份计划：它不带意图，这条轴在链上就从没被跑过。"""
    for name, minimum in (("plan_simple.json", 3), ("plan_long.json", 61)):
        payload = json.loads(
            (__import__("pathlib").Path(__file__).resolve().parents[1]
             / "fixtures" / "mock_llm_responses" / name).read_text(encoding="utf-8"))
        shots = payload["shots"]
        assert len(shots) >= minimum
        assert all(shot.get("intent_type") in VALUE_DOMAINS["intent"]
                   for shot in shots), name
