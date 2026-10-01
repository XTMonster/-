"""从 MIT OpenCourseWare 找**可抓的讲义 PDF**（P14-1 扩来源）。

为什么要单独一个工具（而不是继续用 `find_sources.py`）：那个工具查的是
Project Gutenberg 的目录 CSV，实测三轮检索 29 本里只有 4 本沾电影技术，
其中 3 本本来就在语料里 —— 关键词检索基本只返回小说。换馆藏是唯一出路。

OCW 的静态入口（实测，2026-10-01）：

- `robots.txt`：`Allow: /` ＋ `Sitemap: https://ocw.mit.edu/sitemap.xml`；
- `sitemap.xml`：**2588 个子 sitemap**，每个课程一个；
- `/courses/<slug>/sitemap.xml`：约 11 个**页面** URL（资源页），不含 `.pdf`；
- `/courses/<slug>/data.json`：只有元数据，**没有资源清单**。

所以 PDF 在**资源页**那一层（与语料里已有的那两份同形：
`/courses/<slug>/<hash>_MIT21L_011F13_2006_Notes.pdf`）。本工具走四步：
取课程清单 → 关键词筛影视相关 → 取资源页 → 抓页面抽 `.pdf` →
**逐个走既有管线验证**（`fetch.py` 的 robots 门 ＋ `extract_text`），
通过的才写进候选文件，人工再决定要不要进 `sources.yaml`。

纪律与 `find_sources.py` 一致：只走 http/https、每一跳都过 robots、同域限速。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
from typing import Dict, List, Sequence

try:
    from . import fetch as fetch_mod
    from . import extract_text as extract_mod
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import fetch as fetch_mod  # type: ignore
    from tools.kb_fetch import extract_text as extract_mod  # type: ignore

SITEMAP = "https://ocw.mit.edu/sitemap.xml"
COURSE_SITEMAP = "https://ocw.mit.edu/courses/%s/sitemap.xml"

#: 影视/影像制作相关的课程名关键词。宁可窄一点：命中一批跟电影无关的课，
#: 后面每个资源页都要抓一遍，白烧时间。
KEYWORDS = ("film", "cinema", "photography", "moving image", "documentary",
            "video", "animation", "storyboard", "media arts", "screenplay")


def _get(url: str, timeout: float) -> str:
    """过 robots 门再抓，解码成文本（编不出来就 replace）。"""
    allowed, reason = fetch_mod.robots_allows(url, timeout)
    if not allowed:
        raise PermissionError(reason)
    return fetch_mod._http_get(url, timeout).decode("utf-8", errors="replace")


def course_slugs(timeout: float = 30.0) -> List[str]:
    """从 `sitemap.xml` 取全部课程 slug（子 sitemap 的 URL 里就有）。"""
    text = _get(SITEMAP, timeout)
    out: List[str] = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", text):
        match = re.search(r"/courses/([^/]+)/sitemap\.xml$", loc)
        if match:
            out.append(match.group(1))
    return sorted(set(out))


def filmish(slugs: Sequence[str]) -> List[str]:
    picked = [s for s in slugs if any(k in s.lower() for k in KEYWORDS)]
    return sorted(set(picked))


def resource_pages(slug: str, timeout: float = 30.0) -> List[str]:
    text = _get(COURSE_SITEMAP % slug, timeout)
    return sorted({loc for loc in re.findall(r"<loc>([^<]+)</loc>", text)
                   if "/courses/" in loc})


def pdfs_on(page: str, timeout: float = 30.0) -> List[str]:
    try:
        html = _get(page, timeout)
    except Exception:  # noqa: BLE001 - 单个资源页失败不该打断整轮
        return []
    found = set()
    for href in re.findall(r'href="([^"]+)"', html):
        if href.lower().endswith(".pdf"):
            found.add(href if href.startswith("http") else "https://ocw.mit.edu" + href)
    return sorted(found)


def harvest(slugs: Sequence[str], *, timeout: float = 30.0, rate: float = 1.0,
            max_courses: int = 5, max_pages_per_course: int = 12,
            want: Sequence[str] = ()) -> Dict:
    """对若干课程走完"资源页 → PDF → 管线验证"。返回候选与统计。"""
    candidates: List[Dict] = []
    stats = {"courses": 0, "pages": 0, "pdfs": 0, "verified": 0}
    picked = [s for s in slugs if not want or any(w in s for w in want)]
    for slug in picked[:max_courses]:
        stats["courses"] += 1
        for page in resource_pages(slug, timeout)[:max_pages_per_course]:
            stats["pages"] += 1
            time.sleep(rate)
            for pdf in pdfs_on(page, timeout):
                stats["pdfs"] += 1
                hit = {"url": pdf, "title": pdf.rsplit("/", 1)[-1][:80],
                       "author": "MIT OpenCourseWare", "license": "CC-BY-NC-SA",
                       "domain": "cinematography", "mode": "http"}
                # 与 Gutenberg 通道**同一道**验证（`fetch_source` 的 robots 门 ＋
                # `extract_text.extract_record`），但**不能复用 `find_sources.verify`**：
                # 它按 Gutenberg 的 `id` 拼 `plaintext_url()`，喂任意 URL 会 `KeyError: 'id'`
                # （实测第一版就是这么崩的）。抓不到 / 抽不出文本的**不算候选**。
                try:
                    record = fetch_mod.fetch_source(hit, timeout, rate)
                    text, _reason = extract_mod.extract_record(record)
                except Exception as exc:  # noqa: BLE001 - 单个 PDF 失败不该打断整轮
                    print("  FAIL %-48s %s" % (hit["title"][:46], type(exc).__name__))
                    time.sleep(rate)
                    continue
                if text:
                    stats["verified"] += 1
                    # **记录课程归属**：否则分不清哪份 PDF 来自哪门课，
                    # 也就没法"按题材收"（实测第一版就是这样，45 份候选全成了无名氏）。
                    candidates.append({**hit, "course": slug, "chars": len(text)})
                    print("  OK %7d chars %s" % (len(text), hit["title"][:48]))
                time.sleep(rate)
    return {"stats": stats, "candidates": candidates}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.find_ocw_sources")
    parser.add_argument("--max-courses", type=int, default=5)
    parser.add_argument("--max-pages-per-course", type=int, default=12)
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--out", default="work/ocw_candidates.json")
    parser.add_argument("--list-only", action="store_true",
                        help="只列筛出来的课程名，不抓资源页")
    parser.add_argument("--want", nargs="*", default=[],
                        help="**只收课程名里含这些子串的课**（例：`--want editing sound`）。"
                             "用来按题材挑，而不是把 40 门课全吞 —— 扩语料会抬高门⑥ 的分母。")
    args = parser.parse_args(list(argv) if argv is not None else None)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    slugs = course_slugs(args.timeout)
    picked = filmish(slugs)
    print(json.dumps({"courses_total": len(slugs), "filmish": len(picked),
                      "sample": picked[:10]}, ensure_ascii=False))
    if args.list_only:
        return 0
    report = harvest(picked, timeout=args.timeout, rate=args.rate,
                     max_courses=args.max_courses,
                     max_pages_per_course=args.max_pages_per_course,
                     want=args.want)
    pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps(report["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
