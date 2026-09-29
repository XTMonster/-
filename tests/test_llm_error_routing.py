"""传输错误的阶段化恢复（v1.3 P0-4）。

v1.2 的 ``_step_calling_llm`` 只区分 repair 与非 repair，于是 editor /
review / react 的传输错误全被送回 PLANNING：计划被反复重新生成、
``plan_attempts`` 迅速耗尽，最终报出"分镜计划生成失败（已达最大尝试次数）"
——与真实原因完全不符，并把整次运行终止掉。

实测证据：一次真实模型运行里 react 阶段 sidecar 返回 502（耗时 0.042 秒），
整次运行就此结束。
"""

from __future__ import annotations

import pytest

from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

SCRIPT = "INT. 咖啡馆 - 日\n\n两人争吵。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


class StubBuilder:
    """满足构建器协议：没有构建器就不会进 EDITING 阶段。"""

    def __init__(self):
        self.built = []

    def build(self, plan):
        self.built.append(plan)
        return {"shots": len(plan.shots), "total_frames": plan.total_frames}


class FailAtPurpose:
    """在指定阶段注入若干次传输错误；其余请求原样转发给离线传输。"""

    def __init__(self, inner, purpose: str, times: int = 1):
        self.inner = inner
        self.purpose = purpose
        self.times = times
        self.fired = 0
        self.purposes: list = []

    def chat(self, payload, timeout=120.0):
        self.purposes.append(str(payload.purpose))
        if str(payload.purpose) == self.purpose and self.fired < self.times:
            self.fired += 1
            raise RuntimeError(f"注入的传输错误（{self.purpose}）")
        return self.inner.chat(payload, timeout)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _driver(**kwargs) -> PrevisDriver:
    return PrevisDriver(transport=OfflineTransport(), audit=AuditLogger(),
                        script=SCRIPT, thread_factory=InlineThread, **kwargs)


# --------------------------------------------------------------------------- #
# 恢复落点：五个阶段各自的正确去向
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("purpose,expected", [
    ("plan", DriverState.PLANNING),
    ("editor", DriverState.EDITING),
    ("review", DriverState.CHECKING),
    ("repair", DriverState.CHECKING),
    ("react", DriverState.CHECKING),
])
def test_error_lands_in_the_right_state_per_purpose(purpose, expected):
    driver = _driver()
    driver._transition(DriverState.CALLING_LLM)
    driver._recover_from_llm_error(purpose, "注入的传输错误")
    assert driver.state is expected


def test_editor_error_advances_to_the_next_shot():
    """不前进的话 _step_editing 会一直重取同一个镜号，卡死在这一镜。"""
    driver = _driver()
    driver._editing_queue = ["shot_001", "shot_002"]
    driver._editing_index = 0
    driver._recover_from_llm_error("editor", "boom")
    assert driver._editing_index == 1
    assert driver.drafts_failed[-1]["shot_id"] == "shot_001"
    assert driver.state is DriverState.EDITING


def test_repair_error_counts_towards_the_limit():
    """失败必须计入 —— 否则 CHECKING ↔ REPAIRING 会无限往返。"""
    driver = _driver()
    driver._repair_attempts = 0
    driver._recover_from_llm_error("repair", "boom")
    assert driver._repair_attempts == 1
    assert driver.state is DriverState.CHECKING


def test_review_error_marks_the_shot_reviewed():
    """失败必须记入 —— 否则同一镜会被无限复核。"""
    driver = _driver()
    driver._pending_review = "shot_003"
    driver._current_shot_id = "shot_003"
    driver._recover_from_llm_error("review", "boom")
    assert "shot_003" in driver._reviewed_shots
    assert driver._pending_review is None
    assert driver.state is DriverState.CHECKING


def test_react_error_ends_the_react_turn_with_a_reason():
    driver = _driver()
    driver._react_shot = "shot_002"
    driver._recover_from_llm_error("react", "sidecar 502")
    assert driver.state is DriverState.CHECKING
    assert driver.react_history[-1]["reason"].startswith("传输错误")


# --------------------------------------------------------------------------- #
# 端到端：editor 阶段的传输错误不再重启规划
# --------------------------------------------------------------------------- #
def test_editor_transport_error_does_not_restart_planning():
    transport = FailAtPurpose(OfflineTransport(), "editor")
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, builder=StubBuilder(),
                          thread_factory=InlineThread)
    state = driver.run_to_completion()
    assert state is DriverState.DONE
    # 计划只请求过一次：v1.2 会在这里第二次回到 PLANNING
    assert transport.purposes.count("plan") == 1
    assert len([p for p in transport.purposes if p == "editor"]) == 2
    assert driver.drafts_failed and driver.drafts_failed[0]["error"]


def test_review_transport_error_does_not_loop_forever():
    """复核失败必须收尾，而不是反复重试同一镜。"""
    transport = FailAtPurpose(OfflineTransport(), "review", times=99)
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT, builder=StubBuilder(),
                          thread_factory=InlineThread)
    state = driver.run_to_completion()
    assert state is DriverState.DONE
    assert transport.purposes.count("review") == \
        len([p for p in transport.purposes if p == "review"])   # 有限次
    assert transport.purposes.count("review") <= 4


# --------------------------------------------------------------------------- #
# v1.3 P0-5：B1 的提示词必须带上剧本原文
# --------------------------------------------------------------------------- #
SCRIPT_WITH_DIALOGUE = (
    "INT. 咖啡馆 - 日\n\n"
    "林可把手机贴在耳边，窗外在下雨。\n\n"
    "林可\n"
    "你还在听吗。\n"
)


class CapturingTransport:
    def __init__(self, inner):
        self.inner = inner
        self.payloads: list = []

    def chat(self, payload, timeout=120.0):
        self.payloads.append(payload)
        return self.inner.chat(payload, timeout)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_editor_prompt_carries_the_script_text():
    """v1.2 根本没传 scene_text，B1 只能自己编台词。"""
    from block_director.layer1_input.script_parser import parse_text

    parsed = parse_text(SCRIPT_WITH_DIALOGUE)
    transport = CapturingTransport(OfflineTransport())
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT_WITH_DIALOGUE, parsed_script=parsed,
                          builder=StubBuilder(), thread_factory=InlineThread)
    state = driver.run_to_completion()
    assert state is DriverState.DONE
    editor = [p for p in transport.payloads if str(p.purpose) == "editor"]
    assert editor, "没有发起任何 B1 调用"
    system = editor[0].messages[0].content
    assert "你还在听吗。" in system          # 剧本里的真台词
    assert "林可" in system
    assert "<untrusted_script_content>" in system   # §7.7 的注入防护仍在
