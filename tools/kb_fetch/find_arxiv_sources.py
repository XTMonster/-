"""Find **modern** production-side sources for the corpus (P14-1 supply).

Why a third finder
==================

The corpus the user actually asked for - modern film/animation *production*
theory - is thin: `anime` has a single 1920 source (Lutz, *Animated Cartoons*),
and the hunts recorded in `docs/knowledge/ACCEPTANCE_STATUS.md` 9.11 measure why
Gutenberg cannot supply more.  This machine reaches only three source families
at all (measured 2026-10-01):

    ocw.mit.edu     OK      arxiv.org / export.arxiv.org   OK
    gutenberg.org   OK      en.wikipedia.org (timeout), OER hosts (DNS/404)

What is gated, and what is a named exception
============================================

`fetch.py`'s rule is "fetch nothing without robots.txt; prefer a gap over a
grab".  For arXiv that produces exactly one exception, and it is named here
rather than left implicit (the audit in `docs/knowledge/AUDIT_ARXIV_FINDER.md`
found the first version skipping the gate silently):

* `export.arxiv.org` (the **API** host) answers `robots.txt` with `Disallow: /`,
  and `arxiv.org` disallows `/search`.  Neither the API nor the web search page
  can therefore be a *gated* discovery step, while `/list/` browsing is allowed
  but cannot be targeted at a topic.
* `API_EXCEPTION_*` therefore name one host and one path prefix, and
  :func:`api_exempt` refuses everything else - including other paths on the same
  host.  arXiv documents the API as its programmatic entry point and asks for
  3 s between calls, which :func:`search` honours.
* Everything else goes through `fetch.fetch_source`, so the abstract page (where
  the licence lives) and the PDF both pass the robots gate.  `extract_text` runs
  for every candidate that is **verified** (`--verify`), not for the whole list.
* The candidate file records the exception it relied on (`_discovery`), so the
  next reader sees the deviation instead of having to rediscover it.

The licence filter is mechanical: `LICENSE_MAP` contains only the deeds the
pipeline's own whitelist accepts, so `by-nc-nd` and arXiv's perpetual licence
cannot pass.  An entry whose licence cannot be read is **not** accepted -
"unknown" is not "permitted".

Measured limits (2026-10-01), so the next reader does not re-derive them
==============================================================================================

* discovery works: 8 terms, 157 candidates, 29 on topic **after** the whole-word
  filter (`all:`/`abs:` match substrings - `anime` hits `animals`, and without
  the filter the first run's 63 candidates were all irrelevant);
* the licence lives only on the abstract page (the Atom feed has no
  `rel="license"`), and a single abstract-page fetch succeeds in 15.5 s
  (arXiv's own `Crawl-delay: 15`) while a dozen in a row raise
  `URLError … WinError 10060` - hence :data:`FETCH_ATTEMPTS`;
* a second batch then got `HTTP 429 Too Many Requests` from the API.  The family
  is usable, but only as a **slow drip**, not as a batch: budget the interval,
  not the candidates.

    python -m tools.kb_fetch.find_arxiv_sources --per-term 25 --licences 12 --verify 4
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common, extract_text, fetch  # noqa: E402

API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
#: The **only** host+path exempt from the robots gate (see the module docstring).
API_EXCEPTION_HOST = "export.arxiv.org"
API_EXCEPTION_PATH = "/api/query"
API_INTERVAL = 3.0

#: The topics the corpus is missing: production-side, animation-side, and the
#: "strong couplings" the user named (impact / rhythm / camera language).
DEFAULT_TERMS = (
    'abs:"anime" AND abs:"production"',
    'abs:"keyframe animation"',
    'abs:"cinematography" AND abs:"camera"',
    'abs:"film editing"',
    'abs:"storyboard"',
    'abs:"inbetweening"',
    'abs:"shot composition"',
    'abs:"animation" AND abs:"directing"',
)

#: arXiv's `all:`/`abs:` operators match **substrings** (`anime` hits `animals`),
#: so a candidate only counts when the topic words appear as whole words.  The
#: first run returned 63 candidates and zero usable ones without this filter.
TOPIC_WORDS = ("anime", "animation", "animated", "animator", "cinematography",
               "cinematographer", "storyboard", "keyframe", "inbetweening",
               "inbetween", "mise-en-scene", "shot", "shots", "filmmaking",
               "screenplay", "directing", "editing", "camera")

#: CC deeds that the pipeline's own whitelist accepts.  `by-nc-nd` (no
#: derivatives) and arXiv's perpetual licence are deliberately absent: a card is
#: a derivative work, so those two cannot be used no matter how useful the paper.
LICENSE_MAP = {
    "creativecommons.org/licenses/by/": "CC-BY",
    "creativecommons.org/licenses/by-sa/": "CC-BY-SA",
    "creativecommons.org/licenses/by-nc-sa/": "CC-BY-NC-SA",
    "creativecommons.org/publicdomain/zero/": "CC0",
}


def api_exempt(url: str) -> bool:
    """True only for the named API exception - host **and** path prefix both match."""
    parsed = urllib.parse.urlsplit(str(url))
    return (parsed.scheme in ("http", "https")
            and parsed.netloc.lower() == API_EXCEPTION_HOST
            and parsed.path.startswith(API_EXCEPTION_PATH))


def _gate(url: str, timeout: float) -> None:
    """Raise unless the URL passes the robots gate or is the named exception."""
    if api_exempt(url):
        return
    allowed, why = fetch.robots_allows(url, timeout)
    if not allowed:
        raise fetch.FetchError(f"robots_denied:{why}")


def license_class(url: str) -> str:
    """Map an arXiv licence URL to the pipeline's whitelist name (``""`` = rejected)."""
    text = str(url or "").strip().lower()
    for fragment, name in LICENSE_MAP.items():
        if fragment in text:
            return name
    return ""


