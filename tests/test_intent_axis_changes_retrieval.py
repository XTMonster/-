"""意图轴不只是"多发一个键"——它**真的改变了超图交回来的东西**。

判定方向由证据给出（`docs/evidence/20261003_intent/README.md`）：同索引、同 6 条
**真实发出**的查询，只改"查询里有没有 `意图=`"，交回来的 `INTENT_PACK` 里
承载这一镜自己意图的比例从 1/17 变成 9/22。

为什么不把绝对数写死：索引会随语料重抽而重签，绝对条数本来就该变。这里钉的是
**方向**（带轴必须严格优于不带轴），以及"带轴之后不是零"——轴要是被谁摘掉，
这条会红，而它不会因为索引换代而假红。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import (  # noqa: E402
    HyperEdge,
    Hypergraph,
    Node,
)

AUDIT = ROOT / "docs" / "evidence" / "20261003_intent" / "audit_log.jsonl"


def _graph() -> Hypergraph:
    def load(name, cls):
        return [cls.from_dict(json.loads(line)) for line in
                (ROOT / "knowledge" / name).read_text(
                    encoding="utf-8").splitlines() if line.strip()]

    return Hypergraph(load("hypergraph.nodes.jsonl", Node),
                      load("hypergraph.edges.jsonl", HyperEdge))


def _queries():
    out = []
    for line in AUDIT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        data = event.get("data") or {}
        if event.get("kind") == "retrieval_call" and data.get("scope") == "shot":
            out.append((str(data.get("shot_id")), str(data.get("query") or "")))
    return out


def _split(query):
    intent, without = "", []
    for part in query.split("；"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == "意图":
            intent = value.strip()
        else:
            without.append(part)
    return intent, "；".join(without)


def _intent_of(edge) -> str:
    for member in edge.members:
        if str(getattr(member, "kind", "")) == "intent":
            #: `Member` 只存 `node_id`（`intent:停顿`），取值在冒号后面。
            return str(getattr(member, "node_id", "")).split(":", 1)[-1]
    return ""


def test_the_intent_axis_raises_the_share_of_on_intent_knowledge():
    graph = _graph()
    with_hits = with_total = without_hits = without_total = 0
    for _shot_id, query in _queries():
        intent, without = _split(query)
        assert intent, f"证据里的查询没有意图轴：{query}"
        for label, text in (("without", without), ("with", query)):
            selected, _rendered, _trace = graph.retrieve(text, top_k=5)
            packs = [edge for edge in selected
                     if getattr(edge, "type", "") == "INTENT_PACK"]
            hits = [edge for edge in packs if _intent_of(edge) == intent]
            if label == "with":
                with_hits += len(hits)
                with_total += len(packs)
            else:
                without_hits += len(hits)
                without_total += len(packs)
    assert with_total and without_total, "两次检索都没交回 INTENT_PACK，用例失去意义"
    assert with_hits > without_hits, (
        f"带上意图轴之后对得上意图的边没有变多：{with_hits}/{with_total} "
        f"vs {without_hits}/{without_total}")
    assert with_hits / with_total > without_hits / without_total
    assert without_hits / without_total < 0.2 < with_hits / with_total, (
        "方向反了或轴没生效："
        f"{without_hits}/{without_total} -> {with_hits}/{with_total}")
