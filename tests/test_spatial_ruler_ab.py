"""空间尺外挂评测台（spec §15）的测试：TDD 红→绿。

覆盖：
* 任务集两臂齐全、地面真值均由纯层几何确定性算出；
* 防作弊不变量：尺子臂只注入"测量读数"，estimate/direction/fix 不得泄露
  处方答案（tool/args/建议执行）；坏处方必须能触发"拒绝"裁决；
* 评分器各任务族的判定规则；
* mock 判官（plumbing 专用）在尺子臂下得分不低、报告/转录确定性；
* 报告 JSON 形态与 delta 聚合。
"""
from __future__ import annotations

import json
from typing import Dict, List

from block_director.cinema.composition import evaluate_composition
from block_director.cinema.prescription import build_prescriptions

from tools.spatial_ruler_ab.arms import render_measurement_block
from tools.spatial_ruler_ab.fixtures import (
    build_battery,
    composition_scenes,
    fight_scene,
    render_prescription_block,
)
from tools.spatial_ruler_ab.method import (
    METHOD_PROMPT,
    render_method_block,
)
from tools.spatial_ruler_ab.llm import MockJudge
from tools.spatial_ruler_ab.report import build_report, run_experiment
from tools.spatial_ruler_ab.scoring import score_task
from block_director.knowledge.cards_review_method import (
    CARDS as METHOD_CARDS,
    render_method_checklist,
)


# --------------------------------------------------------------------------- #
# 任务集
# --------------------------------------------------------------------------- #
def test_battery_both_arms_present_and_ground_truth_deterministic():
    """每个任务两臂提示非空；地面真值可 JSON 序列化（确定性）。"""
    battery = build_battery()
    kinds = {t.kind for t in battery}
    assert {"verdict", "estimate", "direction", "fix",
            "dynamic_facts", "prescription_verdict"} <= kinds
    for t in battery:
        assert t.baseline_prompt.strip()
        assert t.ruler_prompt.strip()
        assert t.method_prompt.strip()
        assert t.ruler_method_prompt.strip()
        assert "测量读数" in t.ruler_prompt
        assert "测量读数" in t.ruler_method_prompt
        assert "检查顺序" in t.method_prompt
        assert "检查顺序" in t.ruler_method_prompt
        json.dumps(t.ground_truth, ensure_ascii=False)  # 必须可序列化


def test_method_cards_are_review_methodology_not_theory():
    """方法卡必须讲「怎么审」而非「构图是什么」：含操作步骤/顺序/判定。"""
    assert METHOD_CARDS
    for card in METHOD_CARDS:
        assert card.id.startswith("rev_method_")
        assert card.domain == "composition"
        assert any(k in card.content for k in ("步骤", "顺序", "判定", "流程",
                                               "检查", "核对", "复核"))


def test_ground_truth_matches_pure_geometry():
    """地面真值必须与纯层几何同一算法：同输入重算结果一致。"""
    for scene in composition_scenes():
        report = evaluate_composition(
            scene["boxes"], scene.get("occluded"),
            scene.get("expected_height"),
            scene.get("headroom_applies", True))
        assert report.passed == scene["gt"]["passed"]
        #: 与 tools/spatial_ruler_ab/fixtures.py 的 failed 口径同源：
        #: 用户 2026-10-18 裁决，分量达标线严格高于 0.8（等于不算过）。
        failed = {k for k, v in report.items.items() if v.score <= 0.8}
        assert failed == set(scene["gt"]["failed"])


def test_method_block_contains_operation_checklist():
    """方法臂的话术必须包含「可操作检查清单/判定顺序」，不是理论重述。"""
    scene = next(s for s in composition_scenes() if not s["gt"]["passed"])
    block = render_method_block(scene)
    assert "检查顺序" in block
    assert "step" in block.lower()
    assert "过门" in block
    assert "分量" in block


def test_method_cards_agree_with_method_block():
    """知识卡草案与评测台方法臂话术同源：检查顺序与判定阈值一致。"""
    checklist = render_method_checklist()
    block = render_method_block(next(s for s in composition_scenes()
                                     if not s["gt"]["passed"]))
    for expected in ("1. 看主体入画", "2. 看头部留白", "3. 看三分/视线",
                     "4. 看重心", "5. 看遮挡", "6. 看动态"):
        assert expected in checklist
        assert expected in block


# --------------------------------------------------------------------------- #
# 防作弊（spec §15.4 红线）
# --------------------------------------------------------------------------- #
def test_ruler_arm_leaks_no_prescription_answer():
    """estimate/direction/fix 的尺子臂不得含处方答案（tool/args/建议执行）。"""
    battery = build_battery()
    banned_tokens = {"建议执行", "move_camera", "move_character", "reframe",
                     "dolly_in", "dolly_out", "truck_left", "truck_right", "pan"}
    for t in battery:
        for arm_prompt in (t.ruler_prompt, t.ruler_method_prompt,
                           t.method_prompt):
            if t.kind not in {"estimate", "direction", "fix"}:
                continue
            for token in banned_tokens:
                assert token not in arm_prompt, \
                    f"{t.id} 尺子臂泄露处方答案：{token}"


