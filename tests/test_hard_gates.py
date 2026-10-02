"""`tools/knowledge/hard_gates.py`：RK-13 的硬门按 id 判。

这份文件要钉住的是 2026-10-02 发现的真实缺陷：验收链跑的是
`tools/holdout_score.py`，它的报告里**只有** `Q1..Q7`；而 §2.3b/§4.1b 里属于
`tools/knowledge/quality.py` 的 **Q0 与 E3**（"经验越权率 = 0"是一条硬门）
因此从来没有被链量过。下面第 4 条用例喂的就是那份真实报告的 id 集合——
它以前会被当成"没什么可判"，现在必须判失败。

2026-10-03 追加：`Q5` 与 `E1` 从软项**归位为门**。它们以前只能记 `not_measured`
（链上没有输入），而规格一直把它们写成门（§2.3b 的 `E1 ≥70%`、§4.1 的
`Q5 ≥80%` ＋ §4.1b 的分母下界）。链上现在喂真实模型运行的
`export/shots.json` ＋ `audit_log.jsonl` 与录档的面板评分，所以"这次量不到"
必须算 RK-13 未通过，不能继续挂在 `SOFT_IDS` 里。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._holdout_index import write_index  # noqa: E402
from tools.knowledge import hard_gates, quality  # noqa: E402


def make_report(**overrides):
    """硬门全 pass ＋ 软项如实记 `not_measured` 的报告；`overrides` 逐条改写。"""
    metrics = [{"id": ident, "status": overrides.get(ident, "pass")}
               for ident in hard_gates.HARD_IDS
               if ident not in overrides.get("__drop__", ())]
    for ident in hard_gates.SOFT_IDS:
        metrics.append({"id": ident, "status": "not_measured"})
    return {"metrics": metrics}


def test_all_hard_gates_passing_is_a_pass_and_the_soft_ones_are_recorded():
    result = hard_gates.verdict(make_report())
    assert result["passed"] is True
    assert result["missing"] == [] and result["red"] == []
    # 软项必须被如实报出来：读者要能一眼看到"这几条这次量不到"。
    # 2026-10-03：只剩 E2——Q5 / E1 已经归位成门（见下面两条用例）。
    assert result["soft"] == {"E2": "not_measured"}


def test_a_missing_hard_id_is_a_failure_not_an_absence():
    """**缺证据不是通过**（§4.1b 硬规则 1）：报告里没有 E3 也算不合格。"""
    result = hard_gates.verdict(make_report(__drop__=("E3",)))
    assert result["passed"] is False
    assert result["missing"] == ["E3"]


def test_a_not_measured_hard_id_is_a_failure():
    result = hard_gates.verdict(make_report(E3="not_measured"))
    assert result["passed"] is False
    assert result["red"] == ["E3"]


def test_the_report_the_chain_used_to_produce_is_rejected():
    """回归钉：链以前写出的那份报告（只有 Q1..Q7）必须判失败。

    这不是"造出来的反例"——它就是 2026-10-02 之前每个
    `docs/evidence/<run-id>/knowledge_quality.json` 的真实 id 集合。
    """
    old = {"metrics": [{"id": ident, "status": "pass"} for ident in
                       ("Q1", "Q2", "Q3", "Q4", "Q6a", "Q6b", "Q7")]}
    result = hard_gates.verdict(old)
    assert result["passed"] is False
    assert set(result["missing"]) == {"Q0", "Q4_pre_required_edges_exist",
                                     "E3", "E3_cases", "Q5", "E1"}


def test_the_two_gates_the_spec_names_are_hard_not_soft():
    """`Q5` / `E1` 是规格里的门，不许因为"以前没输入"就藏在软项里。

    §2.3b 把 `E1 ≥ 70%` 写成经验层的门（`E2` 只记录、不设门），§4.1 把
    `Q5 ≥ 80%` 写成 RK-13 的判据、§4.1b 给了它的分母下界与"分母为 0 一律
    判失败"。链上现在两条都有真实输入（`--shots`/`--audit-log` 与
    `--e1-reviews`），所以"这条这次量不到"不再是软项，而是 RK-13 未通过。
    """
    assert "Q5" in hard_gates.HARD_IDS
    assert "E1" in hard_gates.HARD_IDS
    assert set(hard_gates.SOFT_IDS) == {"E2"}, (
        "§2.3b 只对 E2 写了'记录、不设门'；别的条目进软项就是把门藏起来")


def test_a_red_or_unmeasured_gate_counts_as_rk13_failed():
    """反例两条：E1 量到但不达标、Q5 这次量不到——两种都必须判 RK-13 未通过。"""
    red = hard_gates.verdict(make_report(E1="fail"))
    assert red["passed"] is False and red["red"] == ["E1"]
    unmeasured = hard_gates.verdict(make_report(Q5="not_measured"))
    assert unmeasured["passed"] is False and unmeasured["red"] == ["Q5"]


def test_soft_ids_are_never_hard_and_vice_versa():
    assert set(hard_gates.HARD_IDS).isdisjoint(hard_gates.SOFT_IDS)
    result = hard_gates.verdict(make_report())
    assert set(result["soft"]) == set(hard_gates.SOFT_IDS)


def test_the_cli_exit_code_says_pass_fail_or_unreadable(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(make_report(), ensure_ascii=False), encoding="utf-8")
    assert hard_gates.main(["--report", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(make_report(E3="fail"), ensure_ascii=False),
                   encoding="utf-8")
    assert hard_gates.main(["--report", str(bad)]) == 1

    # 读不到 / 不是报告 ⇒ 2（缺证据），绝不等于"过"。
    assert hard_gates.main(["--report", str(tmp_path / "nope.json")]) == 2
    not_a_report = tmp_path / "other.json"
    not_a_report.write_text('{"hello": 1}', encoding="utf-8")
    assert hard_gates.main(["--report", str(not_a_report)]) == 2


def test_the_hard_list_matches_what_the_reporter_emits(tmp_path):
    """清单不许漂：真的跑一次 `quality.build_report`，两边的 id 必须一一对应。

    与 `quality.py` 反着来（例如它哪天把 E3 改名或删掉），这条当场红——而不是
    等到链上某个硬门悄悄变成"报告里没有这一条"。
    """
    first = json.loads((ROOT / "fixtures" / "knowledge_holdout.jsonl")
                       .read_text(encoding="utf-8").splitlines()[0])
    holdout = tmp_path / "holdout.jsonl"
    holdout.write_text(json.dumps(first, ensure_ascii=False) + "\n", encoding="utf-8")
    nodes, edges = write_index(tmp_path, [first])
    report = quality.build_report(
        run_id="idcheck", holdout=holdout, nodes=nodes, edges=edges,
        manifest=pathlib.Path("knowledge") / "hypergraph.manifest.json",
        rejects=pathlib.Path("knowledge") / "hypergraph.rejects.jsonl",
        cases=None, shots=None, e1_reviews=None, top_k=3, token_limit=2000)
    ids = {str(item["id"]) for item in report["metrics"]}
    expected = set(hard_gates.HARD_IDS) | set(hard_gates.SOFT_IDS)
    assert ids == expected, (
        "quality.py 的 metric id 与 hard_gates 的清单漂了："
        f"只在报告里 {sorted(ids - expected)}，只在清单里 {sorted(expected - ids)}")


def test_a_report_with_no_metrics_is_unreadable_not_a_pass(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"metrics": []}), encoding="utf-8")
    result = hard_gates.verdict(json.loads(empty.read_text(encoding="utf-8")))
    assert result["passed"] is False
    assert set(result["missing"]) == set(hard_gates.HARD_IDS)
    with pytest.raises(OSError):            # 文件不在
        hard_gates.load_report(tmp_path / "missing_metrics.json")
    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text('{"metrics": {}}', encoding="utf-8")
    with pytest.raises(ValueError):          # 有 metrics 但不是数组
        hard_gates.load_report(wrong_shape)
