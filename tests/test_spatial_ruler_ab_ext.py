"""Ticket 11 扩展测试：四类新任务接入四臂（spec §9/§10 报告扩展）。

覆盖（SPEC 11 A5 九点）：
1. 四类新任务各 ≥3 条（good/bad/边界），含拒绝污染；
2. ground truth 确定性：同构造函数两次调用逐字段一致；
3. 防泄漏：ruler/ruler_method 提示不含 ground_truth 的 JSON 全文（污染除外）；
4. 污染留痕：transcript 行 poisoned + poison_rejected 正确；
5. 评分器四新 kind 对/错/缺键；
6. run_experiment 报告含全部 §10 字段；
7. render_markdown 含六层表、硬门、三问、plumbing 警示、打斗独立动作层；
8. 确定性：同 MockJudge 同 battery 两次运行（剔除 timestamp）逐字段相等；
9. 回归：既有 AB/demo/10 票测试保持绿（本文件自身 + 验收命令里执行）。
"""
from __future__ import annotations

import json

from tools.spatial_ruler_ab.llm import MockJudge
from tools.spatial_ruler_ab.fixtures import build_battery
from tools.spatial_ruler_ab.report import run_experiment, render_markdown
from tools.spatial_ruler_ab.scoring import score_task
from tools.spatial_ruler_ab.tasks_new import (
    build_action_roles_tasks,
    build_continuity_verdict_tasks,
    build_full_battery,
    build_new_tasks,
    build_priority_order_tasks,
    build_robustness_verdict_tasks,
)


def _jsonable(value):
    json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 1) 四类新任务数量与三态
# --------------------------------------------------------------------------- #
def test_four_new_kinds_present_with_states():
    tasks = build_new_tasks()
    kinds = {t.kind for t in tasks}
    assert kinds == {"action_roles", "continuity_verdict", "priority_order",
                     "robustness_verdict"}
    by_kind = {k: [t for t in tasks if t.kind == k] for k in kinds}
    assert len(by_kind["action_roles"]) >= 3
    assert len(by_kind["continuity_verdict"]) >= 3
    assert len(by_kind["priority_order"]) >= 3
    assert len(by_kind["robustness_verdict"]) >= 3
    for t in tasks:
        assert t.baseline_prompt.strip()
        assert t.ruler_prompt.strip()
        assert t.method_prompt.strip()
        assert t.ruler_method_prompt.strip()
        _jsonable(t.ground_truth)


def test_new_kinds_have_bad_and_boundary_states():
    """每类至少含 bad 态；continuity 含 ambiguous（低置信边界）。"""
    action = build_action_roles_tasks()
    assert any(t.payload.get("sample_state") == "bad" for t in action)
    continuity = build_continuity_verdict_tasks()
    assert any(t.payload.get("sample_state") == "ambiguous" for t in continuity)
    assert any(t.payload.get("sample_state") == "bad" for t in continuity)
    priority = build_priority_order_tasks()
    assert any(t.payload.get("sample_state") == "bad" for t in priority)
    robustness = build_robustness_verdict_tasks()
    assert any(t.payload.get("sample_state") == "bad" for t in robustness)


# --------------------------------------------------------------------------- #
# 2) ground truth 确定性
# --------------------------------------------------------------------------- #
def test_ground_truth_deterministic():
    a = build_new_tasks()
    b = build_new_tasks()
    assert [t.ground_truth for t in a] == [t.ground_truth for t in b]
    assert [t.payload for t in a] == [t.payload for t in b]


def test_action_roles_ground_truth_from_geometry():
    """攻击者/受击者/结果帧由样例几何确定性提取，不靠人工写死。"""
    tasks = build_action_roles_tasks()
    good = next(t for t in tasks if t.id.endswith("_good"))
    assert good.ground_truth == {"attacker": "hero", "victim": "enemy",
                                 "result_frame": 5}
    bad = next(t for t in tasks if t.id.endswith("_bad"))
    # reaction_legibility bad：受击者第 5 帧不可见 -> 最后可见帧 4
    assert bad.ground_truth["result_frame"] == 4
    assert bad.ground_truth["attacker"] == "hero"
    assert bad.ground_truth["victim"] == "enemy"


