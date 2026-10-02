"""把 CLI 的输出流固定成 UTF-8——**工具的退出码与输出都不许取决于控制台编码**。

**为什么需要它（实测依据，2026-10-02）**

中文 Windows 上控制台是 cp936，而 ``print()`` 用的是 ``sys.stdout.encoding``。
凡是往 stdout 打中文（或 `⊆` 这类 cp936 编不出的符号）的命令行工具，都会踩到
两种成因不同、后果不同的故障：

1. **进程直接死掉，退出码说谎。** ``python tools/check_holdout.py … --json``
   会打印整份报告，里面有 `⊆`（`gate_10_index_resolvable.note` 写着
   "must/top1 ⊆ 索引里的边"）→ ``UnicodeEncodeError`` → 未捕获异常退出。
   而它的退出码**就是判据**（0 = 全部门通过 / 1 = 有门失败 / 2 = 缺证据），
   于是"全部门通过"被报成"门失败"。``tools/run_tests.ps1`` 先设了
   ``PYTHONIOENCODING=utf-8`` 才没暴露；任何直接调用（人工核对、测试里的
   ``subprocess``）都会踩到。
2. **输出字节随控制台变。** ``authorship_report`` / ``gap_report`` /
   ``run_tests_rks`` 打的是中文（cp936 编得出），所以不崩，但 stdout 是 cp936
   字节；下游按 UTF-8 解码就得到乱码或 ``UnicodeDecodeError``
   （``tests/test_gap_report.py`` 的 reader-thread 警告就是这个：子进程把带中文
   路径的 traceback 按 cp936 写给按 utf-8 解码的父进程）。

``tools/kb_fetch/find_sources.py`` / ``find_ocw_sources.py`` 早先各自内联过同一段
处置（`ä` 那次事故）。这里把它收成**一份**实现，验收链上的工具统一调用它——
按本仓库的规矩，"同一个事实"不抄第二遍。

处置后的性质（`tests/test_cli_console_encoding.py` 逐条钉住）：
同一命令在 ``PYTHONIOENCODING=gbk`` 与 ``=utf-8`` 下给出**相同的退出码**、
**逐字节相同的 stdout**、stderr 里没有 traceback。

本模块不 import bpy，可在任意 Python 环境与测试中使用。
"""

from __future__ import annotations

import sys


def force_utf8_streams() -> None:
    """把 ``sys.stdout`` / ``sys.stderr`` 重配成 UTF-8 ＋ ``errors="replace"``。

    ``errors="replace"`` 是刻意的：编码问题最多让某个字符显示成 ``?``，
    绝不让一次长跑（或一次判据）因为一个字符作废。

    被重定向成非 ``TextIOWrapper``（例如某些测试替身）时静默跳过——
    拿不到 ``reconfigure`` 就没有编码问题可言。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 流已关闭/不可重配
            pass