def test_ruler_arm_contains_measurement_block():
    """尺子臂必须含测量读数块；基线臂不得含该块。"""
    battery = build_battery()
    assert any("测量读数" in t.ruler_prompt for t in battery)
    for t in battery:
        assert "测量读数" not in t.baseline_prompt
        assert "测量读数" not in t.method_prompt
        assert "测量读数" in t.ruler_method_prompt
        assert "检查顺序" in t.method_prompt
        assert "检查顺序" in t.ruler_method_prompt
        assert "检查顺序" not in t.baseline_prompt


def test_measurement_block_round_trip_parseable():
    """读数块可被 mock 判官解析（格式契约，防双真源漂移）。"""
    scene = next(s for s in composition_scenes() if not s["gt"]["passed"])
    block = render_measurement_block(scene)
    parsed = MockJudge().parse_measurements(block)
    assert parsed["headroom_current"] is not None
    assert parsed["score"] is not None


def test_ruler_method_arm_parses_measurements():
    """方法+读数臂的读数块格式不变，mock 判官可解析（防双真源漂移）。"""
    battery = build_battery()
    t = next(x for x in battery if x.kind == "estimate")
    parsed = MockJudge().parse_measurements(t.ruler_method_prompt)
    assert parsed["headroom_current"] is not None
    assert parsed["score"] is not None


def test_poisoned_prescription_must_be_rejected():
    """含内部键（camera_z）的处方 → 地面真值是"拒绝"，渲染文本必须能触发污染守卫。"""
    scene = next(s for s in composition_scenes() if not s["gt"]["passed"])
    from tools.spatial_ruler_ab.poison import poisoned_prescriptions
    from block_director.cinema.prescription import detect_pollution
    bad = poisoned_prescriptions(scene)
    assert bad, "坏处方样本必须存在"
    verdict = score_task({
        "kind": "prescription_verdict",
        "ground_truth": {"accept": False},
    }, {"accept": False})
    assert verdict["correct"] is True
    assert any("camera_z" in render_prescription_block(p) for p in bad)
    assert any(detect_pollution(render_prescription_block(p)) for p in bad)


def test_demo_schemas_and_fix_ground_truth_stay_within_action_tools():
    """03b 迁移不变量：demo schema 与 fix 地面真值必须是正式工具名单子集。"""
    from block_director.contracts.tools import ACTION_TOOLS
    from tools.spatial_ruler_ab.arms import DEMO_ACTION_TOOL_SCHEMAS
    assert set(DEMO_ACTION_TOOL_SCHEMAS) <= set(ACTION_TOOLS)
    for t in build_battery():
        if t.kind == "fix":
            assert set(t.ground_truth["allowed_tools"]) <= set(ACTION_TOOLS)


# --------------------------------------------------------------------------- #
# 评分器
# --------------------------------------------------------------------------- #
def test_scoring_verdict_and_estimate():
    gt_verdict = {"passed": False, "failed": ["headroom", "thirds"]}
    assert score_task({"kind": "verdict", "ground_truth": gt_verdict},
                      {"passed": False, "failed": ["headroom", "thirds"]})["correct"]
    assert not score_task({"kind": "verdict", "ground_truth": gt_verdict},
                          {"passed": True, "failed": []})["correct"]
    assert score_task({"kind": "estimate", "ground_truth": {"value": 0.4}},
                      {"value": 0.42})["correct"]
    assert not score_task({"kind": "estimate", "ground_truth": {"value": 0.4}},
                          {"value": 0.9})["correct"]


def test_scoring_direction_fix_prescription_verdict():
    assert score_task(
        {"kind": "direction", "ground_truth": {"acceptable": ["抬高机位", "推近"]}},
        {"direction": "推近"})["correct"]
    fix_gt = {"allowed_tools": ["move_camera"], "tool": "move_camera"}
    from block_director.layer5_orchestrator.tool_schema import validate_args
    from tools.spatial_ruler_ab.arms import DEMO_ACTION_TOOL_SCHEMAS
    good = {"tool": "move_camera",
            "tool_args": {"movement_type": "pan", "amount": 6,
                          "start_frame": 1, "end_frame": 48}}
    assert not validate_args(DEMO_ACTION_TOOL_SCHEMAS["move_camera"], good["tool_args"])
    assert score_task({"kind": "fix", "ground_truth": fix_gt,
                       "schemas": DEMO_ACTION_TOOL_SCHEMAS}, good)["correct"]
    assert score_task(
        {"kind": "prescription_verdict", "ground_truth": {"accept": True}},
        {"accept": True})["correct"]


