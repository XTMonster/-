"""剩下三个"未纳入"的 kind（headroom_policy／composition_rule／camera_angle）：
它们背后的**规则原文**里到底有没有可抄的阈值/区间？（裁决 F2 的前置）

裁决原话："区间必须**逐字引自规则原文**……原文无区间者**先改知识侧**，禁校验器自造数字。"
本探针只**读**：把带这三个 kind 的边、它们的来源卡、以及卡上的原文摘录打出来。
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

KINDS = ("headroom_policy", "composition_rule", "camera_angle")
NUM = re.compile(r"\d")


def load_cards() -> dict:
    """`case_id/card_id -> 卡内容`（按 id 找得到就够）。"""
    out = {}
    for path in (ROOT / "knowledge/cards_generated").glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        for block in text.split("\n- "):
            ident = re.search(r"id:\s*([^\s]+)", block)
            if ident:
                out[ident.group(1)] = block
    return out


def main() -> int:
    cards = load_cards()
    by_kind = collections.defaultdict(list)
    for line in (ROOT / "knowledge/hypergraph.edges.jsonl").read_text(
            encoding="utf-8").split("\n"):
        line = line.strip()
        if not line:
            continue
        edge = json.loads(line)
        for member in edge.get("members") or []:
            if len(member) == 3 and str(member[1]) in KINDS:
                by_kind[str(member[1])].append((edge, member))
    for kind in KINDS:
        rows = by_kind.get(kind, [])
        print("=" * 20, kind, "共", len(rows), "个成员")
        seen = set()
        for edge, member in rows[:4]:
            for source in (edge.get("sources") or [])[:2]:
                if (kind, source) in seen:
                    continue
                seen.add((kind, source))
                card = cards.get(str(source), "")
                has_number = bool(NUM.search(card))
                print("  边 %s 取值 %s ｜ 来源卡 %s ｜ 卡里有数字: %s"
                      % (edge.get("edge_id"), member[2], source, has_number))
        values = collections.Counter(str(member[2]) for _edge, member in rows)
        print("  取值分布:", dict(values))
        #: 取**出现最多**的那个取值，把它来源卡的原文摘出来看：里面到底有没有"阈值/区间"。
        top_value = values.most_common(1)[0][0]
        for edge, member in rows:
            if str(member[2]) != top_value:
                continue
            for source in (edge.get("sources") or [])[:1]:
                card = cards.get(str(source), "")
                #: 卡是 YAML（原文常用块标量 `|-`），所以**整块摘出来**看，别硬找某个键。
                body = " ".join(line.strip() for line in card.split("\n") if line.strip())
                print("  ▼ %s 的来源卡 %s 全文（截 300）：%s"
                      % (top_value, source, body[:300]))
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
