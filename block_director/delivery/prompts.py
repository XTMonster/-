"""Prompt 表 prompts.md（执行文档 v1.2 §15.5）。

把"白模预演"和"AI 视频生成"之间最后一段手工劳动自动化：用户拿着
参考视频作结构、首帧作输入图、这段文字作提示词，即可直接生成。
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from ..contracts.elements import ElementRegistry, shot_element_ids
from ..contracts.plan import Plan
from ..cinema.camera_motion import describe as describe_movement

SHOT_TYPE_LABELS: Dict[str, str] = {
    "ECU": "大特写", "CU": "特写", "MCU": "中近景", "MS": "中景",
    "MLS": "中远景", "LS": "全景", "ELS": "大远景", "OTS": "过肩", "POV": "主观",
}

DEFAULT_STYLE = "写实电影质感，35mm，柔和自然光"

STATIC_LABEL = "固定机位"

#: 元素类型的中文标签（元素表头用，与登记表的 kind 闭集一一对应）。
ELEMENT_KIND_LABELS: Dict[str, str] = {
    "character": "角色", "prop": "道具", "environment": "环境",
}

#: 结构化引用行的前缀（FR-A4 对拍只读这两类稳定 token 行）。
NAME_LINE_PREFIXES: tuple = ("**出场角色**：", "**元素**：")


def movement_label(movement: str) -> str:
    """单个运镜 id → 中文名；``static`` 与空值都读作固定机位。"""
    text = str(movement or "")
    if not text or text == "static":
        return STATIC_LABEL
    return describe_movement(text)


def movement_labels(shot) -> str:
    """这一镜的运镜中文名。

    v1.2 把"固定机位"写死在标题与提示词里，于是只要计划里带了运镜，
    ``prompts.md`` 就会**谎报**镜头运动。这里改为从计划读取，
    没有声明运镜时才回落到固定机位。
    """
    camera = getattr(shot, "camera", None) or {}
    raw = camera.get("movements") if isinstance(camera, dict) else None
    labels = []
    for item in raw or []:
        movement = (str(item.get("type") or "") if isinstance(item, dict)
                    else str(item))
        if movement:
            labels.append(movement_label(movement))
    if not labels and isinstance(camera, dict) and camera.get("movement"):
        labels.append(movement_label(str(camera["movement"])))
    return "、".join(labels) if labels else STATIC_LABEL


def compose_prompt(intent: str, shot_type: str, style: str,
                   movement: str = "static") -> str:
    """拼装一句可直接投喂视频模型的提示词。"""
    parts: List[str] = []
    if intent:
        parts.append(intent.rstrip("。."))
    label = SHOT_TYPE_LABELS.get(str(shot_type).upper())
    if label:
        parts.append(label)
    parts.append(movement_label(movement))
    if style:
        parts.append(style)
    return "，".join(part for part in parts if part)


def render_element_table(registry: ElementRegistry) -> str:
    """FR-A4 的头部"元素表"：与 ``elements.json`` 同一套稳定 id / 名字 / 颜色 / 形状。"""
    if not registry.elements:
        return ""
    lines = [
        "## 元素表", "",
        "| 元素 | 类型 | 名称 | 颜色 | 形状 | 首次出现 |",
        "|---|---|---|---|---|---|",
    ]
    for element in sorted(registry.elements, key=lambda item: item.id):
        kind = ELEMENT_KIND_LABELS.get(element.kind, element.kind)
        lines.append(f"| `{element.id}` | {kind} | {element.label} "
                     f"| {element.color_hex} | {element.shape or '—'} "
                     f"| {element.first_shot or '—'} |")
    return "\n".join(lines)


def unknown_prompt_names(text: str, registry: ElementRegistry) -> List[str]:
    """返回 prompts.md 里引用、但不在登记表中的名字（FR-A4 对拍）。

    只读**结构化引用行**（``出场角色`` / ``元素``）——它们才是稳定 token；
    自由文本的 Prompt 句子不做 NLP 推断。登记名 = 元素 id ∪ 显示名，命中即
    合法；表外名字去重、按字典序返回（报错顺序稳定）。空表 = 全部命中。
    """
    registered = {element.id for element in registry.elements}
    registered.update(element.label for element in registry.elements
                      if element.label)
    names = set()
    for line in (text or "").splitlines():
        for prefix in NAME_LINE_PREFIXES:
            if not line.startswith(prefix):
                continue
            names.update(name.strip()
                         for name in line[len(prefix):].split("、")
                         if name.strip())
    return sorted(name for name in names if name not in registered)


def render_prompt_sheet(plan: Plan, *, style: str = DEFAULT_STYLE,
                        fps: int = 24, resolution: Sequence[int] = (1280, 720),
                        project: str = "BlockDirector",
                        registry: Optional[ElementRegistry] = None,
                        failures: Optional[Sequence[Mapping[str, Any]]] = None,
                        pending_review: Optional[
                            Sequence[Mapping[str, Any]]] = None,
                        ) -> str:
    """生成 prompts.md 全文。

    传 ``registry``（v1.6 E1 / FR-A4）：头部渲染"元素表"，逐镜补一行
    "元素"（该镜的道具 + 环境件，按登记表显示名引用）。不传时与旧输出
    **逐字节一致**（旧调用方不受影响）。

    传 ``failures``（缺陷 D / T8，U1）：文末追加失败清单段——失败镜没有
    参考视频可投，必须如实标注而不是假装有产物。不传/空清单与旧输出
    **逐字节一致**（零行为差）。
    """
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
    if registry is not None and registry.elements:
        lines += [render_element_table(registry), ""]

    element_by_id = registry.by_id() if registry is not None else {}
    failed_by_id = {
        str(item.get("shot_id") or ""): item
        for item in (failures or [])
        if isinstance(item, Mapping)
    }
    pending_by_id = {
        str(item.get("shot_id") or ""): item
        for item in (pending_review or [])
        if isinstance(item, Mapping)
    }
    cursor = 1
    for shot in plan.shots:
        end = cursor + shot.duration_frames - 1
        seconds = round(shot.duration_frames / fps, 1)
        label = SHOT_TYPE_LABELS.get(str(shot.shot_type).upper(), str(shot.shot_type))
        lines.append(f"## {shot.shot_id}（{seconds}s / {label} / "
                     f"{movement_labels(shot)}）")
        lines.append("")
        lines.append(f"**帧范围**：{cursor}–{end}（共 {shot.duration_frames} 帧）")
        # v1.4 US-15：`景别` / `运镜` 必须是**可拆分的独立行**——逐字段对拍
        # 要拿它与计划的 `shot_type` / `camera.movements` 逐项比，塞在标题的
        # 括号里就只能靠正则猜。
        lines.append(f"**景别**：{label}")
        movements = movement_labels(shot)
        if movements:
            lines.append(f"**运镜**：{movements}")
        if shot.shot_id in failed_by_id:
            lines.append("**审核状态**：未通过（尽力版本）")
        elif shot.shot_id in pending_by_id:
            status = str(
                pending_by_id[shot.shot_id].get("status") or "unknown")
            lines.append(f"**审核状态**：待复核（{status}）")
        lines.append(f"**参考视频**：export/blockout_{shot.shot_id}.mp4")
        lines.append(f"**首帧**：export/first_frames/{shot.shot_id}.png")
        lines.append("")
        prompt = shot.prompt.strip() or compose_prompt(
            shot.intent, str(shot.shot_type), style)
        lines.append(f"**Prompt**：{prompt}")
        lines.append("")
        if shot.characters:
            lines.append(f"**出场角色**：{'、'.join(shot.characters)}")
        if registry is not None:
            in_frame = shot_element_ids(shot, registry)
            if in_frame:
                lines.append("**元素**：" + "、".join(
                    element_by_id[item].label for item in in_frame))
        if shot.dialogue_ids:
            lines.append(f"**对白**：{'、'.join(shot.dialogue_ids)}")
        if shot.actions:
            types = "、".join(str(a.get("action_type")) for a in shot.actions)
            lines.append(f"**动作**：{types}")
        if shot.intent:
            lines.append(f"**镜头意图**：{shot.intent}")
        lines.append("")
        cursor = end + 1
    failure_items = list(failures or [])
    if failure_items:
        from .failures import render_failures_markdown

        lines += ["## 失败清单", "",
                  "> 以下镜头未达到构图门槛；若已生成本镜 mp4，"
                  "该片只是最佳尽力版本，不是通过镜。"
                  "失败原因见交付包 `failures.json`：", ""]
        lines.append(render_failures_markdown(failure_items).rstrip())
        lines.append("")
    pending_items = list(pending_review or [])
    if pending_items:
        from .failures import render_pending_review_markdown

        lines.append(
            render_pending_review_markdown(pending_items).rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
