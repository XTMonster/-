"""逐镜的**对白帧预算**（执行文档 v1.2 §4.4 / §7.1 B1／B4 的信息面）。

为什么要有这个模块（2026-10-03 的 64 镜真跑，`docs/evidence/20261003_chunked_long5/`）：

* R011（= SDL 的 S6）要求「一句对白的最晚结束帧 + 12 帧收尾余量 ≤ 镜头时长」，
  这是**硬门槛**；
* 阶段 A 的计划提示里有 §4.4 的对白时长表与那 12 帧的说明（`planner.py`）——
  但**真正给对白排帧的是阶段 B1**（`emit_shot_draft` 的
  ``dialogues[].start_frame/end_frame``），而 B1 的提示词只有一句
  "对白必须落在镜头时长内，并留出收尾余量"：没有每句要几帧，也没有那 12 帧
  到底是多少。修复回合（B4）拿到的也只有审核文本，同样没有帧数。

  于是模型只能凭感觉排帧 → 26 个镜头踩 S6，其中 **24 个是结构性不可行的**
  （按引擎自己的估算，光是把这一镜的台词排完就要 94–470 帧，而计划只给了
  48–96 帧）。这不是"模型差几帧"，是"没人把预算告诉它"。

本模块只做一件事：把**引擎已经会算的那套数**（每句估算帧数、句间最小间隔、
收尾余量、最晚结束帧、装得下/装不下）摊开成一段可直接进提示词的文本。
数字全部来自 ``layer1_input.dialogue_timing`` 的单一真源，不另抄一份公式。

纯计算、不碰 bpy：B1、B4、审计与测试共用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..layer1_input.dialogue_timing import (
    CHINESE_CPS,
    DIALOGUE_GAP,
    DIALOGUE_TAIL_FRAMES,
    FPS,
    detect_emotion,
    estimate_dialogue_frames,
)
from .timing_tool import estimate_shot_duration

#: 探针用字：汉字本身没有语义，只用来量"几个字 = 几帧"。
_PROBE_CHAR = "字"
_CPS = CHINESE_CPS


@dataclass
class DialogueLineBudget:
    """一句对白的预算行。"""

    text: str
    frames: int
    declared_seconds: Optional[float] = None
    emotion: str = "normal"

    @property
    def source(self) -> str:
        return "剧本声明" if self.declared_seconds else "引擎估算"


@dataclass
class ShotDialogueBudget:
    """一个镜头的对白帧预算。"""

    shot_id: str = ""
    duration_frames: int = 0
    tail_frames: int = DIALOGUE_TAIL_FRAMES
    gap_frames: int = 0
    fps: int = FPS
    lines: List[DialogueLineBudget] = field(default_factory=list)
    #: 按声明顺序排完全部台词所占的**最晚帧号**（含收尾余量）。
    required_frames: int = 0
    #: 最后一句最晚可以结束在哪一帧（= 时长 − 收尾余量）。
    latest_allowed_end: int = 0
    #: 按声明顺序**最多**能装下几句（0 = 一句都排不下）。
    max_lines: int = 0

    @property
    def fits(self) -> bool:
        return self.required_frames <= self.duration_frames

    @property
    def overflow_frames(self) -> int:
        return max(self.required_frames - self.duration_frames, 0)

    @property
    def spare_frames(self) -> int:
        return max(self.duration_frames - self.required_frames, 0)

    def single_line_char_cap(self) -> int:
        """这一镜**只放一句**时，最多几个汉字（同一套语速公式算出来的）。

        台词还没分配（阶段 A 的计划只带 ``dialogue_ids``）时，B1 只能自己
        挑台词——那时唯一能给的"预算"就是这条：**一句话最长能有多长**，
        以及"最后一句最晚结束在哪一帧"。
        """
        budget = self.latest_allowed_end
        if budget <= 0:
            return 0
        best = 0
        for chars in range(1, 121):
            if estimate_dialogue_frames(_PROBE_CHAR * chars) > budget:
                break
            best = chars
        return best

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "duration_frames": self.duration_frames,
            "tail_frames": self.tail_frames,
            "gap_frames": self.gap_frames,
            "required_frames": self.required_frames,
            "latest_allowed_end": self.latest_allowed_end,
            "max_lines": self.max_lines,
            "fits": self.fits,
            "overflow_frames": self.overflow_frames,
            "spare_frames": self.spare_frames,
            "lines": [{"text": line.text, "frames": line.frames,
                       "declared_seconds": line.declared_seconds,
                       "emotion": line.emotion, "source": line.source}
                      for line in self.lines],
        }

    def render(self) -> str:
        """给模型看的一段。**逐字给数**，不留"自己估一估"的口子。"""
        if not self.lines:
            cap = self.single_line_char_cap()
            return (
                f"  · 本镜帧预算（**这一镜的台词由你分配时也必须满足它**，"
                f"R011 会逐镜核对）：\n"
                f"    - 镜头时长 {self.duration_frames} 帧，收尾余量 "
                f"{self.tail_frames} 帧 ⇒ 最后一句必须结束在第 "
                f"{self.latest_allowed_end} 帧以内；\n"
                f"    - 句间最小间隔 {self.gap_frames} 帧；\n"
                f"    - 语速：中文 {_CPS:g} 字/秒 @ {self.fps}fps ⇒ "
                f"5 字约 {estimate_dialogue_frames(_PROBE_CHAR * 5)} 帧、"
                f"10 字约 {estimate_dialogue_frames(_PROBE_CHAR * 10)} 帧；\n"
                f"    - 只放一句时最多 {cap} 个汉字（多句要一起挤进同一段）。")
        rows = "；".join(
            f"{index}.“{line.text}” 约 {line.frames} 帧（{line.source}）"
            for index, line in enumerate(self.lines, start=1))
        head = (f"  · 本镜帧预算（引擎按台词长度算的，**照它排帧**）：\n"
                f"    - 镜头时长 {self.duration_frames} 帧，收尾余量 "
                f"{self.tail_frames} 帧 ⇒ 最后一句最晚结束在第 "
                f"{self.latest_allowed_end} 帧；\n"
                f"    - 句间最小间隔 {self.gap_frames} 帧；\n"
                f"    - 台词与估算帧数：{rows}；\n"
                f"    - 按上面的顺序全排下需要 {self.required_frames} 帧。")
        if self.fits:
            return head + (f" 本镜装得下（余 {self.spare_frames} 帧）。"
                           f"起止帧必须落在 1–{self.latest_allowed_end} 内。")
        return head + (
            f"\n    - ⚠ **装不下**：超出 {self.overflow_frames} 帧，"
            f"本镜最多只排得下前 {self.max_lines} 句。"
            f"**不要删台词**：本镜的台词由剧本钉死（删/改写会让 R016 当场红）。"
            f"你能做的是把现有台词**按最小间隔排紧**（每句按上面的估算帧数、"
            f"句间只用 {self.gap_frames} 帧），让真实占用尽可能小；"
            f"剩下的超时是**脚本自身的时长不足**（镜头时长由阶段 A 与剧本声明拥有，"
            f"B1/B4 改不了），审计会如实记 R011 —— 那不是你的排帧错误。")


def _declared_seconds_for(shot) -> List[Optional[float]]:
    """剧本声明的逐句秒数（来自 ``dialogue_pins``，按顺序对齐）。

    数量对不上时一律返回 ``None``：宁可退回引擎估算，也不要错位借用别句的
    声明时长。
    """
    dialogues = list(getattr(shot, "dialogues", None) or [])
    pins = list(getattr(shot, "dialogue_pins", None) or [])
    if len(pins) != len(dialogues):
        return [None] * len(dialogues)
    return [pin.get("declared_s") for pin in pins]


def shot_dialogue_budget(shot, *, fps: int = FPS,
                         timing_source: str = "script_first",
                         dialogues: Optional[Sequence[Dict[str, Any]]] = None,
                         ) -> ShotDialogueBudget:
    """算出这一镜的对白帧预算。``shot`` 只用到 ``duration_frames`` 与台词。"""
    if dialogues is None:
        dialogues = [item for item in
                     (getattr(shot, "dialogues", None) or [])
                     if str((item or {}).get("text") or "").strip()]
        declared = _declared_seconds_for(shot)
    else:
        dialogues = [item for item in dialogues
                     if str((item or {}).get("text") or "").strip()]
        declared = [None] * len(dialogues)

    lines: List[DialogueLineBudget] = []
    payload: List[Dict[str, Any]] = []
    for index, item in enumerate(dialogues):
        text = str(item.get("text") or "")
        seconds = declared[index] if index < len(declared) else None
        declared_seconds = float(seconds) if seconds else None
        emotion = detect_emotion("", text)
        frames = estimate_dialogue_frames(
            text, emotion, fps=int(fps), declared_seconds=declared_seconds,
            timing_source=timing_source)
        lines.append(DialogueLineBudget(text=text, frames=int(frames),
                                        declared_seconds=declared_seconds,
                                        emotion=emotion))
        payload.append({"text": text, "emotion": emotion,
                        "declared_seconds": declared_seconds})

    duration = int(getattr(shot, "duration_frames", 0) or 0)
    result = estimate_shot_duration(payload, (), fps=int(fps),
                                    timing_source=timing_source)
    required = int(result["frames"])

    #: 按**声明顺序**贪心：前 k 句排得下就收下（顺序是硬约束——剧本里
    #: 先说的那句不能因为"短"被挪到后面）。
    max_lines = 0
    for count in range(1, len(lines) + 1):
        probe = estimate_shot_duration(payload[:count], (), fps=int(fps),
                                       timing_source=timing_source)
        if int(probe["frames"]) <= duration:
            max_lines = count
        else:
            break

    return ShotDialogueBudget(
        shot_id=str(getattr(shot, "shot_id", "") or ""),
        duration_frames=duration,
        tail_frames=DIALOGUE_TAIL_FRAMES,
        gap_frames=int(round(DIALOGUE_GAP * int(fps))),
        fps=int(fps),
        lines=lines,
        required_frames=required,
        latest_allowed_end=max(duration - DIALOGUE_TAIL_FRAMES, 0),
        max_lines=max_lines,
    )
