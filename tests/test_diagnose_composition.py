"""B1（D-04）：构图门归因诊断工具的纯层测试（零 bpy）。

只测 ``tools/diagnose_composition.py`` 的纯函数：日志解析、最终计划重建、
三类归因判定与报告渲染。归因判定用**合成输入**逐类钉死，不依赖 Blender。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import diagnose_composition as diag  # noqa: E402


def evidence(**overrides) -> diag.ShotEvidence:
    base = dict(
        shot_id="shot_001",
        shot_type="MS",
        side="front",
        lens=50.0,
        recorded_score=60.3,
        replayed_score=60.3,
        threshold=70.0,
        subject_xy=(3.95, 0.0),
        subject_z=0.0,
        extent_m=12.0,
        camera_xyz=(3.95, 4.63, 1.4),
        target_xyz=(3.95, 0.0, 1.55),
        solver_position=(3.95, 4.63, 1.4),
        solver_distance=4.63,
        solver_clamped=False,
        actual_distance=4.72,
        required_distance=4.63,
        frame_width=3.4,
        components={"headroom": 1.0, "lead_room": 0.75,
                    "rule_of_thirds": 0.05, "balance": 1.0,
                    "occlusion": 1.0, "framing": 0.85},
        measurements_available=True,
    )
    base.update(overrides)
    return diag.ShotEvidence(**base)


def test_module_imports_without_bpy():
    assert "bpy" not in sys.modules
    assert diag.ATTRIBUTION_CLASSES == (
        "camera_misplaced", "solver_no_solution",
        "script_scale_exceeds_extent")


def test_cli_accepts_code_dir_for_faithful_replay():
    args = diag.parse_cli(["run_dir", "--code-dir", "C:/tmp/tree",
                           "--no-blender"])
    assert args.run_dir == "run_dir"
    assert args.code_dir == "C:/tmp/tree"
    assert args.no_blender is True


def test_classify_requires_measurements():
    with pytest.raises(ValueError, match="缺少 Blender 测量"):
        diag.classify(evidence(measurements_available=False))


def test_classify_script_scale_exceeds_extent_by_subject_position():
    attribution = diag.classify(
        evidence(subject_xy=(13.1, 0.0)))
    assert attribution.klass == diag.CLASS_SCRIPT_SCALE_EXCEEDS_EXTENT
    assert attribution.evidence["subject_xy"] == [13.1, 0.0]
    assert attribution.evidence["extent_m"] == 12.0


def test_classify_script_scale_exceeds_extent_by_declared_walk_target():
    attribution = diag.classify(
        evidence(subject_xy=(2.0, 0.0),
                 declared_target_out_of_extent=True,
                 declared_targets=[(14.0, 0.0)]))
    assert attribution.klass == diag.CLASS_SCRIPT_SCALE_EXCEEDS_EXTENT
    assert attribution.evidence["declared_target_out_of_extent"] is True
    assert attribution.evidence["declared_targets"] == [[14.0, 0.0]]


def test_classify_camera_misplaced_by_position_gap():
    # 求解器按实际站位会摆到 (3.95, 4.63)，实际机位却在原点附近：瞄的是旧锚点。
    attribution = diag.classify(
        evidence(camera_xyz=(0.0, 0.0, 1.4),
                 solver_position=(3.95, 4.63, 1.4)))
    assert attribution.klass == diag.CLASS_CAMERA_MISPLACED
    reasons = attribution.evidence["reasons"]
    assert any("camera_vs_solver_m" in reason for reason in reasons)


def test_classify_camera_misplaced_by_aim_target_gap():
    # 机位对、距离对，但首帧目标点离开主体超过 1/3 幅宽：瞄准点不对。
    attribution = diag.classify(
        evidence(target_xyz=(6.95, 0.0, 1.55), frame_width=3.4))
    assert attribution.klass == diag.CLASS_CAMERA_MISPLACED
    reasons = attribution.evidence["reasons"]
    assert any("target_to_subject_m" in reason for reason in reasons)


def test_classify_camera_misplaced_by_distance_deviation():
    # 景别要求 4.63 m，实际站到 8 m 外：偏差 0.73 > R009 的 0.25 容差。
    attribution = diag.classify(evidence(actual_distance=8.0))
    assert attribution.klass == diag.CLASS_CAMERA_MISPLACED
    reasons = attribution.evidence["reasons"]
    assert any("distance_deviation_ratio" in reason for reason in reasons)


def test_legitimate_lead_room_offset_is_not_misplaced():
    # 合法视线留白 = 1/6 幅宽：不许把正常取景判成"瞄错"。
    offset = 3.4 / 6.0
    attribution = diag.classify(
        evidence(target_xyz=(3.95 + offset, 0.0, 1.55),
                 frame_width=3.4))
    assert attribution.klass == diag.CLASS_SOLVER_NO_SOLUTION


def test_classify_solver_no_solution_when_room_clamped():
    attribution = diag.classify(
        evidence(solver_clamped=True, room=(-3.0, 3.0, -3.0, 3.0),
                 solver_distance=4.63))
    assert attribution.klass == diag.CLASS_SOLVER_NO_SOLUTION
    assert attribution.evidence["solver_clamped"] is True
    assert attribution.evidence["room"] == [-3.0, 3.0, -3.0, 3.0]


def test_classify_solver_no_solution_residual():
    # 机位/目标点/距离全部与求解器一致，却仍然低于门：这组参数无解。
    attribution = diag.classify(evidence())
    assert attribution.klass == diag.CLASS_SOLVER_NO_SOLUTION
    assert attribution.evidence["camera_matches_solver"] is True
    assert attribution.evidence["replayed_score"] == 60.3
    assert attribution.evidence["components"]["rule_of_thirds"] == 0.05


def test_attribution_never_suggests_loosening_threshold():
    for klass in diag.ATTRIBUTION_CLASSES:
        card = diag.fix_card_for(klass)
        assert "PASS_SCORE" not in card or "不动 PASS_SCORE" in card
        assert "放宽" not in card
        assert "降低阈值" not in card


def _shot_audit(shot_id, score, finding_code):
    rule = "COMPOSITION" if finding_code == "E_CAM_001" else "R001"
    return {
        "ts": 1.0, "level": "warning", "kind": "shot_audit",
        "message": "审核结果", "data": {
            "shot": shot_id, "passed": score >= 70.0, "errors": 0,
            "warnings": 0, "rule_ids": [rule],
            "findings": [{
                "code": finding_code, "rule": rule,
                "severity": "error", "target": shot_id,
                "message": f"构图评分 {score}", "suggestion": "x",
            }],
            "composition_score": score, "composition_threshold": 70.0,
            "justification_audit": {},
        },
    }


def _base_plan_payload():
    return {
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "定场",
             "intent_type": "铺垫", "shot_type": "LS", "duration_frames": 120,
             "characters": [], "dialogue_ids": [], "axis_note": "",
             "continuity_in": "", "prompt": ""},
            {"shot_id": "shot_002", "order": 2, "intent": "出场",
             "intent_type": "铺垫", "shot_type": "CU", "duration_frames": 96,
             "characters": ["甲"], "dialogue_ids": [], "axis_note": "",
             "continuity_in": "", "prompt": ""},
        ],
        "scene_heading": "测试场",
    }


def _write_run(tmp_path, audit_records, trace_records=None):
    (tmp_path / "audit_log.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False)
                  for record in audit_records), encoding="utf-8")
    if trace_records is not None:
        (tmp_path / "llm_trace.jsonl").write_text(
            "\n".join(json.dumps(record, ensure_ascii=False)
                      for record in trace_records), encoding="utf-8")
    return tmp_path


def test_failing_shots_extraction_dedupes_and_keeps_last_score(tmp_path):
    records = [
        {"ts": 1.0, "kind": "tool_call", "data": {
            "tool": "emit_plan", "ok": True,
            "args": _base_plan_payload()}},
        _shot_audit("shot_001", 80.0, "E_AXIS_001"),
        _shot_audit("shot_002", 46.4, "E_CAM_001"),
        _shot_audit("shot_002", 60.3, "E_CAM_001"),
        _shot_audit("shot_003", 30.4, "E_CAM_001"),
    ]
    plan, _, _ = diag.rebuild_plan(records)
    failing = diag.failing_shots(records, plan)
    assert [item["shot_id"] for item in failing] == ["shot_002", "shot_003"]
    assert failing[0]["recorded_score"] == 60.3  # 取最后一次审核的分
    assert failing[0]["audit_count"] == 2
    assert failing[1]["recorded_score"] == 30.4


def test_rebuild_plan_merges_accepted_draft_and_rejects_invalid(tmp_path):
    valid_draft = {
        "shot_id": "shot_002", "shot_type": "CU", "characters": ["甲"],
        "camera": {"side": "front_left", "lens": 85},
        "actions": [{"character_id": "甲", "action_type": "turn_head",
                     "start_frame": 1, "end_frame": 10,
                     "params": {"angle_deg": -10}}],
    }
    invalid_draft = {
        "shot_id": "shot_002", "shot_type": "CU", "characters": ["甲"],
        "actions": [{"character_id": "甲", "action_type": "turn_head",
                     "start_frame": 1, "end_frame": 10,
                     "params": {"bogus_key": 1}}],
    }
    records = [
        {"ts": 1.0, "kind": "tool_call", "data": {
            "tool": "emit_plan", "ok": True,
            "args": _base_plan_payload()}},
    ]
    trace = [
        {"ts": 2.0, "purpose": "editor",
         "response": {"tool_calls": [{"name": "emit_shot_draft",
                                      "arguments": json.dumps(valid_draft)}]}},
        {"ts": 3.0, "purpose": "editor",
         "response": {"tool_calls": [{"name": "emit_shot_draft",
                                      "arguments": json.dumps(invalid_draft)}]}},
    ]
    run_dir = _write_run(tmp_path, records, trace)
    plan, events, source = diag.rebuild_plan(
        diag.read_audit_log(run_dir), diag.read_jsonl_lines(
            run_dir / "llm_trace.jsonl"))
    assert source == "emit_plan"
    shot = next(item for item in plan.shots if item.shot_id == "shot_002")
    assert shot.camera == {"side": "front_left", "lens": 85}
    assert len(shot.actions) == 1
    accepted = [event for event in events if event["accepted"]]
    rejected = [event for event in events if not event["accepted"]]
    assert len(accepted) == 1 and len(rejected) == 1
    assert "不认识的参数" in rejected[0]["reason"]


def test_rebuild_plan_prefers_plan_received_event(tmp_path):
    plan_received = {
        "shots": [{"shot_id": "shot_009", "order": 1, "intent": "x",
                   "intent_type": "铺垫", "shot_type": "MS",
                   "duration_frames": 60, "characters": ["甲"],
                   "dialogue_ids": [], "axis_note": "", "continuity_in": "",
                   "prompt": ""}],
        "scene_heading": "plan_received 场",
    }
    records = [
        {"ts": 1.0, "kind": "plan_received", "data": {"plan": plan_received}},
        {"ts": 2.0, "kind": "tool_call", "data": {
            "tool": "emit_plan", "ok": True,
            "args": _base_plan_payload()}},
    ]
    run_dir = _write_run(tmp_path, records)
    plan, _, source = diag.rebuild_plan(diag.read_audit_log(run_dir))
    assert source == "plan_received"
    assert [shot.shot_id for shot in plan.shots] == ["shot_009"]


def test_rebuild_plan_raises_when_no_plan_event():
    records = [{"ts": 1.0, "kind": "run_started", "data": {}}]
    with pytest.raises(diag.ReplayError, match="无法零 LLM 重建计划"):
        diag.rebuild_plan(records)


def test_declared_walk_targets_only_counts_walk_actions(tmp_path):
    plan_payload = _base_plan_payload()
    plan_payload["shots"][1]["actions"] = [
        {"character_id": "甲", "action_type": "walk_to",
         "target_position": [13.0, 0.0, 0.0]},
        {"character_id": "甲", "action_type": "look_at",
         "target_position": [2.1, 1.5, 0.2]},
        {"character_id": "甲", "action_type": "run_to",
         "target_position": [0.0, 12.5, 0.0]},
    ]
    records = [{"ts": 1.0, "kind": "tool_call", "data": {
        "tool": "emit_plan", "ok": True, "args": plan_payload}}]
    plan, _, _ = diag.rebuild_plan(records)
    declared = diag.declared_walk_targets(plan, 12.0)
    assert declared["shot_002"] == [(13.0, 0.0), (0.0, 12.5)]


def test_attribution_distribution_and_markdown(tmp_path):
    def row(shot_id, klass):
        if klass == "camera_misplaced":
            attribution = {"class": klass, "evidence": {"reasons": [
                {"camera_vs_solver_m": 0.5962,
                 "camera_xyz": [6.62, 2.75, 1.32],
                 "solver_position": [7.08, 3.13, 1.28]}]},
                "fix_card": diag.fix_card_for(klass)}
        else:
            attribution = {"class": klass, "evidence": {},
                           "fix_card": diag.fix_card_for(klass)}
        return {
            "shot_id": shot_id,
            "shot_type": "MS",
            "recorded_score": 46.4,
            "replayed_score": 46.4,
            "target_gap_m": 0.2,
            "threshold": 70.0,
            "evidence": {
                "subject_xy": [3.95, 0.0],
                "camera_xyz": [3.95, 4.63, 1.4],
                "lens": 50.0,
                "target_xyz": [3.95, 0.0, 1.55],
                "components": {"headroom": 1.0, "lead_room": 0.75,
                               "rule_of_thirds": 0.05, "balance": 1.0,
                               "occlusion": 1.0, "framing": 0.85},
                "per_frame_scores": [{"frame": 1, "score": 71.7},
                                     {"frame": 60, "score": 46.4}],
                "component_items": {"headroom": {"score": 0.0},
                                    "rule_of_thirds": {"score": 0.0}},
            },
            "attribution": attribution,
        }
    rows = [
        row("shot_002", "camera_misplaced"),
        row("shot_003", "solver_no_solution"),
        row("shot_004", "script_scale_exceeds_extent"),
    ]
    distribution = diag.attribution_distribution(rows)
    assert distribution == {
        "camera_misplaced": ["shot_002"],
        "solver_no_solution": ["shot_003"],
        "script_scale_exceeds_extent": ["shot_004"],
    }
    markdown = diag.render_markdown(
        pathlib.Path("."), "emit_plan", [], [], rows, [], [], 12.0)
    assert "归因分布与修卡去向" in markdown
    assert "camera_misplaced" in markdown
    assert "solver_no_solution" in markdown
    assert "script_scale_exceeds_extent" in markdown
    assert "卡 D-12" in markdown
    assert "extent_m" in markdown
    assert "camera_vs_solver_m" in markdown
    assert "逐镜根因注记" in markdown
    assert f"PASS_SCORE 保持 {diag.PASS_SCORE:g}" in markdown
    assert "放宽" not in markdown
    assert "降低阈值" not in markdown


def test_root_note_reports_weak_items_and_first_frame_gap():
    evidence_dict = {
        "component_items": {
            "headroom": {"score": 0.0},
            "framing": {"score": 0.19},
            "occlusion": {"score": 1.0},
        },
        "per_frame_scores": [{"frame": 121, "score": 71.7},
                             {"frame": 216, "score": 46.9}],
        "declared_movements": [{"type": "dolly_in", "amount": 0.6}],
    }
    note = diag.root_note(evidence_dict, 70.0)
    assert "headroom=0.00" in note
    assert "framing=0.19" in note
    assert "首帧 71.7 已达门" in note
    assert "dolly_in 0.6" in note


def test_root_note_does_not_treat_exact_threshold_as_passing():
    note = diag.root_note(
        {
            "component_items": {},
            "per_frame_scores": [{"frame": 1, "score": 80.0}],
        },
        80.0,
    )

    assert "已达门" not in note
    assert "未严格高于门 80" in note
