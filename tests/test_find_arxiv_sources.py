"""Adversarial tests for the arXiv finder: licence gate first, parsing second.

The finder exists because `anime` has exactly one source (a 1920 book) while the
user asked for modern production theory.  The only thing that makes an arXiv
paper usable is its *licence*, and a card is a derivative work - so a paper under
`by-nc-nd` or arXiv's perpetual licence must be dropped mechanically, not by
whoever happens to read the candidate list.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common  # noqa: E402
from tools.kb_fetch import find_arxiv_sources as fa  # noqa: E402
from tools.kb_fetch import fetch  # noqa: E402

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <title>  Shot   language
      for animation production </title>
    <author><name>A. Director</name></author>
    <published>2024-01-01T00:00:00Z</published>
    <link href="http://arxiv.org/abs/2401.00001v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v2" rel="related"/>
    <link href="http://creativecommons.org/licenses/by/4.0/" rel="license"/>
    <summary>We study the
      strong coupling.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>No derivatives allowed</title>
    <author><name>B. Author</name></author>
    <published>2024-01-02T00:00:00Z</published>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00002v1" rel="related"/>
    <link href="http://creativecommons.org/licenses/by-nc-nd/4.0/" rel="license"/>
    <summary>Text.</summary>
  </entry>
</feed>
"""


def test_licence_map_keeps_the_whitelist_and_drops_no_derivatives():
    assert fa.license_class("http://creativecommons.org/licenses/by/4.0/") == "CC-BY"
    assert fa.license_class("https://creativecommons.org/licenses/by-sa/4.0") == "CC-BY-SA"
    assert fa.license_class("http://creativecommons.org/licenses/by-nc-sa/4.0/") == "CC-BY-NC-SA"
    assert fa.license_class("http://creativecommons.org/publicdomain/zero/1.0/") == "CC0"
    assert fa.license_class("http://creativecommons.org/licenses/by-nc-nd/4.0/") == ""
    assert fa.license_class("http://arxiv.org/licenses/nonexclusive-distrib/1.0/") == ""
    assert fa.license_class("") == ""
    # 每一个映射出来的名字都必须是管线自己的白名单成员——两处不许分叉。
    for fragment, name in fa.LICENSE_MAP.items():
        assert common.license_allowed(name), (fragment, name)


def test_parse_feed_reads_the_pdf_link_and_the_licence_link():
    entries = fa.parse_feed(FEED)
    assert len(entries) == 2
    first = entries[0]
    assert first["id"].endswith("2401.00001v2")
    assert first["title"] == "Shot language for animation production"   # 空白已折叠
    assert first["pdf_url"] == "http://arxiv.org/pdf/2401.00001v2"
    assert first["license_url"].endswith("by/4.0/")
    assert first["author"] == "A. Director"
    assert "\n" not in first["abstract"]


def test_accepted_drops_the_no_derivatives_entry():
    clean = fa.accepted(fa.parse_feed(FEED))
    assert [item["title"] for item in clean] == ["Shot language for animation production"]
    assert clean[0]["license"] == "CC-BY"


def test_an_entry_without_a_licence_is_not_accepted():
    """The API feed states no licence at all (measured); unknown is not permitted."""
    entries = fa.parse_feed(FEED)
    bare = [{**entries[0], "license_url": ""}]
    assert fa.accepted(bare) == []
    assert fa.accepted([{**bare[0], "license": "CC-BY-NC-SA"}])[0]["license"] == "CC-BY-NC-SA"


def test_license_is_read_off_the_abstract_page():
    html = ('<div class="abs-license">'
            '<a href="http://creativecommons.org/licenses/by-nc-sa/4.0/" '
            'title="Rights to this article" class="has_license">')
    assert fa.license_from_html(html) == "CC-BY-NC-SA"
    assert fa.license_from_html('<div class="abs-license"><a href="http://arxiv.org/'
                                'licenses/nonexclusive-distrib/1.0/">x</a>') == ""
    assert fa.license_from_html("<html>no licence block</html>") == ""


def test_relevance_uses_whole_words_because_arxiv_matches_substrings():
    """`all:"anime"` really did return LLM papers about `animals`."""
    animal_paper = {"title": "Signatures of semantic search in language models",
                    "abstract": "The animals were clustered by semantic production."}
    film_paper = {"title": "Shot language for animation production",
                  "abstract": "We model camera movement and storyboard rhythm."}
    assert not fa.relevant(animal_paper)
    assert fa.relevant(film_paper)
    # 标题里一个主题词都没有 → 不算（正文提到两次也不算）
    assert not fa.relevant({"title": "A generic framework", "abstract":
                            "camera and shot and editing"})


def test_query_url_encodes_the_term_and_asks_for_the_newest_first():
    url = fa.query_url('all:"anime" AND all:"production"', 7)
    assert "max_results=7" in url
    assert "sortOrder=descending" in url
    assert "%22anime%22" in url and " " not in url.split("search_query=")[1].split("&")[0]


def test_as_source_keeps_the_licence_and_points_at_the_pdf():
    item = fa.accepted(fa.parse_feed(FEED))[0]
    source = fa.as_source(item, "anime")
    assert source["url"] == "http://arxiv.org/pdf/2401.00001v2"
    assert source["license"] == "CC-BY"
    assert source["domain"] == "anime" and source["mode"] == "http"
    assert not common.source_ref_problems({
        "url": source["url"], "title": source["title"], "author": source["author"],
        "license": source["license"], "retrieved_at": source["retrieved_at"],
        "sha256": "0" * 64})


