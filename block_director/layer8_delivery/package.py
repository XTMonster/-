"""白模参考包装配（v1.7 卡 I3，TDD §12.3，R-痛点 M2 交付半）。

纯层、无 bpy：把导出目录里已有的元素登记表与镜头数据组装成五件套——
``README.md`` / ``prompt_<target>.txt`` / ``shot_cards.md`` /
``continuity.json`` / ``responsibility.md``。目标模型适配在
``target_advisor.py``（I4）做，这里只消费其结果。

模板文件（``specs/prompt_templates/``）三份逐字相同，只含 5 个占位符；
渲染用 ``string.Template.substitute``（严格，缺槽抛错不静默）。
"""

from __future__ import annotations

import json
import os
import string
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..cinema.anchor import DEFAULT_TOTAL_HEIGHT
from ..contracts.elements import Element
from ..contracts.target_models import TargetModelError, load_table
from .reference_cards import assign_card_names
from .target_advisor import suggest_slices

#: 模板目录（package.py 位于 ``block_director/layer8_delivery/``，上溯两级到仓库根）。
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "specs" / "prompt_templates"

#: SPEC v2 §3.6 模板静态句②（逐字）。
STATIC_COLOUR_SENTENCE = (
    "画面中的几何体全部是占位符；占位符颜色仅用于区分角色身份"
    "（同色即同人），不代表最终外观、材质与色调。")

#: M2 同色时替换的中性句（逐字）。
NEUTRAL_COLOUR_SENTENCE = (
    "画面中的几何体全部是占位符；占位符颜色不代表任何含义，"
    "不代表最终外观、材质与色调。")

#: M2 warning 逐字。
M2_WARNING = (
    "reference_pack: 检测到同色角色（同色即同人）声明不成立，"
    "模板已改中性句（见 README 角色名册）。")

#: SPEC v2 §3.6 三 authority 变体逐字。
AUTHORITY_CARD_AND_STYLE = (
    "角色外观、表情与动作细节，以随包角色定妆卡与逐镜镜头卡"
    "（shot_cards.md）为准；场景风格与色调以风格参考图为准。")
AUTHORITY_CARD_NO_STYLE = (
    "角色外观、表情与动作细节，以随包角色定妆卡与逐镜镜头卡"
    "（shot_cards.md）为准；场景风格与色调以镜头卡文字描述为准。")
AUTHORITY_NO_CARD = (
    "角色外观、表情、动作细节与场景风格，一律以逐镜镜头卡"
    "（shot_cards.md）的文字描述为准。")

#: README 名册表头（SPEC v2 §3.2 逐字）。
README_HEADER = "| 角色名 | 占位色 | 身高 | 定妆卡文件 | 出场镜号 |"
README_SEPARATOR = "| --- | --- | --- | --- | --- |"

#: shot_cards 表头（SPEC v2 §3.3 逐字）。
SHOT_CARDS_HEADER = "| 镜号 | 景别 | 时长s | 运镜文字 | 出场角色 | 台词数 | 连续性指针 |"
SHOT_CARDS_SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- |"

#: 五件套文件名与一句话用途（README 里的说明部分）。
PACK_FILES: Dict[str, str] = {
    "README.md": "交付清单、角色名册与切片建议总览",
    "prompt_<target>.txt": "给目标视频模型的逐字提示词（模板渲染结果）",
    "shot_cards.md": "逐镜镜头卡：景别、时长、运镜文字与出场角色",
    "continuity.json": "整场连续性快照：每镜屏幕左右分组与朝向",
    "responsibility.md": "各镜分工声明：白模/提示词/参考图职责分区",
}


@dataclass
class ReferencePack:
    """白模参考包装配结果（SPEC v2 §3.1 唯一真源）。"""

    out_dir: Path
    files: List[str]
    prompt: str
    shot_cards: str
    continuity: str
    responsibility: str
    rendered_count: int
    shot_count: int
    warnings: List[str]


def _target_key(config: Any) -> str:
    """目标模型键：``config.target_model``；未知值回落 seedance_2.5。"""
    name = str(getattr(config, "target_model", "") or "")
    if not name:
        delivery = getattr(config, "delivery", None)
        if delivery is not None:
            name = str(getattr(delivery, "target_model", "") or "")
    table = load_table()
    return name if name in table else "seedance_2.5"


def _config_flag(config: Any, name: str, default: bool = False) -> bool:
    """扁平字段优先；为兼容 SPEC 的 ``config.delivery.*`` 写法加一层兜底。"""
    value = getattr(config, name, None)
    if value is None:
        delivery = getattr(config, "delivery", None)
        value = getattr(delivery, name, default)
    return bool(value)


