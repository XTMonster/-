"""逐镜散文的**收集口径**：一行一条、去重、账目对得上。

为什么值得钉（2026-10-06 实测）：真实 `project.bdproj` 里 **5 条 `prompt` 带换行**，
原样写出会让池文件从 1,251 条变 **1,275 行**——冻出来的"查询"里会混进**碎片**，
而 `freeze_eval` 与 `e1_panel --queries` 都是**按行**读的。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import collect_shot_prompts as csp  # noqa: E402


def _project(*prompts):
    return {"scenes": [{"shots": [{"prompt": text} for text in prompts]}]}


def test_internal_whitespace_is_folded_so_one_query_stays_one_line():
    assert csp.prompts_of(_project("  远景建立镜头，\n固定机位。  ")) == ["远景建立镜头， 固定机位。"]
    assert csp.prompts_of(_project("a\n\nb", "c\td")) == ["a b", "c d"]


def test_empty_prompts_are_skipped():
    assert csp.prompts_of(_project("", "  ", "有内容")) == ["有内容"]


def test_collect_dedups_across_projects_and_books_the_accounts(tmp_path):
    a = tmp_path / "a.bdproj"
    b = tmp_path / "b.bdproj"
    import json
    a.write_text(json.dumps(_project("同一条", "甲"), ensure_ascii=False), encoding="utf-8")
    b.write_text(json.dumps(_project("同一条", "乙"), ensure_ascii=False), encoding="utf-8")
    report = csp.collect([a, b])
    assert report["pool"] == ["同一条", "甲", "乙"], "跨项目去重，且保持首次出现的顺序"
    assert report["first_seen"]["同一条"] == str(a), "记下第一次出现在哪个文件"
    a_book = [row for row in report["files"] if row["file"] == str(a)][0]
    b_book = [row for row in report["files"] if row["file"] == str(b)][0]
    assert (a_book["shots"], a_book["new"], a_book["duplicate"]) == (2, 2, 0)
    assert (b_book["shots"], b_book["new"], b_book["duplicate"]) == (2, 1, 1)


def test_a_broken_project_is_recorded_by_name_not_swallowed(tmp_path):
    bad = tmp_path / "bad.bdproj"
    bad.write_text("{not json", encoding="utf-8")
    report = csp.collect([bad])
    assert report["pool"] == []
    assert "error" in report["files"][0], "坏文件要具名记账，不许静默跳过"
