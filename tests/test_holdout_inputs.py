"""门③/门⑥ 的**输入本身**必须与当前语料一致。

这一条来自 2026-10-01 的实际事故：`fixtures/knowledge_holdout.cards.json` 是上一代
产物（2067 个 id），而运行时 `block_director.knowledge.corpus.CARDS` 是 2113 ——
97 个 fixture id 已不存在、143 张卡不在文件里。门⑥ 因此把**输入错误**报成了
"1334 张卡零条目"。

为什么 pytest 之前没抓到：门⑥ 把 `--cards` 当**输入**，没有任何断言说这个输入等于
运行时的卡片集合；而 `run_tests.ps1` 里那一步只跑门、不做输入对账。所以这条不变量
必须自己站起来 —— 它是"门⑥ 的数字到底有没有意义"的前置条件。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CARDS_JSON = ROOT / "fixtures" / "knowledge_holdout.cards.json"


def test_cards_fixture_matches_the_runtime_corpus():
    """门⑥ 的输入必须**逐字**等于运行时语料。"""
    if not CARDS_JSON.is_file():
        pytest.skip("卡片全集未入库")
    from block_director.knowledge.corpus import CARDS

    shipped = json.loads(CARDS_JSON.read_text(encoding="utf-8"))
    expected = sorted(str(card.id) for card in CARDS)
    missing = sorted(set(expected) - set(shipped))
    stale = sorted(set(shipped) - set(expected))
    assert not missing and not stale, (
        "门⑥ 的输入与运行时语料脱节："
        f"文件里缺 {len(missing)} 张（例 {missing[:5]}）、"
        f"多出 {len(stale)} 个已不存在的 id（例 {stale[:5]}）。"
        "修法：`python tools/holdout_merge.py --cards-only --out "
        "fixtures/knowledge_holdout.jsonl`")


def test_quarantined_annotation_shards_are_not_merge_inputs():
    """被隔离的半成品分片不许出现在任何"默认合并输入"里。

    实测事故：自由标注 lane（`work/glm_v14/`）的 6 个 shard 里有一半停过、一半重启过，
    `partial*.jsonl` 与 `keep*.jsonl` 还互相重叠；把它们并进 held-out 会把
    "上一代语料 × 半成品"混成一份看起来合法的 oracle。
    """
    quarantine = ROOT / "work" / "glm_v14" / "QUARANTINE"
    if not quarantine.is_dir():
        pytest.skip("没有隔离目录（已清理）")
    assert (quarantine / "README.md").is_file(), "隔离目录必须有说明书，否则下一个人会当它是有效分片"
    text = (quarantine / "README.md").read_text(encoding="utf-8")
    assert "不得" in text and "oracle" in text, "README 必须写明这些分片不得用于门①–⑩"
    # 隔离目录之外不该再有 v14 的分片（有就说明有人在往回搬）
    leftovers = sorted(p.name for p in quarantine.parent.glob("partial*.jsonl"))
    assert leftovers == [], f"隔离目录外的 v14 分片会被误并：{leftovers}"
