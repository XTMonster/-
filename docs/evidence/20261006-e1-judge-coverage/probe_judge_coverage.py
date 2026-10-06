"""Read-only probe: how much of E1 comes from rows that only ONE judge scored?

The frozen E1 definition is "two LLM judges each score 1-5, take the mean, >=4 counts
as relevant".  e1_panel._score_one writes None for a judge that failed and then averages
over whatever judges DID answer, so a single-judge row is still labelled and still
counted in the denominator.  This probe measures how big that deviation is on the file
the acceptance chain actually consumes.

Usage:  python work/_probe_judge_coverage.py <reviews.jsonl> [...]
"""
import json
import sys
from pathlib import Path


RELEVANT = 4.0


def _numbers(row):
    return [float(s) for s in (row.get("scores") or []) if isinstance(s, (int, float))]


def _relevant(rows):
    return sum(1 for r in rows if _numbers(r) and
               sum(_numbers(r)) / len(_numbers(r)) >= RELEVANT)


def summarise(path):
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    both = [r for r in rows if len(_numbers(r)) >= 2]
    single = [r for r in rows if len(_numbers(r)) == 1]
    zero = [r for r in rows if not _numbers(r)]
    total = len(rows)
    return {
        "file": str(path),
        "rows": total,
        "rows_two_judges": len(both),
        "rows_one_judge": len(single),
        "rows_zero_judges": len(zero),
        "E1_reported": round(_relevant(rows) / total, 4) if total else None,
        "E1_two_judge_only": round(_relevant(both) / len(both), 4) if both else None,
        "E1_single_as_irrelevant": round(_relevant(both) / total, 4) if total else None,
        "single_rows_that_count_relevant_today": _relevant(single),
        "has_judge_batch_on_every_row": all("judge_batch" in r for r in rows) if rows else None,
        "judge_batch_values": sorted({int(r.get("judge_batch") or 0) for r in rows}),
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    print(json.dumps([summarise(Path(p)) for p in argv[1:]],
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