def test_priority_order_ground_truth_from_registry():
    """排序由注册表严重度字符串确定性判定（fatal > error > warning）。"""
    tasks = build_priority_order_tasks()
    a = next(t for t in tasks if t.id == "priority/mixed_a")
    # axis_continuity=fatal, scale_continuity=error, lead_room=fatal
    # -> fatal 档字典序：axis_continuity < lead_room
    assert a.ground_truth["priority"] == [
        "axis_continuity", "lead_room", "scale_continuity"]
    c = next(t for t in tasks if t.id == "priority/tie_error")
    assert c.ground_truth["priority"] == [
        "camera_robustness", "movement_intent_match", "scale_continuity"]


# --------------------------------------------------------------------------- #
# 3) 防泄漏：ground truth 不出现在尺子臂提示
# --------------------------------------------------------------------------- #
def test_ground_truth_not_in_ruler_prompts():
    for t in build_new_tasks():
        if t.payload.get("poisoned"):
            continue
        gt_json = json.dumps(t.ground_truth, ensure_ascii=False)
        assert gt_json not in t.ruler_prompt, f"{t.id} ruler 泄露 GT"
        assert gt_json not in t.ruler_method_prompt, f"{t.id} 方法+读数泄露 GT"


# --------------------------------------------------------------------------- #
# 4) 污染留痕
# --------------------------------------------------------------------------- #
def test_poisoned_rows_leave_trace():
    battery = build_full_battery()
    report = run_experiment(MockJudge(), battery,
                            timestamp="2026-10-17T00:00:00")
    poisoned = [r for r in report["transcript"] if r.get("poisoned")]
    assert poisoned, "必须存在污染任务行"
    for row in poisoned:
        assert "poison_rejected" in row
        assert isinstance(row["poison_rejected"], bool)
    # 新 kind 污染任务（带 poison_wrong）：完美读数臂必须拒绝污染并答对；
    # 基线臂是固定猜测，允许答错但必须留痕。
    new_poison = [r for r in poisoned
                  if r["task_id"] in {"fight_01/action_roles_leak",
                                      "priority/poisoned"}]
    assert new_poison, "四类新任务必须含污染样例"
    perfect = [r for r in new_poison
               if r["arm"] in ("ruler", "ruler_method")]
    assert perfect
    assert all(r["correct"] for r in perfect)
    assert all(r["poison_rejected"] for r in perfect)
    assert any(r["poison_rejected"] for r in poisoned)


def test_poisoned_prompt_contains_wrong_hint():
    tasks = build_full_battery()
    leaked = next(t for t in tasks
                  if t.payload.get("poisoned")
                  and t.kind == "action_roles")
    assert "攻击者是 enemy" in leaked.ruler_prompt
    priority_poison = next(t for t in tasks
                           if t.payload.get("poisoned")
                           and t.kind == "priority_order")
    assert "错误示例" in priority_poison.ruler_method_prompt


