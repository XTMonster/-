"""**去标签**的候选生成：把池子从"检索原序前 6"换成"云端嵌入重排前 6"，proxy 上界会动多少？

要回答的问题（`docs/knowledge/E1_LEVERS_v1.md` / `OPEN_PROBLEMS.md` P3）：

* E1 的过关线是 **135/192 = 0.703125**，而它的依据是"**标签池**的 oracle 0.7448"。
* 选择器**不许看判分** ⇒ 它只能用**去标签池**；去标签池的 oracle 实测只有 **0.375**
  （8 条试点，`work/_labelfree_pool.out`）⇒ 那条门槛**可能够不着**。
* 台账把"更好的候选生成（云端嵌入重排）"列为**唯一未被证伪的正向杠杆**
  （`OPEN_PROBLEMS.md` P3：本地 bge 重排是负结果，但智谱 `embedding-3` 没在**重排位**试过）。

本探针**不花一分判分**：`docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl`
里已有 **64 条查询 × top-120** 的**逐案例** C=3 判分（7,679 行），所以任何"在同一个 top-120 里
重排"的池子都可以**离线**量它的 proxy 上界。

**口径（必须读）**：本探针报的是 **proxy**——相关＝该案例在银行里的分数 ≥ 4.0。
它不是冻结仪器：`e1_triple_search.py` 的 0.7448 是**整组三条重判**得到的，而银行标签是
**另一种呈现**下的分。两者**不许互相引用**，这里只用它做**方向性筛选**：
嵌入重排**有没有**把池子推向标签池？没有就该如实否掉这条杠杆；有才值得花 1h50m 去真判。

用法：

```powershell
$env:GLM_API_KEY=(Get-ItemProperty 'HKCU:\\Environment' -Name GLM_API_KEY).GLM_API_KEY
python -u work/_probe_embed_pool.py --limit 64
```
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import math
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import common  # noqa: E402

BANK = "docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl"
CACHE = "work/_embed3_cache.jsonl"
ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/embeddings"
RELEVANT = 4.0


# --------------------------------------------------------------------------- 数据
def load_bank(path: str) -> "collections.OrderedDict[str, list]":
    grouped: "collections.OrderedDict[str, list]" = collections.OrderedDict()
    for row in common.read_jsonl(pathlib.Path(path)):
        grouped.setdefault(str(row["query"]), []).append(row)
    return grouped


def strict_score(row) -> float | None:
    """两位评委都有分才算（P14-249），与银行里的 `score` 字段同义。"""
    nums = [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]
    return sum(nums) / len(nums) if len(nums) >= 2 else None


def case_texts(index) -> dict:
    return {str(c.case_id): {"title": str(getattr(c, "title", "") or ""),
                             "excerpt": str(getattr(c, "excerpt", "") or "")}
            for c in index.cases}


# --------------------------------------------------------------------------- 嵌入
class Embedder:
    """智谱 `embedding-3`，**带磁盘缓存**（key 只从环境变量读）。"""

    def __init__(self, cache: str, key: str, model: str = "embedding-3", batch: int = 32):
        self.path = pathlib.Path(cache)
        self.key = key
        self.model = model
        self.batch = int(batch)
        self.store: dict = {}
        self.used = 0
        if self.path.exists():
            for row in common.read_jsonl(self.path):
                self.store[str(row["sha"])] = row["vec"]

    @staticmethod
    def sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _call(self, texts: list) -> list:
        body = json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - 固定 https 端点
            ENDPOINT, data=body, method="POST",
            headers={"Authorization": "Bearer " + self.key,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        vecs = [item.get("embedding") for item in payload.get("data") or []]
        if len(vecs) != len(texts) or any(v is None for v in vecs):
            raise RuntimeError("云端嵌入回包缺向量：%d/%d" % (len(vecs), len(texts)))
        return vecs

    def embed(self, texts: list) -> list:
        """返回与 `texts` 同序的向量；缓存命中不联网。"""
        out: list = [None] * len(texts)
        todo, seen = [], {}
        for i, text in enumerate(texts):
            sha = self.sha(text)
            if sha in self.store:
                out[i] = self.store[sha]
            elif sha not in seen:
                seen[sha] = [i]
                todo.append(text)
            else:
                seen[sha].append(i)
        for start in range(0, len(todo), self.batch):
            chunk = todo[start:start + self.batch]
            for attempt in range(4):
                try:
                    vecs = self._call(chunk)
                    break
                except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                    if attempt == 3:
                        raise
                    print("  embed retry %d: %s" % (attempt + 1, str(exc)[:120]), flush=True)
                    time.sleep(2.0 * (attempt + 1))
            self.used += len(chunk)
            for text, vec in zip(chunk, vecs):
                self.store[self.sha(text)] = vec
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                for text, vec in zip(chunk, vecs):
                    handle.write(json.dumps({"sha": self.sha(text), "vec": vec},
                                            ensure_ascii=False) + "\n")
        #: `seen` 是 **sha -> 位置**（不是文本 -> 位置），所以这里直接取 sha。
        for sha, positions in seen.items():
            vec = self.store[sha]
            for i in positions:
                out[i] = vec
        return out


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------------------- 池子与 proxy
def proxy_of(pool_ids, label_of: dict) -> dict:
    """池子的 proxy：枚举 C(n,3)，按逐案例标签数命中。"""
    triples = list(itertools.combinations(pool_ids, 3))
    counts = [sum(1 for cid in triple if (label_of.get(cid) or -1) >= RELEVANT)
              for triple in triples]
    best = max(counts) if counts else 0
    return {
        "triples": len(triples),
        "oracle": sum(counts) / len(counts) / 3.0 if counts else None,
        "best": best,
        "first_triple": counts[0] / 3.0 if counts else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default=BANK)
    ap.add_argument("--limit", type=int, default=64)
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--cases", default="knowledge")
    ap.add_argument("--pool", type=int, default=6)
    ap.add_argument("--out", default="work/_embed_pool_probe.json")
    args = ap.parse_args(argv)

    key = os.environ.get("GLM_API_KEY", "")
    if not key:
        print(json.dumps({"error": "missing GLM_API_KEY"}, ensure_ascii=False))
        return 3

    bank = load_bank(args.bank)
    queries = list(bank)[:args.limit]
    index = load_index(pathlib.Path(args.cases), backend="hybrid")
    texts = case_texts(index)
    embedder = Embedder(args.cache, key)

    # ---- 一次把所有要编码的文本收集起来（查询 + 每条的三种文本面）
    query_texts: list = []
    case_texts_all: list = []
    for query in queries:
        query_texts.append(str(query))
        for row in bank[query]:
            cid = str(row["case_id"])
            title = texts.get(cid, {}).get("title", "")
            excerpt = str(row.get("excerpt") or texts.get(cid, {}).get("excerpt", ""))
            zh = str(row.get("zh") or "")
            case_texts_all.append(excerpt)
            case_texts_all.append((excerpt + "\n" + zh).strip())
            case_texts_all.append((title + " ｜ " + excerpt + "\n" + zh).strip())
    print("unique texts to embed: %d (+%d queries)"
          % (len({t for t in case_texts_all}), len(set(query_texts))), flush=True)
    qvecs = embedder.embed(query_texts)
    cvecs = embedder.embed(case_texts_all)
    print("embedding calls made: %d texts" % embedder.used, flush=True)

    # ---- 逐查询：几种池子
    faces = ["excerpt", "excerpt+zh", "title+excerpt+zh"]
    report = []
    cursor_q, cursor_c = 0, 0
    for query in queries:
        rows = bank[query]
        qvec = qvecs[cursor_q]
        cursor_q += 1
        vecs = {}
        for row in rows:
            vecs[str(row["case_id"])] = cvecs[cursor_c:cursor_c + 3]
            cursor_c += 3
        label_of = {str(r["case_id"]): strict_score(r) for r in rows}
        order = [str(r["case_id"]) for r in rows]

        pools = {"retrieval_order": order[:args.pool]}
        by_label = sorted(order, key=lambda cid: (-(label_of[cid] or 0), cid))
        pools["label_top"] = by_label[:args.pool]          # 阳性对照：应接近 1.0
        for face_index, face in enumerate(faces):
            scored = sorted(order, key=lambda cid: (-cosine(qvec, vecs[cid][face_index]), cid))
            pools["embed3:" + face] = scored[:args.pool]

        entry = {"query": query, "pools": {}}
        for name, pool in pools.items():
            metrics = proxy_of(pool, label_of)
            metrics["overlap_with_label_top"] = len(set(pool) & set(pools["label_top"]))
            entry["pools"][name] = metrics
        report.append(entry)

    summary = {}
    for name in report[0]["pools"]:
        summary[name] = {
            "proxy_oracle": round(sum(e["pools"][name]["oracle"] for e in report) / len(report), 4),
            "queries_at_3of3": sum(1 for e in report if e["pools"][name]["best"] == 3),
            "first_triple": round(
                sum(e["pools"][name]["first_triple"] for e in report) / len(report), 4),
            "mean_overlap_with_label_top": round(
                sum(e["pools"][name]["overlap_with_label_top"] for e in report) / len(report), 2),
        }
    payload = {"queries": len(report), "pool": args.pool, "bank": args.bank,
               "summary": summary, "per_query": report}
    pathlib.Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                      encoding="utf-8", newline="\n")
    print(json.dumps({"queries": len(report), "pool": args.pool, "summary": summary},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
