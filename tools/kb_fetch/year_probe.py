"""从**已抓正文**里定一个来源的年份（P3 的影子来源清单需要 `year`）。

背景（实测）：`knowledge/sources.yaml` 的 **321 条来源里一条都没有 `year` 字段**，
而 D1 的裁决是 `year >= 1980` 才进语料——所以"没有年份"就等于"没有语料"。
`work/raw/` 里已经有 1201 份过门后的正文，本工具**只读**它们，不重新抓。

三条纪律：

* **不许猜**：找不到日期就返回 `(None, "not_found")`，绝不用"看起来挺新"顶上；
* **留依据**：每条返回 `(year, basis)`，`basis` 进影子清单的 `year_basis` 字段，
  读的人能一眼看出这个年份是从哪来的；
* **优先级固定**：机器可读的 meta > 正文版权年 > URL 里的课程学期。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import common  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.kb_fetch import common  # type: ignore

#: 合理年份区间：1895（公认的电影元年）到 2100。与 `ingest_corpus._year_of` 同源。
MIN_YEAR = 1895
MAX_YEAR = 2100

#: 机器可读的发布时间（三种最常见的写法）。取**第一个**命中的。
_META_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("meta:published_time",
     re.compile(r"""<meta[^>]+(?:property|name)=["'](?:article:published_time|og:published_time|datePublished|pubdate)["'][^>]*content=["']([^"']{4,40})["']""", re.I)),
    ("meta:published_time",
     re.compile(r"""<meta[^>]+content=["']([^"']{4,40})["'][^>]*(?:property|name)=["'](?:article:published_time|og:published_time|datePublished|pubdate)["']""", re.I)),
    ("meta:dc_date",
     re.compile(r"""<meta[^>]+(?:name|property)=["'](?:dc\.date|dcterms\.date|article:modified_time)["'][^>]*content=["']([^"']{4,40})["']""", re.I)),
    #: 学术站（OJS 一类）用 `citation_publication_date` 报发表日期，值是 `2018/11/02`
    #: 或 `2018-11-02`。实测：Animation Studies 全站走这一条。
    ("meta:citation_publication_date",
     re.compile(r"""<meta[^>]+name=["']citation_publication_date["'][^>]*content=["']([^"']{4,40})["']""", re.I)),
)

#: 正文里的版权年。`©`／`(c)`／`Copyright` 三种写法都收，但**只认 4 位年**。
_TEXT_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    #: 现代站点常把日期**只**放进 JSON-LD（`<script type="application/ld+json">`）。
    #: 实测：不认它的时候，StudioBinder / BFI 那一类的命中率会掉一大截。
    ("jsonld:datePublished",
     re.compile(r'"(?:datePublished|dateCreated|dateModified)"\s*:\s*"([^"]{4,40})"', re.I)),
    ("html:time_datetime",
     re.compile(r"""<time[^>]+datetime=["']([^"']{4,40})["']""", re.I)),
    ("text:copyright", re.compile(r"(?:©|\(c\)|copyright)\s*(?:19|20)\d{2}\D{0,40}?((?:19|20)\d{2})", re.I)),
    ("text:copyright", re.compile(r"(?:©|\(c\)|copyright)\s*((?:19|20)\d{2})", re.I)),
)

#: 最后一条兜底：**看起来像 HTML** 的文档里，第一个完整 ISO 日期当作发表日期。
#: 为什么限定 HTML：纯文本文档里出现的 ISO 日期多半是**引文**里的年代（实测反例：
#: 一篇讨论 1930／1928 年影片的文章，正文里全是旧年份）。HTML 页面的头部日期
#: 才是站点的发布元数据。这条**只在前面的规则都没命中时**才用，且如实记 basis。
_ISO_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})-\d{2}-\d{2}(?!\d)")

#: URL 里的课程学期：MIT OCW 的 `…-fall-2013`／`…-spring-2003`。
_SLUG_PATTERN = re.compile(r"-(?:spring|summer|fall|winter|january|iap)-((?:19|20)\d{2})\b",
                           re.I)


def _plausible(year: int) -> bool:
    return MIN_YEAR <= year <= MAX_YEAR


