"""E1 的**去标签**候选池上界：选择器能用的那个池子，oracle 到底够多高？

为什么要有它（GPT-6A 的 RK-13 裁定 ＋ 主线核对，见
`docs/knowledge/SELECTOR_PIPELINE_v1.md`／`docs/knowledge/RULING_CHECK_RK13.md`）：

* 裁定把 E1 的过关线定成 **≥135/192 = 0.703125**，依据是"oracle 约 143/192"
  （= `E1_best_of_search` 0.7448 × 192）。
* 但那个 0.7448 的池子是 `tools/knowledge/e1_triple_search.py` 里
  **按标签分取 top-N 再全组合**得到的 —— **池子本身用了标签**；
* 而裁定**同时**要求"选择器**不许**看判分" ⇒ 选择器只能用**去标签池**，
  而**去标签池的 oracle 从来没人量过**。

本工具就量它：每条查询用**产品检索器的原始名次**取前 `--pool` 条
（`CaseIndex.retrieve(query, top_k=pool)`，**不看任何判分字段**）→ 全组合 C(pool,3) 组
→ 用**与 `e1_panel` 逐字同一份**判分（`e1_triple_search.judge_triple`：同 SYSTEM、
同两位评委、同 C=3 语境、P14-249 的"少一位评委不发分"）逐组判。

判据（与全仓一致，**不动**）：行分 = **两位**评委各 1-5 分的均值；`>= 4.0` 记相关。

产出（`--out` JSON）：

* `triples[]`——**判过的每一个三元组**（`query`／`triple`／`values`／`hits`／`pool_rank`），
  顺序＝`(查询序, 枚举序)`；选择器的评估集就是它；
* `labelfree_oracle`——每条查询**挑中最好那一组**的行相关率（这是这条池子的上界）；
* `delivered_first_triple`——不做选择、直接用检索器前 3 条（＝产品的交付形状）的读数；
* `three_of_three`——3/3 的组数。

用法：

```powershell
python tools/knowledge/e1_labelfree_pool.py `
    --queries docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl `
    --cases knowledge --pool 6 --workers 6 `
    --out docs/evidence/<run-id>/labelfree_pool.json
```

`--scripted` 走 `llm` 的离线桩，**不碰网络**（守门测试用它）。
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import itertools
import json
import pathlib
import sys
from typing import Any, Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.knowledge import Case  # noqa: E402
from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import common, llm  # noqa: E402
from tools.knowledge import e1_panel  # noqa: E402
#: **判分口径只准有一份**：直接复用三元组搜索器里那条（它自己又是 `e1_panel.judge`）。
from tools.knowledge.e1_triple_search import judge_triple  # noqa: E402


def queries_from(path: pathlib.Path) -> List[str]:
    """只取**查询串**（按首次出现去重）——**不碰任何判分字段**，这就是"去标签"的含义。"""
    seen, out = set(), []
    for row in common.read_jsonl(path):
        query = str(row.get("query") or "")
        if query and query not in seen:
            seen.add(query)
            out.append(query)
    return out


def as_case(item: Any) -> Case:
    """检索器回的东西可能是 `Case`，也可能是 dict（适配器路径）——两种都收。"""
    if isinstance(item, Case):
        return item
    if isinstance(item, dict):
        return Case.from_dict(dict(item))
    return Case(case_id=str(getattr(item, "case_id", "")),
                title=str(getattr(item, "title", "")),
                excerpt=str(getattr(item, "excerpt", "")))


def pool_of(index: Any, query: str, size: int) -> List[Case]:
    """候选池＝**检索器的原始名次**取前 `size` 条。除检索外不读任何东西。"""
    return [as_case(item) for item in index.retrieve(query, top_k=int(size))]


def search(index: Any, queries: Sequence[str], *, clients: Sequence[tuple],
           pool_size: int = 6, workers: int = 1) -> Dict[str, Any]:
    """按查询枚举去标签池里的**全部**三元组并逐组判分。**纯函数式**（索引与客户端注入）。"""

    def one(query: str) -> Tuple[str, List[Case], List[Tuple[str, ...]], List[List[Any]]]:
        pool = pool_of(index, query, pool_size)
        combos = list(itertools.combinations(pool, 3))
        judged = [judge_triple(clients, query, list(combo)) for combo in combos]
        return query, pool, combos, judged

    if int(workers) > 1 and len(queries) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(workers)) as pool_:
            results = list(pool_.map(one, queries))
    else:
        results = [one(query) for query in queries]

    records: List[Dict[str, Any]] = []
    per_query: "collections.OrderedDict[str, List[Dict[str, Any]]]" = \
        collections.OrderedDict()
    pools: Dict[str, List[str]] = {}
    for query, pool, combos, judged in results:
        pools[query] = [c.case_id for c in pool]
        rank = {c.case_id: i for i, c in enumerate(pool)}
        rows: List[Dict[str, Any]] = []
        for combo, values in zip(combos, judged):
            rows.append({
                "query": query, "triple": [c.case_id for c in combo],
                "values": [None if v is None else round(float(v), 2) for v in values],
                "hits": sum(1 for v in values
                            if v is not None and v >= e1_panel.RELEVANT),
                "pool_rank": [rank[c.case_id] for c in combo],
            })
        records.extend(rows)
        per_query[query] = rows

    #: 池子不足 3 条 ⇒ 这条查询**一个三元组都判不了**。不编数：把它**排除在均值之外**
    #: 并单独计数（写进 `queries_without_a_triple`），否则 `max()` 会当场炸，
    #: 而"悄悄把空查询当成 0 分"会让分母含义漂移。
    judged_rows = [rows for rows in per_query.values() if rows]
    best = [max(r["hits"] for r in rows) for rows in judged_rows]
    first = [rows[0]["hits"] for rows in judged_rows]
    describe = index.describe() if hasattr(index, "describe") else {}
    return {
        "queries": len(judged_rows),
        "queries_requested": len(per_query),
        "queries_without_a_triple": len(per_query) - len(judged_rows),
        "triples_judged": len(records),
        "pool": int(pool_size),
        "labelfree_oracle": (round(sum(best) / len(best) / 3.0, 4) if best else None),
        "delivered_first_triple": (round(sum(first) / len(first) / 3.0, 4)
                                   if first else None),
        "three_of_three": sum(1 for value in best if value == 3),
        #: 自述：这个数是在哪一代索引上量的（换语料/换路由必须能看出来）。
        "cases_backend": describe.get("cases_backend"),
        "cases_index_fingerprint": describe.get("cases_index_fingerprint"),
        "cases_clues": describe.get("cases_clues"),
        "cases_clue_state": describe.get("cases_clue_state"),
        "pools": pools,
        "triples": records,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-e1-labelfree-pool")
    parser.add_argument("--queries", required=True,
                        help="带 `query` 的文件（只读查询串；判分字段一概不读）")
    parser.add_argument("--cases", default="knowledge")
    parser.add_argument("--backend", default="hybrid")
    parser.add_argument("--pool", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0, help="0 ＝ 全部查询")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--models", default=",".join(e1_panel.DEFAULT_PANEL))
    parser.add_argument("--scripted", default="", help="离线桩；给了就完全不碰网络")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    queries = queries_from(pathlib.Path(args.queries))
    if args.limit:
        queries = queries[:int(args.limit)]
    index = load_index(pathlib.Path(args.cases), backend=args.backend)
    names = [n.strip() for n in args.models.split(",") if n.strip()]
    families = list(e1_panel.DEFAULT_FAMILIES[:len(names)]) or ["scripted"]
    clients = [(name, llm.make_client("scripted", name, args.scripted) if args.scripted
                else llm.make_client(families[i], name))
               for i, name in enumerate(names)]
    payload = search(index, queries, clients=clients, pool_size=args.pool,
                     workers=args.workers)
    payload["queries_file"] = args.queries
    payload["panel"] = names
    pathlib.Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                      encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in payload.items()
                      if k not in ("triples", "pools")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
