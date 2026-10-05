"""第三方裁定（Kimi K3）代替用户做人工审核 —— 用户 2026-10-06 的授权在机器上的形态。

钉住四件事：

1. **不冒充 human**：记录写 `reviewed_by: "third-party"`，并且 `source` 里带
   `authorized_by` —— "凭什么是它来裁"可追；
2. **`error` 不是判决**：不落记录（`holdout_review_llm` 上有实测先例：把 429 写成 amended）；
3. **门⑦ 认它要带佐证**：`check_holdout.review_class()` 只认带 `source.model` 与
   `source.prompt_sha256` 的 `third-party` 记录；缺了就不算一条裁决记录；
4. **对拍表只列分歧**：与既有 llm-panel 记录同 verdict 的不进表。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_holdout  # noqa: E402
from tools import holdout_review_third_party as tp  # noqa: E402


def _source():
    return {"model": "kimi-k3", "prompt_sha256": "deadbeef",
            "authorized_by": tp.AUTHORIZED_BY, "tool": "holdout_review_third_party"}


def _entry(ident, *, movements=True, review=None):
    entry = {"id": ident, "from_card": "card_1", "q": {}, "must": []}
    if movements:
        entry["expect_movements"] = ["static"]
    if review is not None:
        entry["review"] = review
    return entry


def test_the_tag_is_not_human_and_the_authorisation_travels_with_every_record():
    assert tp.THIRD_PARTY_TAG == "third-party" != "human"
    assert "user-2026-10-06" in tp.AUTHORIZED_BY
    record = tp.build_record(_entry("hq_1"), {"verdict": "accepted", "reason": "ok"},
                             _source())
    assert record["review"]["reviewed_by"] == "third-party"
    assert record["review"]["source"]["authorized_by"] == tp.AUTHORIZED_BY
    assert record["action"] == "keep"


def test_the_action_map_matches_the_panel_reviewer():
    for verdict, action in (("accepted", "keep"), ("rejected", "drop"),
                            ("amended", "flag")):
        record = tp.build_record(_entry("hq_2"), {"verdict": verdict}, _source())
        assert record["action"] == action


def test_an_error_is_not_a_verdict_so_no_record_is_written():
    for decision in ({"verdict": "error", "reason": "TimeoutError"}, {"reason": "x"}):
        record = tp.build_record(_entry("hq_3"), decision, _source())
        assert record["action"] == "retry"
        assert "review" not in record


def test_only_entries_that_need_a_verdict_are_selected():
    entries = [_entry("a"), _entry("b", movements=False), _entry("c")]
    picked = [str(e["id"]) for e in tp.select_third_party(entries)]
    assert picked == ["a", "c"], "b 不需要裁决（没有 expect_movements / forbid_*）"


def test_a_second_run_does_not_re_judge_what_third_party_already_signed():
    entries = [_entry("a"), _entry("b", review={"reviewed_by": "third-party",
                                                "verdict": "accepted"})]
    assert [e["id"] for e in tp.select_third_party(entries)] == ["a"]
    # 但 llm-panel 的记录**不**阻止第三方去裁——人审那一层要覆盖完整的一批。
    entries = [_entry("a", review={"reviewed_by": "llm-panel", "verdict": "accepted"})]
    assert [e["id"] for e in tp.select_third_party(entries)] == ["a"]
    assert tp.select_third_party(entries, include_reviewed=False) == []


def test_the_gate_accepts_third_party_only_with_corroboration():
    who, why = check_holdout.review_class(
        {"reviewed_by": "third-party", "verdict": "accepted", "source": _source()})
    assert who == "third-party" and why == ""
    # 没佐证、或佐证不全 ⇒ 不算一条裁决记录，并把原因如实报出来。
    who, why = check_holdout.review_class({"reviewed_by": "third-party",
                                           "verdict": "accepted"})
    assert who is None and "source.model" in why
    who, why = check_holdout.review_class(
        {"reviewed_by": "third-party", "verdict": "accepted",
         "source": {"model": "kimi-k3"}})
    assert who is None and "prompt_sha256" in why


def test_the_gate_still_refuses_an_unknown_reviewer():
    who, why = check_holdout.review_class({"reviewed_by": "vibes",
                                           "verdict": "accepted"})
    assert who is None and "third-party" in why


def test_the_gate_counts_only_the_classes_it_is_told_to_accept():
    classes = {"human": 0, "llm-panel": 210, "third-party": 212}
    status, detail = check_holdout.gate_human_review(
        212, classes, 120, classes=("human", "llm-panel", "third-party"))
    assert status == check_holdout.PASS
    assert detail["human_reviewed"] == 422
    assert detail["reviewed_by_class"]["third-party"] == 212
    # 默认口径（只认 human）不变——它照旧不通，这条是协议原样。
    status, _ = check_holdout.gate_human_review(212, classes, 120)
    assert status == check_holdout.FAIL


def test_the_disagreement_sheet_lists_only_real_disagreements():
    entries = {"hq_1": _entry("hq_1", review={"reviewed_by": "llm-panel",
                                              "verdict": "accepted",
                                              "reason": "r"}),
               "hq_2": _entry("hq_2", review={"reviewed_by": "llm-panel",
                                              "verdict": "rejected",
                                              "reason": "r"})}
    rows = [{"id": "hq_1", "review": {"verdict": "accepted"}},
            {"id": "hq_2", "review": {"verdict": "amended"}}]
    lines = tp.compare_sheet(rows, entries)
    assert len(lines) == 1 and "hq_2" in lines[0]


def test_merging_writes_the_review_back_and_drops_only_the_rejected():
    """合并语义与 `holdout_review_llm` 一致：keep/flag 写回 review，drop 剔除，retry 不动。"""
    entries = [_entry("a"), _entry("b"), _entry("c"), _entry("d")]
    rows = [
        {"id": "a", "action": "keep", "review": {"reviewed_by": "third-party",
                                                 "verdict": "accepted"}},
        {"id": "b", "action": "drop", "review": {"reviewed_by": "third-party",
                                                 "verdict": "rejected"}},
        {"id": "c", "action": "flag", "review": {"reviewed_by": "third-party",
                                                 "verdict": "amended"}},
        {"id": "d", "action": "retry"},          # 缺证据 ⇒ 不写 review
    ]
    kept, dropped = tp.merge_entries(entries, rows)
    assert [item["id"] for item in kept] == ["a", "c", "d"]
    assert dropped == ["b"]
    by_id = {item["id"]: item for item in kept}
    assert by_id["a"]["review"]["verdict"] == "accepted"
    assert by_id["c"]["panel_disagreement"] is True
    assert "review" not in by_id["d"]


def test_a_one_to_one_dispute_is_kept_and_flagged_not_silently_dropped():
    """第三方判 rejected、但条目上原本是 llm-panel 的 accepted ⇒ **分歧**，保留并标记。

    为什么这条重要（2026-10-06 实测）：那 2 条第三方 rejected 的条目**都**挂着 llm-panel 的
    accepted/amended；其中 `hq_1057` 还是卡 `gen_cine_0247` 的**唯一**一条期望——按一方意见
    删掉，门⑥ 的 `missing_cards` 立刻变红。1:1 的分歧不该有这种后果。
    只有"两边都判 rejected"（或对面没有记录）才真剔除。
    """
    disputed = _entry("a", review={"reviewed_by": "llm-panel", "verdict": "accepted"})
    agreed = _entry("b", review={"reviewed_by": "llm-panel", "verdict": "rejected"})
    fresh = _entry("c")                      # 对面本来就没有记录
    rows = [{"id": "a", "action": "drop", "review": {"reviewed_by": "third-party",
                                                     "verdict": "rejected"}},
            {"id": "b", "action": "drop", "review": {"reviewed_by": "third-party",
                                                     "verdict": "rejected"}},
            {"id": "c", "action": "drop", "review": {"reviewed_by": "third-party",
                                                     "verdict": "rejected"}}]
    kept, dropped = tp.merge_entries([disputed, agreed, fresh], rows)
    assert [item["id"] for item in kept] == ["a"], "只有 1:1 的那条被保留"
    assert kept[0]["panel_disagreement"] is True
    assert kept[0]["review"]["reviewed_by"] == "third-party"
    assert dropped == ["b", "c"], "两边一致 reject、或对面没记录 ⇒ 真剔除"


def test_the_default_adjudication_channel_is_gpt6a_with_thinking_maxed(monkeypatch):
    """用户 2026-10-06：“**gpt6A 只能用于人工裁决和执行计划书写**”＋“**思考强度拉到最大**”。

    人工裁决正是那两条允许用途之一 ⇒ 默认通道从 `kimi-k3` 换成中转站 `gpt-6-astra`；
    `RelayClient` 默认带 `reasoning_effort=max`（实测同一问题 reasoning 40 → 1034 token）。
    """
    from tools.kb_fetch import llm

    client = llm.make_client("relay", "gpt-6-astra")
    assert isinstance(client, llm.RelayClient)
    assert client.reasoning_effort == "max"
    assert "reasoning_effort=max" in client.decode_tag
    # 显式关掉也能关（万一某天要对照）。
    assert llm.RelayClient("gpt-6-astra", reasoning_effort="low").reasoning_effort == "low"
