"""把**已入库的真实运行**里的逐镜散文（`scenes[].shots[].prompt`）汇成一个查询池。

为什么需要它（2026-10-06，`docs/evidence/20261006-gpt6a-consult/` 第 3 点）：
GPT-6A 会诊的验收判据是"**另取 100 个未见分镜**盲评"，而现冻结查询集只有 **64 条**
（来自 `20261006-long21` 一个项目）——不够，任何"赢/没赢"都落在噪声里。

本仓 `docs/evidence/` 下有 **28 份 `project.bdproj`**（多次真实运行），每份的每个镜头都带
一段 `prompt`（导演指令的散文）。**同一份脚本被分块跑过多次**（`chunked_long*`），
所以**必须按文本去重**，否则"未见"是假的。本工具只做"收集＋去重＋如实记账"，
抽样与冻结交给 `freeze_eval.py`（它才是冻结集的唯一入口）。

用法::

  python tools/knowledge/collect_shot_prompts.py --roots docs/evidence \
      --out work/eval_sets/shot_prompts.pool.txt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Dict, List, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402

#: 查询池是**一行一条**（`freeze_eval` 与 `e1_panel --queries` 都按行读）。
#: 实测（2026-10-06）：5 条 `prompt` 里带换行 ⇒ 原样写出会让池文件 1,251 条变 **1,275 行**，
#: 冻出来的"查询"里混进**碎片**。所以这里把**内部空白折叠成一个空格**（不改字词）。
_WHITESPACE = re.compile(r"\s+")


def prompts_of(project: Dict[str, Any]) -> List[str]:
    """一个 `project.bdproj` 里的逐镜散文（保持场景/镜头顺序）。"""
    out: List[str] = []
    for scene in project.get("scenes") or []:
        for shot in scene.get("shots") or []:
            text = _WHITESPACE.sub(" ", str(shot.get("prompt") or "")).strip()
            if text:
                out.append(text)
    return out


def collect(paths: Sequence[pathlib.Path]) -> Dict[str, Any]:
    """读所有项目 → 去重后的池 ＋ 逐文件的账（**先记账、再给池**）。"""
    seen: Dict[str, str] = {}          # text -> 第一次出现的文件（可追）
    per_file: List[Dict[str, Any]] = []
    for path in sorted(paths):
        try:
            project = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            per_file.append({"file": str(path), "error": "%s: %s" % (type(exc).__name__, exc)[:120]})
            continue
        shots = prompts_of(project)
        fresh = 0
        duplicates = 0
        for text in shots:
            if text in seen:
                duplicates += 1
            else:
                seen[text] = str(path)
                fresh += 1
        per_file.append({"file": str(path), "shots": len(shots),
                         "new": fresh, "duplicate": duplicates})
    return {"files": per_file, "pool": list(seen), "first_seen": seen}


def main(argv: Sequence[str] | None = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-collect-shot-prompts")
    parser.add_argument("--roots", nargs="+", default=["docs/evidence"])
    parser.add_argument("--out", default="work/eval_sets/shot_prompts.pool.txt")
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    paths: List[pathlib.Path] = []
    for root in args.roots:
        base = pathlib.Path(root)
        if not base.is_absolute():
            base = ROOT / base
        paths.extend(sorted(base.rglob("project.bdproj")))
    report = collect(paths)
    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(text + "\n" for text in report["pool"]),
                   encoding="utf-8", newline="\n")
    manifest = {"files": report["files"], "projects": len(report["files"]),
                "pool_size": len(report["pool"]),
                "pool_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                "out": str(out)}
    (out.parent / "shot_prompts.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
