"""P9①的编排器（`tools/knowledge/e1_report.py`）：**判词不重写**，但计划必须可判定。

计划 v4 的 P9① 要的是"三条路由 × N 次读数 ＋ 成对差值 ＋ inconclusive 标记"。
本文件钉住三件事：运行计划是确定性的、调的是**冻结仪器** `e1_panel` 的 CLI、
判词来自 `paired_report`（噪声带以下算 inconclusive，**不是**"两臂相等"）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import e1_report as er  # noqa: E402

FP = "f" * 64
DG = "d" * 64


def test_the_run_plan_is_route_major_and_repeats_inside():
    assert er.plan_runs(["lexical", "hybrid"], 2) == [
        ("lexical", 1), ("lexical", 2), ("hybrid", 1), ("hybrid", 2)]
    try:
        er.plan_runs(["lexical"], 0)
    except er.InputError as exc:
        assert "至少" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("0 次重复竟然被当成一份读数")


def test_an_unknown_route_is_refused_and_duplicates_collapse():
    assert er.parse_routes("hybrid, lexical ,hybrid") == ["hybrid", "lexical"]
    for bad in ("turbo", "hybrid,turbo", ""):
        try:
            er.parse_routes(bad)
        except er.InputError:
            continue
        raise AssertionError("路由 %r 竟然被收下了" % bad)


def test_one_route_can_carry_two_configs_under_distinct_arm_names():
    """D3 的用法：同一条 `lightrag` 路由，本地嵌入 vs 云端嵌入各算一个臂。

    臂名进文件名，所以冒号/斜杠（Windows 非法）必须当场拒收；标签不能空。
    """
    assert er.parse_routes("lightrag+local,lightrag+cloud") == ["lightrag+local",
                                                               "lightrag+cloud"]
    assert er.adapter_of("lightrag+cloud") == "lightrag"
    assert er.adapter_of("hybrid") == "hybrid"
    argv = er.panel_argv("lightrag+cloud", heldout=pathlib.Path("h.txt"),
                         cases_dir=pathlib.Path("cases"), out_path=pathlib.Path("o.jsonl"),
                         top_k=3, workers=3, lightrag_url="http://127.0.0.1:8812",
                         lightrag_fingerprint="fp")
    assert argv[argv.index("--adapter") + 1] == "lightrag"
    assert argv[argv.index("--out") + 1].endswith("o.jsonl")
    #: 臂名进文件名 ⇒ 非法字符与空标签都要拒。
    for bad in ("lightrag:", "lightrag+c loud", "lightrag+", "light/rag+cloud"):
        try:
            er.parse_routes(bad)
        except er.InputError:
            continue
        raise AssertionError("臂名 %r 竟然被收下了" % bad)


def test_the_panel_argv_is_the_frozen_instruments_cli():
    """本工具**只按 CLI 调** `e1_panel`（冻结仪器），不改它一行。"""
    argv = er.panel_argv("hybrid", heldout=pathlib.Path("h.txt"),
                         cases_dir=pathlib.Path("knowledge_v4"),
                         out_path=pathlib.Path("o.jsonl"), top_k=3, workers=3)
    assert argv[:2] == ["--queries", "h.txt"]
    #: `hybrid` 在产品 CLI 里叫 `--adapter none`（名字不同，路是同一条）。
    assert argv[argv.index("--adapter") + 1] == "none"
    assert "--lightrag-fingerprint" not in argv

    #: 走 sidecar 的路由**必须**带指纹：没有它就没法保证量的是哪一代索引。
    try:
        er.panel_argv("lightrag", heldout=pathlib.Path("h.txt"),
                      cases_dir=pathlib.Path("knowledge_v4"),
                      out_path=pathlib.Path("o.jsonl"), top_k=3, workers=3)
    except er.InputError as exc:
        assert "指纹" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("lightrag 路由没指纹也放行了")
    argv = er.panel_argv("lightrag", heldout=pathlib.Path("h.txt"),
                         cases_dir=pathlib.Path("knowledge_v4"),
                         out_path=pathlib.Path("o.jsonl"), top_k=3, workers=3,
                         lightrag_url="http://127.0.0.1:8793",
                         lightrag_fingerprint="abc")
    assert argv[argv.index("--lightrag-url") + 1] == "http://127.0.0.1:8793"
    assert argv[argv.index("--lightrag-fingerprint") + 1] == "abc"


def test_the_lightrag_fingerprint_is_read_from_the_shadow_layout(tmp_path):
    """计划 v4 的布局：影子目录下挂 `lightrag/`；指纹从那份 manifest 现读。"""
    assert er.lightrag_fingerprint_from(tmp_path) == ""
    target = tmp_path / "lightrag"
    target.mkdir()
    (target / "INDEX_MANIFEST.json").write_text(
        json.dumps({"fingerprint": "fp-from-manifest"}), encoding="utf-8")
    assert er.lightrag_fingerprint_from(tmp_path) == "fp-from-manifest"


def _write_reviews(path: pathlib.Path, *, route: str, relevant: int, rows: int = 10,
                   missing_side: bool = False) -> None:
    lines = []
    for index in range(rows):
        scores = [5, 5] if index < relevant else [1, 1]
        if missing_side and index == rows - 1:
            scores = [5, None]          #: 一位评委缺席 ⇒ 这一行不是"两位都回了分"
        lines.append(json.dumps({
            "query": "q%d" % index, "case_id": "c_%s_%d" % (route, index),
            "scores": scores, "score": 5.0 if index < relevant else 1.0,
            "retrieval_path": route, "cases_fingerprint": FP, "cases_digest": DG,
            "panel": ["deepseek-chat", "glm-5.3"], "zh": "", "excerpt": "x",
            #: 与真实行同形：实际干活的后端 + 降级原因（后者非空 ⇒ 已退回 BM25）。
            "cases_backend_effective": "hybrid" if route == "hybrid" else "lightrag",
            "cases_degrade_reason": "",
        }, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    #: 同轮的 **V1 轮记录**（执行器在判分前写身份、之后补终态；检查器只读）。
    _write_round(path.parent, route, _rep_of(path), state="valid", rows=rows)


def _rep_of(path: pathlib.Path) -> int:
    """`reviews.<route>.repN.jsonl` → N（测试夹具用）。"""
    return int(path.name.rsplit(".rep", 1)[1].split(".")[0])


def _write_round(directory: pathlib.Path, route: str, rep: int, *, state: str,
                 rows: int = 10, **identity) -> pathlib.Path:
    payload = {"route": route, "rep": rep, "terminal_state": state,
               "seed": 20261005, "rows": rows, "rows_digest": "r" * 64,
               "panel": ["deepseek-chat", "glm-5.3"], "panel_digest": "p" * 64,
               "corpus_manifest_digest": "c" * 64,
               "hypergraph_manifest_digest": "h" * 64,
               "identity_written_at": "2026-10-05T00:00:00+00:00",
               "state_written_at": "2026-10-05T00:00:00+00:00", **identity}
    path = directory / er.round_record_path(directory, route, rep).name
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_the_report_marks_pairs_inside_the_noise_band_as_inconclusive(tmp_path):
    """噪声带 ＝ 各臂**同臂重复极差**的最大值；带内的差**不叫**"某条路由更好"。"""
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    for route, values in (("a", (2, 3)), ("b", (3, 4)), ("c", (8, 9))):
        for rep, relevant in enumerate(values, 1):
            _write_reviews(reviews / er.rep_name(route, rep), route=route,
                           relevant=relevant)
    report = er.build_report(reviews, ["a", "b", "c"], 2, provenance={"k": "v"})
    assert report["noise_band"] == 0.1
    verdicts = {(pair["a"], pair["b"]): pair["verdict"] for pair in report["pairs"]}
    assert verdicts[("a", "b")] == "inconclusive", verdicts     # Δ 0.1 落在带内
    assert verdicts[("a", "c")] == "separated", verdicts        # Δ 0.6 在带外
    assert report["provenance"] == {"k": "v"}
    assert report["all_rounds_complete"] is True
    assert report["repetition_sufficient"] is True
    assert report["separation_verdicts_valid"] is True


def test_one_repetition_cannot_support_a_separation_verdict(tmp_path):
    """一次重复 ⇒ 噪声带恒为 0 ⇒ `separated` 恒真（无信息量）。本工具必须写明。"""
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    for route, relevant in (("a", 2), ("b", 4)):
        _write_reviews(reviews / er.rep_name(route, 1), route=route, relevant=relevant)
    report = er.build_report(reviews, ["a", "b"], 1)
    assert report["noise_band"] == 0.0
    assert report["pairs"][0]["verdict"] == "separated"       # paired_report 如实报
    assert report["repetition_sufficient"] is False           # 但本工具不许它被当判词
    assert report["separation_verdicts_valid"] is False
    assert "恒真" in report["note"]


def test_a_round_with_a_missing_judge_side_is_not_a_complete_round(tmp_path):
    """一侧缺席永远不算同意——这一轮要能被读出来"不是有效轮"。"""
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    for route in ("a", "b"):
        for rep in (1, 2):
            _write_reviews(reviews / er.rep_name(route, rep), route=route,
                           relevant=4, missing_side=True)
    report = er.build_report(reviews, ["a", "b"], 2)
    assert report["all_rounds_complete"] is False
    entry = report["judge_coverage"]["reviews.a.rep1.jsonl"]
    assert entry["single_judge_rows"] == 1 and entry["two_judge_rows"] == 9
    assert entry["complete"] is False


def test_a_round_that_degraded_or_lost_queries_is_reported_not_silent(tmp_path):
    """**2026-10-05 实测**：lightrag 臂的客户端 10 秒超时把它打回 BM25，行里
    `retrieval_path` 仍写着 `lightrag`——读数量的其实是超时。

    本工具把这件事**报出来**（`route_usage`），但**不当门**：把"看得见的降级"
    升格成"该臂无效"是判据级改动，单列 D11（须用户点头）。
    """
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    for route in ("hybrid", "lightrag"):
        for rep in (1, 2):
            _write_reviews(reviews / er.rep_name(route, rep), route=route, relevant=3)
    #: 让 lightrag 的第 2 轮里出现一行"退回 BM25"的记录。
    lines = (reviews / er.rep_name("lightrag", 2)).read_text(encoding="utf-8").split("\n")
    row = json.loads(lines[0])
    row["cases_backend_effective"] = "hybrid"
    row["cases_degrade_reason"] = "lightrag_query_failed:TimeoutError"
    lines[0] = json.dumps(row, ensure_ascii=False)
    (reviews / er.rep_name("lightrag", 2)).write_text("\n".join(lines), encoding="utf-8")

    report = er.build_report(reviews, ["hybrid", "lightrag"], 2, expected_queries=10)
    entry = report["route_usage"][er.rep_name("lightrag", 2)]
    assert entry["degraded_rows"] == 1
    assert entry["used_the_route"] is False
    assert entry["backends_effective"] == ["hybrid", "lightrag"]
    assert report["all_rounds_used_the_route"] is False
    assert report["route_usage"][er.rep_name("hybrid", 1)]["used_the_route"] is True
    assert report["route_usage"][er.rep_name("hybrid", 1)]["queries_missing"] == 0
    #: 静默空：查询集比这一轮实际有行的查询多 ⇒ 那几条一条都没召回，也要看得见。
    thin = er.build_report(reviews, ["hybrid", "lightrag"], 2, expected_queries=11)
    assert thin["route_usage"][er.rep_name("hybrid", 1)]["queries_missing"] == 1
    assert thin["route_usage"][er.rep_name("hybrid", 1)]["used_the_route"] is False


def test_count_queries_ignores_blank_lines(tmp_path):
    path = tmp_path / "heldout.txt"
    path.write_text("一\n\n二\n三\n", encoding="utf-8")
    assert er.count_queries(path) == 3


def test_rounds_only_runs_one_route_without_building_a_report(tmp_path, monkeypatch):
    """分次跑三臂时用：先落全部轮次（逐行录档 ＋ 轮记录），最后再一起判读。

    为什么需要这条缝：`paired_report` **至少两臂**才成立，而 P9 的第三臂要等 sidecar
    起来才能跑——若中途就出报告，会以"只有一臂"整批失败。
    """
    heldout = tmp_path / "heldout.txt"
    heldout.write_text("查询一\n查询二\n", encoding="utf-8")
    cases = tmp_path / "cases"
    (cases / "cases").mkdir(parents=True)
    (cases / "cases" / "part-000.jsonl").write_text(
        json.dumps({"case_id": "c1", "case_type": "narrative", "title": "t",
                    "excerpt": "e", "beat_sequence": [], "source_ref": {},
                    "score": 0.0}, ensure_ascii=False) + "\n", encoding="utf-8")
    calls = []

    def fake_main(argv):
        calls.append(list(argv))
        out = pathlib.Path(argv[argv.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"case_id": "c1", "query": "查询一", "score": 5.0,
                                   "scores": [5, 5], "retrieval_path": "hybrid",
                                   "cases_fingerprint": "f" * 64, "cases_digest": "d" * 64,
                                   "panel": ["a", "b"]}, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        return 0

    monkeypatch.setattr(er.e1_panel, "main", fake_main)
    out = tmp_path / "ab.json"
    assert er.main(["--index-dir", str(cases), "--heldout", str(heldout),
                    "--routes", "hybrid", "--runs", "2", "--rounds-only",
                    "--out", str(out)]) == 0
    assert not out.exists(), "rounds-only 不许出报告（一臂还汇总不了）"
    assert len(calls) == 2
    reviews = er.reviews_dir_for(out)
    for rep in (1, 2):
        assert (reviews / er.rep_name("hybrid", rep)).is_file()
        record = json.loads((reviews / er.round_record_path(reviews, "hybrid", rep))
                            .read_text(encoding="utf-8"))
        assert record["terminal_state"] == "valid"
        assert record["identity_written_at"] and record["state_written_at"]
