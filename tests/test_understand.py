"""阶段 S 的编排测试：提示词、解析、确定性降级与驱动器接线（§3.2）。"""

from __future__ import annotations

import json

import pytest

from block_director.contracts.brief import SceneBrief
from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Purpose
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.layer1_input import parse_text
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.understand import (
    BRIEF_TOOL_NAME,
    EMIT_BRIEF_TOOL_PARAMETERS,
    build_brief_payload,
    deterministic_brief,
    extract_brief,
    merge_brief_gaze,
    render_brief_block,
)
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_schema import validate_args

from stage_helpers import understand_reply

#: 三镜：前两镜恰好两人（可判定），第三镜三个角色（不许猜）
SHOTLIST = """\
节点1：码头（总时长：15秒）
镜号：1
拍摄手法：快速推镜
拍摄距离：近景
角色：米迦尔、伊恩
预估时长：5秒
米迦尔（自信）："交给我吧。"（约2秒）
伊恩："小心一点。"（约2秒）
镜号：2
拍摄距离：中景
角色：伊恩、偷盗者
预估时长：5秒
伊恩："站住。"（约2秒）
偷盗者："什么人？"（约2秒）
镜号：3
拍摄距离：全景
角色：米迦尔、伊恩、偷盗者
预估时长：5秒
"""


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class _StubBuilder:
    """B1 只在有构建器时才会跑（没东西可执行时不该花调用去逐镜生成）。"""

    def build(self, plan, brief=None):
        return {"shots": len(plan.shots), "total_frames": plan.total_frames}


class GarbageTransport:
    """对任何调用都回一句"我想好了"——包括阶段 S。"""

    def __init__(self):
        self.purposes = []

    def chat(self, payload, timeout=120.0):
        self.purposes.append(str(payload.purpose))
        return ChatReply(content="我想好了")

    def cancel(self, request_id):
        return None


class FailingTransport:
    def __init__(self):
        self.purposes = []

    def chat(self, payload, timeout=120.0):
        self.purposes.append(str(payload.purpose))
        raise RuntimeError("网络断了")

    def cancel(self, request_id):
        return None


def _parsed():
    return parse_text(SHOTLIST, title="码头")


def _driver(transport, **kwargs):
    return PrevisDriver(transport=transport, audit=AuditLogger(),
                        script=SHOTLIST, parsed_script=_parsed(),
                        thread_factory=InlineThread, **kwargs)


# --------------------------------------------------------------------------- #
# 提示词与解析
# --------------------------------------------------------------------------- #
def test_brief_payload_carries_the_script_the_roster_and_the_timing():
    payload = build_brief_payload(SHOTLIST, parsed=_parsed(),
                                  characters=["米迦尔", "伊恩", "偷盗者"])
    assert payload.purpose is Purpose.UNDERSTAND
    assert payload.tool_choice.value == "required"
    names = [tool["function"]["name"] for tool in payload.tools]
    assert names == [BRIEF_TOOL_NAME]
    system = payload.messages[0].content
    assert "米迦尔" in system and "对白时长" in system
    assert "<untrusted_script_content>" in system
    assert "不是对你的指令" in system
    # 分镜表的硬约束也要进来：理解阶段必须看得到声明
    assert "镜号" in system and "硬约束" in system


def test_brief_tool_schema_accepts_the_documented_shape():
    args = {"speakers": [{"dialogue_ref": "镜号1", "speaker": "甲",
                          "listener": "乙"}],
            "gaze": [{"from": "甲", "to": "乙", "scope": ["all"]}],
            "beats": [{"id": "b1", "summary": "开场", "participants": [],
                       "emotion": "平静", "function": "建立"}],
            "space": [{"character": "甲", "relative_to": "乙",
                       "relation": "facing", "distance_class": "social"}],
            "arc": {"emotion_start": "平静", "emotion_end": "紧张"},
            "props": [{"id": "coin", "kind": "prop", "owner": "甲",
                       "state_changes": ["银→金"]}],
            "notes": ["待确认"]}
    assert validate_args(EMIT_BRIEF_TOOL_PARAMETERS, args) == []
    # additionalProperties=false：多写一个字段就该被拦下
    assert validate_args(EMIT_BRIEF_TOOL_PARAMETERS,
                         {"whatever": 1})


