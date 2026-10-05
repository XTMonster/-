"""第三方裁定（Kimi K3）—— 用户 2026-10-06 授权它代替自己做人工审核判断。

与其他两个复核者的区别（这是本工具存在的全部理由）：

* `tools/holdout_review.py` 产出的记录写 `reviewed_by: "human"` —— 那要求人去填
  markdown 表；用户长期不在家，这份一直空着（`human 0/212`）。
* `tools/holdout_review_llm.py` 产出 `reviewed_by: "llm-panel"` —— DeepSeek ＋ GLM
  两个模型，而它们同时是评委族（deepseek-chat / glm-5.3）。
* 本工具产出 `reviewed_by: "third-party"` —— Kimi K3 一个模型，它既不是抽取器
  （deepseek）、也不是标注器（zhipu）、也与两位评委不同族，所以它是这份语料之外的
  独立判词。用户 2026-10-06 的原话是"这个裁定是指代替我做人工审核判断"，
  所以它承担的是人审那一层，但记录如实写 third-party，绝不冒充 human
  （`check_holdout.gate_human_review` 的 `--reviewer-classes` 才决定它算不算数）。

判据一字不改：直接复用 `holdout_review_llm.SYSTEM`（`review/v2`）与
`entry_prompt()` 与 `_judge()`，所以它与 llm-panel 的判决逐字可比；
`source.prompt_sha256` 就是那份提示词的指纹，`check_holdout.review_class()` 据此认它。

用法::

  python tools/holdout_review_third_party.py --entries fixtures/knowledge_holdout.jsonl \
      --out work/holdout_third_party.reviewed.jsonl \
      --report work/holdout_third_party.json --sheet work/holdout_third_party_disagreements.md

离线自测：`--scripted` 传一份 JSON 桩（与 `tools/kb_fetch/llm.py` 的 scripted 后端同一约定）。
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import threading
from concurrent import futures
from typing import Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.holdout_review import needs_human  # noqa: E402
from tools.holdout_review_llm import (  # noqa: E402
    PROMPT_VERSION, SYSTEM, _judge, load_cards)
from tools.kb_fetch import llm  # noqa: E402

#: 裁决者类别。不许写 "human"：那是要人填的（见模块 docstring）。
THIRD_PARTY_TAG = "third-party"

#: 授权出处：进每条记录的 `source.authorized_by`，这样"凭什么是它来裁"永远可追。
AUTHORIZED_BY = "user-2026-10-06:third-party adjudication stands in for my human review"

#: 判决 → 动作。与 `holdout_review_llm.merge()` 同一张表。
ACTION_OF = {"accepted": "keep", "rejected": "drop", "amended": "flag"}


def select_third_party(entries: Sequence[Dict], limit: int = 0,
                       include_reviewed: bool = True) -> List[Dict]:
    """要第三方裁的条目：`needs_human` 且还没有 third-party 记录。

    `include_reviewed=True`（默认）连已经带 llm-panel 记录的也算——用户的诉求是
    "代替我做人工审核"，人审那一层本来就要覆盖完整的一批，只补空缺会让这份判词
    不是全量、无法与 llm-panel 逐条对拍。
    `include_reviewed=False` 退回 `holdout_review_llm.select()` 的语义（只补空缺）。
    """
    chosen = []
    for entry in sorted(entries, key=lambda item: str(item.get("id", ""))):
        if not needs_human(entry):
            continue
        review = entry.get("review") or {}
        if str(review.get("reviewed_by") or "").strip().lower() == THIRD_PARTY_TAG:
            continue
        if not include_reviewed and review:
            continue
        chosen.append(entry)
    return chosen[:limit] if limit else chosen


def build_record(entry: Dict, decision: Dict, source: Dict) -> Dict:
    """一条第三方裁决记录（形状与 llm-panel 对齐，只有 reviewed_by 与 source 不同）。"""
    verdict = str(decision.get("verdict") or "")
    record = {
        "id": str(entry.get("id", "")),
        "action": ACTION_OF.get(verdict, "retry"),
        "review": {
            "reviewed_by": THIRD_PARTY_TAG,
            "verdict": verdict,
            "reason": str(decision.get("reason") or ""),
            "fix": str(decision.get("fix") or ""),
            "agreement": True,
            "source": source,
        },
        "detail": {"id": str(entry.get("id", "")), "verdict": verdict,
                   "reason": str(decision.get("reason") or "")},
    }
    if record["action"] == "retry":
        #: `error` 不是判决（holdout_review_llm 实测过：把 429 写成 amended）。
        #: 第三方这边同样不落记录——缺证据不是通过。
        record.pop("review")
    return record


def merge_entries(entries: Sequence[Dict],
                  rows: Sequence[Dict]) -> "tuple[List[Dict], List[str]]":
    """把第三方判决**并进条目**（与 `holdout_review_llm` 同一套语义）。

    * `keep` / `flag` ⇒ 把 `review` 写进该条目（`flag` 额外打 `panel_disagreement`，
      因为它与 `llm-panel` 不一致的会在对拍表里）；
    * `drop` ⇒ **从 held-out 里剔除**（第三方判"这条期望不成立"，留着会污染 oracle）；
    * `retry` ⇒ 原样保留、**不写 review**（缺证据不是通过）。

    返回 `(新条目表, 被剔除的 id)`。**纯函数**：不碰网络、不写盘，所以可离线测。
    """
    by_id = {str(row.get("id", "")): row for row in rows if row.get("id")}
    kept: List[Dict] = []
    dropped: List[str] = []
    for entry in entries:
        ident = str(entry.get("id", ""))
        row = by_id.get(ident)
        review = (row or {}).get("review")
        action = str((row or {}).get("action") or "")
        if row is not None and action == "drop":
            #: **分歧不静默剔除**（2026-10-06 实测出来的口径）：第三方判 rejected，但如果
            #: 该条目上原本挂着 `llm-panel` 的 accepted/amended，那就是**两位裁决者分歧**，
            #: 按本仓纪律（"分歧单独成表，人只裁分歧"）应当**保留并标记**，而不是按一方
            #: 的意见把它删掉。删掉还有第二重代价：`gen_cine_0247` 那条是它所属卡片的
            #: **唯一**一条期望，剔除它会让门⑥ 的 `missing_cards` 直接变红——一条 1:1 的
            #: 分歧不该有这种后果。只有"两边都判 rejected"（或对面没有记录）才真剔除。
            prior = entry.get("review") or {}
            prior_by = str(prior.get("reviewed_by") or "").strip().lower()
            prior_verdict = str(prior.get("verdict") or "").strip().lower()
            if prior_by and prior_by != "human" and prior_verdict != "rejected":
                merged = dict(entry)
                merged["review"] = review
                merged["panel_disagreement"] = True
                kept.append(merged)
                continue
            dropped.append(ident)
            continue
        merged = dict(entry)
        if review:
            merged["review"] = review
            if action == "flag":
                merged["panel_disagreement"] = True
        kept.append(merged)
    return kept, dropped


def compare_sheet(rows: Sequence[Dict], entries_by_id: Dict[str, Dict]) -> List[str]:
    """与既有 llm-panel 记录对拍，只列分歧（人只需看这一份）。"""
    lines: List[str] = []
    for row in rows:
        review = row.get("review") or {}
        if not review:
            continue
        ident = str(row.get("id", ""))
        prior = (entries_by_id.get(ident) or {}).get("review") or {}
        if str(prior.get("reviewed_by") or "").strip().lower() != "llm-panel":
            continue
        if str(prior.get("verdict")) == str(review.get("verdict")):
            continue
        lines.append("- **%s**：llm-panel `%s`（%s）／ third-party `%s`（%s）"
                     % (ident, prior.get("verdict"), str(prior.get("reason") or "")[:60],
                        review.get("verdict"), str(review.get("reason") or "")[:60]))
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="holdout_review_third_party")
    parser.add_argument("--entries", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="0 = 不限")
    #: 用户 2026-10-06："**gpt6A 只能用于人工裁决和执行计划书写，其他的用 glm 和 DeepSeek**"
    #: ＋"**使用 gpt6A 时思考强度拉到最大**"。人工裁决正是这两条允许用途之一，
    #: 所以这里的默认通道改成中转站 GPT-6A（`reasoning_effort=max` 由 `RelayClient` 默认带上；
    #: 实测同一问题 reasoning 40 → 1034 token，见 `work/_probe_linkai_thinking.py`）。
    #: `--provider kimi` 仍可用（历史上那 212 条判词就是 `kimi-k3` 产出的，记录里写着型号）。
    parser.add_argument("--model", default="")
    parser.add_argument("--provider", default="relay")
    parser.add_argument("--out", default="work/holdout_third_party.reviewed.jsonl")
    parser.add_argument("--report", default="work/holdout_third_party.json")
    parser.add_argument("--sheet", default="work/holdout_third_party_disagreements.md")
    parser.add_argument("--scripted", default="")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--only-unreviewed", action="store_true",
                        help="只补没有 llm-panel 记录的那些（默认：全量）")
    parser.add_argument("--merge-from", default="",
                        help="只做合并（不联网）：读一份本次工具产出的判决 jsonl，"
                             "把 review 写进条目、剔掉 drop，落 --merged")
    parser.add_argument("--merged", default="",
                        help="合并结果写到哪里（配 --merge-from；不写就不合并）")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    entries = [json.loads(line) for line in
               pathlib.Path(args.entries).read_text(encoding="utf-8").splitlines()
               if line.strip()]

    if args.merge_from:
        if not args.merged:
            raise SystemExit("--merge-from 必须配 --merged")
        rows = [json.loads(line) for line in
                pathlib.Path(args.merge_from).read_text(encoding="utf-8").splitlines()
                if line.strip()]
        kept, dropped = merge_entries(entries, rows)
        out = ROOT / args.merged
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n"
                               for item in kept),
                       encoding="utf-8", newline="\n")
        print(json.dumps({"merged_into": str(out), "entries_in": len(entries),
                          "entries_out": len(kept), "dropped": dropped},
                         ensure_ascii=False))
        return 0

    entries_by_id = {str(entry.get("id", "")): entry for entry in entries}
    cards = load_cards()
    picked = select_third_party(entries, args.limit,
                                include_reviewed=not args.only_unreviewed)

    source = {
        "model": str(args.model or ("gpt-6-astra" if args.provider != "kimi" else "kimi-k3")),
        "prompt_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
        "prompt_version": PROMPT_VERSION,
        "tool": "holdout_review_third_party",
        "adjudicator_provider": str(args.provider),
        "authorized_by": AUTHORIZED_BY,
        "ran_at": datetime.datetime.now(
            datetime.timezone.utc).astimezone().isoformat(timespec="seconds"),
    }

    if args.scripted:
        client = llm.make_client("scripted", source["model"], args.scripted)
    else:
        client = llm.make_client(args.provider, source["model"])

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    counts = {"selected": len(picked), "keep": 0, "drop": 0, "flag": 0, "retry": 0}
    rows: List[Dict] = []

    def decide(entry: Dict) -> Dict:
        card = cards.get(str(entry.get("from_card")), {})
        decision = _judge(client, entry, card)
        return build_record(entry, decision, dict(source))

    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        with futures.ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as pool:
            for record in pool.map(decide, picked):
                with lock:
                    rows.append(record)
                    action = str(record.get("action") or "retry")
                    counts[action] = counts.get(action, 0) + 1
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()

    kept = [row for row in rows if row.get("review")]
    lines = compare_sheet(rows, entries_by_id)
    sheet = ROOT / args.sheet
    sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.write_text(
        "# 第三方裁定（`%s`）与 llm-panel 的分歧清单\n\n"
        "授权：`%s`。裁决者写的是 `third-party`，不是 `human`。\n\n"
        % (source["model"], AUTHORIZED_BY)
        + ("\n".join(lines) if lines else "（无分歧）") + "\n",
        encoding="utf-8", newline="\n")

    report = {"tool": "holdout_review_third_party", "reviewer_class": THIRD_PARTY_TAG,
              "source": source, "counts": counts, "records": len(kept),
              "disagreements_with_llm_panel": len(lines),
              "out": str(out_path), "sheet": str(sheet)}
    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
