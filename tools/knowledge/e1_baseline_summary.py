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

#: 一般化入口（计划 v4 · P9 要跑三臂）用的默认臂名。
#: 与 `ARMS` 同源：臂名就是 `reviews.<arm>.rep<N>.jsonl` 里的那个词。
DEFAULT_ARM_NAMES = tuple(arm for arm, _adapter in ARMS)

#: **V1 的轮记录文件**（附件 `PLAN_HYPERGRAPH_v4_ANNEX.md` §0／§1 的 V1，有约束力）：
#: 每跑一轮 E1 落一份 `round.<route>.<n>.json`，**执行器是唯一写入方、检查器只读**。
ROUND_RECORD = "round.%s.%d.json"
#: 轮记录里属于**身份**的字段（同批各轮必须逐字相同 ⇒ 不一致字段数＝0）。
ROUND_IDENTITY_FIELDS = ("seed", "rows", "rows_digest", "panel", "panel_digest",
                         "corpus_manifest_digest", "hypergraph_manifest_digest")
#: 轮记录**终态**的封闭枚举（V2：集外取值数＝0；两个作废码分开计数）。
ROUND_STATES = ("valid", "invalid_parse_fault", "invalid_empty_intersection")


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


def scores(path: pathlib.Path) -> Dict[tuple, float]:
    """逐 **（查询, 案例）行**的两个评委均分——用来量**只重判**那一下的散布。"""
    return {key: float(row["score"]) for key, row in (
        ((str(row["query"]), str(row["case_id"])), row) for row in read_rows(path))}


def build_summary(directory: pathlib.Path) -> dict:
    arms: Dict[str, dict] = {}
    judge_noise: Dict[str, dict] = {}
    for arm, _adapter in ARMS:
        reps = [summarise_rep(directory / ("reviews.%s.rep%d.jsonl" % (arm, rep)))
                for rep in REPS]
        values = [rep["value"] for rep in reps]
        votes = [verdicts(directory / rep["file"]) for rep in reps]
        graded = [scores(directory / rep["file"]) for rep in reps]
        keysets = [set(vote) for vote in votes]
        if any(keys != keysets[0] for keys in keysets[1:]):
            raise InputError("%s 的两次重复判的不是同一批（查询, 案例）行" % arm)
        flips = sorted(case_id for (query, case_id) in keysets[0]
                       if votes[0][(query, case_id)] != votes[1][(query, case_id)])
        #: **两次重复喂给评委的是同一份候选集**（检索是确定性的；上面那条键相等
        #: 就是这条的机器证据）⇒ 下面这几格量的**只能是评委噪声**，不是检索噪声。
        deltas = [abs(graded[0][key] - graded[1][key]) for key in keysets[0]]
        judge_noise[arm] = {
            "rows": len(keysets[0]),
            "score_delta_mean": round(statistics.fmean(deltas), 6),
            "score_delta_max": round(max(deltas), 6),
            "rows_whose_score_moved": sum(1 for value in deltas if value > 0),
            "verdict_flips": len(flips),
            "verdict_flip_rate": round(len(flips) / len(keysets[0]), 6),
        }
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
        #: §6(b) 的**第一半**（固定候选集、只重跑评委）：两次重复的候选集逐行相同
        #: （检索确定性 ⇒ 键集相等已经在上面断言过），所以这里的散布＝**评委噪声**。
        #: 第二半（固定评委、只重跑检索）本批没有做，如实挂着。
        "judge_noise": judge_noise,
        "judge_noise_note": ("候选集跨重复逐行相同（检索确定性）；这些散布是**只重判**"
                             "那一下的噪声。E1 的整臂差 Δ 只有 "
                             "%.4f，而单行分数的平均位移是 %.4f。"
                             % (abs(delta), statistics.fmean(
                                 [item["score_delta_mean"]
                                  for item in judge_noise.values()]))),
    }


