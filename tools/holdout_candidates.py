"""Draft held-out candidates from the card corpus, and render a human choice sheet.

Flow (execution plan §2.3c, R49/R50):

    cards  ->  [model A]  ->  candidates.jsonl   (one draft per card)
           ->  [model B]  ->  disagreements      (only these go to the human)
           ->  candidates.md                    (the 选择题 sheet a human actually reads)

The model call is injectable so the whole pipeline runs offline and is unit-testable:
the default `offline` transport is deterministic and needs no network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import threading
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Iterable, List, Sequence

#: domain -> the edge type a card of that domain is most likely to justify
DOMAIN_EDGE = {
    "cinematography": "SHOT_PATTERN",
    "composition": "SHOT_PATTERN",
    "axis_theory": "AXIS_RULE",
    "blocking": "EMOTION_PACK",
    "performance": "EMOTION_PACK",
    "editing": "EDIT_RHYTHM",
    "anime": "TROPE",
    "storyboard": "SHOT_PATTERN",
    "production": "EDIT_RHYTHM",
}

Transport = Callable[[str], str]


def prompt_for(card: dict) -> str:
    """The labelling prompt handed to a drafting model (frozen wording)."""
    return (
        "你在为一个白模预演插件的知识库做标注。给定一张知识卡，产出 1 条检索期望条目。\n"
        "只输出 JSON：{\"q\": \"键=值；键=值\", \"must\": [\"TYPE:槽位=取值,...\"], "
        "\"top1\": [...], \"never\": [...], \"expect_movements\": [...]}\n"
        "规则：\n"
        "1. must 1–3 条；top1 ⊆ must；never 与 must 不相交。\n"
        "2. q 的键只用协议 §2.1 的冻结键集（情绪/动作/运镜/景别/镜头/节奏/特效/音效/"
        "机位/光线/构图/轴线/题材/桥段），取值只用冻结词表里的规范名。\n"
        "3. **禁忌必须写出来**：若这张卡说明某个取值应当被禁止，写成 "
        "`forbid_<kind>=取值`（例：`EMOTION_PACK:emotion=荒诞,intensity=high,forbid_shot_size=特写`）。\n"
        "4. 若某个关键词应当**被禁止**（而不是被要求），把它同时写进 `q` 与 `forbid_<kind>`——"
        "这正是 Q7 要测的「禁忌拦截」，**至少 1/20 的条目必须带这种冲突**。\n"
        "5. 每条边的必填槽位：EMOTION_PACK(emotion,intensity)／SHOT_PATTERN(shot_size,lens,headroom_policy)／"
        "AXIS_RULE(pair,axis_side)／TROPE(genre,emotion)／EDIT_RHYTHM(pacing,avg_shot_len)／"
        "LIGHT_PACK(lighting,intensity)。\n"
        f"卡 id：{card.get('id')}\n域：{card.get('domain')}\n标题：{card.get('title')}\n"
        f"关键词：{','.join(str(k) for k in (card.get('keywords') or []))}\n"
        f"正文：{card.get('content')}\n"
    )


def card_from_prompt(prompt: str) -> dict:
    """Read back the card fields the frozen prompt carries (used by the stubs)."""
    out: Dict[str, str] = {}
    for line in prompt.splitlines():
        for label, key in (("卡 id：", "id"), ("域：", "domain"), ("标题：", "title"),
                           ("关键词：", "keywords"), ("正文：", "content")):
            if line.startswith(label):
                out[key] = line[len(label):].strip()
    return out


def offline_transport(prompt: str) -> str:
    """Deterministic stub: derive one plausible candidate straight from the prompt."""
    card = card_from_prompt(prompt)
    domain = card.get("domain") or "cinematography"
    etype = DOMAIN_EDGE.get(domain, "SHOT_PATTERN")
    title = card.get("title") or card.get("id") or "未命名"
    keywords = [k for k in (card.get("keywords") or "").split(",") if k][:3]
    q_key = {"motion": "运镜", "景别": "景别", "构图": "构图", "轴线": "轴线",
             "光线": "光线", "机位": "机位", "节奏": "节奏", "情绪": "情绪"}.get(
        title[:2], "景别")
    q_value = keywords[-1] if keywords else title
    slots = {
        "EMOTION_PACK": f"emotion={title},intensity=mid",
        "SHOT_PATTERN": f"shot_size={q_value},lens=50mm,headroom_policy=board",
        "AXIS_RULE": "pair=any_two,axis_side=right",
        "TROPE": f"genre=film,emotion={title}",
        "EDIT_RHYTHM": "pacing=short_cut,avg_shot_len=2.0",
        "LIGHT_PACK": f"lighting={q_value},intensity=mid",
    }[etype]
    spec = f"{etype}:{slots}"
    return json.dumps({"q": f"{q_key}={q_value}", "must": [spec], "top1": [spec],
                       "never": [], "expect_movements": []}, ensure_ascii=False)


def offline_transport_b(prompt: str) -> str:
    """A deliberately different stub standing in for the second family.

    It swaps the `must` edge to a different type so that the disagreement path is
    exercised end to end without a network call.
    """
    payload = json.loads(offline_transport(prompt))
    spec = payload["must"][0]
    if spec.startswith("SHOT_PATTERN:"):
        swapped = "LIGHT_PACK:lighting=中景,intensity=mid"
    else:
        swapped = "SHOT_PATTERN:shot_size=中景,lens=50mm,headroom_policy=board"
    payload["must"] = [swapped]
    payload["top1"] = [swapped]
    payload["expect_movements"] = []
    return json.dumps(payload, ensure_ascii=False)


def build_transport(name: str) -> Transport:
    """`offline` | `offline-b` | `http:<url>` (OpenAI-compatible /chat/completions)."""
    if name == "offline":
        return offline_transport
    if name == "offline-b":
        return offline_transport_b
    if name.startswith("http"):
        import urllib.request

        def _http(prompt: str) -> str:  # pragma: no cover - network path
            body = json.dumps({"model": "annotator",
                               "messages": [{"role": "user", "content": prompt}],
                               "temperature": 0}).encode("utf-8")
            req = urllib.request.Request(
                name, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

        return _http
    raise SystemExit(f"未知 transport: {name}")


def parse_draft(raw: str) -> dict:
    """Tolerate code fences and surrounding prose; return the JSON object."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"没有 JSON 对象：{raw[:80]!r}")
    draft = json.loads(text[start:end + 1])
    for key in ("q", "must", "top1", "never"):
        if key not in draft:
            raise ValueError(f"草稿缺字段 {key}")
    draft.setdefault("expect_movements", [])
    return draft