# --------------------------------------------------------------------------- #
# mock 判官与整链
# --------------------------------------------------------------------------- #
def test_mock_judge_returns_parseable_answer():
    judge = MockJudge()
    battery = build_battery()
    t = next(x for x in battery if x.kind == "estimate")
    ans = judge.answer(t, t.ruler_prompt, "ruler")
    assert "value" in ans
    assert isinstance(ans["value"], float)

    t_method = next(x for x in battery if x.kind == "estimate")
    ans2 = judge.answer(t_method, t_method.ruler_method_prompt, "ruler_method")
    assert "value" in ans2
    assert isinstance(ans2["value"], float)


def test_mock_judge_method_arm_does_not_leak_answer_in_fix():
    """mock 的方法+读数臂不能从方法块里直接抄处方答案（防作弊）。"""
    judge = MockJudge()
    battery = build_battery()
    t = next(x for x in battery if x.kind == "fix")
    ans = judge.answer(t, t.ruler_method_prompt, "ruler_method")
    assert ans["tool"] == t.ground_truth["tool"]
    assert "建议执行" not in t.ruler_method_prompt


def test_mock_ab_delta_positive_and_report_shape():
    """mock 整链：尺子臂总体不低于基线臂；报告含 delta/transcript。"""
    battery = build_battery()
    report = run_experiment(MockJudge(), battery, timestamp="2026-10-12T00:00:00")
    arms = report["arms"]
    assert set(arms) == {"baseline", "ruler", "method", "ruler_method"}
    assert arms["ruler_method"]["overall"] >= arms["baseline"]["overall"]
    assert arms["ruler_method"]["overall"] >= arms["ruler"]["overall"]
    assert arms["method"]["overall"] >= arms["baseline"]["overall"]
    assert report["delta"]["ruler_vs_baseline"]["overall"] >= 0
    assert report["delta"]["method_vs_baseline"]["overall"] >= 0
    assert report["delta"]["ruler_method_vs_method"]["overall"] >= 0
    assert report["judge"]["evidence_grade"] == "plumbing"
    assert report["transcript"]
    row = report["transcript"][0]
    assert {"task_id", "arm", "kind", "answer", "correct"} <= set(row)
    assert "baseline" in {r["arm"] for r in report["transcript"]}
    assert "ruler" in {r["arm"] for r in report["transcript"]}
    assert "method" in {r["arm"] for r in report["transcript"]}
    assert "ruler_method" in {r["arm"] for r in report["transcript"]}


def test_mock_four_arm_deltas_decompose():
    """2×2 分解：总增量 = 读数增量 + 方法论增量 + 交互增量。"""
    battery = build_battery()
    report = run_experiment(MockJudge(), battery, timestamp="2026-10-12T00:00:00")
    d = report["delta"]
    total = d["ruler_method_vs_baseline"]["overall"]
    readings = d["ruler_vs_baseline"]["overall"]
    method = d["method_vs_baseline"]["overall"]
    interaction = d["ruler_method_vs_sum"]["overall"]
    assert abs((readings + method + interaction) - total) < 1e-6


def test_report_deterministic():
    """同判官同参数两次运行逐字节相同。"""
    battery = build_battery()
    a = json.dumps(run_experiment(MockJudge(), battery,
                                  timestamp="2026-10-12T00:00:00"),
                   ensure_ascii=False, sort_keys=True)
    b = json.dumps(run_experiment(MockJudge(), battery,
                                  timestamp="2026-10-12T00:00:00"),
                   ensure_ascii=False, sort_keys=True)
    assert a == b


def test_fight_dynamic_facts_in_battery():
    """打斗动态事实任务进入任务集，且尺子臂读数可被 mock 解析。"""
    battery = build_battery()
    t = next(x for x in battery if x.kind == "dynamic_facts")
    assert t.ground_truth["exits"]
    judge = MockJudge()
    ans = judge.answer(t, t.ruler_prompt, "ruler")
    assert ans["exits"] == t.ground_truth["exits"]
    ans2 = judge.answer(t, t.ruler_method_prompt, "ruler_method")
    assert ans2["exits"] == t.ground_truth["exits"]


def test_fight_dynamic_method_block():
    """打斗动态任务的方法臂包含动态检查项：出画/回冲/方向反转。"""
    battery = build_battery()
    t = next(x for x in battery if x.kind == "dynamic_facts")
    block = render_method_block(t.payload.get("scene") or fight_scene())
    assert "出画" in block
    assert "回冲" in block
    assert "方向" in block
    assert "遮挡" in block


# --------------------------------------------------------------------------- #
# 引用防漂移：fixture 与既有 demo 同源
# --------------------------------------------------------------------------- #
def test_fight_fixture_matches_demo_geometry():
    """fight_scene 与打斗 demo 用同一组采样，事件帧一致。"""
    from block_director.cinema.dynamic_measure import analyze_fight
    report = analyze_fight(fight_scene())
    exits = [e for e in report.events if e.kind == "exit_frame"]
    assert exits and exits[0].frame == 8
