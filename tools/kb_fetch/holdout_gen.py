"""生成 held-out 标注集（P14-1 产出；执行文档 v1.4 §4.1 RK-13 / §2.3c 的 R49 五条）。

* **换族**：默认用本地 `qwen3-vl:30b`（family=qwen），而抽取器是 DeepSeek
  （family=deepseek）——`annotator.model_id != extractor.model_id`，且不同厂商族
  → `independence: strong`。
* **不可见**：提示里只给**卡片**（语料）与**冻结的词表/schema**，不给索引、
  不给 `knowledge_trace.json`、不给检索器实现、不给抽取 prompt。
* **格式**：一条 JSONL = `{id, from_card, q, must, top1, never, expect_movements,
  annotator, independence}`，`must` 写成 `TYPE:槽位=取值,…`，标注者不写 sha1。
* **覆盖**：按卡片 round-robin 保证"每张卡至少派生 1 条"（门⑥）。

断点续跑：与抽取一样绑在指纹上（卡片清单 sha256 ＋ 模型 id ＋ prompt 版本）。
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

from block_director.knowledge import hypergraph as hg

HOLDOUT = common.ROOT / "fixtures" / "knowledge_holdout.jsonl"
CARDS_JSON = common.ROOT / "fixtures" / "knowledge_holdout.cards.json"
MANIFEST = common.WORK / "holdout.manifest.json"
PROMPT_VERSION = "holdout/v3"
REVIEW_BATCH = 1

SYSTEM_PROMPT = """你是分镜知识库的**独立标注员**。你会看到若干条知识卡（语料）与一份冻结的\
超边 schema ＋ 取值词表。你的工作是：**为每张卡写出 2 条不同的检索期望**，用来检验一个超图\
检索器是否真能召回该卡所表达的知识。第 1 条抓这张卡最核心的那条约束；第 2 条换一组查询键\
或取值（不要与第 1 条同义重复），让词表覆盖更广。每张卡都必须有 2 条。

只输出 JSON：{"entries":[{...}, ...]}，每条：
{
 "from_card": "<卡片 id>",
 "q": "键=值；键=值",                     // 查询串，键取自下面允许的键集
 "must": ["TYPE:槽位=取值,槽位=取值"],      // 1–3 条，必须能从这个查询检出
 "top1": ["与 must 中某条完全相同"],        // 期望排第一的那条
 "never": ["TYPE:槽位=取值"],              // 不该被召回（可为 []），与 must 不相交
 "expect_movements": ["运镜名"]             // 可缺省；这条查询下作者期望的运镜
}

规则（违反的条目会被机器拒绝）：
1. `q` 的键只能用：情绪/动作/运镜/景别/镜头/节奏/特效/音效/机位/光线/构图/轴线/题材/桥段。
2. `must` 的边类型只能取六类之一；**每条边的必填槽位必须写全**：
   EMOTION_PACK: emotion＋intensity；SHOT_PATTERN: shot_size＋lens＋headroom_policy；
   AXIS_RULE: pair＋axis_side；TROPE: genre＋emotion；EDIT_RHYTHM: pacing＋avg_shot_len；
   LIGHT_PACK: lighting＋intensity。
2b. **只有这六个类型名**。不要发明 `COMPOSITION`／`COMPOSITION_RULE`／`FRAMING` 之类的
   新类型——机器会以 `bad_type` 整条拒收。
2c. **构图/机位/特效/音效/动作类知识挂到最接近的那一类边上，作为额外槽位**
   （必填槽位照旧写全）：
   * 构图（均衡/三分/留白/引导空间/遮挡）→ `SHOT_PATTERN` ＋ `composition_rule=<词表取值>`；
   * 机位（高低/荷兰角/过肩/骑轴）→ 就近那类 ＋ `camera_angle=<词表取值>`；
   * 特效/音效 → 就近那类 ＋ `vfx=`／`sfx=<词表取值>`；
   * 动作 → 就近那类 ＋ `action=<词表取值>`；
   * 适用题材/景别 → `applies_to_genre=`／`applies_to_shot_size=<词表取值>`。
   **卡片属于哪个 domain 与边类型无关**：`domain=composition` 的卡也要写成这六类之一。
3. 槽位名 = kind；禁忌槽位写成 `forbid_<kind>=取值`。取值尽量用词表里的规范名。
3b. 取值**必须**是词表里的那一个（闭集，逐字相同）：`q` 里和 `must` 里都一样。
    写了词表外的说法会被机器判成 `unknown_values`——那**整条作废**，不是警告。