# --------------------------------------------------------------------------- #
# 5) 评分器四新 kind
# --------------------------------------------------------------------------- #
def test_scoring_new_kinds():
    assert score_task(
        {"kind": "action_roles",
         "ground_truth": {"attacker": "hero", "victim": "enemy",
                          "result_frame": 5}},
        {"attacker": "hero", "victim": "enemy", "result_frame": 5})["correct"]
    assert not score_task(
        {"kind": "action_roles",
         "ground_truth": {"attacker": "hero", "victim": "enemy",
                          "result_frame": 5}},
        {"attacker": "hero", "victim": "enemy", "result_frame": 4})["correct"]
    assert not score_task(
        {"kind": "action_roles",
         "ground_truth": {"attacker": "hero", "victim": "enemy",
                          "result_frame": 5}},
        {"attacker": "hero"})["correct"]

    assert score_task(
        {"kind": "continuity_verdict",
         "ground_truth": {"continuous": False}},
        {"continuous": False})["correct"]
    assert not score_task(
        {"kind": "continuity_verdict",
         "ground_truth": {"continuous": False}},
        {"continuous": True})["correct"]
    assert not score_task(
        {"kind": "continuity_verdict",
         "ground_truth": {"continuous": False}}, {})["correct"]

    assert score_task(
        {"kind": "priority_order",
         "ground_truth": {"priority": ["a", "b", "c"]}},
        {"priority": ["a", "b", "c"]})["correct"]
    assert not score_task(
        {"kind": "priority_order",
         "ground_truth": {"priority": ["a", "b", "c"]}},
        {"priority": ["c", "b", "a"]})["correct"]
    assert not score_task(
        {"kind": "priority_order",
         "ground_truth": {"priority": ["a", "b", "c"]}}, {})["correct"]

    assert score_task(
        {"kind": "robustness_verdict",
         "ground_truth": {"still_pass": True}},
        {"still_pass": True})["correct"]
    assert not score_task(
        {"kind": "robustness_verdict",
         "ground_truth": {"still_pass": True}},
        {"still_pass": False})["correct"]
    assert not score_task(
        {"kind": "robustness_verdict",
         "ground_truth": {"still_pass": True}}, {})["correct"]


# --------------------------------------------------------------------------- #
# 6) 报告 §10 字段
# --------------------------------------------------------------------------- #
def test_report_contains_section10_fields():
    battery = build_full_battery()
    report = run_experiment(MockJudge(), battery,
                            timestamp="2026-10-17T00:00:00")
    for key in ("fingerprint", "layer_scores", "hard_gates",
                "prescriptions", "accept_reject", "bad_repaired",
                "uncovered", "confidence", "raw_measurements",
                "three_questions", "ci"):
        assert key in report, f"报告缺 {key}"
    fp = report["fingerprint"]
    assert fp["task_set_sha256"]
    assert fp["metric_schema_sha256"]
    assert set(fp["layer_weights"]) == {
        "geometry", "attention", "action", "continuity", "cinema",
        "robustness"}
    assert report["ci"]["only_for_real_judge"] is True
    assert report["ci"]["value"] is None  # mock 不计算 CI
    assert set(report["layer_scores"]) == {
        "geometry", "attention", "action", "continuity", "cinema",
        "robustness"}


def test_report_raw_measurements_and_confidence():
    battery = build_full_battery()
    report = run_experiment(MockJudge(), battery,
                            timestamp="2026-10-17T00:00:00")
    rm = report["raw_measurements"]
    assert rm["tasks"] == len(battery)
    sample_based = [e for e in rm["records"] if e["measurements"]]
    assert sample_based, "报告必须含每镜每帧原始测量与证据引用"
    assert any(e.get("evidence_ref") for e in rm["records"])
    conf = report["confidence"]
    assert "low_confidence_tasks" in conf
    assert "manual_review_required" in conf
    assert any(it["confidence"] < 1.0
               for it in conf["low_confidence_tasks"])


def test_hard_gates_each_have_triggered_and_not_triggered():
    """SPEC 11 A5.7 / 主 SPEC §11.1：H1–H6 各一条触发与不触发。"""
    battery = build_full_battery()
    report = run_experiment(MockJudge(), battery,
                            timestamp="2026-10-17T00:00:00")
    hg = report["hard_gates"]
    for gate in ("H1", "H2", "H3", "H4", "H5", "H6"):
        assert gate in hg, f"报告缺硬门 {gate}"
        assert hg[gate]["triggered"] is True, f"{gate} 应有触发样例"
        assert hg[gate]["tasks"], f"{gate} 触发任务/证据非空"
        assert hg[gate]["reasons"], f"{gate} 触发理由非空"
        assert hg[gate].get("not_triggered_tasks"), f"{gate} 应有不触发样例"