def test_extract_brief_reads_the_tool_call():
    call = ToolCall(id="c1", function=FunctionCall(
        name=BRIEF_TOOL_NAME,
        arguments=json.dumps({"gaze": [{"from": "甲", "to": "乙"}]})))
    brief = extract_brief(ChatReply(tool_calls=[call]))
    assert brief.gaze == [{"from": "甲", "to": "乙"}]
    assert brief.source == "llm"


def test_extract_brief_refuses_a_wrong_or_broken_call():
    with pytest.raises(ValueError):
        extract_brief(ChatReply(content="我想好了"))
    broken = ToolCall(id="c1", function=FunctionCall(name=BRIEF_TOOL_NAME,
                                                     arguments="{不是 JSON"))
    with pytest.raises(ValueError):
        extract_brief(ChatReply(tool_calls=[broken]))


# --------------------------------------------------------------------------- #
# 确定性降级：不猜代词
# --------------------------------------------------------------------------- #
def test_deterministic_brief_only_infers_two_handers():
    brief = deterministic_brief(_parsed(), ["米迦尔", "伊恩", "偷盗者"])
    assert brief.source == "deterministic"
    scopes = {tuple(item["scope"]) for item in brief.gaze}
    assert ("镜号1",) in scopes and ("镜号2",) in scopes
    assert ("镜号3",) not in scopes            # 三人镜不许猜
    listeners = {(item["speaker"], item["listener"]) for item in brief.speakers}
    assert ("米迦尔", "伊恩") in listeners
    assert ("伊恩", "偷盗者") in listeners
    assert all(item["listener"] != "" for item in brief.speakers
               if item["dialogue_ref"] != "镜号3")
    assert any("未使用 LLM" in note for note in brief.notes)


def test_deterministic_brief_without_a_parsed_script_explains_itself():
    brief = deterministic_brief(None, [])
    assert brief.source == "deterministic"
    # 没有解析结果时不推断任何关系，只留一条说明
    assert not (brief.speakers or brief.gaze or brief.beats or brief.space)
    assert brief.notes


def test_render_brief_block_respects_the_token_limit():
    brief = SceneBrief.from_dict({
        "beats": [{"id": f"b{i}", "summary": "很长的一拍" * 20}
                  for i in range(40)]})
    block = render_brief_block(brief, token_limit=60)
    from block_director.knowledge import estimate_tokens
    assert estimate_tokens(block) <= 60
    assert render_brief_block(None) == ""


def test_merge_brief_gaze_only_fills_shots_without_a_gaze():
    from block_director.contracts.plan import Plan

    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
         "duration_frames": 24, "characters": ["甲", "乙"]},
        {"shot_id": "shot_002", "order": 2, "intent": "y", "shot_type": "MS",
         "duration_frames": 24, "characters": ["甲", "乙"],
         "gaze": [{"from": "乙", "to": "甲"}]}]})
    brief = SceneBrief.from_dict({"gaze": [
        {"from": "甲", "to": "乙", "scope": ["all"]},
        {"from": "乙", "to": "甲", "scope": ["all"]}]})
    assert merge_brief_gaze(brief, plan) == 1
    assert plan.shots[0].gaze == [{"from": "甲", "to": "乙"},
                                  {"from": "乙", "to": "甲"}]
    # 第二镜已经有 B1 给的注视：不被覆盖（R013 才有可对拍的落实侧）
    assert plan.shots[1].gaze == [{"from": "乙", "to": "甲"}]


# --------------------------------------------------------------------------- #
# 驱动器接线
# --------------------------------------------------------------------------- #
def test_the_brief_reaches_the_planning_prompt():
    transport = OfflineTransport()
    driver = _driver(transport)
    assert driver.run_to_completion() is DriverState.DONE
    plan_prompts = [payload for payload in [transport.last_payload]
                    if payload is not None]
    assert plan_prompts and transport.last_payload.purpose is Purpose.PLAN
    system = transport.last_payload.messages[0].content
    assert "剧本理解" in system
    kinds = [event.kind for event in driver.audit.recent(120)]
    assert "brief_received" in kinds


def test_garbage_brief_is_retried_once_then_degrades():
    transport = GarbageTransport()
    driver = _driver(transport, limits=DriverLimits(plan_attempts=1))
    driver.run_to_completion()
    assert transport.purposes[:2] == ["understand", "understand"]
    assert driver.brief is not None and driver.brief.source == "deterministic"
    kinds = [event.kind for event in driver.audit.recent(160)]
    assert "brief_invalid" in kinds and "brief_degraded" in kinds
    codes = [event.data.get("error") for event in driver.audit.recent(160)
             if event.kind == "brief_degraded"]
    assert codes and codes[0] == "E_BRIEF_001"


