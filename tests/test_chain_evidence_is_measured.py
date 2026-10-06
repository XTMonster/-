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

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import quality  # noqa: E402


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
                "--cases knowledge --out (Join-Path $evidenceDir "
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


def test_the_chain_also_runs_step_3_the_rebuild():
    """§4.4 **步骤 3**（`rebuild_project.py`）必须被执行——P9.4 的验收列明写
    "步骤 1 与步骤 3 按字面可执行"。

    2026-10-03 实测：`tools/rebuild_project.py` **全仓无人调用**（`rg` 在
    `tests/`、`tools/` 里只命中它自己），链上也没有这一步 ⇒ "改一镜、重出一镜"这条
    路（不调 LLM 也能重建场景）**从来没有任何机器验证**。它按字面能在
    `docs/evidence/offline_run1/project` 上跑通（实测 154 s、`ok: true`、64 镜、
    4584 帧），产物落在 `<project>/export/`（§R44⑩ 记过的双层嵌套；`.gitignore`
    已把这类**可重生成的嵌套导出**排除，免得每次按字面跑都脏一次工作树）。

    这条用例钉住链上的**存在性**与**断言面**：必须带 `--project`/`--export`，
    必须断言 `ok: true`、导出块 ok、且镜数与帧数与步骤 1 **相等**（重建悄悄少几镜
    也会打印 ok）。
    """
    lines = [line for _number, line in live_lines(chain_text())]
    calls = [line for line in lines if "rebuild_project.py" in line]
    assert calls, "链上没有调用 tools/rebuild_project.py（§4.4 步骤 3）"
    call = calls[0]
    assert "--project" in call and "--export" in call, call
    joined = "\n".join(lines)
    assert "BLOCKDIRECTOR_REBUILD" in joined, "必须读重建的标记"
    assert "rebuildJson.shots" in joined and "rebuildJson.total_frames" in joined, (
        "重建必须断言镜数与帧数与步骤 1 相等（否则少几镜也会绿）")
    assert "rebuildJson.export" in joined, "重建带了 --export，就必须断言导出块"


def test_step_1_runs_at_the_preset_the_doc_calls_mandatory():
    """§4.4 步骤 1 的命令里 `--preset fhd16x9` 是**必给**的，链上此前没给。

    文档的理由是"随分辨率变的是 RK-4 的眼簇与 RK-14 的头球直径"，而默认 preset 是
    hd16x9 = 1280×720。实测两条硬证据：

    * **入库的 `docs/evidence/offline_run1/export/shots.json` 是 `[1920, 1080]`**——
      也就是说当初按文档跑出来的那份产物用的是 fhd16x9，而链上那条命令跑的是默认；
    * `run_headless.py` 的 `--preset` 确实存在、也确实写进 `config.delivery.preset`
      （`:115-118`），所以问题不在开关，而在链上没传。

    这条用例钉住"传了"与"断言了产物分辨率"两件事——只传不断言，开关空转时没人会发现
    （RK-4/RK-14 的探针有自己的 640×360 分辨率常量，所以它们**不会**替这条命令兜底）。
    """
    lines = [line for _number, line in live_lines(chain_text())]
    calls = [line for line in lines if "run_headless.py" in line]
    assert calls, "链上没有 run_headless.py 的活行"
    assert any("fhd16x9" in line for line in calls), (
        "§4.4 步骤 1 的命令必须显式给 --preset fhd16x9")
    joined = "\n".join(lines)
    assert "shots.json" in joined and "1920x1080" in joined, (
        "只传 --preset 不够：必须从导出的 shots.json 断言分辨率真的变了")
    # 负对照：Probe 侧的 RK-4/RK-14 用的是自己的小分辨率，不会替这条兜底。
    geometry = (ROOT / "tools" / "blender_tests" / "test_character_geometry.py"
                ).read_text(encoding="utf-8")
    assert "WIDTH, HEIGHT = 640, 360" in geometry, (
        "如果哪天 RK-4/RK-14 的探针改吃 preset，这条用例的前提要重写")