def _render_template(template: str, mapping: Dict[str, Any]) -> str:
    """严格替换 + 空槽删行 + 连续空行压成一行（SPEC v2 §3.6）。"""
    text = string.Template(template).substitute(mapping)
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _authority_sentence(has_reference_cards: bool,
                        has_style_image: bool = False) -> str:
    """SPEC v2 §3.6 authority 三变体逐字。"""
    if not has_reference_cards:
        return AUTHORITY_NO_CARD
    if has_style_image:
        return AUTHORITY_CARD_AND_STYLE
    return AUTHORITY_CARD_NO_STYLE


def _slice_sentence(key: str, plan: Any, spec: Any) -> str:
    """按目标模型键产 slice 句；无切点返回空串（整句删掉）。"""
    slices = suggest_slices(plan, spec)
    if not slices:
        return ""
    count = len(slices) + 1
    if key == "kling":
        return (
            "时间线超出单段上限，已建议按 5/10 秒档位组织为 "
            f"{count} 段（切点全在镜头切换处，见 README）；逐段喂入并保持段序。")
    if key == "hailuo_h3":
        return (
            "时间线超出单段上限，已建议按 4–15 秒段组织为 "
            f"{count} 段，注意参考文件预算（图 9 / 视频 3 / 音频 3）"
            "（切点全在镜头切换处，见 README）；逐段喂入并保持段序。")
    return (
        "时间线超出单段上限，已建议切为 "
        f"{count} 段（切点全在镜头切换处，见 README）；逐段喂入并保持段序。")


def _load_elements(export_dir: Path,
                   elements: Optional[Any] = None) -> List[Element]:
    """归一元素：None → 读 elements.json；dict（registry 形）或 list 都接受。"""
    if elements is None:
        path = export_dir / "elements.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(
                "reference_pack: 缺少元素登记表（elements.json），拒绝猜测"
            ) from exc
    else:
        raw = elements
    if isinstance(raw, dict):
        raw = raw.get("elements") or []
    if not isinstance(raw, list):
        raise ValueError(
            f"reference_pack: 元素登记表形态非法（收到 {type(raw).__name__}）")
    return [Element.from_dict(item) for item in raw]


def _same_colour_characters(elements: Sequence[Element]) -> bool:
    """M2 判据：≥2 个角色（kind==character 且 color_hex 非空）同色。"""
    colours = [element.color_hex for element in elements
               if element.kind == "character" and element.color_hex]
    return any(count >= 2 for count in Counter(colours).values())


def _readme(plan: Any, config: Any, target_key: str, spec: Any,
            elements: Sequence[Element], names: Dict[str, str],
            manifest: Dict[str, Any], rendered_count: int,
            slice_sentence: str) -> str:
    """README.md 全文：目标模型、镜数/渲染段数、名册、五件套、切片说明。"""
    shot_count = len(plan.shots)
    lines = [
        f"# 白模参考包 · 目标模型 {spec.label}",
        "",
        f"- 总镜数：{shot_count}；白模视频段数：{rendered_count}。",
        f"- 提示词模板：`prompt_{target_key}.txt`（{spec.label}）。",
        "",
        "## 角色名册",
        "",
        README_HEADER,
        README_SEPARATOR,
    ]
    shots_by_id: Dict[str, Dict[str, Any]] = {
        str(shot.get("shot_id") or ""): shot
        for shot in (manifest.get("shots") or [])}
    has_cards = _config_flag(config, "reference_cards", True)
    for element in elements:
        if element.kind != "character":
            continue
        shots: List[str] = []
        for shot_id, shot in shots_by_id.items():
            if element.id in (shot.get("characters") or []):
                shots.append(shot_id)
        colour = element.color_hex or "-"
        height = f"{DEFAULT_TOTAL_HEIGHT:.2f}"
        if has_cards:
            card = f"reference/characters/{names.get(element.id, 'character')}.png"
        else:
            card = "（未生成）"
        lines.append(
            f"| {element.label} | {colour} | {height} | {card} | "
            f"{'、'.join(shots) if shots else '-'} |")
    lines += [
        "",
        "## 交付物",
        "",
        "| 文件 | 用途 |",
        "| --- | --- |",
    ]
    for name, purpose in PACK_FILES.items():
        actual = name.replace("<target>", target_key)
        lines.append(f"| `{actual}` | {purpose} |")
    if slice_sentence:
        lines += ["", "## 切片建议", "", slice_sentence]
    return "\n".join(lines) + "\n"


def _shot_cards(manifest: Dict[str, Any]) -> str:
    """shot_cards.md 全文（SPEC v2 §3.3）。"""
    lines = ["# 逐镜镜头卡", "", SHOT_CARDS_HEADER, SHOT_CARDS_SEPARATOR]
    for shot in (manifest.get("shots") or []):
        declared = shot.get("declared") or {}
        shot_type = str(declared.get("shot_type") or "").strip() \
            or str(shot.get("shot_type") or "").strip() or "-"
        duration = float(shot.get("duration_seconds") or 0.0)
        narration = str(shot.get("camera_narration") or "").strip() or "-"
        characters = "、".join(str(item) for item
                               in (shot.get("characters") or []))
        dialogue_count = len(shot.get("dialogue_ids") or [])
        continuity_in = str(shot.get("continuity_in") or "").strip() or "-"
        lines.append(
            f"| {shot.get('shot_id')} | {shot_type} | {duration:.1f} | "
            f"{narration} | {characters} | {dialogue_count} | "
            f"{continuity_in} |")
    return "\n".join(lines) + "\n"


