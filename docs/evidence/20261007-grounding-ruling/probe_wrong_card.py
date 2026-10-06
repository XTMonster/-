"""那 33 条判不了的边：**是不是挂错了卡？**（裁决要的机械判据）

裁决（`docs/evidence/20261007-grounding-ruling/`，两角色一致）："无论占比如何，立即逐条处置
33 条闭环边：**能在主题相符卡找到 surface 则换卡挂接，否则删边并记删除日志**"。

本探针给"主题相符"一个**机械**定义（不靠人看）：
① 该成员取值出现在**某张来源卡的正文**里（surface 命中）⇒ `in_card_text`；
② 否则，来源卡里**有没有哪张的 `topic` 等于这个 kind** ⇒ `topic_matches` / `topic_mismatch`；
③ 都没有 ⇒ `no_evidence`。
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

from tools.knowledge import execution_closure_report as ecr  # noqa: E402


def load_cards() -> dict:
    out = {}
    for path in (ROOT / "knowledge/cards_generated").glob("*.yaml"):
        for block in path.read_text(encoding="utf-8").split("\n- "):
            ident = re.search(r"id:\s*([^\s]+)", block)
            if ident:
                topic = re.search(r"^\s*topic:\s*(.*)$", block, re.M)
                out[ident.group(1)] = {"text": block,
                                       "topic": (topic.group(1).strip().strip("'\"")
                                                 if topic else "")}
    return out


def main() -> int:
    cards = load_cards()
    edges = ecr.load_edges(ROOT / "knowledge/hypergraph.edges.jsonl")
    injections = ecr.injections(ROOT / "docs/evidence/20261007-real-closure/audit_log.jsonl")
    shot_map = json.loads((ROOT / "work/_real_closure/export/shots.json").read_text(
        encoding="utf-8"))["shots"]
    shots = {str(row["shot_id"]): row for row in shot_map}
    result = ecr.analyze(injections, edges, shots)

    #: 从诊断里把"判不了"的边捞出来（它们的成员 kind 就是那三个未纳入的）。
    blocked = collections.Counter()
    for event in injections:
        if str(event.get("shot_id") or "") not in shots:
            continue
        for edge_id in event.get("edge_ids") or []:
            edge = edges.get(str(edge_id))
            if edge is None:
                continue
            kinds = {str(m[1]) for m in (edge.get("members") or []) if len(m) == 3}
            if kinds - set(ecr.MAPPING) - set(ecr.NOT_A_CONDITION):
                blocked[str(edge_id)] += 1

    verdicts = collections.Counter()
    rows = []
    for edge_id in blocked:
        edge = edges[edge_id]
        sources = [str(item) for item in (edge.get("sources") or [])]
        for member in edge.get("members") or []:
            if len(member) != 3:
                continue
            kind = str(member[1])
            if kind not in ("headroom_policy", "composition_rule", "camera_angle"):
                continue
            value = str(member[2]).split(":", 1)[-1]
            texts = [cards.get(s, {}).get("text", "") for s in sources]
            topics = {cards.get(s, {}).get("topic", "") for s in sources}
            if any(value and value in text for text in texts):
                verdict = "in_card_text"
            elif kind in topics:
                verdict = "topic_matches"
            elif topics:
                verdict = "topic_mismatch"
            else:
                verdict = "no_evidence"
            verdicts[verdict] += 1
            rows.append({"edge_id": edge_id, "kind": kind, "value": value,
                         "sources": sources, "card_topics": sorted(topics),
                         "verdict": verdict})
    print(json.dumps({"blocked_edges": len(blocked),
                      "blocked_edge_ids": sorted(blocked),
                      "member_verdicts": dict(verdicts),
                      "samples": rows[:8],
                      "note": "机械判据：surface 命中／topic 相符／topic 不符；**不是**违规判定"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
