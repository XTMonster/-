"""Fountain 解析（执行文档 v1.2 §4.1）。

标准 Fountain 靠"角色名全大写"识别对白；中文剧本没有大小写，因此本实现
用一条**可解释的启发式**：短行 + 不含句读 + 后面紧跟内容 → 视为角色名。
这条规则在 parser 的 docstring 里写清楚，避免实现者各自发明一套。

被识别的元素：

- 场景标题：``INT.`` / ``EXT.`` / ``INT./EXT.`` / ``I/E`` / ``EST.``，
  以及中文的 ``第N场``、``场景N``；
- 转场：``CUT TO:`` / ``FADE OUT.`` 等（只记录不建模，预演不需要转场动画）；
- 角色名：全大写拉丁行，或短的中文行；
- 括注：整行被 ``()`` 或 ``（）`` 包住；
- 其余非空行为动作描写。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .model import ParsedAction, ParsedDialogue, ParsedScene, ParsedScript
from .timing import extract_declared_seconds

SCENE_HEADING_RE = re.compile(
    r"^\s*(INT\.?/EXT\.?|EXT\.?/INT\.?|I/E|INT\.?|EXT\.?|EST\.?)\s+(.*)$",
    re.IGNORECASE)
CHINESE_SCENE_RE = re.compile(r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*场|场景\s*[0-9]+)(.*)$")
TRANSITION_RE = re.compile(
    r"^\s*(CUT TO|SMASH CUT TO|FADE (IN|OUT|TO BLACK)?|DISSOLVE TO|MATCH CUT TO)"
    r"[:：]?\s*$", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\s*\d+\.?\s*$")
TITLE_KEYS = ("title:", "credit:", "author:", "authors:", "source:",
              "draft date:", "contact:", "copyright:")

CAST_ANCHOR = "【角色锚】"
#: R2-F5：场景锚块前缀。跟在角色锚之后，是导演对场景/环境的明确声明。
SCENE_ANCHOR = "【场景锚】"
#: 逐行声明：``名字：描述``（名字 ≤12 个汉字/拉丁字符，冒号前无句读）。
CAST_LINE_RE = re.compile(r"^([^：:、，,。；;\s]{1,12})[：:]")
#: 同行声明：``【角色锚】名字：描述……名字：描述``——取冒号前的短汉字/拉丁串。
CAST_INLINE_RE = re.compile(r"([\u4e00-\u9fffA-Za-z]{1,12})[：:]")

SENTENCE_MARKS = "。！？…"
CLAUSE_MARKS = "，、；：,;:"
MAX_CUE_CHARS = 24            # 拉丁角色名上限
MAX_CUE_CJK = 12              # 中文角色名上限


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _split_cue(line: str) -> Tuple[str, str]:
    """``小明（画外音）`` → ``("小明", "画外音")``。"""
    match = re.match(r"^(?P<name>[^（(]+)[（(](?P<ext>[^）)]*)[）)]\s*$", line)
    if match:
        return match.group("name").strip(), match.group("ext").strip()
    return line.strip(), ""


def _looks_like_cue(line: str, following: str) -> bool:
    if not following:
        return False
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_CUE_CHARS:
        return False
    if stripped.startswith((">", "=", "@", ".", "#")):
        return False
    if stripped.startswith(("（", "(")):
        return False
    if stripped.endswith(tuple(SENTENCE_MARKS)):
        return False
    if SCENE_HEADING_RE.match(stripped) or CHINESE_SCENE_RE.match(stripped):
        return False
    if TRANSITION_RE.match(stripped) or PAGE_NUMBER_RE.match(stripped):
        return False
    if stripped.upper() == stripped and any(c.isalpha() for c in stripped):
        return True                       # 拉丁全大写
    if any(_is_cjk(c) for c in stripped):
        return (len(stripped) <= MAX_CUE_CJK
                and not any(mark in stripped for mark in CLAUSE_MARKS))
    return False


def _parse_heading(line: str) -> Tuple[str, str, str, str]:
    """返回 ``(interior_exterior, location, time_of_day, heading)``。"""
    heading = line.strip()
    match = SCENE_HEADING_RE.match(heading)
    if match:
        raw = match.group(1).upper().replace(".", "")
        if "EXT" in raw and "INT" in raw:
            interior = "INT_EXT"
        elif raw.startswith("EXT") or raw.startswith("EST"):
            interior = "EXT"
        else:
            interior = "INT"
        body = match.group(2).strip()
    else:
        match = CHINESE_SCENE_RE.match(heading)
        interior = "INT"
        body = (match.group(2).strip() if match else heading)

    location, _, time_of_day = body.partition(" - ")
    if not location:
        location = body
    return interior, location.strip(), time_of_day.strip(), heading


def collect_cast_declarations(lines: List[str]) -> List[str]:
    """从 ``【角色锚】`` 块里收出场角色名（台词之外的角色也计入角色表）。

    支持两种写法：
    1. ``【角色锚】`` 独占一行，后续每行 ``名字：描述``（fixtures 写法）；
    2. ``【角色锚】名字：描述……名字：描述`` 同一行（白模预演剧本写法）。
    只收明确声明，不猜：名字是冒号前的短汉字/拉丁串，去重保序。
    """
    names: List[str] = []

    def _append(name: str) -> None:
        name = str(name or "").strip()
        if name and name not in names:
            names.append(name)

    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith(CAST_ANCHOR):
            rest = stripped[len(CAST_ANCHOR):].strip()
            if rest:
                for name in CAST_INLINE_RE.findall(rest):
                    _append(name)
            else:
                lookahead = index + 1
                while lookahead < len(lines) and lines[lookahead].strip():
                    candidate = lines[lookahead].strip()
                    match = CAST_LINE_RE.match(candidate)
                    if match is None:
                        break
                    _append(match.group(1))
                    lookahead += 1
                index = lookahead
                continue
        index += 1
    return names


def collect_scene_anchor_texts(lines: List[str]) -> List[str]:
    """从 ``【场景锚】`` 块收原文（R2-F5）。

    支持两种写法（与角色锚同口径）：
    1. ``【场景锚】`` 独占一行，后续非空行直到下一个锚块/标题前都是它的
       内容（fixtures 写法）；
    2. ``【场景锚】文本`` 同一行（白模预演剧本写法）。
    只收导演明确写下的声明原文，不在解析层编造或补全。
    """
    texts: List[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith(SCENE_ANCHOR):
            rest = stripped[len(SCENE_ANCHOR):].strip()
            if rest:
                texts.append(rest)
            else:
                lookahead = index + 1
                block: List[str] = []
                while lookahead < len(lines):
                    candidate = lines[lookahead].strip()
                    if not candidate:
                        break
                    if candidate.startswith(CAST_ANCHOR) \
                            or candidate.startswith(SCENE_ANCHOR):
                        break
                    block.append(candidate)
                    lookahead += 1
                if block:
                    texts.append("".join(block))
                index = lookahead
                continue
        index += 1
    return texts


def parse_fountain(text: str, *, title: str = "") -> ParsedScript:
    """把 Fountain 文本解析成结构化剧本。"""
    lines = [line.rstrip("\r") for line in (text or "").split("\n")]
    script = ParsedScript(title=title, source_format="fountain")
    script.cast_declarations = collect_cast_declarations(lines)
    script.scene_anchor_texts = collect_scene_anchor_texts(lines)

    index = 0
    # 标题页：开头连续的 "Key: value" 行
    if lines and lines[0].strip().lower().startswith(TITLE_KEYS):
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped:
                index += 1
                break
            key, _, value = stripped.partition(":")
            if key.strip().lower() + ":" in TITLE_KEYS and value.strip():
                if key.strip().lower() == "title":
                    script.title = value.strip() or script.title
            index += 1

    scene: Optional[ParsedScene] = None
    source_index = 0
    pending_cue: Optional[Tuple[str, str]] = None
    in_dialogue = False

    def ensure_scene() -> ParsedScene:
        nonlocal scene
        if scene is None:
            scene = ParsedScene(scene_number=1, heading="（未标注场景）",
                                location="", interior_exterior="INT")
            script.scenes.append(scene)
        return scene

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        following = ""
        lookahead = index + 1
        while lookahead < len(lines):
            if lines[lookahead].strip():
                following = lines[lookahead].strip()
                break
            lookahead += 1
        index += 1

        if not stripped:
            if in_dialogue:
                in_dialogue = False
                pending_cue = None
            continue
        if PAGE_NUMBER_RE.match(stripped) and not in_dialogue:
            continue
        if TRANSITION_RE.match(stripped):
            continue
        if stripped.startswith(CAST_ANCHOR):
            #: 角色锚是**角色表声明**，不是角色名 cue；不进入对白解析。
            ensure_scene()
            continue
        if stripped.startswith(SCENE_ANCHOR):
            #: 场景锚是**环境声明**，不是对白/动作；不进入对白解析。
            ensure_scene()
            continue

        if SCENE_HEADING_RE.match(stripped) or CHINESE_SCENE_RE.match(stripped):
            interior, location, time_of_day, heading = _parse_heading(stripped)
            scene = ParsedScene(scene_number=len(script.scenes) + 1,
                                heading=heading, location=location,
                                time_of_day=time_of_day,
                                interior_exterior=interior)
            script.scenes.append(scene)
            in_dialogue = False
            pending_cue = None
            continue

        current = ensure_scene()
        source_index += 1

        if in_dialogue and pending_cue is not None:
            name, extension = pending_cue
            if (stripped.startswith(("（", "("))
                    and stripped.endswith(("）", ")"))):
                current.dialogues.append(ParsedDialogue(
                    character=name, text="", parenthetical=stripped.strip("（）()"),
                    source_index=source_index))
                continue
            # 上一行若是纯括注，把括注补到这一句上
            if (current.dialogues and current.dialogues[-1].character == name
                    and not current.dialogues[-1].text
                    and current.dialogues[-1].parenthetical):
                text, declared = extract_declared_seconds(stripped)
                current.dialogues[-1].text = text
                current.dialogues[-1].declared_seconds = declared
                continue
            # 末端的"（约3秒）"是剧本声明的时长，必须抽出来单独记，
            # 不能留在台词文本里（§4.4 的优先级链以它为准）。
            text, declared = extract_declared_seconds(stripped)
            current.dialogues.append(ParsedDialogue(
                character=name, text=text, source_index=source_index,
                declared_seconds=declared))
            continue

        if _looks_like_cue(stripped, following):
            pending_cue = _split_cue(stripped)
            in_dialogue = True
            continue

        current.actions.append(ParsedAction(text=stripped,
                                            source_index=source_index))
        in_dialogue = False

    if not script.scenes:
        script.warnings.append("没有识别到任何场景标题，已按单场处理")
        script.scenes.append(ParsedScene(scene_number=1, heading="（未标注场景）"))
    return script
