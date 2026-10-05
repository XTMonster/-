"""E1 成对读数的一般化：**任意臂集合 ＋ N 次重复 ＋ 噪声带**。

为什么需要这一层（来自计划 v4 的两处裁决）：

* 循环 2 的处置稿 B.1 把"判读线"从写死的 0.02 改成**由同臂离散推出的噪声带 R**
  （实测同臂极差 hybrid 4/192＝0.0208、lexical 7/192＝0.0365，两条都 ≥ 0.02
  ⇒ 0.02 不是阈值而是掷硬币）。R 只能从"同一配置重复 N 次"里算。
* 计划 v4 的 P9 要跑**三臂**（`lexical` / `hybrid` / `lightrag`），而现役的
  `tools/knowledge/e1_baseline_summary.py` 硬编码了 `ARMS`＝两臂、`REPS`＝(1,2)、
  且只算 `lexical - hybrid` 一个差。要跑三臂就得一般化，**不是**再写一个平行工具
  （循环 3 的接口与契约审查点名的"两个工具各写一份必然漂移"）。

本文件钉四件事：

1. 任意臂 × 任意重复次数都能汇总，且每一格都能从原始行复算；
2. **每一对**都给出 `delta` 与 `separation_measured`（`|Δ| > 噪声带` 才算量到差别）；
3. 噪声带是**参与比较的那些臂**的同臂极差最大值（有鉴别力：能判 true 也能判 false）；
4. 缺一次重复 ⇒ `InputError`（不许当成"少跑一轮"悄悄放过去）。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import e1_baseline_summary as ebs  # noqa: E402

TOOL = ROOT / "tools" / "knowledge" / "e1_baseline_summary.py"

FINGERPRINT = "48df4a53c2c95637dd4150499320b1a87fab201645ec4bacec605eb3a8f44a86"
DIGEST = "937a04e052e675483cbe37dd13a00fbbf84659c2cadedce7e336a55cca7ed4f7"
PANEL = ["deepseek-chat", "glm-5.3"]


def _row(case_id: str, score: float, path: str) -> str:
    return json.dumps({
        "case_id": case_id, "query": "q::" + case_id,
        "score": score, "scores": [score, score],
        "reviewed_by": "llm-panel", "retrieval_path": path,
        "cases_fingerprint": FINGERPRINT, "cases_digest": DIGEST, "panel": PANEL,
    }, ensure_ascii=False)


def _write(directory: pathlib.Path, arm: str, rep: int, relevant: int,
           total: int = 4) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = [_row("case_%02d" % index, 5.0 if index < relevant else 1.0, arm)
             for index in range(total)]
    (directory / ("reviews.%s.rep%d.jsonl" % (arm, rep))).write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    #: **V1 的轮记录**（附件 §0／§1）：执行器在判分之前写身份、之后补终态。
    #: 检查器（`paired_report`）硬依赖它——缺了就只能重跑那一轮。
    (directory / (ebs.ROUND_RECORD % (arm, rep))).write_text(json.dumps({
        "route": arm, "rep": rep, "terminal_state": "valid",
        "seed": 20261005, "rows": total, "rows_digest": "r" * 64,
        "panel": PANEL, "panel_digest": "p" * 64,
        "corpus_manifest_digest": "c" * 64, "hypergraph_manifest_digest": "h" * 64,
        "identity_written_at": "2026-10-05T00:00:00+00:00",
        "state_written_at": "2026-10-05T00:00:00+00:00",
    }, ensure_ascii=False) + "\n", encoding="utf-8")


def _build(directory: pathlib.Path, table: dict, reps) -> pathlib.Path:
    for arm, per_rep in table.items():
        for rep in reps:
            if rep in per_rep:          # 故意缺的那一次就是"少跑一轮"的夹具
                _write(directory, arm, rep, per_rep[rep])
    return directory


def test_three_arms_and_three_reps_are_summarised(tmp_path):
    """任意臂 × 任意重复次数：每臂的 reps/mean/range 都要能算出来。"""
    table = {
        "hybrid": {1: 2, 2: 2, 3: 2},      # 0.5, 0.5, 0.5
        "lexical": {1: 2, 2: 1, 3: 3},     # 0.5, 0.25, 0.75
        "lightrag": {1: 3, 2: 3, 3: 3},    # 0.75 x3
    }
    directory = _build(tmp_path / "ev", table, (1, 2, 3))
    report = ebs.paired_report(directory, arms=("hybrid", "lexical", "lightrag"),
                               reps=(1, 2, 3))
    assert set(report["arms"]) == {"hybrid", "lexical", "lightrag"}
    for arm, block in report["arms"].items():
        assert len(block["reps"]) == 3, arm
        assert block["range"] == pytest.approx(
            max(r["value"] for r in block["reps"])
            - min(r["value"] for r in block["reps"])), arm
    assert len(report["pairs"]) == 3
    assert report["reps"] == [1, 2, 3]


def test_the_noise_band_is_the_largest_single_arm_range(tmp_path):
    table = {
        "hybrid": {1: 2, 2: 2},      # range 0.00
        "lexical": {1: 3, 2: 1},     # 0.75 / 0.25 -> range 0.50
    }
    directory = _build(tmp_path / "ev", table, (1, 2))
    report = ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    assert report["noise_band"] == pytest.approx(0.50)


def test_a_pair_below_the_noise_band_is_inconclusive(tmp_path):
    """Δ 小于噪声带 ⇒ 不许下方向性结论（B.1 的核心）。"""
    table = {
        "hybrid": {1: 2, 2: 2},      # 0.5 / 0.5
        "lexical": {1: 3, 2: 1},     # 0.75 / 0.25  -> delta 0.0, band 0.5
    }
    directory = _build(tmp_path / "ev", table, (1, 2))
    report = ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    pair = report["pairs"][0]
    assert pair["delta"] == pytest.approx(0.0)
    assert pair["separation_measured"] is False
    assert pair["verdict"] == "inconclusive"


def test_a_pair_above_the_noise_band_separates(tmp_path):
    """反面控制：让这条判据有鉴别力——明显分开的两臂必须判 true。"""
    table = {
        "hybrid": {1: 4, 2: 4},      # 1.00 / 1.00
        "lexical": {1: 2, 2: 2},     # 0.50 / 0.50 -> delta 0.5, band 0.0
    }
    directory = _build(tmp_path / "ev", table, (1, 2))
    report = ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    pair = report["pairs"][0]
    assert pair["delta"] == pytest.approx(-0.5)
    assert pair["separation_measured"] is True
    assert pair["verdict"] == "separated"


def test_every_pair_is_reported_once(tmp_path):
    table = {
        "hybrid": {1: 2, 2: 2},
        "lexical": {1: 2, 2: 2},
        "lightrag": {1: 2, 2: 2},
    }
    directory = _build(tmp_path / "ev", table, (1, 2))
    report = ebs.paired_report(directory, arms=("hybrid", "lexical", "lightrag"),
                               reps=(1, 2))
    names = sorted((pair["a"], pair["b"]) for pair in report["pairs"])
    assert names == [("hybrid", "lexical"), ("hybrid", "lightrag"),
                     ("lexical", "lightrag")]


def test_a_missing_rep_is_an_input_error(tmp_path):
    """少跑一轮不许被当成"就这些读数"悄悄放过去。"""
    table = {"hybrid": {1: 2, 2: 2}, "lexical": {1: 2}}
    directory = _build(tmp_path / "ev", table, (1, 2))
    with pytest.raises(ebs.InputError):
        ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))


def test_arms_from_different_indexes_are_rejected(tmp_path):
    """两臂跑在不同索引上 ⇒ 这不是对照，必须拒收。"""
    directory = tmp_path / "ev"
    _write(directory, "hybrid", 1, 2)
    _write(directory, "hybrid", 2, 2)
    for rep in (1, 2):
        path = directory / ("reviews.lexical.rep%d.jsonl" % rep)
        lines = [_row("case_%02d" % index, 5.0, "lexical").replace(
            FINGERPRINT, "0" * 64) for index in range(4)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ebs.InputError):
        ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))


def test_cli_general_mode_writes_a_paired_report(tmp_path):
    """P9 的三臂消融要能从这里出报告：CLI 必须能收 `--arms/--reps`。"""
    table = {"hybrid": {1: 2, 2: 2}, "lexical": {1: 2, 2: 2}}
    directory = _build(tmp_path / "ev", table, (1, 2))
    out = tmp_path / "paired.json"
    done = subprocess.run(
        [sys.executable, str(TOOL), "--dir", str(directory),
         "--arms", "hybrid,lexical", "--reps", "1,2", "--out", str(out)],
        cwd=str(ROOT), capture_output=True)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["arms_order"] == ["hybrid", "lexical"]
    assert payload["noise_band"] == pytest.approx(0.0)
    assert [pair["verdict"] for pair in payload["pairs"]] == ["inconclusive"]


# --- V1／V2（附件 PLAN_HYPERGRAPH_v4_ANNEX.md §0／§1；有约束力）----------------------


def test_the_batch_identity_must_match_across_rounds(tmp_path):
    """**V1 的判据逐字**：同批两臂的轮记录做身份字段 diff，**不一致字段数＝0**。

    为什么值得一条判据：`reviews.*.rep*.jsonl` 只记"判了什么"，不记"这一轮是在**什么
    身份**下跑的"。两臂若不是同一个 seed／行清单／评委配置／语料构建，ΔE1 就不是对照
    ——而那种错**在看分数时完全看不出来**。
    """
    table = {"hybrid": {1: 2, 2: 2}, "lexical": {1: 2, 2: 2}}
    directory = _build(tmp_path / "ev", table, (1, 2))
    report = ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    assert report["identity_mismatched_fields"] == []
    assert report["round_identity"]["seed"] == 20261005
    assert set(report["round_records"]) == {"hybrid.rep1", "hybrid.rep2",
                                            "lexical.rep1", "lexical.rep2"}

    #: 把 lexical.rep2 的**行清单摘要**改掉 ⇒ 这一批不是成对的了。
    record = directory / (ebs.ROUND_RECORD % ("lexical", 2))
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["rows_digest"] = "x" * 64
    record.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ebs.InputError) as excinfo:
        ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    assert "rows_digest" in str(excinfo.value), str(excinfo.value)


def test_a_missing_round_record_is_refused_by_name(tmp_path):
    """V1：执行器是唯一写入方、检查器只读——**没有轮记录就只能重跑那一轮**。"""
    table = {"hybrid": {1: 2, 2: 2}, "lexical": {1: 2, 2: 2}}
    directory = _build(tmp_path / "ev", table, (1, 2))
    (directory / (ebs.ROUND_RECORD % ("lexical", 2))).unlink()
    with pytest.raises(ebs.InputError) as excinfo:
        ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    assert "round.lexical.2.json" in str(excinfo.value), str(excinfo.value)


def test_the_terminal_state_enum_is_closed_and_both_invalid_codes_count(tmp_path):
    """**V2**：终态取值来自封闭枚举（集外取值数＝0），两个作废码**分开**计数。

    作废只写进轮记录，**没有**第二条入账通道；有作废轮的一批不允许被当成读数。
    """
    table = {"hybrid": {1: 2, 2: 2}, "lexical": {1: 2, 2: 2}}
    directory = _build(tmp_path / "ev", table, (1, 2))
    record = directory / (ebs.ROUND_RECORD % ("hybrid", 2))
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["terminal_state"] = "pending"            # 集外取值
    record.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ebs.InputError) as excinfo:
        ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    assert "枚举" in str(excinfo.value), str(excinfo.value)

    #: 两个作废码分开记：一批里同时出现两码时，两条计数各 1。
    table_states = {("hybrid", 2): "invalid_parse_fault",
                    ("lexical", 2): "invalid_empty_intersection"}
    for (arm, rep), state in table_states.items():
        record = directory / (ebs.ROUND_RECORD % (arm, rep))
        payload = json.loads(record.read_text(encoding="utf-8"))
        payload["terminal_state"] = state
        record.write_text(json.dumps(payload, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    with pytest.raises(ebs.InputError) as excinfo:
        ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    assert "作废轮" in str(excinfo.value), str(excinfo.value)

    #: 终态全 valid 时，报告里两条作废计数都是 0。
    for (arm, rep) in table_states:
        record = directory / (ebs.ROUND_RECORD % (arm, rep))
        payload = json.loads(record.read_text(encoding="utf-8"))
        payload["terminal_state"] = "valid"
        record.write_text(json.dumps(payload, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    report = ebs.paired_report(directory, arms=("hybrid", "lexical"), reps=(1, 2))
    assert report["invalid_parse_fault"] == 0
    assert report["invalid_empty_intersection"] == 0
    assert report["terminal_states"] == {"valid": 4}
