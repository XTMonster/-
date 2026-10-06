"""把第三方代裁判词做成**具名、被 pin 的独立输入工件**（门⑦ 换代 gen1→gen2 的那一层）。

依据（人工裁决通道 GLM-5.3，`docs/evidence/20261006-gate7-disambiguation/规格一致性.json`）：
**"pin 绑'运行↔输入'，gate 输入一旦含增量层即是 gen2，与旧夹具字节未动无关；
'逐位命中'只证未篡改，不证切题。增量层必须具名为被 pin 的独立输入工件并登记 gen1→gen2，
否则是无 pin 的影子输入。"**

本工具**只做三件事**（不改夹具、不回写历史 manifest、不碰判据）：

1. 从 `work/knowledge_holdout.third_party.jsonl`（＝夹具 ＋ 212 条 `review` 块的合并件）
   抽出那 212 条裁决 ⇒ `fixtures/knowledge_holdout.third_party.jsonl`（**只带裁决与溯源**）；
2. 把这一轮的产出方自述（模型／提示指纹／跑的时间／计数）抄成
   `fixtures/knowledge_holdout.third_party.manifest.json`；
3. 写换代登记 `fixtures/knowledge_holdout.generations.json`：**gen1 与 gen2 的 `holdout` 指纹
   必须逐位相同**（这正是"用 A 的机制"——不动夹具字节），gen2 多一个 `third_party` 输入。

`--check` 只校验不写：重算一遍，与已入库的三份工件逐位比对，任何漂移非零退出。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any, Dict, List

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common  # noqa: E402

DEFAULTS = {
    "merged": "work/knowledge_holdout.third_party.jsonl",
    "summary": "work/holdout_third_party.json",
    "fixture": "fixtures/knowledge_holdout.jsonl",
    "layer": "fixtures/knowledge_holdout.third_party.jsonl",
    "manifest": "fixtures/knowledge_holdout.third_party.manifest.json",
    "generations": "fixtures/knowledge_holdout.generations.json",
}


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path: pathlib.Path) -> List[Dict[str, Any]]:
    return [row for row in common.read_jsonl(path) if isinstance(row, dict)]


def build(paths: Dict[str, pathlib.Path]) -> Dict[str, Any]:
    """算三份工件的内容（**纯**：不读环境、不写盘，`--check` 也走这里）。"""
    reviewed = [row for row in records(paths["merged"])
                if isinstance(row.get("review"), dict)]
    layer_rows = []
    for row in reviewed:
        review = row["review"]
        layer_rows.append({
            "entry_id": str(row.get("id")),
            "verdict": str(review.get("verdict")),
            "reviewed_by": str(review.get("reviewed_by") or ""),
            "reason": str(review.get("reason") or ""),
            "fix": str(review.get("fix") or ""),
            "agreement": review.get("agreement"),
            "source": review.get("source") or {},
        })
    layer_text = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                         for row in layer_rows)

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    manifest = {
        "tool": "build_third_party_layer",
        "layer": str(paths["layer"]),
        "records": len(layer_rows),
        "counts": summary.get("counts") or {},
        "reviewer_class": summary.get("reviewer_class"),
        "source": summary.get("source") or {},
        "disagreements_with_llm_panel": summary.get("disagreements_with_llm_panel"),
        "note": "**这一层是 gate 的输入之一**：pin 它 = pin 这一代；旧夹具的字节不动。",
    }
    holdout_sha = sha256_file(paths["fixture"])
    generations = {
        "current": "gen2",
        "generations": [
            {"id": "gen1",
             "inputs": {"holdout": holdout_sha},
             "note": "P14 那一代：只有夹具，没有第三方层。"},
            {"id": "gen2",
             "inputs": {"holdout": holdout_sha,
                        "third_party": hashlib.sha256(
                            layer_text.encode("utf-8")).hexdigest()},
             "transition": {
                 "from": "gen1",
                 "reason": "把第三方代裁并入 gate 的输入（口径闭合：合并件已过门①–⑩ 却计账 "
                           "third-party 0）",
                 "counts": summary.get("counts") or {},
                 "diff_note": "**夹具字节未动**（gen1 与 gen2 的 `holdout` 指纹逐位相同）——"
                              "这正是裁决允许的'用 A 的机制'；但按裁决，**输入集合变了就是换代**。",
                 "pending": ["tools/check_holdout.py 加 --third-party 并让门⑦ 按代计数",
                             "那 6 条按 'pin == 夹具 sha' 断言的测试改成**按代断言**",
                             "新开一次 gate 运行（gens2 的第一份证据）"],
             }},
        ],
    }
    return {"layer_text": layer_text, "manifest": manifest, "generations": generations}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-third-party-layer")
    for key, default in DEFAULTS.items():
        parser.add_argument("--" + key.replace("_", "-"), default=default)
    parser.add_argument("--check", action="store_true",
                        help="只校验：重算并与已入库工件比对（漂移 ⇒ 非零退出）")
    args = parser.parse_args(argv)
    paths = {key: ROOT / getattr(args, key) for key in DEFAULTS}
    built = build(paths)

    layer_path, manifest_path = paths["layer"], paths["manifest"]
    generations_path = paths["generations"]
    if args.check:
        problems = []
        if not layer_path.is_file():
            problems.append("缺 %s" % layer_path.relative_to(ROOT))
        elif layer_path.read_text(encoding="utf-8") != built["layer_text"]:
            problems.append("%s 与源不一致" % layer_path.relative_to(ROOT))
        for path, payload in ((manifest_path, built["manifest"]),
                              (generations_path, built["generations"])):
            if not path.is_file():
                problems.append("缺 %s" % path.relative_to(ROOT))
                continue
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            if on_disk != payload:
                problems.append("%s 与源不一致" % path.relative_to(ROOT))
        if problems:
            print(json.dumps({"ok": False, "problems": problems}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "records": built["manifest"]["records"]},
                         ensure_ascii=False))
        return 0

    layer_path.write_text(built["layer_text"], encoding="utf-8", newline="\n")
    manifest_path.write_text(json.dumps(built["manifest"], ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    generations_path.write_text(
        json.dumps(built["generations"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({"written": [str(path.relative_to(ROOT))
                                  for path in (layer_path, manifest_path, generations_path)],
                      "records": built["manifest"]["records"],
                      "counts": built["manifest"]["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
