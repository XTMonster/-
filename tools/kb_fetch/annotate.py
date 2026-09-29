"""管线第 6 步：标注 / 抽取卡片（§2.3c 的 `annotate.py`，LLM 建议 ＋ 机器校验）。

模型只负责"从一段语料里读出可复用的知识条目"；**能不能入库由机器判**：

* `quote` 必须是片段里**逐字**出现的子串（允许空白差异）；
* 引用块 ≤2 句且 ≤120 字（§2.3d 的"改写而非转载"）；
* `domain` 取来源声明的域（K3 的分域计数因此可复算）。

断点续跑绑在**六元指纹**上：语料 sha256 / 抽取器 model id / prompt 版本 /
切块版本 / 解码参数 / schema 版本——指纹变了就整体重抽（§2.3）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from . import common, llm
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common, llm  # type: ignore

CHUNKS = common.WORK / "chunks.jsonl"
ANNOTATED = common.WORK / "annotated.jsonl"
ANNOTATE_REJECTS = common.WORK / "annotate_rejects.jsonl"
MANIFEST = common.WORK / "annotate.manifest.json"

MIN_CARDS_PER_CHUNK = 1
MAX_CARDS_PER_CHUNK = 16
MIN_CONTENT_CHARS = 24
MAX_CONTENT_CHARS = 900
CHECKPOINT_EVERY = 10

SYSTEM_PROMPT = """你是电影 / 动画分镜知识库的语料标注员。你的工作是从给定的【语料片段】里\
抽出**能指导拍摄的规则性知识**，供一个 Blender 白模预演引擎检索使用。

硬规则（违反的条目会被机器丢弃）：
0. **只抽"这一镜该怎么拍"的知识**：构图、机位、镜头、光线、色彩、运动、剪辑、
   节奏、调度、表演、分镜写法、段落结构。**禁止**抽取商业价格、票房、市场、
   器材广告、公司历史、人物轶事、版权与出版信息；片段里只有这些内容时，输出空数组
   （宁缺勿滥——这种片段不会被当成构建失败）。
1. 每条知识必须是**改写**后的规则、条件→取舍、或术语定义，禁止整段照抄原文。
   正文用中文写；`quote` 保留原文语言（可以是英文）。
2. 每条必须给 `quote`：从【语料片段】里**逐字复制**的连续短引用，**最多 2 句**且**不超过 120 字**。
   `quote` 必须能在片段里原样找到，不得改写、不得拼接不相邻的两段。
3. 条数 = 片段里**真正独立**的知识点数量（0–14 条）。片段信息少就少给；不要凑数、不要同义重复；
   同一段文字里的同一件事只写一条。
4. `content` 必须具体可执行：带上条件、取值或取舍（例如"拍两人对话时，机位高度取眼睛高度，
   越轴只在用中性机位或运动过渡时才允许"）。禁止"要注意构图"这类空话。
5. `title` ≤ 14 字；`keywords` 3–6 个；`tags` 是可检索的手法词（如"推镜""压迫""特写"）；
   `emotion` 填这条知识主要服务的情绪（没有就留空字符串）；`rules` 填片段里出现的规则编号（没有就空数组）。
6. 只输出 JSON，形如 {"cards":[{"title":..,"content":..,"quote":..,"keywords":[..],"tags":[..],"rules":[..],"emotion":..}]}

