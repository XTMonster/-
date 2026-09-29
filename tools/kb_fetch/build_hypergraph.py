"""P14-2：把卡片抽取成超边并建索引（执行文档 v1.4 §2.3 的"索引构建"）。

两段式（§2.3）在这里落地为：**逐卡抽原子事实**（batch = 若干张卡）→ **同域归并**。
归并窗口写死为"同一 `domain`（含卡片自身的 `related` 邻域）且每批不超过 8 张卡"，
这与 §2.3 的"同域 ＋ 一跳 related 闭包；每次归并最多 8 张卡"一致。

校验：`block_director/knowledge/hypergraph.build_index` 的 9 条门。不合格的边进
`knowledge/hypergraph.rejects.jsonl`；构建门是 `rejects ≤ 5%` 且没有 chunk 被跳过。

断点续跑：六元指纹（语料 sha256 ＋ 抽取器 model id＋版本 ＋ prompt 版本 ＋ chunk 策略 ＋
解码参数 ＋ schema 版本）写进 `knowledge/hypergraph.manifest.json`。

**六元指纹必须是"记录下来的六个分量的纯函数"**（§2.3 的缓存键 / §6 的"重抽取成本"）：
`fingerprint_of(manifest["cache_key"]) == manifest["fingerprint"]`，且六个分量任一个变了
指纹就必须变——否则"改了 prompt / 换了 chunk 策略"会复用旧索引，而 manifest 上看不出来。
本模块只认这六个键（多一个少一个都直接报错），免得以后加了新分量却忘了进哈希。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from . import common, llm
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools.kb_fetch import common, llm  # type: ignore

from block_director.knowledge import hypergraph as hg

EDGES = common.KNOWLEDGE / "hypergraph.edges.jsonl"
NODES = common.KNOWLEDGE / "hypergraph.nodes.jsonl"
REJECTS = common.KNOWLEDGE / "hypergraph.rejects.jsonl"
MANIFEST = common.KNOWLEDGE / "hypergraph.manifest.json"
REPORT = common.WORK / "hypergraph_report.json"
VOCAB = common.KNOWLEDGE / "hypergraph.vocab.json"

PROMPT_VERSION = "extract/v1"
BATCH_CARDS = 8
MAX_EDGES_PER_CARD = 2
#: 解码参数属于六元指纹的一部分：它写死在调用里（`extract()` 的 temperature=0/seed=0/ctx=8192）。
DECODE = "temperature=0;seed=0;ctx=8192"

#: 六元指纹的分量名（顺序即 `cache_key` 的键序）。
CACHE_KEY_FIELDS = ("corpus_sha256", "model", "prompt_version",
                    "chunker_version", "decode", "schema_version")


def corpus_digest(cards: Sequence[Dict]) -> str:
    """语料指纹：卡片 id ＋ chunk ＋ 源文档 sha256 ＋ 正文 sha256，按字典序拼后取 sha256。

    只拿 id 列表去哈希是不够的：**同样的 id、改过的正文**必须让指纹变（否则缓存会
    拿旧索引当新语料的产物）。源文档 sha256 与正文 sha256 同时计入，正是为此。
    """
    rows = []
    for card in cards:
        span = card.get("source_span") or {}
        rows.append([
            str(card.get("id", "")),
            str(card.get("chunk_id") or span.get("chunk_id") or ""),
            str((card.get("source_ref") or {}).get("sha256", "")),
            common.sha256_text(str(card.get("content", ""))),
        ])
    rows.sort()
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_components(cards: Sequence[Dict], client, *,
                           prompt_version: str = PROMPT_VERSION,
                           decode: str = DECODE,
                           chunker_version: str = "",
                           schema_version: str = "") -> Dict[str, str]:
    """把六元指纹的六个分量算出来（`cache_key` 的**唯一**生产者）。"""
    return {
        "corpus_sha256": corpus_digest(cards),
        "model": f"{client.model_id}@{getattr(client, 'model_version', '')}",
        "prompt_version": str(prompt_version),
        "chunker_version": str(chunker_version or common.CHUNKER_VERSION),
        "decode": str(decode),
        "schema_version": str(schema_version or hg.SCHEMA_VERSION),
    }


def fingerprint_of(components: Dict) -> str:
    """六元指纹：对**恰好这六个**分量做规范化 JSON 哈希。

    键集不对就报错（不是忽略多余键）：这是"加了新分量却没进哈希"的机械防线。
    """
    keys = set(components)
    expected = set(CACHE_KEY_FIELDS)
    if keys != expected:
        raise ValueError(f"六元指纹的分量不匹配：多 {sorted(keys - expected)} / "
                         f"少 {sorted(expected - keys)}")
    payload = json.dumps({key: str(components[key]) for key in CACHE_KEY_FIELDS},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def rekey_manifest(path: pathlib.Path | None = None,
                   cards: Sequence[Dict] | None = None) -> Dict:
    """只重算 `cache_key`/`fingerprint`，**不重抽**。

    指纹是"记录下来的六个分量"的纯函数，所以口径升级（例如以前只哈希 id＋model）
    之后可以就地重算：`corpus_sha256` 用当前卡片重算，其余五个从 manifest 自己读。
    """
    target = pathlib.Path(path or MANIFEST)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    extractor = manifest.get("extractor") or {}
    components = {
        "corpus_sha256": corpus_digest(list(cards if cards is not None else load_cards())),
        "model": f"{extractor.get('model_id', '')}@{extractor.get('model_version', '')}",
        "prompt_version": str(manifest.get("prompt_version", PROMPT_VERSION)),
        "chunker_version": str(manifest.get("chunker_version", common.CHUNKER_VERSION)),
        "decode": str(manifest.get("decode", DECODE)),
        "schema_version": str(manifest.get("schema_version", hg.SCHEMA_VERSION)),
    }
    rekeyed = {"fingerprint": fingerprint_of(components), "cache_key": components}
    rekeyed.update({key: value for key, value in manifest.items()
                    if key not in ("fingerprint", "cache_key")})
    common.dump_json(target, rekeyed)
    return {"manifest": str(target), "fingerprint": rekeyed["fingerprint"],
            "cache_key": components}

SYSTEM_PROMPT = """你是超图索引的抽取器。给定若干条知识卡与一份**冻结的取值词表**，把卡片里\
的多元耦合（情绪×运镜×景别×剪辑×特效×禁忌）收敛成下面六类超边之一。

