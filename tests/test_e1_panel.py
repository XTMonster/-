"""E1 的打分通道（`tools/knowledge/e1_panel.py`）：判据不变，但必须**可复算**。

为什么值得单独钉：链上 `quality.py --e1-reviews` 消费这份文件，而在本工具之前
它是由 `work/` 下两个**未跟踪**的临时脚本生成的——"链的输入来自一个不在库里的
脚本"意味着换代之后没人能重跑，也没人能对拍。这里的用例全部走**注入的桩**
（假索引 ＋ scripted 客户端），不碰网络。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.knowledge import Case  # noqa: E402
from tools.knowledge import e1_panel  # noqa: E402


class _Index:
    """最小可用的案例索引桩：`retrieve` + `search_zh` + `fingerprint`。"""

    def __init__(self, mapping, fingerprint="f" * 64):
        self.mapping = mapping
        self.search_zh = {case.case_id: f"线索 {case.case_id}"
                          for cases in mapping.values() for case in cases}
        self.fingerprint = fingerprint

    def retrieve(self, query, top_k=3):
        return self.mapping.get(query, [])[:top_k]


class _Client:
    def __init__(self, scores, *, boom=False):
        self.scores = scores
        self.boom = boom
        self.calls = 0

    def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=1):
        self.calls += 1
        if self.boom:
            raise RuntimeError("network down")
        return {"scores": [{"case_id": case_id, "score": self.scores.get(case_id, 1)}
                           for case_id in self.scores]}


def _cases(*ids):
    return [Case(case_id=case_id, title=f"t {case_id}", excerpt="e " * 5)
            for case_id in ids]


def test_rows_carry_the_index_fingerprint_and_a_panel_label():
    """E1 的每一行必须能自证"是哪一代语料、谁裁的"——否则 quality.py 只能记 stale。"""
    index = _Index({"q1": _cases("c1", "c2")}, fingerprint="a" * 64)
    clients = [("m-a", _Client({"c1": 5, "c2": 2})),
               ("m-b", _Client({"c1": 4, "c2": 3}))]
    rows = e1_panel.score_queries(index, ["q1"], clients, top_k=3)
    assert len(rows) == 2
    assert {row["case_id"] for row in rows} == {"c1", "c2"}
    for row in rows:
        assert row["cases_fingerprint"] == "a" * 64
        assert row["reviewed_by"] == "llm-panel" != "human"
        assert row["panel"] == ["m-a", "m-b"]
        assert len(row["prompt_sha256"]) == 64
    first = [row for row in rows if row["case_id"] == "c1"][0]
    assert first["score"] == 4.5            # 两条模型的**均值**，不是取其一


def test_a_broken_judge_is_recorded_as_missing_not_as_a_low_score():
    """一条模型挂了：那一格记 `None`，**绝不**记成低分。

    把失败写成 1 分，会把"基础设施挂了"记成"案例不相关"——那是把网络问题伪装成
    语料问题。所以失败侧在 `scores` 里是 `None`，分数只由**答上来的**模型给。
    两条模型都失败的那一镜**不进样本**（没有分数就没有分母）。
    """
    index = _Index({"q1": _cases("c1"), "q2": _cases("c2")})
    clients = [("m-a", _Client({"c1": 5, "c2": 5}, boom=True)),
               ("m-b", _Client({"c1": 5, "c2": 5}))]
    rows = e1_panel.score_queries(index, ["q1", "q2"], clients, top_k=3)
    assert len(rows) == 2
    assert all(row["scores"][0] is None for row in rows)
    assert all(row["score"] == 5.0 for row in rows), (
        "分数只由答上来的那条模型给；失败侧留 None，不是 1 分")
    assert clients[1][1].calls == 2, "另一条模型照旧被调用（失败是逐条的）"

    # 两条都挂：没有分数 ⇒ 不进样本（分母不靠"猜"）。
    both_down = [("m-a", _Client({}, boom=True)), ("m-b", _Client({}, boom=True))]
    assert e1_panel.score_queries(index, ["q1"], both_down, top_k=3) == []


def test_summary_reports_the_line_and_the_zero_denominator():
    rows = [{"score": 5.0}, {"score": 3.0}, {"score": 4.0}]
    summary = e1_panel.summarise(rows)
    assert summary == {"scored": 3, "relevant": 2, "value": 0.6667, "line": 0.70}
    assert e1_panel.summarise([])["value"] is None, "分母 0 不许算成 1.0"


def test_concurrency_changes_throughput_not_the_rows():
    """并发**只许改吞吐**：行序（查询序 × 案例序）与每一行的内容都要一模一样。

    为什么这条必须存在（2026-10-04 实测）：一次 64 查询 × 2 模型的判分串行要跑
    一小时以上，"换代之后重测 E1"在工程上就做不了。把并发打开是唯一的出路，
    但它**不能**顺手改掉判据或产物——否则两次测量不可对拍。
    """
    mapping = {f"q{number}": _cases("c1", "c2", "c3") for number in range(1, 9)}
    index = _Index(mapping, fingerprint="b" * 64)
    verdicts = {"c1": 5, "c2": 2, "c3": 4}
    clients = [("m-a", _Client(dict(verdicts))), ("m-b", _Client(dict(verdicts)))]
    serial = e1_panel.score_queries(index, list(mapping), clients, top_k=3,
                                    workers=1)
    parallel = e1_panel.score_queries(index, list(mapping), clients, top_k=3,
                                      workers=4)
    assert serial, "夹具必须真的产出打分，否则这条用例是空绿"
    assert serial == parallel
    assert [row["query"] for row in parallel] == [
        query for query in mapping for _ in range(3)], "并发不许打乱行序"


def test_project_queries_drop_the_plan_scope_blob_in_order(tmp_path):
    """查询的单位是**逐镜散文**；计划期那种把整段剧本塞进去的串必须丢掉。"""
    project = tmp_path / "project.bdproj"
    project.write_text(json.dumps({"scenes": [{"shots": [
        {"prompt": "剧本《第十四街区》：4 场、6 镜"},
        {"prompt": "米迦尔自信面朝画面左侧，推镜缓入"},
        {"prompt": "米迦尔自信面朝画面左侧，推镜缓入"},
        {"prompt": "留白镜头：伊恩望向偷盗者离去的方向"},
        {"prompt": "   "},
    ]}]}, ensure_ascii=False), encoding="utf-8")
    assert e1_panel.queries_from_project(project) == [
        "米迦尔自信面朝画面左侧，推镜缓入",
        "留白镜头：伊恩望向偷盗者离去的方向",
    ]
