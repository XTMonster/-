"""Re-run the load-bearing "oracle triple" measurement - and COMMIT its raw artifact.

Why this exists (2026-10-06, P14-263): `docs/evidence/20261006-fresh-oracle/README.md` reports
**E1 0.4583** for "take each query's label-top-3 (the oracle triple) and re-judge it as a fresh
triple".  That number is load-bearing - the whole RK-13 argument ("the reachable ceiling under
the current protocol is ~0.46, not 0.84") rests on it - but the **raw scores were never written
to disk**: the original `work/_probe_oracle_triple.py` only printed a summary, and no reviews
file exists anywhere.  A load-bearing number that cannot be recomputed is exactly the evidence
hole this repo keeps closing (cf. the packs that lived only under gitignored `work/`).

So this version writes the full per-query detail, and records BOTH rules:

* `strict` - the frozen definition after P14-249 (a row counts only when BOTH judges scored it;
  a single-judge row stays in the denominator but can never be relevant);
* `loose`  - what the original run reported (mean over whichever judges answered).

Everything else is deliberately identical to the original: same label source, same "top-3 by
label score, ties by case_id", same two judges, same frozen `e1_panel.judge`.
"""
import argparse
import collections
import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
from block_director.contracts.knowledge import Case  # noqa: E402
from block_director.knowledge.cases import case_paths  # noqa: E402
from tools.kb_fetch import common, llm  # noqa: E402
from tools.knowledge import e1_panel  # noqa: E402

DEFAULT_LABELS = "docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top50.jsonl"


def load_cases():
    out = {}
    for path in case_paths(pathlib.Path("knowledge")):
        for row in common.read_jsonl(path):
            out[str(row["case_id"])] = row
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default=DEFAULT_LABELS)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", default="docs/evidence/20261006-fresh-oracle/reviews.oracle_triple.json")
    args = parser.parse_args()

    rows = common.read_jsonl(pathlib.Path(args.labels))
    grouped = collections.OrderedDict()
    for row in rows:
        grouped.setdefault(str(row["query"]), []).append(row)
    if args.limit:
        grouped = collections.OrderedDict(list(grouped.items())[:args.limit])
    cases = load_cases()
    clients = [("deepseek-chat", llm.make_client("deepseek", "deepseek-chat")),
               ("glm-5.3", llm.make_client("glm", "glm-5.3"))]

    def one(item):
        query, items = item
        ranked = sorted(items, key=lambda r: (-(r.get("score") or 0), str(r["case_id"])))[:3]
        triple = [Case(case_id=str(r["case_id"]),
                       title=str(cases.get(str(r["case_id"]), {}).get("title", "")),
                       excerpt=str(cases.get(str(r["case_id"]), {}).get("excerpt")
                                   or r.get("excerpt") or ""))
                  for r in ranked]
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
            out.append({"scores": [s[i] for s in per],
                        "strict": (sum(nums) / len(nums)) if len(nums) >= 2 else None,
                        "loose": (sum(nums) / len(nums)) if nums else None})
        return {"query": query,
                "label_top3": [str(r["case_id"]) for r in ranked],
                "rows": out}

    with ThreadPoolExecutor(max_workers=int(args.workers)) as pool:
        detail = list(pool.map(one, list(grouped.items())))

    def rate(key):
        hits = served = 0
        for entry in detail:
            for row in entry["rows"]:
                value = row[key]
                if value is None:
                    continue
                served += 1
                if value >= e1_panel.RELEVANT:
                    hits += 1
        return {"numerator": hits, "denominator": 3 * len(detail), "served": served,
                "value": round(hits / (3 * len(detail)), 4) if detail else None}

    summary = {"labels": args.labels, "queries": len(detail),
               "panel": [name for name, _c in clients],
               "strict": rate("strict"), "loose": rate("loose"),
               "per_query": detail}
    pathlib.Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_query"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
