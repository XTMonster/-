"""探测"现代教材/论文"能否进管线（开发侧探针，不写任何入库产物）。

它用的是**管线自己的** `tools.kb_fetch.fetch.fetch_source`，也就是真实入库的
同一道门（scheme 白名单 → robots → 限速 → 抓取）。结论与逐条原因记录在
`docs/knowledge/MODERN_SOURCES.md`。

    python tools/probe_modern_sources.py
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.kb_fetch import fetch  # noqa: E402

#: (url, domain) —— 只列真正在考虑的现代来源，不做广撒网。
CANDIDATES: Sequence[Tuple[str, str]] = (
    ("https://ocw.mit.edu/courses/21l-011-the-film-experience-fall-2013/pages/lecture-notes/",
     "cinematography"),
    ("https://en.wikipedia.org/api/rest_v1/page/html/Cinematography", "cinematography"),
    ("https://en.wikipedia.org/api/rest_v1/page/html/Continuity_editing", "editing"),
    ("https://docs.blender.org/manual/en/latest/render/cameras.html", "cinematography"),
    ("https://arxiv.org/abs/2104.02680", "editing"),
)


def probe(candidates: Sequence[Tuple[str, str]] = CANDIDATES,
          timeout: float = 25.0, rate: float = 0.2) -> List[dict]:
    out: List[dict] = []
    for url, domain in candidates:
        source = {"url": url, "title": url.rstrip("/").rsplit("/", 1)[-1] or "index",
                  "author": "probe", "license": "PersonalStudy",
                  "domain": domain, "mode": "http"}
        try:
            record = fetch.fetch_source(source, timeout, rate)
            out.append({"url": url, "ok": True, "chars": int(record["chars"]),
                        "sha256": record["source_ref"]["sha256"]})
        except Exception as exc:  # noqa: BLE001 - 探针要给出**原因**，不是崩掉
            out.append({"url": url, "ok": False,
                        "reason": f"{type(exc).__name__}: {exc}"})
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe_modern_sources")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--rate", type=float, default=0.2)
    args = parser.parse_args(list(argv) if argv is not None else None)
    failed = 0
    for row in probe(timeout=args.timeout, rate=args.rate):
        if row["ok"]:
            print(f"OK   {row['chars']:7d} chars  {row['url']}")
        else:
            failed += 1
            print(f"FAIL {row['reason'][:100]}  {row['url']}")
    return 0 if failed < len(CANDIDATES) else 1


if __name__ == "__main__":  # pragma: no cover - 开发侧探针
    raise SystemExit(main())