def test_the_nested_rebuild_export_is_gitignored():
    """按字面跑步骤 3 会在 `<project>/export/` 留一份**可重生成**的输出。

    它是"重新导出一次"的产物（与 mp4/first_frames 同类），而一次运行的入库证据是
    `<run>/export/`。不排除它，每次按文档跑一遍步骤 3 就会往工作树里丢 132 个未跟踪
    文件——那正是"下一次 `git add -A` 把它们带进去"的前提。
    """
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    rule = [line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
            and "project/export" in line]
    assert rule, "`.gitignore` 必须排除重建产生的嵌套导出"


# --------------------------------------------------------------------------- #
# 四、US-16 / §4.4 步骤 0b：缺环境必须**判无法测量**，而不是把"跑不了"记成"代码坏了"
# --------------------------------------------------------------------------- #
def blender_guard_is_sound(text: str) -> bool:
    """链上那段"定位 Blender"的活行是否守法（US-16 的两半）。

    判据（全部只看**活行**）：

    ① **非空的 `$env:BLENDER_EXE` 必须先被 `Test-Path` 检一遍**——指向死路径时
       不能"当作没设"直接崩在后面；
    ② 候选都找不到时必须以 `INCOMPLETE` ＋ `exit 1` 收场（"这次没量"与"代码坏了"
       是两件事，报告必须说清是哪一种）。
    """
    lines = [line for _number, line in live_lines(text)]
    exe_at = [index for index, line in enumerate(lines)
              if "$env:BLENDER_EXE" in line]
    if not exe_at:
        return False
    window = "\n".join(lines[exe_at[0]:exe_at[0] + 4])
    if "Test-Path" not in window:
        return False
    incomplete_at = [index for index, line in enumerate(lines)
                     if "INCOMPLETE" in line]
    if not incomplete_at:
        return False
    tail = "\n".join(lines[incomplete_at[0]:incomplete_at[0] + 4])
    return "exit 1" in tail


def test_the_chain_refuses_a_dead_blender_path_and_says_incomplete():
    """§4.4 步骤 0b / US-16：**缺环境必须失败，而不是假装全绿**。

    现场（文档 §4.4 步骤 0b 的原文）：把 `BLENDER_EXE` 指向"死路径"**不会**命中
    `INCOMPLETE` 分支——脚本只在变量为空时才搜候选。所以这一半必须显式做
    `Test-Path`，否则死路径会被当成"设过了"，问题推迟到几十个探针一起报
    "blender 打不开"，而那会被读成"代码坏了"。

    2026-10-03 实测：`rg BLENDER_EXE tests` **零命中**——两半都没有任何测试钉住。
    这条静态门（带自证）补上：判据只看**活行**，把守卫摘掉的写法必须被判出来。
    """
    text = chain_text()
    assert blender_guard_is_sound(text), (
        "链上定位 Blender 的那一段必须：① 对非空的 BLENDER_EXE 做 Test-Path；"
        "② 找不到时打印 INCOMPLETE 并 exit 1")

    # 自证：把守卫改成"死路径也照用"，判据必须开火。
    broken = text.replace("if ($blender -and -not (Test-Path $blender)) {",
                          "if ($false) {")
    assert broken != text, "自证需要能改动那段守卫（源码形状变了要同步这条用例）"
    assert not blender_guard_is_sound(broken), (
        "去掉死路径的 Test-Path 守卫之后，判据没开火——这条用例就是空的")


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


