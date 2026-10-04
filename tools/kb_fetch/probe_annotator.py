"""标注通道体检：**一条命令**告诉当前哪条通道还能用（开发侧探针，只读）。

为什么需要它：held-out 的标注方**必须与抽取器换族**（§2.3c），也就是不能用
DeepSeek。可用通道会随外部状态变化——2026-10-01 实测：

* `glm-4.6` / `glm-4.5` / `glm-4.7` / `glm-4.7-flash`：`HTTP 429 / code 1113
  账户余额不足或没有资源包` —— **智谱的资源包按模型分开计费**，本账号的包是
  `glm-5.3` 的（2026-10-04 用户裁决："用 glm 模型只用 glm-5.3，只有 glm-5.3
  有额度"）。查"有没有额度"必须**逐模型**试，不能拿一个模型的下场推断账号状态
  （这一条让我们白等了几小时；`CHANNELS` 里那两条 glm-4.x 只作历史记录）；
* `ollama`（本机 `qwen3-vl:30b`）：`HTTP 500 prediction aborted, token repeat limit
  reached`。**模型文件是好的**（安装 blob 的 sha256 与 manifest 摘要逐位相同），
  失败发生在加载/推理期；反重复参数与 assistant 预填都试过，仍然瞬间 500。
  用户已裁决**不再使用本地模型**，所以这条通道在探针里保留为"仅记录"；
* `deepseek`：可用，但**换族规则禁止**它当标注方（抽取器就是它）。

用法（每条都真发一次请求，用 3 张卡的最小批）：

    python tools/kb_fetch/probe_annotator.py --cards work/glm_v14/shard0.jsonl
    python tools/kb_fetch/probe_annotator.py --only glm --model glm-5.3
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common, holdout_gen, llm  # noqa: E402

#: 默认体检的通道（intent = 能不能当 held-out 标注方；deepseek 只能当抽取器）。
CHANNELS = (
    #: 用户裁决（2026-10-04）：**GLM 只用 `glm-5.3`**——智谱按模型分别计费，
    #: 这个账号下只有它还有额度（`glm-4.7`/`glm-4.7-flash` 都会 429
    #: 「余额不足或无可用资源包」）。下面的历史条目留着当记录，不再默认使用。
    ("glm", "glm-5.3", "annotator"),
    ("glm", "glm-4.7", "annotator(历史：本账号已无额度)"),
    ("glm", "glm-4.7-flash", "annotator(历史：本账号已无额度)"),
    ("glm", "glm-4.6", "annotator(本机实测 1113：该模型无资源包)"),
    ("ollama", "qwen3-vl:30b", "record-only(用户裁决停用本地模型)"),
    ("deepseek", "deepseek-chat", "extractor-only(换族规则禁止当标注方)"),
)


def probe(provider: str, model: str, cards: Sequence[dict], vocab: dict,
          timeout_note: str = "") -> dict:
    started = time.time()
    try:
        client = llm.make_client(provider, model)
        prompt = holdout_gen.build_prompt(list(cards), vocab)
        reply = client.chat_json(holdout_gen.SYSTEM_PROMPT, prompt, 0.0, 0, 8192, key="probe")
        entries = reply.get("entries") if isinstance(reply, dict) else None
        ok = isinstance(entries, list) and len(entries) > 0
        return {"provider": provider, "model": model, "ok": ok,
                "seconds": round(time.time() - started, 1),
                "entries": len(entries or []) if isinstance(entries, list) else 0,
                "error": "" if ok else "reply_without_entries"}
    except Exception as exc:  # noqa: BLE001 - 探针要给出原因，不是崩掉
        return {"provider": provider, "model": model, "ok": False,
                "seconds": round(time.time() - started, 1), "entries": 0,
                "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.probe_annotator")
    parser.add_argument("--cards", default=str(common.WORK / "glm_v14" / "shard0.jsonl"))
    parser.add_argument("--vocab", default=str(common.KNOWLEDGE / "hypergraph.vocab.json"))
    parser.add_argument("--only", default="", help="只探某个 provider")
    parser.add_argument("--model", default="")
    parser.add_argument("--batch", type=int, default=3)
    parser.add_argument("--json", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cards = [json.loads(line) for line in
             pathlib.Path(args.cards).read_text(encoding="utf-8").splitlines()
             if line.strip()][:args.batch]
    vocab = json.loads(pathlib.Path(args.vocab).read_text(encoding="utf-8"))["holdout_vocab"]
    rows = []
    for provider, model, role in CHANNELS:
        if args.only and provider != args.only:
            continue
        row = probe(provider, args.model or model, cards, vocab)
        row["role"] = role
        rows.append(row)
        print("%-9s %-16s %-34s %s%s"
              % (provider, row["model"], role,
                 "OK %d entries in %.1fs" % (row["entries"], row["seconds"])
                 if row["ok"] else f"FAIL {row['error'][:60]}",
                 "" if row["provider"] != "deepseek" else "  （不可作标注方）"))
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    usable = [r for r in rows if r["ok"] and r["provider"] not in ("deepseek", "ollama")]
    print("可作标注方的通道：", [r["provider"] for r in usable] or "（无）")
    for row in rows:
        if row["ok"] and row["provider"] in ("deepseek", "ollama"):
            print("  注意：%s 即使可用也不作标注方（%s）" % (row["provider"], row["role"]))
    return 0 if usable else 1


if __name__ == "__main__":  # pragma: no cover - 开发侧探针
    raise SystemExit(main())
