"""去标签池的**上界**随"池子怎么来 / 池子多深"怎么变？——全部离线（零判分成本）。

数据：`docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl`
（64 条固定集查询 × top-120，**逐案例** C=3 判分）＋ `work/_embed3_cache.jsonl`
（智谱 `embedding-3` 向量缓存）。

**口径**：相关＝该案例的两位评委均值 ≥ 4.0；上界＝**每条查询取最好那一组**的命中率
（`mean(max hits)/3`）。它是 **proxy**（银行标签是"连续三连"呈现下的分，
`e1_triple_search.py` 的 0.7448 是"整组重判"），**只用于方向筛选**，不是冻结读数。

用法：`python -u work/_probe_pool_ceiling.py`
"""

from __future__ import annotations

import collections
import itertools
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
DEPTHS = (3, 6, 9, 12, 20, 40)


def sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strict_score(row):
    nums = [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]
    return sum(nums) / len(nums) if len(nums) >= 2 else None


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def ceiling(pool, label_of):
    """池子的上界：枚举 C(n,3)，取最好那组。"""
    counts = [sum(1 for cid in triple if (label_of.get(cid) or -1) >= RELEVANT)
              for triple in itertools.combinations(pool, 3)]
    return (max(counts) if counts else 0), (sum(counts) / len(counts) / 3.0 if counts else None)


def main() -> int:
    bank = collections.OrderedDict()
    for row in common.read_jsonl(pathlib.Path(BANK)):
        bank.setdefault(str(row["query"]), []).append(row)

    index = load_index(pathlib.Path("knowledge"), backend="hybrid")
    titles = {str(c.case_id): str(getattr(c, "title", "") or "") for c in index.cases}

    cache = {}
    for row in common.read_jsonl(pathlib.Path(CACHE)):
        cache[str(row["sha"])] = row["vec"]
    print("cache vectors: %d" % len(cache), flush=True)

    # ---- 先验一件事：银行的文件序 == 产品检索器的前 120 吗？
    probe_query = list(bank)[0]
    shipped = [c.case_id for c in index.retrieve(probe_query, top_k=6)]
    bank_first6 = [str(r["case_id"]) for r in bank[probe_query][:6]]
    probe_match = (shipped == bank_first6)

    faces = ["excerpt", "excerpt+zh", "title+excerpt+zh"]
    rows_out, agg = [], {}
    for query, rows in bank.items():
        label_of = {str(r["case_id"]): strict_score(r) for r in rows}
        order = [str(r["case_id"]) for r in rows]
        qvec = cache.get(sha(str(query)))
        vecs = {}
        for row in rows:
            cid = str(row["case_id"])
            excerpt = str(row.get("excerpt") or "")
            zh = str(row.get("zh") or "")
            vecs[cid] = [
                cache.get(sha(excerpt)),
                cache.get(sha((excerpt + "\n" + zh).strip())),
                cache.get(sha((titles.get(cid, "") + " ｜ " + excerpt + "\n" + zh).strip())),
            ]
        entry = {"query": query, "pools": {}}
        for depth in DEPTHS:
            pools = {"retrieval_order": order[:depth],
                     "label_top": sorted(order, key=lambda c: (-(label_of[c] or 0), c))[:depth]}
            if qvec:
                for i, face in enumerate(faces):
                    usable = [c for c in order if vecs[c][i]]
                    pools["embed3:" + face] = sorted(
                        usable, key=lambda c: (-cosine(qvec, vecs[c][i]), c))[:depth]
            for name, pool in pools.items():
                best, mean = ceiling(pool, label_of)
                key = "%s@%d" % (name, depth)
                bucket = agg.setdefault(key, {"best": 0.0, "three": 0, "mean": 0.0, "n": 0})
                bucket["best"] += best / 3.0
                bucket["three"] += 1 if best == 3 else 0
                bucket["mean"] += mean or 0.0
                bucket["n"] += 1
                entry["pools"][key] = {"best": best, "mean": mean}
        rows_out.append(entry)

    table = []
    for key in sorted(agg, key=lambda k: (int(k.split("@")[1]), k)):
        b = agg[key]
        table.append({"pool": key,
                      "ceiling": round(b["best"] / b["n"], 4),
                      "queries_at_3of3": b["three"],
                      "mean_triple": round(b["mean"] / b["n"], 4)})
    payload = {"queries": len(rows_out), "bank": BANK,
               "bank_order_equals_shipped_top6": probe_match,
               "threshold_135_of_192": 0.703125, "table": table, "per_query": rows_out}
    pathlib.Path("work/_embed_pool_ceiling.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")

    print("bank_first6 == shipped retrieve(top_k=6): %s" % probe_match)
    print("%-34s %9s %8s %11s" % ("pool", "ceiling", "3of3", "mean/triple"))
    for row in table:
        print("%-34s %9.4f %5d/64 %11.4f" % (row["pool"], row["ceiling"],
                                             row["queries_at_3of3"], row["mean_triple"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
