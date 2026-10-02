"""验收工具的**退出码不许取决于控制台编码**。

2026-10-02 实测（中文 Windows，控制台 cp936）::

    python tools/check_holdout.py fixtures/knowledge_holdout.jsonl --vocab … --json
    → UnicodeEncodeError: 'gbk' codec can't encode character '\\u2286'
      （`--json` 那份报告里 `gate_10_index_resolvable.note` 写着 "must/top1 ⊆ 索引里的边"）
    → 未捕获异常 → 进程退出码 **1**

而 1 在这个工具里的含义是"**有门失败**"（0 = 全部门通过 / 1 = 有门失败 /
2 = 缺证据，见 `tools/check_holdout.py:main` 的返回式）。于是：

* **"全部门通过"被报成"门失败"** —— 判据的退出码自己说谎；
* `tools/run_tests.ps1` 之所以没暴露，是因为它先设了 `PYTHONIOENCODING=utf-8`；
  任何**直接调用**（人工核对门⑥、测试里的 `subprocess.run`）都会踩到。

这也是 `tests/test_gap_report.py` 里那条 `PytestUnhandledThreadExceptionWarning`
（`_readerthread` 解码 0xb0 失败）的真正来因：子进程把 traceback（含中文路径
`E:\\白模预演codex`）按 cp936 写到 stderr，父进程按 utf-8 严格解码。

所以这里钉两条不变量：

1. 同一条命令在 `PYTHONIOENCODING=gbk` 与 `=utf-8` 下**退出码相同**、
   **stdout 逐字节相同**、stderr 里没有 traceback、写出的报告文件逐字节相同；
2. 退出码与报告里的 `overall` 一一对应（pass→0 / fail→1 / not_measured→2）。

外加一条**反面控制**：不做事后处置的朴素子进程在 gbk 下确实会死——证明第 1 条
不是恒真式（"判据必须有鉴别力"，§B.5）。
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GATES = ["tools/check_holdout.py", "fixtures/knowledge_holdout.jsonl",
         "--vocab", "fixtures/knowledge_holdout.vocab.json",
         "--cards", "fixtures/knowledge_holdout.cards.json",
         "--assertable", "fixtures/knowledge_holdout.assertable.json",
         "--reviewer-classes", "human,llm-panel", "--json"]


def run_gates(encoding: str, out_path: pathlib.Path):
    """在指定控制台编码下跑一遍门；stdout/stderr 一律按字节取回。

    刻意不传 `encoding=`/`text=`：**要看的正是原始字节**（"两种编码下 stdout
    是否逐字节相同"）。父进程因此不会因为子进程的编码而死。
    """
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    return subprocess.run([sys.executable, *GATES, "--out", str(out_path)],
                          cwd=str(ROOT), capture_output=True, env=env)


def test_gate_tool_exit_code_and_stdout_do_not_depend_on_console_encoding(tmp_path):
    """门⑥/⑦/⑩ 那套门：gbk 控制台与 utf-8 控制台必须给出**同一个判据**。"""
    gbk = run_gates("gbk", tmp_path / "gates_gbk.json")
    utf = run_gates("utf-8", tmp_path / "gates_utf8.json")
    assert b"Traceback" not in gbk.stderr, gbk.stderr[:800]
    assert b"UnicodeEncodeError" not in gbk.stderr, gbk.stderr[:800]
    assert gbk.returncode == utf.returncode, (gbk.returncode, utf.returncode)
    assert hashlib.sha256(gbk.stdout).hexdigest() == \
        hashlib.sha256(utf.stdout).hexdigest(), (
            "两种编码下 stdout 不一致：工具没有把输出流固定成 UTF-8")
    assert (tmp_path / "gates_gbk.json").read_bytes() == \
        (tmp_path / "gates_utf8.json").read_bytes()


def test_gate_tool_exit_code_matches_the_report_it_writes(tmp_path):
    """退出码必须与报告里的 `overall` 对得上（0/1/2 的契约，别让异常冒充它）。"""
    done = run_gates("gbk", tmp_path / "gates.json")
    report = json.loads((tmp_path / "gates.json").read_text(encoding="utf-8"))
    expected = {"pass": 0, "fail": 1, "not_measured": 2}[report["overall"]]
    assert done.returncode == expected, (done.returncode, report["overall"])
    # 报告里必须真的带着那个 cp936 编不出的字符，否则这条用例是"没碰过现场"。
    assert "\u2286" in json.dumps(report, ensure_ascii=False)


#: 链上会打印中文的**验收工具**（`(名字, 造 argv 的函数)`）。三者都曾把 stdout
#: 交给控制台编码：cp936 下不崩，但下游按 UTF-8 解码得到乱码或直接抛异常。
ACCEPTANCE_TOOLS = [
    ("authorship_report",
     lambda tmp: ["tools/knowledge/authorship_report.py", "--json",
                  str(tmp / "authorship.json")]),
    ("gap_report",
     lambda tmp: ["tools/knowledge/gap_report.py", "--json",
                  "--out-dir", str(tmp / "gaps")]),
    ("run_tests_rks",
     lambda tmp: ["tools/run_tests_rks.py", "--run-id", "probe",
                  "--evidence-dir", str(tmp / "evidence"), "--checks", "RK-7"]),
]


@pytest.mark.parametrize("name,build_argv", ACCEPTANCE_TOOLS,
                         ids=[item[0] for item in ACCEPTANCE_TOOLS])
def test_console_encoding_does_not_change_another_acceptance_tool(name, build_argv, tmp_path):
    """同一不变量也管住链上别的工具：编码只能影响**显示**，不能影响字节。"""
    runs = {}
    for encoding in ("gbk", "utf-8"):
        env = dict(os.environ, PYTHONIOENCODING=encoding)
        # 两次跑同一组 argv（同一个输出路径）——路径本身进 stdout 也不影响对拍。
        runs[encoding] = subprocess.run(
            [sys.executable, *build_argv(tmp_path)], cwd=str(ROOT),
            capture_output=True, env=env)
    gbk, utf = runs["gbk"], runs["utf-8"]
    assert b"Traceback" not in gbk.stderr, (name, gbk.stderr[:800])
    assert b"UnicodeEncodeError" not in gbk.stderr, (name, gbk.stderr[:800])
    assert gbk.returncode == utf.returncode, (name, gbk.returncode, utf.returncode)
    assert gbk.stdout.decode("utf-8")          # 严格解码：cp936 字节会在这里炸
    assert hashlib.sha256(gbk.stdout).hexdigest() == \
        hashlib.sha256(utf.stdout).hexdigest(), (
            f"{name}: 两种编码下 stdout 不一致（工具没有固定输出编码）")


def test_the_negative_control_still_dies_on_a_gbk_console(tmp_path):
    """反面控制：**不处置**的朴素子进程在 gbk 下确实会死。

    没有这条，"退出码与编码无关"可能只是判据没在判东西。它同时也解释了
    `test_gap_report.py` 那条 reader-thread 警告的来因（子进程的 stderr
    带着中文路径、按 cp936 编码）。
    """
    naive = tmp_path / "naive.py"
    naive.write_text(
        "import json, sys\n"
        # 先写一行**本身编得出**的中文（gbk 下会写成 0xb0 0xd7…）：
        # 这正是 reader-thread 那一版的现场——`0xb0` 不是合法的 UTF-8 前导字节。
        "print('E:\\\\白模预演codex', file=sys.stderr)\n"
        "print(json.dumps({'note': 'must/top1 \u2286 edges'}, ensure_ascii=False))\n",
        encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="gbk")
    done = subprocess.run([sys.executable, str(naive)], capture_output=True,
                          env=env)
    assert done.returncode != 0
    assert b"UnicodeEncodeError" in done.stderr
    raw = done.stderr
    assert b"\xb0\xd7" in raw, "'白' 在 cp936 下是 0xb0 0xd7 —— 现场那一对字节"
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")      # 严格 utf-8 解码 ⇒ reader thread 里那一下
