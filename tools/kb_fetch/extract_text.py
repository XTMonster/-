"""管线第 2 步：正文抽取（去掉 Project Gutenberg 的页眉页脚与授权样板）。

`mode: manual` 的笔记原样通过（它们本来就是 Markdown 正文）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Dict, List, Optional, Sequence

try:
    from . import common
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common  # type: ignore

EXTRACTED = common.WORK / "extracted.jsonl"
FETCHED = common.WORK / "fetched.jsonl"

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
        text = strip_gutenberg(text)
    return common.normalize_text(text)


def run(records: Sequence[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for record in records:
        text = clean(record["text"], str(record.get("mode", "http")))
        if not text:
            continue
        out.append({**record, "text": text, "chars": len(text)})
    common.write_jsonl(EXTRACTED, out)
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
    print(json.dumps({"extracted": len(out)}, ensure_ascii=False))
    return 0 if out else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
