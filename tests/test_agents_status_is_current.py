"""`AGENTS.md` 的状态行必须与仓库**对得上**（v1.4 F7 / X16：漂移检查 ＋ 动态计数）。

为什么值得一条用例（2026-10-03 实测）：`AGENTS.md` 是 agent 唯一的验收真源，而它
**当场漂过一次**——链上新增一支探针（`body-ab`）之后，状态行里那句
`run_tests.ps1 31/31` 立刻就不对了，而没有任何东西会红。文档说"30 for the chain"
会让下一个 agent 照着错数字行事，这正是 F7/X16 记的"同源文档漂移"。

判据（都从**产物**推，不手填）：

* 链的总步数 = `tools/run_tests.ps1` 的探针清单长度 ＋ 4（spec/golden 漂移、pytest、
  契约冒烟、headless 各一步）——状态行里的 `N/N` 必须等于它；
* 状态行点名的最新证据目录必须**真的存在**（不能指向一个不存在的 run-id）；
* "门①–⑩ 全 pass" 这句必须与那份证据里的 `holdout_gates.json` 的 `overall` 一致
  （写了"全 pass"而产物是 fail，或者反过来，都算漂移）。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AGENTS = ROOT / "AGENTS.md"
CHAIN = ROOT / "tools" / "run_tests.ps1"
MARKER = "最新，以这行为准"


def latest_status_block() -> str:
    """状态块（从标注"最新，以这行为准"那行起，到空行为止）。

    找不到就当场红——它被删掉本身就是漂移。整块一起读是因为**现况是跨行的**：
    `N/N` 与证据目录在紧随其后的几行里，只看标记那一行会什么都读不到。
    """
    lines = AGENTS.read_text(encoding="utf-8").splitlines()
    hits = [index for index, line in enumerate(lines) if MARKER in line]
    assert hits, f"AGENTS.md 里没有标注『{MARKER}』的现状行：状态真源丢了"
    assert len(hits) == 1, (
        f"『{MARKER}』出现了 {len(hits)} 次：状态表必须**只有一份**（X16：合并为单一状态表）")
    block = []
    for line in lines[hits[0]:]:
        if not line.strip():
            break
        block.append(line)
    return "\n".join(block)


def chain_step_total() -> int:
    """链的总步数：探针清单长度 ＋ 4。

    与 `run_tests.ps1` 里的 `$total = $checks.Count + 4` 同源——这里数的是**清单条目**
    （`@{ Script = ... }`），不是注释里提到的文件名。
    """
    text = CHAIN.read_text(encoding="utf-8")
    entries = re.findall(r"^\s*@\{ Script = ", text, flags=re.M)
    assert entries, "run_tests.ps1 里没找到探针清单条目"
    return len(entries) + 4


def test_the_status_line_reports_the_real_chain_size():
    """状态行里的 `N/N` 必须等于链的真实步数（加了探针就得跟着改）。"""
    line = latest_status_block()
    seen = re.findall(r"(\d+)\s*/\s*(\d+)", line)
    assert seen, f"状态行里没有 `N/N` 形式的链规模：{line[:80]}…"
    expected = chain_step_total()
    for left, right in seen:
        assert (int(left), int(right)) == (expected, expected), (
            f"AGENTS.md 写的是 {left}/{right}，链实际上是 {expected}/{expected}"
            f"（探针清单 {expected - 4} 支 ＋ 4 步固定步骤）")


def test_the_status_line_points_at_evidence_that_exists():
    """状态行点名的最新证据目录必须存在——指向不存在的 run-id 就是漂移。"""
    line = latest_status_block()
    pointers = re.findall(r"docs/evidence/([A-Za-z0-9._-]+)", line)
    assert pointers, f"状态行没有点名任何证据目录：{line[:80]}…"
    missing = [name for name in pointers
               if not (ROOT / "docs" / "evidence" / name).is_dir()]
    assert not missing, f"状态行指向的证据目录不存在：{missing}"


def test_the_gate_claim_matches_the_evidence_it_points_at():
    """`门①–⑩ 全 pass` 这句必须与那份证据的 `holdout_gates.json` 一致。"""
    line = latest_status_block()
    claims_all_pass = "门①–⑩" in line and "全 pass" in line
    if not claims_all_pass:
        return                      # 状态行没声称全过时，这条不适用
    name = re.findall(r"docs/evidence/([A-Za-z0-9._-]+)", line)[0]
    gates_path = ROOT / "docs" / "evidence" / name / "holdout_gates.json"
    assert gates_path.is_file(), f"证据目录 {name} 里没有 holdout_gates.json"
    payload = json.loads(gates_path.read_text(encoding="utf-8"))
    assert payload.get("overall") == "pass", (
        f"状态行写『门①–⑩ 全 pass』，而 {name}/holdout_gates.json 的 overall 是 "
        f"{payload.get('overall')!r}：文档与产物对不上")
