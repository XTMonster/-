"""卡 E1：Stage P 剧本优化契约（v1.7 TDD §9）。

契约层只提供：PolishResult DTO、strict schema、提示词模板（双通道唯一真源）。
"""

from __future__ import annotations

from dataclasses import asdict

from block_director.contracts.script_polish import (
    POLISH_PROMPT_TEMPLATE,
    POLISH_SCHEMA,
    PolishResult,
)


def test_polish_schema_is_strict():
    assert POLISH_SCHEMA["type"] == "object"
    assert "suggestions" in POLISH_SCHEMA["required"]
    assert "rewritten" in POLISH_SCHEMA["required"]
    assert POLISH_SCHEMA["additionalProperties"] is False
    props = POLISH_SCHEMA["properties"]
    assert props["suggestions"]["type"] == "array"
    assert props["suggestions"]["items"]["type"] == "string"
    assert props["rewritten"]["type"] == "string"


def test_prompt_template_has_both_placeholders():
    assert "{{script}}" in POLISH_PROMPT_TEMPLATE
    assert "{{brief}}" in POLISH_PROMPT_TEMPLATE


def test_polish_result_roundtrip():
    result = PolishResult(suggestions=["拆镜建议", "视线衔接"],
                          rewritten="改写稿全文", accepted=True)
    plain = asdict(result)
    rebuilt = PolishResult(**plain)
    assert rebuilt == result
    assert rebuilt.accepted is True


def test_polish_result_defaults():
    result = PolishResult(suggestions=[], rewritten="")
    assert result.accepted is False
