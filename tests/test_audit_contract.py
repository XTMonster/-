"""§16.3 审核契约测试：结构化违规项必须能被修复提示词直接用。"""

from __future__ import annotations

from block_director.contracts.audit import AuditError, AuditResult
from block_director.contracts.enums import Severity


def _axis_error() -> AuditError:
    return AuditError(
        rule="R001", code="E_AXIS_001", severity=Severity.ERROR,
        target="shot_001",
        message="相机位置违反 180° 轴线规则，可能导致角色左右方向混乱。",
        suggestion="将相机移到轴线另一侧，或插入中性镜头过渡。")


def test_findings_split_into_errors_and_warnings():
    warning = AuditError(rule="R009", message="镜头距离与景别不符",
                         severity=Severity.WARNING, target="shot_001")
    result = AuditResult.from_findings([_axis_error(), warning],
                                       score=61.9, target="shot_001")
    assert result.passed is False
    assert len(result.errors) == 1 and len(result.warnings) == 1
    assert result.score == 61.9
    assert result.suggestions == ["将相机移到轴线另一侧，或插入中性镜头过渡。"]


def test_only_warnings_still_pass():
    warning = AuditError(rule="R005", message="角色部分出画",
                         severity=Severity.WARNING)
    result = AuditResult.from_findings([warning])
    assert result.passed is True and result.warnings


def test_no_findings_passes():
    result = AuditResult.from_findings([])
    assert result.passed and result.total == 0
    assert "无违规项" in result.format_for_llm()


def test_format_for_llm_carries_structured_fields():
    text = AuditResult.from_findings([_axis_error()]).format_for_llm()
    assert "[R001]" in text
    assert "target=shot_001" in text
    assert "180° 轴线" in text
    assert "建议：将相机移到轴线另一侧" in text
    assert "未通过" in text


def test_format_reports_score_when_present():
    result = AuditResult.from_findings([_axis_error()], score=61.94)
    assert "评分 61.9" in result.format_for_llm()


def test_round_trip_serialisation():
    result = AuditResult.from_findings([_axis_error()], target="shot_001")
    data = result.to_dict()
    assert data["errors"][0]["rule"] == "R001"
    restored = AuditError.from_dict(data["errors"][0])
    assert restored == _axis_error()


def test_severity_stringifies_for_prompt():
    assert str(Severity.ERROR) == "error"
    assert "(error)" in AuditResult.from_findings([_axis_error()]).format_for_llm()
