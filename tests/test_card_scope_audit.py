"""`tools/kb_fetch/card_scope_audit.py`：门⑥ 的分母（`scope/v3`，2026-10-02）。

§4.1b 的来源覆盖门写的是「每张**入库卡（L1/L2）**至少派生 1 条」。判"哪些卡不是
入库卡"不能由实现自己说了算，所以这个工具带**两条反向对照**：

1. **对照组**：从"**已经有条目**的卡"
里抽一批一起判——它们已经派生出边，如果审查员把它们也判成范围外，说明"范围外"
这个桶真的会开火，不是橡皮章。

原实现把这条写成了 `set(cards) - set(wanted) & set(covered)`。Python 里 `&` 比 `-`
优先，于是它算的是 `cards - (wanted ∩ covered)`——"去除被点名且已覆盖的"，结果
**几乎全部卡片**都进了对照池，其中一大批根本没有条目。那样抽出来的样本不再证明
任何事：它没法说明"已覆盖的卡被判范围外"这种情况发生过几次。

这里钉住三件事：只取已覆盖的、不取被点名的、同一 seed 可复现。

另外一个更重的教训（2026-10-02）：**判据本身不能是模型判读**。实测双模型面板
在同一批卡上不可复现（同一提示、`temperature=0`，同一张卡两次运行被判成
`not_expressible` 与 `shot_language` 各一次），所以 `scope/v3` 的判据改成确定性
的索引证据：**索引对该卡零条边 ⇒ 不进分母**（`must` 在构造上落不到任何边，
门⑩ 无解；而"单卡重抽"会逼模型凭空吐边——实测 29 张卡全部吐出了边，
包括"场景表只需列出外景与内景的清单"→ `SHOT_PATTERN:MS/50mm/cinematic`）。
面板只作旁证，留在 `--panel-out` 的产物里。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch.card_scope_audit import (  # noqa: E402
    CATEGORIES,
    audit,
    control_pool,
)


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


def test_exclusion_follows_the_index_and_not_the_oracle() -> None:
    """判据是"索引对该卡零条边"，**与 oracle 里有什么无关**。

    这正是 `scope/v3` 与前一版的区别：前一版的分母随双模型判读变动，实测两次运行
    给出两套名单。这里用"把 covered 换成空集／全集"来证明分母不动。
    """
    cards = {ident: {"id": ident, "domain": "d", "title": "t", "content": "c"}
             for ident in ("a", "b", "c")}
    counts = {"a": 2, "b": 0, "c": 1}
    first = audit(cards, counts, covered=[])
    second = audit(cards, counts, covered=["a", "b", "c"])
    assert first["excluded"] == second["excluded"] == ["b"]
    assert first["edge_backed"] == 2
    assert first["excluded_with_edges"] == []
    # 门⑥ 真正在测的东西随 oracle 变——那是**缺口**，不是分母。
    assert first["edge_backed_without_entry"] == ["a", "c"]
    assert second["edge_backed_without_entry"] == []


def test_a_card_with_an_edge_may_never_be_excluded() -> None:
    """不变量：剔掉一张索引能表达的卡 ⇒ 判据坏了（`excluded_with_edges` 必须空）。"""
    cards = {ident: {"id": ident} for ident in ("a", "b")}
    report = audit(cards, {"a": 1, "b": 0}, covered=[])
    assert report["excluded"] == ["b"]
    assert report["excluded_with_edges"] == []
    assert report["edge_backed_without_entry"] == ["a"]


def test_the_shipped_scope_artifact_matches_the_index() -> None:
    """入库的 `knowledge/card_scope.json` 必须**就是**索引算出来的那张名单。

    没有这一条，"判据不是橡皮章"就只是一句自述：产物可能被手工改窄，
    或者索引换了而名单没跟着动。这里三件事一起钉住——
    ① `excluded` 与索引、入库清单三方一致；
    ② 被剔的卡一张都不许有边；
    ③ 那个桶真的开过火（有**已经派生条目**的卡被剔，也有**可断言卡**的缺口被如实报出）。
    """
    import json

    scope = json.loads((ROOT / "knowledge" / "card_scope.json").read_text(encoding="utf-8"))
    catalogue = json.loads(
        (ROOT / "fixtures" / "knowledge_holdout.cards.json").read_text(encoding="utf-8"))
    edges = [json.loads(line) for line in
             (ROOT / "knowledge" / "hypergraph.edges.jsonl")
             .read_text(encoding="utf-8").splitlines() if line.strip()]
    counts: dict = {}
    for edge in edges:
        for source in edge.get("sources") or []:
            counts[str(source)] = counts.get(str(source), 0) + 1
    expected = sorted(card for card in catalogue if counts.get(str(card), 0) == 0)

    assert scope["criterion_version"] == "scope/v3"
    assert scope["excluded"] == expected
    assert scope["out_of_scope"] == expected, "旧键必须与新键同义（读取方两个都认）"
    assert scope["excluded_count"] == len(expected)
    assert scope["excluded"], "一张都不剔：这个桶要么没用，要么判据坏了"
    assert scope["excluded_with_edges"] == [], "剔掉了索引能表达的卡"
    for ident in expected:
        assert scope["edges_per_card"][ident] == 0

    # ③ 桶开过火的两条证据。
    covered = {json.loads(line).get("from_card") for line in
               (ROOT / "fixtures" / "knowledge_holdout.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()}
    covered_but_excluded = sorted(ident for ident in expected if ident in covered)
    assert covered_but_excluded, (
        "被剔掉的卡全都是没有条目的——那对照组就没法证明判据会开火")
    #: `edge_backed_without_entry` 是门⑥ 的**真缺口**（可断言卡里还缺条目的）。
    #: 它必须与直接算出来的一致；空集表示这一轮覆盖率真的达标了。
    assert scope["edge_backed_without_entry"] == sorted(
        card for card in catalogue
        if counts.get(str(card), 0) > 0 and card not in covered)


def test_the_criterion_categories_stay_a_closed_set() -> None:
    """面板的类别表是闭集，且**只有一个** assertable——漏答按 shot_language 计。"""
    assert CATEGORIES["shot_language"] is True
    assert sum(1 for value in CATEGORIES.values() if value) == 1
    assert all(isinstance(value, bool) for value in CATEGORIES.values())