# --------------------------------------------------------------------------- #
# 四、链的读数必须能归因到**一棵树**（2026-10-05 联合会诊 D3）
# --------------------------------------------------------------------------- #
def tree_guard_is_sound(text: str) -> bool:
    """链是否① 取树摘要、② 写进证据、③ 树动了就 INCOMPLETE ＋ 非零退出。

    "记下来"不算：只有**判定**了才算。生成物（`docs/evidence/`）必须排除在摘要外
    ——链自己会往那里写盘，不排除就会把每一次运行都判成"树动了"。
    """
    if "function Get-TreeDigest" not in text or "$treeBefore = Get-TreeDigest" not in text:
        return False
    body = text[text.index("function Get-TreeDigest"):text.index("$treeBefore = Get-TreeDigest")]
    #: 判据是**谓词**本身（注释里提到 `docs/evidence/` 不算数——自证用例会因此恒真）。
    if "-notmatch 'docs/evidence/'" not in body:
        return False                      # 生成物进了摘要 ⇒ 自己写盘就把自己判红
    if "$treeAfter = Get-TreeDigest" not in text:
        return False
    tail = text[text.index("$treeAfter = Get-TreeDigest"):]
    if "tree.json" not in tail:
        return False
    if "$treeBefore -ne $treeAfter" not in tail:
        return False
    #: **"INCOMPLETE" 与"非零退出"必须挨着**（2026-10-05 收紧）：链子在更后面
    #: 还有别的 `exit 1`（RK-13 升格之后，红线未达也非零退出）。只要按"tail 里
    #: 同时出现过这两个串"来判，那条无关的 exit 1 就把这枚判据**变成恒真**——
    #: 把树守卫的整段删掉、用例仍然说"健全"。所以窗口必须小：同一条裁决里
    #: 打印 INCOMPLETE 并退出。
    index = tail.find("INCOMPLETE")
    while index != -1:
        if "exit 1" in tail[index:index + 400]:
            return True
        index = tail.find("INCOMPLETE", index + 1)
    return False


def test_the_chain_pins_its_numbers_to_one_tree():
    """链必须证明"这些数字来自同一棵树"（HEAD ＋ 脏清单 ＋ diff）。

    现场（2026-10-05 实测）：并发 lane 正在改同一工作树时，链第 2 步红
    （2 failed / 2037 passed），几分钟后同一套用例在**稳定的**树上 2041/0 failed
    ——而链自己说不出来"那次红是中间态"。于是读数归因只能靠人复述，正是
    §24.1「过期证据被当成现行证据」的同族形状。
    """
    text = chain_text()
    assert tree_guard_is_sound(text), (
        "链上没有『取树摘要 ⇒ 写证据 ⇒ 树动了判 INCOMPLETE』这条守卫："
        "绿色可能是在说一棵已经不存在的树")


def test_the_tree_guard_checker_fires_on_each_missing_half():
    """自证：三种残法都必须判 False（只取不判 ／ 不排除生成物 ／ 判了不退出）。"""
    text = chain_text()

    recorded_only = text.replace("$treeBefore -ne $treeAfter", "$false")
    assert recorded_only != text, "自证需要能改动那段判定（源码形状变了要同步这条用例）"
    assert not tree_guard_is_sound(recorded_only)

    no_exclude = text.replace("$_ -notmatch 'docs/evidence/'", "$true")
    assert no_exclude != text
    assert not tree_guard_is_sound(no_exclude)

    no_exit = text.replace("""    Write-Host ('INCOMPLETE: before=' + $treeBefore + ' after=' + $treeAfter) -ForegroundColor Red
    Write-Host 'INCOMPLETE: these numbers are NOT attributable to one tree; rerun on a frozen tree.' -ForegroundColor Red
    exit 1""", "")
    assert no_exit != text
    assert not tree_guard_is_sound(no_exit)


