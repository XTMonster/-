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
        #: `read_search_zh` 的第二个返回值：空串 = 线索可用。
        self.search_zh_reason = ""
        #: `CaseIndex` 的自述：请求的臂（`path_label`）与**实际干活**的后端（`effective`）。
        self.effective = "hybrid"
        self.reason = ""

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


def test_every_scored_row_says_which_retrieval_path_produced_it(tmp_path):
    """每行都要自带**检索路径**（`hybrid` / `lexical`）——否则两条路的读数会混账。

    为什么值得一条判据：`--adapter lexical` 换的是**替谁做检索**（零依赖适配器
    vs 产品现行的 BM25），而 E1 的分母是"返回的案例"。一份证据里如果分不清
    哪些行来自哪条路，"适配器有没有用"就说不清——这正是本项目反复吃过的
    "同一事实两个口径"的形状。
    """
    index = _Index({"q1": _cases("c1")})
    index.path_label = "hybrid"
    rows = e1_panel.score_queries(index, ["q1"], [("stub", _Client({"c1": 5}))],
                                 top_k=1, workers=1)
    assert rows, "夹具必须真的产出打分，否则这条用例是空绿"
    assert {row["retrieval_path"] for row in rows} == {"hybrid"}, rows


def test_every_scored_row_says_what_state_the_clue_layer_was_in():
    """**2026-10-05 的实缺陷**：v4 案例层整份缺中文线索时，三臂 E1 从 0.20 塌到
    0.0065，而产物里**没有一行**写着原因——每行只有一个空的 `zh`，读的人只看到
    "分数很低"。`read_search_zh` 本来就把原因算出来了（`search_zh_missing`），
    是消费侧把它丢掉的。判分记录现在必须自证"这一代索引的线索层是什么状态"。
    """
    index = _Index({"q1": _cases("c1", "c2")})
    index.search_zh_reason = "search_zh_missing"
    rows = e1_panel.score_queries(index, ["q1"], [("stub", _Client({"c1": 5, "c2": 1}))],
                                  top_k=2, workers=1)
    assert rows, "夹具必须真的产出打分，否则这条用例是空绿"
    assert {row["clue_state"] for row in rows} == {"search_zh_missing"}, rows
    assert {row["clues"] for row in rows} == {len(index.search_zh)}

    #: 线索可用时它就是空串——别把"正常"也写成某个具名原因。
    healthy = _Index({"q1": _cases("c1")})
    rows = e1_panel.score_queries(healthy, ["q1"], [("stub", _Client({"c1": 5}))],
                                  top_k=1, workers=1)
    assert {row["clue_state"] for row in rows} == {""}


def test_every_scored_row_says_which_backend_actually_did_the_retrieval():
    """请求的臂 ≠ 实际干的活。**2026-10-05 实测**：`LightRAGIndex.search` 每次
    `asyncio.run()`（新建一条事件循环），而 `_rag` 跨调用复用 ⇒ 第二次起必抛
    `bound to a different event loop`（`work/_sidecar4.err` 里 5773 行）。
    `CaseIndex.retrieve` 遇到它就**退回 BM25**，而那些行当时仍被标成 `lightrag`
    ——"这条臂不行"与"这条臂根本没跑到"于是混成一个结论，正是 D8 要判的那件事。
    """
    index = _Index({"q1": _cases("c1")})
    index.path_label = "lightrag"
    index.effective = "hybrid"
    index.reason = "lightrag_query_failed:TimeoutError"
    rows = e1_panel.score_queries(index, ["q1"], [("stub", _Client({"c1": 5}))],
                                  top_k=1, workers=1)
    assert rows, "夹具必须真的产出打分，否则这条用例是空绿"
    assert rows[0]["retrieval_path"] == "lightrag"          # 请求的臂
    assert rows[0]["cases_backend_effective"] == "hybrid"   # 实际干的活
    assert rows[0]["cases_degrade_reason"].startswith("lightrag_query_failed")


