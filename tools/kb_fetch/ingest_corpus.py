"""P3 的入口：把**来源清单**变成一份**影子语料目录**（计划 v4 的 `work/corpus_v4/`）。

它在管线里的位置：`sources.v4.yaml` → 本工具 → `work/corpus_v4/`（MANIFEST ＋
excluded ＋ fetched）→ P4 的抽取。

## 为什么只做两件事

抓取本身**完全复用** `tools/kb_fetch/fetch.py` 的 `fetch_source`：scheme 白名单、
robots 门（取不到 `robots.txt` 就拒收）、同域限速、sha256 幂等——一道都不重写。
本工具只补它没有的两件：

1. **按年门槛选料**。`CORPUS_V4.md` 的实测结论是"语料库不缺现代来源
   （321 条里有 267 条非 Gutenberg），缺的是 L1/L2 的**产能配比**"，
   所以换代的第一刀就是"`year >= cutoff` 才进"——而这要求每条来源**带年份**，
   没有年份的**一律排除**（不许当成"大概很新"放行）。
2. **选出来的与排除的分账**。`MANIFEST.json` 记收下的（每条带
   `url/title/author/license/year`）＋ `excluded.jsonl` 记没要的（带具名 reason），
   两者相加＝输入条数，账目闭合。

## 影子路径纪律

所有产物只落在**调用方给的 out_dir**。现役的 `work/fetched.jsonl` 是**已发货索引**的
输入，本工具**不碰**它——重建期间老产物必须逐字节不动（计划 §3.1 的"保留 3 项"）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):  # 直跑时把仓库根挂上（与 build_hypergraph 同一约定）
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import common  # type: ignore
    from . import fetch as kb_fetch  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.kb_fetch import common  # type: ignore
    from tools.kb_fetch import fetch as kb_fetch  # type: ignore

#: 年份门槛（`ADJUDICATIONS_v4.md` 的 D1 裁决：cutoff = 1980）。
DEFAULT_CUTOFF = 1980

MANIFEST_NAME = "MANIFEST.json"
EXCLUDED_NAME = "excluded.jsonl"
FETCHED_NAME = "fetched.jsonl"

#: 排除原因（闭集；进 `excluded.jsonl` 的 `reason` 字段）。
REASON_MISSING_YEAR = "missing_year"
REASON_BELOW_CUTOFF = "below_cutoff"
REASON_BAD_YEAR = "bad_year"


def _year_of(source: Dict) -> Optional[int]:
    """来源的年份；缺、空、非整数、不在合理区间 ⇒ ``None``。"""
    raw = source.get("year")
    if raw is None or raw == "":
        return None
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return None
    #: 1895 是公认的电影元年；早于它的"年份"只可能是笔误（例如把 2001 写成 201）。
    if year < 1895 or year > 2100:
        return None
    return year


def select_sources(sources: Sequence[Dict], *, cutoff: int
                   ) -> Tuple[List[Dict], List[Dict]]:
    """按年门槛把来源分成"收下"与"排除"两堆（纯函数，可离线测）。"""
    if cutoff <= 0:
        raise ValueError("cutoff 必须是正的年份，收到 %r" % (cutoff,))
    kept: List[Dict] = []
    excluded: List[Dict] = []
    for source in sources:
        url = str(source.get("url") or "")
        year = _year_of(source)
        if source.get("year") not in (None, "") and year is None:
            excluded.append({"url": url, "year": source.get("year"),
                             "reason": REASON_BAD_YEAR})
            continue
        if year is None:
            excluded.append({"url": url, "reason": REASON_MISSING_YEAR})
            continue
        if year < cutoff:
            excluded.append({"url": url, "year": year, "reason": REASON_BELOW_CUTOFF})
            continue
        kept.append(source)
    return kept, excluded


def corpus_digest(entries: Sequence[Dict]) -> str:
    """语料摘要：对**全部字段的规范序列化**取 sha256（排序后）。

    它是 P5 缓存键里的"语料分量"——换一条来源、改一个年份、甚至只改标题，
    摘要都会变，从而让旧缓存失效。同一批 entries 必须**可复算**。
    """
    payload = json.dumps([{key: (entry.get(key)) for key in sorted(entry)}
                          for entry in sorted(entries, key=lambda item: str(item.get("url")))],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry_from_record(source: Dict, record: Dict) -> Dict:
    ref = dict(record.get("source_ref") or {})
    return {
        "url": ref.get("url") or source.get("url"),
        "title": ref.get("title") or source.get("title"),
        "author": ref.get("author") or source.get("author"),
        "license": ref.get("license") or source.get("license"),
        "year": source.get("year"),
        "domain": source.get("domain"),
        "sha256": ref.get("sha256"),
        "retrieved_at": ref.get("retrieved_at"),
    }


def ingest(sources_path: pathlib.Path, out_dir: pathlib.Path, *,
           cutoff: int = DEFAULT_CUTOFF, fetch_one=None,
           timeout: float = 30.0, rate_seconds: float = 1.0) -> Dict:
    """跑一次入库：选料 → 抓取（走 `fetch.py` 的门）→ 落三份产物。

    `fetch_one` 只在测试里注入（替身）；生产路径用 `fetch.fetch_source`。
    """
    if cutoff <= 0:
        raise ValueError("cutoff 必须是正的年份，收到 %r" % (cutoff,))
    fetcher = fetch_one or kb_fetch.fetch_source
    sources = common.load_sources(pathlib.Path(sources_path))
    kept, excluded = select_sources(sources, cutoff=cutoff)

    entries: List[Dict] = []
    rejects: List[Dict] = []
    fetched: List[Dict] = []
    for source in kept:
        try:
            record = fetcher(source, timeout, rate_seconds)
        except kb_fetch.FetchError as exc:
            #: 门自己的拒收**已经是具名原因**（`robots_denied:…`／`scheme_not_allowed:…`），
            #: 原样记，不再套一层类型名——套了会让"按 reason 归类"要多做一次剥壳。
            rejects.append({"url": source.get("url"), "domain": source.get("domain"),
                            "reason": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 - 网络错误也要留痕
            rejects.append({"url": source.get("url"), "domain": source.get("domain"),
                            "reason": "%s: %s" % (type(exc).__name__, exc)})
            continue
        entries.append(_entry_from_record(source, record))
        fetched.append(record)

    entries.sort(key=lambda item: str(item.get("url")))
    manifest = {
        "generated_by": "tools/kb_fetch/ingest_corpus.py",
        "sources_file": str(sources_path),
        "cutoff": int(cutoff),
        "counts": {"input": len(sources), "kept": len(entries),
                   "excluded": len(excluded), "rejects": len(rejects)},
        "entries": entries,
        "rejects": rejects,
        #: 缓存失效的钥匙（P5 的语料分量）。
        "corpus_digest": corpus_digest(entries),
    }
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    common.dump_json(out_dir / MANIFEST_NAME, manifest)
    common.write_jsonl(out_dir / EXCLUDED_NAME, excluded)
    common.write_jsonl(out_dir / FETCHED_NAME, fetched)
    #: 账目必须闭合：收下的 ＋ 排除的 ＋ 被拒的 ＝ 输入。
    assert (len(entries) + len(excluded) + len(rejects)) == len(sources), (
        "语料账目不闭合：%d + %d + %d != %d"
        % (len(entries), len(excluded), len(rejects), len(sources)))
    return {"kept": len(entries), "excluded": len(excluded), "rejects": len(rejects),
            "input": len(sources), "corpus_digest": manifest["corpus_digest"],
            "out_dir": str(out_dir)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.ingest_corpus")
    parser.add_argument("--sources", default=str(common.KNOWLEDGE / "sources.v4.yaml"),
                        help="来源清单（v4 用影子清单，默认 knowledge/sources.v4.yaml）")
    parser.add_argument("--out", required=True, help="影子语料目录，例如 work/corpus_v4")
    parser.add_argument("--cutoff", type=int, default=DEFAULT_CUTOFF)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--rate", type=float, default=1.0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        report = ingest(pathlib.Path(args.sources), pathlib.Path(args.out),
                        cutoff=args.cutoff, timeout=args.timeout,
                        rate_seconds=args.rate)
    except ValueError as exc:
        print(json.dumps({"overall": "not_measured", "error": str(exc)},
                         ensure_ascii=False))
        return 2
    print(json.dumps({"overall": "pass", **report}, ensure_ascii=False))
    return 0 if report["kept"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
