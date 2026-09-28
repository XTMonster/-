"""Final Draft (.fdx) 解析（执行文档 v1.2 §4.1）。"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from .fountain import _parse_heading, _split_cue
from .model import ParsedAction, ParsedDialogue, ParsedScene, ParsedScript

DIALOGUE_TYPES = {"dialogue"}
ACTION_TYPES = {"action"}
CHARACTER_TYPES = {"character"}
PARENTHETICAL_TYPES = {"parenthetical"}
HEADING_TYPES = {"scene heading"}
SKIP_TYPES = {"transition", "shot", "general", "cast list", "new act",
              "end of act"}


def _paragraph_type(node) -> str:
    return str(node.attrib.get("Type", "")).strip().lower()


def _paragraph_text(node) -> str:
    return "".join(part.text or "" for part in node.iter("Text")).strip()


def parse_fdx(text: str, *, title: str = "") -> ParsedScript:
    """解析 FDX；结构由段落 ``Type`` 属性直接给出，不需要启发式。"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"FDX 不是合法 XML: {exc}") from exc

    script = ParsedScript(title=title, source_format="fdx")
    scene: Optional[ParsedScene] = None
    pending_character: Optional[str] = None
    source_index = 0

    for node in root.iter("Paragraph"):
        kind = _paragraph_type(node)
        body = _paragraph_text(node)
        if not body or kind in SKIP_TYPES:
            continue
        source_index += 1

        if kind in HEADING_TYPES:
            interior, location, time_of_day, heading = _parse_heading(body)
            scene = ParsedScene(scene_number=len(script.scenes) + 1,
                                heading=heading, location=location,
                                time_of_day=time_of_day,
                                interior_exterior=interior)
            script.scenes.append(scene)
            pending_character = None
            continue

        if scene is None:
            scene = ParsedScene(scene_number=1, heading="（未标注场景）")
            script.scenes.append(scene)

        if kind in CHARACTER_TYPES:
            name, _extension = _split_cue(body)
            pending_character = name
            continue
        if kind in PARENTHETICAL_TYPES and pending_character:
            scene.dialogues.append(ParsedDialogue(
                character=pending_character, text="",
                parenthetical=body.strip("（）()"), source_index=source_index))
            continue
        if kind in DIALOGUE_TYPES:
            name = pending_character or "（未知）"
            if (scene.dialogues and scene.dialogues[-1].character == name
                    and not scene.dialogues[-1].text
                    and scene.dialogues[-1].parenthetical):
                scene.dialogues[-1].text = body
            else:
                scene.dialogues.append(ParsedDialogue(
                    character=name, text=body, source_index=source_index))
            continue
        if kind in ACTION_TYPES:
            scene.actions.append(ParsedAction(text=body,
                                              source_index=source_index))

    if not script.scenes:
        script.warnings.append("FDX 中没有场景标题")
        script.scenes.append(ParsedScene(scene_number=1, heading="（未标注场景）"))
    return script