class _FilterClient:
    """只回 `{"keep": [...]}` 的过滤器桩；记下它收到的 system 文本。"""

    def __init__(self, keep):
        self.keep = list(keep)
        self.systems = []
        self.calls = 0

    def chat_json(self, system, user, temperature, seed, num_ctx):
        self.calls += 1
        self.systems.append(system)
        return {"keep": self.keep}


def test_the_case_filter_uses_the_products_own_prompt_and_only_subtracts():
    """`--cases-filter llm` 必须用**产品那条提示词**（单一真源 import），且只做减法。

    为什么单独钉一条：E1 是精确率指标，而产品在注入前会过滤；如果这里另写一份提示词，
    "E1 带过滤"量的就不是产品会做的事。`CaseIndex._filtered` 还会把不属于入参的
    id 剔掉——所以过滤器**造不出**案例（这条在 `tests/test_case_filter.py` 里另有反面用例）。
    """
    client = _FilterClient(keep=["c2", "c9"])          # c9 不在候选里：不许凭空加案例
    case_filter = e1_panel.make_llm_case_filter(model="deepseek-chat", client=client)
    cases = _cases("c1", "c2", "c3")
    kept = case_filter("q1", cases)
    assert [case.case_id for case in kept] == ["c2"]
    assert client.systems == [e1_panel.CASE_FILTER_SYSTEM]
    assert "不确定就保留" in client.systems[0]


def test_every_row_says_whether_the_case_filter_was_on():
    """自述字段：这一跑开没开过滤器、以及过滤器自己报的降级原因。"""
    plain = _Index({"q1": _cases("c1")})
    rows = e1_panel.score_queries(plain, ["q1"], [("stub", _Client({"c1": 5}))],
                                  top_k=1, workers=1)
    assert rows[0]["cases_filter"] == "off" and rows[0]["cases_filter_reason"] == ""

    filtered = _Index({"q1": _cases("c1")})
    filtered.case_filter = lambda query, cases: list(cases)
    filtered.filter_reason = "cases_filter_failed:RuntimeError"
    rows = e1_panel.score_queries(filtered, ["q1"], [("stub", _Client({"c1": 5}))],
                                  top_k=1, workers=1)
    assert rows[0]["cases_filter"] == "on"
    assert rows[0]["cases_filter_reason"].startswith("cases_filter_failed")


class _RecordingIndex(_Index):
    """把"被问了多少条"记下来的索引桩（rerank 的取宽行为靠它钉住）。"""

    def __init__(self, mapping, fingerprint="f" * 64):
        super().__init__(mapping, fingerprint)
        self.requested = []

    def retrieve(self, query, top_k=3):
        self.requested.append(int(top_k))
        return self.mapping.get(query, [])[:top_k]


def test_rerank_keeps_the_top_n_by_score_with_a_deterministic_tie_break():
    """纯函数：按分取前 keep 条；并列按 `case_id` 定序 ⇒ 同输入同输出。"""
    cases = _cases("c1", "c2", "c3", "c4")
    scorer = lambda query, items: [0.5, 0.9, 0.5, 0.1]      # noqa: E731 - 测试桩
    kept = e1_panel.rerank_cases(scorer, "q", cases, 3)
    assert [case.case_id for case in kept] == ["c2", "c1", "c3"]
    assert [case.case_id for case in e1_panel.rerank_cases(scorer, "q", cases, 2)] == \
        ["c2", "c1"]
    try:                       # 分数条数对不上 ⇒ 当场报错（不许悄悄配平）
        e1_panel.rerank_cases(lambda query, items: [0.1], "q", cases, 3)
    except ValueError:
        pass
    else:                      # pragma: no cover
        raise AssertionError("重排分与候选数不匹配竟然被收下了")


