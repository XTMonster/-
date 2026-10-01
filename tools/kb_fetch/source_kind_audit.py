"""把"知识形态"判到每张卡上，并把结论写进原子边的 `source_kind`（§2.3b 的 L2）。

## 为什么需要它

§2.3b 的用户裁决把三层栈的切分标准定成**知识的形态**，不是来源：
L2 结构化经验层 = "能写成**条件 → 取舍**"的那部分（`24mm 拍饭桌显脏`＝镜头×场景×结果）。
抽取器**本来**就该写 `source_kind=experience`，但实测 738 条边里 **0 条**是 experience：
提示给每张卡塞了一句假的"来源性质：theory"（1981 张生成卡**全部**没有这个字段，
于是 `card.get('source_kind','theory')` 恒为 theory）。后果是
`E3 经验越权率` 的分母为 0 —— 按 §4.1b 硬规则 1 直接判**失败**。

## 判据（与提示里的规则 5 逐字同源）

* `tradeoff`：卡里给的是**带条件的实践取舍**——某具体条件下优先什么、避开什么、
  换来什么结果，常带实践口吻（实测/一般来说/在…时/会显得/别用）；
* `constraint`：普遍适用的规则、结论、定义。

判据是**形态**，与作者是谁无关（§2.3b 的裁决就是这么定的），所以这里按卡判一次，
再落到它的原子边上：

* `tradeoff` ＋ 无 `forbid` → `experience` ＋ `soft`
* `tradeoff` ＋ 有 `forbid` → `lesson` ＋ `soft`（§2.3b 关键纪律 1：只有 lesson/theory
  允许带 forbid，经验不得越权）
* 其余 → `theory` ＋ `hard`
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

DEFAULT_ATOMS = "work/hypergraph.atoms.jsonl"

SYSTEM = (
    "你是知识卡的分类员。逐张判断这张卡的**知识形态**，只输出 JSON："
    '{"decisions":[{"id":"<卡片 id>","form":"constraint|tradeoff",'
    '"quote":"最相关的一句原文","reason":"不超过 20 字"}]}，每张卡一条，不要遗漏。\n'
    "constraint（普遍约束）= 普遍适用的规则/结论/定义。\n"
    "tradeoff（条件→取舍）= 明确带条件的实践取舍：某个具体条件（镜头/光位/景别/情绪/"
    "场景/成本/人员）下**优先什么、避开什么、换来什么结果**，常带实践口吻。\n"
    "判的是**写法**，不是作者是谁；拿不准按 constraint 计（宁缺勿滥）。"
)


def claims(atoms_path: pathlib.Path) -> Dict[str, Dict]:
    """有原子边的卡 → 待判的卡片正文（用卡片自己的 title＋content）。"""
    from block_director.knowledge.corpus import CARDS

    by_id = {str(card.id): card for card in CARDS}
    wanted: Dict[str, Dict] = {}
    for line in atoms_path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        for source in json.loads(line).get("sources") or ():
            card = by_id.get(str(source))
            if card is not None:
                wanted[str(source)] = {
                    "id": str(source),
                    "title": str(getattr(card, "title", ""))[:80],
                    "content": str(getattr(card, "content", ""))[:700]}
    return wanted


def _prompt(batch: Sequence[Dict]) -> str:
    parts = []
    for item in batch:
        parts.append("### %s\n标题：%s\n内容：%s"
                     % (item["id"], item["title"], item["content"]))
    return "\n\n".join(parts)


def classify(items: Sequence[Dict], client, *, batch_size: int = 10) -> Dict[str, Dict]:
    decisions: Dict[str, Dict] = {}
    rows = list(items)
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        try:
            reply = client.chat_json(SYSTEM, _prompt(batch), 0.0, 0, 8192)
        except Exception as exc:  # noqa: BLE001
            for item in batch:
                decisions[item["id"]] = {"form": "constraint", "quote": "",
                                         "reason": "调用失败：%s" % type(exc).__name__}
            continue
        got = {}
        for row in reply.get("decisions") or []:
            if isinstance(row, dict) and str(row.get("id") or "").strip():
                got[str(row["id"]).strip()] = row
        for item in batch:
            row = got.get(item["id"])
            form = str((row or {}).get("form") or "").strip().lower()
            if form not in ("constraint", "tradeoff"):
                decisions[item["id"]] = {"form": "constraint", "quote": "",
                                         "reason": "模型漏答/取值非法，按 constraint 计"}
                continue
            decisions[item["id"]] = {
                "form": form, "quote": str(row.get("quote") or "")[:200],
                "reason": str(row.get("reason") or "")[:80]}
    return decisions


def apply(atoms_path: pathlib.Path, decisions: Dict[str, Dict]) -> Dict:
    """按卡片的形态重写原子边的 `source_kind` / `hardness`（逐卡，不逐边）。"""
    rows = [json.loads(line) for line in
            atoms_path.read_text(encoding="utf-8").split("\n") if line.strip()]
    changed = {"experience": 0, "lesson": 0, "theory": 0}
    out = []
    for row in rows:
        sources = [str(source) for source in (row.get("sources") or ())]
        forms = {(decisions.get(source) or {}).get("form") for source in sources}
        tradeoff = "tradeoff" in forms
        has_forbid = any(member[0] == "forbid" for member in row.get("members") or [])
        if tradeoff and has_forbid:
            kind, hardness = "lesson", "soft"
        elif tradeoff:
            kind, hardness = "experience", "soft"
        else:
            kind, hardness = "theory", "hard"
        changed[kind] += 1
        out.append(dict(row, source_kind=kind, hardness=hardness))
    atoms_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n"
                                  for item in out),
                          encoding="utf-8", newline="\n")
    return {"atoms": len(out), "by_kind": changed}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.source_kind_audit")
    parser.add_argument("--atoms", default=DEFAULT_ATOMS)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--out", default="work/source_kind_audit.json")
    parser.add_argument("--apply", action="store_true",
                        help="把形态写进原子边（之后要跑 --rematch）")
    parser.add_argument("--from-report", default="",
                        help="不复审，直接用这份已有报告执行 `--apply`")
    args = parser.parse_args(list(argv) if argv is not None else None)

    atoms_path = ROOT / args.atoms
    if args.from_report:
        report = json.loads((ROOT / args.from_report).read_text(encoding="utf-8"))
        decisions = report["decisions"]
    else:
        from tools.kb_fetch import llm

        items = list(claims(atoms_path).values())
        client = llm.make_client(args.provider, args.model)
        decisions = classify(items, client, batch_size=args.batch_size)
    tradeoffs = sorted(key for key, row in decisions.items() if row["form"] == "tradeoff")
    result = {"cards": len(decisions), "tradeoff": len(tradeoffs),
              "constraint": len(decisions) - len(tradeoffs), "decisions": decisions}
    if args.apply:
        result["apply"] = apply(atoms_path, decisions)
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                      encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k != "decisions"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
