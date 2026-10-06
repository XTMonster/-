"""`tools/knowledge/e1_triple_search.py`：**组装**三元组的搜索器（离线）。

为什么需要它（GPT-6A 2026-10-06 的挑战，见
`docs/evidence/20261006-gpt6a-round2/answers/full_head.md` 第 3 条）：
本仓把"标签分最高的 3 条重新盲评 = 0.4583"当成当前协议下的**可达上界**，
但那个 3 条本身就是一种选择方式 ⇒ 它只是"已试方法"的成绩，**不是组合最优**。
要证"不可达"必须**在 C=3 尺子上真的搜三元组**。

这些用例守住：① 搜索确实对**组装出来的**三元组判分（不是复用原标签）；
② 汇总用**两位评委**口径（P14-249：少一位不算分、也不算相关）；
③ 分母与判分语境与 `e1_panel` 同源。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import e1_triple_search as probe  # noqa: E402


class _Client:
    """按 `user` 串里出现的 case_id 给分；同一次调用里所有 case 给同一个分数。"""

    def __init__(self, score, *, boom=False):
        self.score = score
        self.boom = boom
        self.calls = 0
        self.seen = []

    def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=1):
        self.calls += 1
        if self.boom:
            raise RuntimeError("network down")
        ids = [line.split("｜")[0].strip()
               for line in user.splitlines() if "｜" in line]
        self.seen.append(tuple(ids))
        return {"scores": [{"case_id": cid, "score": self.score} for cid in ids]}


def _rows(query, ids, score=4.0):
    return [{"query": query, "case_id": cid, "score": score, "excerpt": "x"}
            for cid in ids]


def test_candidate_triples_are_deterministic_and_bounded():
    rows = _rows("q1", ["c%d" % i for i in range(8)])
    combos = probe.candidate_triples(rows, pool_per_query=4, max_triples=0)
    assert combos == [("c0", "c1", "c2"), ("c0", "c1", "c3"), ("c0", "c2", "c3"),
                      ("c1", "c2", "c3")], "全组合：C(4,3)=4，且按枚举序"
    capped = probe.candidate_triples(rows, pool_per_query=8, max_triples=3)
    assert capped == [("c0", "c1", "c2"), ("c0", "c1", "c3"), ("c0", "c1", "c4")], (
        "超过上限时按枚举序截断（确定、可复现）")


def test_search_judges_assembled_triples_not_the_original_labels():
    """原标签说全都不相关；组装出来的三元组照样要被**真的判一次**。"""
    rows = _rows("q1", ["c1", "c2", "c3"], score=1.0)
    cases = {cid: {"title": "t" + cid, "excerpt": "e"} for cid in ("c1", "c2", "c3")}
    #: **两位**评委（P14-249 的口径）：只给一位时 `judge_triple` 不发分。
    a, b = _Client(5), _Client(5)
    out = probe.search(rows, cases=cases, clients=[("m-a", a), ("m-b", b)],
                       pool_per_query=3, max_triples=0)
    assert (a.calls, b.calls) == (1, 1), "必须真的各调一次（原标签是 1 分，不许拿它当结论）"
    assert a.seen == [("c1", "c2", "c3")]
    assert out["three_of_three"] == 1
    assert out["E1_best_of_search"] == 1.0


def test_a_single_judge_does_not_produce_a_score():
    """P14-249：只有一位评委给分的行**不发分**，也**不算相关**。"""
    rows = _rows("q1", ["c1", "c2", "c3"])
    cases = {cid: {"title": "t", "excerpt": "e"} for cid in ("c1", "c2", "c3")}
    out = probe.search(rows, cases=cases,
                       clients=[("m-a", _Client(5)), ("m-b", _Client(5, boom=True))],
                       pool_per_query=3, max_triples=0)
    assert out["three_of_three"] == 0
    assert out["E1_best_of_search"] == 0.0
    assert out["distribution"][0] == 1


def test_the_summary_counts_every_query_that_has_any_triple():
    rows = _rows("q1", ["c1", "c2", "c3"]) + _rows("q2", ["c4", "c5", "c6"])
    cases = {cid: {"title": "t", "excerpt": "e"}
             for cid in ("c1", "c2", "c3", "c4", "c5", "c6")}
    out = probe.search(rows, cases=cases, clients=[("m-a", _Client(4)), ("m-b", _Client(4))],
                       pool_per_query=3, max_triples=0)
    assert out["queries"] == 2 and out["triples_judged"] == 2
    assert out["E1_best_of_search"] == 1.0


def test_cli_writes_the_evidence_shape_offline(tmp_path):
    """CLI 必须能**完全不碰网络**地跑（`--scripted`），产物形状可复算。"""
    labels = tmp_path / "labels.jsonl"
    labels.write_text("\n".join(json.dumps(r) for r in _rows("q1", ["c1", "c2", "c3"])),
                      encoding="utf-8")
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "cases.jsonl").write_text("\n".join(
        json.dumps({"case_id": "c%d" % i, "title": "t", "excerpt": "e",
                    "case_type": "narrative", "source_ref": {}})
        for i in (1, 2, 3)), encoding="utf-8")
    stub = tmp_path / "stub.json"
    stub.write_text("{}", encoding="utf-8")
    out = tmp_path / "out.json"
    code = probe.main(["--labels", str(labels), "--cases", str(cases_dir),
                       "--pool-per-query", "3", "--max-triples", "0",
                       "--scripted", str(stub), "--limit", "1", "--out", str(out)])
    assert code == 0 and out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["labels"] == str(labels) and payload["panel"]
