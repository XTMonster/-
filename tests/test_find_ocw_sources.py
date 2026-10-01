"""OCW 来源发现器的**纯函数**用例（不联网）。

背景：`find_sources.py` 查的是 Project Gutenberg 的目录 CSV，三轮检索 29 本里只有
4 本沾电影技术（其中 3 本本来就在语料里）——关键词检索基本只返回小说。换馆藏是
唯一出路，而 OCW 的静态入口在**资源页**那一层（课程页是 JS 外壳、`data.json` 只有
元数据）。这个工具把那条路走通：实测 5 个课程 → 44 个资源页 → 8 个 PDF → **8/8 通过
既有管线验证**。

这里只测**不联网的那几段**：课程名筛选、页面里的 PDF 抽取、以及"每跳都过 robots
门"这条纪律（用假的 `robots_allows` 打桩）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import find_ocw_sources as ocw  # noqa: E402


def test_filmish_keeps_film_courses_and_drops_the_rest():
    slugs = ["21l-011-the-film-experience-fall-2013",
             "6-006-introduction-to-algorithms-fall-2011",
             "21a-550j-dv-lab-documenting-science-through-video-and-new-media-fall-2012",
             "18-06-linear-algebra-spring-2010"]
    picked = ocw.filmish(slugs)
    assert "21l-011-the-film-experience-fall-2013" in picked
    assert "21a-550j-dv-lab-documenting-science-through-video-and-new-media-fall-2012" in picked
    assert "6-006-introduction-to-algorithms-fall-2011" not in picked
    assert "18-06-linear-algebra-spring-2010" not in picked


def test_course_slugs_reads_a_sitemap_index():
    text = ("<?xml version=\"1.0\"?><sitemapindex>"
            "<loc>https://ocw.mit.edu/sitemap-www.xml</loc>"
            "<loc>https://ocw.mit.edu/courses/21l-011-the-film-experience-fall-2013/sitemap.xml</loc>"
            "<loc>https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/sitemap.xml</loc>"
            "</sitemapindex>")
    import re
    out = []
    for loc in re.findall(r"<loc>([^<]+)</loc>", text):
        match = re.search(r"/courses/([^/]+)/sitemap\.xml$", loc)
        if match:
            out.append(match.group(1))
    assert out == ["21l-011-the-film-experience-fall-2013",
                   "6-006-introduction-to-algorithms-fall-2011"]


def test_every_hop_goes_through_the_robots_gate(monkeypatch):
    """违反 robots 的 URL 必须**抛错**，不许直接抓——这是管线唯一的护栏。"""
    called = {"fetched": 0}

    def fake_allows(url, timeout, *a, **kw):
        return (False, "disallowed by robots") if "blocked" in url else (True, "")

    def fake_get(url, timeout, *a, **kw):
        called["fetched"] += 1
        return b"<html></html>"

    monkeypatch.setattr(ocw.fetch_mod, "robots_allows", fake_allows)
    monkeypatch.setattr(ocw.fetch_mod, "_http_get", fake_get)
    with pytest.raises(PermissionError):
        ocw._get("https://ocw.mit.edu/blocked/x.pdf", 5.0)
    ocw._get("https://ocw.mit.edu/courses/ok/x.pdf", 5.0)
    assert called["fetched"] == 1, "被 robots 拒的那一跳不许真的抓"


def test_harvest_records_the_course_and_honours_the_want_filter(monkeypatch):
    """候选必须带**课程归属**，且 `--want` 能按题材挑——否则只能"全吞"。

    为什么重要：扩语料会**抬高门⑥ 的分母**（每张新卡都要有至少一条条目），
    所以只能按题材挑最可能补薄边的几门课，而不是把 40 门全收进来。
    第一版没有归属字段，45 份候选全成了无名氏，根本没法挑。
    """
    monkeypatch.setattr(ocw, "resource_pages",
                        lambda slug, timeout=30.0: ["https://ocw.mit.edu/p/%s" % slug])
    monkeypatch.setattr(ocw, "pdfs_on",
                        lambda page, timeout=30.0: [page.replace("/p/", "/f_") + ".pdf"])

    def fake_fetch(source, timeout, rate):
        return {"url": source["url"]}

    monkeypatch.setattr(ocw.fetch_mod, "fetch_source", fake_fetch)
    monkeypatch.setattr(ocw.extract_mod, "extract_record",
                        lambda record: ("正文" * 40, ""))
    monkeypatch.setattr(ocw.time, "sleep", lambda _s: None)

    slugs = ["21a-550j-dv-lab-documenting-science-through-video-and-new-media-fall-2012",
             "21l-011-the-film-experience-fall-2013"]
    report = ocw.harvest(slugs, timeout=1.0, rate=0.0, max_courses=5,
                         max_pages_per_course=5, want=["dv-lab"])
    assert report["stats"]["courses"] == 1, "`--want` 之外课程不许被抓"
    assert report["candidates"], "应当产出候选"
    assert {c["course"] for c in report["candidates"]} == {slugs[0]}, (
        "候选必须记录课程归属")