示例（格式示范，内容与本次片段无关）：
{"cards":[{"title":"越轴的安全过渡","content":"相邻两镜必须留在两人连线同侧；若必须越轴，用中性机位、\
演员走位或运动镜头过渡，不要硬切。","quote":"越轴只能在运动中或经由中性镜头完成。",\
"keywords":["越轴","轴线","中性镜头"],"tags":["轴线","连续性"],"rules":["R012"],"emotion":""}]}
"""


def corpus_fingerprint(chunks: Sequence[Dict]) -> str:
    payload = "".join(sorted(c["sha256"] for c in chunks))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def decode_params(temperature: float, seed: int, num_ctx: int) -> str:
    return f"t={temperature};seed={seed};ctx={num_ctx}"


def fingerprint(chunks: Sequence[Dict], model_id: str, decode: str) -> str:
    six = [
        corpus_fingerprint(chunks),
        model_id,
        common.ANNOTATE_PROMPT_VERSION,
        common.CHUNKER_VERSION,
        decode,
        common.SCHEMA_VERSION,
    ]
    return hashlib.sha256("|".join(six).encode("utf-8")).hexdigest()


def build_user_prompt(chunk: Dict) -> str:
    return (f"知识域：{chunk['domain']}\n"
            f"题材：{chunk.get('genre') or '未标注'}\n"
            f"主题：{chunk.get('theme') or '未标注'}\n"
            f"来源：{chunk['source_ref']['title']}（{chunk['source_ref']['author']}）\n\n"
            f"【语料片段】\n{chunk['text']}\n【片段结束】")


def validate_card(raw: Dict, chunk: Dict) -> Tuple[Optional[Dict], str]:
    if not isinstance(raw, dict):
        return None, "card_not_object"
    title = str(raw.get("title", "")).strip()
    content = str(raw.get("content", "")).strip()
    quote = str(raw.get("quote", "")).strip()
    if not title or not content:
        return None, "card_missing_title_or_content"
    if len(title) > 40:
        return None, "title_too_long"
    if not (MIN_CONTENT_CHARS <= len(content) <= MAX_CONTENT_CHARS):
        return None, f"content_length:{len(content)}"
    ok, reason = common.quote_check(quote)
    if not ok:
        return None, reason
    if not common.quote_is_verbatim(quote, chunk["text"]):
        return None, "quote_not_verbatim"
    card = {
        "title": title,
        "content": content,
        "quote": quote,
        "keywords": [str(k).strip() for k in (raw.get("keywords") or []) if str(k).strip()][:8],
        "tags": [str(t).strip() for t in (raw.get("tags") or []) if str(t).strip()][:8],
        "rules": [str(r).strip() for r in (raw.get("rules") or []) if str(r).strip()][:6],
        "emotion": str(raw.get("emotion", "") or "").strip()[:24],
    }
    return card, ""


def annotate_chunk(client, chunk: Dict, temperature: float, seed: int,
                   num_ctx: int) -> Tuple[List[Dict], List[str]]:
    reply = client.chat_json(SYSTEM_PROMPT, build_user_prompt(chunk),
                             temperature, seed, num_ctx, key=chunk["chunk_id"])
    raw_cards = reply.get("cards") if isinstance(reply, dict) else None
    if not isinstance(raw_cards, list):
        return [], ["reply_not_a_card_list"]
    cards: List[Dict] = []
    reasons: List[str] = []
    seen_titles = set()
    for raw in raw_cards[:MAX_CARDS_PER_CHUNK]:
        card, reason = validate_card(raw, chunk)
        if card is None:
            reasons.append(reason)
            continue
        key = re.sub(r"\s+", "", card["title"])
        if key in seen_titles:
            reasons.append("duplicate_title_in_chunk")
            continue
        seen_titles.add(key)
        cards.append(card)
    return cards, reasons


def _checkpoint(fp: str, client, decode: str, total: int,
                manifest_chunks: List[Dict], annotated: List[Dict],
                rejects: List[Dict]) -> None:
    """长跑任务每 10 段落一次盘：中断后按指纹与 chunk sha256 续跑，不重抽。"""
    existing: Dict[str, Dict] = {}
    if MANIFEST.exists():
        try:
            previous = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        for entry in previous.get("chunks", []):
            existing[entry["chunk_id"]] = entry
    for entry in manifest_chunks:
        existing[entry["chunk_id"]] = entry
    common.write_jsonl(ANNOTATED, annotated)
    common.write_jsonl(ANNOTATE_REJECTS, rejects)
    common.dump_json(MANIFEST, {
        "fingerprint": fp,
        "extractor": {"model_id": client.model_id, "family": client.family,
                      "model_version": client.model_version},
        "decode": decode,
        "chunker_version": common.CHUNKER_VERSION,
        "schema_version": common.SCHEMA_VERSION,
        "prompt_version": common.ANNOTATE_PROMPT_VERSION,
        "total_chunks": total,
        "chunks": sorted(existing.values(), key=lambda c: c["chunk_id"]),
    })


def run(chunks: Sequence[Dict], client, temperature: float = 0.0, seed: int = 0,
        num_ctx: int = 8192, limit: int = 0, progress=None) -> Tuple[List[Dict], List[Dict]]:
    decode = decode_params(temperature, seed, num_ctx)
    fp = fingerprint(chunks, client.model_id, decode)
    done: Dict[str, Dict] = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if manifest.get("fingerprint") == fp:
            by_chunk = {c["chunk_id"]: c for c in manifest.get("chunks", [])
                        if c.get("status") == "done"}
            # §2.3 的断点续跑纪律：**先比指纹，再比 per-chunk sha256**——
            # 同一 id 换了正文（改了笔记、改了切块）必须重抽，不能复用旧结果。
            done = {c["chunk_id"]: by_chunk[c["chunk_id"]] for c in chunks
                    if c["chunk_id"] in by_chunk
                    and by_chunk[c["chunk_id"]].get("sha256") == c["sha256"]}

    annotated: List[Dict] = []
    rejects: List[Dict] = []
    manifest_chunks: List[Dict] = []
    todo = [c for c in chunks if c["chunk_id"] not in done]
    if limit:
        todo = todo[:limit]

    # 指纹未变时，已标注的 chunk 直接复用上次的记录——否则 `annotated.jsonl`
    # 会随着每次续跑而缩水（只剩本次新增的部分），导入计数跟着失真。
    previous_records = {r["chunk_id"]: r for r in common.read_jsonl(ANNOTATED)}
    for chunk_id in done:
        if chunk_id in previous_records:
            annotated.append(previous_records[chunk_id])

    for index, chunk in enumerate(todo, 1):
        if progress:
            progress(index, len(todo), chunk["chunk_id"])
        cards, reasons = annotate_chunk(client, chunk, temperature, seed, num_ctx)
        if len(cards) < MIN_CARDS_PER_CHUNK:
            rejects.append({"chunk_id": chunk["chunk_id"], "domain": chunk["domain"],
                            "reasons": reasons or ["no_cards"], "chars": len(chunk["text"])})
            manifest_chunks.append({"chunk_id": chunk["chunk_id"], "sha256": chunk["sha256"],
                                    "status": "rejected", "cards": [],
                                    "reject_reason": ",".join(reasons or ["no_cards"])})
        else:
            record = {
                "chunk_id": chunk["chunk_id"],
                "sha256": chunk["sha256"],
                "domain": chunk["domain"],
                "genre": chunk.get("genre", ""),
                "theme": chunk.get("theme", ""),
                "source_ref": chunk["source_ref"],
                "cards": cards,
                "dropped_cards": reasons,
                "extractor": {"model_id": client.model_id,
                              "family": client.family,
                              "model_version": client.model_version},
            }
            annotated.append(record)
            manifest_chunks.append({"chunk_id": chunk["chunk_id"], "sha256": chunk["sha256"],
                                    "status": "done", "cards": [c["title"] for c in cards]})
        if index % CHECKPOINT_EVERY == 0:
            _checkpoint(fp, client, decode, len(chunks), manifest_chunks, annotated, rejects)

    for chunk_id, entry in done.items():  # 指纹未变：复用上次结果
        manifest_chunks.append({**entry, "status": "done"})

    common.write_jsonl(ANNOTATED, annotated)
    common.write_jsonl(ANNOTATE_REJECTS, rejects)
    existing = {}
    for entry in manifest_chunks:
        existing.setdefault(entry["chunk_id"], entry)
    common.dump_json(MANIFEST, {
        "fingerprint": fp,
        "extractor": {"model_id": client.model_id, "family": client.family,
                      "model_version": client.model_version},
        "decode": decode,
        "chunker_version": common.CHUNKER_VERSION,
        "schema_version": common.SCHEMA_VERSION,
        "prompt_version": common.ANNOTATE_PROMPT_VERSION,
        "total_chunks": len(chunks),
        "chunks": sorted(existing.values(), key=lambda c: c["chunk_id"]),
    })
    return annotated, rejects


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.annotate")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--domain", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    chunks = common.read_jsonl(CHUNKS)
    if args.domain:
        chunks = [c for c in chunks if c["domain"] == args.domain]
    client = llm.make_client(args.provider, args.model, args.scripted)

    def progress(index: int, total: int, chunk_id: str) -> None:
        print(f"[{index}/{total}] {chunk_id}", flush=True)

    annotated, rejects = run(chunks, client, args.temperature, args.seed,
                             args.num_ctx, args.limit, progress)
    total_cards = sum(len(r["cards"]) for r in annotated)
    print(json.dumps({"chunks_annotated": len(annotated), "chunks_rejected": len(rejects),
                      "cards": total_cards}, ensure_ascii=False))
    return 0 if annotated else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