def _responsibility(plan: Any, rendered_count: int) -> str:
    """responsibility.md 全文（SPEC v2 §3.4）。"""
    shot_count = len(plan.shots)
    skipped = shot_count - rendered_count
    lines = ["# 各镜分工声明", ""]
    if skipped:
        lines.append(
            f"（其中 {skipped} 镜声明直出提示词＋参考图，无白模视频，"
            "见 responsibility.md）")
        lines.append("")
    for shot in plan.shots:
        responsibility = shot.responsibility
        if responsibility is None:
            lines.append(f"- {shot.shot_id}: 未声明")
            continue
        data = responsibility.to_dict()
        white_model = "、".join(str(item) for item in data.get("white_model") or [])
        prompt = "、".join(str(item) for item in data.get("prompt") or [])
        ref_image = "、".join(str(item) for item in data.get("ref_image") or [])
        skip = "true" if bool(data.get("skip_white_model")) else "false"
        lines.append(
            f"- {shot.shot_id}: white_model={white_model}; prompt={prompt}; "
            f"ref_image={ref_image}; skip_white_model={skip}")
    return "\n".join(lines) + "\n"


def _write(out_dir: Path, name: str, text: str) -> Path:
    path = out_dir / name
    path.write_text(text, encoding="utf-8")
    return path


def build_reference_pack(export_dir, plan, config, manifest, *,
                         continuity=None, elements=None,
                         slice_sentence=None) -> ReferencePack:
    """装配五件套（SPEC v2 §3.1 唯一真源）。"""
    export_dir = Path(export_dir)
    out_dir = export_dir / "reference_pack"
    out_dir.mkdir(parents=True, exist_ok=True)

    target_key = _target_key(config)
    table = load_table()
    spec = table[target_key]
    template_path = TEMPLATE_DIR / f"{target_key}.txt"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TargetModelError(f"reference_pack 模板缺失：{template_path}") from exc

    element_objects = _load_elements(export_dir, elements)
    names = assign_card_names(element_objects)
    shot_count = len(plan.shots)
    skipped = sum(
        1 for shot in plan.shots
        if shot.responsibility is not None
        and bool(shot.responsibility.skip_white_model))
    rendered_count = shot_count - skipped

    warnings: List[str] = []
    if slice_sentence is None:
        slice_sentence = _slice_sentence(target_key, plan, spec)

    mapping = {
        "target_label": spec.label,
        "shot_count": shot_count,
        "rendered_count": rendered_count,
        "authority_sentence": _authority_sentence(
            _config_flag(config, "reference_cards", True)),
        "slice_sentence": slice_sentence,
    }
    prompt = _render_template(template, mapping)
    if rendered_count < shot_count:
        note = (
            f"（其中 {skipped} 镜声明直出提示词＋参考图，无白模视频，"
            "见 responsibility.md）")
        first_newline = prompt.find("\n")
        if first_newline != -1:
            prompt = prompt[:first_newline] + "\n" + note + prompt[first_newline:]
        else:
            prompt = prompt + "\n" + note + "\n"
    if _same_colour_characters(element_objects):
        prompt = prompt.replace(STATIC_COLOUR_SENTENCE,
                                NEUTRAL_COLOUR_SENTENCE)
        warnings.append(M2_WARNING)

    shot_cards_text = _shot_cards(manifest)
    continuity_text = json.dumps(continuity if continuity is not None else {},
                                 ensure_ascii=False, indent=2)
    responsibility_text = _responsibility(plan, rendered_count)
    readme_text = _readme(
        plan, config, target_key, spec, element_objects, names,
        manifest, rendered_count, slice_sentence)

    files: List[str] = []
    for name, text in (
        ("README.md", readme_text),
        (f"prompt_{target_key}.txt", prompt),
        ("shot_cards.md", shot_cards_text),
        ("continuity.json", continuity_text),
        ("responsibility.md", responsibility_text),
    ):
        path = _write(out_dir, name, text)
        files.append(os.path.abspath(str(path)))

    return ReferencePack(
        out_dir=out_dir,
        files=files,
        prompt=prompt,
        shot_cards=shot_cards_text,
        continuity=continuity_text,
        responsibility=responsibility_text,
        rendered_count=rendered_count,
        shot_count=shot_count,
        warnings=warnings,
    )


__all__ = [
    "ReferencePack",
    "build_reference_pack",
    "_render_template",
    "_slice_sentence",
    "_target_key",
    "_authority_sentence",
]
