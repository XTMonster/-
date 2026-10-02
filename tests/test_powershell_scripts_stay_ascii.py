"""`.ps1` 里不许出现非 ASCII 字符——这条规则写在 `tools/run_tests.ps1` 的文件头上，
但直到 2026-10-02 它**没有任何测试看着**，于是当场踩了一次，而且踩得很安静。

## 事故（有据可查）

`tools/run_tests.ps1` 是 **BOM-less UTF-8**。Windows PowerShell 5.1 **不嗅探 UTF-8**，
它按 ANSI 代码页（本机 cp936）解码。注释里的中文被拆成 GBK 双字节序列后，**最后一个
字节会和行尾的 CR 配对**，于是换行消失——**下一行整行并进上一条注释**。

实测（`[System.Text.Encoding]::GetEncoding(936)` 解码当时的文件）：

```
311: # 鑼冨洿澶栫殑鍗★紙…鍦?# `tools/kb_fetch/card_scope_audit` …  $gateExit = …
```

被吞掉的正是门⑥ 的调用行：

```
python tools/check_holdout.py … --exclude-cards knowledge/card_scope.json --out … > $null 2>&1
```

后果不是报错，而是**静默跳过**：命令没执行，`$LASTEXITCODE` 保留上一条 Python 的 0，
脚本于是打印 `held-out coverage gates: all passed`——**门其实一次都没跑**——然后
`Test-Path holdout_gates.json` 失败，链路以一句
`FAILED: the held-out gate report was not written` 收尾，把人往"重定向不写文件"的
方向带（我第一轮就是这么误诊的）。同一次运行里 pytest 1512 passed、31/31 探针全绿，
所以如果那天的核对应答没把这条日志读到底，这轮"门全过"就会被当成真的。

## 所以这里钉三条

1. 仓库里每个 `.ps1` 必须是**纯 ASCII**（含 BOM 也不行——BOM 说明有人当 UTF-8 存）。
2. 判据本身要有牙：造一个非 ASCII 的脚本必须被抓出来（负对照），纯 ASCII 的必须放行
   （正对照）。没有这两条，"扫描器扫了 0 个文件"也会绿。
3. **把机制本身钉住**：换行是怎么被吃掉的——GBK 里 `0x81..0xFE` 是引导字节、要吃掉
   后一个字节；行尾若剩一个引导字节，它吃掉的就是后面那个 `\r`。这条按**字节**算，
   不依赖任何解码器，所以机器判据和"到底是哪一步出的错"是同一件事。

（注：Python 的 `gbk` 解码器**不能**复现 .NET 的吞行——同一段字节它两种都试过，
一边吞一边不吞。所以这里不去模拟解码器，只算字节配对。）
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 不是仓库资产，是本地垃圾/产物：诊断脚本、证据目录里被跑出来的副本。
SKIP_DIRS = {".git", ".scratch", "work", "__pycache__", ".pytest_cache", "node_modules"}


def _powershell_scripts() -> list[pathlib.Path]:
    found = []
    for path in ROOT.rglob("*.ps1"):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        found.append(path)
    return sorted(found)


def _non_ascii(path: pathlib.Path) -> list[tuple[int, int]]:
    """返回 [(字节偏移, 字节值), ...]，空列表 = 纯 ASCII。"""
    raw = path.read_bytes()
    return [(i, b) for i, b in enumerate(raw) if b > 127]


def _swallows_its_newline(line: bytes) -> bool:
    """这一行按 GBK 配对后，最后一个引导字节是不是只剩下了「吃 CR」这一条路。

    GBK 的配对规则：`0x81..0xFE` 是引导字节，消费掉后一个字节；其余各自消费一个。
    走到末尾时如果**越过了行尾**，说明最后一个引导字节要去吃 CR——那一行的换行
    就没了，下一行并进这一行（事故就是这么发生的）。
    """
    index, size = 0, len(line)
    while index < size:
        index += 2 if 0x81 <= line[index] <= 0xFE else 1
    return index > size


def test_the_repo_actually_has_powershell_scripts_to_check() -> None:
    """扫描器扫到 0 个文件也必须算失败：那是判据失效，不是"没问题"。"""
    scripts = _powershell_scripts()
    assert scripts, "一个 .ps1 都没扫到——判据本身失效了"
    assert (ROOT / "tools" / "run_tests.ps1") in scripts


def test_every_powershell_script_is_pure_ascii() -> None:
    offenders = {}
    for path in _powershell_scripts():
        bad = _non_ascii(path)
        if bad:
            offenders[str(path.relative_to(ROOT))] = bad[:5]
    assert not offenders, (
        "这些 .ps1 含非 ASCII 字符，PowerShell 5.1 会按 ANSI 解码并可能吞掉下一行"
        "（详见本文件头部的事故记录）：" + repr(offenders))


def test_every_powershell_script_has_no_bom() -> None:
    for path in _powershell_scripts():
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), (
            f"{path} 带 UTF-8 BOM；本仓的 .ps1 约定是纯 ASCII 且无 BOM")


def test_the_ascii_check_has_teeth(tmp_path: pathlib.Path) -> None:
    """负对照：带一个中文字的脚本必须被抓；正对照：纯 ASCII 必须放行。"""
    bad = tmp_path / "bad.ps1"
    bad.write_bytes("# 这一段是中文注释\npython tools/x.py\n".encode("utf-8"))
    assert _non_ascii(bad), "非 ASCII 文件没被抓出来——判据没牙"

    good = tmp_path / "good.ps1"
    good.write_bytes(b"# plain ascii comment\npython tools/x.py\n")
    assert _non_ascii(good) == []


def test_the_swallow_mechanism_is_real() -> None:
    """负对照：证明这条判据抓得住"行尾剩一个引导字节"的形状，不是恒真。"""
    # 3 个 UTF-8 字节 = 1 个汉字。1 个汉字时，E6 吃掉 BC，剩下 A2 是引导字节、
    # 只能去吃后面的 CR —— 换行被吃掉。
    assert _swallows_its_newline("# 汉".encode("utf-8")) is True
    # 2 个汉字时 6 个字节两两配对正好走完，不吃 CR。
    assert _swallows_its_newline("# 汉字".encode("utf-8")) is False
    # 纯 ASCII 恒不触发（对照，防止判据把正常脚本也判红）。
    assert _swallows_its_newline(b"# plain ascii") is False


def test_no_powershell_line_eats_its_own_newline() -> None:
    """把上面那条机制**逐行**跑一遍仓库里的脚本。

    纯 ASCII 的文件天然全过（没有任何字节 >= 0x81）；这条的真正价值是：万一将来
    有人在别的代码页/别的写法下又绕开纯 ASCII 的判据，机制本身还会再拦一次。

    行尾按 LF 切、再去掉一个 CR——仓库里两种行尾都有（`run_tests.ps1` 的工作副本
    是 LF，checkout 时可能变 CRLF），只按 `\\r\\n` 切会让这条判据在 LF 文件上变成
    "整份文件算一行"，那就等于没查。
    """
    offenders = {}
    for path in _powershell_scripts():
        for number, line in enumerate(path.read_bytes().split(b"\n"), start=1):
            line = line[:-1] if line.endswith(b"\r") else line
            if _swallows_its_newline(line):
                offenders.setdefault(str(path.relative_to(ROOT)), []).append(number)
    assert not offenders, (
        f"这些 .ps1 的行尾会吃掉换行，下一行将被并进注释：{offenders}")
