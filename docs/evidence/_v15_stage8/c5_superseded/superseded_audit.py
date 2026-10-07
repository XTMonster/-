"""C5: which in-repo runs are 'superseded' by the current generation?

Read-only. Resolves every run's pinned holdout sha against the generation
registry (`fixtures/knowledge_holdout.generations.json`) so "superseded" is
derived from the registry, not from prose.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
while not (ROOT / "pyproject.toml").is_file() and ROOT.parent != ROOT:
    ROOT = ROOT.parent

REGISTRY = ROOT / "fixtures" / "knowledge_holdout.generations.json"
EVIDENCE = ROOT / "docs" / "evidence"


def pinned_holdout(manifest: dict) -> str:
    pins = manifest.get("pins") or {}
    entry = pins.get("holdout")
    if isinstance(entry, dict):
        return str(entry.get("sha256") or "")
    return str(entry or "")


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    current = str(registry.get("current") or "")
    by_sha: dict = {}
    for generation in registry.get("generations") or []:
        sha = str((generation.get("inputs") or {}).get("holdout") or "")
        if sha:
            by_sha.setdefault(sha, []).append(str(generation.get("id")))

    rows = []
    for manifest_path in sorted(EVIDENCE.glob("*/run_manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001 - a broken manifest is reported, not fatal
            continue
        sha = pinned_holdout(manifest)
        if not sha:
            continue
        generations = by_sha.get(sha, [])
        if not generations:
            verdict = "待定（pin 不在登记表里）"
        elif current in generations:
            verdict = "不失据（pin == 现行代）"
        else:
            verdict = "待定（异代；裁定明说不能定案）"
        rows.append({
            "run": manifest_path.parent.name,
            "holdout_sha256_16": sha[:16],
            "resolved_generations": generations,
            "verdict": verdict,
        })

    payload = {
        "current_generation": current,
        "runs_with_holdout_pin": len(rows),
        "by_verdict": {v: sum(1 for r in rows if r["verdict"] == v)
                       for v in sorted({r["verdict"] for r in rows})},
        "runs": rows,
    }
    out = Path(__file__).with_name("superseded_audit.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "runs"},
                     ensure_ascii=False))
    for row in rows:
        print(f"  {row['run']:34} {row['holdout_sha256_16']} "
              f"{row['resolved_generations']} -> {row['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