def load_checkpoint(path: pathlib.Path, family: str) -> Dict[str, dict]:
    """`card_id -> draft` for entries whose prompt fingerprint still matches."""
    if not path.is_file():
        return {}
    done: Dict[str, dict] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if row.get("family") == family and row.get("card"):
            done[str(row["card"])] = row
    return done


def draft_all(cards: Iterable[dict], transport: Transport, *, family: str = "",
              concurrency: int = 1, checkpoint: pathlib.Path | None = None,
              calls: List[str] | None = None) -> List[dict]:
    """Draft every card, optionally in parallel and resumable.

    The checkpoint is keyed by `(card, family, prompt_sha256)` so a prompt change
    invalidates the cached draft instead of silently reusing it. Writing happens as
    each result lands, so a crash costs at most the in-flight calls.
    """
    cards = list(cards)
    cached = load_checkpoint(checkpoint, family) if checkpoint else {}
    lock = threading.Lock()
    results: Dict[str, dict] = {}
    pending: List[dict] = []

    for card in cards:
        cid = str(card.get("id"))
        prompt = prompt_for(card)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        row = cached.get(cid)
        if row and row.get("prompt_sha256") == digest and not row.get("error"):
            draft = dict(row.get("draft") or {})
            draft["from_card"] = cid
            draft["_prompt_sha256"] = digest
            results[cid] = draft
            continue
        pending.append({"card": card, "prompt": prompt, "digest": digest, "id": cid})

    def work(item: dict) -> None:
        if calls is not None:
            with lock:
                calls.append(item["id"])
        try:
            draft = parse_draft(transport(item["prompt"]))
        except ValueError as exc:
            draft = {"from_card": item["id"], "error": str(exc)}
        draft["from_card"] = item["id"]
        draft["_prompt_sha256"] = item["digest"]
        with lock:
            results[item["id"]] = draft
            if checkpoint is not None:
                with open(checkpoint, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps({"card": item["id"], "family": family,
                                         "prompt_sha256": item["digest"],
                                         "draft": {k: v for k, v in draft.items()
                                                   if not k.startswith("_")}},
                                        ensure_ascii=False) + "\n")

    if pending:
        if concurrency > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                list(pool.map(work, pending))
        else:
            for item in pending:
                work(item)
    return [results[str(card.get("id"))] for card in cards if str(card.get("id")) in results]


