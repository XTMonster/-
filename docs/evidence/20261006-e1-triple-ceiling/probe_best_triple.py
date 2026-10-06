"""Decisive-question probe: can ANY assembled triple reach 3/3 under the C=3 ruler?

The big search (`work/_run_triple_search.ps1`) walks 20 combinations per query and only writes
its JSON at the very end, so it is a black box for hours.  This probe asks the same question in
the *most favourable* place possible, for one triple per query:

  per query, take the rows that were labelled RELEVANT in their own C=3 context
  (`reviews.current.batch3.top120.jsonl`), fill up to 3 with the best remaining rows by label
  score, assemble them into ONE triple, and judge that triple with the frozen `e1_panel.judge`
  (same SYSTEM prompt, same two judges).

Why this is the sharp end: if a 3/3 triple exists anywhere, it is most likely to be the one
built from the rows that were each judged relevant somewhere.  If even THIS never reaches 3/3,
the "3/3 is essentially unreachable under this ruler" reading gets much stronger.

Cost: 64 queries x 2 judges = 128 judge calls (vs 2,560 for the full search).
"""
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
from block_director.contracts.knowledge import Case  # noqa: E402
from block_director.knowledge.cases import case_paths  # noqa: E402
from tools.kb_fetch import common, llm  # noqa: E402
from tools.knowledge import e1_panel  # noqa: E402

LABELS = "docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl"
OUT = "work/_probe_best_triple.json"


def load_cases():
    out = {}
    for path in case_paths(pathlib.Path("knowledge")):
        for row in common.read_jsonl(path):
            out[str(row["case_id"])] = row
    return out


def strict_relevant(row):
    nums = [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]
    return len(nums) >= 2 and sum(nums) / len(nums) >= e1_panel.RELEVANT


def judge_one(clients, query, triple):
    per = []
    for _name, client in clients:
        try:
            got = e1_panel.judge(client, query, triple)
        except Exception as exc:  # noqa: BLE001
            got = {"__error__": str(exc)[:120]}
        per.append([got.get(c.case_id, {}).get("score") for c in triple])
    out = []
    for i in range(len(triple)):
        nums = [s[i] for s in per if isinstance(s[i], (int, float))]
        out.append(sum(nums) / len(nums) if len(nums) >= 2 else None)
    return out


def main():
    rows = common.read_jsonl(pathlib.Path(LABELS))
    grouped = {}
    for row in rows:
        grouped.setdefault(str(row["query"]), []).append(row)
    cases = load_cases()
    clients = [("deepseek-chat", llm.make_client("deepseek", "deepseek-chat")),
               ("glm-5.3", llm.make_client("glm", "glm-5.3"))]

    jobs = []
    for query, items in grouped.items():
        labelled_rel = sorted([r for r in items if strict_relevant(r)],
                              key=lambda r: (-(r.get("score") or 0), str(r["case_id"])))
        rest = sorted([r for r in items if not strict_relevant(r)],
                      key=lambda r: (-(r.get("score") or 0), str(r["case_id"])))
        picked = (labelled_rel + rest)[:3]
        triple = [Case(case_id=str(r["case_id"]),
                       title=str(cases.get(str(r["case_id"]), {}).get("title", "")),
                       excerpt=str(cases.get(str(r["case_id"]), {}).get("excerpt")
                                   or r.get("excerpt") or ""))
                  for r in picked]
        jobs.append((query, [str(r["case_id"]) for r in picked], triple,
                     len(labelled_rel)))

    def run(job):
        query, ids, triple, n_rel = job
        return query, ids, judge_one(clients, query, triple), n_rel

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, jobs))

    dist = {0: 0, 1: 0, 2: 0, 3: 0}
    rows_out = []
    for query, ids, values, n_rel in results:
        hits = sum(1 for v in values if v is not None and v >= e1_panel.RELEVANT)
        dist[hits] += 1
        rows_out.append({"query": query, "triple": ids,
                         "labelled_relevant_available": n_rel,
                         "values": [None if v is None else round(float(v), 2) for v in values],
                         "hits": hits})
    summary = {
        "queries": len(results),
        "judge_calls": 2 * len(results),
        "distribution": dist,
        "three_of_three": dist[3],
        "E1_best_single_assembled_triple": round(
            sum(r["hits"] for r in rows_out) / len(rows_out) / 3.0, 4) if rows_out else None,
        "queries_with_3_labelled_relevant_rows": sum(
            1 for r in rows_out if r["labelled_relevant_available"] >= 3),
        "rows": rows_out,
    }
    pathlib.Path(OUT).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                 encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