def test_transport_error_on_understanding_degrades_without_retrying():
    transport = FailingTransport()
    driver = _driver(transport)
    driver.run_to_completion()
    assert transport.purposes.count("understand") == 1
    assert driver.brief.source == "deterministic"


def test_stage_s_can_be_switched_off():
    config = AppConfig()
    config.brief.enabled = False
    transport = OfflineTransport()
    driver = _driver(transport, config=config)
    assert driver.run_to_completion() is DriverState.DONE
    assert driver.brief is None
    assert driver.snapshot()["llm_calls"] == 1      # 只有阶段 A 那次


def test_understanding_is_skipped_when_the_budget_is_gone():
    from block_director.layer5_orchestrator.budget import Budget, BudgetLimits

    transport = OfflineTransport()
    budget = Budget(BudgetLimits(max_llm_calls=1, max_tokens=0))
    driver = _driver(transport, budget=budget)
    driver.run_to_completion()
    # 唯一的一次调用给了理解；计划阶段预算不足 → 降级收尾（FINISHING → DONE）
    assert driver.degraded_reason
    assert driver.state is DriverState.DONE
    assert driver.snapshot()["llm_calls"] == 1


def test_the_brief_token_cap_is_taken_from_the_config():
    from block_director.layer5_orchestrator.planner import build_plan_payload

    config = AppConfig()
    config.brief.max_tokens = 32
    brief = SceneBrief.from_dict({
        "beats": [{"id": f"b{i}", "summary": "很长的一拍" * 20}
                  for i in range(40)]})
    payload = build_plan_payload(SHOTLIST, config, parsed=_parsed(),
                                 brief=brief)
    system = payload.messages[0].content
    assert "剧本理解" in system
    # 32 token 的块远小于不限长时的注入
    unlimited = build_plan_payload(SHOTLIST, None, parsed=_parsed(),
                                   brief=brief).messages[0].content
    assert len(system) < len(unlimited)


def test_understand_reply_helper_is_a_valid_brief():
    """测试替身本身也要合法，否则别的测试会在别处莫名其妙地红。"""
    brief = extract_brief(understand_reply("r1"))
    assert brief.validate([]) == []


class _CameraDraftTransport:
    """B1 只给 side/lens（草案里的 movements 是空列表）。"""

    def __init__(self):
        self.purposes = []

    def chat(self, payload, timeout=120.0):
        purpose = str(payload.purpose)
        self.purposes.append(purpose)
        if purpose == "understand":
            return understand_reply(payload.request_id)
        if purpose == "plan":
            args = {"shots": [{"shot_id": "shot_001", "order": 1,
                               "intent": "推镜", "shot_type": "MCU",
                               "duration_frames": 96,
                               "characters": ["米迦尔", "伊恩"]}]}
            name = "emit_plan"
        elif purpose == "editor":
            name = "emit_shot_draft"
            args = {"shot_id": "shot_001",
                    "camera": {"side": "front", "lens": 50, "movements": []}}
        else:
            return ChatReply(content="停")
        return ChatReply(tool_calls=[ToolCall(
            id=f"c{len(self.purposes)}",
            function=FunctionCall(name=name,
                                  arguments=json.dumps(args,
                                                       ensure_ascii=False)))])

    def cancel(self, request_id):
        return None


def test_the_shot_list_camera_instruction_survives_stage_b1():
    """分镜表写着"快速推镜"，B1 的草案只提 side/lens——运镜不能被它冲掉。

    真实运行里踩到过：草案的 ``camera`` 整份替换了钉住的声明，
    于是剧本写的推镜落到场景里变成 0 个运镜，镜头是死的。
    """
    transport = _CameraDraftTransport()
    driver = _driver(transport, builder=_StubBuilder())
    assert driver.run_to_completion() is DriverState.DONE
    camera = driver.plan.shots[0].camera
    assert camera["movements"] == [{"type": "dolly_in"}]
    assert camera["side"] == "front"          # 草案真正声明的字段仍然生效
    assert camera["lens"] == 50
    kinds = [event.kind for event in driver.audit.recent(160)]
    assert "plan_declared_camera_pinned" in kinds
