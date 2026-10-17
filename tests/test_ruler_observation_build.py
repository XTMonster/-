"""Ticket 04：Blender 测量序列化（生产折档，纯层无 bpy）。

把现有运行产物（plan / parsed / brief / audit_results / build_results）折成
空间尺观测 v2 文档：shot_specs / camera_specs / measurements / verdicts /
prescriptions。本测试钉住：
* 产物通过已入库 schema（jsonschema）校验；
* 来源四态闭合（source == provenance）、verdict 三件套、处方闭集、
  evidence 引用闭合；
* 确定性：同样输入两次调用逐字节相同；
* 观测用 fixture 取自真实 dock-market 运行口径（16s / 4 镜 / 3 角色）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import jsonschema

from block_director.contracts.audit import AuditError
from block_director.contracts.enums import Severity
from block_director.contracts.plan import Plan, Responsibility, ShotPlan
from block_director.layer1_input.model import (
    ParsedNodeDeclaration,
    ParsedScript,
    ParsedShotDeclaration,
)
from block_director.layer5_orchestrator.ruler_observation import (
    build_observation,
    validate_observation,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (ROOT / "block_director" / "contracts" / "spatial_ruler"
               / "schema" / "spatial-ruler-observation.v1.schema.json")
FPS = 24


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


class _Brief:
    """SceneBrief 的测试替身（只带空间尺消费的字段）。"""

    speakers = [{"speaker": "米迦尔", "listener": "伊恩"}]
    gaze = [{"from": "米迦尔", "to": "偷盗者"}]
    space = [{"character": "偷盗者", "relative_to": "伊恩"}]


def _parsed() -> ParsedScript:
    specs = [
        (1, 5.0, "ELS", []),
        (2, 4.0, "MS", ["米迦尔"]),
        (3, 3.5, "MCU", ["伊恩"]),
        (4, 3.5, "MCU", ["米迦尔"]),
    ]
    shots = [
        ParsedShotDeclaration(number, declared_seconds=seconds,
                              shot_type=shot_type, characters=list(chars))
        for number, seconds, shot_type, chars in specs
    ]
    return ParsedScript(
        title="码头市场", source_format="text",
        declared_nodes=[ParsedNodeDeclaration(
            node_number=1, title="用户节点", declared_seconds=16.0,
            shots=shots)])


def _plan() -> Plan:
    plan = Plan(scene_heading="码头市场")
    plan.shots = [
        ShotPlan("shot_001", "建立", "ELS", 120, order=1,
                 camera={"lens": 24},
                 characters=["米迦尔", "伊恩", "偷盗者"],
                 responsibility=Responsibility(
                     white_model=["米迦尔", "伊恩", "偷盗者"])),
        ShotPlan("shot_002", "推进", "MS", 96, order=2,
                 camera={"lens": 35, "side": "front_left"},
                 characters=["米迦尔"],
                 responsibility=Responsibility(white_model=["米迦尔"])),
        ShotPlan("shot_003", "对白", "MCU", 84, order=3,
                 camera={"lens": 50, "side": "front_left"},
                 characters=["伊恩"],
                 responsibility=Responsibility(white_model=["伊恩"])),
        ShotPlan("shot_004", "反应", "MCU", 84, order=4,
                 camera={"lens": 35, "side": "front_right"},
                 characters=["米迦尔"],
                 responsibility=Responsibility(white_model=["米迦尔"])),
    ]
    return plan


def _guard_warning(shot_id: str, kind: str, subject: str,
                   evidence: Dict[str, Any],
                   severity: str = "warning") -> Dict[str, Any]:
    return {
        "shot_id": shot_id, "frame_range": [0, 1], "type": kind,
        "subject": subject, "evidence": evidence, "severity": severity,
        "confidence": "high", "declared_intent": "",
        "suggestion_hint": "结构化修复提示",
    }


def _audits() -> Dict[str, Dict[str, Any]]:
    return {
        "shot_001": {
            "passed": False, "score": 64.7, "errors": [], "warnings": [],
            "guard_warnings": [],
        },
        "shot_002": {
            "passed": False, "score": 51.4, "errors": [], "warnings": [],
            "guard_warnings": [
                _guard_warning(
                    "shot_002", "subject_not_visible", "米迦尔",
                    {"visible_ratio": 0.0, "frames": 22}, severity="error"),
                _guard_warning(
                    "shot_002", "edge_clip", "米迦尔",
                    {"edge_clip": 0.1975, "edge_clip_max": 0.10}),
                _guard_warning(
                    "shot_002", "framing_too_tight", "米迦尔",
                    {"body_height_ratio": 1.1933,
                     "expected_range": [0.55, 0.7]}),
            ],
        },
        "shot_003": {
            "passed": True, "score": 73.6, "errors": [], "warnings": [],
            "guard_warnings": [
                _guard_warning(
                    "shot_003", "jump_cut_risk", "scene",
                    {"previous_shot": "shot_002", "size_diff": 0.02,
                     "angle_diff_deg": 15.5, "jump_cut_size_diff": 0.10,
                     "jump_cut_angle_deg": 30.0}),
            ],
        },
        "shot_004": {
            "passed": True, "score": 79.2, "errors": [], "warnings": [],
            "guard_warnings": [
                _guard_warning(
                    "shot_004", "jump_cut_risk", "scene",
                    {"previous_shot": "shot_003", "size_diff": 0.01,
                     "angle_diff_deg": 24.8, "jump_cut_size_diff": 0.10,
                     "jump_cut_angle_deg": 30.0}),
            ],
        },
    }


def _audits_with_rules() -> Dict[str, Dict[str, Any]]:
    """带原审核器规则 findings（errors/warnings）的审核字典。"""
    audits = _audits()
    audits["shot_001"] = {
        "passed": False, "score": 64.7, "errors": [], "warnings": [],
        "guard_warnings": [],
    }
    audits["shot_002"] = {
        "passed": False, "score": 51.4,
        "errors": [{
            "rule": "R002", "code": "E_SPACE_001",
            "message": "角色与道具 AABB 穿模",
            "severity": "error", "target": "米迦尔",
            "suggestion": "move_character 移开",
            "frame": 0,
        }],
        "warnings": [{
            "rule": "R010", "code": "E_AXIS_001",
            "message": "相邻镜同景别同角度缺乏变化",
            "severity": "warning", "target": "shot_002",
            "suggestion": "改变机位角度或景别一档",
            "frame": 0,
        }],
        "guard_warnings": [
            _guard_warning(
                "shot_002", "subject_not_visible", "米迦尔",
                {"visible_ratio": 0.0, "frames": 22}, severity="error"),
        ],
    }
    return audits


def _build_results() -> Dict[str, Dict[str, Any]]:
    """只给 shot_004 实测坐标：其余镜 source=plan_intent（诚实标 null）。"""
    return {
        "shot_001": {"lens": 24.0},
        "shot_002": {"lens": 35.0},
        "shot_003": {"lens": 50.0},
        "shot_004": {"lens": 35.0, "camera_position": [3.0, -2.5, 1.6],
                     "camera_target": [0.0, 0.5, 1.0]},
    }


def _findings() -> List[AuditError]:
    return [
        AuditError(rule="SR001", message="角色已从 white_model 恢复",
                   severity=Severity.WARNING, target="shot_001"),
        AuditError(rule="SR002", message="全场时长 16s 与声明一致",
                   severity=Severity.WARNING),
    ]


def _build(plan: Plan | None = None) -> Dict[str, Any]:
    return build_observation(
        plan=plan or _plan(),
        parsed=_parsed(),
        brief=_Brief(),
        shot_audits=_audits(),
        build_results=_build_results(),
        fps=FPS,
        run_context={"source_run": "fixture", "model": "pytest",
                     "status": "completed_with_repairs",
                     "summary": {"shots": 4, "characters": 3}},
        observation_id="obs-dock-market-fixture",
        plan_findings=_findings())


def _camera_applied() -> List[Dict[str, Any]]:
    """一条已实际执行的相机处方（转正：驱动自动 reframe 后回写）。"""
    return [{
        "prescription_id": "p_shot_002_subject_not_visible",
        "shot_id": "shot_002",
        "operation": "reframe",
        "parameters": {"reason": "subject_not_visible", "target": "米迦尔",
                       "old_lens": 35.0, "new_lens": 25.2},
        "precondition_measurement_ids": ["m_shot_002_visibility_ratio"],
        "postcondition_measurement_ids": ["m_shot_002_composition_score"],
        "postcondition": "全镜 visible_ratio > 0 且 composition_score > 80",
        "applied": True, "applied_at": "2026-10-18T00:00:00+08:00",
        "waived": False, "waive_reason": "",
    }]


# --------------------------------------------------------------------------- #
# schema 与结构
# --------------------------------------------------------------------------- #
def test_observation_validates_against_committed_schema():
    doc = _build()
    jsonschema.validate(instance=doc, schema=_schema())


def test_top_level_families_present():
    doc = _build()
    assert doc["schema_version"] == "spatial-ruler-observation/v2"
    assert doc["plugin_adapter"]["integration_status"] == "full_pre_build"
    assert doc["observation_request"]["fps"] == FPS
    assert len(doc["shot_specs"]) == 4
    assert len(doc["camera_specs"]) == 4


def test_rule_findings_fold_into_verdicts():
    """原审核器的规则 errors/warnings 必须折进观测 verdicts。"""
    doc = build_observation(
        plan=_plan(), parsed=_parsed(), brief=_Brief(),
        shot_audits=_audits_with_rules(), build_results=_build_results(),
        fps=FPS, run_context={"source_run": "fixture", "status": "completed",
                              "summary": {"shots": 4}},
        plan_findings=_findings())
    rules = {item["rule_code"] for item in doc["verdicts"]}
    #: R002（穿模 error）与 R010（跳切 warning）来自原审核器规则层。
    assert "R002" in rules, rules
    assert "R010" in rules, rules
    r002 = [v for v in doc["verdicts"] if v["rule_code"] == "R002"]
    assert r002 and r002[0]["status"] == "repair"
    assert r002[0]["severity"] == "error"
    r010 = [v for v in doc["verdicts"] if v["rule_code"] == "R010"]
    assert r010 and r010[0]["status"] == "warning"
    #: 带规则 findings 的观测文档必须同时通过 schema 与纯层校验。
    jsonschema.validate(doc, _schema())
    assert validate_observation(doc) == []


def test_rule_findings_from_log_preserve_warnings():
    """重放折档必须保留原审核器的 warnings，不得恒置空。"""
    from block_director.layer5_orchestrator.ruler_observation import (
        shot_audits_from_log)
    records = [{
        "kind": "shot_audit",
        "data": {
            "shot": "shot_002", "passed": False,
            "composition_score": 51.4,
            "findings": [
                {"rule": "R002", "code": "E_SPACE_001",
                 "message": "角色与道具 AABB 穿模", "severity": "error",
                 "target": "米迦尔", "suggestion": "move_character 移开",
                 "frame": 0},
                {"rule": "R010", "code": "E_AXIS_001",
                 "message": "相邻镜同景别同角度缺乏变化", "severity": "warning",
                 "target": "shot_002",
                 "suggestion": "改变机位角度或景别一档", "frame": 0},
            ],
        },
    }]
    audits = shot_audits_from_log(records)
    entry = audits["shot_002"]
    assert entry["errors"], entry
    assert entry["warnings"], entry
    assert {w["rule"] for w in entry["warnings"]} == {"R010"}


# --------------------------------------------------------------------------- #
# shot_specs / camera_specs
# --------------------------------------------------------------------------- #
def test_shot_specs_carry_declared_vs_planned():
    doc = _build()
    first = doc["shot_specs"][0]
    assert first["shot_id"] == "shot_001"
    assert first["declared"]["seconds"] == 5.0
    assert first["declared"]["frames"] == 120
    assert first["planned"]["seconds"] == 5.0
    assert first["planned"]["frames"] == 120
    assert first["planned"]["characters"] == ["米迦尔", "伊恩", "偷盗者"]


def test_camera_spec_source_plan_intent_vs_blender_geometry():
    doc = _build()
    by_id = {item["shot_id"]: item for item in doc["camera_specs"]}
    assert by_id["shot_001"]["source"] == "plan_intent"
    assert by_id["shot_001"]["position"] is None
    assert by_id["shot_001"]["lens"] == 24.0
    assert by_id["shot_004"]["source"] == "blender_geometry"
    assert by_id["shot_004"]["position"] == [3.0, -2.5, 1.6]
    assert by_id["shot_004"]["lens"] == 35.0


# --------------------------------------------------------------------------- #
# measurements
# --------------------------------------------------------------------------- #
def test_measurements_cover_duration_composition_and_guard():
    doc = _build()
    metrics = {(m["shot_id"], m["metric"])
               for m in doc["measurements"]}
    assert ("scene", "total_duration") in metrics
    assert ("shot_001", "duration") in metrics
    assert ("shot_002", "composition_score") in metrics
    # guard 数值证据被折成测量：可见性 / 裁切 / 跳切角差
    assert ("shot_002", "visibility_ratio") in metrics
    assert ("shot_002", "edge_clip") in metrics
    assert ("shot_003", "camera_angle_deg") in metrics


def test_measurement_provenance_closed_and_matching_source():
    doc = _build()
    allowed = {"script_declaration", "plan_intent",
               "algorithmic_measurement", "blender_geometry"}
    for m in doc["measurements"]:
        assert m["source"] in allowed
        assert m["provenance"] == m["source"]
        assert m["measurement_id"]
        assert m["unit"]


# --------------------------------------------------------------------------- #
# verdicts
# --------------------------------------------------------------------------- #
def test_verdicts_carry_numeric_pairs_and_closed_status():
    doc = _build()
    statuses = {v["status"] for v in doc["verdicts"]}
    assert statuses <= {"pass", "warning", "repair", "blocked"}
    composition = [v for v in doc["verdicts"] if v["rule_code"] == "COMPOSITION"]
    assert composition
    repair = [v for v in composition if v["status"] == "repair"]
    assert any(v["shot_id"] == "shot_002" for v in repair)
    transition = [v for v in doc["verdicts"] if v["rule_code"] == "R010"]
    assert transition and all(v["threshold"] == 30.0 for v in transition)


def test_composition_verdict_strictly_above_pass_score():
    """用户 2026-10-18 裁决：构图分必须严格高于 80，等于 80.0 不算过。"""
    from block_director.layer5_orchestrator.ruler_observation import (
        build_observation)
    from block_director.contracts.plan import Plan, ShotPlan

    def one_shot(score: float) -> Dict[str, Any]:
        plan = Plan(scene_heading="边界")
        plan.shots = [
            ShotPlan("shot_001", "边界", "MCU", 24, order=1,
                     camera={"lens": 50}, characters=["甲"],
                     responsibility=Responsibility(white_model=["甲"]))]
        return build_observation(
            plan=plan, parsed=_parsed(), brief=_Brief(),
            shot_audits={"shot_001": {
                "passed": False, "score": score,
                "errors": [], "warnings": [], "guard_warnings": []}},
            build_results={"shot_001": {"lens": 50.0}},
            fps=FPS,
            run_context={"source_run": "fixture", "status": "completed",
                         "summary": {"shots": 1}},
            plan_findings=[])

    for score in (79.99, 80.0):
        doc = one_shot(score)
        comp = [v for v in doc["verdicts"] if v["rule_code"] == "COMPOSITION"]
        assert comp and comp[0]["status"] == "repair", f"{score} 不应通过"
        assert comp[0]["severity"] == "error"
    doc = one_shot(80.01)
    comp = [v for v in doc["verdicts"] if v["rule_code"] == "COMPOSITION"]
    assert comp and comp[0]["status"] == "pass", "80.01 应通过"
    assert comp[0]["severity"] == "info"


def test_verdict_evidence_references_existing_measurements_or_events():
    doc = _build()
    measurement_ids = {m["measurement_id"] for m in doc["measurements"]}
    for verdict in doc["verdicts"]:
        for ref in verdict["evidence"]:
            assert ref in measurement_ids, (
                f"{verdict['verdict_id']} 证据引用不存在：{ref}")


# --------------------------------------------------------------------------- #
# prescriptions
# --------------------------------------------------------------------------- #
def test_prescriptions_allow_list_and_lifecycle():
    doc = _build()
    allowed = {"retime_shot", "restore_cast", "reframe", "move_character",
               "change_camera_side", "review_transition"}
    ops = {p["operation"] for p in doc["prescriptions"]}
    assert ops <= allowed
    by_op = {p["operation"]: p for p in doc["prescriptions"]}
    assert by_op["restore_cast"]["applied"] is True
    assert by_op["review_transition"]["applied"] is False
    for p in doc["prescriptions"]:
        for ref in (p["precondition_measurement_ids"]
                    + p["postcondition_measurement_ids"]):
            assert ref, f"{p['prescription_id']} 前后置引用不能为空串"


def test_applied_camera_prescription_merged_and_marks_full():
    """已执行相机处方合并进观测：applied=True，integration_status 升 full。"""
    doc = _build()
    #: 默认生成阶段：同镜同操作 reframe 是未应用版本，integration 非 full。
    by_id = {p["prescription_id"]: p for p in doc["prescriptions"]}
    assert by_id["p_shot_002_subject_not_visible"]["applied"] is False
    #: 注入已应用版本（驱动自动 reframe 后回写），观察合并结果。
    doc2 = build_observation(
        plan=_plan(), parsed=_parsed(), brief=_Brief(),
        shot_audits=_audits(), build_results=_build_results(), fps=FPS,
        run_context={"source_run": "fixture", "status": "completed",
                     "summary": {"shots": 4}},
        plan_findings=_findings(),
        applied_prescriptions=_camera_applied())
    by_id = {p["prescription_id"]: p for p in doc2["prescriptions"]}
    merged = by_id["p_shot_002_subject_not_visible"]
    assert merged["applied"] is True
    assert merged["operation"] == "reframe"
    assert doc2["plugin_adapter"]["integration_status"] == "full"
    #: 同镜同类型的默认处方（未应用）不得与已应用版本并存，避免自相矛盾。
    applied = [p for p in doc2["prescriptions"]
               if p["prescription_id"] == "p_shot_002_subject_not_visible"]
    assert len(applied) == 1, applied
    assert applied[0]["applied"] is True
    assert {p["prescription_id"] for p in doc2["prescriptions"]
            if p["shot_id"] == "shot_002" and p["operation"] == "reframe"} >= {
        "p_shot_002_edge_clip", "p_shot_002_framing_too_tight"}
    #: 未被执行的处方（如 review_transition）必须保留。
    assert any(p["operation"] == "review_transition"
               for p in doc2["prescriptions"])


# --------------------------------------------------------------------------- #
# 确定性与校验
# --------------------------------------------------------------------------- #
def test_observation_is_deterministic():
    first = json.dumps(_build(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(_build(), ensure_ascii=False, sort_keys=True)
    assert first == second


def test_validate_observation_rejects_unknown_operation():
    doc = _build()
    doc["prescriptions"][0]["operation"] = "delete_everything"
    findings = validate_observation(doc)
    assert any("operation" in item for item in findings)


def test_validate_observation_rejects_missing_verdict_pairs():
    doc = _build()
    del doc["verdicts"][0]["actual"]
    findings = validate_observation(doc)
    assert findings


def test_validate_observation_rejects_dangling_evidence():
    doc = _build()
    doc["verdicts"][0]["evidence"].append("m_does_not_exist")
    findings = validate_observation(doc)
    assert any("证据" in item or "evidence" in item for item in findings)

