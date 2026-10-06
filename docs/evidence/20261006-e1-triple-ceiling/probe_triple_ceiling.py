"""Is the "ceiling" a property of the CASES or of the PRESENTATION?

GPT-6A's challenge (2026-10-06, `docs/evidence/20261006-gpt6a-round2/answers/full_head.md`
point 3): the 0.4583 "ceiling" was measured by re-judging the *label-top-3* triple, i.e. it is
the score of ONE tried selection method -- not a combinatorial optimum.  So "unreachable under
the frozen protocol" is an inference, not a measurement.

`reviews.current.batch3.top120.jsonl` already contains C=3 labels for **every consecutive
triple** of each query's top-120 candidate list (40 triples/query, `judge_batch=3`), so part of
that question can be answered with NO new judging:

* the distribution of per-triple relevant counts (how often is a triple 0/1/2/3 relevant?);
* E1 over all triples (cross-check against the reported 0.0611);
* the **delivered** triple (ranks 1-3) -- the product ruler;
* the **best-of-40** triple per query (an oracle over the groupings we actually judged).

The best-of-40 is an upper bound for a selector restricted to those 40 groupings.  It is NOT an
upper bound over all C(120,3) triples -- say so explicitly, do not oversell it.

Usage: python work/_probe_triple_ceiling.py <reviews.jsonl> [...]
"""
import json
import sys
from pathlib import Path

RELEVANT = 4.0


def _numbers(row):
    return [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]


def _strict(row):
    """Two-judge definition (P14-249): no score unless BOTH judges answered."""
    nums = _numbers(row)
    if len(nums) < 2:
        return None
    return sum(nums) / len(nums)


def _loose(row):
    """What was reported before P14-249: mean over whichever judges answered."""
    nums = _numbers(row)
    return sum(nums) / len(nums) if nums else None


def triples_of(rows):
    """Group one query's rows into consecutive triples, dropping a partial tail."""
    out, batch = [], int(rows[0].get("judge_batch") or 0) or 3
    for i in range(0, len(rows) - batch + 1, batch):
        out.append(rows[i:i + batch])
    return out


def summarise(path, score_of):
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    per_query = {}
    for row in rows:
        per_query.setdefault(str(row["query"]), []).append(row)

    dist = {0: 0, 1: 0, 2: 0, 3: 0}
    all_counts, first_counts, best_counts = [], [], []
    for _q, qrows in per_query.items():
        groups = triples_of(qrows)
        counts = []
        for group in groups:
            vals = [score_of(r) for r in group]
            # a row with no usable label counts as NOT relevant, and STAYS in the denominator
            hits = sum(1 for v in vals if v is not None and v >= RELEVANT)
            counts.append(hits)
            dist[hits] += 1
        if not counts:
            continue
        all_counts.extend(counts)
        first_counts.append(counts[0])       # ranks 1-3 = what the product delivers
        best_counts.append(max(counts))      # oracle over the 40 judged groupings

    mean = lambda xs: round(sum(xs) / len(xs) / 3.0, 4) if xs else None
    return {
        "file": str(path),
        "queries": len(per_query),
        "triples_judged": sum(dist.values()),
        "per_triple_relevant_distribution": dist,
        "E1_all_triples": mean(all_counts),
        "E1_delivered_triple": mean(first_counts),
        "E1_best_of_judged_groupings": mean(best_counts),
        "three_of_three_triples": dist[3],
        "queries_with_a_3of3": sum(1 for q in per_query.values()
                                   if any(sum(1 for r in g if (score_of(r) or -1) >= RELEVANT) == 3
                                          for g in triples_of(q))),
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = []
    for p in argv[1:]:
        path = Path(p)
        out.append({"strict_two_judge": summarise(path, _strict), "as_reported_before": summarise(path, _loose)})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
