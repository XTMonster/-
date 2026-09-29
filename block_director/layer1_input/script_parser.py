"""格式检测与分派（执行文档 v1.2 §4.1）。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .fdx import parse_fdx
from .fountain import CHINESE_SCENE_RE, SCENE_HEADING_RE, parse_fountain
from .model import ParsedScript
from .shotlist import looks_like_shot_list, parse_shot_list


class ScriptParseError(RuntimeError):
    """剧本无法解析。消息里必须给出可执行的下一步。"""


SUFFIX_FORMATS = {".fountain": "fountain", ".fdx": "fdx", ".txt": "text",
                  ".text": "text", ".md": "text", ".pdf": "pdf"}


def detect_format(path: Union[str, Path]) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in SUFFIX_FORMATS:
        return SUFFIX_FORMATS[suffix]
    raise ScriptParseError(
        f"无法识别的剧本格式：{suffix or '（无扩展名）'}。"
        f"支持 .fountain / .fdx / .txt / .pdf")


def parse_pdf(path: Union[str, Path], *, title: str = "") -> ParsedScript:
    """PDF → 文本 → 纯文本路径（§4.1）。缺少依赖时明确报错。"""
    try:
        import pdfplumber  # noqa: F401
    except ImportError as exc:
        raise ScriptParseError(
            "解析 PDF 需要 pdfplumber。请先安装：\n"
            "  <blender>/<ver>/python/bin/python.exe -m pip install pdfplumber\n"
            "或把剧本另存为 .txt / .fountain 后重试。") from exc

    import pdfplumber

    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    text = "\n".join(pages)
    script = parse_text(text, title=title or Path(path).stem)
    script.source_format = "pdf"
    script.warnings.append("PDF 已抽取为纯文本：分页与页眉页脚可能残留，请核对场景划分")
    return script


def parse_text(text: str, *, title: str = "") -> ParsedScript:
    """纯文本：先认分镜表，再按场景标题切分，最后整篇当一场。

    v1.3 起优先识别**分镜表**（`节点/镜号/拍摄手法/预估时长` 那套格式）：
    它带着导演写死的镜号、景别、时长与台词，是"剧本落实审核"的声明侧来源。
    识别失败或解析异常时一律降级回旧路径，绝不因此拒绝一份剧本。
    """
    fallback_note = ""
    if looks_like_shot_list(text):
        try:
            script, _shot_list = parse_shot_list(text, title=title)
            if script.scenes:
                return script
            fallback_note = "分镜表里没有解析出任何节点或镜号，已退回纯文本"
        except Exception as exc:  # noqa: BLE001 - 降级而不是拒绝
            fallback_note = f"分镜表解析失败，已退回纯文本：{exc}"

    lines = (text or "").split("\n")
    has_headings = any(SCENE_HEADING_RE.match(line.strip())
                       or CHINESE_SCENE_RE.match(line.strip())
                       for line in lines)
    if has_headings:
        script = parse_fountain(text, title=title)
        script.source_format = "text"
        if fallback_note:
            script.warnings.append(fallback_note)
        return script

    script = ParsedScript(title=title, source_format="text",
                          needs_llm_structure=True)
    if fallback_note:
        script.warnings.append(fallback_note)
    from .model import ParsedAction, ParsedScene

    scene = ParsedScene(scene_number=1, heading="（未标注场景）")
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped:
            scene.actions.append(ParsedAction(text=stripped, source_index=index))
    script.scenes.append(scene)
    script.warnings.append("纯文本未包含场景标题：已整篇作为一场，建议交由 LLM 补全结构")
    return script


def parse_script(path: Union[str, Path], *,
                 title: Optional[str] = None) -> ParsedScript:
    """按扩展名解析剧本文件。"""
    path = Path(path)
    if not path.exists():
        raise ScriptParseError(f"剧本文件不存在：{path}")
    fmt = detect_format(path)
    name = title if title is not None else path.stem

    if fmt == "pdf":
        return parse_pdf(path, title=name)

    raw = path.read_text(encoding="utf-8", errors="replace")
    if fmt == "fdx":
        try:
            return parse_fdx(raw, title=name)
        except ValueError as exc:
            raise ScriptParseError(str(exc)) from exc
    if fmt == "fountain":
        return parse_fountain(raw, title=name)
    return parse_text(raw, title=name)
