"""C2：「9 边 / 15 槽位」两案备料（**只读**，不动索引）。

本脚本把两把尺子并排跑在同一批 9 条边上：

* **旧尺子**（`work/_probe_wrong_card.py` 的口径）：卡片只从
  `knowledge/cards_generated/*.yaml` 用正则切块读，主题只读 `topic` ⇒
  132 张手写卡**读不到**、`topic` 为空的卡也进集合（于是"不知道"被记成"不符"）。
* **新尺子**（`work/_probe_wrong_card_full.py` 的口径）：生成卡（`.jsonl`）＋
  手写卡（`corpus.HANDWRITTEN_CARDS`）一起进索引；手写卡用 `domain` 顶替 `topic`；
  `topic` 为空单列 `topic_unknown`。

并且数出**换代影响面**：仓库里有多少份已入库运行的 `run_manifest.json.pins.index`
钉着当前索引指纹。

跑法（仓库根）：`python docs/evidence/_v15_stage8/c2_edge_surgery/edge_surgery.py`
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = pathlib.Path(__file__).resolve().parent
EDGES = ROOT / "knowledge/hypergraph.edges.jsonl"
MANIFEST = ROOT / "knowledge/hypergraph.manifest.json"
CLOSURE_LOG = ROOT / "docs/evidence/20261007-real-closure/audit_log.jsonl"
CLOSURE_SHOTS = ROOT / "work/_real_closure/export/shots.json"

#: 闭环诊断里"未纳入判定"的三个 kind（`tools/knowledge/execution_closure_report.py`）。
CLOSED_LOOP_KINDS = ("headroom_policy", "composition_rule", "camera_angle")


def load_jsonl(path: pathlib.Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def old_ruler_cards() -> dict:
    """旧尺子：只读 `*.yaml` 的正则切块（**故意照抄旧探针的读法**，含它的缺陷）。"""
    cards: dict = {}
    for path in (ROOT / "knowledge/cards_generated").glob("*.yaml"):
        for block in path.read_text(encoding="utf-8").split("\n- "):
            ident = re.search(r"id:\s*([^\s]+)", block)
            if not ident:
                continue
            topic = re.search(r"^\s*topic:\s*(.*)$", block, re.M)
            cards[ident.group(1)] = {
                "text": block,
                "topic": topic.group(1).strip().strip("'\"") if topic else "",
                "origin": "generated",
            }
    return cards


def new_ruler_cards() -> dict:
    """新尺子：权威索引（生成卡 `.jsonl` ＋ 132 张手写卡）。"""
    cards: dict = {}
    for path in sorted((ROOT / "knowledge/cards_generated").glob("*.jsonl")):
        for row in load_jsonl(path):
            cards[str(row["id"])] = {
                "text": " ".join([str(row.get("title", "")), str(row.get("content", "")),
                                  " ".join(map(str, row.get("keywords") or [])),
                                  " ".join(map(str, row.get("tags") or []))]),
                "topic": str(row.get("topic") or "").strip(),
                "domain": str(row.get("domain") or "").strip(),
                "origin": "generated",
            }
    from block_director.knowledge.corpus import HANDWRITTEN_CARDS

    for card in HANDWRITTEN_CARDS:
        cards[str(card.id)] = {
            "text": " ".join([str(card.title), str(card.content),
                              " ".join(map(str, card.keywords or [])),
                              " ".join(map(str, card.tags or []))]),
            "topic": "",                       # 手写卡没有 `topic` 字段
            "domain": str(getattr(card, "domain", "") or "").strip(),
            "origin": "handwritten",
        }
    return cards


def blocked_edges() -> dict:
    """闭环诊断里"判不了"的边（成员含未纳入的 kind），逐条计数它的命中次数。"""
    from tools.knowledge import execution_closure_report as ecr

    edges = ecr.load_edges(EDGES)
    injections = ecr.injections(CLOSURE_LOG)
    shots = {str(row["shot_id"]): row
             for row in json.loads(CLOSURE_SHOTS.read_text(encoding="utf-8"))["shots"]}
    hit: collections.Counter = collections.Counter()
    for event in injections:
        if str(event.get("shot_id") or "") not in shots:
            continue
        for edge_id in event.get("edge_ids") or []:
            edge = edges.get(str(edge_id))
            if edge is None:
                continue
            kinds = {str(m[1]) for m in (edge.get("members") or []) if len(m) == 3}
            if kinds - set(ecr.MAPPING) - set(ecr.NOT_A_CONDITION):
                hit[str(edge_id)] += 1
    return edges, hit


def verdict_old(row: dict, cards: dict) -> str:
    texts = [cards.get(s, {}).get("text", "") for s in row["sources"]]
    topics = {cards.get(s, {}).get("topic", "") for s in row["sources"]}
    if any(row["value"] and row["value"] in text for text in texts):
        return "in_card_text"
    if row["kind"] in topics:
        return "topic_matches"
    return "topic_mismatch"          # 空串也进集合 ⇒ "不知道"被记成"不符"


def verdict_new(row: dict, cards: dict) -> str:
    """新尺子的判定（**逐字照抄 `work/_probe_wrong_card_full.py:121-135` 的口径**）：

    * 主题比对用的是**双向子串包含**（`token == kind or token in kind or kind in token`）；
    * 手写卡用 `domain` 顶替 `topic`；
    * 来源卡的取值**全是空** ⇒ `topic_unknown`（"不知道"不是"不符"）。

    双向子串本身是**宽松**的：域 `composition` 会"包含于" kind `composition_rule`
    而判成相符——这**不是**语义等价，只是命名巧合。本脚本照抄它，是为了与已入库的
    读数对得上；判断谁对谁错不在本卡范围内。
    """
    texts = [cards.get(s, {}).get("text", "") for s in row["sources"]]
    values = [cards[s]["domain"] if cards[s]["origin"] == "handwritten"
              else cards[s]["topic"] for s in row["sources"] if s in cards]
    if any(row["value"] and row["value"] in text for text in texts):
        return "in_card_text"
    if any(token and (token == row["kind"] or token in row["kind"]
                      or row["kind"] in token) for token in values):
        return "topic_or_domain_matches_kind"
    if not any(values):
        return "topic_unknown"
    return "topic_mismatch"


def candidate_cards(row: dict, cards: dict) -> list:
    """"换卡案"的机械候选：**正文里真的写了这个取值**的卡（全库搜，不只是来源卡）。

    没有候选就如实返回空列表——那说明这条槽位**当前无机械证据**，
    "换卡"要等 90 槽位三分类的语义判词。
    """
    value = row["value"]
    if not value:
        return []
    return sorted(cid for cid, card in cards.items() if value in card["text"])


def pins_impact() -> dict:
    manifests = sorted(pathlib.Path(ROOT).rglob("run_manifest.json"))
    pinned = []
    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        index = (data.get("pins") or {}).get("index") or {}
        if not index:
            continue
        pinned.append({
            "run": path.parent.relative_to(ROOT).as_posix(),
            "fingerprint": index.get("fingerprint"),
            "pins": sorted((data.get("pins") or {}).keys()),
        })
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {
        "runs_pinning_index": len(pinned),
        "current_index_fingerprint": manifest.get("fingerprint"),
        "runs": pinned,
        "all_same_fingerprint": len({r["fingerprint"] for r in pinned}) == 1,
    }


def main() -> int:
    from block_director.knowledge import hypergraph as hg

    old_cards = old_ruler_cards()
    new_cards = new_ruler_cards()
    edges, hit = blocked_edges()

    rows = []
    for edge_id in sorted(hit):
        edge = edges[edge_id]
        sources = [str(s) for s in (edge.get("sources") or [])]
        members = [m for m in (edge.get("members") or []) if len(m) == 3]
        for member in members:
            kind = str(member[1])
            if kind not in CLOSED_LOOP_KINDS:
                continue
            row = {"edge_id": edge_id, "type": edge.get("type"), "role": str(member[0]),
                   "kind": kind, "value": str(member[2]).split(":", 1)[-1],
                   "sources": sources, "injection_hits": hit[edge_id]}
            row["verdict_old"] = verdict_old(row, old_cards)
            row["verdict_new"] = verdict_new(row, new_cards)
            row["candidate_cards"] = candidate_cards(row, new_cards)
            row["sources_include_handwritten"] = sorted(
                s for s in sources if new_cards.get(s, {}).get("origin") == "handwritten")
            rows.append(row)

    report = {
        "blocked_edges": len(hit),
        "slots": len(rows),
        "old_ruler_verdicts": dict(collections.Counter(r["verdict_old"] for r in rows)),
        "new_ruler_verdicts": dict(collections.Counter(r["verdict_new"] for r in rows)),
        "slots_without_mechanical_candidate": sum(
            1 for r in rows if not r["candidate_cards"]),
        "rows": rows,
        "pins_impact": pins_impact(),
        "schema_fingerprint": hg.schema_fingerprint(),
        "note": ("两把尺子的差别**只在读卡口径**；机械判据给的是信号，不是判决。"
                 "`candidate_cards` 是『正文里真的写了这个取值』的全库候选，"
                 "空列表＝当前无机械证据，不等于『这张卡是错的』。"),
    }
    (OUT / "edges.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("rows", "pins_impact")}, ensure_ascii=False, indent=1))
    print("pins_impact.runs_pinning_index =", report["pins_impact"]["runs_pinning_index"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
