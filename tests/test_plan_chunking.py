"""长分镜表**分块出计划**（v1.5）：一分钟的修复，治的是"一次说不完"。

现场（2026-10-03 真跑）：64 镜的 `emit_plan` 参数约 **16.5 KB**，正好压在供应商的
输出上限上（DeepSeek 8k completion tokens）——那一跑 `state=ERROR`、0 镜，两次重试
都在同一列被切断。模型没错，是"一次说这么多话"的预算不够，而这个预算**不由我们
决定**。分段之后每段只是全表的 1/3，任何 ≥8k 输出的模型都稳。

本文件钉四件事：

* 分段规则（`planner.plan_chunks`）：≤24 镜不分块、64 镜 → 3 段、镜号取**分镜表原编号**；
* 提示只在**真分块**时才多出那两句（短剧本的提示逐字不变——所有既有断言都不受影响）；
* 端到端（离线替身）：64 镜声明 → 3 次计划调用、最终计划仍是 64 镜且顺序/镜号正确；
* 失败只重试**当前段**：已收下的前几段不丢、不重复。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer1_input import parse_script  # noqa: E402
from block_director.layer5_orchestrator import planner as P  # noqa: E402
from block_director.layer5_orchestrator.offline import OfflineTransport  # noqa: E402

LONG = ROOT / "fixtures" / "script_long_61.md"
SHORT = ROOT / "fixtures" / "shotlist_market.md"


class Declaration:
    """最小声明对象（`plan_chunks` 只读 `shot_number`）。"""

    def __init__(self, number):
        self.shot_number = number


class Parsed:
    def __init__(self, numbers):
        self.declared_shots = [Declaration(n) for n in numbers]


def test_the_chunk_rule_uses_the_storyboard_numbers():
    assert P.PLAN_CHUNK_SHOTS == 24
    assert P.plan_chunks(None) == []
    assert P.plan_chunks(Parsed(list(range(1, 7)))) == [
        {"index": 0, "total": 1, "start": 0, "stop": 6,
         "shot_numbers": [1, 2, 3, 4, 5, 6]}]
    chunks = P.plan_chunks(Parsed(list(range(1, 65))))
    assert [c["total"] for c in chunks] == [3, 3, 3]
    assert [len(c["shot_numbers"]) for c in chunks] == [24, 24, 16]
    assert chunks[0]["shot_numbers"][0] == 1
    assert chunks[1]["shot_numbers"][0] == 25
    assert chunks[2]["shot_numbers"][-1] == 64
    #: 位置（给离线替身切片用）与镜号（给提示与合并用）都在，两者不许混用。
    assert (chunks[1]["start"], chunks[1]["stop"]) == (24, 48)


def test_a_short_script_prompt_is_unchanged():
    """只在**真分块**时加那两句：短剧本的提示与分块前逐字相同。"""
    parsed = parse_script(SHORT)
    chunks = P.plan_chunks(parsed)
    payload = P.build_plan_payload("x", None, parsed=parsed,
                                   chunk=chunks[0], plan_chunks_total=len(chunks))
    text = "\n".join(message.content or "" for message in payload.messages)
    assert "第 1/1 段" not in text
    assert payload.metadata == {}


def test_a_long_script_prompt_names_the_segment():
    parsed = parse_script(LONG)
    chunks = P.plan_chunks(parsed)
    assert len(chunks) == 3
    payload = P.build_plan_payload("x", None, parsed=parsed,
                                   chunk=chunks[1], plan_chunks_total=len(chunks))
    text = "\n".join(message.content or "" for message in payload.messages)
    assert "第 2/3 段" in text and "镜号 25–48" in text
    #: 这一段之外的镜号**不许**进提示（否则模型会把它们也写一遍）。
    assert "镜号 24｜" not in text
    assert "镜号 49｜" not in text
    assert payload.metadata["plan_chunk"]["shot_numbers"] == list(range(25, 49))
    #: metadata 必须真的上 wire（离线替身与审计都靠它）。
    assert payload.to_dict()["metadata"]["plan_chunk"]["index"] == 1


def test_the_offline_transport_slices_by_the_same_rule():
    parsed = parse_script(LONG)
    transport = OfflineTransport(declarations=parsed.declared_shots)
    chunks = P.plan_chunks(parsed)
    payload = P.build_plan_payload("x", None, parsed=parsed,
                                   chunk=chunks[1], plan_chunks_total=len(chunks))
    reply = transport.chat(payload)
    plan = json.loads(reply.tool_calls[0].function.arguments)
    assert len(plan["shots"]) == 24
    assert plan["shots"][0]["shot_id"] == "shot_025"


def test_the_driver_asks_for_every_segment_and_merges_them(tmp_path):
    """端到端：64 镜声明 → 3 次计划调用，最终计划仍是 64 镜且顺序正确。"""
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger

    parsed = parse_script(LONG)
    transport = OfflineTransport(declarations=parsed.declared_shots)
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(transport=transport, audit=audit, script="",
                          parsed_script=parsed, limits=DriverLimits(),
                          knowledge=None)
    driver.run_to_completion(poll_interval=0.0, max_wall_s=30)
    #: 三次计划调用：段数由分镜表决定，不是模型说了算。
    chunk_events = [event for event in audit.recent(400)
                    if event.kind == "plan_chunk_received"]
    assert len(chunk_events) == 2, [e.message for e in chunk_events]
    assert driver.plan is not None and len(driver.plan.shots) == 64
    assert [int(shot.declared_shot_number) for shot in driver.plan.shots[:3]] == [1, 2, 3]
    assert int(driver.plan.shots[-1].declared_shot_number) == 64


def test_a_bad_segment_is_re_asked_and_does_not_double_count(tmp_path):
    """某一段先回一个坏计划：只重问那一段，前几段不丢、不重复。"""
    from block_director.layer5_orchestrator.driver import (
        DriverLimits,
        PrevisDriver,
    )
    from block_director.layer6_audit.audit_logger import AuditLogger

    parsed = parse_script(LONG)
    transport = OfflineTransport(declarations=parsed.declared_shots)
    calls = {"plan": 0}
    original = transport.chat

    def flaky(payload, timeout=120.0):
        reply = original(payload, timeout)
        if payload.metadata.get("plan_chunk") and payload.metadata["plan_chunk"]["index"] == 1:
            calls["plan"] += 1
            if calls["plan"] == 1:
                #: 第二段第一次只回了 3 个镜头（数量对不上）⇒ 必须整段退回。
                bad = json.loads(reply.tool_calls[0].function.arguments)
                bad["shots"] = bad["shots"][:3]
                reply.tool_calls[0].function.arguments = json.dumps(
                    bad, ensure_ascii=False)
        return reply

    transport.chat = flaky            # type: ignore[assignment]
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(transport=transport, audit=audit, script="",
                          parsed_script=parsed, limits=DriverLimits(),
                          knowledge=None)
    driver.run_to_completion(poll_interval=0.0, max_wall_s=30)
    assert calls["plan"] == 2, "第二段必须被重问一次"
    assert driver.plan is not None
    assert len(driver.plan.shots) == 64, "重问不许把前几段弄丢或弄重"
    assert any(event.kind == "plan_invalid" for event in audit.recent(400))
