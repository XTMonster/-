"""等距抽样：让一次有界的试跑**跨来源**，而不是只拿到排序最前的那个域。

为什么要它（2026-10-05）：`--limit-records N` 取的是**前缀**，而语料按
`(domain, url)` 排序——前 30 份**全部**来自 Animation Studies（anime 域）。
拿它当"全量影子构建"的代表，会系统性地高估/低估某些域。`--sample-every N`
隔 N 取 1，域分布更接近整体，而且**可复算**（同输入同样本）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import extract_segmented as ex  # noqa: E402


def test_the_stride_is_deterministic_and_spreads_across_records():
    records = [{"source_ref": {"url": "u%d" % index, "sha256": "%064d" % index},
                "text": "x" * 200} for index in range(20)]
    picked = ex.sample_records(records, every=5)
    assert [record["source_ref"]["url"] for record in picked] == ["u0", "u5", "u10", "u15"]
    assert ex.sample_records(records, every=5) == picked, "同输入必须同样本"


def test_every_one_or_zero_means_no_sampling():
    records = [{"source_ref": {"url": "u%d" % index}, "text": "x"} for index in range(3)]
    assert ex.sample_records(records, every=0) == records
    assert ex.sample_records(records, every=1) == records
