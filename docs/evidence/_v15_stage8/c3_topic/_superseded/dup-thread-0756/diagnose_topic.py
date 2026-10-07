"""C3：`topic` 字段准确率诊断（**只诊断，不改生成器**）。

回答的问题（`执行文档v1.5/TECH_SOLUTIONS.md` §三 C3）：
「`topic` 字段本身也是生成物，它的准确率没核」——而 90 槽位样本的机械预读
（`topic_mismatch 88/90`）**整套结论都架在这个字段上**。

本脚本只读仓库文件（卡片语料、索引、90 槽位样本），不写任何仓库位置，
输出三样东西：① `topic` 字段自身的质量读数；② 90 行样本在三种口径下的重算；
③ `topic` 与成员 `kind` 到底是不是同一维度。

跑法（仓库根）：`python docs/evidence/_v15_stage8/c3_topic/diagnose_topic.py`
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = pathlib.Path(__file__).resolve().parent
SAMPLE = ROOT / "docs/evidence/20261007-grounding-sample90/sample90.json"
CARDS_DIR = ROOT / "knowledge/cards_generated"
EDGES = ROOT / "knowledge/hypergraph.edges.jsonl"


def load_jsonl(path: pathlib.Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_cards() -> dict:
    """全库卡片：生成卡（有 `topic` 与 `domain`）＋ 132 张手写卡（只有 `domain`）。"""
    cards: dict = {}
    for path in sorted(CARDS_DIR.glob("*.jsonl")):
        for row in load_jsonl(path):
            cards[str(row["id"])] = {
                "id": str(row["id"]),
                "origin": "generated",
                "topic": str(row.get("topic") or "").strip(),
                "domain": str(row.get("domain") or "").strip(),
            }
    from block_director.knowledge.corpus import HANDWRITTEN_CARDS

    for card in HANDWRITTEN_CARDS:
        cards[str(card.id)] = {
            "id": str(card.id),
            # 手写卡的字段表里**没有** `topic`（`Card` 的字段是 domain/title/content/…）
            "origin": "handwritten",
            "topic": "",
            "domain": str(getattr(card, "domain", "") or "").strip(),
        }
    return cards


def corpus_readings(cards: dict) -> dict:
    gen = [c for c in cards.values() if c["origin"] == "generated"]
    hand = [c for c in cards.values() if c["origin"] == "handwritten"]
    nonempty = [c for c in gen if c["topic"]]
    agree = sum(1 for c in nonempty if c["topic"] == c["domain"])
    return {
        "cards_total": len(cards),
        "generated": len(gen),
        "handwritten": len(hand),
        "generated_topic_empty": len(gen) - len(nonempty),
        "generated_topic_empty_share": round((len(gen) - len(nonempty)) / len(gen), 4),
        "topic_values": dict(collections.Counter(c["topic"] for c in gen).most_common()),
        "domain_values": dict(collections.Counter(c["domain"] for c in cards.values()).most_common()),
        "handwritten_have_topic_field": sum(1 for c in hand if c["topic"]),
        "topic_equals_domain_when_nonempty": round(agree / len(nonempty), 4),
        "topic_domain_cross_tab": [
            {"domain": d, "topic": t, "n": n}
            for (d, t), n in collections.Counter(
                (c["domain"], c["topic"]) for c in nonempty).most_common(20)
        ],
        "empty_topic_by_domain": dict(collections.Counter(
            c["domain"] for c in gen if not c["topic"]).most_common()),
    }


def kind_vocabulary() -> dict:
    edges = load_jsonl(EDGES)
    kinds = collections.Counter(str(m[1]) for e in edges for m in e["members"])
    return {"kinds": dict(kinds.most_common()), "kind_count": len(kinds)}


def classify_row(row: dict, cards: dict, mode: str) -> str:
    """一行样本的判定。三种口径的差别**只在"卡级主题取哪个字段"**：

    * `topic_naive`：旧探针口径——只读 `topic`，空串也进集合（于是"不知道"被当成
      "不符"，因为 `['']` 是**真值**，`kind not in ['']` 恒真）。
    * `topic_corrected`：空 `topic` 记 `topic_unknown`；手写卡用 `domain` 顶替。
    * `domain_only`：一律用 `domain`（132 张手写卡与 2221 张生成卡**都有**这个字段）。
    """
    sources = [str(s) for s in row.get("sources") or []]
    kind = str(row.get("kind") or "")
    if mode == "topic_naive":
        pool = {cards[s]["topic"] for s in sources if s in cards}
        if pool and kind in pool:
            return "topic_ok"
        return "topic_mismatch"

    def effective(card: dict) -> str:
        if mode == "domain_only":
            return card["domain"]
        if card["origin"] == "handwritten":
            return card["domain"]          # 手写卡没有 topic：用 domain 顶替
        return card["topic"]

    values = [effective(cards[s]) for s in sources if s in cards]
    if kind in values:
        return "topic_ok"
    if not any(values):
        return "topic_unknown"
    return "topic_mismatch"


def sample_readings(cards: dict) -> dict:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    rows = data["rows"]
    out: dict = {"rows": len(rows), "recorded_pre_read": data.get("mechanical_pre_read"),
                 "modes": {}}
    for mode in ("topic_naive", "topic_corrected", "domain_only"):
        labels = [classify_row(row, cards, mode) for row in rows]
        counter = collections.Counter(labels)
        out["modes"][mode] = {
            "counts": dict(counter),
            "by_stratum": {
                stratum: dict(collections.Counter(
                    label for row, label in zip(rows, labels)
                    if row.get("stratum") == stratum))
                for stratum in sorted({r.get("stratum") for r in rows})
            },
            "mismatch_by_kind": dict(collections.Counter(
                row.get("kind") for row, label in zip(rows, labels)
                if label == "topic_mismatch").most_common()),
            "sources_seen": sum(len(r.get("sources") or []) for r in rows),
            "rows_with_multiple_sources": sum(
                1 for r in rows if len(r.get("sources") or []) > 1),
        }
    return out


def main() -> int:
    cards = load_cards()
    corpus = corpus_readings(cards)
    kinds = kind_vocabulary()
    sample = sample_readings(cards)
    topic_values = set(corpus["topic_values"]) - {""}
    domain_values = set(corpus["domain_values"])
    overlap = {
        "topic_values_that_are_also_kinds": sorted(topic_values & set(kinds["kinds"])),
        "domain_values_that_are_also_kinds": sorted(domain_values & set(kinds["kinds"])),
        "kind_count": kinds["kind_count"],
        "topic_value_count": len(topic_values),
        "domain_value_count": len(domain_values),
    }
    report = {"corpus": corpus, "kinds": kinds, "sample": sample, "vocabulary_overlap": overlap,
              "generated_at": "2026-10-07", "criterion_version": "topic-diagnosis/v1"}
    (OUT / "topic_inventory.json").write_text(
        json.dumps({"corpus": corpus, "kinds": kinds, "vocabulary_overlap": overlap},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (OUT / "topic_accuracy.json").write_text(
        json.dumps({"sample": sample}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
