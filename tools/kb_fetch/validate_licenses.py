"""管线第 4 步：许可门（§2.3c）。

不过门即**拒收**（进 `work/license_rejects.jsonl`），不做"警告后仍入库"。
判定：许可在白名单内 ＋ `source_ref` 六字段全非空 ＋ 正文长度下限。
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
LICENSED = common.WORK / "licensed.jsonl"
LICENSE_REJECTS = common.WORK / "license_rejects.jsonl"

#: 太短的正文无法承载一条可复用的知识条目——低于此值拒收（防止把目录页当语料）。
MIN_DOC_CHARS = 600


def check(record: Dict) -> Tuple[bool, str]:
    #: 出处＋许可那两判一律走 `common.source_and_licence_ok`——它是**唯一实现**
    #: （此前 `validate_licenses` / `import_cards` / `find_arxiv_sources` 各抄一份，
    #: 见 `common.source_and_licence_ok` 的 docstring）。这一步**特有**的是正文长度下限。
    ok, reason = common.source_and_licence_ok(record.get("source_ref"))
    if not ok:
        return False, reason
    if len(str(record.get("text", ""))) < MIN_DOC_CHARS:
        return False, f"text_too_short:{len(str(record.get('text', '')))}"
    return True, ""


def run(records: Sequence[Dict]) -> Tuple[List[Dict], List[Dict]]:
    kept: List[Dict] = []
    rejects: List[Dict] = []
    for record in records:
        if record.get("dup_of"):
            continue  # 文档级重复：不进许可门，也不计入卡片计数
        ok, reason = check(record)
        if ok:
            kept.append(record)
        else:
            rejects.append({"source_ref": record.get("source_ref", {}),
                            "domain": record.get("domain", ""),
                            "reason": reason})
    common.write_jsonl(LICENSED, kept)
    common.write_jsonl(LICENSE_REJECTS, rejects)
    return kept, rejects


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.validate_licenses")
    args = parser.parse_args(list(argv) if argv is not None else None)  # noqa: F841
    records = common.read_jsonl(DEDUPED)
    kept, rejects = run(records)
    print(json.dumps({"licensed": len(kept), "rejected": len(rejects),
                      "rejects": rejects[:10]}, ensure_ascii=False))
    return 0 if kept else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
