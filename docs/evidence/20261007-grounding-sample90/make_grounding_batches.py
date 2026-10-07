"""把 90 槽位切成 12 批（每批 8），生成给裁定通道的**逐批问题文件**。

每批问法固定：给 8 条槽位（成员取值＋来源卡 topic 并集＋**全部来源卡的正文**），
要求**只回一个 JSON 数组**，每条判 `hidden`（蕴含未写出）／`wrong_card`（挂错卡）／`wrong_value`（取错值）。

**证据与判据同源**（2026-10-07 修正）：判据 `attestation.audit()` 拼接这条边**全部来源卡**的
`card_blob` 再回查 surface；此前组题只印 `sources[0]` 一张、还截到 200 字 ⇒ 多来源的行
（39/90）只看到中位 19% 的判据文本。现在**逐卡展示**全部来源卡（空白归一），并按 `PER_ROW_BUDGET`
在卡之间分摊——**每张卡都出现**，长的按 `per_card` 截断（截断处留 `…`），并写明判据拼接总字数。
"""

from __future__ import annotations

import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SAMPLE = ROOT / "work/_grounding_sample90.json"
BATCH = 8
#: 每一条槽位在问题里给多少字的**来源卡正文**预算（在全部来源卡之间分摊，每张都出现）。
PER_ROW_BUDGET = 1600
#: 单张卡最少露多少字（卡多时摊薄，但保证每张都有正文可读）。
PER_CARD_FLOOR = 160

HEADER = """# 只做一件事：给这 {n} 条"未被佐证"的边槽位做**三分类**

背景（一句话）：这套知识索引里，**1,593 个可检槽位只有 331 个（20.78%）能在自己的来源卡正文里
找到取值本身**。现在要分清这 1,262 条"未被来源佐证"里，各有多少属于下面三类——

* `hidden`：**蕴含未写出**（卡在讲对的东西，只是没写出这个取值本身的词）——良性；
* `wrong_card`：**挂错卡**（卡的**主题**与这个取值不是一回事，比如拿"三脚架调平"的卡去挂
  `composition_rule:balance`）——腐蚀下游；
* `wrong_value`：**取错值**（卡在讲对的主题，但取值本身抄错/编错）——腐蚀下游。

**判法**：只看下面给的证据（成员取值、来源卡的 `topic` 字段、**来源卡的正文**）。
每条的"来源卡正文"就是**这条边的全部来源卡**的正文（判据也是拿它们拼起来回查的），
已按预算展示——卡多的会短一些，但每张都露了头。
拿不准就判 `hidden` 但把理由写清（宁可漏报错，不要乱扣帽子）。

**只输出一个 JSON 数组**，长度 = {n}，每条形如
`{{"i": 1, "class": "hidden"|"wrong_card"|"wrong_value", "why": "<不超过 20 字>"}}`。
不要任何额外说明。

---
"""


def card_lines(card_texts, budget=PER_ROW_BUDGET, floor=PER_CARD_FLOOR):
    """把一条边的全部来源卡正文分摊展示：每张都出现，长的按摊到的额度截断。"""
    n = max(1, len(card_texts))
    per_card = max(floor, budget // n)
    lines = []
    for card_id, text in card_texts:
        clipped = text if len(text) <= per_card else text[:per_card] + "…"
        lines.append(("  - %s：%s" % (card_id, clipped)) if text else ("  - %s：（空）" % card_id))
    return lines


def main() -> int:
    payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
    rows = payload["rows"]
    made = []
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        lines = [HEADER.format(n=len(chunk))]
        for offset, row in enumerate(chunk, start=1):
            lines.append("## %d. `%s`（边 %s，类型 %s）" % (
                offset, row["value"], row["edge_id"], row["type"]))
            lines.append("- 来源卡（%d 张）：%s"
                         % (len(row.get("card_texts") or row["sources"]),
                            ", ".join(row["sources"]) or "（无）"))
            lines.append("- 来源卡的 `topic` 字段：%s"
                         % (", ".join(row["card_topics"]) or "（空）"))
            lines.append("- 来源卡正文（判据看到的就是这些正文的拼接，共 %d 字）："
                         % row.get("judge_blob_chars", 0))
            lines.extend(card_lines(row.get("card_texts") or []))
            lines.append("")
        target = ROOT / ("work/_q_grounding_batch%d.md" % (start // BATCH + 1))
        target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        made.append((target.name, len(chunk), target.stat().st_size))
    print(json.dumps({"batches": made, "total": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