def _live(text):
    """活行（命令行；注释会被 PowerShell 忽略，但它们不算"链在做什么"）。"""
    return [(number, line) for number, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")]


def test_q6b_reads_the_same_real_run_as_the_rest_of_the_knowledge_block():
    """Q6b 的读数通道必须读**与 knowledge 块同一跑**——这是 SS84 那条的同形洞。

    实测（2026-10-06）：链上 Q5 那一侧早在 SS84 就修成"喂当前代真跑"，而
    `tools/knowledge/injection_audit.py` 那一行**一直写死** `docs/evidence/20261003_real_long`
    ——那是**bm25 时代**的跑（SS84 的原话：它的逐镜查询 join 不上现在的 oracle）。
    后果不是"数字难看"，是**半边指标永远量不到**：旧跑的 required 半边 `not_measured`
    （`complete: false`），换成本代真跑 `20261006-long21` 后**当场变成 measured 且 pass**
    （167 个镜头 join 上 oracle、167 条 required 边、丢 0 条）。

    所以这条守门钉三件事：① 只允许**一处**调用；② 那一处必须走 `$knowledgeRun`，
    **不许再写死日期路径**（否则下一个人换跑时又会漏掉这一处）；③ 定义必须在该调用
    **之前**——PowerShell 自上而下执行，把变量挪到后面会让这行拿到空路径。
    """
    text = chain_text()
    calls = [(n, line) for n, line in _live(text) if "injection_audit.py" in line]
    assert len(calls) == 1, "链上只该有一处调用 injection_audit.py：%s" % calls
    number, line = calls[0]
    assert "$knowledgeRun" in line, (
        "Q6b 必须读与 knowledge 块**同一跑**（SS84 修的是 Q5 那一侧，Q6b 被漏下了）：%s" % line)
    assert not re.search(r"docs/evidence/\d{8}", line), (
        "不许把日期路径写死在链里——换跑时一定漏改：%s" % line)

    definitions = [(n, line) for n, line in _live(text)
                   if re.match(r"\s*\$knowledgeRun\s*=", line)]
    assert len(definitions) == 1, (
        "`$knowledgeRun` 只许有**一处**定义（两处定义就是这个洞的成因）：%s" % definitions)
    assert definitions[0][0] < number, (
        "定义必须在调用之前（PowerShell 自上而下执行）：定义在第 %d 行、调用在第 %d 行"
        % (definitions[0][0], number))


def test_the_chain_feeds_e1_a_review_file_the_metric_can_certify():
    """链喂给 E1 的打分文件必须**能被 E1 认证**——否则红线读的是"量不到"，不是"量到了、很低"。

    实测（2026-10-06，P14-260）：链一直喂 `docs/evidence/20261006-e1-craft/reviews.jsonl`。
    它**与当前索引同代**（`cases_digest` 与 live 逐字相同）、面板也对（deepseek-chat ＋ glm-5.3），
    但它是在 `--judge-batch` 存在**之前**产出的 ⇒ **没有一行带判分语境** ⇒
    `quality.e1_relevance` 按规矩**拒绝认证**、记 `not_measured`（`stale_evidence: true`）。
    于是 RK-13 那条红线的措辞是"**我们量不到**"，而不是"量到了、远低于 0.70"——对一条要
    "能可信地判成败"的红线来说，这两句话不是一回事。

    换成同一次测量的**认证版**（同索引、**同一批 64 条 long21 查询**、同两位评委、同 C=3
    产品口径 `rag.cases_top_k=3`）后，E1 变成 `fail`（**0.1771** < 0.70）。
    **判据一个字没动**（阈值 4.0、分母＝面板行数、线 0.70），而且它**不可能把红线翻绿**——
    它只是把"量不到的"变成"量到的"。

    这条守门钉的就是那个前提：**每一行都必须带产品口径的 `judge_batch`**。
    （"是不是当前代"由链自己的 `e1_evidence_is_stale` 负责，它记 `not_measured`＋
    `stale_evidence` 而不是静默判过——所以这里不重复它。）
    """
    lines = [line for _number, line in live_lines(chain_text()) if "--e1-reviews" in line]
    assert len(lines) == 1, "链上只该有一处给 E1 喂打分文件：%s" % lines
    match = re.search(r"--e1-reviews\s+(\S+)", lines[0])
    assert match, lines[0]
    path = ROOT / match.group(1)
    assert path.is_file(), "喂的打分文件必须存在：%s" % path
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").split("\n") if line.strip()]
    assert rows, "打分文件为空：%s" % path
    contexts = sorted({int(row.get("judge_batch") or 0) for row in rows})
    assert contexts == [quality.PRODUCT_CONTEXT], (
        "每一行都必须带**产品口径的判分语境**（rag.cases_top_k = %d），实得 %s；"
        "没有它，E1 只能记 not_measured（P14-260）" % (quality.PRODUCT_CONTEXT, contexts))
