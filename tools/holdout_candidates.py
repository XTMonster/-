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
import sys
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
        "规则：must 1–3 条；top1 ⊆ must；never 与 must 不相交；q 的键只用协议 §2.1 的词表。\n"
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


def draft_all(cards: Iterable[dict], transport: Transport) -> List[dict]:
    out: List[dict] = []
    for card in cards:
        raw = transport(prompt_for(card))
        try:
            draft = parse_draft(raw)
        except ValueError as exc:
            out.append({"from_card": card.get("id"), "error": str(exc)})
            continue
        draft["from_card"] = card.get("id")
        draft["_prompt_sha256"] = hashlib.sha256(
            prompt_for(card).encode("utf-8")).hexdigest()
        out.append(draft)
    return out


def disagreements(a: Sequence[dict], b: Sequence[dict]) -> List[str]:
    """Card ids whose two drafts differ on `must`."""
    by_b = {d.get("from_card"): d for d in b}
    out = []
    for draft in a:
        other = by_b.get(draft.get("from_card"))
        if other is None or draft.get("error") or other.get("error"):
            out.append(str(draft.get("from_card")))
            continue
        if sorted(draft.get("must") or []) != sorted(other.get("must") or []):
            out.append(str(draft.get("from_card")))
    return out


def finalise(draft: dict, idx: int, *, family: str, independence: str,
             transport: str) -> dict:
    """Turn a raw draft into an entry `check_holdout.py` can validate.

    Only `review` is left for the human — everything mechanical (id, annotator,
    independence) is filled here so the pipeline is closed end to end.
    """
    if draft.get("error"):
        return draft
    out = dict(draft)
    out.pop("_prompt_sha256", None)
    out["id"] = f"hq_{idx:04d}"
    out.setdefault("never", [])
    out.setdefault("expect_movements", [])
    out["annotator"] = {"model_id": transport, "family": family,
                        "model_version": "", "prompt_sha256": ""}
    out["independence"] = independence
    return out


def render_sheet(drafts: Sequence[dict], diff_ids: Sequence[str]) -> str:
    """The Markdown 选择题 a human actually reads (only the disagreements)."""
    lines = ["# held-out 裁决表（只列两个族分歧的条目）", "",
             "对的打勾；都不对就写一句期望。", ""]
    want = set(diff_ids)
    for draft in drafts:
        if draft.get("from_card") not in want:
            continue
        lines.append(f"## {draft.get('from_card')}")
        lines.append("")
        lines.append(f"查询：`{draft.get('q', '')}`")
        lines.append("")
        lines.append("| 候选「必须边」 | 采纳？ |")
        lines.append("|---|---|")
        for spec in draft.get("must") or []:
            lines.append(f"| `{spec}` | [ ] |")
        lines.append("")
        lines.append(f"期望运镜：`{', '.join(draft.get('expect_movements') or []) or '（未给）'}`")
        lines.append("")
    return "\n".join(lines) + "\n"


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
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cards = load_cards(args.cards)
    if args.n:
        cards = cards[: args.n]
    transport_a = build_transport(args.transport_a)
    raw_drafts = draft_all(cards, transport_a)

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    diff_ids: List[str] = []
    family_b = args.family_b or f"{args.family}-b"
    if args.transport_b != "none":
        transport_b = build_transport(args.transport_b)
        drafts_b = draft_all(cards, transport_b)
        diff_ids = disagreements(raw_drafts, drafts_b)
        (out_dir / "disagreements.json").write_text(
            json.dumps(diff_ids, ensure_ascii=False, indent=2), encoding="utf-8")
    independence = "strong" if family_b != args.family else "weak"
    drafts = [finalise(d, i, family=args.family, independence=independence,
                       transport=args.transport_a)
              for i, d in enumerate(raw_drafts, 1)]
    (out_dir / "candidates.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in drafts) + "\n", encoding="utf-8")

    sheet = render_sheet(drafts, diff_ids or [str(d.get("from_card")) for d in drafts])
    (out_dir / "candidates.md").write_text(sheet, encoding="utf-8")

    ok = sum(1 for d in drafts if not d.get("error"))
    print(json.dumps({"cards": len(cards), "drafted": ok,
                      "errors": len(drafts) - ok, "disagreements": len(diff_ids),
                      "out_dir": str(out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
