"""看索引里 7 个「相等式」kind 的取值长什么样，以及成片侧对应字段长什么样。"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

KINDS = ("shot_size", "movement", "intent", "lens", "vfx", "action", "transition")
ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    domains = collections.defaultdict(collections.Counter)
    roles = collections.defaultdict(collections.Counter)
    for line in (ROOT / "knowledge/hypergraph.edges.jsonl").read_text(
            encoding="utf-8").split("\n"):
        line = line.strip()
        if not line:
            continue
        edge = json.loads(line)
        for member in edge.get("members") or []:
            if len(member) != 3 or str(member[1]) not in KINDS:
                continue
            roles[str(member[1])][str(member[0])] += 1
            domains[str(member[1])][str(member[2]).split(":", 1)[-1]] += 1
    for kind in KINDS:
        print("%-12s roles=%s" % (kind, dict(roles[kind])))
        print("             values=%s" % list(domains[kind])[:12])

    shots = json.loads((ROOT / "docs/evidence/20261006-long21/export/export/"
                        "shots.json").read_text(encoding="utf-8"))["shots"]
    print()
    print("shots: shot_type", sorted({s["shot_type"] for s in shots}))
    print("shots: intent_type", sorted({s["intent_type"] for s in shots}))
    print("shots: action_types", sorted({a for s in shots for a in (s.get("action_types") or [])}))
    print("shots: lens", sorted({s["camera"].get("lens") for s in shots}))
    print("shots: declared.transition", sorted({(s.get("declared") or {}).get("transition")
                                                for s in shots}))
    print("shots: movements.kind", sorted({m.get("kind") for s in shots
                                           for m in (s.get("movements") or [])}))
    print("shots: has vfx key?", any("vfx" in s for s in shots))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
