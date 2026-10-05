"""P6 A 路：按来源的**可引用量**定配额（不是拍一个数）。

归因证据（`work/_case_reject_diag.py`）：v4 案例层 `reject_ratio 0.0753` 全部来自
`quote_gate` 117 条，其中**两份 MIT OCW 讲义 PDF 占 34 条**——讲义多是标题/条目，
没有可引用的句子。根因是生成 `knowledge/sources.v4.yaml` 时给**所有**来源统一
`chunk_budget: 20`，没有按"这一段能不能引用"区分。

所以配额的依据是**实测的可引用段数**：`pick_excerpt(segment) is not None` 的段数。
规则（写死）：

* 配额 ＝ 可引用段数（向下有 `MIN_BUDGET` 兜底、向上有 `MAX_BUDGET` 封顶）；
* **可引用段为 0 的来源**给 `MIN_BUDGET`（不是 0——那会让来源整个消失，
  而"这个来源不可引用"本身是要被看见的事实，不是被抹掉）；
* 每个来源的配额旁**必须记依据**（`budget_basis`），否则这条配额是拍脑袋来的。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import allocate_budgets_v4 as ab  # noqa: E402


def test_the_budget_follows_the_measured_quotable_count():
    rows = {"a": 12, "b": 0, "c": 3}
    budgets = ab.allocate(rows, min_budget=1, max_budget=20)
    assert budgets["a"] == 12
    assert budgets["c"] == 3
    #: 可引用段为 0 也要给下限——"不可引用"是要被看见的事实，不是被抹掉。
    assert budgets["b"] == 1


def test_the_budget_is_capped_and_floored():
    rows = {"a": 999, "b": 0}
    budgets = ab.allocate(rows, min_budget=2, max_budget=10)
    assert budgets["a"] == 10 and budgets["b"] == 2


def test_every_budget_carries_its_basis():
    rows = {"a": 5}
    report = ab.allocate_with_basis(rows, min_budget=1, max_budget=20)
    assert report["a"]["budget"] == 5
    assert report["a"]["basis"] == "quotable_segments:5"


def test_allocation_is_deterministic():
    rows = {"a": 3, "b": 7}
    assert ab.allocate(rows) == ab.allocate(rows)
