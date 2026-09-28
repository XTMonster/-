"""Prompt 表 prompts.md（执行文档 v1.2 §15.5）。

把"白模预演"和"AI 视频生成"之间最后一段手工劳动自动化：用户拿着
参考视频作结构、首帧作输入图、这段文字作提示词，即可直接生成。
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from ..contracts.plan import Plan

SHOT_TYPE_LABELS: Dict[str, str] = {
    "ECU": "大特写", "CU": "特写", "MCU": "中近景", "MS": "中景",
    "MLS": "中远景", "LS": "全景", "ELS": "大远景", "OTS": "过肩", "POV": "主观",
}

DEFAULT_STYLE = "写实电影质感，35mm，柔和自然光"

MOVEMENT_LABELS = {"static": "固定机位"}


def compose_prompt(intent: str, shot_type: str, style: str,
                   movement: str = "static") -> str:
    """拼装一句可直接投喂视频模型的提示词。"""
    parts: List[str] = []
    if intent:
        parts.append(intent.rstrip("。."))
    label = SHOT_TYPE_LABELS.get(str(shot_type).upper())
    if label:
        parts.append(label)
    parts.append(MOVEMENT_LABELS.get(movement, movement))
    if style:
        parts.append(style)
    return "，".join(part for part in parts if part)


def render_prompt_sheet(plan: Plan, *, style: str = DEFAULT_STYLE,
                        fps: int = 24, resolution: Sequence[int] = (1280, 720),
                        project: str = "BlockDirector") -> str:
    """生成 prompts.md 全文。"""
    width, height = (list(resolution) + [1280, 720])[:2]
    lines: List[str] = [f"# {project} — 分镜 Prompt 表", ""]
    if plan.scene_heading:
        lines += [f"> 场景：{plan.scene_heading}", ""]
    lines += [
        f"- 参考视频分辨率：{width}×{height} @ {fps}fps",
        f"- 全局风格：{style}",
        "- 用法：把该镜的 **mp4 作为参考视频**、**首帧 PNG 作为输入图**、"
        "下面的 Prompt 作为提示词，投给视频生成模型。",
        "",
    ]

    cursor = 1
    for shot in plan.shots:
        end = cursor + shot.duration_frames - 1
        seconds = round(shot.duration_frames / fps, 1)
        label = SHOT_TYPE_LABELS.get(str(shot.shot_type).upper(), str(shot.shot_type))
        lines.append(f"## {shot.shot_id}（{seconds}s / {label} / 固定机位）")
        lines.append("")
        lines.append(f"**帧范围**：{cursor}–{end}（共 {shot.duration_frames} 帧）")
        lines.append(f"**参考视频**：export/blockout_{shot.shot_id}.mp4")
        lines.append(f"**首帧**：export/first_frames/{shot.shot_id}.png")
        lines.append("")
        prompt = shot.prompt.strip() or compose_prompt(
            shot.intent, str(shot.shot_type), style)
        lines.append(f"**Prompt**：{prompt}")
        lines.append("")
        if shot.characters:
            lines.append(f"**出场角色**：{'、'.join(shot.characters)}")
        if shot.dialogue_ids:
            lines.append(f"**对白**：{'、'.join(shot.dialogue_ids)}")
        if shot.actions:
            types = "、".join(str(a.get("action_type")) for a in shot.actions)
            lines.append(f"**动作**：{types}")
        if shot.intent:
            lines.append(f"**镜头意图**：{shot.intent}")
        lines.append("")
        cursor = end + 1
    return "\n".join(lines).rstrip() + "\n"
