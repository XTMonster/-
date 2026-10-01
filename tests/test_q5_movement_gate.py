"""Q5 运镜命中的**第一步**（§4.1b）：夹具下界不足时不许静默消失。

Q5 的分母是"真实模型跑出来的、与本条 `q` 等价的镜头数"，所以它的夹具侧先有一条
下界：**带 `expect_movements` 的条目 ≥ 30**。实测（2026-10-02，2840 条 oracle）
这个字段是 **0 条**——池通道的标注模板只写 `q/must/top1/never`（旧的
`holdout_gen` 写过，换通道之后就没了）。修 P14-5 之前，`tools/knowledge/quality.py`
**根本没有 Q5 这一项**：报告里少一条，看起来像是"没有这条要求"。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import quality as Q  # noqa: E402


def _entry(ident: str, movements=None) -> dict:
    row = {"id": ident, "from_card": "c1", "q": "情绪=荒诞；强度=high",
           "must": ["EMOTION_PACK:emotion=荒诞,intensity=high"], "top1": [], "never": []}
    if movements:
        row["expect_movements"] = list(movements)
    return row


def test_a_fixture_without_expect_movements_is_not_measured_with_the_reason():
    """夹具里一条都没有 → `not_measured`，而且**必须点名缺什么、缺多少**。"""
    report = Q.q5_movement_hit([_entry("hq_0001"), _entry("hq_0002")])
    assert report["status"] == Q.NA
    assert report["numerator"] == 0
    assert "expect_movements" in report["note"]
    assert str(Q.MIN_Q5_FIXTURE_ITEMS) in report["note"]


def test_below_the_floor_still_does_not_pass():
    """**硬规则 1 的边界**：29 条也不许判通过——差一条就是差一条。"""
    rows = [_entry("hq_%04d" % i, ["fixed"]) for i in range(Q.MIN_Q5_FIXTURE_ITEMS - 1)]
    report = Q.q5_movement_hit(rows)
    assert report["status"] == Q.NA
    assert report["numerator"] == Q.MIN_Q5_FIXTURE_ITEMS - 1


def test_at_the_floor_it_says_what_is_still_missing():
    """够了下界也只是"夹具侧够"：运行侧的 join 没接上就仍然不是 pass。"""
    rows = [_entry("hq_%04d" % i, ["fixed"]) for i in range(Q.MIN_Q5_FIXTURE_ITEMS)]
    report = Q.q5_movement_hit(rows)
    assert report["status"] == Q.NA
    assert report["numerator"] == Q.MIN_Q5_FIXTURE_ITEMS
    assert "运行侧" in report["note"]


def test_the_shipped_oracle_reports_q5_instead_of_silently_omitting_it():
    """入库的那份 oracle 必须**出现**在报告里（哪怕只是 not_measured）。"""
    from tools.holdout_score import load_holdout
    entries = load_holdout(ROOT / "fixtures" / "knowledge_holdout.jsonl")
    report = Q.q5_movement_hit(entries)
    assert report["id"] == "Q5"
    assert report["status"] in (Q.NA, Q.PASS, Q.FAIL)