只输出 JSON：{"edges":[{"type":..., "members":[["role","kind","node_id"], ...],
 "source_kind":"theory|experience|lesson", "hardness":"hard|soft",
 "confidence":0.0-1.0, "source_card":"<卡片 id>"}]}

硬规则（违反的边会被机器丢弃，因此宁少勿错）：
1. `type` 只能取六类之一，必填成员必须写全：
   EMOTION_PACK: (allow,emotion) ＋ (qualifier,intensity)；
   SHOT_PATTERN: (allow,shot_size) ＋ (allow,lens) ＋ (qualifier,headroom_policy)；
   AXIS_RULE: (qualifier,pair) ＋ (qualifier,axis_side)；
   TROPE: (allow,genre) ＋ (allow,emotion)；
   EDIT_RHYTHM: (allow,pacing) ＋ (qualifier,avg_shot_len)；
   LIGHT_PACK: (allow,lighting) ＋ (qualifier,intensity)。
2. `node_id` **必须**取自下面词表（`kind:取值` 已经写好）；词表里没有的取值就不要抽。
3. 同一个 `node_id` 不能既出现在 `allow` 又出现在 `forbid`。
4. 禁忌写成 `["forbid", kind, node_id]`——它是这条边最有价值的部分，别省略。
   注意：**只有 EMOTION_PACK 允许 `forbid` 成员**（§2.3 的边表），其它五类不许写。
5. `source_kind`：教科书/权威理论的边用 `theory`＋`hard`；来自个人经验的取舍用
   `experience`＋`soft`；只有卡片明确写成"教训/禁忌"时才用 `lesson`。
6. **每一张卡都要至少产出一条边**（除非它只是孤立术语的定义）。一张卡最多 2 条。
   宁可少写成员，也不要空手而归——索引里没有边，这条知识就等于不存在。
7. `value` 必须落在冻结取值域内（例如 intensity 只能是 low/mid/high）。
   受限取值只有这几组，抄错即被拒收：intensity∈{low,mid,high}；
   avg_shot_len∈{<1s,1-3s,3-8s,>8s}；pacing∈{short,medium,long}；
   axis_side∈{left,right,neutral}；pair=any_two；headroom_policy∈{board,cinematic}；
   transition∈{cut,dissolve,fade,whip}；
   scene_type∈{establish,dialogue,action,reaction,transition,insert}；
   genre 与 applies_to_genre∈{film,anime,documentary}；
   shot_size 与 applies_to_shot_size∈{ECU,CU,MCU,MS,MLS,LS,ELS}。
