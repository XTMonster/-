"""验收链必须**真的量到**它声称量到的东西。

两条都是 2026-10-02 实测出来的真实缺陷，形状不同、成因同一个：缺证据被当成通过。

1. **硬门没有生产者跑。** 链只跑 `tools/holdout_score.py`，却把它的报告写在
   `knowledge_quality.json` 名下（AGENTS.md 把这个名字给了 `quality.py`）。
   实测后果：每个 `docs/evidence/<run-id>/knowledge_quality.json` 的 metric id
   集合是 `['Q1','Q2','Q3','Q4','Q6a','Q6b','Q7']`——**没有 Q0、没有 E3**，
   而"E3 经验越权率 = 0"是 §2.3b/§4.1b 的硬门。判据从这里开始：

   * 两个生产者都必须被链调用，且**各写各的文件名**（一个名字两个 schema
     就是"同一事实多个真源"）；
   * RK-13 的归属必须走 `tools/knowledge/hard_gates.py`（按 id 判、缺 id 也算失败），
     **不许**拿 `quality.py` 的聚合退出码判——它因为 Q5/E1 在 CI 上恒为 2。

2. **探针结果解析失败只 WARN。** `run_tests.ps1` 里 `$payloadOk = $false` 时
   只打印 WARN 并落一份 dump，然后继续；于是链最后照旧打印
   `All checks passed.`，而挂在那条探针上的 RK 全部静默变成 `not_measured`。
   现在必须走 `INCOMPLETE:` ＋ 非零退出码。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def chain_text() -> str:
    return (ROOT / "tools" / "run_tests.ps1").read_text(encoding="utf-8")


def live_lines(text: str):
    """``[(行号, 行)]``，只取**活行**（命令行不会被注释吃掉）。"""
    return [(number, line) for number, line in enumerate(text.splitlines(), 1)
            if not line.strip().startswith("#")]


def escalates_parse_failures(text: str) -> bool:
    """链是否把"探针结果解析失败"升级成 INCOMPLETE ＋ 非零退出码。

    判据：先有收集（``probeParseFailures +=``），再有判定（``….Count``）且它在
    后面几行里以 ``exit 1`` 收尾。
    """
    lines = text.splitlines()
    collected = [number for number, line in enumerate(lines)
                 if "probeParseFailures +=" in line]
    judged = [number for number, line in enumerate(lines)
              if "probeParseFailures.Count" in line]
    for cursor in judged:
        window = "\n".join(lines[cursor:cursor + 8])
        # 收集在判定**之前**才算数：只判定、不收集的写法是死的。
        if collected and min(collected) < cursor and "exit 1" in window:
            return True
    return False


# --------------------------------------------------------------------------- #
# 一、两个生产者 ＋ 各自的文件名
# --------------------------------------------------------------------------- #
def test_the_chain_runs_both_knowledge_producers_on_live_lines():
    lines = live_lines(chain_text())
    for tool in ("tools/holdout_score.py", "tools/knowledge/quality.py"):
        assert any(tool in line for _, line in lines), (
            f"{tool} 没有被链调用（活行）——它的报告就没有生产者")


def test_the_two_producers_do_not_write_the_same_file_name():
    """一个文件名只能有一个 schema：holdout_score 与 quality 各写各的。"""
    lines = live_lines(chain_text())
    names = {}
    for tool in ("holdout_score.py", "knowledge/quality.py"):
        written = [line for _, line in lines if tool in line and "--out" in line]
        if tool.startswith("holdout_score"):
            written += [line for _, line in lines if tool in line and "--json" in line]
        assert written, f"{tool} 这一行看不出写哪个文件"
        out_names = set(re.findall(r"'(holdout_quality|knowledge_quality)\.json'",
                                   " ".join(written)))
        assert out_names, f"{tool} 的输出文件名没有用 <name>.json 的写法"
        names[tool] = out_names
    assert names["holdout_score.py"].isdisjoint(names["knowledge/quality.py"]), names


def test_the_chain_attributes_rk13_by_hard_gate_ids_not_by_an_exit_code():
    text = chain_text()
    call = [number for number, line in live_lines(text)
            if "tools/knowledge/hard_gates.py" in line]
    assert call, "RK-13 的硬门判定没有接进链里（活行）"
    # 调用之后必须看它的退出码（不是 quality.py 的聚合退出码）。
    after = "\n".join(text.splitlines()[call[0]:call[0] + 8])
    assert "$LASTEXITCODE" in after


# --------------------------------------------------------------------------- #
# 二、探针结果解析失败 ⇒ INCOMPLETE（不是 WARN）
# --------------------------------------------------------------------------- #
def test_the_chain_escalates_a_probe_parse_failure():
    text = chain_text()
    assert "probeParseFailures +=" in text, "解析失败没有被收集起来"
    assert escalates_parse_failures(text), (
        "探针结果解析不到时链仍然会报 'All checks passed.' —— "
        "挂在那条探针上的 RK 静默变成 not_measured（§4.1b 硬规则 1）")
    assert "INCOMPLETE" in text


def test_the_escalation_checker_fires_on_a_warn_only_chain():
    """自证：只 WARN 不升级的链必须判 False，有升级的（含无出口的那种）才 True。"""
    warn_only = """
    if ($payloadOk) { $probePassed += $parsed.passed }
    else { Write-Host '  WARN: could not parse' -ForegroundColor Yellow }
    Write-Host 'All checks passed.'
    """
    assert escalates_parse_failures(warn_only) is False

    no_exit = """
    $probeParseFailures = @()
    if (-not $payloadOk) { $probeParseFailures += $check.Label }
    if ($probeParseFailures.Count -gt 0) { Write-Host 'INCOMPLETE' }
    """
    assert escalates_parse_failures(no_exit) is False

    proper = """
    $probeParseFailures = @()
    if (-not $payloadOk) { $probeParseFailures += $check.Label }
    if ($probeParseFailures.Count -gt 0) {
        Write-Host 'INCOMPLETE: evidence did not come back'
        exit 1
    }
    """
    assert escalates_parse_failures(proper) is True
