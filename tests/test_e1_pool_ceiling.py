"""`tools/knowledge/e1_pool_ceiling.py`：去标签池的**上界 / 交付位工作点**（全离线，零判分）。

它守的是三件事：
① **上界＝取最好那一组**（不是全三元组均值——两个数不许互换引用）；
② **交付位只按"去标签标量"排**（池内名次/余弦），**永远看不到判分**；
③ 承重墙：`retrieval_order` 那一列只有在"银行文件序 == 产品检索器"成立时才有意义，
   不成立要**具名报出来**，不许默默给表。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import e1_pool_ceiling as pc  # noqa: E402


def _row(query, case_id, scores, *, zh="", excerpt="e"):
    return {"query": query, "case_id": case_id, "scores": scores,
            "zh": zh, "excerpt": excerpt}


def _write_bank(tmp_path, rows):
    path = tmp_path / "bank.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return path


# --------------------------------------------------------------------------- 口径
def test_strict_score_needs_both_judges():
    """P14-249：少一位评委⇒不发分⇒**算不相关**（而它**仍留在分母里**）。"""
    assert pc.strict_score({"scores": [5, 5]}) == 5.0
    assert pc.strict_score({"scores": [5, None]}) is None
    assert pc.strict_score({"scores": [None]}) is None
    assert pc.is_relevant(None) is False
    assert pc.is_relevant(4.0) is True and pc.is_relevant(3.99) is False


def test_ceiling_takes_the_best_group_while_mean_takes_all():
    """"上界"必须是**最好那一组**；把它和"全三元组均值"混用就是把两个量纲当同一个数。"""
    label_of = {"a": 5.0, "b": 5.0, "c": 5.0, "d": 1.0}
    metrics = pc.pool_ceiling(["a", "b", "c", "d"], label_of)
    assert metrics["triples"] == 4
    assert metrics["best"] == 3 and metrics["ceiling"] == 1.0
    assert metrics["mean"] == pytest.approx((3 + 2 + 2 + 2) / 4 / 3.0)


def test_ceiling_is_non_decreasing_in_pool_depth():
    """池子变大只能让"最好那组"更好，绝不会更差——这是这张表能被当曲线读的前提。"""
    label_of = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 5.0, "e": 5.0, "f": 5.0}
    order = ["a", "b", "c", "d", "e", "f"]
    ceilings = [pc.pool_ceiling(order[:n], label_of)["ceiling"] for n in (3, 4, 5, 6)]
    assert ceilings == sorted(ceilings)
    assert ceilings[0] == 0.0 and ceilings[-1] == 1.0


# --------------------------------------------------------------------------- 选择器只能看标量
def test_delivered_top3_uses_only_the_scorer_and_can_be_punished():
    """故意给一个**反着排**的标量 ⇒ 命中 0。证明交付位没有偷看判分。"""
    label_of = {"a": 5.0, "b": 5.0, "c": 5.0, "d": 1.0, "e": 1.0, "f": 1.0}
    #: 反着排：**相关的那三条拿最低分** ⇒ 交付位交出来的是 d/e/f ⇒ 命中 0。
    worst = {"a": -6.0, "b": -5.0, "c": -4.0, "d": -3.0, "e": -2.0, "f": -1.0}
    best = {"a": 6.0, "b": 5.0, "c": 4.0, "d": 3.0, "e": 2.0, "f": 1.0}
    pool = ["a", "b", "c", "d", "e", "f"]
    assert pc.delivered_top3(pool, worst, label_of) == 0
    assert pc.delivered_top3(pool, best, label_of) == 3


def test_retrieval_order_scorer_reproduces_the_top_three_identity():
    """锚点性质：`retrieval_order` 这个选择器在任何深度下交的都是**前 3 条**。"""
    label_of = {"a": 5.0, "b": 1.0, "c": 1.0, "d": 5.0, "e": 5.0, "f": 1.0}
    order = ["a", "b", "c", "d", "e", "f"]
    prior = {cid: -float(i) for i, cid in enumerate(order)}
    for depth in (3, 4, 5, 6):
        hits = pc.delivered_top3(order[:depth], prior, label_of)
        expected = sum(1 for cid in order[:3] if pc.is_relevant(label_of[cid]))
        assert hits == expected


def test_empty_pool_is_reported_as_none_not_as_zero():
    """池里凑不够 3 条可评案例 ⇒ `None`（**不是 0**：0 会被当成"交了但全不相关"）。"""
    assert pc.delivered_top3(["a", "b"], {"a": 1.0, "b": 1.0}, {"a": 5.0, "b": 5.0}) is None


def test_the_label_top_control_is_what_the_selector_may_not_build():
    """阳性对照：**按标签分**取 top-N 的上界贴着 1.0——它就是"门槛的参照物"那一列。"""
    label_of = {"a": 5.0, "b": 5.0, "c": 5.0, "d": 5.0}
    by_label = sorted(label_of, key=lambda cid: (-label_of[cid], cid))[:3]
    assert pc.pool_ceiling(by_label, label_of)["ceiling"] == 1.0


# --------------------------------------------------------------------------- 承重墙
def test_verify_bank_order_passes_when_they_agree_and_names_the_mismatch_when_not():
    bank = {"q1": [_row("q1", c, [5, 5]) for c in ("a", "b", "c")]}
    good = pc.verify_bank_order(bank, lambda q, k: ["a", "b", "c"][:k], top_k=3)
    assert good["exact"] == 1 and good["mismatched"] == 0
    assert good["verdict"].startswith("bank file order ==")
    bad = pc.verify_bank_order(bank, lambda q, k: ["b", "a", "c"][:k], top_k=3)
    assert bad["exact"] == 0 and bad["mismatched"] == 1
    assert "不成立" in bad["verdict"] and bad["mismatches"][0]["shipped"] == ["b", "a", "c"]


# --------------------------------------------------------------------------- 向量缓存
def test_vector_cache_reads_both_row_formats_and_refuses_empty_text(tmp_path):
    mine = tmp_path / "mine.jsonl"
    mine.write_text(json.dumps({"sha": pc.sha256_text("甲"), "vec": [1.0, 0.0]},
                               ensure_ascii=False) + "\n", encoding="utf-8")
    cache = pc.VectorCache(mine)
    assert cache.get("甲") == [1.0, 0.0] and cache.get("乙") is None
    assert cache.get("") is None, "空串不许送编码（智谱回 HTTP 400，实测）"

    theirs = tmp_path / "theirs.jsonl"
    key = pc.sha256_text("embedding-3\x00甲")
    theirs.write_text(json.dumps({"key": key, "model": "embedding-3", "vector": [0.0, 1.0]},
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    other = pc.VectorCache(theirs)
    assert other.get("甲") == [0.0, 1.0], "要能直接吃 embedding_cloud 的缓存格式"


# --------------------------------------------------------------------------- 端到端
def test_build_report_without_vectors_still_gives_the_two_label_free_columns():
    bank = collections_ordered(
        {"q1": [_row("q1", c, [5, 5]) for c in ("a", "b", "c")]
         + [_row("q1", c, [1, 1]) for c in ("d", "e", "f")]})
    report = pc.build_report(bank, vectors=None, titles={}, depths=(3, 6))
    constructions = {(r["construction"], r["pool_depth"]) for r in report["ceiling_table"]}
    assert ("retrieval_order", 3) in constructions and ("label_top", 6) in constructions
    assert not any(r["construction"].startswith("embed3") for r in report["ceiling_table"]), (
        "没有向量缓存就不该凭空多出嵌入列（更不能联网去要）")
    #: 这份合成银行的前 3 条就是相关的那 3 条 ⇒ 交付形状逐位命中（＝锚点性质）。
    assert report["anchors"]["proxy_retrieval_order_at_depth3"] == 1.0


def test_main_refuses_a_missing_bank_with_a_named_reason(tmp_path, capsys):
    code = pc.main(["--bank", str(tmp_path / "nope.jsonl"),
                    "--out", str(tmp_path / "o.json")])
    assert code == 3
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["error"] == "bank not found"
    assert not (tmp_path / "o.json").exists(), "拒绝时要**不落任何'读数'文件**"


def test_main_writes_the_report_end_to_end(tmp_path):
    """真的走一遍 CLI（`--cases knowledge` 只读本地索引，不联网）。"""
    rows = [_row("q1", c, [5, 5]) for c in ("a", "b", "c")]
    rows += [_row("q1", c, [1, 1]) for c in ("d", "e", "f")]
    bank = _write_bank(tmp_path, rows)
    out = tmp_path / "report.json"
    code = pc.main(["--bank", str(bank), "--cases", "knowledge",
                    "--out", str(out), "--depths", "3,6"])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["queries"] == 1
    assert payload["anchors"]["proxy_retrieval_order_at_depth3"] == 1.0
    assert payload["threshold_135_of_192"] == 0.703125


def collections_ordered(pairs):
    import collections
    return collections.OrderedDict(pairs)
