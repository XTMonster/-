"""卡片是否落在**工具声明的知识范围**内（§2.3b 的 L1/L2 定义）。

## 为什么需要它

§4.1b 的来源覆盖门写的是「**每张入库卡（L1/L2）**至少派生 1 条」。`L1/L2` 不是
装饰：§2.3b 把 L1 定义成"电影/视频拍摄理论、轴线规则、构图门、运镜与景别的耦合"，
L2 是"能写成条件→取舍的经验"。**卡片是不是入库卡，取决于它的知识在不在这个范围里**。

实测（2026-10-02，词表口径修正之后门⑥ 仍缺 27 张）：这些卡的正文讲的是

* **照相/胶片化学**（`gen_cine_0077`「染色前不可放映」、`gen_cine_0078`「染色温度上限」）；
* **绘画与墨法**（`gen_comp_0262`「墨色浓黑靠少水」、`gen_comp_0273`「线描工具不宜做调子」）；
* **电气施工**（`gen_prod_0014`「同回路导线同管敷设」、`gen_prod_0022`「小规格用螺钉垫圈接线」）；

它们来自"照片冲洗手册／绘画教材／电工手册"这类**与镜头语言无关**的来源，
被域配额（K3 要求每域 ≥60 张）顺带收进了语料。既写不成超边，又会在检索里
当噪声（一次"冷光"查询可能召回"染色液配比"）。

## 判据（只判**范围**，不判质量）

`in_scope = true`：知识讲的是**镜头/场面/表演/剪辑/声音/动画生产**层面的做法或取舍
（含导演、摄影、灯光、构图、调度、分镜、声画、动作）。
`in_scope = false`：知识讲的是**别的工种或别的媒介**——照相化学/冲洗工艺、绘画与书法
技法、电气或土建施工、印刷/排版格式、以及与制作无关的泛论。
**拿不准按 in_scope=true 计**（宁可留着，也不要把片子相关的东西剔出去）。

产出 `knowledge/card_scope.json`（钉进仓库，含每条的判据与理由）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = "knowledge/card_scope.json"

SYSTEM = (
    "你是电影白模预演工具的**知识范围审查员**。这个工具只服务**镜头层面**的预演："
    "机位/镜头/运镜/景别/构图/调度/光线/剪辑节奏/声画/表演与动作/分镜与剧本的场面设计。\n"
    '逐张判断，只输出 JSON：{"decisions":[{"id":"<卡片 id>",'
    '"in_scope":true|false,"reason":"不超过 25 字","quote":"最相关的一句原文"}]}。\n'
    "in_scope=false 只有这几种：照相或胶片**化学/冲洗/染色工艺**；**绘画/书法/墨法**技法；"
    "**电气/土建施工**；**印刷排版或稿件格式**规定；与影片制作无关的泛论或史料。\n"
    "除此之外一律 true——**拿不准就判 true**（宁可不剔）。"
)


def _prompt(batch: Sequence[Dict]) -> str:
    parts = []
    for item in batch:
        parts.append("### %s（domain=%s）\n标题：%s\n内容：%s"
                     % (item["id"], item.get("domain", ""), item["title"],
                        item["content"]))
    return "\n\n".join(parts)


def classify(items: Sequence[Dict], client, *, batch_size: int = 10) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    rows = list(items)
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        try:
            reply = client.chat_json(SYSTEM, _prompt(batch), 0.0, 0, 8192)
        except Exception as exc:  # noqa: BLE001
            for item in batch:
                out[item["id"]] = {"in_scope": True, "reason":
                                   "调用失败：%s（按 in_scope 计）" % type(exc).__name__,
                                   "quote": ""}
            continue
        got = {}
        for row in reply.get("decisions") or []:
            if isinstance(row, dict) and str(row.get("id") or "").strip():
                got[str(row["id"]).strip()] = row
        for item in batch:
            row = got.get(item["id"]) or {}
            out[item["id"]] = {
                "in_scope": bool(row.get("in_scope", True)),
                "reason": str(row.get("reason") or "模型漏答，按 in_scope 计")[:80],
                "quote": str(row.get("quote") or "")[:160]}
    return out


def _cards() -> Dict[str, Dict]:
    from block_director.knowledge.corpus import CARDS

    return {str(card.id): {"id": str(card.id), "domain": str(card.domain),
                           "title": str(card.title)[:80],
                           "content": str(card.content)[:600]}
            for card in CARDS if str(card.id).startswith("gen_")}


def control_pool(cards: Sequence[str], wanted: Sequence[str],
                 covered: Sequence[str], count: int,
                 seed: int) -> List[str]:
    """对照组：抽 `count` 张**既有条目、又没被点名**的卡一起判。

    它的作用是证明判据不是橡皮章——这些卡已经派生出条目（说明检索侧认为它们在
    范围内），如果审查员把它们判成范围外，我们就知道"范围外"这个桶真的会开火，
    而不是随手把不想管的都塞进去。

    所以这里**必须**是 `(cards - wanted) & covered`：早先写成
    `set(cards) - set(wanted) & set(covered)`，`&` 的优先级高于 `-`，于是对照池
    变成了"几乎全部卡片"（含大量没有条目的卡），对照组就不再是对照组了。
    """
    if count <= 0:
        return []
    import random

    pool = sorted((set(cards) - set(wanted)) & set(covered))
    random.Random(seed).shuffle(pool)
    return pool[:count]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.card_scope_audit")
    parser.add_argument("--only", default="",
                        help="只判这些 id（`@文件`，每行一个）；留空判全部生成卡")
    parser.add_argument("--control", type=int, default=0,
                        help="另外随机抽 N 张**已覆盖**的卡一起判（对照组：证明判据不是橡皮章）")
    parser.add_argument("--covered-from", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261002)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args(list(argv) if argv is not None else None)

    from tools.kb_fetch import llm

    cards = _cards()
    wanted: List[str] = []
    spec = str(args.only or "")
    if spec.startswith("@"):
        wanted = [line.strip() for line in
                  pathlib.Path(spec[1:]).read_text(encoding="utf-8").split("\n")
                  if line.strip()]
    elif spec:
        wanted = [item.strip() for item in spec.split(",") if item.strip()]
    if not wanted:
        wanted = sorted(cards)
    if args.control:
        covered = {str(json.loads(line).get("from_card")) for line in
                   (ROOT / args.covered_from).read_text(encoding="utf-8").split("\n")
                   if line.strip()}
        wanted = wanted + control_pool(sorted(cards), wanted, sorted(covered),
                                       args.control, args.seed)

    items = [cards[ident] for ident in wanted if ident in cards]
    report = {"criterion": SYSTEM, "cards": len(items)}
    if items:
        client = llm.make_client(args.provider, args.model)
        decisions = classify(items, client, batch_size=args.batch_size)
        report["decisions"] = decisions
        report["out_of_scope"] = sorted(k for k, v in decisions.items()
                                        if not v["in_scope"])
        report["out_of_scope_count"] = len(report["out_of_scope"])
    target = ROOT / args.out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k != "decisions"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