def disagreements(a: Sequence[dict], b: Sequence[dict]) -> List[str]:
    """Card ids whose two drafts differ on anything that feeds an oracle.

    `q` is Q5's join key, `never` is Q3's input, `top1` is Q1's — comparing only
    `must` (the old behaviour) would let those disagreements reach the file unadjudicated.
    """
    by_b = {d.get("from_card"): d for d in b}
    keys = ("q", "must", "top1", "never")
    out = []
    for draft in a:
        other = by_b.get(draft.get("from_card"))
        if other is None or draft.get("error") or other.get("error"):
            out.append(str(draft.get("from_card")))
            continue
        if any(sorted(draft.get(k) or []) != sorted(other.get(k) or []) for k in keys):
            out.append(str(draft.get("from_card")))
    return out


def finalise(draft: dict, idx: int, *, family: str, model_id: str, model_version: str,
             independence: str) -> dict:
    """Turn a raw draft into an entry `check_holdout.py` can validate.

    Only `review` is left for the human — everything mechanical (id, annotator,
    independence) is filled here so the pipeline is closed end to end.

    The `annotator` block is the **evidence chain for the family switch** (R49), so it
    must carry the real model id/version and the prompt hash — putting the transport
    name there (the old behaviour) made the chain silently empty.
    """
    if draft.get("error"):
        return draft
    out = dict(draft)
    out["id"] = f"hq_{idx:04d}"
    out.setdefault("never", [])
    out.setdefault("expect_movements", [])
    out["annotator"] = {"model_id": model_id, "family": family,
                        "model_version": model_version,
                        "prompt_sha256": draft.get("_prompt_sha256", "")}
    out["independence"] = independence
    return out


