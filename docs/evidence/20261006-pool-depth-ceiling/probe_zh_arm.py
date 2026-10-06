"""**中文线索单独当语义桥**：`cos(查询, 案例的 zh 线索)` 排序，交付 E1 / 上界会不会跳？

为什么值得单独试（不是重复 `embed3:excerpt+zh`）：那个面里 **excerpt 占主导**，
线索被稀释；而本仓**另有一条 `search_zh` 路线**（案例自带中文"需求"线索），
且在**路由位**上实测过"换云端嵌入器 E1 提高约 5.6 倍"（`ADJUDICATIONS_v4.md` D3）。
本探针把"线索"从面里拆出来，**单独**放在交付位/池子位上量。

口径与 `_probe_pool_ceiling.py` / `_probe_delivered_sim.py` 逐字相同（同一批银行标签、
同一把 proxy），**锚点**同样要复算：`retrieval_order@3` 必须仍是 **0.1719**。

用法：`python -u work/_probe_zh_arm.py`
"""

from __future__ import annotations

import collections
import itertools
import json
import math
import pathlib
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "work")
from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import common  # noqa: E402
import _probe_embed_pool as pe  # noqa: E402  (复用同一个带缓存的嵌入器)

BANK = "docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl"
CACHE = "work/_embed3_cache.jsonl"
RELEVANT = 4.0
DEPTHS = (6, 12, 20, 40)


def zscores(values: dict) -> dict:
    xs = list(values.values())
    if not xs:
        return {}
    mean = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))
    return {k: ((v - mean) / sd if sd else 0.0) for k, v in values.items()}


def main() -> int:
    import os
    key = os.environ.get("GLM_API_KEY", "")
    if not key:
        print(json.dumps({"error": "missing GLM_API_KEY"}, ensure_ascii=False))
        return 3
    bank = collections.OrderedDict()
    for row in common.read_jsonl(pathlib.Path(BANK)):
        bank.setdefault(str(row["query"]), []).append(row)
    index = load_index(pathlib.Path("knowledge"), backend="hybrid")
    titles = {str(c.case_id): str(getattr(c, "title", "") or "") for c in index.cases}

    embedder = pe.Embedder(CACHE, key)
    queries = list(bank)
    #: **空串不许送去编码**（智谱对空输入回 `HTTP 400`，实测）。所以只编码非空的那些，
    #: 并把"没有线索"的案例**留空向量** ⇒ 它在 `zh_only` 那一臂里**不可被排序**（如实排除，
    #: 不是给它编一个分）。
    zh_slots, zh_texts, tz_slots, tz_texts = [], [], [], []
    for query_position, query in enumerate(queries):
        for row_position, row in enumerate(bank[query]):
            zh = str(row.get("zh") or "").strip()
            if not zh:
                continue
            cid = str(row["case_id"])
            zh_slots.append((query_position, row_position))
            zh_texts.append(zh)
            tz_slots.append((query_position, row_position))
            tz_texts.append((titles.get(cid, "") + " ｜ " + zh).strip())
    qvecs = embedder.embed(queries)
    zh_vectors = embedder.embed(zh_texts) if zh_texts else []
    tz_vectors = embedder.embed(tz_texts) if tz_texts else []
    print("newly embedded: %d texts (%d zh / %d title+zh)"
          % (embedder.used, len(zh_texts), len(tz_texts)), flush=True)
    zh_by_slot = {(q, r): v for (q, r), v in zip(zh_slots, zh_vectors)}
    tz_by_slot = {(q, r): v for (q, r), v in zip(tz_slots, tz_vectors)}

    stat = collections.defaultdict(lambda: {"rel": 0, "n": 0, "best": 0.0, "3of3": 0})
    for position, query in enumerate(queries):
        rows = bank[query]
        qvec = qvecs[position]
        label, zh_cos, tz_cos, order = {}, {}, {}, []
        for offset, row in enumerate(rows):
            cid = str(row["case_id"])
            order.append(cid)
            nums = [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]
            label[cid] = sum(nums) / len(nums) if len(nums) >= 2 else None
            zh_vector = zh_by_slot.get((position, offset))
            tz_vector = tz_by_slot.get((position, offset))
            if qvec and zh_vector:
                zh_cos[cid] = pe.cosine(qvec, zh_vector)
            if qvec and tz_vector:
                tz_cos[cid] = pe.cosine(qvec, tz_vector)
        prior = {cid: -float(i) for i, cid in enumerate(order)}
        #: 混合臂：把**名次先验**与**线索余弦**各做成 z 分再平均——"最好的简单做法"长什么样。
        zh_z = zscores(zh_cos) if zh_cos else {}
        prior_z = zscores(prior)
        blend = {cid: (prior_z.get(cid, 0.0) + zh_z.get(cid, 0.0)) / 2.0
                 for cid in prior if cid in zh_z}
        for depth in DEPTHS:
            for name, table in (("retrieval_order", prior), ("zh_only", zh_cos),
                                ("title+zh", tz_cos), ("prior+zh(z)", blend)):
                if not table:
                    continue
                pool = order[:depth]
                usable = [c for c in pool if c in table]
                if len(usable) < 3:
                    continue
                top3 = sorted(usable, key=lambda c: (-table[c], c))[:3]
                hits = sum(1 for c in top3 if (label.get(c) or -1) >= RELEVANT)
                counts = [sum(1 for c in combo if (label.get(c) or -1) >= RELEVANT)
                          for combo in itertools.combinations(usable, 3)]
                bucket = stat[(name, depth)]
                bucket["rel"] += hits
                bucket["n"] += 1
                bucket["best"] += (max(counts) / 3.0) if counts else 0.0
                bucket["3of3"] += 1 if max(counts) == 3 else 0
    table = []
    for (name, depth) in sorted(stat, key=lambda k: (k[1], k[0])):
        b = stat[(name, depth)]
        table.append({"arm": name, "pool_depth": depth,
                      "delivered_E1_proxy": round(b["rel"] / b["n"] / 3.0, 4),
                      "ceiling_proxy": round(b["best"] / b["n"], 4),
                      "queries_at_3of3": b["3of3"]})
    anchor = [r for r in table if r["arm"] == "retrieval_order" and r["pool_depth"] == 6]
    payload = {"queries": len(queries), "table": table,
               "anchor_delivered_at_depth6": anchor[0]["delivered_E1_proxy"] if anchor else None}
    pathlib.Path("work/_zh_arm.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print("%-18s %6s %12s %10s %8s" % ("arm", "depth", "deliveredE1", "ceiling", "3of3"))
    for row in table:
        print("%-18s %6d %12.4f %10.4f %5d/64" % (row["arm"], row["pool_depth"],
                                                  row["delivered_E1_proxy"],
                                                  row["ceiling_proxy"], row["queries_at_3of3"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
