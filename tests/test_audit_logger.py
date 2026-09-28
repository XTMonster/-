"""§11.3 审计日志与 LLM Trace 测试。"""

from __future__ import annotations

import json

from block_director.contracts.messages import ChatReply, Usage
from block_director.layer6_audit.audit_logger import AuditLogger


def test_memory_only_mode(tmp_path):
    audit = AuditLogger()
    audit.log("state", "IDLE → PLANNING")
    audit.log("run_failed", "boom", level="error")
    assert audit.audit_path is None
    assert [e.kind for e in audit.recent()] == ["state", "run_failed"]
    assert audit.recent(1)[0].level == "error"


def test_jsonl_is_written_line_by_line(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    audit.log("run_started", "开始")
    audit.log("state", "IDLE → PLANNING")
    lines = audit.audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["kind"] == "run_started"
    assert first["run_id"] == audit.run_id
    assert "ts" in first


def test_llm_trace_records_usage_and_tools(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    reply = ChatReply(content=None, usage=Usage(10, 5, 15))
    audit.log_llm("plan", reply, duration_s=1.25, request_id="req_1")
    record = json.loads(audit.trace_path.read_text(encoding="utf-8").strip())
    assert record["purpose"] == "plan"
    assert record["duration_s"] == 1.25
    assert record["usage"]["total_tokens"] == 15
    assert record["request_id"] == "req_1"
    assert audit.counters["llm_calls"] == 1


def test_llm_error_is_recorded(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    audit.log_llm("plan", None, 0.5, "req_2", error="TimeoutError: slow")
    record = json.loads(audit.trace_path.read_text(encoding="utf-8").strip())
    assert record["error"] == "TimeoutError: slow"
    assert record["usage"] is None


def test_invalid_level_falls_back_to_info():
    audit = AuditLogger()
    assert audit.log("x", "y", level="critical").level == "info"


def test_recent_is_bounded():
    audit = AuditLogger(keep=3)
    for index in range(10):
        audit.log("tick", str(index))
    assert len(audit.recent()) == 3
    assert audit.recent()[-1].message == "9"
