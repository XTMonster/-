"""E1 的"上限"到底是**组合最优**还是**已试方法的成绩**？

背景（GPT-6A 2026-10-06，`docs/evidence/20261006-gpt6a-round2/answers/full_head.md` 第 3 条）：
本仓把"把每条查询**标签分最高的 3 条**重新盲评"得到的 **0.4583** 当成当前协议下的
**可达上界**。但那个 3 条**本身就是一种选择方式**，所以它量的是"已试方法"的成绩，
**不是组合最优**。要证"不可达"，得在 **C=3 尺子上真的去搜三元组**。

`work/_probe_triple_ceiling.py` 先用**已有标签**做了半张答卷（只能覆盖"连续三元组"：
top-120 那份里 **2,559 个三元组没有一个到 3/3**，按分组取最好也只有 0.4219）；
本工具补上另一半：**自己组装**三元组再判——每条查询从候选池里枚举/抽样三元组，
用**与 `e1_panel` 逐字同一份** `judge()`（同 SYSTEM 提示词、同两位评委、同 C=3 语境）打分。

判据（与全仓一致，**不动**）：行分 = **两位**评委各 1-5 分的均值；`>= 4.0` 记相关；
少一位评委的行**不发分、也算不相关**（P14-249 的 `judge_incomplete` 口径）。

输出（`--out` JSON）：

* `E1_best_of_search`——每条查询**搜到的最好三元组**的相关行率均值（这是这次搜索能到达的上界）；
* `three_of_three`——搜出来的 3/3 三元组条数（**>0 就直接推翻"不可达"**）；
* `distribution`——所有被判三元组的 0/1/2/3 相关分布。
* `triples`——**判过的每一个三元组**（`query`／三条 `case_id`／逐行均值 `values`／命中数
  `hits`，顺序＝枚举序）：给"整组三条联合打分"的选择器留的**评估集**。只留每组最好的
  那一组（上一版的做法）会让事后无法回答"选择器挑的那组比最好那组差多少"；
* `pools`——每条查询当时的**候选池**（按检索名次排好），选择器只许看池内名次这类去标签线索。

用法：

```powershell
python tools/knowledge/e1_triple_search.py `
    --labels docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl `
    --cases knowledge --pool-per-query 8 --max-triples 24 --workers 6 `
    --out docs/evidence/<run-id>/triple_search.json
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
from block_director.knowledge.cases import case_paths  # noqa: E402
from tools.kb_fetch import common, llm  # noqa: E402
from tools.knowledge import e1_panel  # noqa: E402

#: 与 `e1_panel` 同一份定义，不另立一份。
RELEVANT = e1_panel.RELEVANT


def load_cases(cases_dir: pathlib.Path) -> Dict[str, Dict[str, Any]]:
    """`case_id -> 原行`，给 `Case(...)` 补 title／excerpt 用。"""
    out: Dict[str, Dict[str, Any]] = {}
    for path in case_paths(cases_dir):
        #: 走全仓**唯一**的 JSONL 读入口：它只按 `\n` 切，`str.splitlines()` 会按
        #: Unicode 行边界切，而 U+0085/U+2028/U+2029 是合法的 JSON 字符串内容
        #: （守门 `tests/test_jsonl_reading_convention.py`）。
        for row in common.read_jsonl(path):
            out[str(row["case_id"])] = row
    return out


def candidate_pool(rows: Sequence[Dict[str, Any]], *, pool_per_query: int) -> List[str]:
    """这条查询的候选池：**按标签分降序**（并列按 `case_id`）取前 `pool_per_query` 条。

    池子与三元组都要落盘（见 `test_e1_triple_search.py` 的步骤 0 守门），所以这条
    排序规则**只准有一份**——`candidate_triples()` 与 `search()` 都从这里取。
    """
    ranked = sorted(rows, key=lambda r: (-(r.get("score") or 0), str(r["case_id"])))
    return [str(r["case_id"]) for r in ranked[:int(pool_per_query)]]


def candidate_triples(rows: Sequence[Dict[str, Any]], *, pool_per_query: int,
                      max_triples: int) -> List[Tuple[str, ...]]:
    """一条查询的候选三元组。

    池子＝`candidate_pool(...)`；三元组＝该池子的**全部组合**，超过 `max_triples` 时
    **按枚举序取前 N**（确定、可复现）。
    """
    ids = candidate_pool(rows, pool_per_query=pool_per_query)
    combos = list(itertools.combinations(ids, 3))
    if max_triples and len(combos) > int(max_triples):
        combos = combos[:int(max_triples)]
    return combos


def judge_triple(clients: Sequence[tuple], query: str,
                 triple: Sequence[Case]) -> List[Any]:
    """一次三元组判分：返回按三元组顺序的**每行均值**（凑不够两位评委 ⇒ `None`）。

    与 `e1_panel._score_one` 的汇总逐字同口径：把每位评委的分数收齐，只有
    **两位都有分**才算得出均值；少一位就 `None`（P14-249）。
    """
    per_judge: List[List[Any]] = []
    for _name, client in clients:
        try:
            got = e1_panel.judge(client, query, triple)
        except Exception as exc:  # noqa: BLE001 - 失败要具名，不吞
            got = {"__error__": str(exc)[:120]}
        per_judge.append([got.get(c.case_id, {}).get("score")
                          for c in triple])
    out: List[Any] = []
    for position in range(len(triple)):
        numbers = [scores[position] for scores in per_judge
                   if isinstance(scores[position], (int, float))]
        out.append(sum(numbers) / len(numbers) if len(numbers) >= 2 else None)
    return out


def search(rows: Sequence[Dict[str, Any]], *, cases: Dict[str, Dict[str, Any]],
           clients: Sequence[tuple], pool_per_query: int = 8,
           max_triples: int = 24, workers: int = 1) -> Dict[str, Any]:
    """按查询搜三元组。**纯函数式**：索引与客户端都由调用方注入，因此可离线测。"""
    grouped: "collections.OrderedDict[str, List[Dict[str, Any]]]" = \
        collections.OrderedDict()
    for row in rows:
        grouped.setdefault(str(row["query"]), []).append(row)

    jobs = []
    pools: Dict[str, List[str]] = {}
    for query, items in grouped.items():
        pools[query] = candidate_pool(items, pool_per_query=pool_per_query)
        #: 判分清单必须与真实判分**逐字同源**：`CaseIndex.retrieve` 返回的是
        #: `Case`（**没有 `summary` 字段**），`e1_panel.judge` 于是用
        #: `title[:60] ｜ excerpt[:220]`。所以这里也从**案例索引**取 title/excerpt，
        #: 索引里缺这条时才退回这家打分文件自带的 `excerpt`。
        fallback = {str(r["case_id"]): str(r.get("excerpt") or "") for r in items}
        for combo in candidate_triples(items, pool_per_query=pool_per_query,
                                       max_triples=max_triples):
            triple = [Case(case_id=cid,
                           title=str(cases.get(cid, {}).get("title", "")),
                           excerpt=str(cases.get(cid, {}).get("excerpt")
                                       or fallback.get(cid, "")))
                      for cid in combo]
            jobs.append((query, combo, triple))

    def run(job):
        query, combo, triple = job
        return query, combo, judge_triple(clients, query, triple)

    if int(workers) > 1 and len(jobs) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(workers)) as pool:
            results = list(pool.map(run, jobs))
    else:
        results = [run(job) for job in jobs]

    distribution = {0: 0, 1: 0, 2: 0, 3: 0}
    best: Dict[str, Dict[str, Any]] = {}
    three_of_three = 0
    for query, combo, values in results:
        hits = sum(1 for v in values if v is not None and v >= RELEVANT)
        distribution[hits] += 1
        if hits == 3:
            three_of_three += 1
        current = best.get(query)
        if current is None or hits > current["hits"]:
            best[query] = {"hits": hits, "triple": list(combo),
                           "values": [None if v is None else round(float(v), 2)
                                      for v in values]}

    hits_list = [entry["hits"] for entry in best.values()]
    return {
        "queries": len(grouped),
        "triples_judged": len(results),
        "distribution": distribution,
        "three_of_three": three_of_three,
        "E1_best_of_search": (round(sum(hits_list) / len(hits_list) / 3.0, 4)
                              if hits_list else None),
        "best_per_query": best,
        #: 步骤 0（`work/_selector_pipeline_plan.md`）：**判过的每一个三元组**都要落盘，
        #: 否则事后无法给"整组三条联合打分"的选择器评分（只剩每组最好的那一组＝
        #: 答案在手里、过程丢了）。顺序＝`jobs` 的枚举序，确定、可复算。
        "triples": [
            {"query": query, "triple": list(combo),
             "values": [None if value is None else round(float(value), 2)
                        for value in values],
             "hits": sum(1 for value in values
                         if value is not None and value >= RELEVANT)}
            for query, combo, values in results
        ],
        #: 这条查询当时可选的池子（检索名次序）——选择器只许看池内名次这类"去标签"线索。
        "pools": pools,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-e1-triple-search")
    parser.add_argument("--labels", required=True,
                        help="带 `judge_batch=3` 的 e1_panel 打分文件（行序＝检索序）")
    parser.add_argument("--cases", default="knowledge")
    parser.add_argument("--pool-per-query", type=int, default=8)
    parser.add_argument("--max-triples", type=int, default=24,
                        help="每条查询最多判几个三元组（0 ＝ 全部组合）")
    parser.add_argument("--limit", type=int, default=0, help="0 ＝ 全部查询")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--scripted", default="", help="离线桩；给了就完全不碰网络")
    parser.add_argument("--out", required=True)
    parser.add_argument("--models", default=",".join(e1_panel.DEFAULT_PANEL))
    args = parser.parse_args(argv)

    #: 同上：只走 `common.read_jsonl`，不自己切行。
    rows = common.read_jsonl(pathlib.Path(args.labels))
    if args.limit:
        keep = list(collections.OrderedDict.fromkeys(str(r["query"]) for r in rows))[:args.limit]
        rows = [r for r in rows if str(r["query"]) in set(keep)]
    cases = load_cases(pathlib.Path(args.cases))
    names = [n.strip() for n in args.models.split(",") if n.strip()]
    families = list(e1_panel.DEFAULT_FAMILIES[:len(names)]) or ["scripted"]
    clients = [(name, llm.make_client("scripted", name, args.scripted) if args.scripted
                else llm.make_client(families[i], name))
               for i, name in enumerate(names)]
    payload = search(rows, cases=cases, clients=clients,
                     pool_per_query=args.pool_per_query,
                     max_triples=args.max_triples, workers=args.workers)
    payload["labels"] = args.labels
    payload["panel"] = names
    pathlib.Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                      encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "best_per_query"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