def test_licence_check_uses_the_pipelines_own_whitelist():
    good = {"source_ref": {"url": "u", "title": "t", "author": "a", "license": "CC-BY",
                           "retrieved_at": "2024-01-01", "sha256": "0" * 64}}
    assert fa._licence_ok(good) == (True, "")
    bad = {"source_ref": dict(good["source_ref"], license="CC-BY-NC-ND")}
    ok, why = fa._licence_ok(bad)
    assert not ok and "license_not_whitelisted" in why
    missing = {"source_ref": {"url": "u"}}
    ok, why = fa._licence_ok(missing)
    assert not ok and why.startswith("source_ref_missing:")


def test_default_terms_stay_ascii_and_unique():
    """术语串会经 PowerShell 传参；中文或重复项都踩过坑。"""
    assert len(set(fa.DEFAULT_TERMS)) == len(fa.DEFAULT_TERMS)
    for term in fa.DEFAULT_TERMS:
        assert term.isascii() and term.strip() == term


# --- the robots discipline ---------------------------------------------------------

def test_the_api_exception_is_one_host_and_one_path():
    """例外必须窄到"这个 host 的这条路径"，否则它就成了绕过 robots 的万能钥匙。"""
    assert fa.api_exempt(fa.query_url("all:test", 1))
    assert fa.api_exempt("https://export.arxiv.org/api/query?start=0")
    assert not fa.api_exempt("https://export.arxiv.org/list/cs.GR/2401")
    assert not fa.api_exempt("https://export.arxiv.org/api/anything-else")
    assert not fa.api_exempt("https://arxiv.org/abs/2401.00001")
    assert not fa.api_exempt("https://evil.example/export.arxiv.org/api/query")
    assert not fa.api_exempt("ftp://export.arxiv.org/api/query")


def test_a_non_exempt_url_is_stopped_by_the_robots_gate_before_any_request(monkeypatch):
    """实测：`export.arxiv.org/robots.txt` 是 `Disallow: /`、`arxiv.org` 禁 `/search`。

    所以发现步骤要么是那条具名例外，要么被门拦下 —— 不许静默直连。
    """
    def deny(url, timeout, cache_dir=None):
        return False, "robots_disallow:/"

    def boom(*args, **kwargs):                      # pragma: no cover - 不该被调用
        raise AssertionError("网络请求发生在 robots 门之前")

    monkeypatch.setattr(fetch, "robots_allows", deny)
    monkeypatch.setattr(fa.urllib.request, "urlopen", boom)
    with pytest.raises(fetch.FetchError, match="robots_denied"):
        fa._get("https://arxiv.org/search/?query=anime", 5.0)
    fa._gate(fa.query_url("all:test", 1), 5.0)      # 具名例外：过门但不发请求


def test_the_candidate_file_records_the_exception_it_relied_on():
    record = fa.discovery_record()
    assert record["host"] == fa.API_EXCEPTION_HOST
    assert record["path_prefix"] == fa.API_EXCEPTION_PATH
    assert record["robots_verdict"] == "Disallow: /"
    assert "3 s" in str(record["exception"]) or "3 s" in str(record["exception"])
    assert record["api_interval_seconds"] == fa.API_INTERVAL == 3.0


def test_a_throttled_fetch_is_retried_but_a_persistent_failure_is_still_a_failure(monkeypatch):
    """批内瞬时连接失败要重试；但重试用尽后必须把失败原样抛出去（不许吞掉）。"""
    calls = {"n": 0}

    def flaky(source, timeout, interval):
        calls["n"] += 1
        if calls["n"] < 3:
            raise fetch.FetchError("URLError: WinError 10060")
        return {"text": "ok", "source_ref": {}}

    sleeper: list = []
    monkeypatch.setattr(fetch, "fetch_source", flaky)
    record = fa._fetch_with_retry({"url": "u"}, 1.0, 0.0, sleeper=sleeper.append)
    assert record["text"] == "ok" and calls["n"] == 3
    assert sleeper == [fa.FETCH_BACKOFF, fa.FETCH_BACKOFF * 2]   # 退避是递增的

    calls["n"] = 0

    def always(source, timeout, interval):
        calls["n"] += 1
        raise fetch.FetchError("URLError: WinError 10060")

    monkeypatch.setattr(fetch, "fetch_source", always)
    with pytest.raises(fetch.FetchError):
        fa._fetch_with_retry({"url": "u"}, 1.0, 0.0, sleeper=lambda _s: None)
    assert calls["n"] == fa.FETCH_ATTEMPTS


def test_discovery_retries_a_burst_timeout_and_then_gives_up(monkeypatch):
    """搜 API 也会撞同一波抖动；重试用尽后照样把异常抛出去。"""
    monkeypatch.setattr(fa, "_gate", lambda url, timeout: None)
    attempts = {"n": 0}

    class Fake:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"<feed/>"

    def flaky(request, timeout):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TimeoutError("read timed out")
        return Fake()

    monkeypatch.setattr(fa.urllib.request, "urlopen", flaky)
    assert fa._get("https://export.arxiv.org/api/query?x=1", 1.0,
                   sleeper=lambda _s: None) == "<feed/>"
    assert attempts["n"] == 3

    attempts["n"] = 0

    def dead(request, timeout):
        attempts["n"] += 1
        raise TimeoutError("read timed out")

    monkeypatch.setattr(fa.urllib.request, "urlopen", dead)
    with pytest.raises(TimeoutError):
        fa._get("https://export.arxiv.org/api/query?x=1", 1.0, sleeper=lambda _s: None)
    assert attempts["n"] == 3