4. `must` 最多 3 条（上限是硬的：top-3 内 100% 可检出要求 |must| ≤ 3）。
5. `top1` 必须与 `must` 里的某一条**一字不差**。
6. 期待排序靠前的边应当是"这张卡最核心的那条约束"；把"调用方必须避开的东西"
   写成 `forbid_*` 槽位（例如查询里出现"运镜=固定"时，若卡里说这个情绪忌讳固定机位，
   就写 `forbid_movement=固定`）——这类条目是禁忌拦截率的判据。
7. **禁忌槽位只出现在 EMOTION_PACK 上**（§2.3 的边表：只有它有 `forbid` 成员）；
   其它五类写 `forbid_` 会被判成不可召回。
8. **q 与 must 必须自洽**：`q` 里出现的 kind，只要 `must` 里有同类槽位，
    取值就必须与 `q` **逐字相同**（校验器会逐条对拍）。
8b. **`q` 里同一个键只能出现一次**（写两遍 `节奏=…` 会被判红）；同一个 kind 在
    `q` 与 `must` 里必须用**同一个取值**，不许一个写中文、一个写英文代号。
9. 词表里的**每个取值都必须至少出现在一条 `q` 里**（覆盖门③）；
   因此请在多个条目之间轮换取值，不要反复只用同一个词。

