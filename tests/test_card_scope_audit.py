"""`tools/kb_fetch/card_scope_audit.py` 的**对照组**：抽错了就不是对照 (2026-10-02)。

§4.1b 的来源覆盖门写的是「每张**入库卡（L1/L2）**至少派生 1 条」。判"哪些卡不是
入库卡"不能由实现自己说了算，所以审查工具带一个**对照组**：从"**已经有条目**的卡"
里抽一批一起判——它们已经派生出边，如果审查员把它们也判成范围外，说明"范围外"
这个桶真的会开火，不是橡皮章。

原实现把这条写成了 `set(cards) - set(wanted) & set(covered)`。Python 里 `&` 比 `-`
优先，于是它算的是 `cards - (wanted ∩ covered)`——"去除被点名且已覆盖的"，结果
**几乎全部卡片**都进了对照池，其中一大批根本没有条目。那样抽出来的样本不再证明任何事：
它没法说明"已覆盖的卡被判范围外"这种情况发生过几次。

这里钉住三件事：只取已覆盖的、不取被点名的、同一 seed 可复现。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch.card_scope_audit import control_pool  # noqa: E402


def test_control_pool_only_takes_cards_that_already_have_entries() -> None:
    """回归：这正是优先级写错时挂掉的那条。"""
    pool = control_pool(cards=["c1", "c2", "c3"], wanted=[], covered=["c1"],
                        count=5, seed=1)
    assert pool == ["c1"]


def test_control_pool_never_repeats_a_named_card() -> None:
    pool = control_pool(cards=["c1", "c2", "c3"], wanted=["c2"], covered=["c1", "c2"],
                        count=5, seed=1)
    assert pool == ["c1"]


def test_control_pool_is_seed_reproducible_and_capped() -> None:
    cards = [f"c{i}" for i in range(50)]
    first = control_pool(cards=cards, wanted=[], covered=cards, count=10, seed=7)
    again = control_pool(cards=cards, wanted=[], covered=cards, count=10, seed=7)
    other = control_pool(cards=cards, wanted=[], covered=cards, count=10, seed=8)
    assert len(first) == 10
    assert first == again
    assert first != other or set(first) != set(other)
    assert len(set(first)) == 10


def test_control_pool_is_empty_when_asked_for_none() -> None:
    assert control_pool(cards=["c1"], wanted=[], covered=["c1"], count=0, seed=1) == []


def test_the_shipped_scope_artifact_keeps_its_control_group_honest() -> None:
    """入库的 `knowledge/card_scope.json` 里，对照组真的含"已覆盖却判范围外"的卡。

    没有这一条，"判据不是橡皮章"就只是一句自述；有了它，那个桶开过火是有据可查的。
    """
    import json

    scope = json.loads((ROOT / "knowledge" / "card_scope.json").read_text(encoding="utf-8"))
    decisions = scope["decisions"]
    covered = {json.loads(line).get("from_card") for line in
               (ROOT / "fixtures" / "knowledge_holdout.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()}

    out_of_scope = scope["out_of_scope"]
    assert set(out_of_scope) == {k for k, v in decisions.items() if not v["in_scope"]}
    assert out_of_scope, "一条范围外都没有：这个桶要么没用，要么判据坏了"

    covered_but_out = [k for k in out_of_scope if k in covered]
    assert covered_but_out, (
        "被剔掉的卡全都是没有条目的——那对照组就没法证明判据会开火")
