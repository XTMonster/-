"""修正版机械判据：`work/_probe_wrong_card.py` 的**卡索引是残缺的**。

那份探针只读 `knowledge/cards_generated/*.yaml`，于是：

* **手写卡**（`comp_headroom` / `perf_emotion` / `cine_lens` / `block_crowd_density` …）
  住在 Python 模块里（`block_director/knowledge/cards_*.py`，经
  `corpus.HANDWRITTEN_CARDS` 暴露）⇒ 在它的索引里**整个不存在**；
* 手写卡**根本没有 `topic` 字段**——它们有的是 `domain`（`composition` / `performance` …）。

两条合起来的后果：**来源卡只要有一张是手写卡，该槽位就同时得到 `text=""` 与 `topic=""`**，
被机械判成 `topic_mismatch`。这正是裁定自己留的那句边界（"`topic` 字段本身也是生成物，
它错这条判据就跟着错"）之外的**第二个**误差源。

本脚本用**权威注册表** `corpus.CARDS`（手写＋生成，合并规则与产品逐字一致）重算同一批槽位，
并把"这张来源卡在索引里到底找不找得到"单独报出来。**只读**，不写任何知识文件。
"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from block_director.knowledge import corpus  # noqa: E402
from tools.knowledge import execution_closure_report as ecr  # noqa: E402

GEN_DIR = ROOT / "knowledge/cards_generated"
CLOSED_LOOP_KINDS = ("headroom_policy", "composition_rule", "camera_angle")


def load_generated() -> dict:
    """生成卡：**整条 entry**（含 `topic` / `source_ref` / `quote`）——`Card` 里没有 `topic`。"""
    out = {}
    for path in sorted(GEN_DIR.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").split("\n"):
            raw = raw.strip()
            if not raw:
                continue
            entry = json.loads(raw)
            out[str(entry["id"])] = entry
    return out


def load_nodes() -> dict:
    out = {}
    for raw in (ROOT / "knowledge/hypergraph.nodes.jsonl").read_text(
            encoding="utf-8").split("\n"):
        raw = raw.strip()
        if raw:
            record = json.loads(raw)
            out[str(record["node_id"])] = record
    return out


def generated_text(entry: dict) -> str:
    """与 `grounding.asserted_text` 同口径：标题＋正文＋关键词＋标签。"""
    parts = [str(entry.get("title") or ""), str(entry.get("content") or "")]
    for key in ("keywords", "tags"):
        value = entry.get(key) or ()
        if isinstance(value, str):
            parts.append(value)
        else:
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


def handwritten_text(card) -> str:
    """与 `grounding.asserted_text` **逐字同口径**：标题＋正文＋关键词＋标签。

    **刻意不收** `examples` / `related`：`related` 里放的是**别的卡的 id**
    （`comp_headroom_extremes` 这种），拿它当正文会把"取值出现在卡里"变成
    恒真的假命中——那是把判据读歪，不是把判据放松。`examples` 只是举例，
    与"这张卡断言了这个取值"不是一回事（`grounding` 也没把它算进去）。
    """
    parts = [card.title, card.content, " ".join(card.keywords), " ".join(card.tags)]
    return " ".join(part for part in parts if part)


def surfaces(node_id: str, nodes: dict) -> set:
    """与 `grounding.surface_names` 同口径：取值 ＋ 名字 ＋ 别名。"""
    text = str(node_id)
    names = {text.split(":", 1)[1] if ":" in text else text}
    record = nodes.get(text)
    if record:
        for key in ("name", "value"):
            if record.get(key):
                names.add(str(record[key]))
        for alias in record.get("aliases") or []:
            names.add(str(alias))
    return {name for name in names if name}


def classify(edge: dict, member: list, generated: dict, handwritten: dict,
             nodes: dict) -> dict:
    kind, node_id = str(member[1]), str(member[2])
    names = surfaces(node_id, nodes)
    sources = [str(item) for item in (edge.get("sources") or [])]
    rows, tokens, hit, missing = [], set(), None, []
    for source in sources:
        row = {"source": source, "found": False, "topic_or_domain": "", "name_hits": [],
               "side_text_hits": []}
        if source in generated:
            row.update(found=True, topic_or_domain=str(generated[source].get("topic") or ""),
                       name_hits=sorted(n for n in names if n and n in generated_text(generated[source])))
        elif source in handwritten:
            card = handwritten[source]
            side = " ".join(card.examples) + " " + " ".join(card.related)
            row.update(found=True, topic_or_domain=str(card.domain),
                       name_hits=sorted(n for n in names if n and n in handwritten_text(card)),
                       side_text_hits=sorted(n for n in names if n and n in side))
        else:
            missing.append(source)
            rows.append(row)
            continue
        if row["topic_or_domain"]:
            tokens.add(row["topic_or_domain"])
        if row["name_hits"] and hit is None:
            hit = (source, row["name_hits"])
        rows.append(row)
    if hit:
        verdict = "in_card_text"
    elif any(token and (token == kind or token in kind or kind in token) for token in tokens):
        verdict = "topic_or_domain_matches_kind"
    elif tokens:
        verdict = "topic_mismatch"
    elif any(row["found"] for row in rows):
        #: 来源卡都在索引里，但它们的 `topic` 字段**全是空的**——那是"不知道"，
        #: 不是"不符"（把空串当 mismatch 会把"缺字段"读成"挂错卡"）。
        verdict = "topic_unknown"
    else:
        verdict = "no_evidence"
    if not any(row["found"] for row in rows):
        verdict = "card_not_in_index"
    return {"edge_id": str(edge.get("id") or edge.get("edge_id")), "kind": kind,
            "value": str(member[2]).split(":", 1)[-1], "verdict": verdict,
            "surface_hit": list(hit[1]) if hit else [], "sources": rows,
            "missing_sources": missing}


def main() -> int:
    generated, nodes = load_generated(), load_nodes()
    handwritten = {card.id: card for card in corpus.HANDWRITTEN_CARDS}
    edges = ecr.load_edges(ROOT / "knowledge/hypergraph.edges.jsonl")
    injections = ecr.injections(ROOT / "docs/evidence/20261007-real-closure/audit_log.jsonl")
    shots = {str(row["shot_id"]): row for row in json.loads(
        (ROOT / "work/_real_closure/export/shots.json").read_text(encoding="utf-8"))["shots"]}

    blocked = collections.Counter()
    for event in injections:
        if str(event.get("shot_id") or "") not in shots:
            continue
        for edge_id in event.get("edge_ids") or []:
            edge = edges.get(str(edge_id))
            if edge is None:
                continue
            kinds = {str(item[1]) for item in (edge.get("members") or []) if len(item) == 3}
            if kinds - set(ecr.MAPPING) - set(ecr.NOT_A_CONDITION):
                blocked[str(edge_id)] += 1

    rows, verdicts = [], collections.Counter()
    per_edge_index_gap = {}
    for edge_id in sorted(blocked):
        edge = edges[edge_id]
        gap = 0
        for member in edge.get("members") or []:
            if len(member) != 3 or str(member[1]) not in CLOSED_LOOP_KINDS:
                continue
            rows.append(classify(edge, member, generated, handwritten, nodes))
            for source in edge.get("sources") or []:
                if str(source) in handwritten:
                    gap += 1
                    break
        per_edge_index_gap[edge_id] = gap
    for row in rows:
        verdicts[row["verdict"]] += 1

    payload = {
        "blocked_edges": len(blocked),
        "slots": len(rows),
        "verdicts_full_index": dict(verdicts),
        "index_size": {"generated": len(generated), "handwritten": len(handwritten),
                       "nodes": len(nodes)},
        "edges_whose_sources_include_a_handwritten_card": sorted(
            edge for edge, gap in per_edge_index_gap.items() if gap),
        "slots_detail": rows,
        "note": "修正版：手写卡（Python 模块）与生成卡（jsonl）一起进索引；"
                "`topic` 对手写卡用 `domain` 代替。这是机械信号，不是判决。",
    }
    (ROOT / "work/_wrong_card_full.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in payload.items()
                      if key != "slots_detail"}, ensure_ascii=False, indent=1))
    for row in rows:
        source_bits = ", ".join(
            "%s%s:%s" % (item["source"], "" if item["found"] else "(缺失)",
                         item["topic_or_domain"] or "∅") for item in row["sources"])
        print("%-20s %-18s %-9s %-30s | %s" % (
            row["edge_id"], row["kind"], row["value"], source_bits, row["verdict"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
