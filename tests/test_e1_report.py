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
        }, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