def render(summary: dict) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def read_round_record(directory: pathlib.Path, arm: str, rep: int) -> dict:
    """读一轮的**轮记录**（V1：执行器写、检查器只读）。缺文件／终态集外 ⇒ 拒读。

    为什么检查器要硬依赖它（V1 的理由）：`reviews.*.rep*.jsonl` 只记"判了什么"，
    不记"这一轮是在**什么身份**下跑的"——同一批两臂如果不是同一个 seed／行清单／
    评委配置／语料构建，那 ΔE1 就不是对照。把身份写在**跑之前**（执行器唯一写入）
    且由检查器 diff，才挡得住"事后配平"。
    """
    path = pathlib.Path(directory) / (ROUND_RECORD % (arm, int(rep)))
    if not path.is_file():
        raise InputError("缺轮记录 %s（V1：每轮先写它再判分；没有就只能重跑那一轮）"
                         % path.name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError("%s 读不出：%s" % (path.name, exc)) from exc
    state = str(payload.get("terminal_state") or "")
    if state not in ROUND_STATES:
        raise InputError("%s 的终态不在封闭枚举里：%r（V2：集外取值数必须为 0）"
                         % (path.name, state))
    return payload


def paired_report(directory: pathlib.Path, *, arms: Sequence[str] = DEFAULT_ARM_NAMES,
                  reps: Sequence[int] = REPS) -> dict:
    """**任意臂集合 × 任意重复次数**的成对读数（计划 v4 的 B.1／R13）。

    与 :func:`build_summary` 的关系：那个是**两臂两重复**的专用版（它的字段名与
    入库产物 `baselines.json` 绑死，动它就等于改写已发货的证据）；本函数是同一条
    读数纪律的一般形式，给 P9 的三臂消融用。**不重复实现**判分、复算与唯一性检查——
    每一臂的读数仍走 :func:`summarise_rep`，与专用版同一份代码。

    三条不变量（都有反面用例）：

    1. **噪声带 R ＝ 参与比较的那些臂的同臂极差的最大值**（`|Δ| > R` 才算量到差别）。
       这条来自实测：同臂极差 hybrid 4/192＝0.0208、lexical 7/192＝0.0365，
       所以循环 2 的处置稿把写死的 0.02 换成"从数据推出来的 R"。
    2. **同一份索引**：所有臂的 `cases_fingerprint` 与 `cases_digest` 必须唯一，
       否则这不是对照（与专用版同一条检查）。
    3. **少一次重复 = 输入错误**，不许当成"就这些读数"放过去。

    返回里 `pairs` 覆盖**所有**两两组合，每对带 `delta` / `separation_measured` /
    `verdict`。注意 `delta` 的方向是 `b − a`（按 `arms` 的给出顺序），
    `verdict` 只有两种取值：`separated` 或 `inconclusive`——后者**不是**"相等"。
    """
    arm_names = tuple(arms)
    rep_ids = tuple(int(rep) for rep in reps)
    if len(arm_names) < 2:
        raise InputError("至少要两条臂才能做对照，收到 %d" % len(arm_names))
    if not rep_ids:
        raise InputError("至少要一次重复")

    blocks: Dict[str, dict] = {}
    for arm in arm_names:
        entries = []
        for rep in rep_ids:
            path = directory / ("reviews.%s.rep%d.jsonl" % (arm, rep))
            if not path.is_file():
                raise InputError("找不到 %s" % path.name)
            entries.append(summarise_rep(path))
        rows = read_rows(directory / ("reviews.%s.rep%d.jsonl" % (arm, rep_ids[0])))
        counts = [entry["scored"] for entry in entries]
        if len(set(counts)) != 1:
            #: 同一臂的两次重复判的行数不同 ⇒ 候选集变了，R 就不是"只重判"的散布。
            raise InputError("%s 的几次重复行数不同：%s" % (arm, sorted(set(counts))))
        values = [entry["value"] for entry in entries]
        blocks[arm] = {
            "reps": entries,
            "mean": round(statistics.fmean(values), 6),
            "range": round(max(values) - min(values), 6),
            "rows": counts[0],
            "queries": len({str(row.get("query") or "") for row in rows}),
            "cases": len({str(row.get("case_id") or "") for row in rows}),
        }

    fingerprints = {entry["cases_fingerprint"] for block in blocks.values()
                    for entry in block["reps"]}
    digests = {entry["cases_digest"] for block in blocks.values()
               for entry in block["reps"]}
    if len(fingerprints) != 1 or len(digests) != 1:
        raise InputError("各臂的索引不是同一份：%s / %s" % (fingerprints, digests))
    panels = {tuple(entry["panel"]) for block in blocks.values()
              for entry in block["reps"]}
    if len(panels) != 1:
        raise InputError("各臂的面板不是同一个：%s" % panels)

    #: **V1 的轮记录**：身份字段由检查器 diff（不一致字段数必须为 0），终态按 V2 读。
    records = {(arm, rep): read_round_record(directory, arm, rep)
               for arm in arm_names for rep in rep_ids}
    identity_diff: Dict[str, List[str]] = {}
    for field in ROUND_IDENTITY_FIELDS:
        seen = {json.dumps(record.get(field), ensure_ascii=False, sort_keys=True)
                for record in records.values()}
        if len(seen) != 1:
            identity_diff[field] = sorted(seen)
    if identity_diff:
        raise InputError("同批各轮的**身份字段**不一致（V1：不一致字段数＝0）：%s"
                         % sorted(identity_diff))
    states = [str(record["terminal_state"]) for record in records.values()]
    invalid = {(arm, rep): record["terminal_state"]
               for (arm, rep), record in records.items()
               if record["terminal_state"] != "valid"}
    if invalid:
        raise InputError("有**作废轮**（V2：作废只记在轮记录里、不计入统计）：%s" % invalid)

    noise_band = round(max(block["range"] for block in blocks.values()), 6)
    pairs: List[dict] = []
    for index, first in enumerate(arm_names):
        for second in arm_names[index + 1:]:
            delta = round(blocks[second]["mean"] - blocks[first]["mean"], 6)
            measured = abs(delta) > noise_band
            pairs.append({
                "a": first, "b": second, "delta": delta,
                "noise_band": noise_band,
                "separation_measured": measured,
                "verdict": "separated" if measured else "inconclusive",
            })

    return {
        "generated_by": "tools/knowledge/e1_baseline_summary.py::paired_report",
        "relevant_threshold": RELEVANT,
        "panel": sorted(next(iter(panels))),
        "cases_fingerprint": next(iter(fingerprints)),
        "cases_digest": next(iter(digests)),
        "arms_order": list(arm_names),
        "reps": list(rep_ids),
        #: V1／V2 的轮记录账：身份字段（同批一致）、终态计数、以及"不一致字段数"。
        "round_records": {("%s.rep%d" % (arm, rep)): (ROUND_RECORD % (arm, rep))
                          for arm in arm_names for rep in rep_ids},
        "round_identity": {field: records[(arm_names[0], rep_ids[0])].get(field)
                           for field in ROUND_IDENTITY_FIELDS},
        "identity_mismatched_fields": [],
        "terminal_states": {state: states.count(state) for state in ROUND_STATES
                            if states.count(state)},
        "invalid_parse_fault": states.count("invalid_parse_fault"),
        "invalid_empty_intersection": states.count("invalid_empty_intersection"),
        "arms": blocks,
        "noise_band": noise_band,
        "pairs": pairs,
        #: 读数纪律：噪声带以下是 **inconclusive**，不是"两臂相等"。
        "inconclusive_pairs": [pair for pair in pairs
                               if not pair["separation_measured"]],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    force_utf8_streams()
    parser = argparse.ArgumentParser(prog="knowledge-e1-baseline-summary")
    parser.add_argument("--dir", default=str(DEFAULT_DIR),
                        help="证据目录（默认 %s）" % DEFAULT_DIR)
    parser.add_argument("--out", default="",
                        help="写到哪（默认 <dir>/%s）" % SUMMARY_NAME)
    parser.add_argument("--check", action="store_true",
                        help="只对拍，不写盘；漂移 ⇒ 退出码 1")
    parser.add_argument("--arms", default="",
                        help="逗号分隔的臂名（给了一般化成对报告模式；"
                             "不给＝跑入库那份两臂两重复的专用版）")
    parser.add_argument("--reps", default="",
                        help="逗号分隔的重复号，例如 1,2,3（配合 --arms）")
    args = parser.parse_args(argv)

    directory = pathlib.Path(args.dir)
    target = pathlib.Path(args.out) if args.out else directory / SUMMARY_NAME
    general = bool(args.arms or args.reps)
    try:
        if general:
            arm_names = tuple(name.strip() for name in (args.arms or "").split(",")
                              if name.strip()) or DEFAULT_ARM_NAMES
            rep_ids = tuple(int(item) for item in (args.reps or "").split(",")
                            if item.strip()) or REPS
            summary = paired_report(directory, arms=arm_names, reps=rep_ids)
        else:
            summary = build_summary(directory)
    except InputError as exc:
        print(json.dumps({"overall": "not_measured", "error": str(exc)},
                         ensure_ascii=False))
        return 2
    text = render(summary)

    if general:
        #: 一般化模式是一份**新**报告，不写进入库那份 `baselines.json` 的位置；
        #: 没给 `--out` 就写到 `<dir>/paired_report.json`，免得覆盖专用版产物。
        if not args.out:
            target = directory / "paired_report.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(json.dumps({"overall": "pass", "path": str(target),
                          "arms_order": summary["arms_order"],
                          "reps": summary["reps"],
                          "noise_band": summary["noise_band"],
                          "pairs": [{k: pair[k] for k in
                                     ("a", "b", "delta", "verdict")}
                                    for pair in summary["pairs"]]},
                         ensure_ascii=False))
        return 0

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
