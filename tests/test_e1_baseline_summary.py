"""E1 成对重复基线：**读数可复算**、**结论不许被静默改写**、**谓词有鉴别力**。

对象：`tools/knowledge/e1_baseline_summary.py` 与它落盘的
`docs/evidence/20261006-e1-baselines/baselines.json`（计划 v3 · S0 的谓词 ②）。

三条不变量：

1. **可复算**：`--check` 从原始行重算，与入库那份逐字节一致（漂移当场红）。
   这条同时挡住"README 里的话与行对不上"——README 引用的每个数都在
   `baselines.json` 里，而 `baselines.json` 只能由行算出。
2. **结论被钉住**：`|Δ| > 两臂极差的最大值` 才算 `separation_measured`。
   当前实测是 `false`（Δ 0.0078 < 极差 0.0365）。若哪天有人**手改**这一格，
   复算就对不上；若真跑出新读数**越过了极差**，这条会随新证据一起翻。
3. **谓词有鉴别力**：合造一份"两臂明显分开"的产物 ⇒ 必须判 `true`；
   两臂跑在不同索引上 ⇒ 必须拒收。没有这两条，"separation_measured=false"
   可能只是这个字段永远算成 false。
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

EVIDENCE = ROOT / "docs" / "evidence" / "20261006-e1-baselines"
SUMMARY = EVIDENCE / ebs.SUMMARY_NAME
TOOL = ROOT / "tools" / "knowledge" / "e1_baseline_summary.py"

FINGERPRINT = "48df4a53c2c95637dd4150499320b1a87fab201645ec4bacec605eb3a8f44a86"
DIGEST = "937a04e052e675483cbe37dd13a00fbbf84659c2cadedce7e336a55cca7ed4f7"
PANEL = ["deepseek-chat", "glm-5.3"]


def _row(case_id: str, score: float, path: str, *, fingerprint: str = FINGERPRINT,
         query: str = "") -> str:
    return json.dumps({
        "case_id": case_id, "query": query or ("q::" + case_id),
        "score": score, "scores": [score, score],
        "reviewed_by": "llm-panel", "retrieval_path": path,
        "cases_fingerprint": fingerprint, "cases_digest": DIGEST,
        "panel": PANEL,
    }, ensure_ascii=False)


def _write_arm(directory: pathlib.Path, arm: str, repr_: int, *, path: str,
               relevant: int, total: int = 4, fingerprint: str = FINGERPRINT) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = [_row("case_%02d" % index, 5.0 if index < relevant else 1.0, path,
                  fingerprint=fingerprint) for index in range(total)]
    (directory / ("reviews.%s.rep%d.jsonl" % (arm, repr_))).write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _synthetic(directory: pathlib.Path, *, relevant: dict, fingerprint: str = FINGERPRINT):
    for arm, path in ebs.ARMS:
        for rep in ebs.REPS:
            _write_arm(directory, arm, rep, path=path,
                       relevant=relevant[arm], fingerprint=fingerprint)
    return directory


# --- 1. 可复算 ---------------------------------------------------------------

def test_the_shipped_summary_is_exactly_what_the_rows_recompute_to():
    """入库那份必须能从原始行逐字节重算（S0 谓词 ② 的"可复算"半）。"""
    assert SUMMARY.is_file(), "基线账不在库里"
    assert ebs.render(ebs.build_summary(EVIDENCE)) == SUMMARY.read_text(encoding="utf-8")


def test_the_tool_check_mode_returns_zero_on_the_shipped_directory():
    done = subprocess.run([sys.executable, str(TOOL), "--check"],
                          cwd=str(ROOT), capture_output=True)
    assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
    payload = json.loads(done.stdout.decode("utf-8"))
    assert payload["overall"] == "pass"
    assert "Traceback" not in done.stderr.decode("utf-8", "replace")


def test_check_mode_is_not_vacuous_a_tampered_summary_turns_it_red(tmp_path):
    """反面控制：把账改一位数 ⇒ `--check` 必须红（否则这条对拍是恒真式）。"""
    tampered = tmp_path / "tampered"
    tampered.mkdir()
    for file in EVIDENCE.iterdir():
        if file.is_file():
            (tampered / file.name).write_bytes(file.read_bytes())
    bogus = json.loads((tampered / ebs.SUMMARY_NAME).read_text(encoding="utf-8"))
    bogus["arms"]["lexical"]["mean"] = 0.9
    (tampered / ebs.SUMMARY_NAME).write_text(
        json.dumps(bogus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    done = subprocess.run([sys.executable, str(TOOL), "--dir", str(tampered), "--check"],
                          cwd=str(ROOT), capture_output=True)
    assert done.returncode == 1
    assert json.loads(done.stdout.decode("utf-8"))["overall"] == "stale"


# --- 2. 结论被钉住 -----------------------------------------------------------

def test_the_shipped_numbers_say_the_two_arms_are_not_separated():
    """当前证据下的**结论**：Δ 没越过同臂极差 ⇒ 两条检索路分不开。"""
    summary = ebs.build_summary(EVIDENCE)
    assert summary["relevant_threshold"] == 4.0
    assert summary["panel"] == PANEL
    assert set(summary["arms"]) == {"hybrid", "lexical"}
    for arm in summary["arms"].values():
        assert [rep["scored"] for rep in arm["reps"]] == [192, 192]
        assert arm["queries"] == 64
    delta = summary["delta_lexical_minus_hybrid"]
    spread = summary["max_arm_range"]
    assert abs(delta) <= spread, (delta, spread)
    assert summary["separation_measured"] is False
    #: 两臂的散布不是同一个量级 —— "±0.008 当通用噪声底"这条已被读数否掉。
    assert summary["arms"]["lexical"]["range"] > summary["arms"]["hybrid"]["range"]


# --- 3. 谓词有鉴别力 ---------------------------------------------------------

def test_clearly_separated_arms_do_report_a_measured_separation(tmp_path):
    """合造一份"hybrid 全中、lexical 全不中"的产物 ⇒ 必须判量到了差别。"""
    directory = _synthetic(tmp_path / "sep", relevant={"hybrid": 4, "lexical": 0})
    summary = ebs.build_summary(directory)
    assert summary["delta_lexical_minus_hybrid"] == -1.0
    assert summary["max_arm_range"] == 0.0
    assert summary["separation_measured"] is True
    #: 两次重复的行**逐字相同** ⇒ 评委噪声必须是 0（差点把这条也算成"量到了差别"）。
    assert {arm: block["score_delta_mean"]
            for arm, block in summary["judge_noise"].items()} == \
        {"hybrid": 0.0, "lexical": 0.0}


def test_the_judge_noise_block_explains_why_the_arms_are_not_separated():
    """§6(b) 的第一半：候选集跨重复相同 ⇒ 那些散布**只可能**来自判分。

    这条是"分不开"的**机制**证据，不是换个说法重述"分不开"：它把
    **单行的分数位移**与**整臂差**放在同一把尺子上比。
    """
    summary = ebs.build_summary(EVIDENCE)
    noise = summary["judge_noise"]
    assert set(noise) == {"hybrid", "lexical"}
    for arm, block in noise.items():
        assert block["rows"] == 192
        assert block["verdict_flip_rate"] == pytest.approx(
            block["verdict_flips"] / block["rows"], abs=1e-6)
        assert block["verdict_flips"] > 0
        assert 0 < block["score_delta_mean"] < block["score_delta_max"] <= 4.0
        assert block["rows_whose_score_moved"] >= block["verdict_flips"]
    mean_shift = sum(block["score_delta_mean"] for block in noise.values()) / len(noise)
    assert mean_shift > 10 * abs(summary["delta_lexical_minus_hybrid"]), (
        "单行分数的平均位移必须远大于整臂差——否则『分不开』的机制不成立")


def test_arms_on_different_indexes_are_rejected(tmp_path):
    """两臂跑在不同索引上 ⇒ 这不是对照，必须拒收（不是"当成 0 差异"）。"""
    directory = _synthetic(tmp_path / "fp", relevant={"hybrid": 2, "lexical": 2})
    _write_arm(directory, "lexical", 2, path="lexical", relevant=2,
               fingerprint="f" * 64)
    with pytest.raises(ebs.InputError):
        ebs.build_summary(directory)


def test_a_missing_repeat_is_not_measured_rather_than_zero(tmp_path):
    """缺一次重复 ⇒ 退出码 2（缺证据），不许把它读成"差异 0"。"""
    directory = _synthetic(tmp_path / "missing", relevant={"hybrid": 2, "lexical": 2})
    (directory / "reviews.lexical.rep2.jsonl").unlink()
    done = subprocess.run([sys.executable, str(TOOL), "--dir", str(directory)],
                          cwd=str(ROOT), capture_output=True)
    assert done.returncode == 2
    assert json.loads(done.stdout.decode("utf-8"))["overall"] == "not_measured"
