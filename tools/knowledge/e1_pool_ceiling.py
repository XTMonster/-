"""**去标签池的上界 / 交付位工作点**——全部离线，一次判分都不用花。

为什么需要这把尺子（`docs/evidence/20261006-pool-depth-ceiling/README.md`）
=========================================================================
`RK-13` 的 `E1 ≥ 0.70` 那条门是照着 **135/192 = 0.703125** 定的，而它的依据是
`0.7448`（≈143/192）—— 那个数是**在"按标签分取 top-6 再全组合"的池子上**搜出来的，
**池子本身用了判分**。裁定同时**禁止选择器看判分** ⇒ 选择器只能用**去标签池**，
而**去标签池的上界此前没人量过**。没有这把尺子，"够不够得着"只能靠猜。

它为什么**不花钱**：`docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl`
已经是 **64 条查询 × top-120 的逐案例 C=3 判分**（7,679 行）。所以**同一批 top-120 里的任何
重排/任何池深**，都可以用这批标签**离线**算它的上界与交付读数。

它**不是**什么（读之前必须知道）
===============================
* 它算的是 **proxy**：相关＝"该案例在银行里**两位评委均值** ≥ 4.0"。银行标签是
  **连续三连呈现**下采的，而 `tools/knowledge/e1_triple_search.py` 与
  `tools/knowledge/e1_labelfree_pool.py` 的读数是**整组三条重判**。两者**量纲不同、不许互相引用**。
* 锚点（本工具在**交付形状**上是准的）：`retrieval_order@3` 算出 **0.1719**，
  而链上认证版 E1 是 **0.1771** —— 差 0.005。**在交付形状上，逐案例标签与整组判分是同一回事**；
  但**重新组装的三元组**会被整组重判抬 ~0.06 / 压 ~0.21（见 README 的三个锚点）。
* 所以：**方向与量级可信，绝对值不许当读数**。要过关仍然走冻结仪器 ＋ 预登记 ＋ 同两位评委。

三种模式（默认全跑）
====================
* `order`——**承重墙**：银行文件序前 `--top-k` 是否等于产品检索器 `CaseIndex.retrieve(query, top_k)`
  （不等的话，"`retrieval_order` 就是去标签池"这句话不成立，整张表作废）；
* `ceiling`——每条查询枚举池内 C(N,3)，取**命中最多**那组 ÷ 3，对查询取均值（＝上界）；
  池子来源：`retrieval_order`／`embed3:<面>`／`label_top`（**阳性对照**，选择器不许构造）；
* `delivered`——池内按**去标签标量**排序交前 3（＝产品交付形状），命中率对查询取均值。

**两张表的"池子"定义不同，这是有意的，不许混读**：

* `ceiling_table` 的池子＝**这个构造自己对全部候选排名后的前 N**
  （`retrieval_order`＝不重排的基线；`embed3:<面>`＝用那个面对 top-120 重排后取前 N；
  `label_top`＝阳性对照）。它回答的是"**这种候选生成方式**最多能捞到多少"。
* `delivered_table` 的池子＝**检索原序前 N**（＝产品真交给选择器的那一池），
  里面的选择器只能用**去标签标量**排前 3。它回答的是"**手里这把排序**能交出来多少"。
  两列放一起才能读出"挖深有用（同样的排序，池子越大交付越好）"。

用法
====
```powershell
python tools/knowledge/e1_pool_ceiling.py `
    --bank docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl `
    --cases knowledge --vectors work/_embed3_cache.jsonl `
    --out docs/evidence/<run-id>/pool_ceiling.json
```

`--vectors` 可省略（那就只有 `retrieval_order` / `label_top` 两列，**不联网、不报错**）。
向量缓存支持两种行格式：本工具的 `{"sha": sha256(text), "vec": [...]}` 与
`tools/kb_fetch/embedding_cloud.py` 的 `{"key": sha256(model\\0text), "model": ..., "vector": [...]}`
—— 后者靠 `--encoder-model`（默认 `embedding-3`）复算键名，**两个模块共用一份缓存**。
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import math
import pathlib
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import common  # noqa: E402

#: 与 `e1_panel` 同一份定义，不另立一份。
RELEVANT = 4.0

#: 默认池深。3＝交付形状；6＝裁定的"每查询 20 组"；更深的用来画曲线。
DEFAULT_DEPTHS: Tuple[int, ...] = (3, 6, 9, 12, 20, 40)

#: 三个"文本面"（都只喂给嵌入编码器，**不看任何判分**）。
FACES: Tuple[str, ...] = ("excerpt", "excerpt+zh", "title+excerpt+zh", "zh")


# --------------------------------------------------------------------------- 纯函数（可离线测）
def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def strict_score(row: Dict[str, Any]) -> Optional[float]:
    """两位评委**都有分**才算得出均值；少一位 ⇒ `None`（P14-249，与 `e1_panel` 同源）。"""
    numbers = [float(s) for s in (row.get("scores") or [])
               if isinstance(s, (int, float))]
    return sum(numbers) / len(numbers) if len(numbers) >= 2 else None


def is_relevant(score: Optional[float], relevant: float = RELEVANT) -> bool:
    return score is not None and float(score) >= float(relevant)


def pool_counts(pool: Sequence[str], label_of: Dict[str, Optional[float]],
                relevant: float = RELEVANT) -> List[int]:
    """池子里**每一组三条**的命中数（顺序＝枚举序）。"""
    return [sum(1 for cid in combo if is_relevant(label_of.get(cid), relevant))
            for combo in itertools.combinations(pool, 3)]


def pool_ceiling(pool: Sequence[str], label_of: Dict[str, Optional[float]],
                 relevant: float = RELEVANT) -> Dict[str, Any]:
    """上界＝**取最好那一组**的命中率；`mean`＝全三元组均值（两者的差是"选择器值多少"）。"""
    counts = pool_counts(pool, label_of, relevant)
    if not counts:
        return {"triples": 0, "ceiling": None, "mean": None, "best": 0}
    return {"triples": len(counts), "best": max(counts),
            "ceiling": max(counts) / 3.0, "mean": sum(counts) / len(counts) / 3.0}


def delivered_top3(pool: Sequence[str], scorer: Dict[str, float],
                   label_of: Dict[str, Optional[float]],
                   relevant: float = RELEVANT) -> Optional[int]:
    """池内按 `scorer`（越大越好，并列按 case_id）排前 3，返回命中数；池里不足 3 条可评 ⇒ `None`。"""
    usable = [cid for cid in pool if cid in scorer]
    if len(usable) < 3:
        return None
    top = sorted(usable, key=lambda cid: (-scorer[cid], str(cid)))[:3]
    return sum(1 for cid in top if is_relevant(label_of.get(cid), relevant))


def zscores(values: Dict[str, float]) -> Dict[str, float]:
    """z 分（同一条查询内部）。`sd=0` ⇒ 全 0，不编造差异。"""
    xs = list(values.values())
    if not xs:
        return {}
    mean = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))
    return {k: ((v - mean) / sd if sd else 0.0) for k, v in values.items()}


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def mean_of(values: Iterable[float]) -> Optional[float]:
    xs = [v for v in values if v is not None]
    return (sum(xs) / len(xs)) if xs else None


# --------------------------------------------------------------------------- 输入
def load_bank(path: pathlib.Path) -> "collections.OrderedDict[str, List[Dict[str, Any]]]":
    """`query -> [row, ...]`，**保留文件序**（它就是检索名次，见 `order` 模式的自证）。"""
    grouped: "collections.OrderedDict[str, List[Dict[str, Any]]]" = collections.OrderedDict()
    for row in common.read_jsonl(path):
        grouped.setdefault(str(row["query"]), []).append(row)
    return grouped


class VectorCache:
    """嵌入向量缓存：支持本工具与 `embedding_cloud` 两种行格式（缺文件 ⇒ 空表，不报错）。"""

    def __init__(self, path: Optional[pathlib.Path], model: str = "embedding-3"):
        self.model = str(model)
        self.by_text: Dict[str, List[float]] = {}
        self.by_key: Dict[str, List[float]] = {}
        if path and pathlib.Path(path).exists():
            for row in common.read_jsonl(pathlib.Path(path)):
                vector = row.get("vec") or row.get("vector")
                if not isinstance(vector, list) or not vector:
                    continue
                if isinstance(row.get("sha"), str):
                    self.by_text[str(row["sha"])] = vector
                if isinstance(row.get("key"), str):
                    self.by_key[str(row["key"])] = vector

    def get(self, text: str) -> Optional[List[float]]:
        text = str(text or "")
        if not text:
            return None                      #: 空串不许送去编码（智谱回 HTTP 400，实测）
        mine = self.by_text.get(sha256_text(text))
        if mine:
            return mine
        theirs = self.by_key.get(sha256_text(self.model + "\x00" + text))
        return theirs or None


def verify_bank_order(bank, retrieve: Callable[[str, int], Sequence[str]],
                      top_k: int = 6) -> Dict[str, Any]:
    """承重墙：银行文件序前 `top_k` 是否**逐条**等于产品检索器。"""
    exact, mismatch = 0, []
    for query, rows in bank.items():
        first = [str(r["case_id"]) for r in rows[:top_k]]
        shipped = [str(cid) for cid in retrieve(query, top_k)]
        if shipped == first:
            exact += 1
        else:
            mismatch.append({"query": query, "bank": first, "shipped": shipped})
    return {"queries": len(bank), "top_k": int(top_k), "exact": exact,
            "mismatched": len(mismatch), "mismatches": mismatch[:20],
            "verdict": ("bank file order == shipped retrieve(top_k=%d) for every query" % top_k)
            if not mismatch else "mismatches exist — retrieval_order 这一列不成立"}


# --------------------------------------------------------------------------- 组装
def build_report(bank, *, vectors: Optional[VectorCache], titles: Dict[str, str],
                 depths: Sequence[int] = DEFAULT_DEPTHS,
                 faces: Sequence[str] = FACES) -> Dict[str, Any]:
    """三张表：上界（construction × depth）、交付位（scorer × depth）、阳性对照。"""
    ceiling_stats: Dict[Tuple[str, int], Dict[str, float]] = collections.defaultdict(
        lambda: {"ceiling": 0.0, "mean": 0.0, "queries": 0, "at_3of3": 0})
    delivered_stats: Dict[Tuple[str, int], Dict[str, float]] = collections.defaultdict(
        lambda: {"hits": 0.0, "queries": 0, "at_3of3": 0})
    for query, rows in bank.items():
        label_of = {str(r["case_id"]): strict_score(r) for r in rows}
        order = [str(r["case_id"]) for r in rows]
        prior = {cid: -float(i) for i, cid in enumerate(order)}
        face_cos: Dict[str, Dict[str, float]] = {}
        if vectors is not None:
            query_vector = vectors.get(query)
            if query_vector:
                for face in faces:
                    table: Dict[str, float] = {}
                    for row in rows:
                        cid = str(row["case_id"])
                        excerpt = str(row.get("excerpt") or "")
                        zh = str(row.get("zh") or "").strip()
                        text = {"excerpt": excerpt, "excerpt+zh": (excerpt + "\n" + zh).strip(),
                                "title+excerpt+zh": (titles.get(cid, "") + " ｜ " + excerpt
                                                     + "\n" + zh).strip(),
                                "zh": zh}.get(face, "")
                        vector = vectors.get(text) if text else None
                        if vector:
                            table[cid] = cosine(query_vector, vector)
                    face_cos[face] = table
        scorers: Dict[str, Dict[str, float]] = {"retrieval_order": dict(prior)}
        for face, table in face_cos.items():
            if table:
                scorers["embed3:" + face] = table
                z = zscores(table)
                prior_z = zscores(prior)
                scorers["prior+%s(z)" % face] = {
                    cid: (prior_z.get(cid, 0.0) + z.get(cid, 0.0)) / 2.0 for cid in z}
        for depth in depths:
            pool = order[:depth] if depth < len(order) else list(order)
            for name in list(scorers):
                table = scorers[name]
                if name != "retrieval_order" and not table:
                    continue
                #: 上界那一列：池子＝**这个构造自己排的前 N**（见模块 docstring 的两张表定义）。
                built = (pool if name == "retrieval_order"
                         else sorted([cid for cid in table],
                                     key=lambda cid: (-table[cid], str(cid)))[:depth])
                metrics = pool_ceiling(built, label_of)
                if metrics["ceiling"] is None:
                    continue
                bucket = ceiling_stats[(name, depth)]
                bucket["ceiling"] += metrics["ceiling"]
                bucket["mean"] += metrics["mean"]
                bucket["queries"] += 1
                bucket["at_3of3"] += 1 if metrics["best"] == 3 else 0
                hits = delivered_top3(pool, table, label_of)
                if hits is None:
                    continue
                found = delivered_stats[(name, depth)]
                found["hits"] += hits
                found["queries"] += 1
                found["at_3of3"] += 1 if hits == 3 else 0
            #: 阳性对照：**按标签分**取前 N（选择器不许构造，只用来看"门槛贴着谁"）。
            by_label = sorted(order, key=lambda cid: (-(label_of.get(cid) or 0.0), cid))[:depth]
            metrics = pool_ceiling(by_label, label_of)
            if metrics["ceiling"] is not None:
                bucket = ceiling_stats[("label_top", depth)]
                bucket["ceiling"] += metrics["ceiling"]
                bucket["mean"] += metrics["mean"]
                bucket["queries"] += 1
                bucket["at_3of3"] += 1 if metrics["best"] == 3 else 0
    ceiling_table = [
        {"construction": name, "pool_depth": depth,
         "ceiling_proxy": round(bucket["ceiling"] / bucket["queries"], 4),
         "mean_triple_proxy": round(bucket["mean"] / bucket["queries"], 4),
         "queries_at_3of3": int(bucket["at_3of3"]), "queries": int(bucket["queries"])}
        for (name, depth), bucket in sorted(
            ceiling_stats.items(), key=lambda kv: (kv[0][1], kv[0][0])) if bucket["queries"]]
    delivered_table = [
        {"scorer": name, "pool_depth": depth,
         "delivered_E1_proxy": round(bucket["hits"] / bucket["queries"] / 3.0, 4),
         "queries_at_3of3": int(bucket["at_3of3"]), "queries": int(bucket["queries"])}
        for (name, depth), bucket in sorted(
            delivered_stats.items(), key=lambda kv: (kv[0][1], kv[0][0])) if bucket["queries"]]
    return {"queries": len(bank), "threshold_135_of_192": 0.703125,
            "relevant": RELEVANT, "depths": list(depths),
            "ceiling_table": ceiling_table, "delivered_table": delivered_table,
            "anchors": {
                "official_delivered_E1": 0.1771,
                "proxy_retrieval_order_at_depth3": next(
                    (r["delivered_E1_proxy"] for r in delivered_table
                     if r["scorer"] == "retrieval_order" and r["pool_depth"] == 3), None),
                "proxy_retrieval_order_ceiling_at_depth6": next(
                    (r["ceiling_proxy"] for r in ceiling_table
                     if r["construction"] == "retrieval_order" and r["pool_depth"] == 6), None),
                "labelfree_pilot_fresh_oracle_8_queries": 0.375,
                "labelled_pool_fresh_oracle_64_queries": 0.7448}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="e1-pool-ceiling")
    parser.add_argument("--bank", required=True, help="逐案例 C=3 判分（含 query/case_id/scores）")
    parser.add_argument("--cases", default="knowledge", help="案例索引目录（取 title）")
    parser.add_argument("--vectors", default="", help="嵌入向量缓存（可省略）")
    parser.add_argument("--encoder-model", default="embedding-3")
    parser.add_argument("--depths", default=",".join(str(d) for d in DEFAULT_DEPTHS))
    parser.add_argument("--top-k", type=int, default=6, help="承重墙模式的比对条数")
    parser.add_argument("--modes", default="order,ceiling,delivered")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    bank_path = pathlib.Path(args.bank)
    if not bank_path.exists():
        print(json.dumps({"error": "bank not found", "bank": str(bank_path)},
                         ensure_ascii=False))
        return 3
    depths = tuple(int(x) for x in str(args.depths).split(",") if str(x).strip())
    modes = {m.strip() for m in str(args.modes).split(",") if m.strip()}
    bank = load_bank(bank_path)
    index = load_index(pathlib.Path(args.cases), backend="hybrid")
    titles = {str(c.case_id): str(getattr(c, "title", "") or "") for c in index.cases}
    vectors = VectorCache(pathlib.Path(args.vectors) if args.vectors else None,
                          model=args.encoder_model)

    payload: Dict[str, Any] = {"bank": str(bank_path), "cases": str(args.cases),
                              "vectors": str(args.vectors or "")}
    if "order" in modes:
        payload["bank_order"] = verify_bank_order(
            bank, lambda query, k: [c.case_id for c in index.retrieve(query, top_k=k)],
            top_k=args.top_k)
    report = build_report(bank, vectors=vectors, titles=titles, depths=depths)
    if "ceiling" in modes:
        payload["ceiling_table"] = report["ceiling_table"]
    if "delivered" in modes:
        payload["delivered_table"] = report["delivered_table"]
    payload.update({"queries": report["queries"], "threshold_135_of_192": 0.703125,
                    "anchors": report["anchors"], "depths": list(depths)})
    pathlib.Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                      encoding="utf-8", newline="\n")
    print(json.dumps({k: payload[k] for k in ("queries", "anchors", "bank_order")
                      if k in payload}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