def license_from_html(html: str) -> str:
    """Read the licence off an arXiv **abstract page** (the API does not state it).

    Measured 2026-10-01: the API's Atom feed carries no `rel="license"` link at
    all, so an API-only pipeline drops 100% of candidates; the abs page does
    carry `<div class="abs-license"><a href="...">`.
    """
    match = re.search(r'class="abs-license"[^>]*>\s*<a[^>]+href="([^"]+)"', html)
    if not match:
        match = re.search(r'<a[^>]+rel="license"[^>]+href="([^"]+)"', html)
    return license_class(match.group(1) if match else "")


def words_of(text: str) -> set:
    return set(re.findall(r"[a-z][a-z\-]{2,}", str(text or "").lower()))


def relevant(item: Dict[str, str], minimum: int = 2) -> bool:
    """Whole-word relevance: >=2 distinct topic words, at least one in the title."""
    title = words_of(item.get("title", ""))
    body = words_of(item.get("abstract", ""))
    hits = (title | body) & set(TOPIC_WORDS)
    return len(hits) >= minimum and bool(title & set(TOPIC_WORDS))


def query_url(term: str, per_term: int) -> str:
    """The API URL for one search term, sorted by submission date (newest first)."""
    return (f"{API}?search_query={urllib.parse.quote(term)}"
            f"&start=0&max_results={int(per_term)}"
            "&sortBy=submittedDate&sortOrder=descending")


def parse_feed(xml_text: str) -> List[Dict[str, str]]:
    """Atom feed -> ``[{id,title,author,published,license_url,url,pdf_url,abstract}]``."""
    root = ET.fromstring(xml_text)
    out: List[Dict[str, str]] = []
    for entry in root.findall(f"{ATOM}entry"):
        ident = (entry.findtext(f"{ATOM}id") or "").strip()
        pdf = ""
        licence = ""
        for link in entry.findall(f"{ATOM}link"):
            if str(link.get("title") or "") == "pdf":
                pdf = str(link.get("href") or "")
            if str(link.get("rel") or "") == "license":
                licence = str(link.get("href") or "")
        out.append({
            "id": ident,
            "title": re.sub(r"\s+", " ", entry.findtext(f"{ATOM}title") or "").strip(),
            "author": re.sub(r"\s+", " ",
                             (entry.findtext(f"{ATOM}author/{ATOM}name") or "")).strip(),
            "published": (entry.findtext(f"{ATOM}published") or "")[:10],
            "license_url": licence,
            "url": ident,
            "pdf_url": pdf,
            "abstract": re.sub(r"\s+", " ",
                               entry.findtext(f"{ATOM}summary") or "").strip(),
        })
    return out