def test_rerank_asks_for_a_wider_candidate_set_and_records_it():
    """retrieve-then-rerank：**先取宽候选**（20）再重排取 3——R3 的算术说这才是
    能改变"哪 3 条被返回"的那一步（在 top-3 上再过滤到不了 0.70）。"""
    index = _RecordingIndex({"q1": _cases("c1", "c2", "c3", "c4", "c5")})
    scorer = lambda query, items: [0.1, 0.2, 0.9, 0.3, 0.4]   # noqa: E731 - 测试桩
    rows = e1_panel.score_queries(
        index, ["q1"], [("stub", _Client({"c3": 5, "c5": 4, "c4": 1}))],
        top_k=3, workers=1, rerank=scorer, retrieve_k=20,
        rerank_label="BAAI/bge-reranker-v2-m3")
    assert index.requested == [20], "必须先取宽候选再重排"
    assert [row["case_id"] for row in rows] == ["c3", "c5", "c4"]   # 重排后的前三
    assert rows[0]["cases_rerank"] == "BAAI/bge-reranker-v2-m3"
    assert rows[0]["cases_retrieve_k"] == 20


def test_rerank_off_keeps_the_historical_call_shape():
    index = _RecordingIndex({"q1": _cases("c1", "c2", "c3", "c4")})
    rows = e1_panel.score_queries(index, ["q1"], [("stub", _Client({"c1": 5}))],
                                  top_k=3, workers=1)
    assert index.requested == [3]        # 与历次读数逐字同口径
    assert rows[0]["cases_rerank"] == "off"
    assert rows[0]["cases_retrieve_k"] == 3


class _OrderClient:
    """只回 `{"order": [...]}` 的重排器桩。"""

    def __init__(self, order, *, boom=False, key="order"):
        self.order = list(order)
        self.boom = boom
        self.key = key
        self.systems = []

    def chat_json(self, system, user, temperature, seed, num_ctx):
        self.systems.append(system)
        if self.boom:
            raise RuntimeError("reranker down")
        return {self.key: self.order}


def test_the_llm_reranker_turns_an_order_into_scores_and_keeps_missing_ids_last():
    """重排器只输出**次序**；漏写的 id 必须**垫底而不是丢掉**（裁到 top-k 是下游的事）。"""
    client = _OrderClient(["c3", "c1"])
    scorer = e1_panel.make_llm_reranker(model="qwen3.8-max", client=client)
    cases = _cases("c1", "c2", "c3")
    scores = scorer("q", cases)
    assert len(scores) == 3
    assert scores[2] > scores[0] > scores[1]        # c3 第一、c1 第二、c2 未排到垫底
    assert "最有用在前" in client.systems[0]
    kept = e1_panel.rerank_cases(scorer, "q", cases, 2)
    assert [case.case_id for case in kept] == ["c3", "c1"]


def test_a_broken_reranker_degrades_by_name_and_keeps_the_unreranked_top_k():
    """重排是增强：它挂了要**具名**退回未重排的前 k 条，不许变成空列表、也不许静默。"""
    index = _RecordingIndex({"q1": _cases("c1", "c2", "c3", "c4")})
    scorer = e1_panel.make_llm_reranker(model="m", client=_OrderClient([], boom=True))
    rows = e1_panel.score_queries(
        index, ["q1"], [("stub", _Client({"c1": 5, "c2": 4, "c3": 1}))],
        top_k=3, workers=1, rerank=scorer, retrieve_k=20, rerank_label="m")
    assert index.requested == [20]
    assert [row["case_id"] for row in rows] == ["c1", "c2", "c3"]   # 未重排的前 3 条
    assert rows[0]["cases_rerank"] == "failed:RuntimeError"


class _ExpandClient:
    """只回 `{"en": "..."}` 的改写器桩。"""

    def __init__(self, en, *, boom=False):
        self.en = en
        self.boom = boom
        self.systems = []

    def chat_json(self, system, user, temperature, seed, num_ctx):
        self.systems.append(system)
        if self.boom:
            raise RuntimeError("expander down")
        return {"en": self.en}


