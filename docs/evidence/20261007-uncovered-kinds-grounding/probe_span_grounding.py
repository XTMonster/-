"""那 1,262 个 `unattested` 槽位：是**没出处**，还是"出处里有、只是卡里没写"？

佐证判据（`attest/v1`）比的是**卡正文**。而每条边另存了 `source_span{chunk_id,start,end}`
——指向**语料原文**。本探针把源文 span 取出来，看成员取值在**原文**里到底有没有。

三种结果：`in_span`（原文里有）／`in_corpus_elsewhere`（语料别处有）／`nowhere`（整个语料都没有）。
"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from tools.knowledge import attestation as att  # noqa: E402


def corpus_text(chunk_id: str) -> str:
    """按 `chunk_id` 在语料里找原文（`work/corpus_v4/fetched.jsonl` 这类）。"""
    for path in list((ROOT / "work/corpus_v4").glob("*.jsonl")) + \
            list((ROOT / "knowledge").glob("**/corpus*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
            line = line.strip()
            if not line or chunk_id not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            for key in ("text", "content", "body"):
                if isinstance(row.get(key), str):
                    return row[key]
            chunks = row.get("chunks")
            if isinstance(chunks, list):
                for chunk in chunks:
                    if str((chunk or {}).get("id")) == chunk_id:
                        return str(chunk.get("text") or "")
    return ""


def main() -> int:
    cards = att.load_cards(ROOT / "knowledge/cards_generated")
    edges = [row for row in att.load_jsonl(ROOT / "knowledge/hypergraph.edges.jsonl")
             if isinstance(row, dict) and row.get("edge_id")]
    verdicts = collections.Counter()
    samples = []
    for edge in edges:
        labels = att.labels_for(edge, cards) if hasattr(att, "labels_for") else None
        span = edge.get("source_span") or {}
        chunk_id = str(span.get("chunk_id") or "")
        text = corpus_text(chunk_id) if chunk_id else ""
        start, end = int(span.get("start") or 0), int(span.get("end") or 0)
        window = text[start:end] if text and end > start else text[:4000]
        for member in edge.get("members") or []:
            if len(member) != 3:
                continue
            value = str(member[2]).split(":", 1)[-1]
            if len(value) < 2:
                continue
            if value in window:
                verdicts["in_span"] += 1
            elif text and value in text:
                verdicts["in_corpus_elsewhere"] += 1
            elif not text:
                verdicts["corpus_not_found"] += 1
            else:
                verdicts["nowhere"] += 1
                if len(samples) < 5:
                    samples.append({"edge": edge.get("edge_id"), "value": value,
                                    "chunk": chunk_id, "span": [start, end]})
    print(json.dumps({"verdicts": dict(verdicts), "nowhere_samples": samples,
                      "note": "只看成员取值在**语料原文**里有没有 surface；不是判据"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
