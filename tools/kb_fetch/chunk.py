"""管线第 5 步：切块（段落优先，句边界兜底；§2.3c 的 `chunk.py`）。

切块策略版本写进每条记录（`chunker_version`），并进六元指纹——改切块就会
整体重抽，而不是复用旧边（§2.3 的"缓存与断点续跑"）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Dict, List, Optional, Sequence

try:
    from . import common
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common  # type: ignore

LICENSED = common.WORK / "licensed.jsonl"
CHUNKS = common.WORK / "chunks.jsonl"

TARGET_CHARS = 2400
MAX_CHARS = 3200
MIN_CHARS = 500

#: 逐域的"这一镜该怎么拍"关键词表：用来把几百页老书里**真正讲拍法**的段落挑出来。
#: 老书里大量篇幅是商业、器材广告与人物轶事，均匀取样会拿到一堆与镜头无关的内容
#: （实测 8 段里 6 段抽不出卡片）。这是一份**可审计的确定性筛选**，不是模型判断。
DOMAIN_KEYWORDS = {
    "cinematography": (
        "camera", "lens", "focus", "exposure", "aperture", "focal", "tripod",
        "pan", "tilt", "close-up", "distance", "angle", "light", "shadow",
        "screen", "movement", "viewpoint", "foreground", "background",
    ),
    "composition": (
        "composition", "balance", "line", "mass", "tone", "perspective",
        "arrange", "centre", "center", "foreground", "background", "pyramid",
        "contrast", "symmetry", "picture",
    ),
    "editing": (
        "cut", "continuity", "sequence", "rhythm", "tempo", "dissolve",
        "transition", "fade", "scene", "attention", "memory", "impression",
    ),
    "storyboard": (
        "photoplay", "scenario", "plot", "scene", "action", "climax",
        "situation", "suspense", "character", "drama", "story", "incident",
    ),
    "blocking": (
        "stage", "position", "cross", "business", "group", "entrance",
        "exit", "actor", "rehearsal", "movement", "upstage", "downstage",
    ),
    "performance": (
        "actor", "emotion", "gesture", "expression", "voice", "rehearsal",
        "tempo", "character", "feeling", "pantomime", "face",
    ),
    "anime": (
        "animation", "cartoon", "drawing", "cel", "movement", "action",
        "run", "cycle", "silhouette", "line",
    ),
    "production": (
        "stage", "electric", "arc", "lamp", "switchboard", "projector",
        "screen", "production", "scene", "operator", "current",
    ),
    "axis_theory": ("axis", "line", "direction", "side"),
}


def relevance_score(text: str, domain: str) -> int:
    lowered = text.lower()
    return sum(lowered.count(word) for word in DOMAIN_KEYWORDS.get(domain, ()))


def select_relevant(pieces: Sequence[str], limit: int, domain: str) -> List[str]:
    """按域关键词取最相关的 `limit` 段；相关段不足时按原文顺序补齐。"""
    if limit <= 0 or len(pieces) <= limit:
        return list(pieces)
    scored = sorted(range(len(pieces)),
                    key=lambda i: (-relevance_score(pieces[i], domain), i))
    picked = [i for i in scored[:limit] if relevance_score(pieces[i], domain) > 0]
    for index in sorted(range(len(pieces))):
        if len(picked) >= limit:
            break
        if index not in picked:
            picked.append(index)
    return [pieces[i] for i in sorted(picked)]


def split_paragraphs(text: str) -> List[str]:
    parts = [p.strip() for p in text.split("\n\n")]
    return [p for p in parts if p]


def _split_long(paragraph: str) -> List[str]:
    sentences = common.split_sentences(paragraph)
    out: List[str] = []
    buffer = ""
    for sentence in sentences:
        if buffer and len(buffer) + len(sentence) > MAX_CHARS:
            out.append(buffer)
            buffer = ""
        buffer += sentence
        while len(buffer) > MAX_CHARS:  # 单句就超长时按硬边界切开
            out.append(buffer[:MAX_CHARS])
            buffer = buffer[MAX_CHARS:]
    if buffer:
        out.append(buffer)
    return out


def section_units(text: str) -> List[str]:
    """按 `## ` 小标题切段：自撰笔记天然按主题分节，一节一个 chunk 更聚焦。"""
    sections: List[str] = []
    current: List[str] = []
    for line in text.split("\n"):
        if line.startswith("## ") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))
    return sections


def _chunk_blocks(text: str) -> List[str]:
    units: List[str] = []
    for paragraph in split_paragraphs(text):
        if len(paragraph) > MAX_CHARS:
            units.extend(_split_long(paragraph))
        else:
            units.append(paragraph)
    chunks: List[str] = []
    buffer = ""
    for unit in units:
        if buffer and len(buffer) + len(unit) + 2 > TARGET_CHARS:
            chunks.append(buffer)
            buffer = unit
        else:
            buffer = f"{buffer}\n\n{unit}" if buffer else unit
    if buffer:
        if chunks and len(buffer) < MIN_CHARS:
            chunks[-1] = chunks[-1] + "\n\n" + buffer
        else:
            chunks.append(buffer)
    return chunks


def chunk_document(text: str) -> List[str]:
    """先按小标题分节（若有），再在节内按段落合并到 `TARGET_CHARS`。"""
    if any(line.startswith("## ") for line in text.split("\n")):
        out: List[str] = []
        for section in section_units(text):
            out.extend(_chunk_blocks(section))
        return [c for c in out if c.strip()]
    return [c for c in _chunk_blocks(text) if c.strip()]


def select_evenly(pieces: Sequence[str], limit: int) -> List[str]:
    """从正文中段均匀取样 `limit` 段：跳过前置页（目录/序）与尾部（索引/广告）。"""
    if limit <= 0 or len(pieces) <= limit:
        return list(pieces)
    start = int(len(pieces) * 0.05)
    stop = max(start + limit, int(len(pieces) * 0.95))
    window = list(range(start, min(stop, len(pieces))))
    if len(window) <= limit:
        return [pieces[i] for i in window]
    step = (len(window) - 1) / (limit - 1) if limit > 1 else 0
    picked = sorted({window[round(i * step)] for i in range(limit)})
    return [pieces[i] for i in picked]


def run(records: Sequence[Dict], per_domain_chunks: int = 0,
        max_per_source: int = 0) -> List[Dict]:
    by_domain: Dict[str, List[Dict]] = {}
    for record in records:
        by_domain.setdefault(record["domain"], []).append(record)

    budget: Dict[str, int] = {}
    if per_domain_chunks:
        for domain, items in by_domain.items():
            budget[domain] = per_domain_chunks

    out: List[Dict] = []
    for domain, items in by_domain.items():
        per_source = 0
        if budget.get(domain):
            per_source = max(1, -(-budget[domain] // len(items)))  # ceil
        if max_per_source:
            per_source = min(per_source or max_per_source, max_per_source) \
                if per_source else max_per_source
        for record in items:
            slug = common.source_slug({"url": record["source_ref"]["url"]})
            if record.get("mode") == "manual":
                # 自撰笔记：一节一个 chunk（每个小标题就是一条独立知识点），
                # 合并成 2400 字会把不同主题搅在一起，抽取质量反而下降。
                candidates = [s for s in section_units(record["text"]) if s.strip()]
                if len(candidates) <= 1:
                    candidates = chunk_document(record["text"])
            else:
                candidates = chunk_document(record["text"])
            if not per_source:
                pieces = candidates
            elif record.get("mode") == "manual":
                pieces = select_evenly(candidates, per_source)
            else:
                pieces = select_relevant(candidates, per_source, record["domain"])
            for index, text in enumerate(pieces):
                out.append({
                    "chunk_id": f"{slug}#{index:03d}",
                    "source_ref": record["source_ref"],
                    "domain": record["domain"],
                    "genre": record.get("genre", ""),
                    "theme": record.get("theme", ""),
                    "ordinal": index,
                    "text": text,
                    "sha256": common.sha256_text(text),
                    "chunker_version": common.CHUNKER_VERSION,
                })
    common.write_jsonl(CHUNKS, out)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.chunk")
    parser.add_argument("--per-domain-chunks", type=int, default=0,
                        help="每个域最多取多少段（0 = 不限制）")
    parser.add_argument("--max-per-source", type=int, default=0,
                        help="每个来源最多取多少段（0 = 不限制）")
    args = parser.parse_args(list(argv) if argv is not None else None)
    chunks = run(common.read_jsonl(LICENSED), args.per_domain_chunks, args.max_per_source)
    counts: Dict[str, int] = {}
    for item in chunks:
        counts[item["domain"]] = counts.get(item["domain"], 0) + 1
    print(json.dumps({"chunks": len(chunks), "per_domain": counts}, ensure_ascii=False))
    return 0 if chunks else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
