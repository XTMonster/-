"""P5-T3（FX-4 / 清单 B4 + G9）的三方词表对拍探针。

只读、只算、只打印：把「知识侧运镜取值」「引擎 24 运镜枚举」「held-out 查询
词表」三份词表拉成一张可复核的对拍表，并复算两张**已经在库里**的别名表
（`hypergraph.VALUE_ALIASES` 与 `execution_closure_report.VALUE_ALIASES`）
覆盖到了哪些值。**不写任何代码、不改任何判据**（红线 R-5）。

用法::

    python docs/evidence/20261007-0610-p5t3t4/probe_movement_alias_table.py --out <json>
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_module(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def knowledge_values() -> dict:
    """索引里 `movement` 节点的 (value, name, aliases)。"""
    out = {}
    path = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") != "movement":
            continue
        out[str(row.get("value") or row.get("name"))] = {
            "name": str(row.get("name") or ""),
            "aliases": [str(item) for item in (row.get("aliases") or [])],
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from block_director.contracts.enums import MOVEMENT_TYPES
    from block_director.knowledge import hypergraph

    vocab = json.loads(
        (ROOT / "fixtures" / "knowledge_holdout.vocab.json").read_text(
            encoding="utf-8"))
    heldout = [str(item) for item in vocab["kinds"]["movement"]]

    closure = _load_module(
        ROOT / "tools" / "knowledge" / "execution_closure_report.py",
        "execution_closure_report_for_probe")

    know = knowledge_values()
    engine = list(MOVEMENT_TYPES)

    #: 逐值分类。判据（写在这里以便复核）：
    #:  * 已等价：知识侧取值**逐字**等于某个引擎枚举（`source_kind == engine`）；
    #:  * 近似：不逐字相等，但**库里已有的别名表**（任一张）把它映射到引擎侧，
    #:    或反过来（引擎枚举的值等于知识侧某个 name/alias）；
    #:  * 无对应：三边都没人认领。
    engine_set = set(engine)
    heldout_set = set(heldout)
    canonical = dict(hypergraph.VALUE_ALIASES)
    closure_aliases = dict(closure.VALUE_ALIASES.get("movement", {}))

    def classify(value: str) -> str:
        if value in engine_set:
            return "已等价"
        target = canonical.get(value) or closure_aliases.get(value)
        if target and target in engine_set:
            return "近似"
        if target and target == "static":
            #: `static` 不是 24 个运镜之一（它是"不动"）——引擎侧表达为
            #: `movements` 数组里没有条目，所以只能算**近似**而不是等价。
            return "近似"
        return "无对应"

    rows = []
    for value in sorted(set(know) | engine_set | heldout_set):
        rows.append({
            "value": value,
            "in_knowledge_index": value in know,
            "knowledge_name": (know.get(value) or {}).get("name", ""),
            "knowledge_aliases": (know.get(value) or {}).get("aliases", []),
            "in_engine_enum": value in engine_set,
            "in_heldout_vocab": value in heldout_set,
            "hypergraph_alias": canonical.get(value, ""),
            "closure_alias": closure_aliases.get(value, ""),
            "class": classify(value),
        })

    counts = {}
    for row in rows:
        counts[row["class"]] = counts.get(row["class"], 0) + 1

    #: 知识侧**只有中文名、没有英文 value** 的那些（若 index 里出现）
    chinese_only = [row["value"] for row in rows
                    if row["in_knowledge_index"]
                    and not row["in_engine_enum"]
                    and not row["value"].isascii()]

    payload = {
        "knowledge_index_values": sorted(know),
        "engine_enum_values": engine,
        "heldout_vocab_values": sorted(heldout_set),
        "engine_not_in_heldout": sorted(engine_set - heldout_set),
        "heldout_not_in_engine": sorted(heldout_set - engine_set),
        "knowledge_not_in_engine": sorted(set(know) - engine_set),
        "rows": rows,
        "counts_by_class": counts,
        "chinese_only_knowledge_values": chinese_only,
        "hypergraph_VALUE_ALIASES": canonical,
        "closure_VALUE_ALIASES": closure_aliases,
        "closure_VALUE_ALIASES_VERSION": closure.VALUE_ALIASES_VERSION,
        "sizes": {
            "knowledge_index": len(know),
            "engine_enum": len(engine),
            "heldout_vocab": len(heldout_set),
            "union": len(rows),
        },
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
        print("MOVEMENT_TABLE", args.out)
    else:
        print(text)
    print("sizes:", payload["sizes"])
    print("counts_by_class:", counts)
    print("engine_not_in_heldout:", payload["engine_not_in_heldout"])
    print("heldout_not_in_engine:", payload["heldout_not_in_engine"])
    print("knowledge_not_in_engine:", payload["knowledge_not_in_engine"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
