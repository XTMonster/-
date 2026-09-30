"""双模型复核（用户裁决：Q5/Q7 这一层让 DeepSeek 与 GLM 两个模型来判）。

**这不是"人审"**——协议 §5.1/§4.1b 把 Q5／Q7／E3 的最终裁定留给**人**，理由是这三条
量的是**作者意图**，agent 没有意图。用户明确指示"这一层让 deepseek 和 glm 做"，所以本
脚本产出的记录一律写 `reviewed_by: "llm-panel"`，**绝不冒充 "human"**：

* `tools/check_holdout.py` 的门⑦ 只认 `reviewed_by == "human"`，因此它照旧判
  `not_measured`／fail——**验收标准没有被放宽**，只是多了一份**辅助证据**；
* 两个模型**都判 rejected** 的条目直接从 held-out 里剔除（提高口径质量）；
* 两个模型**分歧**的条目保留并打上 `panel_disagreement: true`，同时写进
  `--sheet` 的 markdown 清单——那份清单通常只有几十条，人可以只挑它看。

用法::

  python tools/holdout_review_llm.py --entries fixtures/knowledge_holdout.jsonl \
      --limit 150 --out work/holdout_panel.reviewed.jsonl \
      --report work/holdout_panel.json --sheet work/holdout_panel_disagreements.md

离线自测：`--scripted-a/--scripted-b` 传两份 JSON 桩，与 `tools/kb_fetch/llm.py` 的
`scripted` 后端同一套约定。
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.holdout_review import needs_human  # noqa: E402
from tools.kb_fetch import llm  # noqa: E402

PANEL_TAG = "llm-panel"
DEFAULT_PANEL = ("deepseek-chat", "glm-4.7")

SYSTEM = """你是分镜知识库 held-out 的**复核员**。给你一张知识卡和一条检索期望，
请判断这条期望是否**真的由这张卡支持**，以及它是否写得合规。只输出 JSON：
{"verdict":"accepted|rejected|amended","reason":"不超过 40 字","fix":"若 amended 给出改法，否则空串"}

判据（逐条看）：
1. `q` 的键只能用：情绪/动作/运镜/景别/镜头/节奏/特效/音效/机位/光线/构图/轴线/题材/桥段/对白/意图；
   取值必须是词表里的规范写法，`q` 与 `must` 里同 kind 的取值**逐字相同**。
2. `must` 的边类型只能是这 13 个之一（EMOTION_PACK/SHOT_PATTERN/AXIS_RULE/TROPE/
   EDIT_RHYTHM/LIGHT_PACK/ACTION_BEAT/PERFORMANCE_PACK/INTENT_PACK/IMPACT_PACK/
   STAGING_PACK/SOUND_PACK/TRANSITION_PACK），必填槽位必须写全。
3. `top1` 必须与 `must` 中某条一字不差；`never` 与 `must` 不得相交。
4. **这张卡是否真的支持这条边**？卡里没写的耦合不要硬凑——宁可 rejected。
5. `forbid_<kind>=取值` 只在 `q` 里出现同 kind 同取值时才算一次禁忌冲突；`
   expect_movements` 要符合卡里描述的作者意图。
