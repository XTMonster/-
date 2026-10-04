"""把 E1 的**成对重复**基线从原始行重算成一份可对拍的账（S0 的第二半）。

计划 `docs/knowledge/PLAN_HYPERGRAPH_v3.md` 的 S0 谓词 ② 要求：基线命令 ＋ 种子
写进证据目录，**两条命令各跑一次并入库**。`docs/evidence/20261006-e1-baselines/`
里是那条命令的产物（同一份发货索引、同一批 long21 查询、同一个跨族面板，
两臂各跑两次）。本工具只做一件事：**从 `reviews.*.rep*.jsonl` 的原始行**
重算读数，落成 `baselines.json`，并提供 `--check` 让漂移当场红。

为什么要有它（而不是把读数抄进 README 就完事）：

* E1 的分子是**两个 LLM 评委的 1–5 分取均值 ≥ 4.0**（`tools/knowledge/e1_panel.py`）。
  同一份候选集重复判分**本身就有散布**，所以「哪条检索路更好」不能由一次读数决定；
  README 里的文字会过期，`baselines.json` 可以被 `--check` 钉住。
* 读数纪律（`docs/knowledge/ACCEPTANCE_STATUS.md` §九十七／§九十八）：
  任何 ΔE1 都要与**同臂重复的极差**放在一起看。本工具把这条写成字段
  `separation_measured`——`|Δ| > 两臂极差的最大值` 才算量到了差别。

退出码：`0` ＝ 算出/对上；`1` ＝ `--check` 发现漂移；`2` ＝ 输入缺失或行不自洽。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from typing import Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.utils.console import force_utf8_streams  # noqa: E402

#: 判「相关」的下限：与 `tools/knowledge/e1_panel.py::RELEVANT` 同源。
#: 这里**只能**是 4.0——改它就是把 E1 的门限挪走，属于红线。
RELEVANT = 4.0

DEFAULT_DIR = ROOT / "docs" / "evidence" / "20261006-e1-baselines"
SUMMARY_NAME = "baselines.json"

#: 证据里两臂的目录名（`--adapter none` ＝ 产品现行的 hybrid，`--adapter lexical`
#: ＝ ADR-0014 ② 那个候选）。臂名进文件名，不许改名——`--check` 按名字取文件。
ARMS = (("hybrid", "none"), ("lexical", "lexical"))
REPS = (1, 2)


class InputError(RuntimeError):
    """输入缺失或行不自洽（退出码 2 的那一类）。"""


def read_rows(path: pathlib.Path) -> List[dict]:
    if not path.is_file():
        raise InputError("找不到 %s" % path)
    rows: List[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as exc:  # noqa: BLE001
                raise InputError("%s 有非 JSON 行：%s" % (path.name, exc)) from exc
    if not rows:
        raise InputError("%s 是空的" % path.name)
    return rows


def summarise_rep(path: pathlib.Path) -> dict:
    """一份 `reviews.<arm>.repN.jsonl` 的读数（不含逐行明细，明细只用于对拍）。"""
    rows = read_rows(path)
    paths = {str(row.get("retrieval_path") or "") for row in rows}
    if len(paths) != 1:
        # 一份证据里两条路的读数不许混账（`tests/test_e1_panel.py` 的同一不变量）。
        raise InputError("%s 里的 retrieval_path 不唯一：%s" % (path.name, sorted(paths)))
    relevant = sum(1 for row in rows if float(row["score"]) >= RELEVANT)
    return {
        "file": path.name,
        "retrieval_path": paths.pop(),
        "cases_fingerprint": rows[0].get("cases_fingerprint"),
        "cases_digest": rows[0].get("cases_digest"),
        "panel": list(rows[0].get("panel") or ()),
        "scored": len(rows),
        "relevant": relevant,
        "value": round(relevant / len(rows), 6),
    }


def verdicts(path: pathlib.Path) -> Dict[tuple, bool]:
    """逐 **（查询, 案例）行**是否判「相关」——用于找跨重复翻转的行（诊断量）。

    键必须是这一对，不能只用 `case_id`：同一个案例会被多张镜头召回，
    「哪张镜头下从相关变成了不相关」才是能定位的那件事。
    """
    out: Dict[tuple, bool] = {}
    for row in read_rows(path):
        try:
            out[(str(row["query"]), str(row["case_id"]))] = float(row["score"]) >= RELEVANT
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError("%s 的行缺字段或分数不是数：%s" % (path.name, exc)) from exc
    return out


def build_summary(directory: pathlib.Path) -> dict:
    arms: Dict[str, dict] = {}
    for arm, _adapter in ARMS:
        reps = [summarise_rep(directory / ("reviews.%s.rep%d.jsonl" % (arm, rep)))
                for rep in REPS]
        values = [rep["value"] for rep in reps]
        votes = [verdicts(directory / rep["file"]) for rep in reps]
        keysets = [set(vote) for vote in votes]
        if any(keys != keysets[0] for keys in keysets[1:]):
            raise InputError("%s 的两次重复判的不是同一批（查询, 案例）行" % arm)
        flips = sorted(case_id for (query, case_id) in keysets[0]
                       if votes[0][(query, case_id)] != votes[1][(query, case_id)])
        arms[arm] = {
            "reps": reps,
            "mean": round(statistics.fmean(values), 6),
            "range": round(max(values) - min(values), 6),
            "queries": len({query for query, _case in keysets[0]}),
            "cases": len({case_id for _query, case_id in keysets[0]}),
            "rows": len(keysets[0]),
            "verdict_flips": flips,
        }

    fingerprints = {rep["cases_fingerprint"] for arm in arms.values()
                    for rep in arm["reps"]}
    digests = {rep["cases_digest"] for arm in arms.values() for rep in arm["reps"]}
    if len(fingerprints) != 1 or len(digests) != 1:
        # 两臂必须跑在**同一份**索引上，否则这条"对照"根本不是对照。
        raise InputError("两臂的索引不是同一份：%s / %s" % (fingerprints, digests))
    panels = {tuple(rep["panel"]) for arm in arms.values() for rep in arm["reps"]}
    if len(panels) != 1:
        raise InputError("两臂的面板不是同一个：%s" % panels)

    delta = round(arms["lexical"]["mean"] - arms["hybrid"]["mean"], 6)
    spread = round(max(arm["range"] for arm in arms.values()), 6)
    return {
        "generated_by": "tools/knowledge/e1_baseline_summary.py",
        "relevant_threshold": RELEVANT,
        "panel": sorted(next(iter(panels))),
        "cases_fingerprint": next(iter(fingerprints)),
        "cases_digest": next(iter(digests)),
        "arms": arms,
        "delta_lexical_minus_hybrid": delta,
        "max_arm_range": spread,
        #: **读数纪律**（§九十七）：Δ 只有大于同臂重复的极差才算量到差别。
        #: 这一格是**结论**，不是门限——E1 的 0.70 线一个字没动。
        "separation_measured": abs(delta) > spread,
    }


def render(summary: dict) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-e1-baseline-summary")
    parser.add_argument("--dir", default=str(DEFAULT_DIR),
                        help="证据目录（默认 %s）" % DEFAULT_DIR)
    parser.add_argument("--out", default="",
                        help="写到哪（默认 <dir>/%s）" % SUMMARY_NAME)
    parser.add_argument("--check", action="store_true",
                        help="只对拍，不写盘；漂移 ⇒ 退出码 1")
    args = parser.parse_args(argv)

    directory = pathlib.Path(args.dir)
    target = pathlib.Path(args.out) if args.out else directory / SUMMARY_NAME
    try:
        summary = build_summary(directory)
    except InputError as exc:
        print(json.dumps({"overall": "not_measured", "error": str(exc)},
                         ensure_ascii=False))
        return 2
    text = render(summary)

    if args.check:
        if not target.is_file():
            print(json.dumps({"overall": "not_measured", "missing": str(target)},
                             ensure_ascii=False))
            return 2
        shipped = target.read_text(encoding="utf-8")
        if shipped != text:
            print(json.dumps({"overall": "stale", "path": str(target)},
                             ensure_ascii=False))
            return 1
        print(json.dumps({"overall": "pass", "path": str(target),
                          "delta": summary["delta_lexical_minus_hybrid"],
                          "max_arm_range": summary["max_arm_range"],
                          "separation_measured": summary["separation_measured"]},
                         ensure_ascii=False))
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(json.dumps({"overall": "pass", "path": str(target),
                      "arms": {name: {"mean": arm["mean"], "range": arm["range"]}
                               for name, arm in summary["arms"].items()},
                      "delta": summary["delta_lexical_minus_hybrid"],
                      "max_arm_range": summary["max_arm_range"],
                      "separation_measured": summary["separation_measured"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
