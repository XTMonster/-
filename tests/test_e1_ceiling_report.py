"""`tools/knowledge/e1_ceiling_report.py`：把 R3 的"完美重排上限"变成可复算的量。

钉住四件事：

1. 上限的**公式**：`mean(min(top_k, 每条查询的相关行数) / top_k)`；
2. 判据与 `e1_panel`／`e1_baseline_summary` **同源**（阈值 4.0）——
   这条是红线：工具里改一个字都算挪门限；
3. `e1_top_k_rows` 取的是**文件前 top_k 行**（未重排文件里块内就是检索序）；
4. 多文件要报**极差**——单点值不作结论（0.7760 vs 0.7188 那件事的机制化）。

反面对照也在：3.5 分**不**算相关、缺 `score` 时按 `scores` 均值、`top_k<1` 抛错。
"""

from __future__ import annotations

import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import e1_panel  # noqa: E402
from tools.knowledge import e1_baseline_summary as ebs  # noqa: E402
from tools.knowledge import e1_ceiling_report as ecr  # noqa: E402


def _row(query: str, score):
    row = {"query": query}
    if score is not None:
        row["score"] = score
        row["scores"] = [score, score]
    return row


def test_threshold_is_shared_with_the_panel_and_the_baseline():
    # 红线：三处的"相关"门限必须是同一个数。
    assert ecr.RELEVANT == e1_panel.RELEVANT == ebs.RELEVANT == 4.0


def test_ceiling_is_the_mean_of_min_top_k_over_relevant_counts():
    rows = []
    # 查询 A：4 条相关（封顶到 top_k=3）
    rows += [_row("A", 5.0), _row("A", 4.5), _row("A", 4.0), _row("A", 4.0), _row("A", 1.0)]
    # 查询 B：1 条相关
    rows += [_row("B", 4.0), _row("B", 2.0), _row("B", 1.0)]
    # 查询 C：0 条相关
    rows += [_row("C", 3.5), _row("C", 1.0)]
    page = ecr.report(rows, top_k=3)
    assert page["queries"] == 3
    assert page["relevant"] == 5
    assert page["queries_with_k_or_more"] == 1
    assert page["queries_with_none"] == 1
    # (min(3,4) + min(3,1) + min(3,0)) / (3*3) = (3+1+0)/9
    assert page["ceiling"] == pytest.approx(4 / 9, abs=1e-6)
    assert page["per_query_relevant"] == {"A": 4, "B": 1, "C": 0}


def test_three_point_five_is_not_relevant_and_four_is():
    rows = [_row("Q", 3.5), _row("Q", 4.0)]
    page = ecr.report(rows, top_k=3)
    assert page["relevant"] == 1


def test_e1_top_k_rows_reads_the_first_k_rows_in_file_order():
    rows = [_row("Q", 1.0), _row("Q", 1.0), _row("Q", 5.0), _row("Q", 5.0)]
    page = ecr.report(rows, top_k=3)
    # 前三行只有 1 条相关 ⇒ 1/3；但整块有 2 条相关 ⇒ 上限 2/3。
    assert page["e1_top_k_rows"] == pytest.approx(1 / 3, abs=1e-6)
    assert page["ceiling"] == pytest.approx(2 / 3, abs=1e-6)


def test_missing_score_falls_back_to_the_mean_of_judges():
    rows = [{"query": "Q", "scores": [3, 5]}, {"query": "Q", "scores": [2, 2]}]
    page = ecr.report(rows, top_k=3)
    # 3 与 5 的均值是 4.0 ⇒ 算相关；2 与 2 的均值 2.0 ⇒ 不算。
    assert page["relevant"] == 1


def test_an_all_scored_row_without_any_number_is_not_relevant():
    rows = [{"query": "Q", "scores": [None, None]}, {"query": "Q", "score": None}]
    page = ecr.report(rows, top_k=3)
    assert page["relevant"] == 0
    assert page["ceiling"] == 0.0


def test_top_k_below_one_is_refused():
    with pytest.raises(ValueError):
        ecr.report([_row("Q", 5.0)], top_k=0)


def test_range_across_repeats_is_reported(tmp_path, monkeypatch):
    import json

    def write(name, scores):
        path = tmp_path / name
        with open(path, "w", encoding="utf-8") as handle:
            for query, score in scores:
                handle.write(json.dumps({"query": query, "score": score,
                                         "scores": [score, score]}) + "\n")
        return path

    # 两次跑只差**两条**候选的评分（4.0 ↔ 3.5），但那条查询跨过"≥3 相关"的门。
    base = [("A", 5.0), ("A", 4.0), ("A", 4.0), ("A", 4.0)]
    run1 = write("run1.jsonl", base)
    run2 = write("run2.jsonl", base[:2] + [("A", 3.5), ("A", 3.5)])

    import io
    import contextlib
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = ecr.main(["--json", "--top-k", "3", str(run1), str(run2)])
    assert code == 0
    payload = json.loads(captured.getvalue())
    assert payload["range"]["ceiling"]["range"] == pytest.approx(1 / 3, abs=1e-6)
    assert payload["range"]["queries_with_k_or_more"]["range"] == 1
