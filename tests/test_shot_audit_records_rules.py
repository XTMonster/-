"""`shot_audit` 事件必须记下**是哪几条规则红的**（v1.5）。

现场（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long3/`）：
真实草案终于生效之后（`draft_received 65 / draft_invalid 1`，此前是 2/62），
通过率从"56/56"掉到 **29/56**——而事件里只有 `errors: 2` 这样的**计数**，
没人知道红的是构图、R002（穿模）还是 R011（台词装不下）。
一张"有哪些规则、各红几次"的表是修任何一条的前提。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.audit import AuditError, AuditResult, Severity  # noqa: E402
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver  # noqa: E402
from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: E402


class _Auditor:
    composition_threshold = 70.0

    def audit(self, shot_id):
        return AuditResult(
            passed=False, level="rule",
            errors=[AuditError(rule="R002", message="穿模", code="E_RULE_002"),
                    AuditError(rule="R011", message="台词装不下", code="E_RULE_011")],
            warnings=[AuditError(rule="R005", message="轻微越轴",
                                 severity=Severity.WARNING)],
            score=55.8)


class _Transport:
    def chat(self, payload, timeout=10.0):     # pragma: no cover - 不会被调用
        raise AssertionError("本用例不发起 LLM 调用")

    def health(self, timeout=2.0):             # pragma: no cover
        raise AssertionError


def test_the_audit_event_carries_rule_ids_and_findings(tmp_path):
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(transport=_Transport(), audit=audit, script="",
                          limits=DriverLimits(), knowledge=None,
                          auditor=_Auditor())
    driver._shot_queue = ["shot_001"]          # 直接驱动 CHECKING 那一步
    driver._step_checking()

    events = [event for event in audit.recent(20) if event.kind == "shot_audit"]
    assert events, "没有写出 shot_audit 事件"
    data = events[0].data
    #: 计数仍在（既有契约），新增的是**规矩名**与逐条明细。
    assert data["errors"] == 2 and data["warnings"] == 1
    assert data["rule_ids"] == ["R002", "R011"]
    assert [item["rule"] for item in data["findings"]] == ["R002", "R011", "R005"]
    assert data["findings"][0]["code"] == "E_RULE_002"
    assert data["composition_score"] == 55.8
