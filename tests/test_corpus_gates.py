"""§2.3c 的 **K1–K4**：语料合规与覆盖（RK-13 的**前置**）。

为什么单开一个文件（2026-10-03 实测）：这四门一直**只**在重跑导入
（`tools/kb_fetch/import_cards.py`）时才算，而验收链读的是**入库产物**——
卡被重新生成、报告没跟上、或者语料被手改过，链上不会有任何东西红。文档把 K1–K4
写成 RK-13 的前置，所以它们是**该量的**，只是从没被量过。

这里的用例全部用**合成语料**（不碰真语料），逐门造一个反例；另有两条正对照：
入库语料四门全过，以及"空语料不许真空通过"。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.corpus import DOMAINS  # noqa: E402
from tools.knowledge import corpus_gates as C  # noqa: E402
from tools.knowledge import hard_gates  # noqa: E402


def _card(ident: str, domain: str, *, license="CC-BY", sha="a" * 64,
          span=(0, 10, "c1"), **source_overrides) -> dict:
    source = {"url": f"https://example.org/{ident}", "title": "T",
              "author": "A", "license": license, "retrieved_at": "2026-10-01",
              "sha256": sha}
    source.update(source_overrides)
    return {"id": ident, "domain": domain, "title": "T", "content": "x",
            "source_ref": source,
            "source_span": {"chunk_id": span[2], "start": span[0], "end": span[1]}}


def _corpus(per_domain: int = 70) -> list:
    """每域 `per_domain` 张的合规语料（默认满足 K3 的 60 张＋5%）。"""
    cards = []
    for domain in DOMAINS:
        for index in range(per_domain):
            cards.append(_card(f"gen_{domain}_{index:04d}", domain,
                               sha=f"{domain}-{index}".ljust(64, "0"),
                               span=(index, index + 10, f"c{index}")))
    return cards


def _ledger(path: pathlib.Path, *, kept: int, candidates: int,
            deduped: int = 0) -> pathlib.Path:
    path.write_text(json.dumps({"counts": {
        "cards_candidates": candidates, "cards_kept": kept,
        "cards_deduped": deduped, "cards_rejected": 0}}), encoding="utf-8")
    return path


def _by_id(metrics) -> dict:
    return {item["id"]: item for item in metrics}


# --------------------------------------------------------------------------- 正对照


def test_the_shipped_corpus_passes_all_four_gates():
    """入库语料四门全过，而且数字是**非平凡**的（不是空语料蒙过）。"""
    metrics = _by_id(C.corpus_metrics())
    assert set(metrics) == {"K1_source_ref_complete", "K2_license_ratio",
                            "K3_domain_floor", "K4_dedupe_ratio"}
    for item in metrics.values():
        assert item["status"] == C.PASS, item
    k3 = metrics["K3_domain_floor"]
    assert k3["total"] >= C.MIN_CANDIDATES, k3
    assert k3["min_domain"] >= C.MIN_PER_DOMAIN, k3
    assert k3["min_share"] >= C.MIN_DOMAIN_SHARE, k3
    assert metrics["K4_dedupe_ratio"]["exact_duplicates_in_corpus"] == 0


def test_the_four_ids_are_hard_gates():
    """它们是 RK-13 的前置 ⇒ 必须挂在硬门清单上（缺一条就算 RK-13 未通过）。"""
    for ident in ("K1_source_ref_complete", "K2_license_ratio",
                  "K3_domain_floor", "K4_dedupe_ratio"):
        assert ident in hard_gates.HARD_IDS, ident
        assert ident not in hard_gates.SOFT_IDS, ident


# --------------------------------------------------------------------------- 逐门反例


def test_k1_fires_on_a_card_with_a_missing_source_field():
    cards = _corpus()
    cards[5] = _card("gen_bad_0001", DOMAINS[0], author="")
    item = C.k1_source_ref(cards)
    assert item["status"] == C.FAIL
    assert item["numerator"] == len(cards) - 1
    assert item["examples"][0]["missing"] == ["author"], item["examples"]


def test_k2_fires_on_a_license_outside_the_whitelist():
    cards = _corpus()
    cards[7] = _card("gen_bad_0002", DOMAINS[0], license="AllRightsReserved")
    item = C.k2_license(cards)
    assert item["status"] == C.FAIL
    assert item["examples"][0]["license"] == "AllRightsReserved"
    assert item["value"] < 1.0


def test_k3_fires_when_a_domain_is_thin():
    """一个域只有 10 张 ⇒ 低于 60 张的线（**不是**"总体够就行"）。

    这里显式 `handwritten=[]`：默认口径会把手写策展卡也算进语料（§2.3c 的"5 域
    132 张"就是这个口径，见下一条用例），而这一条要单独量"生成卡这一侧"。
    """
    cards = _corpus()
    thin = DOMAINS[0]
    cards = [card for card in cards if card["domain"] != thin]
    cards += [_card(f"gen_{thin}_{i}", thin, sha=f"thin-{i}".ljust(64, "0"),
                    span=(i, i + 1, "c")) for i in range(10)]
    item = C.k3_domain_floor(cards, handwritten=[])
    assert item["status"] == C.FAIL
    assert any(entry["domain"] == thin for entry in item["thin_domains"])


def test_k3_fires_when_a_declared_domain_is_absent():
    cards = [card for card in _corpus() if card["domain"] != DOMAINS[1]]
    item = C.k3_domain_floor(cards, handwritten=[])
    assert item["status"] == C.FAIL
    assert item["missing_domains"] == [DOMAINS[1]]


def test_k3_counts_the_handwritten_curation_cards_by_default():
    """手写策展卡**计入语料**（§2.3c 的"5 域 132 张"口径），否则 K3 的分母错了。

    反例：某个域只剩 10 张生成卡、手写 50 张 ⇒ 60 张，**刚好达标**；把 `handwritten`
    关掉就会误判成"不足"。这两者只差默认口径。
    """
    from block_director.knowledge.corpus import HANDWRITTEN_CARDS

    thin = DOMAINS[0]
    cards = [card for card in _corpus() if card["domain"] != thin]
    cards += [_card(f"gen_{thin}_{i}", thin, sha=f"thin-{i}".ljust(64, "0"),
                    span=(i, i + 1, "c")) for i in range(10)]
    assert C.k3_domain_floor(cards, handwritten=[])["status"] == C.FAIL
    with_defaults = C.k3_domain_floor(cards)
    assert with_defaults["status"] == C.PASS, with_defaults["note"]
    assert sum(c.domain == thin for c in HANDWRITTEN_CARDS) >= 50


def test_k4_fires_when_the_ledger_disagrees_with_the_corpus(tmp_path):
    """账本说 99 张、语料 630 张 ⇒ 判失败（"账对不上语料"）。"""
    cards = _corpus()
    ledger = _ledger(tmp_path / "r.json", kept=99, candidates=99)
    item = C.k4_dedupe(cards, ledger)
    assert item["status"] == C.FAIL
    assert any("账对不上语料" in problem for problem in item["problems"])


def test_k4_fires_when_the_corpus_still_holds_an_exact_duplicate(tmp_path):
    """入库语料里还有完全重复的卡 ⇒ "去重"这件事本身没有发生。"""
    cards = _corpus()
    twin = dict(cards[0])
    twin["id"] = "gen_dup_0001"
    cards.append(twin)
    ledger = _ledger(tmp_path / "r.json", kept=len(cards), candidates=len(cards))
    item = C.k4_dedupe(cards, ledger)
    assert item["status"] == C.FAIL
    assert item["exact_duplicates_in_corpus"] == 1


def test_k4_fires_below_the_dedupe_line(tmp_path):
    """有效率 0.5 < 0.6（分母带 200 条被去掉的重复）⇒ 判失败。"""
    cards = _corpus()
    ledger = _ledger(tmp_path / "r.json", kept=len(cards),
                     candidates=len(cards), deduped=len(cards))
    item = C.k4_dedupe(cards, ledger)
    assert item["status"] == C.FAIL
    assert item["value"] == 0.5


def test_k4_is_not_measured_when_the_ledger_is_missing(tmp_path):
    """账本不在 ⇒ `not_measured`（缺证据不是通过）；硬门那边会把它算成未通过。"""
    item = C.k4_dedupe(_corpus(), tmp_path / "nope.json")
    assert item["status"] == C.NA
    assert "缺构建期账本" in item["note"]


# --------------------------------------------------------------------------- 空集


def test_an_empty_corpus_fails_instead_of_passing_vacuously():
    """空语料：K1/K2/K3 的**分母为 0** ⇒ 按 §4.1b 硬规则 1 一律判失败。"""
    assert C.k1_source_ref([])["status"] == C.FAIL
    assert C.k2_license([])["status"] == C.FAIL
    empty = C.k3_domain_floor([], handwritten=[])
    assert empty["status"] == C.FAIL
    assert "分母无意义" in empty["note"]
