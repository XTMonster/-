"""把**评委的标签**变成重排器的训练/测试集（按查询分组切分，绝不跨查询泄漏）。

为什么需要它（2026-10-06，GPT-6A 会诊给的下一步）：`docs/evidence/20261006-gpt6a-consult/`
的方案是"**固定 50 候选，用原两位评委的标签微调预训练交叉编码重排器**"，
而它自己没点到的前提是——**训练/测试必须按分镜隔离**，否则测出来的是"记住了这批分镜"。
本工具只做**数据这一半**：读一份 `e1_panel` 打分文件，落 `train.jsonl` / `test.jsonl`
＋ `manifest.json`，训练脚本另写。

判据**一个字没动**：标签仍是"**两位评委 1–5 分取均值 ≥ 4.0**"（与
`e1_panel.RELEVANT`／`e1_baseline_summary.RELEVANT` 同源），这里只是把它**摊成监督样本**。

用法::

  python tools/knowledge/rerank_trainset.py \
      --reviews docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top50.jsonl \
      --out-dir work/rerank_trainset --test-queries 16
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402
from tools.kb_fetch.common import read_jsonl  # noqa: E402

#: 判「相关」的下限：与 `e1_panel.RELEVANT` 同源。**只能**是 4.0。
RELEVANT = 4.0


def samples(rows: Sequence[Dict[str, Any]],
            passage_field: str = "excerpt") -> List[Dict[str, Any]]:
    """打分行 → 监督样本。每行给 `(query, passage, label)`，并按查询保序分组。"""
    out: List[Dict[str, Any]] = []
    for row in rows:
        score = row.get("score")
        if not isinstance(score, (int, float)):
            continue                       # 没分的行不进样本（分母不靠猜）
        passage = str(row.get(passage_field) or "").strip()
        if not passage:
            continue
        out.append({"query": str(row.get("query", "")),
                    "case_id": str(row.get("case_id", "")),
                    "passage": passage,
                    "label": 1 if float(score) >= RELEVANT else 0})
    return out


def split_by_query(items: Sequence[Dict[str, Any]], test_queries: int
                   ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[str]]:
    """**按查询**切分（不是按行！）。查询顺序＝文件里第一次出现的顺序，**确定性**。

    为什么必须按查询切（GPT-6A 会诊的第 3 点）：同一个分镜的候选行在训练与测试里同时出现，
    模型只要"认出这批分镜"就能刷分——那是**泄漏**，不是能力。
    """
    grouped: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for item in items:
        grouped.setdefault(item["query"], []).append(item)
    queries = list(grouped)
    if test_queries <= 0 or test_queries >= len(queries):
        raise ValueError("test_queries 必须落在 1..len(queries)-1，收到 %r（共 %d 条查询）"
                         % (test_queries, len(queries)))
    #: 末尾 `test_queries` 条查询做测试：确定性，且与文件顺序无关地可复算。
    test_ids = queries[-test_queries:]
    train_ids = queries[:-test_queries]
    train = [item for q in train_ids for item in grouped[q]]
    test = [item for q in test_ids for item in grouped[q]]
    return train, test, train_ids, test_ids


def _distribution(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    positive = sum(1 for item in items if item["label"] == 1)
    return {"rows": len(items), "positive": positive, "negative": len(items) - positive,
            "positive_rate": round(positive / len(items), 4) if items else 0.0}


def main(argv: Sequence[str] | None = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-rerank-trainset")
    parser.add_argument("--reviews", required=True, help="`e1_panel` 落下的打分 jsonl")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--test-queries", type=int, default=16)
    parser.add_argument("--passage-field", default="excerpt",
                        help="当作「候选正文」的字段（默认 excerpt；`load_cross_encoder` 喂的就是它）")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    reviews_path = pathlib.Path(args.reviews)
    if not reviews_path.is_absolute():
        reviews_path = ROOT / reviews_path
    rows = read_jsonl(reviews_path)
    items = samples(rows, passage_field=args.passage_field)
    train, test, train_ids, test_ids = split_by_query(items, int(args.test_queries))

    out_dir = pathlib.Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in (("train.jsonl", train), ("test.jsonl", test)):
        (out_dir / name).write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in payload),
            encoding="utf-8", newline="\n")
    manifest = {
        "reviews": str(reviews_path),
        "reviews_sha256": hashlib.sha256(reviews_path.read_bytes()).hexdigest(),
        "relevant_threshold": RELEVANT,
        "passage_field": args.passage_field,
        "split": "by-query (deterministic: the LAST test_queries queries in file order)",
        "test_queries": len(test_ids),
        "train_queries": len(train_ids),
        "train": _distribution(train),
        "test": _distribution(test),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
