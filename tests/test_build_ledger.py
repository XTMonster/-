"""`knowledge/hypergraph.manifest.json` 的账目必须自洽。

来自 2026-10-01 的一次真实回归：清洗跑（`--replace-cards`）成功后，我把一条
`{"status": "replace_cards", "cards": <int>}` 塞进了 `batch_log`。构建门 Q0 会数
"多少批 done / 共多少批"，于是 44/45 → 判"构建失败"，一次**成功的清洗**被报成
错误（`tests/test_knowledge_quality.py` 当场转红）。两条不变量钉在这里：

1. `batch_log` 只放**抽取批次**；清洗/补抽的账记在 `merge.refresh`；
2. `chunk_counts()` 遇到非抽取条目要**跳过**而不是崩（那一条的 `cards` 是整数，
   按批次逻辑去迭代会 `TypeError`）。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_hypergraph as bh  # noqa: E402

MANIFEST = ROOT / "knowledge" / "hypergraph.manifest.json"


def test_chunk_counts_skips_non_extraction_entries():
    """非抽取条目（如清洗账）不许参与 chunk 计数，更不许让它崩。"""
    cards = [
        {"id": "c1", "source_span": {"chunk_id": "chunk#1"}},
        {"id": "c2", "source_span": {"chunk_id": "chunk#2"}},
    ]
    log = [
        {"status": "done", "cards": ["c1", "c2"]},
        {"status": "replace_cards", "cards": 329, "atoms_dropped": 518},
    ]
    processed, total = bh.chunk_counts(cards, log)
    assert (processed, total) == (2, 2)
    assert bh.chunk_counts(cards, [log[1]]) == (0, 2), "清洗账本身不代表任何 chunk 被抽过"


def test_shipped_manifest_batch_ledger_only_counts_extractions():
    """入库 manifest 的 `batches` 里只允许抽取批次的 status。

    允许的状态就是抽取器会写的那三种；出现别的（例如把清洗账塞进来）会让
    Q0 的 `processed == total` 失真。
    """
    if not MANIFEST.is_file():
        pytest.skip("索引未入库")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    batches = manifest.get("batches") or []
    assert batches, "manifest 必须有批次账"
    bad = sorted({str(b.get("status")) for b in batches
                  if str(b.get("status")) not in ("done", "error", "skipped")})
    assert bad == [], f"batches 里混进了非抽取条目：{bad}；清洗账应写进 merge.refresh"


def test_refresh_bookkeeping_is_present_when_the_index_was_refreshed():
    """做过清洗的索引必须留下 `merge.refresh` 与混合 prompt 版本的记录。"""
    if not MANIFEST.is_file():
        pytest.skip("索引未入库")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    versions = manifest.get("atom_prompt_versions") or {}
    if len(versions) <= 1:
        pytest.skip("这份索引只由单一 prompt 版本产出，无需 refresh 记录")
    merge = manifest.get("merge") or {}
    assert merge.get("refresh"), (
        "索引里混着多个 prompt 版本的原子边，却没有 `merge.refresh` 记账 —— "
        "manifest 会声称整库都是当前口径（§4.1b 硬规则 2 禁止自报对不上的汇总）")
    assert merge.get("refresh_prompt_version") == manifest.get("prompt_version")