def render_sheet(drafts: Sequence[dict], diff_ids: Sequence[str]) -> str:
    """The Markdown 选择题 a human actually reads (only the disagreements)."""
    lines = ["# held-out 裁决表（只列两个族分歧的条目）", "",
             "打勾 = 采纳（写入 accepted）；都不对就在该节末尾写 `rejected: 原因`。",
             "填完用 `--merge-from decisions.json` 合并，本表的 `id` 就是键。", ""]
    want = set(diff_ids)
    for draft in drafts:
        if draft.get("from_card") not in want:
            continue
        lines.append(f"## {draft.get('id', '')} · {draft.get('from_card')}")
        lines.append("")
        lines.append(f"查询：`{draft.get('q', '')}`")
        lines.append("")
        lines.append("| id | 候选「必须边」 | 采纳 |")
        lines.append("|---|---|---|")
        for spec in draft.get("must") or []:
            lines.append(f"| `{draft.get('id', '')}` | `{spec}` | [ ] |")
        lines.append("")
        lines.append(f"期望运镜：`{', '.join(draft.get('expect_movements') or []) or '（未给）'}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def sheet_to_decisions(sheet_text: str) -> Dict[str, str]:
    """Read a ticked `candidates.md` back into `{id: verdict}`.

    Without this the human's ticks had to be hand-transcribed into JSON — the missing
    half of the last mile.
    """
    decisions: Dict[str, str] = {}
    current: str | None = None
    for raw in sheet_text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            current = line[3:].split("·")[0].strip()
            continue
        if current and line.lower().startswith("rejected:"):
            decisions[current] = "rejected"
            continue
        if current and "|" in line and re.search(r"\[\s*x\s*\]", line, re.I):
            decisions[current] = "accepted"
    return decisions


def merge_decisions(entries: Sequence[dict], decisions: Dict[str, object]) -> List[dict]:
    """Apply the human's verdicts — this is the missing last mile.

    `decisions` maps entry id -> `"accepted" | "rejected" | "amended"` or
    `{"verdict": ..., "note": ...}`. Rejected entries are dropped; the rest get a
    `review` record so the audit trail survives into `knowledge_holdout.jsonl`.
    An unknown id is a hard error (it means the sheet and the file drifted apart).
    """
    known = {str(e.get("id")) for e in entries}
    unknown = sorted(set(decisions) - known)
    if unknown:
        raise SystemExit(f"[merge] 裁决表里有 {len(unknown)} 个未知 id：{unknown[:5]}")
    out: List[dict] = []
    for entry in entries:
        ident = str(entry.get("id"))
        verdict = decisions.get(ident)
        note = ""
        if isinstance(verdict, dict):
            verdict, note = verdict.get("verdict"), str(verdict.get("note") or "")
        if verdict == "rejected":
            continue
        merged = dict(entry)
        if verdict:
            merged["review"] = {"reviewed_by": "human", "verdict": verdict,
                                **({"note": note} if note else {})}
        out.append(merged)
    return out


def link_stub_chain(final: Sequence[dict], draft_a: Sequence[dict], draft_b: Sequence[dict],
                    *, family_a: str, family_b: str) -> List[dict]:
    """Record both families' drafts on each surviving entry (audit trail)."""
    by_b = {str(d.get("from_card")): d.get("must") for d in draft_b}
    by_a = {str(d.get("from_card")): d.get("must") for d in draft_a}
    out = []
    for entry in final:
        card = str(entry.get("from_card"))
        merged = dict(entry)
        merged["drafts"] = {family_a: by_a.get(card), family_b: by_b.get(card)}
        out.append(merged)
    return out


def load_cards(path: str) -> List[dict]:
    if path:
        payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return [{"id": c} if isinstance(c, str) else c for c in payload]
    try:  # default: the in-repo card corpus
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from block_director.knowledge.corpus import CARDS  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise SystemExit(f"读不到内置卡片库（用 --cards 指定 JSON）：{exc}")
    out = []
    for card in CARDS:
        out.append({"id": card.id, "domain": card.domain, "title": card.title,
                    "content": card.content, "keywords": list(card.keywords)})
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_candidates")
    parser.add_argument("--cards", default="", help="卡片 JSON（默认用内置语料）")
    parser.add_argument("--n", type=int, default=0, help="最多处理几张卡（0=全部）")
    parser.add_argument("--transport-a", default="offline")
    parser.add_argument("--transport-b", default="offline-b",
                        help="第二个族；写 none 则跳过分歧检测")
    parser.add_argument("--family", default="offline", help="写进 annotator.family（第一个族）")
    parser.add_argument("--family-b", default="", help="第二个族的 family（默认 = --family + '-b'）")
    parser.add_argument("--extractor-family", default="",
                        help="抽取器的 family；independence 由「标注族 vs 抽取族」派生（协议 §5.1）")
    parser.add_argument("--model-id", default="", help="标注模型 id（写进 annotator）")
    parser.add_argument("--model-version", default="", help="标注模型版本")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="起草并发数（同一族的请求并行发出；默认 1）")
    parser.add_argument("--resume", action="store_true",
                        help="用 <out-dir>/draft_checkpoint.jsonl 续跑（指纹相同才复用）")
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--merge-from", default="",
                        help="裁决文件（{id: accepted|rejected|amended}）；给了它就只做合并")
    parser.add_argument("--merge-into", default="",
                        help="要合并的 candidates.jsonl（默认 <out-dir>/candidates.jsonl）")
    parser.add_argument("--final", default="",
                        help="合并后的产物路径（默认 <out-dir>/knowledge_holdout.jsonl）")
    parser.add_argument("--merge-sheet", default="",
                        help="也可以直接给人打勾的 candidates.md（会先转成 decisions）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    out_dir = pathlib.Path(args.out_dir)
    if args.merge_from or args.merge_sheet:
        src = pathlib.Path(args.merge_into or (out_dir / "candidates.jsonl"))
        entries = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
        if args.merge_sheet:
            decisions = sheet_to_decisions(
                pathlib.Path(args.merge_sheet).read_text(encoding="utf-8"))
        else:
            decisions = json.loads(pathlib.Path(args.merge_from).read_text(encoding="utf-8"))
        final = merge_decisions(entries, decisions)
        dest = pathlib.Path(args.final or (out_dir / "knowledge_holdout.jsonl"))
        dest.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in final) + "\n",
                        encoding="utf-8")
        print(json.dumps({"merged": len(entries), "kept": len(final),
                          "rejected": len(entries) - len(final), "out": str(dest)},
                         ensure_ascii=False))
        return 0

    cards = load_cards(args.cards)
    if args.n:
        cards = cards[: args.n]
    transport_a = build_transport(args.transport_a)

    out_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = (out_dir / "draft_checkpoint.jsonl") if args.resume else None
    raw_drafts = draft_all(cards, transport_a, family=args.family,
                           concurrency=max(1, args.concurrency), checkpoint=checkpoint)

    diff_ids: List[str] = []
    family_b = args.family_b or f"{args.family}-b"
    if args.transport_b != "none":
        transport_b = build_transport(args.transport_b)
        drafts_b = draft_all(cards, transport_b, family=family_b,
                             concurrency=max(1, args.concurrency), checkpoint=checkpoint)
        diff_ids = disagreements(raw_drafts, drafts_b)
        (out_dir / "disagreements.json").write_text(
            json.dumps(diff_ids, ensure_ascii=False, indent=2), encoding="utf-8")
    # 协议 §5.1：strong/weak 由「标注族 vs **抽取族**」派生，与「两个标注族之间」
    # 是否相同无关。没给 --extractor-family 时只能记 weak（保守，不得冒充 strong）。
    independence = "strong" if (args.extractor_family
                                and args.extractor_family != args.family) else "weak"
    model_id = args.model_id or args.transport_a
    drafts = [finalise(d, i, family=args.family, model_id=model_id,
                       model_version=args.model_version, independence=independence)
              for i, d in enumerate(raw_drafts, 1)]
    if args.transport_b != "none":
        drafts = link_stub_chain(drafts, raw_drafts, drafts_b,
                                 family_a=args.family, family_b=family_b)
    (out_dir / "candidates.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in drafts) + "\n", encoding="utf-8")

    sheet = render_sheet(drafts, diff_ids or [str(d.get("from_card")) for d in drafts])
    (out_dir / "candidates.md").write_text(sheet, encoding="utf-8")

    ok = sum(1 for d in drafts if not d.get("error"))
    print(json.dumps({"cards": len(cards), "drafted": ok,
                      "errors": len(drafts) - ok, "disagreements": len(diff_ids),
                      "independence": independence, "out_dir": str(out_dir)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
