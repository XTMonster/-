"""A 路的第一步：把**散文片段**压成**短知识陈述**（卡片形状）。

为什么需要它（实测 2026-10-05 的证据链）：现役 v18 抽取器是在**卡片**上工作的，
而 v4 现在把 700–1,040 字的学术散文段直接喂进去；同一批输入上提示词每加一层
schema 细节产量就掉一截（21 → 4 → 0 → 0 → 0）。⇒ 问题很可能在**输入形状**：
模型要一边读散文、一边把它塞进一套不认识的抽象槽位，于是选择空手。

本层只干一件事：把一段散文压成若干条**短陈述**，每条都必须是这段里说过的。
之后的抽取就回到"在短知识单元上抽边"——也就是 v18 那套已被验证过的形态。

四条纪律：

1. **可回溯**：每条带 `source`（url／sha256／该段 span），供 P5 的 `to_edge` 回查；
2. **解析失败具名**（`parse_fault:*`），不静默跳过；
3. **账目闭合**：`kept + rejected == statements_seen`（解析失败的段单列 `segments_failed`）；
4. **复述不算蒸馏**：超过 `max_statement_chars` 的"陈述"判 `too_long`。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import common  # type: ignore
    from . import extract_segmented as ex  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.kb_fetch import common  # type: ignore
    from tools.kb_fetch import extract_segmented as ex  # type: ignore

PROMPT_VERSION = "distill/v1"

#: 一条"短知识陈述"最多多少字符。超过它就是把原文复述回来了。
DEFAULT_MAX_STATEMENT_CHARS = 120
#: 一个片段最多要几条（防止模型把一段拆成二十条碎片）。
DEFAULT_MAX_STATEMENTS = 6

SYSTEM = (
    "你是知识蒸馏器。给你一段**他人著作**里的文字，请把它里面**可判定的知识陈述**"
    "逐条摘出来。\n"
    "只输出 JSON：{\"statements\":[\"<陈述>\",...]}。\n"
    "规则：①每条 20–60 字，一句一件事；②**只写这段里说过的**，不许发明、不许外推；"
    "③不要评论、不要总结、不要复述整段；④这段里没有可判定的知识就返回空数组；"
    "⑤不要把作者举的例子当成规则（「某片用了 X」不是「该用 X」）。"
)


def distill_prompt(segment_text: str, *,
                   max_statements: int = DEFAULT_MAX_STATEMENTS) -> str:
    return ("%s\n\n最多 %d 条。\n\n原文：\n%s"
            % (SYSTEM, max_statements, segment_text))


def parse_statements(reply: str) -> Tuple[List[str], Optional[str]]:
    """解回包：返回 ``(statements, fault)``。"""
    text = str(reply or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        payload = json.loads(text.strip() or "{}")
    except ValueError as exc:
        return [], "parse_fault:%s" % exc
    raw = payload.get("statements") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return [], "parse_fault:no_statements_array"
    return [str(item).strip() for item in raw if str(item).strip()], None


def distill(records: Iterable[Dict], *, llm: Callable[[str], str],
            max_chars: int = ex.DEFAULT_MAX_CHARS,
            min_chars: int = ex.DEFAULT_MIN_CHARS,
            limit_segments: int = 0,
            max_statement_chars: int = DEFAULT_MAX_STATEMENT_CHARS,
            max_statements: int = DEFAULT_MAX_STATEMENTS
            ) -> Tuple[List[Dict], List[Dict], Dict]:
    """逐片段蒸馏。返回 ``(statements, rejects, stats)``。

    每条输出的形状与 P4 的"记录"兼容（`source_ref` ＋ `text`），所以可以直接喂回
    `extract_segmented.extract()`——那时候它已经是在**短知识单元**上抽边了。
    """
    statements_out: List[Dict] = []
    rejects: List[Dict] = []
    segments_seen = 0
    skipped_short = 0
    statements_seen = 0
    segments_failed = 0
    calls = 0
    for record in records:
        source_ref = dict(record.get("source_ref") or {})
        for segment in ex.segment_text(str(record.get("text") or ""),
                                       source_ref=source_ref, max_chars=max_chars):
            if limit_segments and segments_seen >= limit_segments:
                break
            segments_seen += 1
            if len(segment.text) < min_chars:
                skipped_short += 1
                continue
            where = {"url": source_ref.get("url"), "sha256": source_ref.get("sha256"),
                     "span": list(segment.span)}
            try:
                calls += 1
                items, fault = parse_statements(
                    llm(distill_prompt(segment.text, max_statements=max_statements)))
            except Exception as exc:  # noqa: BLE001 - 单段失败不吞掉整批
                items, fault = [], "llm_error:%s: %s" % (type(exc).__name__, exc)
            if fault is not None:
                segments_failed += 1
                rejects.append({"reason": fault, "source": where})
                continue
            for item in items[:max_statements]:
                statements_seen += 1
                if len(item) > max_statement_chars:
                    rejects.append({"reason": "too_long:%d" % len(item), "source": where,
                                    "statement": item[:80]})
                    continue
                #: 两种形状并存：`source_ref` 让这条陈述能直接当 P4 的"记录"喂回去，
                #: `source` 是它的**出处指针**（url／sha256／span），P5 的 `to_edge`
                #: 靠它把成员依据回查到原文。
                statements_out.append({"source_ref": source_ref, "text": item,
                                       "source": where})
    stats = {"segments": segments_seen, "skipped_short": skipped_short,
             "statements_seen": statements_seen, "kept": len(statements_out),
             "rejected": len(rejects), "segments_failed": segments_failed,
             "calls": calls}
    return statements_out, rejects, stats


STATEMENTS_NAME = "statements.jsonl"
REJECTS_NAME = "distill_rejected.jsonl"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.distill_segments")
    parser.add_argument("--corpus", default=str(common.WORK / "corpus_v4"))
    parser.add_argument("--out", required=True, help="产物目录，例如 work/statements_v4")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--max-chars", type=int, default=ex.DEFAULT_MAX_CHARS)
    parser.add_argument("--min-chars", type=int, default=ex.DEFAULT_MIN_CHARS)
    parser.add_argument("--limit-records", type=int, default=0)
    parser.add_argument("--limit-segments", type=int, default=0)
    parser.add_argument("--max-statement-chars", type=int,
                        default=DEFAULT_MAX_STATEMENT_CHARS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    records = ex.load_records(pathlib.Path(args.corpus))
    if args.limit_records:
        records = records[:args.limit_records]
    statements, rejects, stats = distill(
        records, llm=ex.DeepSeekClient(model=args.model), max_chars=args.max_chars,
        min_chars=args.min_chars, limit_segments=args.limit_segments,
        max_statement_chars=args.max_statement_chars)
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    common.write_jsonl(out_dir / STATEMENTS_NAME, statements)
    common.write_jsonl(out_dir / REJECTS_NAME, rejects)
    print(json.dumps({"overall": "pass", "prompt_version": PROMPT_VERSION,
                      "model": args.model, **stats, "out": str(out_dir)},
                     ensure_ascii=False))
    return 0 if statements else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