def _first_year(text: str) -> Optional[int]:
    """从一段文本里取第一个合理年份（`2019-05-01`／`2019` 都行）。"""
    for match in re.finditer(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)", text):
        year = int(match.group(1))
        if _plausible(year):
            return year
    return None


def extract_year(text: str, *, url: str = "") -> Tuple[Optional[int], str]:
    """返回 ``(year, basis)``；找不到就是 ``(None, "not_found")``。纯函数。"""
    head = text[:200_000]  # meta 一定在头部；正文尾巴里的"© 2001"多是引文
    for basis, pattern in _META_PATTERNS:
        match = pattern.search(head)
        if match:
            year = _first_year(match.group(1))
            if year is not None:
                return year, basis
    for basis, pattern in _TEXT_PATTERNS:
        match = pattern.search(head)
        if match:
            year = _first_year(match.group(1))
            if year is not None:
                return year, basis
    #: 兜底：只在"看起来像 HTML"的文档上用第一个 ISO 日期（见 `_ISO_DATE` 的注释）。
    if "<html" in head[:4000].lower() or "<meta" in head[:4000].lower():
        iso = _ISO_DATE.search(head)
        if iso:
            year = int(iso.group(1))
            if _plausible(year):
                return year, "html:first_iso_date"
    slug = _SLUG_PATTERN.search(str(url))
    if slug:
        year = int(slug.group(1))
        if _plausible(year):
            return year, "url:course_slug"
    return None, "not_found"


def raw_path_for(digest: str, raw_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(raw_dir) / ("%s.txt" % digest)


def probe_sources(sources: Sequence[Dict], *, resolved: Dict[str, Dict],
                  raw_dir: pathlib.Path, limit: int = 0) -> List[Dict]:
    """给每条来源补 ``year`` 与 ``year_basis``。

    `resolved` 是 `work/sources.resolved.json`（键＝`url::sha256`）；正文从
    `raw_dir/<sha256>.txt` 读。**找不到正文不是错误**——那条的 `year_basis`
    记 `raw_text_missing`，年份留空，交给 `ingest_corpus` 按"缺年份"排除。
    """
    by_url: Dict[str, str] = {}
    for _key, record in (resolved or {}).items():
        ref = record.get("source_ref") or {}
        url = str(ref.get("url") or "")
        digest = str(ref.get("sha256") or "")
        if url and digest:
            by_url[url] = digest

    out: List[Dict] = []
    for index, source in enumerate(sources):
        if limit and index >= limit:
            break
        url = str(source.get("url") or "")
        digest = by_url.get(url, "")
        text = ""
        if digest:
            path = raw_path_for(digest, raw_dir)
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
        year, basis = extract_year(text, url=url)
        if year is None and not text:
            basis = "raw_text_missing"
        entry = dict(source)
        if year is not None:
            entry["year"] = year
        entry["year_basis"] = basis
        out.append(entry)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.year_probe")
    parser.add_argument("--sources", default=str(common.SOURCES_YAML))
    parser.add_argument("--resolved", default=str(common.WORK / "sources.resolved.json"))
    parser.add_argument("--raw-dir", default=str(common.RAW_DIR))
    parser.add_argument("--out", required=True, help="写补好年份的清单（yaml）")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    import yaml

    sources = common.load_sources(pathlib.Path(args.sources))
    resolved_path = pathlib.Path(args.resolved)
    resolved = json.loads(resolved_path.read_text(encoding="utf-8")) if resolved_path.is_file() else {}
    probed = probe_sources(sources, resolved=resolved,
                           raw_dir=pathlib.Path(args.raw_dir), limit=args.limit)
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump({"sources": probed}, allow_unicode=True,
                                       sort_keys=False), encoding="utf-8")
    counts: Dict[str, int] = {}
    for entry in probed:
        counts[entry["year_basis"]] = counts.get(entry["year_basis"], 0) + 1
    print(json.dumps({"overall": "pass", "total": len(probed),
                      "with_year": sum(1 for entry in probed if entry.get("year")),
                      "bases": counts, "out": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
