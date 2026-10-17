"""卡 A4：规则元信息目录（v1.7 卡 A4 / TDD §7 末段对拍口径）。"""

from __future__ import annotations

import re
from pathlib import Path

from block_director.contracts.rule_catalog import RULES

ROOT = Path(__file__).resolve().parents[1]

#: 卡 A4 表格钉死的基线档（非 strict 档）；keyword 是 summary 必须含的字样。
EXPECTED = {
    "R001": ("error", "双级"),
    "R002": ("error", ""),
    "R003": ("error", ""),
    "R004": ("warning", ""),
    "R005": ("warning", ""),
    "R006": ("error", ""),
    "R007": ("error", ""),
    "R008": ("warning", ""),
    "R009": ("warning", ""),
    "R010": ("warning", ""),
    "R011": ("error", ""),
    "R012": ("warning", ""),
    "R013": ("warning", "strict"),
    "R014": ("warning", "strict"),
    "R015": ("error", "strict"),
    "R016": ("error", "strict"),
    "R017": ("warning", ""),
    "R019": ("warning", "strict"),
    "R020": ("warning", ""),
    "R021": ("warning", ""),
    "R022": ("warning", ""),
    "R023": ("warning", ""),
}


def _rule_checker_source() -> str:
    return (ROOT / "block_director/layer3_engine/rule_checker.py").read_text(
        encoding="utf-8")


def _compliance_source() -> str:
    return (ROOT / "block_director/layer5_orchestrator/compliance.py").read_text(
        encoding="utf-8")


def _static_ids() -> set:
    """双正则双文件并集（卡 A4 ② 的钉死口径）。"""
    checker = _rule_checker_source()
    ids = set(re.findall(r'_(?:error|warning)\(\s*\n?\s*"(R\d{3})"', checker))
    ids |= set(re.findall(
        r'_error if strict else _warning\)\s*\n?\s*\(\s*\n?\s*"(R\d{3})"',
        checker))
    compliance = _compliance_source()
    ids |= set(re.findall(r'RULE_\w+\s*=\s*"(R\d{3})"', compliance))
    return ids


def test_catalog_matches_static_scan():
    catalog_ids = {entry["id"] for entry in RULES}
    assert _static_ids() == catalog_ids
    assert len(RULES) == 22


def test_severity_matches_usage():
    checker = _rule_checker_source()
    error_ids = set(re.findall(r'_error\(\s*\n?\s*"(R\d{3})"', checker))
    warning_ids = set(re.findall(r'_warning\(\s*\n?\s*"(R\d{3})"', checker))
    ternary_ids = set(re.findall(
        r'_error if strict else _warning\)\s*\n?\s*\(\s*\n?\s*"(R\d{3})"',
        checker))

    for entry in RULES:
        rule_id = entry["id"]
        expected_severity, keyword = EXPECTED[rule_id]
        assert entry["severity"] == expected_severity, rule_id
        if keyword:
            assert keyword in entry["summary"], rule_id
        # 消费侧形态对拍：error 调用点 → error；仅 warning → warning；
        # 双级 → error；三元 strict 形态按非 strict 档落 warning 基线。
        if rule_id in error_ids and rule_id in warning_ids:
            assert entry["severity"] == "error", rule_id
            assert "双级" in entry["summary"], rule_id
        elif rule_id in ternary_ids:
            assert entry["severity"] == "warning", rule_id
        elif rule_id in error_ids:
            assert entry["severity"] == "error", rule_id
        elif rule_id in warning_ids:
            assert entry["severity"] == "warning", rule_id


def test_fields_present():
    for entry in RULES:
        assert set(entry) == {"id", "severity", "summary"}
        assert re.fullmatch(r"R\d{3}", entry["id"])


def test_composition_not_in_catalog():
    catalog_ids = {entry["id"] for entry in RULES}
    assert "COMPOSITION" not in catalog_ids