**示例（照这个形状写，别只写个 `TYPE:` 占位符）**：
```json
{"entries": [
  {"from_card": "gen_cine_0001",
   "q": "情绪=荒诞；运镜=固定；景别=中景",
   "must": ["EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"],
   "top1": ["EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"],
   "never": ["SHOT_PATTERN:shot_size=ELS,lens=24mm,headroom_policy=board"],
   "expect_movements": ["甩镜"]}
]}
```
注意示例里：`q` 用的是**中文键**；`must` 里写的是**真实的边类型名**
（EMOTION_PACK／SHOT_PATTERN／AXIS_RULE／TROPE／EDIT_RHYTHM／LIGHT_PACK），
不是字面量 `TYPE`；`forbid_movement` 的取值与 `q` 的 `运镜=` **一模一样**。
"""


def cards_fingerprint(cards: Sequence[Dict]) -> str:
    payload = "".join(sorted(str(c.get("id", "")) + hashlib.sha256(
        str(c.get("content", "")).encode("utf-8")).hexdigest() for c in cards))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_prompt(cards: Sequence[Dict], vocab: Dict[str, List[str]]) -> str:
    # 词表按 kind 打印时，**必须同时给出对应的中文查询键**：只印英文 kind 名，
    # 模型会把 `q` 写成 `emotion=...；pacing=...`（实测 qwen2.5:7b 就是这样），
    # 而协议冻结的 `q` 键只有中文那一套，于是整批被格式门拒收。
    from tools.check_holdout import Q_KEY_TO_KIND

    zh_of: Dict[str, str] = {}
    for key, kind in Q_KEY_TO_KIND.items():
        zh_of.setdefault(kind, key)
    lines = ["【冻结的取值词表】（`q` 的键用括号里的中文键；取值用这里的规范名）"]
    for kind, values in sorted(vocab.items()):
        key = zh_of.get(kind)
        head = f"{key}/{kind}" if key else f"{kind}（仅用于 must 槽位）"
        lines.append(f"- {head}: " + ", ".join(values[:60]))
    lines.append("\n【知识卡】")
    for card in cards:
        lines.append(f"### {card['id']}（domain={card['domain']}）\n"
                     f"标题：{card['title']}\n内容：{card['content']}\n"
                     f"标签：{'、'.join(card.get('tags', []))}\n"
                     f"关键词：{'、'.join(card.get('keywords', []))}")
    return "\n".join(lines)


_SPEC_RE = re.compile(r"^(?P<etype>[A-Z_]+):(?P<slots>.+)$")
_SLOT_RE = re.compile(r"^(?P<forbid>forbid_)?(?P<kind>[a-z_]+)=(?P<value>.+)$")


def validate_entry(raw: Dict, card_ids: set) -> Tuple[Optional[Dict], str]:
    from tools.check_holdout import ALLOWED_KINDS, EDGE_TYPES, REQUIRED_SLOTS

    if not isinstance(raw, dict):
        return None, "entry_not_object"
    card = str(raw.get("from_card", "")).strip()
    if card not in card_ids:
        return None, f"unknown_from_card:{card}"
    q = str(raw.get("q", "")).strip()
    if "=" not in q:
        return None, "empty_q"
    must = raw.get("must")
    if not isinstance(must, list) or not 1 <= len(must) <= 3:
        return None, "must_size"
    top1 = raw.get("top1")
    if not isinstance(top1, list) or not top1 or not set(top1) <= set(must):
        return None, "top1_not_subset"
    never = raw.get("never") or []
    if not isinstance(never, list) or set(never) & set(must):
        return None, "never_overlaps_must"
    for spec in list(must) + list(never):
        match = _SPEC_RE.match(str(spec).strip())
        if not match:
            return None, f"bad_spec:{spec}"
        etype = match.group("etype")
        if etype not in EDGE_TYPES:
            return None, f"bad_type:{etype}"
        seen = set()
        for slot in match.group("slots").split(","):
            slot = slot.strip()
            if not slot:
                continue
            sm = _SLOT_RE.match(slot)
            if not sm or sm.group("kind") not in ALLOWED_KINDS:
                return None, f"bad_slot:{slot}"
            seen.add(sm.group("kind"))
        missing = [s for s in REQUIRED_SLOTS[etype] if s not in seen]
        if missing:
            return None, f"missing_slots:{etype}:{missing}"
    entry = {"from_card": card, "q": q, "must": [str(s) for s in must],
             "top1": [str(s) for s in top1], "never": [str(s) for s in never]}
    movements = raw.get("expect_movements")
    if isinstance(movements, list) and movements:
        entry["expect_movements"] = [str(m) for m in movements]
    return entry, ""


def run(cards: Sequence[Dict], vocab: Dict[str, List[str]], client,
        batch_size: int = 8, limit: int = 0, target: int = 0) -> Tuple[List[Dict], List[Dict]]:
    card_ids = {str(c["id"]) for c in cards}
    prompt_sha = hashlib.sha256((SYSTEM_PROMPT + PROMPT_VERSION).encode("utf-8")).hexdigest()
    annotator = {"model_id": client.model_id, "family": client.family,
                 "model_version": client.model_version, "prompt_sha256": prompt_sha}
    annotation = {"model_id": client.model_id, "model_version": client.model_version,
                  "family": client.family, "prompt_sha256": prompt_sha}

    batches = [list(cards[i:i + batch_size]) for i in range(0, len(cards), batch_size)]
    if limit:
        batches = batches[:limit]

    entries: List[Dict] = []
    rejects: List[Dict] = []
    counter = 0
    for index, batch in enumerate(batches, 1):
        try:
            reply = client.chat_json(SYSTEM_PROMPT, build_prompt(batch, vocab), 0.0, 0, 8192,
                                     key=batch[0]["id"])
        except Exception as exc:  # noqa: BLE001 - 记因由而不是静默跳过
            rejects.append({"batch": index, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        raw_entries = reply.get("entries") if isinstance(reply, dict) else None
        if not isinstance(raw_entries, list):
            rejects.append({"batch": index, "reason": "reply_not_a_list"})
            continue
        for raw in raw_entries:
            entry, reason = validate_entry(raw, card_ids)
            if entry is None:
                rejects.append({"batch": index, "reason": reason,
                                "raw": str(raw)[:200]})
                continue
            counter += 1
            entries.append({"id": f"hq_{counter:04d}", **entry,
                            "annotator": annotation,
                            "independence": "strong", "pilot": False})
        if target and counter >= target:
            break

    sweep_rejects: List[Dict] = []
    if not limit and not target:
        extra, sweep_rejects = sweep_unused(entries, cards, vocab, client, counter)
        entries.extend(extra)

    common.write_jsonl(HOLDOUT, entries)
    common.dump_json(CARDS_JSON, sorted(card_ids))
    rejects = rejects + sweep_rejects
    common.dump_json(MANIFEST, {
        "fingerprint": hashlib.sha256(
            (cards_fingerprint(cards) + client.model_id + PROMPT_VERSION)
            .encode("utf-8")).hexdigest(),
        "cards_fingerprint": cards_fingerprint(cards),
        "annotator": annotator,
        "prompt_version": PROMPT_VERSION,
        "entries": len(entries),
        "rejects": len(rejects),
        "cards": len(cards),
    })
    return entries, rejects


SWEEP_PROMPT = """你是分镜知识库的独立标注员。下面的**取值**还没有被任何查询用到，\
而覆盖门要求词表里每个取值至少出现在一条查询里。

请为**每一个**取值写一条使用它的检索期望（一次输出多条）。只输出 JSON：
{"entries":[{"from_card":"<卡片 id>","q":"键=值；键=值","must":[...],"top1":[...],"never":[...]}]}

