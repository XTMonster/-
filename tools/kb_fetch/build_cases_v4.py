"""P6：把影子语料按**现役管线**喂成案例层的输入（许可门）。

为什么是"编排"而不是"重写"：`validate_licenses.py`（出处/许可/长度）与
`build_cases.py`（线索门、体积门、按源配额）都是**已被门检验过**的；重写等于把那些门
再实现一遍，而且一定会漂。所以本模块只做三件事：按顺序调用、把中间产物落在
**影子目录**、把拒绝具名记下来。

**默认是直通，不是 `chunk.run`**（2026-10-05 实测抓到的缺陷）：`chunk.py` 是 **L1/L2
那条路**的分段器，它会**跳过全部 `layers: [L3]` 来源**（L3 只喂案例层，不进 chunks）。
而现役 `build_cases.INPUT` 指的是 `licensed.jsonl`（**整篇来源**），它自己会
`segments_of(text)` 再切。我最初把 `chunk.run` 接在这里，结果 v4 案例层只看到
43 个来源、**202 条 L3 来源整批没进去**（那正是现役 1143 条案例的主力）。

**一条纪律**（本项目踩过两次的同一类坑）：`validate_licenses.run()` 会写现役的
`work/licensed.jsonl`——本模块只用它的**纯函数** `check()` 逐条判，绝不调 `run()`。
守门：`tests/test_build_cases_v4.py::test_the_shadow_build_does_not_touch_the_shipped_work_inputs`。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    from . import chunk as chunk_mod  # type: ignore
    from . import common  # type: ignore
    from . import validate_licenses as licences  # type: ignore
except ImportError:  # pragma: no cover - 直跑
    from tools.kb_fetch import chunk as chunk_mod  # type: ignore
    from tools.kb_fetch import common  # type: ignore
    from tools.kb_fetch import validate_licenses as licences  # type: ignore

#: 交给 `build_cases --input` 的那份文件（名字与现役管线一致，便于对照）。
INPUT_NAME = "licensed.jsonl"
REJECTS_NAME = "licence_rejects.jsonl"


def prepare_case_inputs(records: Sequence[Dict], *, out_dir: pathlib.Path,
                        chunk_fn: Optional[Callable] = None,
                        check_fn: Optional[Callable] = None,
                        **chunk_kwargs) -> Tuple[List[Dict], List[Dict], Dict]:
    """分段 → 许可门 → 落 `<out_dir>/licensed.jsonl`。返回 `(kept, rejects, stats)`。"""
    #: **默认直通**：案例层的输入是许可门后的"整篇来源"，`build_cases` 自己会切段。
    #: 接 `chunk.run` 会**丢掉全部 `layers: [L3]` 来源**（那是 L1/L2 那条路的分段器）。
    chunker = chunk_fn or (lambda rows, **kwargs: list(rows))
    checker = check_fn or licences.check
    chunks = list(chunker(list(records), **chunk_kwargs))
    kept: List[Dict] = []
    rejects: List[Dict] = []
    for record in chunks:
        try:
            ok, reason = checker(record)
        except Exception as exc:  # noqa: BLE001 - 单条失败不吞掉整批
            ok, reason = False, "licence_check_error:%s" % type(exc).__name__
        if ok:
            kept.append(record)
        else:
            rejects.append({"source_ref": record.get("source_ref", {}),
                            "domain": record.get("domain", ""), "reason": reason})
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    common.write_jsonl(out_dir / INPUT_NAME, kept)
    common.write_jsonl(out_dir / REJECTS_NAME, rejects)
    stats = {"chunks": len(chunks), "kept": len(kept), "rejected": len(rejects),
             "closes": (len(kept) + len(rejects)) == len(chunks)}
    return kept, rejects, stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb_fetch.build_cases_v4")
    parser.add_argument("--corpus", default=str(common.WORK / "corpus_v4"),
                        help="影子语料目录（读 fetched.jsonl）")
    parser.add_argument("--out", required=True, help="影子案例目录")
    parser.add_argument("--max-cases", type=int, default=0,
                        help="0 = 用 build_cases 的默认")
    parser.add_argument("--per-source", type=int, default=0)
    parser.add_argument("--prepare-only", action="store_true",
                        help="只做到 licensed.jsonl，不跑 build_cases")
    args = parser.parse_args(list(argv) if argv is not None else None)

    corpus = pathlib.Path(args.corpus)
    #: **必须**用 `common.read_jsonl`（只按 `\n` 切）。`read_text().splitlines()` 会按
    #: Unicode 行边界（`\u0085`/`\u2028`/`\u2029`）切开 JSON 字符串——实测在
    #: `work/corpus_v4/fetched.jsonl` 上直接抛 `JSONDecodeError: Unterminated string`。
    records = common.read_jsonl(corpus / "fetched.jsonl")
    out_dir = pathlib.Path(args.out)
    kept, rejects, stats = prepare_case_inputs(records, out_dir=out_dir)
    print(json.dumps({"overall": "pass", "stage": "prepare", **stats,
                      "out": str(out_dir)}, ensure_ascii=False))
    if args.prepare_only or not kept:
        return 0

    #: 交给**现役** `build_cases`（线索门/体积门/按源配额都在它里面）。
    try:  # noqa: PLC0415 - 两种入口都要认：包导入与脚本直跑
        from . import build_cases as bc  # type: ignore
    except ImportError:
        from tools.kb_fetch import build_cases as bc  # type: ignore
    argv_next = ["--input", str(out_dir / INPUT_NAME), "--out-dir", str(out_dir)]
    if args.max_cases:
        argv_next += ["--max-cases", str(args.max_cases)]
    if args.per_source:
        argv_next += ["--per-source", str(args.per_source)]
    return bc.main(argv_next)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
