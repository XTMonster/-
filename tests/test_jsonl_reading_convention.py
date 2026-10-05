"""守门：读 JSONL **只按换行符切**——不许用 `read_text().splitlines()`。

为什么（本仓自己的实测，写在 `tools/kb_fetch/common.read_jsonl` 的注释里）：
`str.splitlines()` 会按 **Unicode 行边界**切分，而 `\u0085`(NEL) / `\u2028` / `\u2029`
都是**合法的 JSON 字符串内容**，`json.dumps` 也不转义它们。于是它会
把一份好文件读成"坏行"——实测在 `work/corpus_v4/fetched.jsonl` 上直接抛
`JSONDecodeError: Unterminated string`。

2026-10-05 我自己在新模块里把这个教训又踩了一遍（`build_cases_v4`／`build_shadow`／
`coverage_matrix` 三处），所以补这条机器判据。历史用法列进白名单，新增的当场红。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common  # noqa: E402

#: 历史用法（不是读 JSONL，或读的是纯文本）：具名白名单。
WHITELIST = (
    "tools/kb_fetch/card_scope_audit.py",
    "tools/kb_fetch/probe_annotator.py",
    "tools/knowledge/attestation.py",
    "tools/knowledge/corpus_gates.py",
    "tools/knowledge/e1_panel.py",
    "tools/knowledge/injection_audit.py",
    "tools/knowledge/prune_holdout.py",
    "tools/knowledge/run_evidence.py",
    "block_director/knowledge/cases.py",
)

PATTERN = re.compile(r"read_text\([^)]*\)\s*\.splitlines\(\)")
SEARCH_ROOTS = ("tools/kb_fetch", "tools/knowledge", "tools/lightrag_service",
                "block_director/knowledge")


def _code_only(path: pathlib.Path) -> str:
    """剥掉注释与 docstring 再匹配——**规范写在注释里是对的，不该被自己绊倒**。"""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    text = re.sub(r"'''[\s\S]*?'''", "", text)
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))


def test_no_new_splitlines_on_read_text_in_the_pipeline_modules():
    offenders = []
    for root in SEARCH_ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            relative = str(path.relative_to(ROOT)).replace("\\", "/")
            if relative in WHITELIST:
                continue
            if PATTERN.search(_code_only(path)):
                offenders.append(relative)
    assert offenders == [], (
        "这些模块用 read_text().splitlines() 读 JSONL：%s\n"
        "请改用 tools.kb_fetch.common.read_jsonl（它只按换行符切）。" % offenders)


def test_read_jsonl_survives_a_unicode_line_separator(tmp_path):
    """反面控制：字符串里带 U+2028 的记录，`read_jsonl` 必须照读不误。"""
    path = tmp_path / "x.jsonl"
    #: 写**真正的** U+2028（不是 JSON 转义序列）——否则文件里根本没有那个字符，
    #: 这条反面控制就成了恒真式。
    path.write_text('{"text": "a\u2028b"}\n{"text": "plain"}\n', encoding="utf-8")
    rows = common.read_jsonl(path)
    assert [row["text"] for row in rows] == ["a\u2028b", "plain"]
    #: 而 `splitlines()` 会把第一行切开——这正是当年那个 bug 的形状。
    assert len(path.read_text(encoding="utf-8").splitlines()) > 2
