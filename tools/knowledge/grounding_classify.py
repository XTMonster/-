"""90 槽位三分类的**机械汇总**：把逐批产物落成裁定给的那条可证伪结论。

出处（`docs/evidence/20261007-grounding-ruling/README.md` §1 第③条）：

    从 1,262 条未佐证槽位**分层抽 90 条**人工三分类
    （**蕴含未写出／挂错卡／取错值**）：后两类 ≤10% ⇒ "修数据"被证伪
    （主体是蕴含，删边会误伤）；**≥33% 且模式一致** ⇒ "暂缓重抽"被证伪，
    应启动换代；中间 ⇒ 按各 kind 真错率排队。

三类（问题文件逐字钉的闭集）：

* ``hidden``      —— 蕴含未写出（卡的**主题**对，只是没写出取值本身）——良性；
* ``wrong_card``  —— 挂错卡（卡的主题与取值不是一回事）——腐蚀下游；
* ``wrong_value`` —— 取错值（主题对、取值抄错/编错）——腐蚀下游。

**它只做机械汇总，不动判据**：门限 ``0.10`` / ``0.33`` 是裁定给的，写在
``HIDDEN_DOMINANT_MAX`` / ``CORRUPT_DOMINANT_MIN``；比较用**整数交叉相乘**
（``corrupt*10 <= total``、``corrupt*100 >= 33*total``）而不是浮点，免得
``9/90`` 那种恰好落在门上的样本被舍入判到隔壁支。

**形状不对就具名失败**（本仓的规矩）：缺一批产物、JSON 不是数组、``class``
越枚举、``i`` 对不上批次长度、批里的取值挂不回样本行 —— 一律 ``raise``，
**不**静默跳过、**不**把缺项算进 ``hidden``。缺项算成"良性"正是这条判据最怕的
污染方式。

用法::

    python tools/knowledge/grounding_classify.py
    python tools/knowledge/grounding_classify.py --batches 12 \
        --sample-dir docs/evidence/20261007-grounding-sample90

产物：``<sample-dir>/三分类汇总.json``（计数 ＋ 占比 ＋ 落在哪一支 ＋ 逐
kind／stratum／type 的拆分 ＋ 每份输入的 sha256 取证）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
import time
from typing import Dict, List, Mapping, Optional, Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 三分类的闭集——与 `work/_q_grounding_batch*.md` 里钉的输出契约逐字一致。
CLASSES = ("hidden", "wrong_card", "wrong_value")
#: 裁定里的"后两类"（腐蚀下游的那两组）。
CORRUPT_CLASSES = ("wrong_card", "wrong_value")
#: 两条门限（**判据级常量，一个字不许动**）。
HIDDEN_DOMINANT_MAX = 0.10
CORRUPT_DOMINANT_MIN = 0.33
#: 同一个门限的整数百分比形式——比较用它，避免 `9/90` 这种落在门上的样本被浮点舍到隔壁。
_HIDDEN_PCT = round(HIDDEN_DOMINANT_MAX * 100)      # 10
_CORRUPT_PCT = round(CORRUPT_DOMINANT_MIN * 100)    # 33

#: 问题文件里的一行小标题：``## 1. `kind:value`（边 hg:xxxx，类型 TYPE）``
ITEM_HEADER = re.compile(
    r"^## (\d+)\. `(.+?)`（边 ([^，]+)，类型 ([^）]+)）$", re.MULTILINE)

#: 批产物文件名（`--plain` 下"角色名"退化成产物的标签，见 `tools/glm_consult.py`）。
RESULT_NAME = "三分类.json"


class GroundingClassifyError(Exception):
    """几何/形状对不上——具名失败，绝不静默补 0。"""


def parse_question_items(text: str) -> List[Dict[str, object]]:
    """问题文件里的有序小标题 → ``[{i, value, edge_id, type}]``。"""
    items: List[Dict[str, object]] = []
    for match in ITEM_HEADER.finditer(text):
        items.append({"i": int(match.group(1)),
                      "value": match.group(2),
                      "edge_id": match.group(3),
                      "type": match.group(4)})
    return items


def index_sample(sample: Mapping[str, object]) -> Dict[tuple, dict]:
    """样本行按 ``(edge_id, value, type)`` 建索引——三分类结果就靠它挂回样本。"""
    rows = sample.get("rows")
    if not isinstance(rows, list) or not rows:
        raise GroundingClassifyError("sample90.json 里没有 rows（样本为空）")
    index: Dict[tuple, dict] = {}
    for row in rows:                                   # type: ignore[assignment]
        if not isinstance(row, dict):
            raise GroundingClassifyError("样本里出现非对象行：%r" % (row,))
        key = (row.get("edge_id"), row.get("value"), row.get("type"))
        if key in index:
            raise GroundingClassifyError("样本里有重复键 %r（抽样框不是一对一）" % (key,))
        index[key] = row
    return index


def batch_items(work_dir: pathlib.Path, batches: int) -> List[Dict[str, object]]:
    """``(batch, i)`` 的有序清单（问题文件是唯一真源）。任一缺项具名失败。"""
    items: List[Dict[str, object]] = []
    for batch in range(1, batches + 1):
        path = work_dir / ("_q_grounding_batch%d.md" % batch)
        if not path.is_file():
            raise GroundingClassifyError("缺少问题文件：%s" % path)
        parsed = parse_question_items(path.read_text(encoding="utf-8"))
        if not parsed:
            raise GroundingClassifyError("问题文件里一条小标题都没解析到：%s" % path)
        for item in parsed:
            items.append({**item, "batch": batch})
    return items


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_results(sample_dir: pathlib.Path, batches: int,
                 items: Sequence[Mapping[str, object]],
                 index: Mapping[tuple, dict]) -> List[Dict[str, object]]:
    """逐批读 ``三分类.json``，校验形状，并把每条挂回样本行。"""
    expected: Dict[int, List[Mapping[str, object]]] = {}
    for item in items:
        expected.setdefault(int(item["batch"]), []).append(item)  # type: ignore[arg-type]

    records: List[Dict[str, object]] = []
    for batch in range(1, batches + 1):
        path = sample_dir / ("batch%d" % batch) / RESULT_NAME
        if not path.is_file():
            raise GroundingClassifyError(
                "第 %d 批没有产物（%s）——三分类还没跑完，别拿半份汇总下结论" % (batch, path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise GroundingClassifyError(
                "第 %d 批不是 JSON 数组（%s）：形状会随角色模板漂，见 tools/glm_consult.py "
                "的 `--plain`" % (batch, path))
        batch_items = expected.get(batch, [])
        if len(payload) != len(batch_items):
            raise GroundingClassifyError(
                "第 %d 批条数不符：产物 %d 条、问题文件 %d 条（%s）"
                % (batch, len(payload), len(batch_items), path))
        seen: set = set()
        for entry in payload:
            if not isinstance(entry, dict) or "i" not in entry or "class" not in entry:
                raise GroundingClassifyError(
                    "第 %d 批有条目形状不对（要 {i, class, why}）：%r" % (batch, entry))
            number = entry["i"]
            if not isinstance(number, int) or not 1 <= number <= len(batch_items):
                raise GroundingClassifyError("第 %d 批的 i 越界：%r" % (batch, number))
            if number in seen:
                raise GroundingClassifyError("第 %d 批的 i 重复：%r" % (batch, number))
            seen.add(number)
            klass = entry["class"]
            if klass not in CLASSES:
                raise GroundingClassifyError(
                    "第 %d 批第 %d 条的 class 越枚举：%r（只许 %s）"
                    % (batch, number, klass, "/".join(CLASSES)))
            source = batch_items[number - 1]
            key = (source["edge_id"], source["value"], source["type"])
            if key not in index:
                raise GroundingClassifyError(
                    "第 %d 批第 %d 条的取值挂不回样本行：%r" % (batch, number, key))
            row = index[key]
            records.append({
                "batch": batch, "i": number,
                "edge_id": source["edge_id"], "value": source["value"],
                "type": source["type"], "kind": row.get("kind"),
                "stratum": row.get("stratum"),
                "class": klass, "why": entry.get("why", ""),
            })
        if seen != set(range(1, len(batch_items) + 1)):
            raise GroundingClassifyError("第 %d 批的 i 不是 1..%d 的排列"
                                         % (batch, len(batch_items)))
    return records


def tally(records: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    """计数 ＋ 腐蚀占比。空输入**不许**真空通过。"""
    if not records:
        raise GroundingClassifyError("一条分类结果都没有——空表不许当成'全良性'")
    counts = {name: 0 for name in CLASSES}
    for record in records:
        counts[str(record["class"])] += 1
    corrupt = sum(counts[name] for name in CORRUPT_CLASSES)
    total = len(records)
    return {"total": total, "counts": counts, "corrupt": corrupt,
            "corrupt_share": corrupt / total}


def decide(summary: Mapping[str, object]) -> Dict[str, str]:
    """裁定给的三支之一。比较走整数交叉相乘，免得落在门上的样本被浮点舍到隔壁。"""
    total = int(summary["total"])                       # type: ignore[arg-type]
    corrupt = int(summary["corrupt"])                   # type: ignore[arg-type]
    if corrupt * 100 <= total * _HIDDEN_PCT:
        return {"branch": "hidden-dominated",
                "reading": "后两类 ≤10% ⇒「修数据」被证伪（主体是蕴含，删边会误伤）"}
    if corrupt * 100 >= total * _CORRUPT_PCT:
        return {"branch": "corrupt-dominated",
                "reading": "后两类 ≥33% ⇒「暂缓重抽」被证伪，应启动换代"}
    return {"branch": "middling",
            "reading": "落在 10%~33% 之间 ⇒ 按各 kind 真错率排队"}


def breakdown(records: Sequence[Mapping[str, object]],
              field: str) -> Dict[str, Dict[str, object]]:
    """按某个字段（``kind``/``stratum``/``type``）拆分计数——中间那支要靠它排队。"""
    buckets: Dict[str, Dict[str, object]] = {}
    for record in records:
        key = str(record.get(field) or "（空）")
        counts = buckets.setdefault(key, {name: 0 for name in CLASSES})
        counts[str(record["class"])] += 1     # type: ignore[index]
    for counts in buckets.values():
        corrupt = sum(int(counts[name]) for name in CORRUPT_CLASSES)
        total = sum(int(counts[name]) for name in CLASSES)
        counts["_total"] = total          # type: ignore[index]
        counts["_corrupt"] = corrupt      # type: ignore[index]
        counts["_corrupt_share"] = corrupt / total if total else 0.0  # type: ignore[index]
    return dict(sorted(buckets.items()))


def summarise(sample_dir: pathlib.Path, work_dir: pathlib.Path,
              batches: int = 12) -> Dict[str, object]:
    """读样本、问题文件与逐批产物 → 计数、占比、落在哪一支、逐维拆分。"""
    sample_path = sample_dir / "sample90.json"
    if not sample_path.is_file():
        raise GroundingClassifyError("缺少样本：%s" % sample_path)
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    index = index_sample(sample)
    items = batch_items(work_dir, batches)
    records = load_results(sample_dir, batches, items, index)

    expected_rows = int(sample.get("sample", len(index)) or len(index))
    if len(records) != expected_rows:
        raise GroundingClassifyError(
            "汇总条数 %d ≠ 样本声明 %d（抽样框与批次产物对不上）"
            % (len(records), expected_rows))

    result_sha = []
    for batch in range(1, batches + 1):
        path = sample_dir / ("batch%d" % batch) / RESULT_NAME
        result_sha.append({"batch": batch, "sha256": _sha256(path),
                           "chars": len(path.read_text(encoding="utf-8"))})

    summary = tally(records)
    verdict = decide(summary)
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sample": {"path": str(sample_path), "sha256": _sha256(sample_path),
                   "universe": sample.get("universe"),
                   "sampled": expected_rows,
                   "by_stratum": sample.get("by_stratum"),
                   "mechanical_pre_read": sample.get("mechanical_pre_read")},
        "batches": {"count": batches, "results": result_sha},
        "total": summary["total"],
        "counts": summary["counts"],
        "corrupt": summary["corrupt"],
        "corrupt_share": summary["corrupt_share"],
        "verdict": verdict,
        "by_kind": breakdown(records, "kind"),
        "by_stratum": breakdown(records, "stratum"),
        "by_type": breakdown(records, "type"),
        "rows": records,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample-dir",
                        default="docs/evidence/20261007-grounding-sample90")
    parser.add_argument("--work-dir", default="work")
    parser.add_argument("--batches", type=int, default=12)
    parser.add_argument("--out", default=None,
                        help="默认写 <sample-dir>/三分类汇总.json")
    args = parser.parse_args(argv)

    sample_dir = pathlib.Path(args.sample_dir)
    work_dir = pathlib.Path(args.work_dir)
    out = pathlib.Path(args.out) if args.out else (sample_dir / "三分类汇总.json")
    try:
        summary = summarise(sample_dir, work_dir, args.batches)
    except GroundingClassifyError as exc:
        print("INCOMPLETE: %s" % exc, file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8", newline="\n")
    counts = summary["counts"]
    print("total=%s corrupt=%s(%.4f) branch=%s"
          % (summary["total"], summary["corrupt"], summary["corrupt_share"],
             summary["verdict"]["branch"]))
    print("counts=%s" % json.dumps(counts, ensure_ascii=False))
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
