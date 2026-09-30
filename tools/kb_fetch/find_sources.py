"""按主题找**他人著作**的来源（开发侧探针）：Gutenberg 官方目录 → 关键词筛 → 逐本验证。

为什么不是抓检索页：Gutenberg 的 `/ebooks/search` 被它**自己的 robots.txt 禁止**
（`fetch.py` 如实拒收）。它对镜像开放的是目录文件
`cache/epub/feeds/pg_catalog.csv`——用允许的路径拿到同一批元数据。

    python tools/kb_fetch/find_sources.py --domain anime --terms animation cartoon
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import re
import sys
import time
from typing import Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common, extract_text, fetch  # noqa: E402

CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
CATALOG_CACHE = common.WORK / "modern" / "pg_catalog.csv"


def catalog_rows(cache: pathlib.Path | None = None) -> List[Dict[str, str]]:
    path = pathlib.Path(cache or CATALOG_CACHE)
    if not path.is_file():
        source = {"url": CATALOG_URL, "title": "Project Gutenberg catalog",
                  "author": "Project Gutenberg", "license": "PublicDomain",
                  "domain": "cinematography", "mode": "http"}
        record = fetch.fetch_source(source, 120.0, 1.0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record["text"], encoding="utf-8", newline="\n")
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8", errors="replace"))))


def search(terms: Sequence[str], limit: int = 6,
           cache: pathlib.Path | None = None) -> List[Dict[str, str]]:
    """标题/主题/作者里出现任一关键词的书（按目录顺序，去重）。"""
    out: List[Dict[str, str]] = []
    seen = set()
    needles = [term.lower() for term in terms]
    for row in catalog_rows(cache):
        if str(row.get("Type", "")).lower() not in ("text", ""):
            continue
        haystack = " ".join([str(row.get("Title", "")), str(row.get("Subjects", "")),
                             str(row.get("Authors", ""))]).lower()
        if not any(needle in haystack for needle in needles):
            continue
        ebook_id = str(row.get("Text#", "")).strip()
        if not ebook_id or ebook_id in seen:
            continue
        seen.add(ebook_id)
        out.append({"id": ebook_id,
                    "title": re.sub(r"\s+", " ", str(row.get("Title", ""))).strip(),
                    "author": re.sub(r"\s+", " ", str(row.get("Authors", ""))).strip()})
        if len(out) >= limit:
            break
    return out


def plaintext_url(ebook_id: str) -> str:
    return f"https://www.gutenberg.org/cache/epub/{ebook_id}/pg{ebook_id}.txt"


def verify(hits: Sequence[Dict[str, str]], domain: str,
           timeout: float = 60.0, rate: float = 1.0) -> List[Dict]:
    """逐本走管线自己的 fetch＋extract——抓不到/抽不出的**不算候选**。"""
    out: List[Dict] = []
    for hit in hits:
        url = plaintext_url(hit["id"])
        source = {"url": url, "title": hit["title"][:80], "author": hit["author"][:60],
                  "license": "PublicDomain", "domain": domain, "mode": "http"}
        try:
            record = fetch.fetch_source(source, timeout, rate)
            text, _reason = extract_text.extract_record(record)
        except Exception as exc:  # noqa: BLE001 - 探针要给出原因，不是崩掉
            print("  FAIL %-58s %s" % (hit["title"][:56], f"{type(exc).__name__}"))
            time.sleep(rate)
            continue
        if text:
            out.append({**hit, "url": url, "domain": domain, "chars": len(text)})
            print("  OK %7d chars %s" % (len(text), hit["title"][:56]))
        time.sleep(rate)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.find_sources")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--terms", nargs="+", required=True)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--out", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    hits = search(args.terms, args.limit)
    print("目录命中 %d 本；逐本验证：" % len(hits))
    verified = verify(hits, args.domain)
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(verified, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    print("可抓 %d / %d" % (len(verified), len(hits)))
    return 0 if verified else 1


if __name__ == "__main__":  # pragma: no cover - 开发侧探针
    raise SystemExit(main())
