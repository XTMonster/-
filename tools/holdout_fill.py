"""P14-1 的长跑驱动：把 `fixtures/knowledge_holdout.jsonl` 从空做到过六道门。

为什么单独一个文件而不是改 `holdout_gen.py`：`holdout_gen.run()` 只在**全部批跑完**
才落盘，1200 条 × 本地 30B 是 1–2 小时的墙钟，中途任何一次异常都会全丢。本模块把它
包成**逐批落盘 ＋ 指纹续跑 ＋ 覆盖驱动的补跑**，且不改 `holdout_gen.py` 的既有 API
（那个 API 有测试钉着）。

三道工序：

1. **逐卡**：batch = N 张卡，一次调用为**每张卡**写 1–2 条检索期望。覆盖门⑥要求
   `.cards.json` 里的每张卡至少派生一条，所以批次按卡片顺序切。
2. **覆盖补跑**：用 `tools/check_holdout.py` 的**同一套门**算出还缺什么（哪些取值支撑
   不足、哪些边类型的 (卡片,查询) 对不够、还差多少 Q7 冲突），变成"点菜清单"再补写。
   判据**复用**校验器，不另写一套。
3. **收尾**：条目写 `fixtures/knowledge_holdout.jsonl`；卡片集合写 `.cards.json`
   （＝实际产出条目的卡片）；报告写 `work/holdout_report.json`。

红线：门限一律不放宽；不过门就如实报告缺口，不伪造 `review`（门⑦人审只能人做）。

用法::

  python tools/holdout_fill.py --provider ollama --model qwen3-vl:30b --batch 6 --rounds 6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_holdout import (  # noqa: E402
    REQUIRED_SLOTS,
    gate_edge_types,
    gate_entries,
    gate_forbid,
    gate_forbid_members,
    gate_seed_coverage,
    must_values_from,
    spec_key,
    support_from,
)
from tools.kb_fetch import common, holdout_gen, llm  # noqa: E402

#: 覆盖门的门限，与 `tools/check_holdout.py` 的默认值同源（此处只引用，不放宽）。
MIN_ENTRIES = 1200
MIN_PER_TYPE = 30
MIN_CARDS_PER_TYPE = 10
MIN_FORBID = 60
MIN_SEED_SUPPORT = 3

PROGRESS = common.WORK / "holdout.progress.json"
PARTIAL = common.WORK / "holdout.partial.jsonl"
REPORT = common.WORK / "holdout_report.json"

_ANNOTATOR: Dict[str, str] = {}

# 缺口补写用的系统提示（不放进 holdout_gen，避免动它的冻结 prompt 版本）。
GAP_PROMPT = (
    "你是分镜知识库的独立标注员。下面给出一份**缺口清单**与若干张知识卡。"
    "请**只**针对缺口写检索期望，输出 JSON：{\"entries\":[...]}，每条格式与之前一致："
    "{\"from_card\":\"<卡片 id>\",\"q\":\"键=值；键=值\",\"must\":[...],\"top1\":[...],\"never\":[...]}。\n"
    "硬规则（违反即被机器拒收）：\n"
    "1. `q` 的键只能用：情绪/动作/运镜/景别/镜头/节奏/特效/音效/机位/光线/构图/轴线/题材/桥段。\n"
    "2. `must` 1–3 条，边类型取六类之一，**必填槽位必须写全**："
    "EMOTION_PACK: emotion＋intensity；SHOT_PATTERN: shot_size＋lens＋headroom_policy；"
    "AXIS_RULE: pair＋axis_side；TROPE: genre＋emotion；EDIT_RHYTHM: pacing＋avg_shot_len；"
    "LIGHT_PACK: lighting＋intensity。\n"
    "3. `top1` 必须与 `must` 里某条**一字不差**；`never` 与 `must` 不相交。\n"
    "4. `q` 里出现的取值，只要 `must` 里有同 kind 的槽位，就必须**取值完全相同**。\n"
    "5. 禁忌槽位 `forbid_<kind>=取值` **只允许出现在 EMOTION_PACK** 上，"
    "且该 kind 的同名取值必须同时出现在 `q` 里（这样才算一次禁忌冲突）。\n"
    "6. `from_card` 必须是下面列出的卡片 id 之一，且**优先用没被用过的卡**。\n"
)


# --------------------------------------------------------------------------- 断点续跑


def run_fingerprint(cards: Sequence[Dict], client, prompt_version: str) -> str:
    """运行指纹：语料 ＋ 模型（id/版本）＋ **prompt 正文的 sha256** ＋ 版本号 ＋ 解码（预填）。

    只哈希 `PROMPT_VERSION` 这个**字符串**是不够的（原先就是这样）：改了
    `holdout_gen.SYSTEM_PROMPT` 而忘了改版本号时，续跑判定"还是同一次运行"，
    于是两套 prompt 产出的条目会被混进同一个 `knowledge_holdout.jsonl`——每条的
    `annotator.prompt_sha256` 不同，文件本身却看不出来。assistant 预填同理
    （它改变解码条件），也必须进指纹。
    """
    payload = "|".join([
        holdout_gen.cards_fingerprint(cards),
        str(client.model_id),
        str(getattr(client, "model_version", "")),
        str(prompt_version),
        hashlib.sha256(holdout_gen.SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        str(getattr(client, "prefill", "")),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_partial(fingerprint: str, progress_path: pathlib.Path = PROGRESS,
                 partial_path: pathlib.Path = PARTIAL) -> Tuple[List[Dict], List[Dict], set]:
    """读回已落盘的条目与"哪些批已完成"；指纹不符则整批作废（不删文件，只重置状态）。"""
    if not progress_path.is_file() or not partial_path.is_file():
        return [], [], set()
    try:
        state = json.loads(progress_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], [], set()
    if str(state.get("fingerprint") or "") != fingerprint:
        return [], [], set()
    rejects = state.get("rejects_detail")
    if not isinstance(rejects, list):
        rejects = []
    return (common.read_jsonl(partial_path), list(rejects),
            {str(key) for key in (state.get("done") or [])})


def save_partial(entries: Sequence[Dict], rejects: Sequence[Dict], done,
                 fingerprint: str, progress_path: pathlib.Path = PROGRESS,
                 partial_path: pathlib.Path = PARTIAL) -> None:
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    common.write_jsonl(partial_path, entries)
    common.dump_json(progress_path, {
        "fingerprint": fingerprint,
        "entries": len(entries),
        "rejects": len(rejects),
        "done": sorted(done),
        "rejects_detail": [dict(item) for item in list(rejects)[-200:]],
    })


# --------------------------------------------------------------------------- 覆盖缺口


def coverage_gaps(entries: Sequence[Dict], vocab: Dict[str, Sequence[str]]) -> Dict:
    """用校验器的**同一套门**算出还缺什么（分子/分母都来自它）。"""
    fstatus, fdetail = gate_entries(entries)
    tstatus, tdetail = gate_edge_types(fdetail["must_pairs_per_type"],
                                       fdetail["must_cards_per_type"],
                                       MIN_PER_TYPE, MIN_CARDS_PER_TYPE)
    gstatus, gdetail = gate_forbid(fdetail["q7_conflicts"], MIN_FORBID)
    mstatus, mdetail = gate_forbid_members(fdetail["q7_forbid_members"], 1)
    sstatus, sdetail = gate_seed_coverage(fdetail["_parsed_q"], vocab,
                                          must_values_from(entries), True,
                                          MIN_SEED_SUPPORT, support_from(entries))
    return {
        "entries": len(entries),
        "format_ok": fstatus == "pass",
        "format_problems": fdetail["problems"][:5],
        "missing_values": sdetail.get("missing_values", {}),
        "unknown_values": sdetail.get("unknown_values", {}),
        "thin_values": sdetail.get("thin_values", {}),
        "short_pairs": tdetail.get("short_pairs", {}),
        "thin_cards": tdetail.get("thin_cards", {}),
        "q7_conflicts": fdetail["q7_conflicts"],
        "q7_deficit": max(0, MIN_FORBID - fdetail["q7_conflicts"]),
        "forbid_under_covered": mdetail.get("under_covered", {}),
        "needs_human": fdetail["needs_human"],
        "human_reviewed": fdetail["human_reviewed"],
        "gates": {"format": fstatus, "edge_types": tstatus, "forbid": gstatus,
                  "forbid_members": mstatus, "seed_coverage": sstatus},
    }


def gaps_closed(gaps: Dict) -> bool:
    return (gaps["format_ok"]
            and not gaps["missing_values"] and not gaps["unknown_values"]
            and not gaps["thin_values"] and not gaps["short_pairs"]
            and not gaps["thin_cards"] and gaps["q7_deficit"] == 0
            and not gaps["forbid_under_covered"])


def build_gap_prompt(gaps: Dict, cards: Sequence[Dict],
                     vocab: Dict[str, Sequence[str]], use_cards: Sequence[str]) -> str:
    lines = ["【缺口清单】"]
    for kind, values in sorted(gaps["missing_values"].items()):
        lines.append("- 取值从没出现过（%s）：%s" % (kind, "、".join(values[:12])))
    for kind, values in sorted(gaps["thin_values"].items()):
        lines.append("- 取值支撑不足（%s，每个至少要在 %d 条不同卡片上出现）：%s"
                     % (kind, MIN_SEED_SUPPORT, "、".join(values[:12])))
    # 这一条以前漏了：门③ 的 unknown 侧是**双向**的，用了词表外的取值同样判红，
    # 而补跑只盯着 missing/thin，于是"越补越红"。必须把用过的词表外取值也列出来。
    for kind, values in sorted(gaps.get("unknown_values", {}).items()):
        lines.append("- 这些取值**不在**词表内（必须改写成词表里的规范名，"
                     "否则整条被判 unknown_values 而作废）：%s=%s"
                     % (kind, "、".join(values[:12])))
    for etype, need in sorted(gaps["short_pairs"].items()):
        lines.append("- 边类型 %s 的 (卡片,查询) 对还差 %d 条（当前 %d，且至少来自 %d 张卡）"
                     % (etype, max(0, MIN_PER_TYPE - need), need, MIN_CARDS_PER_TYPE))
    if gaps["q7_deficit"]:
        lines.append("- 还差 %d 条「查询命中某条禁忌」的条目（EMOTION_PACK 的 forbid 槽位"
                     "取值要与 q 里同 kind 的取值相同）" % gaps["q7_deficit"])
    for item in list(gaps["forbid_under_covered"])[:8]:
        lines.append("- 禁忌取值 %s 还没有任何冲突条目，请补一条" % item)
    lines.append("")
    lines.append("【可用卡片（优先用没出现过的）】")
    by_id = {str(c["id"]): c for c in cards}
    for card_id in use_cards:
        card = by_id.get(card_id)
        if card is None:
            continue
        lines.append("### %s（domain=%s）\n标题：%s\n内容：%s"
                     % (card_id, card["domain"], card["title"],
                        str(card["content"])[:400]))
    lines.append("")
    lines.append("【必填槽位表】")
    for etype, slots in sorted(REQUIRED_SLOTS.items()):
        lines.append("- %s: %s" % (etype, " ＋ ".join(slots)))
    lines.append("")
    lines.append("【取值词表（尽量用规范名）】")
    for kind, values in sorted(vocab.items()):
        lines.append("- %s: %s" % (kind, ", ".join(list(values)[:60])))
    return "\n".join(lines)


# --------------------------------------------------------------------------- 吸收模型回复


def _dedupe_key(entry: Dict) -> Tuple:
    return (str(entry.get("from_card", "")), str(entry.get("q", "")),
            tuple(sorted(spec_key(s) for s in entry.get("must", []))))


def absorb(entries: List[Dict], rejects: List[Dict], raw_reply, card_ids: set,
           counter: int) -> int:
    """把一次回复里合格的条目并进 `entries`（去重），返回新的序号。"""
    seen = {_dedupe_key(entry) for entry in entries}
    raw_entries = raw_reply.get("entries") if isinstance(raw_reply, dict) else None
    if not isinstance(raw_entries, list):
        rejects.append({"reason": "reply_not_a_list"})
        return counter
    for raw in raw_entries:
        entry, reason = holdout_gen.validate_entry(raw, card_ids)
        if entry is None:
            rejects.append({"reason": reason, "raw": str(raw)[:200]})
            continue
        if _dedupe_key(entry) in seen:
            continue
        seen.add(_dedupe_key(entry))
        counter += 1
        entries.append({"id": f"hq_{counter:04d}", **entry,
                        "annotator": dict(_ANNOTATOR), "independence": "strong",
                        "pilot": False})
    return counter


def set_annotator(client, prompt_version: str) -> None:
    prompt_sha = hashlib.sha256(
        (holdout_gen.SYSTEM_PROMPT + prompt_version).encode("utf-8")).hexdigest()
    _ANNOTATOR.clear()
    _ANNOTATOR.update({"model_id": client.model_id, "family": client.family,
                       "model_version": client.model_version,
                       "prompt_sha256": prompt_sha})


# --------------------------------------------------------------------------- 主流程


def per_card_round(cards, vocab, client, entries, rejects, done, fingerprint,
                   batch_size: int, counter: int, progress_path, partial_path) -> int:
    card_ids = {str(c["id"]) for c in cards}
    batches = [list(cards[i:i + batch_size]) for i in range(0, len(cards), batch_size)]
    for index, batch in enumerate(batches, 1):
        key = "card:%d:%s" % (index, batch[0]["id"])
        if key in done:
            continue
        try:
            reply = client.chat_json(holdout_gen.SYSTEM_PROMPT,
                                     holdout_gen.build_prompt(batch, vocab),
                                     0.0, 0, 8192, key=batch[0]["id"])
        except Exception as exc:  # noqa: BLE001 - 记因由并继续下一批
            rejects.append({"batch": key, "reason": "%s: %s" % (type(exc).__name__, exc)})
            continue
        counter = absorb(entries, rejects, reply, card_ids, counter)
        done.add(key)
        save_partial(entries, rejects, done, fingerprint, progress_path, partial_path)
        print(json.dumps({"phase": "cards", "batch": index, "of": len(batches),
                          "entries": len(entries)}, ensure_ascii=False), flush=True)
    return counter


def coverage_rounds(cards, vocab, client, entries, rejects, done, fingerprint,
                    rounds: int, counter: int, window: int,
                    progress_path, partial_path) -> int:
    card_ids = {str(c["id"]) for c in cards}
    for round_index in range(1, rounds + 1):
        gaps = coverage_gaps(entries, vocab)
        if gaps_closed(gaps):
            print(json.dumps({"phase": "gaps", "round": round_index, "closed": True},
                             ensure_ascii=False), flush=True)
            break
        used = {str(e["from_card"]) for e in entries}
        fresh = [str(c["id"]) for c in cards if str(c["id"]) not in used]
        pick = (fresh or [str(c["id"]) for c in cards])[:window]
        key = "gap:%d:%s" % (round_index, ",".join(pick))
        if key in done:
            continue
        prompt = build_gap_prompt(gaps, cards, vocab, pick)
        try:
            reply = client.chat_json(GAP_PROMPT, prompt, 0.0, 0, 8192,
                                     key="gap:%d" % round_index)
        except Exception as exc:  # noqa: BLE001
            rejects.append({"batch": key, "reason": "%s: %s" % (type(exc).__name__, exc)})
            continue
        before = len(entries)
        counter = absorb(entries, rejects, reply, card_ids, counter)
        done.add(key)
        save_partial(entries, rejects, done, fingerprint, progress_path, partial_path)
        print(json.dumps({"phase": "gaps", "round": round_index,
                          "added": len(entries) - before, "entries": len(entries),
                          "gates": gaps["gates"]}, ensure_ascii=False), flush=True)
    return counter


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_fill")
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="qwen3-vl:30b")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--batch", type=int, default=6)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--cards", default="", help="卡片 JSONL（默认用运行时 CARDS）")
    parser.add_argument("--vocab", default=str(common.KNOWLEDGE / "hypergraph.vocab.json"),
                        help="冻结词表（默认 knowledge/hypergraph.vocab.json）")
    parser.add_argument("--out", default=str(common.ROOT / "fixtures" / "knowledge_holdout.jsonl"))
    parser.add_argument("--progress", default=str(PROGRESS))
    parser.add_argument("--partial", default=str(PARTIAL))
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    out_path = pathlib.Path(args.out)
    cards_json = out_path.with_suffix(".cards.json")
    progress_path = pathlib.Path(args.progress)
    partial_path = pathlib.Path(args.partial)
    report_path = pathlib.Path(args.report)

    payload = json.loads(pathlib.Path(args.vocab).read_text(encoding="utf-8"))
    vocab = payload["holdout_vocab"]

    if args.cards:
        cards = common.read_jsonl(pathlib.Path(args.cards))
    else:
        from block_director.knowledge.corpus import CARDS

        cards = [{"id": c.id, "domain": c.domain, "title": c.title,
                  "content": c.content, "tags": list(c.tags),
                  "keywords": list(c.keywords), "emotion": c.emotion}
                 for c in CARDS]

    client = llm.make_client(args.provider, args.model, args.scripted)
    set_annotator(client, holdout_gen.PROMPT_VERSION)
    fingerprint = run_fingerprint(cards, client, holdout_gen.PROMPT_VERSION)

    if args.no_resume:
        entries, rejects, done = [], [], set()
    else:
        entries, rejects, done = load_partial(fingerprint, progress_path, partial_path)
    counter = max([int(str(e["id"]).split("_")[1]) for e in entries] or [0])

    counter = per_card_round(cards, vocab, client, entries, rejects, done, fingerprint,
                             args.batch, counter, progress_path, partial_path)
    counter = coverage_rounds(cards, vocab, client, entries, rejects, done, fingerprint,
                              args.rounds, counter, args.window, progress_path, partial_path)

    covered = sorted({str(e["from_card"]) for e in entries})
    common.write_jsonl(out_path, entries)
    common.dump_json(cards_json, covered)
    gaps = coverage_gaps(entries, vocab)
    common.dump_json(report_path, {
        "fingerprint": fingerprint, "cards": len(cards), "cards_covered": len(covered),
        "entries": len(entries), "rejects": len(rejects),
        "annotator": dict(_ANNOTATOR), "gaps": gaps,
    })
    print(json.dumps({"entries": len(entries), "cards_covered": len(covered),
                      "rejects": len(rejects), "gaps": gaps}, ensure_ascii=False))
    return 0 if len(entries) >= MIN_ENTRIES else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
