"""帧预算必须真的**发出去**：B1 的草案提示与 B4 的修复提示都要带数。

只把预算算好而不进提示词，等于什么都没做（2026-10-03 的教训：§4.4 的表
只给了阶段 A，而**给对白排帧的是 B1**）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.audit import AuditError, AuditResult  # noqa: E402
from block_director.contracts.enums import Severity, ShotType  # noqa: E402
from block_director.contracts.plan import ShotPlan  # noqa: E402
from block_director.layer1_input.dialogue_timing import (  # noqa: E402
    DIALOGUE_TAIL_FRAMES,
    estimate_dialogue_frames,
)
from block_director.layer5_orchestrator.dialogue_budget import (  # noqa: E402
    shot_dialogue_budget,
)
from block_director.layer5_orchestrator.editor import (  # noqa: E402
    build_editor_payload,
)
from block_director.layer5_orchestrator.repair import (  # noqa: E402
    build_repair_payload,
)


class _Registry:
    """够 `build_repair_payload` 用的最小工具表替身。"""

    def schemas_except(self, name):
        return []


def shot_with(lines, *, duration, pinned=False) -> ShotPlan:
    pins = [{"declared_s": None, "speaker_raw": "char_001"}
            for _ in lines] if pinned else []
    return ShotPlan(
        shot_id="shot_001", intent="推进", shot_type=ShotType.MS,
        duration_frames=duration,
        dialogues=[{"character_id": "char_001", "text": text}
                   for text in lines],
        dialogue_pins=pins)


def editor_system(shot: ShotPlan) -> str:
    return build_editor_payload(shot, None, shot_order=1).messages[0].content


def failing_audit() -> AuditResult:
    return AuditResult(errors=[
        AuditError(rule="R011", code="E_SDL_001", severity=Severity.ERROR,
                   target="shot_001", message="对白装不下")])


def test_b1_prompt_carries_the_per_line_numbers_and_the_deadline():
    shot = shot_with(["我先上船。", "别拖了。"], duration=240)
    budget = shot_dialogue_budget(shot)
    system = editor_system(shot)
    assert "{dialogue_budget}" not in system, "占位符没被替换"
    assert f"第 {budget.latest_allowed_end} 帧以内" in system
    for line in budget.lines:
        assert f"“{line.text}” 约 {line.frames} 帧" in system


def test_b1_prompt_says_when_the_shot_cannot_hold_its_dialogue():
    """long5 的 shot_064 形状：10 句塞进 72 帧。提示词必须明说装不下。"""
    shot = shot_with(
        ["我先上船。", "等等我。", "别拖了。", "这一次我听你的。", "走吧。",
         "照顾好自己。", "你也是。", "再见。", "再见。", "船要开了。"],
        duration=72)
    budget = shot_dialogue_budget(shot)
    system = editor_system(shot)
    assert budget.fits is False
    assert "装不下" in system
    assert f"超出 {budget.overflow_frames} 帧" in system
    assert f"最多只排得下前 {budget.max_lines} 句" in system


def test_b1_prompt_gives_the_right_advice_for_free_vs_pinned_dialogue():
    """能挪就挪（B1 自己挑的台词），钉死就只能排紧——两种建议不能混。"""
    free = editor_system(shot_with(["我先上船。", "别拖了。"], duration=72))
    assert "挪到别的镜头" in free
    assert "不要删台词" not in free

    pinned = editor_system(shot_with(["我先上船。", "别拖了。"], duration=72,
                                     pinned=True))
    assert "不要删台词" in pinned
    assert "R016" in pinned


def test_b1_prompt_covers_the_case_where_b1_picks_the_lines():
    """阶段 A 没给台词文本时（剧本只给了台词块），B1 自己分配——预算照样要给。"""
    shot = shot_with([], duration=96)
    system = editor_system(shot)
    budget = shot_dialogue_budget(shot)
    assert f"第 {budget.latest_allowed_end} 帧以内" in system
    assert f"最多 {budget.single_line_char_cap()} 个汉字" in system


def test_repair_prompt_carries_the_same_budget_when_the_shot_is_known():
    shot = shot_with(["我先上船。", "别拖了。"], duration=72)
    payload = build_repair_payload(failing_audit(), _Registry(), shot=shot)
    system = payload.messages[0].content
    budget = shot_dialogue_budget(shot)
    assert f"第 {budget.latest_allowed_end} 帧以内" in system
    assert f"超出 {budget.overflow_frames} 帧" in system


def test_repair_prompt_without_a_shot_still_builds():
    """没给镜头（计划外的临时修复）时不能崩，只是没有预算块。"""
    system = build_repair_payload(failing_audit(), _Registry()).messages[0].content
    assert "帧预算" not in system
    assert "R011" in system


def test_the_tail_constant_moves_with_the_single_source():
    """余量数值只能有一个出处：改 `DIALOGUE_TAIL_FRAMES` 就得体现在提示词里。"""
    shot = shot_with(["走吧。"], duration=120)
    system = editor_system(shot)
    assert f"收尾余量 {DIALOGUE_TAIL_FRAMES} 帧" in system
    assert (f"最后一句必须结束在第 {120 - DIALOGUE_TAIL_FRAMES} 帧以内"
            in system)
    assert estimate_dialogue_frames("走吧。") > 0
