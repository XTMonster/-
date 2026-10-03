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


def live_quality_line(text: str) -> str:
    """链上 `quality.py` 的那条**活行**（找不到就当场红）。"""
    calls = [line for _, line in live_lines(text) if "tools/knowledge/quality.py" in line]
    assert calls, "链上没有调用 tools/knowledge/quality.py（活行）"
    assert len(calls) == 1, "quality.py 被调了不止一次：输入分散在多处，判据会漂"
    return calls[0]


QUALITY_INPUT_FLAGS = ("--shots", "--audit-log", "--e1-reviews")


def missing_quality_inputs(line: str):
    """这条命令行缺了哪个输入开关（缺证据 = Q5/E1 退回 `not_measured`）。"""
    return [flag for flag in QUALITY_INPUT_FLAGS if flag not in line]


def test_the_quality_report_is_fed_the_real_run_and_the_audit_channel():
    """Q5 / E1 归位成门之后，链上那一条命令必须真的把输入递进去。

    2026-10-03 的门归位把 `Q5` 与 `E1` 从 `SOFT_IDS` 移进 `HARD_IDS`：它们从
    "这次量不到"变成"缺证据即 RK-13 未通过"。这条断言钉住**输入侧**——把
    `--shots` / `--audit-log` / `--e1-reviews` 任何一个从活行上摘掉，报告就会
    退回 `not_measured`，而链子依旧全绿（缺证据被当成通过的老形状）。

    `--audit-log` 是 §4.1b 硬规则 2 的通道：join 键只认 `audit_log.jsonl` 里
    **真实发出**的查询，不认 `shots.json` 反推的串（后者是收尾快照）。
    """
    line = live_quality_line(chain_text())
    assert missing_quality_inputs(line) == [], (
        "链上的 quality.py 活行缺输入：" + ",".join(missing_quality_inputs(line)))
    for flag in ("--shots", "--audit-log"):
        match = re.search(re.escape(flag) + r"\s+(\S+)", line)
        assert match, f"{flag} 后面看不出指向哪个文件"
        target = ROOT / match.group(1)
        assert target.is_file() and target.stat().st_size > 0, (
            f"{flag} 指向的证据 {match.group(1)} 不在或为空："
            f"Q5 的输入不许是空气（§4.1b 硬规则 1）")


def test_the_chain_input_checker_fires_when_the_flags_are_dropped():
    """自证：把三个开关摘掉的写法必须被判出来（否则上一条只是自我感觉良好）。"""
    stripped = ("python tools/knowledge/quality.py --run-id $runId --json "
                "--cases knowledge/cases.jsonl --out (Join-Path $evidenceDir "
                "'knowledge_quality.json')")
    assert missing_quality_inputs(stripped) == list(QUALITY_INPUT_FLAGS)
    # 只补回一个也不算够：三个输入各管一件事，缺一个就是缺证据。
    assert missing_quality_inputs(stripped + " --shots x/export/shots.json") == [
        "--audit-log", "--e1-reviews"]


# --------------------------------------------------------------------------- #
# 三、长基线：§4.4 步骤 1 点名的那条命令必须在链上跑，并断言镜数与预算上界
# --------------------------------------------------------------------------- #
def test_the_headless_step_runs_the_long_baseline():
    """链上那条 headless 必须带 `--script fixtures\\script_long_61.md`。

    2026-10-03 实测：它此前**不带 `--script`** ⇒ 跑的是 2 镜默认剧本。后果不是
    "少跑一条命令"，而是 **P13 的验收（"61 镜跑完不降级"）在链上根本没有被执行**：
    61 镜的**计划形状**由 pytest 覆盖，但长路径的**建场、标签烘焙、导出与预算上界**
    一次都没跑过。§4.4 步骤 1 的命令是 `... --offline --script
    fixtures/script_long_61.md --build`。
    """
    calls = [line for _number, line in live_lines(chain_text())
             if "run_headless.py" in line]
    assert calls, "链上没有 run_headless.py 的活行"
    assert any("script_long_61" in line for line in calls), (
        "headless 那条活行必须带 --script fixtures\\script_long_61.md："
        "否则 P13 的长基线在链上没有被执行")


