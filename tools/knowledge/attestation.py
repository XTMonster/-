"""入库索引的**证据支持率**（诊断，不是门）。

这一层回答一个问题：**这条边的每个槽位，能不能在它自己的来源卡正文里找到依据？**

为什么要单独量它（2026-10-02）：

* 抽取器是**逐卡**调用的，而 schema 的 16 类边都是 2–3 个必填槽位的 **pack**
  （`STAGING_PACK` 必填 `构图 ＋ 景别 ＋ 机位`）。一张只讲构图的卡凑不出另外两个槽位，
  模型只能**填**——实测把讲"步行六相位""赛璐璐""逐笔描线"的卡分别补成
  `action=走位,beat_type=coverage,intensity=mid`、
  `prop=陈设,shot_size=MS,camera_angle=平视`、
  `vfx=impact_frame,sfx=静默,movement=固定`。**卡的原文是真的，槽位是填出来的**。
* 全库结构证据（`work/zz_p14_template_edges.py`）：2909 个「卡 × 边」只有 743 个不同的
  成员集，**55.9% 的链接属于被 ≥10 张卡共用**的成员集，最热的一条被 **173 张互不相干
  的卡**共用。
* 独立复核面板（DeepSeek ＋ GLM 两族，`tools/holdout_review_llm.py`）拿**卡**去判这些
  期望：**150 条里 139 条被一致否决**，理由都是"这张卡不支持这条边"。

`extractor.member_grounding` 那一栏本来是为此准备的，但它今天**是空转的**：提示词只
要求一条边级 `quote`，成员都是三元组，于是每个槽位按构造就是 `inferred`
（实测 8087/8087）——看着像测量，其实是常量。本模块改成**从产物本身算**：
拿这条边**全部来源卡**的正文去回查每个槽位取值的 surface（取值／规范名／同义说法）。

两条口径写清楚，免得被当成更严或更松的东西：

* **这是下界**。卡可以**蕴含**一个取值而不写出它（"把画面倒过来看"蕴含"检验平衡"），
  这种算 `unattested`。所以"20.7%"不等于"79.3% 是编的"。
* `not-checkable` 是**词表自己就是桶名**的槽位（`intensity:mid`、`avg_shot_len:>8s`），
  正文里本来就不会出现它们，既不算支持也不算不支持，单列。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Dict, Iterable, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.kb_fetch.build_hypergraph import node_surfaces  # noqa: E402

DEFAULT_EDGES = "knowledge/hypergraph.edges.jsonl"
DEFAULT_NODES = "knowledge/hypergraph.nodes.jsonl"
DEFAULT_CARDS = "knowledge/cards_generated"

ATTESTED = "attested"
UNATTESTED = "unattested"
NOT_CHECKABLE = "not-checkable"


def load_jsonl(path: pathlib.Path) -> List[dict]:
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_cards(directory: pathlib.Path) -> Dict[str, dict]:
    """生成的卡片 ＋ 手写策展卡（索引的 `sources` 两种都会指）。"""
    cards: Dict[str, dict] = {}
    for path in sorted(pathlib.Path(directory).glob("*.jsonl")):
        for row in load_jsonl(path):
            cards[str(row["id"])] = row
    from block_director.knowledge.corpus import CARDS

    for card in CARDS:
        cards.setdefault(str(card.id), {"id": str(card.id), "title": card.title,
                                        "content": card.content,
                                        "keywords": list(card.keywords),
                                        "tags": list(card.tags)})
    return cards


def card_blob(card: dict) -> str:
    return " ".join([str(card.get("title", "")), str(card.get("content", "")),
                     " ".join(map(str, card.get("keywords") or [])),
                     " ".join(map(str, card.get("tags") or []))])


def label_for(node, blob: str) -> str:
    """一个槽位在这条边的来源正文里算不算"有依据"（见模块 docstring 的口径）。"""
    forms = node_surfaces(node) if node is not None else []
    if not forms:
        return NOT_CHECKABLE
    return ATTESTED if any(form in blob for form in forms) else UNATTESTED


def audit(edges: Sequence[dict], cards: Dict[str, dict],
          nodes: Dict[str, hg.Node]) -> dict:
    """纯函数：给定索引、卡片全集与节点表，算证据支持率（可重放、不调模型）。"""
    slots: collections.Counter = collections.Counter()
    per_type: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    fully_attested = 0
    examples: List[dict] = []
    for edge in edges:
        blob = "".join(" " + card_blob(cards[str(source)])
                       for source in (edge.get("sources") or []) if str(source) in cards)
        labels = [label_for(nodes.get(member[2]), blob) for member in edge["members"]]
        for label in labels:
            slots[label] += 1
            per_type[str(edge["type"])][label] += 1
        if labels and all(label != UNATTESTED for label in labels):
            fully_attested += 1
        elif len(examples) < 20:
            examples.append({
                "edge_id": edge.get("edge_id"), "type": edge.get("type"),
                "unattested": [member[2] for member, label in zip(edge["members"], labels)
                               if label == UNATTESTED],
                "sources": list(edge.get("sources") or [])[:3],
            })
    checkable = slots[ATTESTED] + slots[UNATTESTED]
    return {
        "edges": len(edges),
        "slots": dict(slots),
        "checkable_slots": checkable,
        "attested_share": round(slots[ATTESTED] / checkable, 4) if checkable else None,
        "edges_fully_attested": fully_attested,
        "edges_fully_attested_share": (round(fully_attested / len(edges), 4)
                                       if edges else None),
        "by_type": {etype: dict(counter) for etype, counter in sorted(per_type.items())},
        "unattested_examples": examples,
        "criterion": ("成员取值能否在**这条边自己的来源卡正文**里找到 surface"
                      "（取值／规范名／同义说法）；这是**下界**——卡可以蕴含而不写出它。"
                      "`not-checkable` ＝ 词表自己就是桶名（`intensity:mid`／"
                      "`avg_shot_len:>8s`），正文里本来不会出现。"),
        "criterion_version": "attest/v1",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge.attestation")
    parser.add_argument("--edges", default=DEFAULT_EDGES)
    parser.add_argument("--nodes", default=DEFAULT_NODES)
    parser.add_argument("--cards", default=DEFAULT_CARDS)
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    nodes = {row["node_id"]: hg.Node.from_dict(row)
             for row in load_jsonl(ROOT / args.nodes)}
    report = audit(load_jsonl(ROOT / args.edges), load_cards(ROOT / args.cards), nodes)
    if args.json:
        target = ROOT / args.json
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                          encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("by_type", "unattested_examples")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
