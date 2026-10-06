"""**交付形状**的离线估计器：池深 × 选择器 → 交付 E1（proxy），零判分成本。

为什么可信（锚点）：`retrieval_order` 的 top-3（＝产品交付形状）在这批银行标签上算出
**0.1719**，而链上认证版 E1 是 **0.1771** —— **差 0.005**。
⇒ 在"**交付的那 3 条**"这个形状上，逐案例标签与整组判分是同一回事，
因此这张表可以**离线**筛选"换选择器 / 挖深池子"这两个动作，而不必先花 1h50m。

**它不是判据**：银行标签只覆盖 top-120，而且是 C=3 呈现下的分；
真正过关仍然走冻结仪器 + 预登记 + 同两位评委。

用法：`python -u work/_probe_delivered_sim.py`
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import pathlib
import sys

sys.path.insert(0, ".")
from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import common  # noqa: E402

BANK = "docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl"
CACHE = "work/_embed3_cache.jsonl"
RELEVANT = 4.0
DEPTHS = (3, 6, 12, 20, 40, 120)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strict_score(row):
    nums = [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]
    return sum(nums) / len(nums) if len(nums) >= 2 else None


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def zscores(values: dict) -> dict:
    xs = list(values.values())
    if not xs:
        return {}
    mean = sum(xs) / len(xs)
    var = sum((x - mean) ** 2 for x in xs) / len(xs)
    sd = math.sqrt(var)
    return {k: ((v - mean) / sd if sd else 0.0) for k, v in values.items()}


def main() -> int:
    bank = collections.OrderedDict()
    for row in common.read_jsonl(pathlib.Path(BANK)):
        bank.setdefault(str(row["query"]), []).append(row)
    index = load_index(pathlib.Path("knowledge"), backend="hybrid")
    titles = {str(c.case_id): str(getattr(c, "title", "") or "") for c in index.cases}
    cache = {str(r["sha"]): r["vec"] for r in common.read_jsonl(pathlib.Path(CACHE))}

    stats = collections.defaultdict(lambda: {"rel": 0, "rows": 0, "3of3": 0})
    for query, rows in bank.items():
        label = {str(r["case_id"]): strict_score(r) for r in rows}
        order = [str(r["case_id"]) for r in rows]
        qvec = cache.get(sha(str(query)))
        cos_ex, cos_exzh, cos_full = {}, {}, {}
        clue_len, has_clue = {}, {}
        for position, row in enumerate(rows):
            cid = str(row["case_id"])
            excerpt = str(row.get("excerpt") or "")
            zh = str(row.get("zh") or "")
            if qvec:
                for table, text in ((cos_ex, excerpt),
                                    (cos_exzh, (excerpt + "\n" + zh).strip()),
                                    (cos_full, (titles.get(cid, "") + " ｜ " + excerpt
                                                + "\n" + zh).strip())):
                    vec = cache.get(sha(text))
                    if vec:
                        table[cid] = cosine(qvec, vec)
            clue_len[cid] = float(len(zh))
            has_clue[cid] = 1.0 if zh.strip() else 0.0
        prior = {cid: -float(position) for position, cid in enumerate(order)}
        blended = {}
        for cid in order:
            blended[cid] = (zscores(prior).get(cid, 0.0)
                            + zscores(cos_full).get(cid, 0.0)) / 2.0
        scorers = {"retrieval_order": prior, "embed3:excerpt": cos_ex,
                   "embed3:excerpt+zh": cos_exzh, "embed3:title+excerpt+zh": cos_full,
                   "clue_len": clue_len, "has_clue": has_clue,
                   "prior+embed3(z)": blended}
        for depth in DEPTHS:
            pool = order[:depth]
            for name, table in scorers.items():
                if not table:
                    continue
                usable = [cid for cid in pool if cid in table]
                if len(usable) < 3:
                    continue
                top3 = sorted(usable, key=lambda cid: (-table[cid], cid))[:3]
                hits = sum(1 for cid in top3 if (label.get(cid) or -1) >= RELEVANT)
                bucket = stats[(name, depth)]
                bucket["rel"] += hits
                bucket["rows"] += 1
                bucket["3of3"] += 1 if hits == 3 else 0
    table = []
    for (name, depth) in sorted(stats, key=lambda k: (k[1], k[0])):
        bucket = stats[(name, depth)]
        table.append({"scorer": name, "pool_depth": depth,
                      "delivered_E1_proxy": round(bucket["rel"] / bucket["rows"] / 3.0, 4),
                      "queries_at_3of3": bucket["3of3"]})
    payload = {"queries": len(bank), "threshold": 0.703125,
               "anchor_official_delivered": 0.1771,
               "anchor_proxy_retrieval_top3": round(
                   stats[("retrieval_order", 3)]["rel"] / stats[("retrieval_order", 3)]["rows"] / 3.0, 4),
               "table": table}
    pathlib.Path("work/_delivered_sim.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print("anchor: proxy(retrieval_order@3) = %.4f  vs 官方 %.4f"
          % (payload["anchor_proxy_retrieval_top3"], payload["anchor_official_delivered"]))
    print("%-24s %6s %10s %7s" % ("scorer", "depth", "E1(proxy)", "3of3"))
    for row in table:
        print("%-24s %6d %10.4f %5d/64" % (row["scorer"], row["pool_depth"],
                                           row["delivered_E1_proxy"], row["queries_at_3of3"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