8. 若一组卡片表达的是同一条耦合（同 type ＋ 同成员），只写一条，让 `occurrences` 去计权。
"""


def compact_vocab(vocab: Dict[str, List[str]]) -> str:
    lines = []
    for kind, values in sorted(vocab.items()):
        lines.append("- " + kind + ": " + ", ".join(f"{kind}:{v}" for v in values[:80]))
    return "\n".join(lines)


def build_prompt(cards: Sequence[Dict], vocab: Dict[str, List[str]]) -> str:
    parts = ["【冻结词表（node_id 直接抄这里）】", compact_vocab(vocab), "", "【知识卡】"]
    for card in cards:
        parts.append(f"### {card['id']}（domain={card['domain']}）\n"
                     f"标题：{card['title']}\n内容：{card['content']}\n"
                     f"标签：{'、'.join(card.get('tags', []))}\n"
                     f"来源性质：{card.get('source_kind', 'theory')}")
    return "\n".join(parts)


def to_edge(raw: Dict, cards: Dict[str, Dict]) -> Tuple[Optional[hg.HyperEdge], str]:
    if not isinstance(raw, dict):
        return None, "edge_not_object"
    edge_type = str(raw.get("type", "")).strip()
    if edge_type not in hg.EDGE_TYPES:
        return None, f"bad_type:{edge_type}"
    card_id = str(raw.get("source_card", "")).strip()
    card = cards.get(card_id)
    if card is None:
        return None, f"unknown_source_card:{card_id}"
    members: List[hg.Member] = []
    for item in raw.get("members") or []:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return None, f"bad_member:{item}"
        members.append(hg.Member(role=str(item[0]), kind=str(item[1]), node_id=str(item[2])))
    span = dict(card.get("source_span") or {})
    if not span or int(span.get("start", -1)) < 0:
        return None, "unlocatable_source_span"
    source_kind = str(raw.get("source_kind") or "theory")
    if source_kind not in hg.SOURCE_KINDS:
        source_kind = "theory"
    hardness = str(raw.get("hardness") or ("hard" if source_kind == "theory" else "soft"))
    if hardness not in hg.HARDNESS:
        hardness = "hard" if source_kind == "theory" else "soft"
    if source_kind == "experience" and any(m.role == "forbid" for m in members):
        # §2.3b 的关键纪律 1：经验默认不得单独产生 forbid——除非显式标成 lesson。
        return None, "experience_cannot_forbid"
    return hg.HyperEdge(
        type=edge_type,
        members=tuple(members),
        source_kind=source_kind,
        hardness=hardness,
        confidence=float(raw.get("confidence", 0.7) or 0.7),
        confidence_max=float(raw.get("confidence", 0.7) or 0.7),
        occurrences=1,
        sources=(card_id,),
        source_span=span,
        extractor={"prompt_version": PROMPT_VERSION},
        provenance_kind=str(card.get("provenance_kind", "生成卡片")),
    ), ""


def extract(cards: Sequence[Dict], vocab: Dict[str, List[str]], client,
            batch_size: int = BATCH_CARDS, limit: int = 0) -> Tuple[List[hg.HyperEdge], List[Dict], List[Dict]]:
    by_id = {str(c["id"]): c for c in cards}
    # 同域归并：批内只放同一个 domain 的卡（§2.3 的"同一 domain"约束）
    groups: Dict[str, List[Dict]] = {}
    for card in cards:
        groups.setdefault(card["domain"], []).append(card)
    batches: List[List[Dict]] = []
    for domain in sorted(groups):
        items = groups[domain]
        for start in range(0, len(items), batch_size):
            batches.append(items[start:start + batch_size])
    if limit:
        batches = batches[:limit]

    edges: List[hg.HyperEdge] = []
    rejects: List[Dict] = []
    batch_log: List[Dict] = []
    for index, batch in enumerate(batches, 1):
        try:
            reply = client.chat_json(SYSTEM_PROMPT, build_prompt(batch, vocab), 0.0, 0, 8192,
                                     key=batch[0]["id"])
        except Exception as exc:  # noqa: BLE001
            rejects.append({"batch": index, "reason": f"{type(exc).__name__}: {exc}"})
            batch_log.append({"batch": index, "status": "error"})
            continue
        raw_edges = reply.get("edges") if isinstance(reply, dict) else None
        if not isinstance(raw_edges, list):
            rejects.append({"batch": index, "reason": "reply_not_a_list"})
            batch_log.append({"batch": index, "status": "error"})
            continue
        produced = 0
        per_card: Dict[str, int] = {}
        for raw in raw_edges:
            card_id = str(raw.get("source_card", ""))
            if per_card.get(card_id, 0) >= MAX_EDGES_PER_CARD:
                reject = {"batch": index, "reason": "too_many_edges_for_card", "raw": raw}
                rejects.append(reject)
                continue
            edge, reason = to_edge(raw, by_id)
            if edge is None:
                rejects.append({"batch": index, "reason": reason, "raw": raw})
                continue
            per_card[card_id] = per_card.get(card_id, 0) + 1
            edges.append(edge)
            produced += 1
        batch_log.append({"batch": index, "status": "done", "edges": produced,
                          "cards": [c["id"] for c in batch]})
    return edges, rejects, batch_log


def run(cards: Sequence[Dict], vocab: Dict[str, List[str]], client,
        limit: int = 0) -> Dict:
    edges, rejects, batch_log = extract(cards, vocab, client, BATCH_CARDS, limit)
    node_by_id = {node["node_id"]: hg.Node.from_dict(node) for node in
                  json.loads(VOCAB.read_text(encoding="utf-8"))["nodes"]}
    # 构建门的"chunk 处理率"口径：按**批次覆盖到的 chunk_id** 计数，
    # 出错/被跳过的批次不会贡献任何 chunk，因此比率会掉到 1.0 以下。
    all_chunks = {str(c.get("source_span", {}).get("chunk_id", c["id"])) for c in cards}
    processed_chunks = set()
    for entry in batch_log:
        if entry.get("status") == "done":
            for card_id in entry.get("cards", []):
                card = next((c for c in cards if c["id"] == card_id), None)
                if card is not None:
                    processed_chunks.add(str(card.get("source_span", {}).get("chunk_id", card_id)))
    unique, report = hg.build_index(edges, node_by_id,
                                    processed_chunks=len(processed_chunks),
                                    total_chunks=len(all_chunks))

    common.write_jsonl(EDGES, [edge.to_dict() for edge in unique])
    common.write_jsonl(REJECTS, rejects)
    common.dump_json(REPORT, report.to_dict())
    components = fingerprint_components(cards, client)
    common.dump_json(MANIFEST, {
        "fingerprint": fingerprint_of(components),
        "cache_key": components,
        "extractor": {"model_id": client.model_id, "family": client.family,
                      "model_version": client.model_version},
        "prompt_version": PROMPT_VERSION,
        "decode": DECODE,
        "chunker_version": common.CHUNKER_VERSION,
        "schema_version": hg.SCHEMA_VERSION,
        "cards": len(cards),
        "raw_edges": report.raw_edges,
        "valid_unique": report.valid_unique,
        "duplicates": report.duplicates,
        "rejects": report.rejects,
        "batches": batch_log,
    })
    return {"report": report.to_dict(), "edges": len(unique), "rejects": len(rejects)}


def load_cards() -> List[Dict]:
    """优先用生成卡（带 `source_span`）；缺失字段的手写卡不参与抽取。"""
    out: List[Dict] = []
    directory = common.CARDS_DIR
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            card = json.loads(line)
            if card.get("source_span"):
                out.append(card)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.build_hypergraph")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--rekey-manifest", action="store_true",
                        help="只按当前卡片与 manifest 里记录的五个分量重算六元指纹，不重抽")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.rekey_manifest:
        # 指纹是"记录下来的六个分量"的纯函数：口径升级后就地重算，不重抽语料。
        print(json.dumps(rekey_manifest(), ensure_ascii=False, indent=2))
        return 0

    if not VOCAB.exists():
        print(json.dumps({"error": "先跑 tools.kb_fetch.vocabulary"}, ensure_ascii=False))
        return 1
    vocab = json.loads(VOCAB.read_text(encoding="utf-8"))["vocab"]
    cards = load_cards()
    if not cards:
        print(json.dumps({"error": "没有带 source_span 的生成卡"}, ensure_ascii=False))
        return 1
    client = llm.make_client(args.provider, args.model, args.scripted)
    summary = run(cards, vocab, client, args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["report"]["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