"""


def entry_prompt(entry: Dict, card: Dict) -> str:
    return ("【知识卡】\n### %s（domain=%s）\n标题：%s\n内容：%s\n\n【待复核的检索期望】\n%s"
            % (card.get("id", entry.get("from_card")), card.get("domain", ""),
               card.get("title", ""), str(card.get("content", ""))[:600],
               json.dumps({k: v for k, v in entry.items()
                           if k in ("id", "from_card", "q", "must", "top1", "never",
                                    "expect_movements")}, ensure_ascii=False, indent=1)))


def _judge(client, entry: Dict, card: Dict) -> Dict:
    try:
        reply = client.chat_json(SYSTEM, entry_prompt(entry, card), 0.0, 0, 8192)
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "error", "reason": f"{type(exc).__name__}: {exc}"[:120], "fix": ""}
    verdict = str(reply.get("verdict") or "").strip().lower()
    if verdict not in ("accepted", "rejected", "amended"):
        return {"verdict": "error", "reason": "verdict 不在词表内", "fix": ""}
    return {"verdict": verdict, "reason": str(reply.get("reason") or "")[:200],
            "fix": str(reply.get("fix") or "")[:300]}


def merge(a: Dict, b: Dict) -> Tuple[str, Dict]:
    """两条判决 → (action, review)。action ∈ keep/drop/flag；error 一律按分歧处理。"""
    va, vb = a.get("verdict"), b.get("verdict")
    if va == vb == "accepted":
        return "keep", {"reviewed_by": PANEL_TAG, "verdict": "accepted",
                        "agreement": True, "panel": {"a": a, "b": b}}
    if va == vb == "rejected":
        return "drop", {"reviewed_by": PANEL_TAG, "verdict": "rejected",
                        "agreement": True, "panel": {"a": a, "b": b}}
    return "flag", {"reviewed_by": PANEL_TAG, "verdict": "amended", "agreement": False,
                    "needs_human": True, "panel": {"a": a, "b": b}}


def load_cards() -> Dict[str, Dict]:
    from block_director.knowledge.corpus import CARDS

    return {str(card.id): {"id": str(card.id), "domain": str(card.domain),
                           "title": card.title, "content": card.content}
            for card in CARDS}


def select(entries: Sequence[Dict], limit: int) -> List[Dict]:
    chosen = [entry for entry in sorted(entries, key=lambda e: str(e.get("id", "")))
              if needs_human(entry)]
    return chosen[:limit] if limit else chosen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_review_llm")
    parser.add_argument("--entries", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--models", default=",".join(DEFAULT_PANEL))
    parser.add_argument("--out", default="work/holdout_panel.reviewed.jsonl")
    parser.add_argument("--report", default="work/holdout_panel.json")
    parser.add_argument("--sheet", default="work/holdout_panel_disagreements.md")
    parser.add_argument("--scripted-a", default="")
    parser.add_argument("--scripted-b", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    path = pathlib.Path(args.entries)
    if not path.is_file():
        print(json.dumps({"error": f"{path} 不存在"}, ensure_ascii=False))
        return 2
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    models = [item.strip() for item in str(args.models).split(",") if item.strip()]
    if len(models) != 2 and not (args.scripted_a and args.scripted_b):
        print(json.dumps({"error": "需要两个模型（--models a,b）"}, ensure_ascii=False))
        return 2
    client_a = llm.make_client("scripted" if args.scripted_a else "deepseek",
                               models[0], args.scripted_a)
    client_b = llm.make_client("scripted" if args.scripted_b else "glm",
                               models[1], args.scripted_b)
    cards = load_cards()
    picked = select(entries, args.limit)

    reviewed: Dict[str, Dict] = {}
    dropped: List[Dict] = []
    flagged: List[Dict] = []
    counts = {"selected": len(picked), "accepted": 0, "dropped": 0, "flagged": 0}
    for entry in picked:
        card = cards.get(str(entry.get("from_card")), {})
        a = _judge(client_a, entry, card)
        b = _judge(client_b, entry, card)
        action, review = merge(a, b)
        reviewed[str(entry["id"])] = review
        if action == "drop":
            counts["dropped"] += 1
            dropped.append({"id": entry["id"], "q": entry.get("q"),
                            "reasons": {"a": a.get("reason"), "b": b.get("reason")}})
        elif action == "flag":
            counts["flagged"] += 1
            flagged.append({"id": entry["id"], "q": entry.get("q"), "must": entry.get("must"),
                            "expect_movements": entry.get("expect_movements"),
                            "a": a, "b": b})
        else:
            counts["accepted"] += 1

    kept = [dict(entry, review=reviewed[str(entry["id"])]) if str(entry["id"]) in reviewed
            else entry for entry in entries
            if str(entry["id"]) not in {str(item["id"]) for item in dropped}]
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in kept),
                        encoding="utf-8")

    sheet_path = pathlib.Path(args.sheet)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 双模型复核：分歧清单（请人只看这些）", "",
             f"- 复核条目 {counts['selected']} 条；两模型一致接受 {counts['accepted']}；"
             f"一致否决并剔除 {counts['dropped']}；**分歧 {counts['flagged']}**。",
             f"- 复核者标记为 `{PANEL_TAG}`（**不是人**）：门⑦ 只认 `reviewed_by == \"human\"`，"
             "所以它没有被这份清单满足。", ""]
    for item in flagged:
        lines += [f"## {item['id']}", "", f"查询：`{item['q']}`", "",
                  f"- A（{models[0]}）：{item['a'].get('verdict')} — {item['a'].get('reason')}",
                  f"- B（{models[1]}）：{item['b'].get('verdict')} — {item['b'].get('reason')}", ""]
    sheet_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = {"generated_at": datetime.datetime.now(
        datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "entries": str(path), "out": str(out_path), "sheet": str(sheet_path),
        "panel": {"a": models[0], "b": models[1], "tag": PANEL_TAG,
                  "prompt_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest()},
        "counts": counts, "dropped": dropped, "disagreement_ids": [i["id"] for i in flagged],
        "honesty": ("reviewed_by 写的是 llm-panel；门⑦ 需要 reviewed_by=human，"
                    "这份复核**不构成**人审，不得当作门⑦ 通过。")}
    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
