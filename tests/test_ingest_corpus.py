"""P3 的入口：把"来源清单"变成"影子语料目录"（`work/corpus_v4/`）。

为什么要这一层（计划 v4 的 P3 ＋ CORPUS_V4.md 的实测结论）：

* 语料的问题不是"缺现代来源"——实测 `sources.yaml` 里已经有 **267 条非 Gutenberg
  的现代来源**，是那 54 本 1900–1920 旧书在 L1/L2 的**卡片产能上占了 83.6%**。
  所以 P3 的动作是"**按年门槛与预算重配**"，而门槛要能被机器判 ⇒ 每条来源必须带 `year`。
* 抓取必须**复用** `tools/kb_fetch/fetch.py` 的门（scheme ＋ robots ＋ 限速 ＋ sha256 幂等）。
  本层只做两件它没做的事：**按 cutoff 选料**、**把选出来的与排除的分账落盘**。
  另写一套抓取＝把"两道门"变成"两份实现"，那是本项目反复踩过的漂移坑。

本文件钉四件事（都用注入的假抓取器，**不碰网络**）：

1. `year >= cutoff` 的来源进 `MANIFEST.json`，每条带 `url/title/author/license/year`；
2. `year` 缺失或低于门槛的进 `excluded.jsonl`（带具名 reason），**不进 manifest**；
3. 抓取被门拒收的来源**如实进 rejects**，不静默丢弃；
4. 所有产物只落在**给定的 out_dir**，不污染现役的 `work/`（影子路径纪律）。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import fetch as kb_fetch  # noqa: E402
from tools.kb_fetch import ingest_corpus as ingest  # noqa: E402

CUTOFF = 1980


def _source(url: str, *, year=None, domain="cinematography", title="t", author="a",
            license_="CC-BY") -> dict:
    row = {"url": url, "title": title, "author": author, "license": license_,
           "domain": domain, "mode": "http"}
    if year is not None:
        row["year"] = year
    return row


def _fake_fetch(record: dict):
    """替身：把一个来源变成 fetch.py 同形的解析记录（不联网）。"""
    def _fetch(source, timeout=30.0, rate_seconds=1.0):
        if source["url"].endswith("/denied"):
            raise kb_fetch.FetchError("robots_denied:disallow")
        return {
            "source_ref": {"url": source["url"], "title": source["title"],
                           "author": source["author"], "license": source["license"],
                           "year": source.get("year"),
                           "sha256": "0" * 64, "retrieved_at": "2026-10-05T00:00:00Z"},
            "domain": source.get("domain"),
            "text": record.get("text", "正文" * 50),
        }
    return _fetch


def _fake_extract(record: dict):
    """替身：把抓来的原文当 HTML 抽正文（与 `extract_text.extract_record` 同形）。"""
    def _extract(fetched):
        raw = str(fetched.get("text") or "")
        if "<html" in raw.lower() or "<!doctype" in raw.lower():
            return "抽出来的正文", ""
        if not raw.strip():
            return "", "empty_text"
        return raw, ""
    return _extract


def _write_sources(tmp_path: pathlib.Path, rows) -> pathlib.Path:
    import yaml
    path = tmp_path / "sources.v4.yaml"
    path.write_text(yaml.safe_dump({"sources": rows}, allow_unicode=True), encoding="utf-8")
    return path


def test_modern_sources_land_in_the_manifest_with_the_four_fields(tmp_path):
    rows = [_source("https://example.org/a", year=2019),
            _source("https://example.org/b", year=1995)]
    out = tmp_path / "corpus_v4"
    report = ingest.ingest(_write_sources(tmp_path, rows), out, cutoff=CUTOFF,
                           fetch_one=_fake_fetch({}), extract_one=_fake_extract({}))
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert len(manifest["entries"]) == 2
    for entry in manifest["entries"]:
        for field in ("url", "title", "author", "license", "year"):
            assert entry.get(field) is not None, field
    assert report["kept"] == 2 and report["excluded"] == 0


def test_sources_below_the_cutoff_or_without_a_year_are_excluded(tmp_path):
    rows = [_source("https://example.org/old", year=1912),
            _source("https://example.org/noyear"),
            _source("https://example.org/new", year=2021)]
    out = tmp_path / "corpus_v4"
    report = ingest.ingest(_write_sources(tmp_path, rows), out, cutoff=CUTOFF,
                           fetch_one=_fake_fetch({}), extract_one=_fake_extract({}))
    excluded = [json.loads(line) for line in
                (out / "excluded.jsonl").read_text(encoding="utf-8").splitlines() if line]
    reasons = sorted(item["reason"] for item in excluded)
    assert reasons == ["below_cutoff", "missing_year"]
    assert report["kept"] == 1 and report["excluded"] == 2
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    urls = {entry["url"] for entry in manifest["entries"]}
    assert urls == {"https://example.org/new"}


def test_a_source_rejected_by_the_fetch_gate_is_recorded_not_swallowed(tmp_path):
    rows = [_source("https://example.org/denied", year=2020),
            _source("https://example.org/ok", year=2020)]
    out = tmp_path / "corpus_v4"
    report = ingest.ingest(_write_sources(tmp_path, rows), out, cutoff=CUTOFF,
                           fetch_one=_fake_fetch({}), extract_one=_fake_extract({}))
    assert report["rejects"] == 1
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["rejects"][0]["reason"].startswith("robots_denied")
    assert len(manifest["entries"]) == 1


def test_everything_lands_under_the_given_out_dir(tmp_path):
    """影子路径纪律：不许往现役的 `work/` 里写。"""
    rows = [_source("https://example.org/a", year=2019)]
    out = tmp_path / "corpus_v4"
    ingest.ingest(_write_sources(tmp_path, rows), out, cutoff=CUTOFF,
                  fetch_one=_fake_fetch({}), extract_one=_fake_extract({}))
    for name in ("MANIFEST.json", "excluded.jsonl", "fetched.jsonl"):
        assert (out / name).is_file(), name
    assert not (ingest.common.WORK / "corpus_v4_probe_should_not_exist").exists()


def test_the_manifest_digest_is_recomputable_from_its_own_entries(tmp_path):
    """语料摘要必须能从 manifest 自己复算——它是缓存失效的钥匙（P5 要用）。"""
    rows = [_source("https://example.org/a", year=2019),
            _source("https://example.org/b", year=2020)]
    out = tmp_path / "corpus_v4"
    ingest.ingest(_write_sources(tmp_path, rows), out, cutoff=CUTOFF,
                  fetch_one=_fake_fetch({}), extract_one=_fake_extract({}))
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["corpus_digest"] == ingest.corpus_digest(manifest["entries"])
    #: 反面控制：改一条 ⇒ 摘要必须变。
    tampered = [dict(entry) for entry in manifest["entries"]]
    tampered[0]["url"] = "https://example.org/CHANGED"
    assert ingest.corpus_digest(tampered) != manifest["corpus_digest"]


def test_a_negative_cutoff_is_refused(tmp_path):
    with pytest.raises(ValueError):
        ingest.ingest(_write_sources(tmp_path, []), tmp_path / "o", cutoff=0,
                      fetch_one=_fake_fetch({}), extract_one=_fake_extract({}))


def test_html_boilerplate_is_extracted_before_it_reaches_the_corpus(tmp_path):
    """管线第 2 步不许被跳过。

    实测（2026-10-05 的 P4 试点）暴露的缺陷：`work/corpus_v4/fetched.jsonl` 里存的
    是**原始 HTML**（`<!DOCTYPE html>…`），于是抽取器看到的是样板代码、一条草稿都
    产不出来。管线本来是 `fetch → extract_text → …`，P3 的入库漏了中间那步。
    """
    rows = [_source("https://example.org/a", year=2019)]
    out = tmp_path / "corpus_v4"

    def html_fetch(source, timeout=30.0, rate_seconds=1.0):
        return {"source_ref": {"url": source["url"], "title": "t", "author": "a",
                              "license": "CC-BY", "year": source.get("year"),
                              "sha256": "0" * 64, "retrieved_at": "x"},
                "domain": source.get("domain"),
                "text": "<!DOCTYPE html><html><head><title>x</title></head>"
                        "<body><p>真正的正文</p></body></html>"}

    ingest.ingest(_write_sources(tmp_path, rows), out, cutoff=CUTOFF,
                  fetch_one=html_fetch, extract_one=_fake_extract({}))
    fetched = [json.loads(line) for line in
               (out / "fetched.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert fetched and fetched[0]["text"] == "抽出来的正文"
    assert "<html" not in fetched[0]["text"]


def test_an_extraction_failure_is_a_named_reject_not_silent_html(tmp_path):
    rows = [_source("https://example.org/empty", year=2019)]
    out = tmp_path / "corpus_v4"

    def empty_fetch(source, timeout=30.0, rate_seconds=1.0):
        return {"source_ref": {"url": source["url"], "title": "t", "author": "a",
                              "license": "CC-BY", "year": source.get("year"),
                              "sha256": "0" * 64, "retrieved_at": "x"},
                "domain": source.get("domain"), "text": "   "}

    report = ingest.ingest(_write_sources(tmp_path, rows), out, cutoff=CUTOFF,
                           fetch_one=empty_fetch, extract_one=_fake_extract({}))
    assert report["kept"] == 0 and report["rejects"] == 1
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["rejects"][0]["reason"].startswith("extract_failed:")
