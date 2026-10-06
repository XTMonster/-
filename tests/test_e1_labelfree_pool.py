"""`tools/knowledge/e1_labelfree_pool.py`：**去标签**候选池的 oracle（离线）。

为什么需要它（GPT-6A 的 RK-13 裁定 ＋ 主线核对，见
`docs/knowledge/RULING_CHECK_RK13.md`）：裁定把过关线定成 **≥135/192**，
依据是 **按标签取 top-N 再全组合**那个池子的 0.7448；而裁定同时禁止选择器看判分
⇒ 选择器只能用**去标签池**，它的 oracle **必须单独量**。

这些用例守住四件事：
① 池子**只**来自检索器的原始名次（判分一个字都进不去）；
② 每一组都要被**真的判一次**，且**逐个**落盘（选择器的评估集）；
③ 汇总走**两位评委**口径（P14-249：少一位不发分、也不算相关）；
④ 产物**自述**它是在哪一代索引上量的（换语料/换路由必须看得出来）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.knowledge import Case  # noqa: E402
from tools.knowledge import e1_labelfree_pool as probe  # noqa: E402


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


class _Index:
    """假索引：`retrieve` 只按**给定名次**回案例（没有任何判分字段可读）。"""

    def __init__(self, by_query, *, backend="hybrid", fingerprint="fp-1"):
        self.by_query = by_query
        self.backend = backend
        self.fingerprint = fingerprint
        self.asks = []

    def retrieve(self, query, top_k=3):
        self.asks.append((query, top_k))
        return [Case(case_id=cid, title="t" + cid, excerpt="e" + cid)
                for cid in list(self.by_query.get(query, []))[:int(top_k)]]

    def describe(self):
        return {"cases_backend": self.backend,
                "cases_index_fingerprint": self.fingerprint,
                "cases_clues": 3, "cases_clue_state": ""}


def _clients(score_a=5, score_b=5, *, boom_b=False):
    return [("m-a", _Client(score_a)), ("m-b", _Client(score_b, boom=boom_b))]


def test_the_pool_is_the_retriever_rank_order_and_nothing_else():
    """池子＝检索名次；判分给多少分都**不许**改变池子与枚举序。"""
    index = _Index({"q1": ["d3", "d1", "d2", "d4"]})
    low = probe.search(index, ["q1"], clients=_clients(1, 1), pool_size=4)
    high = probe.search(index, ["q1"], clients=_clients(5, 5), pool_size=4)
    assert low["pools"]["q1"] == ["d3", "d1", "d2", "d4"], "池子＝检索名次，不是标签序"
    assert [t["triple"] for t in low["triples"]] == [t["triple"] for t in high["triples"]], (
        "分数从 1 分变 5 分，池子与枚举序必须逐条不变")
    assert [t["pool_rank"] for t in low["triples"]] == [[0, 1, 2], [0, 1, 3],
                                                        [0, 2, 3], [1, 2, 3]]
    assert index.asks == [("q1", 4), ("q1", 4)], "每次取池都走 retrieve(query, top_k=pool)"


def test_every_judged_triple_is_recorded_and_counted():
    index = _Index({"q1": ["c1", "c2", "c3", "c4"], "q2": ["e1", "e2", "e3"]})
    out = probe.search(index, ["q1", "q2"], clients=_clients(), pool_size=4)
    assert out["triples_judged"] == len(out["triples"]) == 4 + 1, (
        "每条查询 C(pool,3)：C(4,3)=4 ＋ C(3,3)=1")
    for entry in out["triples"]:
        assert len(entry["triple"]) == 3 and len(entry["values"]) == 3
        assert entry["hits"] == sum(1 for v in entry["values"]
                                    if v is not None and v >= 4.0)


def test_one_missing_judge_means_no_score_and_not_relevant():
    """P14-249：**两位**评委才发分；少一位 ⇒ `values` 全 `None`、`hits=0`。"""
    index = _Index({"q1": ["c1", "c2", "c3"]})
    out = probe.search(index, ["q1"], clients=_clients(boom_b=True), pool_size=3)
    assert out["triples"][0]["values"] == [None, None, None]
    assert out["triples"][0]["hits"] == 0
    assert out["labelfree_oracle"] == 0.0 and out["three_of_three"] == 0


def test_the_oracle_is_the_best_group_and_the_delivered_shape_is_the_first_one():
    index = _Index({"q1": ["c1", "c2", "c3"]})
    #: 这一组里只有 c3 过 4.0：`_Client` 对所有 case 给同一个分，所以用两次不同的组
    #: 造出"最好 1 条"与"最好的那组"不同 —— 这里直接比的是**同一组**的两个读数口径。
    out = probe.search(index, ["q1"], clients=_clients(4, 4), pool_size=3)
    assert out["labelfree_oracle"] == out["delivered_first_triple"] == 1.0
    assert out["three_of_three"] == 1


def test_the_payload_says_which_index_generation_it_measured():
    index = _Index({"q1": ["c1", "c2", "c3"]}, backend="hybrid", fingerprint="fp-9")
    out = probe.search(index, ["q1"], clients=_clients(), pool_size=3)
    assert out["cases_backend"] == "hybrid" and out["cases_index_fingerprint"] == "fp-9"


def test_cli_writes_the_evidence_shape_offline(tmp_path):
    """`--scripted` 离线桩：CLI 能跑通并把 `triples` 写进产物（不碰网络）。"""
    queries = tmp_path / "q.jsonl"
    queries.write_text(json.dumps({"query": "zebra"}) + "\n", encoding="utf-8")
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "cases.jsonl").write_text("\n".join(
        json.dumps({"case_id": "c%d" % i, "title": "t",
                    "excerpt": ("zebra crossing %d" % i) if i <= 4 else ("beta %d" % i),
                    "case_type": "narrative", "source_ref": {}})
        for i in range(1, 11)), encoding="utf-8")
    stub = tmp_path / "stub.json"
    stub.write_text("{}", encoding="utf-8")
    out = tmp_path / "out.json"
    code = probe.main(["--queries", str(queries), "--cases", str(cases_dir),
                       "--scripted", str(stub), "--pool", "6",
                       "--out", str(out)])
    assert code == 0 and out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["queries"] == 1 and payload["panel"]
    assert set(payload) >= {"triples", "pools", "labelfree_oracle",
                            "delivered_first_triple", "three_of_three"}
    assert payload["pools"]["zebra"] == ["c1", "c2", "c3", "c4"], (
        "池子＝检索名次（BM25 只回命中项，序按分数、并列按 case_id）")
    assert payload["triples_judged"] == 4, "C(4,3)=4 组，逐组判"
    assert payload["labelfree_oracle"] is not None


def test_a_query_whose_pool_is_too_small_is_counted_not_silently_zero():
    """池子不足 3 条 ⇒ 判不了组：**排到均值之外并计数**，不许当成 0 分混进分母。"""
    index = _Index({"q1": ["c1", "c2"], "q2": ["d1", "d2", "d3"]})
    out = probe.search(index, ["q1", "q2"], clients=_clients(), pool_size=3)
    assert out["queries_requested"] == 2 and out["queries"] == 1
    assert out["queries_without_a_triple"] == 1
    assert out["pools"]["q1"] == ["c1", "c2"] and out["triples_judged"] == 1