def test_query_expansion_changes_only_the_retrieval_string():
    """**判据一个字不动**：判分查询仍是冻结原文；只有检索串换成「原文 ＋ 英文改写」。"""
    index = _RecordingIndex({"q1 static tripod shot reverse shot": _cases("c9"),
                             "q1": _cases("c1", "c2")})
    expander = e1_panel.make_query_expander(
        model="deepseek-chat", client=_ExpandClient("static tripod shot reverse shot"))
    rows = e1_panel.score_queries(
        index, ["q1"], [("stub", _Client({"c9": 5}))], top_k=1, workers=1,
        expand=expander, expand_mode="union")
    assert rows, "夹具必须真的产出打分，否则这条用例是空绿"
    assert [row["case_id"] for row in rows] == ["c9"]      # 用改写串检索到了
    assert rows[0]["query"] == "q1"                        # 判分查询＝冻结原文
    assert rows[0]["query_retrieval"] == "q1 static tripod shot reverse shot"
    assert rows[0]["query_expansion"] == "static tripod shot reverse shot"
    assert rows[0]["query_expand"] == "on"


def test_replace_mode_uses_only_the_expansion():
    index = _RecordingIndex({"static tripod shot": _cases("c9")})
    expander = e1_panel.make_query_expander(
        model="m", client=_ExpandClient("static tripod shot"))
    rows = e1_panel.score_queries(
        index, ["q1"], [("stub", _Client({"c9": 5}))], top_k=1, workers=1,
        expand=expander, expand_mode="replace")
    assert rows[0]["query_retrieval"] == "static tripod shot"


def test_a_broken_expander_degrades_by_name_to_the_original_query():
    index = _RecordingIndex({"q1": _cases("c1")})
    expander = e1_panel.make_query_expander(
        model="m", client=_ExpandClient("", boom=True))
    rows = e1_panel.score_queries(
        index, ["q1"], [("stub", _Client({"c1": 5}))], top_k=1, workers=1,
        expand=expander, expand_mode="union")
    assert rows[0]["query_retrieval"] == "q1"
    assert rows[0]["query_expand"] == "failed:RuntimeError"


def test_the_reranker_can_be_asked_to_select_or_to_score():
    """两种更稳的提示词形状（对照用）：**只挑 3 条**与**逐条打分**。

    起因：全序排序那版只拿到上限的 36%（`docs/evidence/20261006-e1-ceiling/`），
    而"一次把 20 条排全序"是模型最容易出错的形状。
    """
    cases = _cases("c1", "c2", "c3", "c4")

    selected = e1_panel.make_llm_reranker(
        model="m", prompt="select", client=_OrderClient(["c3", "c4", "c1"], key="best"))
    kept = e1_panel.rerank_cases(selected, "q", cases, 3)
    assert [case.case_id for case in kept] == ["c3", "c4", "c1"]

    scored = e1_panel.make_llm_reranker(model="m", prompt="score", client=_ScoredClient(
        {"c2": 9.0, "c4": 7.0}))          # c1/c3 漏写 ⇒ 垫底，不丢
    kept = e1_panel.rerank_cases(scored, "q", cases, 2)
    assert [case.case_id for case in kept] == ["c2", "c4"]

    try:
        e1_panel.make_llm_reranker(model="m", prompt="turbo", client=_OrderClient([]))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("未知的提示词形状竟然被收下了")


class _ScoredClient:
    """只回 `{"scores": {...}}` 的打分器桩。"""

    def __init__(self, scores, *, boom=False):
        self.scores = dict(scores)
        self.boom = boom

    def chat_json(self, system, user, temperature, seed, num_ctx):
        if self.boom:
            raise RuntimeError("scorer down")
        return {"scores": self.scores}


def test_an_empty_selection_or_score_set_fails_by_name():
    empty_select = e1_panel.make_llm_reranker(
        model="m", prompt="select", client=_OrderClient([], key="best"))
    empty_score = e1_panel.make_llm_reranker(
        model="m", prompt="score", client=_ScoredClient({}))
    for scorer, label in ((empty_select, "best"), (empty_score, "scores")):
        try:
            scorer("q", _cases("c1"))
        except Exception as exc:  # noqa: BLE001 - 空回包必须具名失败
            assert label in str(exc), str(exc)
        else:  # pragma: no cover
            raise AssertionError("空回包竟然被当成有效重排")