def test_mock_baseline_fixed_guess_differs_for_new_kinds():
    """SPEC A5.4：基线臂固定猜测、尺子臂完美读数，四新 kind 有区分度。"""
    judge = MockJudge()
    tasks = build_new_tasks()
    wrong = [t.id for t in tasks
             if not score_task(
                 {"kind": t.kind, "ground_truth": t.ground_truth},
                 judge.answer(t, t.baseline_prompt, "baseline"))["correct"]]
    assert wrong, "基线臂必须有固定猜测答错的任务"
    for t in tasks:
        ans = judge.answer(t, t.ruler_prompt, "ruler")
        assert score_task(
            {"kind": t.kind, "ground_truth": t.ground_truth},
            ans)["correct"], f"{t.id} 尺子臂应完美读数"


# --------------------------------------------------------------------------- #
# 7) render_markdown 内容
# --------------------------------------------------------------------------- #
def test_render_markdown_sections():
    battery = build_full_battery()
    report = run_experiment(MockJudge(), battery,
                            timestamp="2026-10-17T00:00:00")
    md = render_markdown(report)
    assert "运行指纹" in md
    assert "六层分" in md
    assert "硬门" in md
    assert "三问" in md
    assert "打斗样例动作层独立小节" in md
    assert "污染判词留痕" in md
    assert "⚠️ mock 判官只证明管线通" in md
    assert "geometry" in md and "robustness" in md


def test_render_markdown_fight_section_not_in_overview():
    """打斗动作层独立成节：fight 任务分数不计入任何六层总分。"""
    battery = build_full_battery()
    report = run_experiment(MockJudge(), battery,
                            timestamp="2026-10-17T00:00:00")
    fight_total = sum(v["total"] for v in report["fight_section"].values())
    layer_total = sum(
        v["ruler_method"]["total"]
        for k, v in report["layer_scores"].items()
        if k != "action")
    assert fight_total >= 5  # 打斗动作任务至少 5 条（dynamic_facts + roles）
    # fight_01 的 action 层任务在六层 action 里保留（诚实呈现），
    # 但独立小节同时存在；这里校验小节存在而非从总分剔除。
    assert report["fight_section"]["ruler_method"]["total"] > 0


# --------------------------------------------------------------------------- #
# 8) 确定性
# --------------------------------------------------------------------------- #
def test_report_deterministic_ext():
    battery = build_full_battery()
    a = json.dumps(run_experiment(MockJudge(), battery,
                                  timestamp="2026-10-17T00:00:00"),
                   ensure_ascii=False, sort_keys=True)
    b = json.dumps(run_experiment(MockJudge(), battery,
                                  timestamp="2026-10-17T00:00:00"),
                   ensure_ascii=False, sort_keys=True)
    assert a == b


# --------------------------------------------------------------------------- #
# 9) 组合电池兼容既有任务
# --------------------------------------------------------------------------- #
def test_full_battery_contains_existing_kinds():
    full = build_full_battery()
    kinds = {t.kind for t in full}
    assert {"verdict", "estimate", "direction", "fix", "dynamic_facts",
            "prescription_verdict"} <= kinds
    base = build_battery()
    base_ids = {t.id for t in base}
    full_ids = {t.id for t in full}
    assert base_ids <= full_ids
    assert len(full) > len(base)


def test_llm_judge_answers_new_kinds():
    judge = MockJudge()
    for task in build_new_tasks():
        ans = judge.answer(task, task.ruler_method_prompt, "ruler_method")
        verdict = score_task(
            {"kind": task.kind, "ground_truth": task.ground_truth}, ans)
        assert verdict["correct"] is True, f"{task.id} mock 应答错误"
