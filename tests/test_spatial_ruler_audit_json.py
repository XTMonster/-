from block_director.contracts.audit import AuditResult
from block_director.contracts.enums import Severity
from block_director.contracts.audit import AuditError


def test_audit_result_json_shape_is_stable_without_blender():
    result = AuditResult(passed=False, target="shot_001", score=61.0)
    payload = result.to_dict()
    payload.update({
        "schema_version": "spatial-ruler-audit/v1",
        "shot_id": "shot_001",
        "source": "BlockDirector.audit",
        "verdict": "fail",
        "metrics": [],
        "findings": [],
        "guard": {"warnings": [], "frames_sampled": 0,
                  "sampling_error": None},
        "repair": {"candidates": [], "status": "pending"},
    })
    assert payload["schema_version"] == "spatial-ruler-audit/v1"
    assert payload["shot_id"] == "shot_001"
    assert payload["verdict"] == "fail"
    assert set(payload["repair"]) == {"candidates", "status"}


def test_audit_result_json_carries_rule_findings():
    """审计 JSON 必须携带原审核器的规则 findings（R001–R025 的 errors/warnings）。"""
    result = AuditResult(
        passed=False, target="shot_001", score=61.0,
        errors=[AuditError(rule="R001", message="轴线跨线",
                           severity=Severity.ERROR, target="shot_001",
                           suggestion="换机位")],
        warnings=[AuditError(rule="R010", message="跳切风险",
                             severity=Severity.WARNING, target="shot_001",
                             suggestion="改变机位角度")])
    payload = result.to_dict()
    payload.update({
        "schema_version": "spatial-ruler-audit/v1",
        "shot_id": "shot_001",
        "source": "BlockDirector.audit",
        "verdict": "fail",
        "metrics": [],
        "findings": [item.to_dict() for item in
                      [*result.errors, *result.warnings]],
        "guard": {"warnings": [], "frames_sampled": 0,
                  "sampling_error": None},
        "repair": {"candidates": [], "status": "pending"},
    })
    rules = {item["rule"] for item in payload["findings"]}
    assert rules == {"R001", "R010"}
    assert payload["verdict"] == "fail"
