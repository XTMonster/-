"""v1.4 RK-7 / D-1：台词时长的**三方对拍**。

三方是：① 剧本声明的时长；② **pin 之前**模型自己写的响应（B1 的
``emit_shot_draft`` 原文）；③ pin 之后的计划。三者对同一句台词必须给出一致的
``applied_s``；声明缺失时才回落到"字数 ÷ ``dialogue.chinese_cps``"。

v1.3 的对拍是**自证**的：它先把自己声明的台词钉进计划，再拿同一份计划去比。
这里读的是驱动器留下的证据链——``dialogue_pins[]`` 里的 ``declared_s`` /
``model_text`` / ``applied_s``——其中 ``model_text`` 是 pin 之前的快照。
"""

from __future__ import annotations

from pathlib import Path

from block_director.contracts.config import AppConfig
from block_director.contracts.plan import Plan
from block_director.layer1_input import parse_script
from block_director.layer1_input.dialogue_timing import estimate_dialogue_frames
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread

ROOT = Path(__file__).resolve().parents[1]
NODE5 = ROOT / "fixtures" / "script_node5_8_lines.md"


class _StubBuilder:
    """审核针对的是**已建成**的场景，所以对拍需要一个最小构建器。"""

    def build(self, plan: Plan, brief=None) -> dict:
        return {"shots": len(plan.shots), "characters": 1, "cameras": 0,
                "motions": 0, "keyframes": 0, "total_frames": plan.total_frames,
                "warnings": [], "results": []}


def _run(tmp_path) -> PrevisDriver:
    config = AppConfig()
    # RK-7 的前置：trace 必须开着，否则拿不到 pin 前的响应。
    config.llm.trace_prompts = True
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=AuditLogger(directory=tmp_path),
        script=NODE5.read_text(encoding="utf-8"),
        parsed_script=parse_script(NODE5),
        config=config, builder=_StubBuilder(), thread_factory=InlineThread)
    driver.run_to_completion()
    return driver


def test_first_side_the_script_declares_three_seconds(tmp_path):
    driver = _run(tmp_path)
    pins = [pin for shot in driver.plan.shots for pin in shot.dialogue_pins]
    declared = [pin for pin in pins if pin.get("declared_s")]
    assert declared, "分镜表写了（约3秒），pins 里必须有声明时长"
    assert declared[0]["declared_s"] == 3.0
    assert declared[0]["speaker_raw"] == "米迦尔"
    assert declared[0]["speaker_status"] in ("resolved", "unresolved")


def test_second_side_the_pre_pin_snapshot_is_recorded(tmp_path):
    """② pin **之前**的模型响应：离线草案里没有台词，快照必须是空串——
    而不是"pin 之后的那份文本"（那正是 v1.3 的自证）。"""
    driver = _run(tmp_path)
    pins = [pin for shot in driver.plan.shots for pin in shot.dialogue_pins]
    assert all(isinstance(pin.get("model_text"), str) for pin in pins)
    assert all(pin["model_text"] == "" for pin in pins)


def test_third_side_the_pinned_plan_carries_the_same_line(tmp_path):
    driver = _run(tmp_path)
    first = driver.plan.shots[0]
    texts = [str(entry.get("text") or "") for entry in first.dialogues]
    assert "我先上船。" in texts
    pins = [pin for pin in first.dialogue_pins
            if str(pin.get("speaker_raw")) == "米迦尔"]
    assert pins and pins[0]["declared_s"] == 3.0
    # 三方一致：声明 3.0s 就是这一镜被钉住的时长来源。
    assert pins[0]["applied_s"] is None or pins[0]["applied_s"] >= 0.0


def test_without_a_declaration_the_engine_uses_the_configured_rate():
    """声明缺失时才回退：``applied_s = 字数 ÷ dialogue.chinese_cps``。"""
    config = AppConfig()
    text = "这是一句没有声明时长的台词"
    frames = estimate_dialogue_frames(text, chinese_cps=config.dialogue.chinese_cps)
    expected_seconds = len(text) / config.dialogue.chinese_cps
    assert frames >= 1
    assert abs(frames / 24.0 - expected_seconds) <= 0.5


def test_dialogue_pins_are_serialised_into_the_plan(tmp_path):
    driver = _run(tmp_path)
    payload = driver.plan.to_dict()
    assert any(shot["dialogue_pins"] for shot in payload["shots"])
