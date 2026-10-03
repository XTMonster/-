"""计划重试必须把**上一次被拒的原因**告诉模型（v1.5）。

现场（2026-10-03 的真跑，`docs/evidence/20261003_chunked_long7/`）：`state=ERROR`、
**0 镜**。两次计划调用分别被拒于

* `参数不是合法 JSON: Expecting ',' delimiter: line 1 column 9690`
* `参数校验失败: args.shots[0] 不允许出现字段 dialogue_ids_note`（后同 24 条）

而**重试用的是同一份提示**——模型看不到自己上一次错在哪，于是把同一个错误再犯一遍，
两次额度耗尽，整跑终止。这与"截断被报成 JSON 非法"是同一类问题：**信息没回灌**。

本文件钉：非空 `retry_note` 一定进 user 消息；空的**一个字都不加**（首答的提示
与分块前逐字节相同）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator.planner import build_plan_payload  # noqa: E402


def _user_text(payload) -> str:
    return payload.messages[-1].content or ""


def test_a_first_attempt_carries_no_reason_block():
    payload = build_plan_payload("剧本", None)
    text = _user_text(payload)
    assert "上一次提交" not in text
    assert text == "请基于上述剧本，调用 emit_plan 提交完整分镜计划。"


def test_a_retry_names_what_was_rejected():
    payload = build_plan_payload(
        "剧本", None,
        retry_note="参数校验失败: args.shots[0] 不允许出现字段 dialogue_ids_note")
    text = _user_text(payload)
    assert "上一次提交被拒绝" in text
    assert "dialogue_ids_note" in text
    assert "只" in text and "schema" in text       # 告诉它该怎么改


def test_the_driver_passes_the_last_problem_and_clears_it_after_success(tmp_path):
    """端到端（离线替身）：第一次失败的原因必须出现在第二次请求里。"""
    from block_director.layer1_input import parse_script
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
        default_registry,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger

    long_script = ROOT / "fixtures" / "script_long_61.md"
    parsed = parse_script(long_script)

    class _Transport:
        """第一次计划调用回一个**多写了字段**的计划，之后正常。"""

        def __init__(self):
            self.payloads = []
            self.plan_calls = 0

        def chat(self, payload, timeout=10.0):
            from block_director.contracts.messages import (
                ChatReply, FunctionCall, ToolCall,
            )
            self.payloads.append(payload)
            if getattr(payload, "purpose", None) and str(payload.purpose) == "plan":
                self.plan_calls += 1
                args = {"scene_heading": "t", "continuity_notes": [],
                        "shots": [{"shot_id": "shot_001", "order": 1,
                                   "intent": "x", "shot_type": "MS",
                                   "duration_frames": 48,
                                   "dialogue_ids_note": "多写的字段"}]}
                if self.plan_calls == 1:
                    import json
                    return ChatReply(content=None, model="stub",
                                     request_id=payload.request_id,
                                     tool_calls=[ToolCall(id="c1", function=FunctionCall(
                                         name="emit_plan",
                                         arguments=json.dumps(args,
                                                              ensure_ascii=False)))])
            raise AssertionError("本用例只验证第一次计划的回灌提示")

        def health(self, timeout=2.0):        # pragma: no cover
            raise AssertionError

    transport = _Transport()
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(transport=transport, audit=audit, script="",
                          parsed_script=parsed, limits=DriverLimits(),
                          registry=default_registry(), knowledge=None)
    driver.run_to_completion(poll_interval=0.0, max_wall_s=10)
    plan_payloads = [p for p in transport.payloads
                     if str(getattr(p, "purpose", "")) == "plan"]
    assert len(plan_payloads) >= 2, "应当重试一次"
    assert "上一次提交" not in (plan_payloads[0].messages[-1].content or "")
    assert "dialogue_ids_note" in (plan_payloads[1].messages[-1].content or "")