def test_the_long_baseline_step_asserts_shots_and_the_budget_ceiling():
    """光"跑了"不算：必须断言**镜数**与**预算上界**，否则 2 镜也能绿。

    §2.4 的唯一口径是 `ceiling_effective = max(200, shots * 8 + 40)`（61 镜 → 528）。
    这条静态检查要求链上出现：① `state` 必须是 DONE；② 产出镜数有下界（≥61）；
    ③ 用同一个公式算出 ceiling 并比较 `llm_calls`。数字全部从
    `BLOCKDIRECTOR_RESULT` 的 JSON 载荷里读（不是从单行里正则捞）。
    """
    text = chain_text()
    lines = [line for _number, line in live_lines(text)]
    joined = "\n".join(lines)
    assert '"state": "DONE"' in joined, "链上必须断言长基线终态是 DONE"
    assert "Math]::Max(200" in joined and "* 8 + 40" in joined, (
        "链上必须按 §2.4 的公式算 ceiling_effective = max(200, shots*8+40)")
    assert "-lt 61" in joined, "链上必须断长基线产出镜数 ≥ 61"
    assert "llm_calls" in joined and "ceiling" in joined, (
        "链上必须把 llm_calls 与 ceiling 比较")
    assert "Get-MarkerPayload" in joined, (
        "镜数/预算必须从 JSON 载荷读，别在单行里正则捞数字")


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


# --------------------------------------------------------------------------- #
# 三、空参数不许在 PowerShell 里消失（成功路径的最后一个 bug）
# --------------------------------------------------------------------------- #
def vanishing_failed_args(text: str):
    """返回 `--failed` 写了**裸变量**的调用行。

    PowerShell 5.1 调用原生命令时会**丢掉空字符串参数**。所以
    `--failed $rksFailed`（`$rksFailed = ''`）到 argparse 手里只剩一个光秃秃的
    `--failed` → 退出码 2 "expected one argument" → `rks.json` 没写 → 链最后那步
    S13 检查失败。实测 2026-10-02 11:17：**第一轮"所有门都过"的运行，也是第一轮
    无法报告自己通过运行**。判据：那条命令必须用 `--failed=` 这种单 token 写法。
    """
    offenders = []
    for number, line in live_lines(text):
        if "run_tests_rks.py" not in line:
            continue
        if re.search(r"--failed\s+\$", line):
            offenders.append(f"line {number}: {line.strip()[:120]}")
    return offenders


def test_the_rk_hook_passes_failed_as_one_token():
    text = chain_text()
    assert "run_tests_rks.py" in text
    assert not vanishing_failed_args(text), (
        "`--failed $rksFailed` 在 $rksFailed 为空时会被 PowerShell 整个丢掉："
        + "; ".join(vanishing_failed_args(text)))
    assert "--failed=$rksFailed" in text


def test_the_vanishing_argument_checker_fires_on_the_bare_variable_form():
    """自证：裸变量那种写法必须被判出来，`=` 写法放行。"""
    bare = "python tools/run_tests_rks.py --run-id $runId --failed $rksFailed\n"
    assert vanishing_failed_args(bare)
    fixed = "python tools/run_tests_rks.py --run-id $runId --failed=$rksFailed\n"
    assert vanishing_failed_args(fixed) == []
    # 注释里怎么写都不算（活行判据）。
    commented = "# python tools/run_tests_rks.py --failed $rksFailed\n"
    assert vanishing_failed_args(commented) == []


def test_the_rk_tool_itself_accepts_an_empty_failed_list(tmp_path):
    """工具侧要能接受空清单——修的是"参数别丢"，不是"工具改成必须给值"。"""
    import subprocess

    done = subprocess.run(
        [sys.executable, "tools/run_tests_rks.py", "--run-id", "tolerance",
         "--evidence-dir", str(tmp_path / "ev"), "--checks", "RK-7", "--failed="],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "ev" / "rks.json").is_file()
