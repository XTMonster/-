"""用**评委的标签**微调一个交叉编码重排器——GPT-6A 会诊给的下一步（执行那一半）。

为什么走这条（`docs/evidence/20261006-gpt6a-consult/` 的判词）：候选面挖到 50 之后**完美重排
上限是 0.8438**，而"让大模型读清单挑 3 条"六种配置全试过、**见顶在 0.41～0.46**；
**零样本** cross-encoder 更差（k=50 时 0.1094、k=20 时 0.1302）。剩下没试的就是
**有监督的重排器**——它同时解决两件事：① 用监督信号逼近上限；② **与两位评委不同族**。

判据**一个字没动**：标签仍是"两位评委 1–5 分取均值 ≥ 4.0"（`rerank_trainset.RELEVANT`）。

**评价用"代理 E1"**：在**按查询留出**的测试集上，看模型选出的前 3 条里有多少条是
`rerank_trainset` 标好的相关项——即 `mean(min(3,c) ∩ top3 / 3)`，与"完美重排上限"
（同一个测试集上是 `mean(min(3,c)/3)`）**同一把尺子**，所以代理值/上限就是"拿到了几成"。
**代理不是最终 E1**：最终 E1 要用两位评委**重新盲评**模型选出的 3 条（另一步）。

只读环境变量、绝不写密钥；在 sidecar 的 venv 里跑（main 环境零依赖）。用法::

  work\\_venv_lr\\Scripts\\python.exe -m tools.knowledge.rerank_finetune \
      --trainset work/rerank_trainset --out work/reranker_ft --epochs 2 --batch 4
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys
import time
from collections import OrderedDict
from typing import Any, Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402
from tools.kb_fetch.common import read_jsonl  # noqa: E402


def _read_jsonl(path: pathlib.Path) -> List[Dict[str, Any]]:
    #: 走全仓唯一的 JSONL 读入口（`tests/test_jsonl_reading_convention.py` 守这条）。
    return list(read_jsonl(path))


def group_by_query(items: Sequence[Dict[str, Any]]
                   ) -> "OrderedDict[str, List[Dict[str, Any]]]":
    grouped: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for item in items:
        grouped.setdefault(str(item["query"]), []).append(item)
    return grouped


def proxy_e1(ranked: Dict[str, List[str]], grouped: Dict[str, List[Dict[str, Any]]],
             top_k: int = 3) -> Dict[str, Any]:
    """代理 E1 ＝ 模型前 `top_k` 条里命中多少个**已被标为相关**的行 ÷ `top_k` 的均值。

    与"完美重排上限"同一把尺：上限是 `mean(min(top_k, 相关行数) / top_k)`。
    """
    hits = 0
    ceiling = 0
    for query, items in grouped.items():
        relevant = {str(item["case_id"]) for item in items if item["label"] == 1}
        chosen = [case_id for case_id in ranked.get(query, [])[:top_k]]
        hits += len([case_id for case_id in chosen if case_id in relevant])
        ceiling += min(top_k, len(relevant))
    n = len(grouped) * top_k
    return {"queries": len(grouped),
            "proxy_e1": round(hits / n, 4) if n else 0.0,
            "perfect_ceiling": round(ceiling / n, 4) if n else 0.0,
            "hits": hits, "ceiling_hits": ceiling}


def main(argv: Sequence[str] | None = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-rerank-finetune")
    parser.add_argument("--trainset", default="work/rerank_trainset")
    parser.add_argument("--out", default="work/reranker_ft")
    parser.add_argument("--base", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="")
    parser.add_argument("--zero-shot-only", action="store_true",
                        help="只量零样本基线，不训练（先拿到对照）")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    trainset = pathlib.Path(args.trainset)
    if not trainset.is_absolute():
        trainset = ROOT / trainset
    train = _read_jsonl(trainset / "train.jsonl")
    test = _read_jsonl(trainset / "test.jsonl")
    test_grouped = group_by_query(test)

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base, num_labels=1).to(device)

    def rank_all(items_grouped) -> Dict[str, List[str]]:
        """按模型分数给每条查询的候选排序（确定性：no_grad ＋ eval）。"""
        model.eval()
        ranked: Dict[str, List[str]] = {}
        with torch.no_grad():
            for query, items in items_grouped.items():
                scores: List[tuple] = []
                for start in range(0, len(items), 16):
                    chunk = items[start:start + 16]
                    batch = tokenizer([query] * len(chunk),
                                      [str(item["passage"]) for item in chunk],
                                      padding=True, truncation=True,
                                      max_length=args.max_length, return_tensors="pt")
                    batch = {k: v.to(device) for k, v in batch.items()}
                    logits = model(**batch).logits.view(-1)
                    scores.extend(zip([str(i["case_id"]) for i in chunk],
                                      [float(v) for v in logits]))
                #: 并列按 case_id 定序（与 `rerank_cases` 同一约定）。
                ranked[query] = [cid for cid, _ in
                                 sorted(scores, key=lambda pair: (-pair[1], pair[0]))]
        return ranked

    report: Dict[str, Any] = {"base": args.base, "device": device, "seed": args.seed,
                              "train_rows": len(train), "test_rows": len(test)}
    report["zero_shot"] = proxy_e1(rank_all(test_grouped), test_grouped)
    print("zero-shot:", json.dumps(report["zero_shot"], ensure_ascii=False))
    if args.zero_shot_only:
        print(json.dumps(report, ensure_ascii=False))
        return 0

    positives = sum(1 for item in train if item["label"] == 1)
    negatives = len(train) - positives
    #: 正例只有 ~10% ⇒ 用类权重，别让模型学会"全判负"。
    pos_weight = torch.tensor([max(1.0, negatives / max(1, positives))], device=device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    def collate(batch):
        tokens = tokenizer([item["query"] for item in batch],
                           [str(item["passage"]) for item in batch],
                           padding=True, truncation=True,
                           max_length=args.max_length, return_tensors="pt")
        labels = torch.tensor([float(item["label"]) for item in batch])
        return tokens, labels

    loader = DataLoader(train, batch_size=args.batch, shuffle=True, collate_fn=collate)
    started = time.time()
    model.train()
    steps = 0
    for epoch in range(1, int(args.epochs) + 1):
        running = 0.0
        for tokens, labels in loader:
            tokens = {k: v.to(device) for k, v in tokens.items()}
            labels = labels.to(device)
            optimiser.zero_grad()
            logits = model(**tokens).logits.view(-1)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimiser.step()
            running += float(loss)
            steps += 1
            if steps % 50 == 0:
                print("epoch %d step %d loss %.4f (%.0fs)"
                      % (epoch, steps, running / 50, time.time() - started))
                running = 0.0
    report["fine_tuned"] = proxy_e1(rank_all(test_grouped), test_grouped)
    report["train_seconds"] = round(time.time() - started, 1)
    report["steps"] = steps
    report["pos_weight"] = float(pos_weight)
    print("fine-tuned:", json.dumps(report["fine_tuned"], ensure_ascii=False))

    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out)
    tokenizer.save_pretrained(out)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
