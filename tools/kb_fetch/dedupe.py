"""管线第 3 步：去重（sha256 ＋ SimHash ≥0.9，§2.3c）。

同一份正文的第二次出现（含近重复）会被标 `dup_of`，并在导入时计入
`cards_deduped`——它**不是** `cards_rejected`（§2.3c 的计数口径）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from . import common
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common  # type: ignore

DEDUPED = common.WORK / "deduped.jsonl"
EXTRACTED = common.WORK / "extracted.jsonl"


def dedupe(records: Sequence[Dict]) -> Tuple[List[Dict], int]:
    """返回 (记录列表, 被判定为重复的文档数)。第一份出现的保留。"""
    kept: List[Dict] = []
    seen_exact: Dict[str, str] = {}
    seen_sim: List[Tuple[int, str]] = []
    duplicates = 0
    for record in records:
        digest = record["source_ref"]["sha256"]
        url = record["source_ref"]["url"]
        if digest in seen_exact:
            duplicates += 1
            kept.append({**record, "dup_of": seen_exact[digest]})
            continue
        sim = common.simhash64(record["text"])
        near = next((src for src, dist in
                     ((u, common.hamming(sim, s)) for s, u in seen_sim)
                     if dist <= common.SIMHASH_MAX_HAMMING), "")
        if near:
            duplicates += 1
            kept.append({**record, "dup_of": near})
            continue
        seen_exact[digest] = url
        seen_sim.append((sim, url))
        kept.append({**record, "dup_of": ""})
    return kept, duplicates


def run(records: Sequence[Dict]) -> Tuple[List[Dict], int]:
    deduped, duplicates = dedupe(records)
    common.write_jsonl(DEDUPED, deduped)
    return deduped, duplicates


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.dedupe")
    args = parser.parse_args(list(argv) if argv is not None else None)  # noqa: F841
    records = common.read_jsonl(EXTRACTED)
    deduped, duplicates = run(records)
    print(json.dumps({"documents": len(deduped), "deduped": duplicates}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
