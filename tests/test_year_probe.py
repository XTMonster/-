"""从**已抓正文**里定年份（P3 的影子来源清单需要 `year`）。

为什么必须定年份：`ADJUDICATIONS_v4.md` 的 D1 裁决是 `year >= cutoff(1980)` 才进语料，
而 `knowledge/sources.yaml` 里 **321 条一条都没有 `year` 字段**（实测）。缺年份的来源
会被 `ingest_corpus.py` 一律排除，所以"没有年份"就等于"没有语料"。

为什么是"从已抓正文抽"而不是"重新抓一遍"：`work/raw/` 里已经有 **1201 份**已过门的
正文（357 MB），重新抓一遍既慢又多一次与站点打交道的机会。抽取器是**纯函数**，
所以它可离线测、可复算，而且每条都留下 `year_basis`（依据是什么），
不是"我猜的"。

优先级（高到低，先命中先用）：

1. `<meta property="article:published_time">` 一类**机器可读**的发布时间；
2. 正文里的版权年 `© 2019` / `Copyright 2019`；
3. URL 里的课程学期（MIT OCW 的 `…-fall-2012`）；
4. 都没有 ⇒ `(None, "not_found")`——**不许猜**（猜出来的年份会让换代门槛失效）。

年份合理区间与 `ingest_corpus._year_of` 同源（1895–2100）：1895 是电影元年，
早于它只可能是把 `2001` 写成 `201` 之类的笔误。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import year_probe  # noqa: E402


def test_meta_published_time_wins():
    html = ('<html><head><meta property="article:published_time" '
            'content="2019-05-01T00:00:00+00:00"></head><body>© 2017</body></html>')
    year, basis = year_probe.extract_year(html, url="https://example.org/a")
    assert year == 2019
    assert basis == "meta:published_time"


def test_copyright_year_is_used_when_there_is_no_meta():
    text = "Some essay about staging.\nCopyright 2017 by the author.\nMore prose."
    year, basis = year_probe.extract_year(text, url="https://example.org/b")
    assert year == 2017
    assert basis == "text:copyright"


def test_course_slug_is_the_last_resort_from_the_url():
    """MIT OCW 的课程 slug 末尾就是学期（`…-fall-2012`）。"""
    year, basis = year_probe.extract_year(
        "no date anywhere in this text",
        url="https://ocw.mit.edu/courses/21l-011-the-film-experience-fall-2013/index.htm")
    assert year == 2013
    assert basis == "url:course_slug"


def test_json_ld_date_published_is_used():
    """现代站点常把日期只放在 JSON-LD 里（`<script type="application/ld+json">`）。"""
    html = ('<html><body><script type="application/ld+json">'
            '{"@type":"Article","datePublished":"2021-03-04T09:00:00+00:00",'
            '"headline":"Staging"}</script></body></html>')
    year, basis = year_probe.extract_year(html, url="https://example.org/e")
    assert year == 2021
    assert basis == "jsonld:datePublished"


def test_time_element_datetime_is_used():
    html = ('<article><p class="byline">By A. Author</p>'
            '<time datetime="2016-11-02">2 November 2016</time></article>')
    year, basis = year_probe.extract_year(html, url="https://example.org/f")
    assert year == 2016
    assert basis == "html:time_datetime"


def test_citation_publication_date_meta_is_used():
    """学术站（OJS 一类）用 `citation_publication_date` 报发表日期。"""
    html = ('<html><head><meta name="citation_publication_date" '
            'content="2018/11/02"></head><body>text</body></html>')
    year, basis = year_probe.extract_year(html, url="https://journal.example.org/article/id/1/")
    assert year == 2018
    assert basis == "meta:citation_publication_date"


def test_first_iso_date_in_an_html_document_is_the_last_resort():
    """前几条都没命中时，HTML 文档里的**第一个 ISO 日期**当作发表日期。

    实测依据：`journal.animationstudies.org` 的每篇文章页带 5 个 ISO 日期，
    第一个就是出版年（2008／2018／2019…），而它的 meta 写法前面几条规则都不认。
    这条放在版权年**之后**、只对"看起来像 HTML"的文本生效，且如实记 basis。
    """
    html = ('<html><body><div class="published">2018-11-02</div>'
            '<p>An essay citing 1930 and 1928.</p></body></html>')
    year, basis = year_probe.extract_year(html, url="https://example.org/g")
    assert (year, basis) == (2018, "html:first_iso_date")

    #: 纯文本（没有 HTML 迹象）**不许**走这条——否则正文里引用的年代会被当成发表日期。
    year, basis = year_probe.extract_year("An essay citing 1930 and 1928.",
                                          url="https://example.org/h")
    assert (year, basis) == (None, "not_found")


def test_a_document_without_any_date_is_not_guessed():
    year, basis = year_probe.extract_year("just prose, no dates at all",
                                          url="https://example.org/c")
    assert year is None
    assert basis == "not_found"


@pytest.mark.parametrize("bad", ["© 1888", "Copyright 9999", "© 120"])
def test_implausible_years_are_rejected(bad):
    year, basis = year_probe.extract_year("Published. " + bad + ".",
                                          url="https://example.org/d")
    assert year is None
    assert basis == "not_found"
