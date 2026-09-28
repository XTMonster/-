"""格式检测与分派（执行文档 v1.2 §4.1）。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .fdx import parse_fdx
from .fountain import CHINESE_SCENE_RE, SCENE_HEADING_RE, parse_fountain
from .model import ParsedScript


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
    """纯文本：先按场景标题切分；切不出就整篇当一场并标记需 LLM 结构化。"""
    lines = (text or "").split("\n")
    has_headings = any(SCENE_HEADING_RE.match(line.strip())
                       or CHINESE_SCENE_RE.match(line.strip())
                       for line in lines)
    if has_headings:
        script = parse_fountain(text, title=title)
        script.source_format = "text"
        return script

    script = ParsedScript(title=title, source_format="text",
                          needs_llm_structure=True)
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
