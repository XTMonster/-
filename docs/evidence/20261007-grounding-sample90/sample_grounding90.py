"""裁定要的**分层抽检 90 槽位**：把样本与每条的证据（成员值＋来源卡正文＋卡 topic）摊平。

抽样框（照 `docs/evidence/20261007-grounding-ruling/README.md` §1 第③条）：
`PERFORMANCE_PACK` 20 ＋ `SHOT_PATTERN` 20 ＋ `STAGING_PACK` 20 ＋ **闭环三 kind 30**。
**确定可复现**：每层按 `(edge_id, kind, value)` 排序后取前 N（不是随机，写明即可复算）。

产出：`work/_grounding_sample90.json`（逐条证据）＋ `work/_grounding_sample90.md`（给人/模型看）。
"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.knowledge import attestation as att  # noqa: E402

CLOSED_LOOP_KINDS = ("headroom_policy", "composition_rule", "camera_angle")
PACK_STRATA = ("PERFORMANCE_PACK", "SHOT_PATTERN", "STAGING_PACK")
PER_PACK = 20
CLOSED_LOOP_QUOTA = 30


def card_topics(card: dict) -> str:
    """卡上的 `topic`（手写卡可能没有这个字段 ⇒ 空串）。"""
    return str(card.get("topic") or "").strip()


def card_excerpt(card: dict) -> str:
    """给人/模型看的节选：**与判据同一份文本**（`card_blob`）。"""
    return " ".join(att.card_blob(card).split())[:420]


def main() -> int:
    cards = att.load_cards(ROOT / "knowledge/cards_generated")
    edges = [row for row in att.load_jsonl(ROOT / "knowledge/hypergraph.edges.jsonl")
             if isinstance(row, dict) and row.get("edge_id")]
    nodes = {row["node_id"]: hg.Node.from_dict(row)
             for row in att.load_jsonl(ROOT / "knowledge/hypergraph.nodes.jsonl")}
    unattested = []
    for edge in edges:
        #: **逐字照 `attestation.audit()` 的口径**：同 `card_blob`、同 `label_for`。
        blob = "".join(" " + att.card_blob(cards[str(source)])
                       for source in (edge.get("sources") or [])
                       if str(source) in cards)
        labels = [att.label_for(nodes.get(member[2]), blob)
                  for member in edge["members"]]
        for member, label in zip(edge.get("members") or [], labels):
            if label != att.UNATTESTED or len(member) != 3:
                continue
            value = str(member[2])
            sources = [str(item) for item in (edge.get("sources") or [])]
            bare = value.split(":", 1)[-1]
            unattested.append({
                "edge_id": str(edge.get("edge_id")), "type": str(edge.get("type")),
                "role": str(member[0]), "kind": str(member[1]), "value": value,
                "sources": sources,
                "card_topics": sorted({card_topics(cards[s]) for s in sources
                                       if s in cards}),
                "surface_in_card": bool(bare) and bare in blob,
                "card_excerpt": card_excerpt(cards[sources[0]])
                if sources and sources[0] in cards else "",
            })

    #: 分层**互不重叠**：闭环三 kind 单独成层（它的行优先归它），其余按类型归 pack／rest。
    #: 这样 "20+20+20+30=90" 不会有任何一条被数两次。
    closed_pool = sorted((row for row in unattested if row["kind"] in CLOSED_LOOP_KINDS),
                         key=lambda row: (row["edge_id"], row["kind"], row["value"]))
    closed_take = closed_pool[:CLOSED_LOOP_QUOTA]
    closed_ids = {(row["edge_id"], row["kind"], row["value"]) for row in closed_take}

    def key(row):
        return (row["edge_id"], row["kind"], row["value"])

    sample = [dict(row, stratum="closed_loop_kind") for row in closed_take]
    for pack in PACK_STRATA:
        pool = sorted((row for row in unattested
                       if row["type"] == pack
                       and key(row) not in closed_ids),
                      key=key)
        sample += [dict(row, stratum="pack:%s" % pack) for row in pool[:PER_PACK]]
    if len(sample) < 90:                      # 某层不够就如实补，并把补的来源标出来
        taken = {(row["edge_id"], row["kind"], row["value"]) for row in sample}
        rest = sorted((row for row in unattested
                       if key(row) not in taken), key=key)
        sample += [dict(row, stratum="rest") for row in rest[:90 - len(sample)]]

    counts = collections.Counter(row["stratum"] for row in sample)
    payload = {
        "universe": len(unattested),
        "sample": len(sample),
        "by_stratum": dict(counts),
        "closed_loop_available": len(closed_pool),
        "mechanical_pre_read": {
            "surface_in_card": sum(1 for row in sample if row["surface_in_card"]),
            "topic_mismatch": sum(
                1 for row in sample
                if not row["surface_in_card"] and row["card_topics"]
                and row["kind"] not in row["card_topics"]),
            "topic_ok_or_unknown": sum(
                1 for row in sample
                if not row["surface_in_card"]
                and (not row["card_topics"] or row["kind"] in row["card_topics"])),
        },
        "rows": sample,
    }
    out = ROOT / "work/_grounding_sample90.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8",
                   newline="\n")
    md = ["# 分层抽检 90 槽位（裁定要的样本）", "",
          "判据：**蕴含未写出 / 挂错卡 / 取错值** 三选一。",
          "`surface_in_card` 只是机械提示，**不是**分类结论。", ""]
    for index, row in enumerate(sample, start=1):
        md.append("## %d) %s ｜ %s" % (index, row["edge_id"], row["type"]))
        md.append("- 成员：`%s`（角色 %s）" % (row["value"], row["role"]))
        md.append("- 来源卡：%s（topic：%s）" % (", ".join(row["sources"]) or "（无）",
                                                 ", ".join(row["card_topics"]) or "（空）"))
        md.append("- 卡正文节选：%s" % (row["card_excerpt"] or "（取不到正文）"))
        md.append("")
    (ROOT / "work/_grounding_sample90.md").write_text("\n".join(md), encoding="utf-8",
                                                      newline="\n")
    print(json.dumps({key: value for key, value in payload.items() if key != "rows"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
