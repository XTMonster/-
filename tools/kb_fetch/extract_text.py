"""管线第 2 步：正文抽取（纯文本 / HTML / PDF）。

* `mode: manual` —— 自撰笔记原样通过（它们本来就是 Markdown 正文）；
* 纯文本 —— 去掉 Project Gutenberg 的页眉页脚与授权样板；
* **HTML** —— 抽可见正文（丢 `script/style/nav/footer`，块级标签转换行），
  用 stdlib 的 `html.parser`；
* **PDF** —— 现代教材/讲义/论文的**主体格式**，用 `pypdf` 抽文本。
  `pypdf` 是**可选开发依赖**：缺了它**报错并留痕**，绝不返回空串冒充成功
  （`pip install pypdf`）。自己写"近似 PDF 解析"会把正文搅成乱码，
  那是拿降级冒充能力。

抽取结果为空/失败**都留痕**在 `work/extract_rejects.jsonl`，不静默丢。
"""

from __future__ import annotations

import argparse
import html.parser
import json
import pathlib
import re
from typing import Tuple
from typing import Dict, List, Optional, Sequence

try:
    from . import common
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common  # type: ignore

EXTRACTED = common.WORK / "extracted.jsonl"
FETCHED = common.WORK / "fetched.jsonl"
EXTRACT_REJECTS = common.WORK / "extract_rejects.jsonl"
PDF_MAGIC = b"%PDF"
_HTML_HINT = re.compile(r"<(?:!doctype\s+html|html|head|body)\b", re.IGNORECASE)
_SKIP_ELEMENTS = {"script", "style", "noscript", "svg", "head", "template"}
_BLOCK_ELEMENTS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5",
                   "h6", "section", "article", "header", "footer", "table", "ul", "ol"}


class ExtractionError(RuntimeError):
    """抽取失败（要留痕并拒收，不许静默返回空串）。"""


class _TextCollector(html.parser.HTMLParser):
    """把 HTML 收敛成可见正文：跳过的元素整棵子树不要，块级标签当换行。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):  # noqa: D102
        if tag in _SKIP_ELEMENTS:
            self._skip_depth += 1
        elif tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")

    def handle_endtag(self, tag):  # noqa: D102
        if tag in _SKIP_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")

    def handle_data(self, data):  # noqa: D102
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def strip_html(text: str) -> str:
    """HTML → 可见正文（stdlib）。实体由 `convert_charrefs` 还原。"""
    parser = _TextCollector()
    parser.feed(text)
    parser.close()
    return parser.text()


def extract_pdf(raw: bytes) -> str:
    """PDF → 文本。缺 `pypdf` 时**报错**（附安装命令），不静默成功。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise ExtractionError("缺少 pypdf：请先 `pip install pypdf`（PDF 是可选开发依赖）") from exc
    import io

    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 - 具体异常类型随版本变，统一留痕
        raise ExtractionError(f"pdf_parse_failed:{type(exc).__name__}:{exc}") from exc
    return "\n\n".join(page for page in pages if page.strip())

_PG_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
                       re.IGNORECASE | re.DOTALL)
_PG_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
                     re.IGNORECASE | re.DOTALL)


def strip_gutenberg(text: str) -> str:
    """只保留 `*** START ***` 与 `*** END ***` 之间的正文。"""
    start_match = _PG_START.search(text)
    if start_match:
        text = text[start_match.end():]
    end_match = _PG_END.search(text)
    if end_match:
        text = text[:end_match.start()]
    return text


def clean(text: str, mode: str) -> str:
    if mode == "http":
        if _HTML_HINT.search(text[:4096]):
            text = strip_html(text)
        else:
            text = strip_gutenberg(text)
    return common.normalize_text(text)


def extract_record(record: Dict) -> Tuple[str, str]:
    """返回 `(正文, 拒收原因)`；成功时原因为空串。"""
    mode = str(record.get("mode", "http"))
    raw = b""
    cache_path = str(record.get("cache_path") or "")
    if mode == "http" and cache_path:
        path = common.ROOT / cache_path
        if path.is_file():
            raw = path.read_bytes()
    if raw[:4] == PDF_MAGIC:
        try:
            return common.normalize_text(extract_pdf(raw)), ""
        except ExtractionError as exc:
            return "", str(exc)
    text = clean(str(record.get("text", "")), mode)
    if not text:
        return "", "empty_after_clean"
    return text, ""


def run(records: Sequence[Dict]) -> List[Dict]:
    out: List[Dict] = []
    rejects: List[Dict] = []
    for record in records:
        text, reason = extract_record(record)
        if not text:
            rejects.append({"url": (record.get("source_ref") or {}).get("url", ""),
                            "domain": record.get("domain", ""), "reason": reason})
            continue
        out.append({**record, "text": text, "chars": len(text)})
    common.write_jsonl(EXTRACTED, out)
    common.write_jsonl(EXTRACT_REJECTS, rejects)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.extract_text")
    parser.add_argument("--only", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    records = common.read_jsonl(FETCHED)
    if args.only:
        records = [r for r in records
                   if args.only in (r["domain"], common.source_slug({"url": r["source_ref"]["url"]}))]
    out = run(records)
    rejects = common.read_jsonl(EXTRACT_REJECTS)
    print(json.dumps({"extracted": len(out), "rejected": len(rejects),
                      "rejects_detail": rejects[:5]}, ensure_ascii=False))
    return 0 if out else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
