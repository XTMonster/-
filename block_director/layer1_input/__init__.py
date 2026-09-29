"""剧本解析层（执行文档 v1.2 §4）。

纯 Python：解析、对白计时与共指消解都不依赖 bpy，因此可单测。
"""

from __future__ import annotations

from .dialogue_timing import (
    CHINESE_CPS,
    DIALOGUE_GAP,
    EMOTION_SPEECH_RATE,
    ENGLISH_WPS,
    count_cjk,
    count_words,
    detect_emotion,
    estimate_dialogue_frames,
    estimate_dialogue_seconds,
    schedule_dialogues,
    render_timing_table,
)
from .model import (
    ParsedAction,
    ParsedDialogue,
    ParsedNodeDeclaration,
    ParsedScene,
    ParsedScript,
    ParsedShotDeclaration,
)
from .fdx import parse_fdx
from .fountain import parse_fountain
from .script_parser import ScriptParseError, detect_format, parse_script, parse_text
from .shotlist import (
    ShotList,
    looks_like_shot_list,
    parse_shot_list,
)
from .coreference import (
    apply_deterministic_coreferences,
    apply_mapping,
    collect_names,
    exact_groups,
    is_pronoun,
    normalize_name,
    resolve_coreferences,
)

__all__ = [
    "ParsedScript", "ParsedScene", "ParsedAction", "ParsedDialogue",
    "ParsedNodeDeclaration", "ParsedShotDeclaration",
    "parse_script", "parse_text", "detect_format", "ScriptParseError",
    "parse_fountain", "parse_fdx",
    "parse_shot_list", "looks_like_shot_list", "ShotList",
    "resolve_coreferences", "apply_mapping", "collect_names", "exact_groups",
    "normalize_name", "is_pronoun", "apply_deterministic_coreferences",
    "estimate_dialogue_frames", "estimate_dialogue_seconds",
    "schedule_dialogues", "detect_emotion", "count_cjk", "count_words",
    "render_timing_table",
    "CHINESE_CPS", "ENGLISH_WPS", "EMOTION_SPEECH_RATE", "DIALOGUE_GAP",
]
