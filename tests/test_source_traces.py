"""**反向**门：`sources.yaml` 的每条来源都必须在产物里留下痕迹。

为什么需要它：现有的对拍只有"产物 → 清单"一个方向（`tests/test_cases_corpus.py`
查"案例的出处必须在清单里"、`tests/test_kb_pipeline.py` 查"卡片出处六字段齐全"）。
那个方向对**清单里的多余项完全无感**——实测事故（2026-10-02 17:5x）：一条 lane 往
`knowledge/sources.yaml` 追加了 50 条来源，而 `knowledge/cards_generated/`、
`knowledge/cases.jsonl`、索引与 oracle 里**一条都没有它们**；正向门全绿，
因为产物里出现的出处确实都在清单里。

判据是确定性的：把 `sources.yaml` 的 URL 先归一化（大小写、末尾斜杠、query/fragment），
再与"卡片 ∪ 案例"里出现过的 `source_ref.url` 求差集。差集**只允许**是下面那份
**具名例外表**——每条都写清为什么它拿不到产物。

两向自证：`test_the_checker_catches_a_half_applied_source_edit` 用一份合成清单
证明"清单里有、产物里没有"会被报出来（否则这条门可能只是恒真）。
"""

from __future__ import annotations

import json
import pathlib
import sys
from urllib.parse import urlsplit, urlunsplit

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import read_cases  # noqa: E402

from tools.kb_fetch import common  # noqa: E402

#: 允许"在清单里但没有产物"的来源，逐条具名。
#:
#: **当前为空**——2026-10-02 修 `segments_of` 的自适应句窗（3→2→1 句）之后，此前
#: 唯一那条例外（`skwigly.co.uk/childrens-tv-show-animation-pipeline-cinema-4d/`，
#: 当时"chunk 落选、无卡无案例"）也产出了案例，于是它**不再是例外**。这条表的
#: 防腐断言（下面 `stale` 那一行）当场要求删掉它——这正是那张表该有的行为：
#: **例外是暂时的，必须随修法一起消失**。
NAMED_EXCEPTIONS: dict = {}


def normalise(url: str) -> str:
    """URL 归一化：大小写主机、去 query/fragment、末尾斜杠只留一个。"""
    parsed = urlsplit(str(url).strip())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path.rstrip("/") or "/", "", ""))


def untraced_sources(sources, traced) -> list:
    """清单里有、产物里没有的 URL（**纯函数**，两向自证靠它）。"""
    have = {normalise(url) for url in traced}
    return sorted({normalise(source["url"]) for source in sources
                   if normalise(source["url"]) not in have})


def _traced_urls() -> set:
    out = set()
    for path in sorted((ROOT / "knowledge" / "cards_generated").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                url = (json.loads(line).get("source_ref") or {}).get("url")
                if url:
                    out.add(url)
    for case in read_cases(ROOT / "knowledge"):     # 分片布局，读者按索引目录认
        url = (case.source_ref or {}).get("url")
        if url:
            out.add(url)
    return out


def test_every_source_in_the_manifest_leaves_a_trace():
    """入库清单里每条来源都要在卡片或案例里出现过——例外必须**具名**。"""
    sources = common.load_sources(ROOT / "knowledge" / "sources.yaml")
    assert sources, "清单为空：这条门就什么都没测"
    missing = untraced_sources(sources, _traced_urls())
    named = {normalise(url) for url in NAMED_EXCEPTIONS}
    unexpected = sorted(set(missing) - named)
    assert not unexpected, (
        "这些来源在 `sources.yaml` 里，却没有任何卡片或案例出自它们——"
        "典型的半截语料改动（加了清单没重建产物）：\n  "
        + "\n  ".join(unexpected)
        + "\n修法：跑完整圈 fetch → chunk → annotate → build_hypergraph → "
          "build_cases → 重标 oracle；若这条来源确实不该有产物，把它写进 "
          "NAMED_EXCEPTIONS 并写清原因。")
    #: 例外表本身也不能腐烂：具名的那几条必须**真的**还在清单里。
    stale = sorted(named - set(missing))
    assert not stale, f"例外表里这些 URL 已经不再是例外了，删掉它们：{stale}"


def test_the_checker_catches_a_half_applied_source_edit():
    """反向自证：清单里有、产物里没有 ⇒ 必须被报出来。"""
    sources = [{"url": "https://example.invalid/a/", "domain": "anime"},
               {"url": "https://example.invalid/b/", "domain": "anime"}]
    traced = ["https://example.invalid/a"]
    assert untraced_sources(sources, traced) == [normalise("https://example.invalid/b/")]
    assert untraced_sources([], traced) == []
    #: 归一化：同一条来源写法不同（斜杠、query、大小写）不算缺口。
    assert untraced_sources(
        [{"url": "https://Example.INVALID/a/?x=1"}], traced) == []
