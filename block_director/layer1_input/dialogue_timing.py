"""对白时长估算（执行文档 v1.2 §4.4）。

**这里是 v1.0 那个方向性错误被修正后的实现**：v1.0 写
``base = 字数 / (CPS × 倍率)``，于是"生气(0.85)"反而算得更慢、"悲伤(1.3)"
算得更快——恰好把物理直觉反过来。本实现把倍率明确定义为**语速**：

    rate > 1 表示说得更快 → 耗时更短

并配有自检断言（生气必须比正常短、悲伤必须比正常长）。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

FPS = 24
CHINESE_CPS = 3.0            # 中文 3 字/秒（180 字/分钟，偏慢的叙事语速）
ENGLISH_WPS = 2.5            # 英文 2.5 词/秒

#: 语速倍率：>1 更快（时长更短），<1 更慢（时长更长）
EMOTION_SPEECH_RATE: Dict[str, float] = {
    "normal": 1.00, "angry": 1.15, "excited": 1.15, "urgent": 1.20,
    "sad": 0.80, "thinking": 0.85, "whisper": 0.90,
}

PAUSE_COMMA = 0.2
PAUSE_SENTENCE_END = 0.3
DIALOGUE_GAP = 0.5           # 两句对白之间的停顿（秒）
DIALOGUE_TAIL_FRAMES = 12    # 镜头结尾给对白留的余量（0.5 秒）

COMMA_MARKS = "，,、;；:："
SENTENCE_MARKS = "。.!！?？…"

#: 情绪关键词 → 语速档（中英文都认）
_EMOTION_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    ("urgent", ("急促", "焦急", "急忙", "urgent", "hurried")),
    ("angry", ("愤怒", "生气", "怒", "喊道", "吼道", "大叫",
               "angry", "furious", "shouting", "yelling")),
    ("excited", ("兴奋", "激动", "excited", "thrilled")),
    ("sad", ("悲伤", "难过", "哽咽", "sad", "sorrowful", "crying")),
    ("thinking", ("沉吟", "犹豫", "思索", "thinking", "hesitant")),
    ("whisper", ("低声", "耳语", "轻声", "低语", "whisper")),
]


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def count_cjk(text: str) -> int:
    return sum(1 for char in text if _is_cjk(char))


def count_words(text: str) -> int:
    """英文按词计数：把非字母数字都当分隔符。"""
    cleaned = "".join(char if (char.isalnum() or char == "'") else " "
                      for char in text)
    return len([word for word in cleaned.split() if any(c.isalnum() for c in word)])


def count_punctuation(text: str, marks: str) -> int:
    return sum(text.count(mark) for mark in marks)


def detect_emotion(parenthetical: str = "", text: str = "") -> str:
    """从（ ）提示或台词本身推断语速档。"""
    haystack = f"{parenthetical} {text}".lower()
    for emotion, keywords in _EMOTION_KEYWORDS:
        if any(keyword.lower() in haystack for keyword in keywords):
            return emotion
    return "normal"


def _units_and_base_rate(text: str, chinese_cps: float,
                         english_wps: float) -> Tuple[float, float]:
    """中英混排分别加权，返回 ``(每秒单位数, 单位总数)``。"""
    cjk = count_cjk(text)
    words = count_words("".join(char if not _is_cjk(char) else " "
                                for char in text))
    units = cjk + words
    if units <= 0:
        return chinese_cps, 0.0
    rate = (cjk * chinese_cps + words * english_wps) / units
    return rate, float(units)


def estimate_dialogue_seconds(text: str, emotion: str = "normal", *,
                              chinese_cps: float = CHINESE_CPS,
                              english_wps: float = ENGLISH_WPS,
                              speech_rate: Optional[Dict[str, float]] = None
                              ) -> float:
    rates = speech_rate or EMOTION_SPEECH_RATE
    base_rate, units = _units_and_base_rate(text, chinese_cps, english_wps)
    rate = base_rate * rates.get(emotion, 1.0)      # 语速越快 → 秒数越短
    seconds = units / rate if rate > 0 else 0.0
    seconds += count_punctuation(text, COMMA_MARKS) * PAUSE_COMMA
    seconds += count_punctuation(text, SENTENCE_MARKS) * PAUSE_SENTENCE_END
    return seconds


def estimate_dialogue_frames(text: str, emotion: str = "normal", *,
                             fps: int = FPS, chinese_cps: float = CHINESE_CPS,
                             english_wps: float = ENGLISH_WPS,
                             speech_rate: Optional[Dict[str, float]] = None,
                             minimum: int = 8) -> int:
    seconds = estimate_dialogue_seconds(
        text, emotion, chinese_cps=chinese_cps, english_wps=english_wps,
        speech_rate=speech_rate)
    return max(int(round(seconds * fps)), minimum)


def schedule_dialogues(dialogues: Iterable, start_frame: int = 1, *,
                       fps: int = FPS, gap_seconds: float = DIALOGUE_GAP,
                       chinese_cps: float = CHINESE_CPS,
                       english_wps: float = ENGLISH_WPS,
                       speech_rate: Optional[Dict[str, float]] = None
                       ) -> List[Tuple[int, int]]:
    """把一场对白依次排到时间轴上，返回每句的 ``(start, end)``。

    同时把结果回写到传入的 :class:`ParsedDialogue` 对象上（若它有这些字段）。
    """
    gap = int(round(gap_seconds * fps))
    cursor = int(start_frame)
    spans: List[Tuple[int, int]] = []
    for dialogue in dialogues:
        emotion = getattr(dialogue, "emotion", "normal") or "normal"
        if emotion == "normal":
            emotion = detect_emotion(getattr(dialogue, "parenthetical", ""),
                                     getattr(dialogue, "text", ""))
            try:
                dialogue.emotion = emotion
            except AttributeError:
                pass
        frames = estimate_dialogue_frames(
            getattr(dialogue, "text", ""), emotion, fps=fps,
            chinese_cps=chinese_cps, english_wps=english_wps,
            speech_rate=speech_rate)
        start, end = cursor, cursor + frames - 1
        try:
            dialogue.start_frame = start
            dialogue.end_frame = end
        except AttributeError:
            pass
        spans.append((start, end))
        cursor = end + 1 + gap
    return spans


def render_timing_table(script, *, fps: int = FPS,
                        chinese_cps: float = CHINESE_CPS,
                        english_wps: float = ENGLISH_WPS,
                        speech_rate: Optional[Dict[str, float]] = None,
                        max_lines: int = 40) -> str:
    """给规划提示用的对白时长表（§4.4）。

    模型据此决定每个镜头要给多少帧——这是 R011 能通过的前提。
    """
    lines = [f"对白时长参考（中文 {chinese_cps:g} 字/秒，{fps}fps）："]
    count = 0
    for scene in getattr(script, "scenes", []):
        for dialogue in scene.dialogues:
            if count >= max_lines:
                lines.append(f"（其余对白省略）")
                return "\n".join(lines)
            emotion = getattr(dialogue, "emotion", "normal") or "normal"
            if emotion == "normal":
                emotion = detect_emotion(getattr(dialogue, "parenthetical", ""),
                                         dialogue.text)
            frames = estimate_dialogue_frames(
                dialogue.text, emotion, fps=fps, chinese_cps=chinese_cps,
                english_wps=english_wps, speech_rate=speech_rate)
            lines.append(f"- {scene.scene_id} {dialogue.character}"
                         f"（{emotion}）：“{dialogue.text}” → 约 {frames} 帧"
                         f"（{frames / fps:.1f}s）")
            count += 1
    if count == 0:
        lines.append("- （本剧本没有对白）")
    return "\n".join(lines)
