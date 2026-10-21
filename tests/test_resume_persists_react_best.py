"""R2 ticket 01（D3）：`_react_best` / `_react_no_gain` 跨进程持久化。

第二轮真跑确认：shot_001=55.8、shot_003=63.4、shot_005=76.7 在 resume 后
被 `failures.json` 重写为 0.0/0——根因是 `ResumeState` 只持久化
terminal/delivered/last_audit/version_histories，新进程 `_failures_payload()`
用空内存重建。本文件先红后绿，钉住"高分保留跨进程成立"。
"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.audit import AuditResult
from block_director.layer5_orchestrator.driver import (
    RESUME_STATE_FILENAME,
    PrevisDriver,
    ResumeState,
    load_resume_state,
    save_resume_state,
)
from block_director.layer6_audit.audit_logger import AuditLogger

from test_checkpoint_resume import _driver, _registry
from stage_helpers import understand_reply


SCRIPT = "INT. 市场 - 日\n\n小明与小华在摊位前对峙。\n"


def test_resume_state_round_trip_react_best_no_gain(tmp_path):
    """新字段进 `resume_state.json` 并逐项往返保真。"""
    state = ResumeState(
        run_id="abc123",
        plan={"scene_heading": "市场"},
        terminal_shots={"shot_005": "failed"},
        react_best={
            "shot_005": {"score": 76.7, "version": 3,
                         "world_state": {"characters": {}}},
        },
        react_no_gain={"shot_005": 3},
    )
    path = tmp_path / RESUME_STATE_FILENAME
    save_resume_state(path, state)
    loaded = load_resume_state(path)
    assert loaded.to_dict() == state.to_dict()
    assert loaded.react_best["shot_005"]["score"] == 76.7
    assert loaded.react_best["shot_005"]["version"] == 3
    assert loaded.react_no_gain == {"shot_005": 3}


def test_old_resume_state_without_react_fields_loads_defaults(tmp_path):
    """旧断点（无新字段）加载不报错，缺省补空默认值（兼容不整包拒绝）。"""
    payload = ResumeState(run_id="old").to_dict()
    payload.pop("react_best", None)
    payload.pop("react_no_gain", None)
    path = tmp_path / RESUME_STATE_FILENAME
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    loaded = load_resume_state(path)
    assert loaded.react_best == {}
    assert loaded.react_no_gain == {}


def test_bad_react_field_types_are_reported(tmp_path):
    """坏类型如实报错（沿用既有严格校验，不静默吞）。"""
    payload = ResumeState().to_dict()
    payload["react_no_gain"] = "not-a-map"
    path = tmp_path / RESUME_STATE_FILENAME
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(Exception, match="react_no_gain"):
        load_resume_state(path)


class _ReplayTransport:
    """阶段替身：只应答 understand；本测试不需要走到 plan。"""

    def chat(self, payload, timeout=120.0):
        return understand_reply(payload.request_id)

    def cancel(self, request_id):
        return None


class _EmptyAuditor:
    def shot_ids(self):
        return []

    def audit(self, shot_id):
        return AuditResult(passed=True, target=shot_id)


def _make_driver(resume_state):
    return PrevisDriver(
        transport=_ReplayTransport(),
        audit=AuditLogger(),
        script=SCRIPT,
        registry=_registry(),
        auditor=_EmptyAuditor(),
        builder=None,
        resume_state=resume_state,
        resume_state_path=None,
    )


def test_resume_restores_react_best_and_no_gain():
    """resume 入口把持久化分数种回内存，failures 不再被清零。"""
    state = ResumeState(
        terminal_shots={"shot_005": "failed"},
        react_best={"shot_005": {"score": 76.7, "version": 3,
                                 "world_state": {}}},
        react_no_gain={"shot_005": 3},
    )
    driver = _make_driver(state)
    assert driver._react_best["shot_005"]["score"] == 76.7
    assert driver._react_no_gain["shot_005"] == 3
    failures = driver.snapshot()["failures"]["failures"]
    assert [f["shot_id"] for f in failures] == ["shot_005"]
    assert failures[0]["best_score"] == 76.7
    assert failures[0]["no_gain_rounds"] == 3


def test_checkpoint_writes_react_best_and_no_gain(tmp_path):
    """`_checkpoint_resume` 把内存分数写进断点文件（跨进程保留）。"""
    state = ResumeState()
    path = tmp_path / RESUME_STATE_FILENAME
    driver = _make_driver(state)
    driver._resume_state_path = path
    driver._react_best["shot_007"] = {"score": 80.5, "version": 1,
                                      "world_state": {}}
    driver._react_no_gain["shot_007"] = 0
    driver._checkpoint_resume(stage="terminal", shot_id="shot_007",
                              status="failed")
    loaded = load_resume_state(path)
    assert loaded.react_best["shot_007"]["score"] == 80.5
    assert loaded.react_no_gain == {"shot_007": 0}


def test_checkpoint_writes_react_round_counts(tmp_path):
    """每镜 ReAct 总回合数必须随终态断点落盘，resume 不重置上限。"""
    state = ResumeState()
    path = tmp_path / RESUME_STATE_FILENAME
    driver = _make_driver(state)
    driver._resume_state_path = path
    driver._react_round_counts["shot_007"] = 4
    driver._checkpoint_resume(stage="terminal", shot_id="shot_007",
                              status="failed")
    loaded = load_resume_state(path)
    assert loaded.react_round_counts == {"shot_007": 4}