键与槽位的规则与之前完全一致：`must` 的边必须写全必填槽位，`top1` 必须与 `must` 里
某条一字不差，`|must| ≤ 3`，`never` 与 `must` 不相交。取值请用词表里的规范名。
"""


def sweep_unused(entries: List[Dict], cards: Sequence[Dict],
                 vocab: Dict[str, List[str]], client, counter_start: int,
                 batch: int = 12) -> Tuple[List[Dict], List[Dict]]:
    """把词表里"一次都没被 q 用到"的取值补成查询（门③ 的双向要求）。"""
    from tools.check_holdout import Q_KEY_TO_KIND

    kind_by_key = Q_KEY_TO_KIND
    used: Dict[str, set] = {}
    for entry in entries:
        for chunk in re.split(r"[；;]", entry["q"]):
            if "=" not in chunk:
                continue
            key, _, value = chunk.partition("=")
            kind = kind_by_key.get(key.strip())
            if kind:
                used.setdefault(kind, set()).add(value.strip())
    missing = [(kind, value) for kind, values in vocab.items()
               for value in values if value not in used.get(kind, set())]
    if not missing:
        return [], []

    card_ids = sorted({str(c["id"]) for c in cards})
    extra: List[Dict] = []
    rejects: List[Dict] = []
    counter = counter_start
    for start in range(0, len(missing), batch):
        group = missing[start:start + batch]
        sample = [str(c["id"]) + "｜" + str(c["content"])[:120]
                  for c in cards if str(c["id"]) in set(card_ids[:40])]
        lines = ["【需要覆盖的取值】"] + [f"- {kind}={value}" for kind, value in group]
        lines += ["", "【可用卡片片段】"] + sample[:20]
        try:
            reply = client.chat_json(SWEEP_PROMPT, "\n".join(lines), 0.0, 0, 8192,
                                     key="sweep:" + ",".join(f"{k}={v}" for k, v in group))
        except Exception as exc:  # noqa: BLE001
            rejects.append({"sweep": str(group), "reason": f"{type(exc).__name__}: {exc}"})
            continue
        raw_entries = reply.get("entries") if isinstance(reply, dict) else None
        if not isinstance(raw_entries, list):
            rejects.append({"sweep": str(group), "reason": "reply_not_a_list"})
            continue
        for raw in raw_entries:
            entry, reason = validate_entry(raw, set(card_ids))
            if entry is None:
                rejects.append({"sweep": str(group), "reason": reason})
                continue
            counter += 1
            extra.append({"id": f"hq_{counter:04d}", **entry,
                          "annotator": {"model_id": client.model_id,
                                        "family": client.family,
                                        "model_version": client.model_version},
                          "independence": "strong", "pilot": False})
    return extra, rejects


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.holdout_gen")
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--target", type=int, default=0, help="达到该条数即停（0 = 全跑）")
    parser.add_argument("--cards", default="", help="卡片 JSONL 路径（默认用运行时 CARDS）")
    parser.add_argument("--out", default="", help="输出路径（默认 fixtures/knowledge_holdout.jsonl）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.out:
        global HOLDOUT, CARDS_JSON
        HOLDOUT = pathlib.Path(args.out)
        CARDS_JSON = HOLDOUT.with_suffix(".cards.json")

    vocab_path = common.KNOWLEDGE / "hypergraph.vocab.json"
    if not vocab_path.exists():
        print(json.dumps({"error": "先跑 tools.kb_fetch.vocabulary"}, ensure_ascii=False))
        return 1
    payload = json.loads(vocab_path.read_text(encoding="utf-8"))
    # 只能用 14 个查询 kind 的子集：门③ 会遍历词表的**每一个** kind，
    # 把 qualifier 类（intensity/pair/…）也塞进去会被判成"取值从没被用到"。
    vocab = payload["holdout_vocab"]

    if args.cards:
        cards = [json.loads(line) for line in
                 pathlib.Path(args.cards).read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        from block_director.knowledge.corpus import CARDS
        cards = [{"id": c.id, "domain": c.domain, "title": c.title, "content": c.content,
                  "tags": list(c.tags), "keywords": list(c.keywords),
                  "emotion": c.emotion} for c in CARDS]

    client = llm.make_client(args.provider, args.model, args.scripted)
    entries, rejects = run(cards, vocab, client, args.batch_size, args.limit, args.target)
    print(json.dumps({"entries": len(entries), "rejects": len(rejects),
                      "rejects_detail": rejects[:5]}, ensure_ascii=False))
    return 0 if entries else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
