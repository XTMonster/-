"""把 `pool_ceiling.json` 里那条**单查询**的断言补成**全量**：银行文件序前 6 == 产品检索器前 6？

`probe_pool_ceiling.py` 只拿**第一条查询**验过 `bank_order_equals_shipped_top6`，
而"`retrieval_order` 就是**去标签池**"这条结论整个压在它上面 ⇒ 必须 64 条全验。

用法：`python -u work/_probe_bank_order.py`（只读，不写仓库文件）
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

sys.path.insert(0, ".")
from block_director.knowledge.cases import load_index  # noqa: E402
from tools.kb_fetch import common  # noqa: E402

BANK = "docs/evidence/20261006-c3-deep-pool/reviews.current.batch3.top120.jsonl"


def main() -> int:
    bank = collections.OrderedDict()
    for row in common.read_jsonl(pathlib.Path(BANK)):
        bank.setdefault(str(row["query"]), []).append(str(row["case_id"]))
    index = load_index(pathlib.Path("knowledge"), backend="hybrid")
    exact = partial = 0
    mismatches = []
    for query, ids in bank.items():
        shipped = [str(c.case_id) for c in index.retrieve(query, top_k=6)]
        first_six = ids[:6]
        if shipped == first_six:
            exact += 1
        else:
            overlap = len(set(shipped) & set(first_six))
            partial += 1
            mismatches.append({"query": query, "overlap": overlap,
                               "bank": first_six, "shipped": shipped})
    payload = {"queries": len(bank), "exact": exact, "mismatched": partial,
               "verdict": "bank file order == shipped retrieve(top_k=6) for every query"
               if partial == 0 else "mismatches exist",
               "mismatches": mismatches}
    pathlib.Path("work/_bank_order_check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({k: payload[k] for k in ("queries", "exact", "mismatched", "verdict")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
