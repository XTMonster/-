"""门⑦ 的人审通道必须**真的能走通**：生成的表填完 → 写回 → 门转绿。

背景：`tools/holdout_review.py` 的两条子命令是给**两族对拍**设计的，
池通道只有一**个**标注族，于是人手里缺的不是工具而是"一张能直接打勾的表"。
`tools/knowledge/human_review_sheet.py` 补的就是这一张，判据与门逐字同一份
（`validate_entry` 的 Q7 冲突命中 或 `expect_movements` 非空）。

这条测试走完整条链：生成表 → 全部打勾 → `holdout_review.apply` 写回 →
`check_holdout` 的门⑦ 从 fail 变 pass。少了任何一环，"人审"就只是纸面要求。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_holdout, holdout_review  # noqa: E402
from tools.knowledge import human_review_sheet as HRS  # noqa: E402


def _q7_entry(idx: int) -> dict:
    """一条 Q7 冲突条目：`q` 点名了 `must` 禁止的那个取值。"""
    spec = "EMOTION_PACK:emotion=荒诞,intensity=high,forbid_movement=固定"
    return {
        "id": f"hq_{idx:04d}", "from_card": f"card_{idx}",
        "q": "情绪=荒诞；强度=high；运镜=固定",
        "must": [spec], "top1": [spec], "never": [],
        "annotator": {"model_id": "m", "family": "zhipu", "model_version": "0",
                      "prompt_sha256": "x"},
        "independence": "strong", "pilot": False,
    }


def test_sheet_sections_cover_every_entry_the_gate_wants_reviewed():
    entries = [_q7_entry(i) for i in range(1, 6)]
    markdown, total, written = HRS.render(entries)
    assert total == len(entries), "每一条 Q7 冲突条目都应进人审表"
    assert written == len(entries)
    for record in entries:
        assert f"## {record['id']} ·" in markdown
    # 表里必须写明"这条期望成立吗"与打勾位（人只看这一份就能判）
    assert markdown.count("采纳 A ？ [ ]") == len(entries)


def test_ticking_the_sheet_turns_gate_7_green(tmp_path):
    entries = [_q7_entry(i) for i in range(1, 6)]
    markdown, _total, _written = HRS.render(entries)
    ticked = markdown.replace("采纳 A ？ [ ]", "采纳 A ？ [x]")
    sheet = tmp_path / "sheet.md"
    sheet.write_text(ticked, encoding="utf-8")
    src = tmp_path / "entries.jsonl"
    src.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                   encoding="utf-8")

    decisions = holdout_review.parse_review_sheet(ticked)
    assert set(decisions) == {e["id"] for e in entries}, "打勾的节必须都被解析到"
    final = holdout_review.apply_review(
        entries, decisions, sorted(decisions))
    assert all(e["review"]["reviewed_by"] == "human" for e in final)
    assert all(e["review"]["verdict"] == "accepted" for e in final)

    status, detail = check_holdout.gate_human_review(
        needs=len(entries), reviewed=len(final), minimum=120)
    assert status == check_holdout.PASS, detail


def test_an_untouched_sheet_is_refused_not_silently_accepted(tmp_path):
    """漏填必须**拒绝写回**（`must_touch` 守卫），不许悄悄放过。"""
    entries = [_q7_entry(i) for i in range(1, 4)]
    blank = HRS.render(entries)[0]
    decisions = holdout_review.parse_review_sheet(blank)
    assert decisions == {}
    with pytest.raises(SystemExit):
        holdout_review.apply_review(entries, decisions, sorted(decisions) or ["hq_0001"])
