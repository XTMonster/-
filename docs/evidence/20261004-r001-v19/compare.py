"""Compare the three frozen projects with the stale line vs the line that follows."""

from __future__ import annotations

import json
import statistics
import sys

PAIRS = [
    ("long9", "work/_aim_20261003_chunked_long9.json",
     "work/_v19_20261003_chunked_long9.json"),
    ("long11", "work/_aim_20261004_chunked_long11.json",
     "work/_v19_20261004_chunked_long11.json"),
    ("long12", "work/_aim_20261004_chunked_long12.json",
     "work/_v19_20261004_chunked_long12.json"),
]


def main() -> int:
    for name, stale, follows in PAIRS:
        for tag, path in (("stale-line", stale), ("line-follows", follows)):
            try:
                data = json.load(open(path, encoding="utf-8"))
            except FileNotFoundError:
                print(f"{name:7} {tag:12} MISSING {path}")
                continue
            rows = data["rows"]
            scores = [row["score"] for row in rows if row["score"] is not None]
            passed = len([row for row in rows if row["passed"]])
            gate = len([score for score in scores if score >= 70])
            print(f"{name:7} {tag:12} passed {passed:2}  gate {gate:2}  "
                  f"median {statistics.median(scores):5.1f}  {data.get('rules')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
