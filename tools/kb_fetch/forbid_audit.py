"""`forbid` 成员的**理据审计**：来源卡里到底有没有写"不要这个"。

## 为什么要有它

v10 给抽取提示加了规则 8d：`forbid_<kind>=取值` **只在卡里明确写"不要／避免／
切忌…"时才写**。实测它把 `forbid` 成员从 101 降到 28（`b8ce136`），但**没有清干净**：

* 双模型复核（`tools/holdout_review_llm.py`）对 62 条 Q7 期望判定，
  **两模型一致否决 45 条**，理由几乎都指向同一件事——"卡里没说这个禁忌"；
* 具体样本：`cine_move_and_axis`（讲运镜会换轴侧、硬切换侧禁止）被抽出了
  `forbid_movement=固定`。那张卡**从头到尾没有提到固定机位**，"硬切"也不是运镜取值。

## 为什么不能用字面判据

`tools/holdout_pool.grounded_conflict_pairs` 用的是"取值／别名出现在卡里 ＋ 有否定词"。
它对**同义表述**无能为力：模型判定的 28 条里有 27 条过不了字面判据
（卡里写的是"禁忌：……"配一个别名，或者英文表述）。所以理据判断交给模型，
**但判据只问一件事**：这张卡有没有说"不要 / 避免 / 禁止 <这个取值>"。
每个成员一条记录，带原文引证（`quote`）——人可以抽查，机器可以复核。

产出 `work/forbid_audit.json`：`kept` / `ungrounded`（含理由与引证）。
`--apply` 会把**没有理据**的 forbid 成员从原子边里摘掉（并如实记账），
之后由调用方跑 `--rematch` 重建索引——那是索引换代，oracle 必须跟着重标。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.holdout_score import load_graph  # noqa: E402

DEFAULT_NODES = "knowledge/hypergraph.nodes.jsonl"
DEFAULT_EDGES = "knowledge/hypergraph.edges.jsonl"
DEFAULT_ATOMS = "work/hypergraph.atoms.jsonl"

SYSTEM = (
    "你是分镜知识库的**审计员**。给你一张来源卡片的正文，和一条由它抽出来的"
    "「禁忌」主张。只回答一个问题：**这张卡有没有说「不要／避免／禁止」这个取值**？\n"
    "算有依据（grounded=true）的情形：卡里直接写了「禁忌：…」／「不要…」／「避免…」／"
    "「绝不可…」并且指向的就是这个取值（同义说法也算，例如卡写「别用固定机位」、"
    "主张是 forbid movement=固定）。\n"
    "不算（grounded=false）的情形：卡里只是**提到**这个概念、讲它的用法、"
    "或者讲的是**另一件事**的禁忌（例如卡说「硬切换侧禁止」、主张却是"
    "forbid movement=固定）。**拿不准一律 grounded=false**。\n"
    '只输出 JSON：{"grounded": true|false, "quote": "卡里最相关的一句原文，没有就空串", '
    '"reason": "不超过 30 字"}。'
)


def _prompt(card_text: str, claim: str) -> str:
    return "【来源卡正文】\n%s\n\n【禁忌主张】%s" % (card_text[:1500], claim)


def claims(graph, cards_by_id: Dict[str, str]) -> List[Dict]:
    """索引里每一条 `forbid` 成员 → 一条待审计的主张（边 ＋ 来源卡）。"""
    out: List[Dict] = []
    for edge in graph.edges:
        forbids = [(m.kind, str(m.node_id).split(":", 1)[-1])
                   for m in edge.members if m.role == "forbid"]
        if not forbids:
            continue
        sources = [str(s) for s in (edge.sources or ()) if str(s) in cards_by_id]
        for kind, value in forbids:
            for card in sources:
                out.append({"edge_id": edge.edge_id, "type": edge.type,
                            "card": card, "kind": kind, "value": value,
                            "claim": "forbid %s=%s" % (kind, value)})
    return out


def judge(client, item: Dict, card_text: str) -> Dict:
    try:
        reply = client.chat_json(SYSTEM, _prompt(card_text, item["claim"]),
                                 0.0, 0, 8192)
    except Exception as exc:  # noqa: BLE001
        return {"grounded": None, "quote": "", "reason": "%s: %s" % (type(exc).__name__, exc),
                "error": True}
    return {"grounded": bool(reply.get("grounded")),
            "quote": str(reply.get("quote") or "")[:200],
            "reason": str(reply.get("reason") or "")[:80]}


def audit(items: Sequence[Dict], cards_by_id: Dict[str, str], client) -> Dict:
    kept: List[Dict] = []
    ungrounded: List[Dict] = []
    errors: List[Dict] = []
    for item in items:
        verdict = judge(client, item, cards_by_id.get(item["card"], ""))
        row = dict(item, **verdict)
        if verdict.get("error"):
            errors.append(row)
        elif verdict["grounded"]:
            kept.append(row)
        else:
            ungrounded.append(row)
    # 一条 (edge, kind, value) 只有在**所有**来源卡都说不清时才算无理据：
    # 一张卡写了禁忌，这条主张对这个来源就是成立的。
    by_claim: Dict[Tuple[str, str, str], List[Dict]] = {}
    for row in kept + ungrounded + errors:
        by_claim.setdefault((row["edge_id"], row["kind"], row["value"]), []).append(row)
    survived = sorted(key for key, rows in by_claim.items()
                      if any(r.get("grounded") for r in rows))
    return {"claims": len(items), "kept": kept, "ungrounded": ungrounded,
            "errors": errors,
            "grounded_edges": sorted({key[0] for key in survived}),
            "ungrounded_edges": sorted({row["edge_id"] for row in ungrounded
                                        if row["edge_id"] not in {key[0] for key in survived}})}


def apply(atoms_path: pathlib.Path, report: Dict) -> Dict:
    """把**没有理据**的 forbid 成员从原子边里摘掉。

    只动 `role == "forbid"` 的成员，不动 allow/qualifier：这不是"改判据"，
    是把抽取器违反自己规则 8d 写进来的东西去掉。摘掉之后必填槽位可能填不满——
    那一档由 `to_edge` 的同一套规则处理（各边类型的必填槽位都不含 forbid 成员），
    所以不会产生"非法边"。

    **按卡匹配，不按 edge_id 匹配**（第一版就是栽在这里）：审计读的是**归并后**的
    超边，而归并边只沿用**其中一个**原子边的 `edge_id`。按 edge_id 摘，只会摘掉那
    一张卡的原子边，同组其它卡的原子边会把它**带回来**（实测：审出 42 条没依据，
    重归并后还剩 11 条）。按 `(来源卡, kind, 取值)` 摘才是对的——判据本来就是
    "这张卡有没有说"，一张卡说了就不该被另一张卡连累。
    """
    # 一条 (edge, kind, value) 只有在**所有**来源卡都说不清时才摘：一张卡写了禁忌，
    # 这条主张对这个来源就是成立的。
    def _grounded_anywhere(edge_id, kind, value) -> bool:
        return any(other.get("grounded") for other in
                   report["kept"] + report["ungrounded"] + report["errors"]
                   if (other["edge_id"], other["kind"], other["value"])
                   == (edge_id, kind, value))

    drop = {(str(row["card"]), row["kind"], row["value"]) for row in report["ungrounded"]
            if not _grounded_anywhere(row["edge_id"], row["kind"], row["value"])}

    rows = [json.loads(line) for line in
            atoms_path.read_text(encoding="utf-8").split("\n") if line.strip()]
    changed = 0
    out = []
    for row in rows:
        sources = {str(source) for source in (row.get("sources") or ())}
        members = []
        for member in row.get("members") or []:
            role, kind, node_id = (list(member) + ["", "", ""])[:3]
            value = str(node_id).split(":", 1)[-1]
            if role == "forbid" and any((card, kind, value) in drop for card in sources):
                changed += 1
                continue
            members.append(member)
        out.append(dict(row, members=members))
    atoms_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in out),
                          encoding="utf-8", newline="\n")
    return {"atoms": len(out), "members_dropped": changed,
            "claims_without_evidence": len(drop)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.forbid_audit")
    parser.add_argument("--nodes", default=DEFAULT_NODES)
    parser.add_argument("--edges", default=DEFAULT_EDGES)
    parser.add_argument("--atoms", default=DEFAULT_ATOMS)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--out", default="work/forbid_audit.json")
    parser.add_argument("--apply", action="store_true",
                        help="把没有理据的 forbid 成员从原子边里摘掉（之后要跑 --rematch）")
    parser.add_argument("--from-report", default="",
                        help="不复审，直接用这份已有报告执行 `--apply`。"
                             "审计是模型调用、两次跑会有抖动；**审计与执行必须用同一份结果**，"
                             "否则「我审的」和「我摘的」就不是一回事。")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from block_director.knowledge.corpus import CARDS
    from tools.kb_fetch import llm

    graph = load_graph(ROOT / args.nodes, ROOT / args.edges)
    cards_by_id = {str(card.id): (str(card.title or "") + " " + str(card.content or ""))
                   for card in CARDS}
    if args.from_report:
        report = json.loads((ROOT / args.from_report).read_text(encoding="utf-8"))["detail"]
    else:
        items = claims(graph, cards_by_id)
        client = llm.make_client(args.provider, args.model)
        report = audit(items, cards_by_id, client)
    result = {"claims": report["claims"],
              "grounded": len(report["kept"]),
              "ungrounded": len(report["ungrounded"]),
              "errors": len(report["errors"]),
              "ungrounded_edges": report["ungrounded_edges"],
              "detail": report}
    if args.apply:
        result["apply"] = apply(ROOT / args.atoms, report)
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                      encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k != "detail"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