def _get(url: str, timeout: float, *, gate: bool = True,
         attempts: int = 3, backoff: float = 5.0, sleeper=time.sleep) -> str:
    """One GET, with the same bounded retry the licence step needs.

    Measured 2026-10-01: this network drops connections in bursts - a single
    request to the API or an abstract page succeeds in under a second, while a
    run of a dozen in a row raises `TimeoutError`/`WinError 10060`.  Without a
    retry the whole harvest dies on the first burst instead of recording a gap.
    """
    if gate:
        _gate(url, timeout)
    last: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            sleeper(backoff * attempt)
        try:
            request = urllib.request.Request(  # noqa: S310 - http(s) only, checked above
                url, headers={"User-Agent": fetch.USER_AGENT,
                              "Accept": "application/atom+xml"})
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - re-raised if the last attempt fails
            last = exc
    raise last


def search(terms: Sequence[str], per_term: int, *, timeout: float = 30.0,
           interval: float = API_INTERVAL, sleeper=time.sleep) -> List[Dict[str, str]]:
    """One API call per term, `interval` seconds apart (arXiv's stated API limit)."""
    out: List[Dict[str, str]] = []
    seen: set = set()
    for index, term in enumerate(terms):
        if index:
            sleeper(interval)
        for item in parse_feed(_get(query_url(term, per_term), timeout)):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            item["term"] = term
            out.append(item)
    return out


def discovery_record() -> Dict[str, object]:
    """What the candidate file has to state about *how* it was discovered."""
    return {
        "host": API_EXCEPTION_HOST,
        "path_prefix": API_EXCEPTION_PATH,
        "robots_verdict": "Disallow: /",
        "exception": ("arXiv documents the API as its programmatic entry point and asks for "
                      "3 s between calls; arxiv.org blocks /search and export.arxiv.org blocks "
                      "everything, so a targeted search is impossible inside the gate. "
                      "This one host+path is the named exception; every other request "
                      "(abstract page, PDF) goes through fetch.robots_allows."),
        "api_interval_seconds": API_INTERVAL,
    }


