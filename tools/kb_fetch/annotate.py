"""管线第 6 步：标注 / 抽取卡片（§2.3c 的 `annotate.py`，LLM 建议 ＋ 机器校验）。

模型只负责"从一段语料里读出可复用的知识条目"；**能不能入库由机器判**：

* `quote` 必须是片段里**逐字**出现的子串（允许空白差异）；
* 引用块 ≤2 句且 ≤120 字（§2.3d 的"改写而非转载"）；
* `domain` 取来源声明的域（K3 的分域计数因此可复算）。

断点续跑绑在**六元指纹**上：语料 sha256 / 抽取器 model id / prompt 版本 /
切块版本 / 解码参数 / schema 版本——指纹变了就整体重抽（§2.3）。

**增量入库（v1.5，`--incremental`）**：语料是会长的。默认口径（strict）在指纹
任何一位变化时整体重抽——旧书那 298 段为此要重烧一遍 API，而它们一个字节都没变。
`--incremental` 把"一份指纹"换成"若干 pass"：每个 pass 记下**它自己抽过的
chunk_id → sha256**、模型与解码参数，并用与 strict 完全相同的公式自证（
`fingerprint_of_shas`）。复用条件是三条同时成立：

1. 该 pass 的指纹按当前 prompt/切块/schema 口径重算后仍等于记录值（口径升级 → 整体失效）；
2. chunk 的 sha256 与该 pass 记录的一致（正文变了 → 只重抽这一段）；
3. `annotated.jsonl` 里确有这条记录（产物与账本必须对得上）。

换模型**不**使旧 pass 失效：每条记录都带自己的 `extractor`，族与版本可逐条审计，
而"这段正文在这个 prompt/切块口径下已经抽过"这一事实与是谁抽的无关。
宁严勿松：任何一条不成立就重抽，`--incremental` 从不降低 `validate_card` 的标准。
"""

from __future__ import annotations

import argparse
import concurrent.futures
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

#: 清单结构版本。v1 是"一份全局指纹 + 一张 chunk 状态表"；v2 在它之上加
#: `passes[]`（见模块 docstring）。v2 仍然写 v1 的全部字段，旧读者不会瞎。
MANIFEST_VERSION = 2

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
    return corpus_fingerprint_of([c["sha256"] for c in chunks])


def corpus_fingerprint_of(shas: Sequence[str]) -> str:
    payload = "".join(sorted(str(sha) for sha in shas))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def decode_params(temperature: float, seed: int, num_ctx: int) -> str:
    return f"t={temperature};seed={seed};ctx={num_ctx}"


def fingerprint(chunks: Sequence[Dict], model_id: str, decode: str) -> str:
    return fingerprint_of_shas([c["sha256"] for c in chunks], model_id, decode)


