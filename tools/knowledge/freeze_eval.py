"""P6③：把评测集**冻起来**（计划里 `freeze_eval.py` 那一步）。

为什么必须有：A/B 的可比性全靠"三臂跑在**同一批查询**上"。而这批查询来自一次
真实运行（`project.bdproj`）——运行一换代、查询就换，"哪条检索路更好"就变成
拿两把尺子量。所以评测集要落成一个**带摘要的冻结文件**，当三臂的共同输入。

三条纪律（见 `tests/test_freeze_eval.py`）：

* **可复算**：同输入 ＋ 同种子 ⇒ 同抽样、同摘要（不是"随机一次"）；
* **摘要随内容变**：改一行内容 ⇒ 摘要必须变；
* **如实记来源**：manifest 里写清它从哪来、条数、抽样参数——否则以后没人知道
  这批行是怎么来的。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import sys
from typing import Dict, List, Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

MANIFEST_NAME = "heldout.manifest.json"


def freeze(queries: Sequence[str], *, source: str, seed: int, size: int) -> Dict:
    """抽样并算摘要。**纯函数**：同输入 ＋ 同种子 ⇒ 同结果。"""
    items = [str(query) for query in queries if str(query).strip()]
    count = len(items) if int(size) <= 0 else min(int(size), len(items))
    #: `random.Random(seed).sample` 是确定性的；列表本身有序 ⇒ 抽样可复算。
    picked = list(items) if count == len(items) else sorted(
        random.Random(int(seed)).sample(items, count))
    payload = "\n".join(picked) + ("\n" if picked else "")
    return {"source": str(source), "seed": int(seed), "size": len(picked),
            "available": len(items), "queries": picked,
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}


def write(out: pathlib.Path, queries: Sequence[str], *, source: str, seed: int,
          size: int) -> Dict:
    report = freeze(queries, source=source, seed=seed, size=size)
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(report["queries"]) + "\n", encoding="utf-8")
    manifest = {key: value for key, value in report.items() if key != "queries"}
    manifest["file"] = out.name
    manifest["file_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    (out.parent / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge.freeze_eval")
    parser.add_argument("--queries", required=True,
                        help="一行一条查询的文本文件（或 --project 的产物）")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20261005)
    parser.add_argument("--size", type=int, default=0, help="0 = 全取")
    args = parser.parse_args(list(argv) if argv is not None else None)

    path = pathlib.Path(args.queries)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").split("\n")
             if line.strip()]
    report = write(pathlib.Path(args.out), lines, source=str(path),
                   seed=args.seed, size=args.size)
    print(json.dumps({key: value for key, value in report.items() if key != "queries"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