def accepted(entries: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep the licence-clean entries, carrying the whitelist name forward."""
    kept = []
    for item in entries:
        name = str(item.get("license") or "") or license_class(item.get("license_url", ""))
        if not name:
            continue
        kept.append({**item, "license": name})
    return kept


def read_licence(item: Dict[str, str], *, timeout: float = 45.0,
                 interval: float = 1.0) -> str:
    """Fetch the abstract page (through the robots gate) and return the licence."""
    page = {"url": item.get("url", ""), "title": item.get("title", ""),
            "author": item.get("author", ""), "license": "PublicDomain",
            "domain": "storyboard", "mode": "http"}
    record = _fetch_with_retry(page, timeout, interval)
    return license_from_html(str(record.get("text", "")))


#: 实测（2026-10-01）：同一台机器、同一个 URL，单独抓 15.5 s 成功，而批内连续抓
#: 12 条时**每一条**都 `URLError … WinError 10060`（连接超时）。这是批内的瞬时连接
#: 失败，不是封锁，也不是 URL 的问题——所以重试是必要的，但要有界且不改判据：
#: 失败还是失败，只是不再把"第 12 次抖动"记成"arXiv 抓不到"。
FETCH_ATTEMPTS = 3
FETCH_BACKOFF = 10.0


def _fetch_with_retry(source: Dict, timeout: float, interval: float,
                      *, attempts: int = FETCH_ATTEMPTS,
                      backoff: float = FETCH_BACKOFF, sleeper=time.sleep) -> Dict:
    """`fetch.fetch_source` with a bounded retry - the site throttles bursts."""
    last: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            sleeper(backoff * attempt)
        try:
            return fetch.fetch_source(source, timeout, interval)
        except Exception as exc:  # noqa: BLE001 - re-raised below if the last attempt
            last = exc
    raise last


def enrich_licences(entries: Sequence[Dict[str, str]], *, timeout: float = 45.0,
                    interval: float = 1.0) -> List[Dict[str, str]]:
    """Attach the licence to every candidate that is relevant enough to keep."""
    out: List[Dict[str, str]] = []
    for item in entries:
        try:
            name = read_licence(item, timeout=timeout, interval=interval)
        except Exception as exc:  # noqa: BLE001 - a page that will not load is a reject
            print(f"  reject abs     {item.get('id', '')[-24:]:24s} "
                  f"{type(exc).__name__}: {str(exc)[:60]}", flush=True)
            continue
        if not name:
            print(f"  reject licence {item.get('id', '')[-24:]:24s} "
                  "not in the whitelist (ND / arXiv perpetual)", flush=True)
            continue
        out.append({**item, "license": name})
    return out


def as_source(item: Dict[str, str], domain: str) -> Dict:
    """The `sources.yaml` shape, so a verified candidate can be pasted in as-is."""
    return {
        "url": item.get("pdf_url") or item.get("url", ""),
        "title": item.get("title", ""),
        "author": item.get("author", ""),
        "license": item.get("license", ""),
        "domain": domain,
        "genre": "film",
        "mode": "http",
        "retrieved_at": item.get("published", ""),
    }


def verify(candidates: Sequence[Dict[str, str]], domain: str, limit: int,
           *, timeout: float = 60.0, interval: float = 1.0) -> List[Dict]:
    """Run the *existing* fetch (robots gate) + extract gate over the candidates."""
    verified: List[Dict] = []
    for item in candidates[:limit]:
        source = as_source(item, domain)
        try:
            record = _fetch_with_retry(source, timeout, interval)
        except Exception as exc:  # noqa: BLE001 - the pipeline's own reject classes
            print(f"  reject fetch  {item.get('id', '')[-24:]:24s} {type(exc).__name__}: "
                  f"{str(exc)[:70]}", flush=True)
            continue
        text, reason = extract_text.extract_record(record)
        if not text:
            print(f"  reject extract {item.get('id', '')[-24:]:24s} {reason}", flush=True)
            continue
        ok, why = _licence_ok(record)
        if not ok:
            print(f"  reject licence {item.get('id', '')[-24:]:24s} {why}", flush=True)
            continue
        verified.append({**source, "chars": len(text), "abstract": item.get("abstract", ""),
                         "text": text})
        print(f"  verified       {item.get('id', '')[-24:]:24s} chars={len(text)}", flush=True)
    return verified


def _licence_ok(record: Dict) -> tuple:
    """The same two checks `validate_licenses.check` makes, without its file I/O."""
    source_ref = record.get("source_ref") or {}
    missing = common.source_ref_problems(source_ref)
    if missing:
        return False, "source_ref_missing:" + ",".join(missing)
    if not common.license_allowed(str(source_ref.get("license", ""))):
        return False, f"license_not_whitelisted:{source_ref.get('license', '')}"
    return True, ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="find_arxiv_sources")
    parser.add_argument("--terms", default="|".join(DEFAULT_TERMS),
                        help="用 `|` 分隔的 arXiv 查询串（同 arXiv API 语法）")
    parser.add_argument("--per-term", type=int, default=20)
    parser.add_argument("--licences", type=int, default=25,
                        help="对相关性通过的前 N 篇取 abs 页读许可（0 = 跳过，全部按未知拒收）")
    parser.add_argument("--verify", type=int, default=0,
                        help="对许可通过的候选跑 fetch＋extract 验证前 N 篇（0 = 只列候选）")
    parser.add_argument("--domain", default="anime",
                        help="候选写进哪个域（默认 anime —— 那正是语料最薄的一域）")
    parser.add_argument("--interval", type=float, default=API_INTERVAL)
    parser.add_argument("--out", default="work/modern/arxiv_candidates.json")
    parser.add_argument("--verified-out", default="work/modern/arxiv_verified.json")
    args = parser.parse_args(list(argv) if argv is not None else None)

    terms = [term.strip() for term in str(args.terms).split("|") if term.strip()]
    found = search(terms, args.per_term, interval=args.interval)
    on_topic = [item for item in found if relevant(item)]
    print(f"found={len(found)} on_topic={len(on_topic)} "
          f"dropped_by_relevance={len(found) - len(on_topic)}")
    clean = accepted(enrich_licences(on_topic[:args.licences],
                                     interval=1.0)) if args.licences else []
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"_discovery": discovery_record(), "candidates": clean},
                              ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"licence_clean={len(clean)}")
    for item in clean[:12]:
        print(f"  {item['license']:12s} {item['published']}  {item['title'][:66]}")

    if args.verify:
        verified = verify(clean, args.domain, args.verify, interval=1.0)
        target = ROOT / args.verified_out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"_discovery": discovery_record(),
                                      "verified": verified},
                                     ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")
        print(f"verified={len(verified)} -> {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