def fingerprint_of_shas(shas: Sequence[str], model_id: str, decode: str) -> str:
    """与 `fingerprint` 同一个公式，但输入是"一批 chunk 的 sha 列表"。

    pass 只留得下 sha（正文在 `work/` 里，未必还在），所以指纹必须能从这个
    最小充分集重算——否则 pass 无法自证，增量入库就退化成"盲信旧结果"。
    """
    six = [
        corpus_fingerprint_of(shas),
        str(model_id),
        common.ANNOTATE_PROMPT_VERSION,
        common.CHUNKER_VERSION,
        str(decode),
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


def _read_manifest() -> Dict:
    if not MANIFEST.exists():
        return {}
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def passes_of(manifest: Dict) -> List[Dict]:
    """清单里的 pass 列表；v1（扁平清单）就地折成一条。

    v1 的 `fingerprint` 是"整份语料 + 一个模型"的指纹，语料一长就整体失效。
    折成 pass 时按**记录下来的 chunk sha256** 重算指纹（自证），并且要求
    prompt / 切块 / schema 三项版本与当前一致——口径变了就不迁移，
    宁可重抽，也不拿旧口径的产物冒充新口径（§2.3）。
    """
    stored = manifest.get("passes")
    if isinstance(stored, list) and stored:
        return [dict(p) for p in stored if isinstance(p, dict)]
    if not manifest:
        return []
    for field, current in (("prompt_version", common.ANNOTATE_PROMPT_VERSION),
                           ("chunker_version", common.CHUNKER_VERSION),
                           ("schema_version", common.SCHEMA_VERSION)):
        if str(manifest.get(field, "")) != str(current):
            return []
    entries = [c for c in (manifest.get("chunks") or [])
               if isinstance(c, dict) and c.get("chunk_id") and c.get("sha256")]
    if not entries:
        return []
    extractor = manifest.get("extractor") or {}
    sha_map = {str(e["chunk_id"]): str(e["sha256"]) for e in entries}
    decode = str(manifest.get("decode", ""))
    model_id = str(extractor.get("model_id", ""))
    return [{
        "pass_id": "p001",
        "model_id": model_id,
        "family": str(extractor.get("family", "")),
        "model_version": str(extractor.get("model_version", "")),
        "decode": decode,
        "fingerprint": fingerprint_of_shas(list(sha_map.values()), model_id, decode),
        "legacy_fingerprint": str(manifest.get("fingerprint", "")),
        "chunk_sha256": sha_map,
        "status": {str(e["chunk_id"]): str(e.get("status") or "done") for e in entries},
        "reject_reason": {str(e["chunk_id"]): str(e.get("reject_reason", ""))
                          for e in entries if e.get("status") == "rejected"},
    }]


def pass_is_valid(payload: Dict) -> bool:
    """pass 自证：按**当前** prompt / 切块 / schema 口径重算它自己的指纹。"""
    sha_map = payload.get("chunk_sha256") or {}
    if not sha_map or not str(payload.get("fingerprint", "")):
        return False
    expected = fingerprint_of_shas(list(sha_map.values()),
                                   str(payload.get("model_id", "")),
                                   str(payload.get("decode", "")))
    return expected == str(payload["fingerprint"])


def reusable_from_passes(chunks: Sequence[Dict], passes: Sequence[Dict],
                         records: Dict[str, Dict],
                         retry_rejects: bool = False) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """逐条判定"这一段已经抽过、且产物还在"；返回 (可复用, 已判无卡片的拒收)。"""
    shas = {c["chunk_id"]: c["sha256"] for c in chunks}
    done: Dict[str, Dict] = {}
    rejected: Dict[str, Dict] = {}
    for payload in passes:
        if not pass_is_valid(payload):
            continue
        status = payload.get("status") or {}
        reasons = payload.get("reject_reason") or {}
        for chunk_id, sha in (payload.get("chunk_sha256") or {}).items():
            if shas.get(chunk_id) != sha or chunk_id in done or chunk_id in rejected:
                continue
            if str(status.get(chunk_id) or "done") == "rejected":
                if not retry_rejects:
                    rejected[chunk_id] = {
                        "chunk_id": chunk_id,
                        "reasons": [str(reasons.get(chunk_id) or "no_cards")],
                    }
                continue
            record = records.get(chunk_id)
            if (record is not None and str(record.get("sha256", "")) == str(sha)
                    and record.get("cards")):
                done[chunk_id] = {"chunk_id": chunk_id, "sha256": str(sha),
                                  "status": "done",
                                  "cards": [c["title"] for c in record["cards"]]}
    return done, rejected


def _manifest_payload(fp: str, client, decode: str, total: int, previous: Dict,
                      run_entries: Sequence[Dict], base_passes: Sequence[Dict],
                      stats: Dict) -> Dict:
    """写清单：v2 = v1 的全部字段 ＋ `passes[]` ＋ 本次的复用/新抽计数。"""
    passes = [dict(p) for p in base_passes]
    fresh = [e for e in run_entries if e.get("chunk_id") and e.get("sha256")]
    if fresh:
        sha_map = {str(e["chunk_id"]): str(e["sha256"]) for e in fresh}
        passes.append({
            "pass_id": f"p{len(passes) + 1:03d}",
            "model_id": str(client.model_id),
            "family": str(client.family),
            "model_version": str(getattr(client, "model_version", "")),
            "decode": str(decode),
            "fingerprint": fingerprint_of_shas(list(sha_map.values()),
                                               str(client.model_id), str(decode)),
            "chunk_sha256": sha_map,
            "status": {str(e["chunk_id"]): str(e.get("status") or "done") for e in fresh},
            "reject_reason": {str(e["chunk_id"]): str(e.get("reject_reason", ""))
                              for e in fresh if e.get("status") == "rejected"},
        })
    # 账本要能回答"这份语料里每一段现在是什么状态"：以旧清单为底再覆盖本次结果，
    # 否则被 `--limit` 截断或被复用跳过的那些段会从清单里消失。
    existing: Dict[str, Dict] = {}
    for entry in (previous.get("chunks") or []):
        if isinstance(entry, dict) and entry.get("chunk_id"):
            existing[str(entry["chunk_id"])] = entry
    for entry in run_entries:
        if entry.get("chunk_id"):
            existing[str(entry["chunk_id"])] = entry
    return {
        "version": MANIFEST_VERSION,
        "mode": "incremental" if stats.get("incremental") else "strict",
        "fingerprint": fp,
        "extractor": {"model_id": client.model_id, "family": client.family,
                      "model_version": getattr(client, "model_version", "")},
        "decode": decode,
        "chunker_version": common.CHUNKER_VERSION,
        "schema_version": common.SCHEMA_VERSION,
        "prompt_version": common.ANNOTATE_PROMPT_VERSION,
        "total_chunks": total,
        "reused_chunks": int(stats.get("reused", 0)),
        "reused_rejects": int(stats.get("reused_rejects", 0)),
        "annotated_chunks": int(stats.get("annotated", 0)),
        "passes": passes,
        "chunks": sorted(existing.values(), key=lambda c: str(c.get("chunk_id", ""))),
    }


def _checkpoint(fp: str, client, decode: str, total: int,
                manifest_chunks: List[Dict], annotated: List[Dict],
                rejects: List[Dict], previous: Dict, base_passes: Sequence[Dict],
                stats: Dict) -> None:
    """长跑任务每 10 段落一次盘：中断后按 pass 与 chunk sha256 续跑，不重抽。"""
    common.write_jsonl(ANNOTATED, annotated)
    common.write_jsonl(ANNOTATE_REJECTS, rejects)
    common.dump_json(MANIFEST, _manifest_payload(fp, client, decode, total, previous,
                                                 manifest_chunks, base_passes, stats))


def _annotate_todo(todo: Sequence[Dict], client, temperature: float, seed: int,
                   num_ctx: int, workers: int, progress=None):
    """按批并发调用标注器，并**按原顺序**产出结果。

    并发是网络等待的并发，不是口径的放松：每个 chunk 仍然各自调用一次
    `annotate_chunk`，用的是同一套 prompt、同一套 `validate_card` 校验，
    结果按提交顺序回收，因此产物与串行**逐字节一致**（见
    `tests/test_kb_pipeline.py::test_parallel_annotate_matches_serial_output`）。
    批大小 = `CHECKPOINT_EVERY`：一批落了盘再开下一批，中断不丢中间进度。
    """
    total = len(todo)
    if workers <= 1:
        for index, chunk in enumerate(todo, 1):
            if progress:
                progress(index, total, chunk["chunk_id"])
            yield index, chunk, annotate_chunk(client, chunk, temperature, seed, num_ctx)
        return
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    try:
        for start in range(0, total, CHECKPOINT_EVERY):
            batch = todo[start:start + CHECKPOINT_EVERY]
            for offset, chunk in enumerate(batch, 1):
                if progress:
                    progress(start + offset, total, chunk["chunk_id"])
            futures = [executor.submit(annotate_chunk, client, chunk, temperature,
                                       seed, num_ctx) for chunk in batch]
            for offset, (chunk, future) in enumerate(zip(batch, futures), 1):
                yield start + offset, chunk, future.result()
    finally:
        executor.shutdown(wait=True)


def run(chunks: Sequence[Dict], client, temperature: float = 0.0, seed: int = 0,
        num_ctx: int = 8192, limit: int = 0, progress=None,
        incremental: bool = False,
        retry_rejects: bool = False,
        workers: int = 1) -> Tuple[List[Dict], List[Dict]]:
    decode = decode_params(temperature, seed, num_ctx)
    fp = fingerprint(chunks, client.model_id, decode)
    previous = _read_manifest()
    base_passes = passes_of(previous)
    previous_records = {r["chunk_id"]: r for r in common.read_jsonl(ANNOTATED)}
    done: Dict[str, Dict] = {}
    reused_rejects: Dict[str, Dict] = {}
    if previous.get("fingerprint") == fp:
        by_chunk = {c["chunk_id"]: c for c in (previous.get("chunks") or [])
                    if c.get("status") == "done"}
        # §2.3 的断点续跑纪律：**先比指纹，再比 per-chunk sha256**——
        # 同一 id 换了正文（改了笔记、改了切块）必须重抽，不能复用旧结果。
        done = {c["chunk_id"]: by_chunk[c["chunk_id"]] for c in chunks
                if c["chunk_id"] in by_chunk
                and by_chunk[c["chunk_id"]].get("sha256") == c["sha256"]}
    elif incremental:
        done, reused_rejects = reusable_from_passes(chunks, base_passes, previous_records,
                                                   retry_rejects)

    annotated: List[Dict] = []
    rejects: List[Dict] = []
    if incremental:
        # 旧的"已判无卡片"要留在账上：它们没被重抽，就不该从 rejects 里消失。
        chunk_index = {c["chunk_id"]: c for c in chunks}
        for chunk_id, entry in reused_rejects.items():
            chunk = chunk_index.get(chunk_id) or {}
            rejects.append({"chunk_id": chunk_id,
                            "domain": str(chunk.get("domain", "")),
                            "reasons": list(entry.get("reasons", [])),
                            "chars": len(str(chunk.get("text", "")))})
    manifest_chunks: List[Dict] = []
    # 复用过的"已判无卡片"也要从 todo 里剔除：它是**已判定**的结果，
    # 不是"还没抽"，否则每一轮增量都会把它们重烧一遍（`--retry-rejects` 才重抽）。
    settled = set(done) | set(reused_rejects)
    todo = [c for c in chunks if c["chunk_id"] not in settled]
    if limit:
        todo = todo[:limit]

    # 指纹未变时，已标注的 chunk 直接复用上次的记录——否则 `annotated.jsonl`
    # 会随着每次续跑而缩水（只剩本次新增的部分），导入计数跟着失真。
    for chunk_id in done:
        if chunk_id in previous_records:
            annotated.append(previous_records[chunk_id])

    stats = {"incremental": bool(incremental), "reused": len(done),
             "reused_rejects": len(reused_rejects), "annotated": 0}
    for index, chunk, outcome in _annotate_todo(todo, client, temperature, seed,
                                                num_ctx, workers, progress):
        cards, reasons = outcome
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
            _checkpoint(fp, client, decode, len(chunks), manifest_chunks, annotated,
                        rejects, previous, base_passes, stats)

    stats["annotated"] = sum(1 for e in manifest_chunks if e.get("status") == "done")
    for chunk_id, entry in done.items():  # 指纹未变：复用上次结果
        manifest_chunks.append({**entry, "status": "done"})

    common.write_jsonl(ANNOTATED, annotated)
    common.write_jsonl(ANNOTATE_REJECTS, rejects)
    common.dump_json(MANIFEST, _manifest_payload(fp, client, decode, len(chunks), previous,
                                                 manifest_chunks, base_passes, stats))
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
    parser.add_argument("--incremental", action="store_true",
                        help="按 pass 逐段复用（语料长大时不重抽没变过的段）；"
                             "口径或正文变了的那一段仍然重抽")
    parser.add_argument("--retry-rejects", action="store_true",
                        help="配 --incremental：连「已判无卡片」的段也重抽一遍")
    parser.add_argument("--workers", type=int, default=1,
                        help="并发调用数（默认 1 = 串行；产物与串行逐字节相同）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    chunks = common.read_jsonl(CHUNKS)
    if args.domain:
        chunks = [c for c in chunks if c["domain"] == args.domain]
    client = llm.make_client(args.provider, args.model, args.scripted)

    def progress(index: int, total: int, chunk_id: str) -> None:
        print(f"[{index}/{total}] {chunk_id}", flush=True)

    annotated, rejects = run(chunks, client, args.temperature, args.seed,
                             args.num_ctx, args.limit, progress,
                             incremental=args.incremental,
                             retry_rejects=args.retry_rejects,
                             workers=max(1, args.workers))
    total_cards = sum(len(r["cards"]) for r in annotated)
    print(json.dumps({"chunks_annotated": len(annotated), "chunks_rejected": len(rejects),
                      "cards": total_cards}, ensure_ascii=False))
    return 0 if annotated else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
