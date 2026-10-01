"""`tools/knowledge/quality.py`：Q0 构建门与 E1–E3 的判定纪律（离线）。"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.hypergraph import HyperEdge, Member, Node  # noqa: E402
from tools.knowledge import quality  # noqa: E402


def _graph(edges):
    nodes = {n.node_id: n for n in (
        Node("emotion:荒诞", "emotion", "荒诞"),
        Node("intensity:high", "intensity", "high"),
        Node("movement:固定", "movement", "固定"),
    )}
    from block_director.knowledge.hypergraph import Hypergraph

    return Hypergraph(list(nodes.values()), list(edges))


def _edge(source_kind="theory", forbid=False):
    members = [Member("allow", "emotion", "emotion:荒诞"),
               Member("qualifier", "intensity", "intensity:high")]
    if forbid:
        members.append(Member("forbid", "movement", "movement:固定"))
    return HyperEdge(type="EMOTION_PACK", members=tuple(members),
                     source_kind=source_kind,
                     hardness="hard" if source_kind == "theory" else "soft")


# --------------------------------------------------------------------------- Q0


def test_q0_passes_on_a_consistent_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    rejects = tmp_path / "rejects.jsonl"
    manifest.write_text(json.dumps({
        "raw_edges": 100, "valid_unique": 90, "duplicates": 5, "rejects": 5,
        "batches": [{"status": "done"}, {"status": "rejected"}]}), encoding="utf-8")
    rejects.write_text("\n".join(["{}"] * 5), encoding="utf-8")
    out = quality.q0_build_gate(manifest, rejects)
    assert out["status"] == "pass"
    assert out["processed_chunks"] == 2 and out["total_chunks"] == 2


def test_q0_fails_when_the_rejects_ledger_does_not_match(tmp_path):
    manifest = tmp_path / "manifest.json"
    rejects = tmp_path / "rejects.jsonl"
    manifest.write_text(json.dumps({"raw_edges": 100, "valid_unique": 90,
                                    "duplicates": 5, "rejects": 5}), encoding="utf-8")
    rejects.write_text("\n".join(["{}"] * 3), encoding="utf-8")
    out = quality.q0_build_gate(manifest, rejects)
    assert out["status"] == "fail" and "账不对" in out["note"]


def test_q0_fails_over_the_five_percent_line(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"raw_edges": 100, "valid_unique": 80,
                                    "duplicates": 6, "rejects": 14,
                                    "batches": [{"status": "done"}]}), encoding="utf-8")
    out = quality.q0_build_gate(manifest, tmp_path / "missing.jsonl")
    assert out["status"] == "fail"


def test_q0_is_not_measured_without_a_manifest(tmp_path):
    out = quality.q0_build_gate(tmp_path / "nope.json", tmp_path / "nope.jsonl")
    assert out["status"] == "not_measured"


# --------------------------------------------------------------------------- E3


def test_e3_is_zero_for_a_theory_only_index():
    """理论-only 索引**不再**判 pass：分母为 0 就是空集通过（§4.1b 硬规则 1）。

    2026-10-01 实测：入库索引 766 条边里 `theory 762 / lesson 4 / experience 0`，
    旧实现因此把"经验不越权"这条硬门**恒真**地判成 pass 并记进 RK-13。规格
    §B.5 的 E3 行写死了"只有分子没有分母 = 空集通过；分母为 0 → 失败"。
    """
    out = quality.e3_experience_override(_graph([_edge("theory", forbid=True)]))
    assert out["status"] == "fail" and out["denominator"] == 0
    assert "分母下界" in out["note"]


def test_e3_counts_an_experience_edge_that_forbids():
    graph = _graph([_edge("experience", forbid=True), _edge("experience")])
    out = quality.e3_experience_override(graph)
    assert out["status"] == "fail"
    assert out["numerator"] == 1 and out["denominator"] == 2


def test_e3_lesson_may_forbid_but_experience_may_not():
    """只有显式 lesson 允许带 forbid（§2.3b 关键纪律 1）。"""
    lesson = _edge("lesson", forbid=True)
    # 分母必须有东西：单给 lesson 会让 experience 计数为 0，那是"测不到"（fail），
    # 不是"lesson 允许带禁"。这里补一条干净的 experience 边当分母。
    clean = _edge("experience")
    out = quality.e3_experience_override(_graph([lesson, clean]))
    assert out["status"] == "pass" and out["denominator"] == 1
    # 反面：分母为 0 时同一条 lesson 索引判 fail（不是 pass）。
    assert quality.e3_experience_override(_graph([lesson]))["status"] == "fail"


def test_e3_cases_flag_a_constraint_field(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join([
        json.dumps({"case_id": "c1", "case_type": "narrative"}),
        json.dumps({"case_id": "c2", "forbid": ["movement=固定"]}, ensure_ascii=False),
    ]), encoding="utf-8")
    out = quality.e3_cases(cases)
    assert out["status"] == "fail" and out["numerator"] == 1
    assert quality.e3_cases(None)["status"] == "not_measured"


# --------------------------------------------------------------------------- E1 / E2


def test_e1_needs_human_scores_and_never_guesses():
    assert quality.e1_relevance(None)["status"] == "not_measured"


def test_e1_uses_the_human_scores_when_present(tmp_path):
    reviews = tmp_path / "e1.jsonl"
    reviews.write_text("\n".join(json.dumps({"score": s}) for s in (5, 4, 3, 5)),
                       encoding="utf-8")
    out = quality.e1_relevance(reviews)
    assert out["status"] == "pass" and out["value"] == 0.75

    reviews.write_text("\n".join(json.dumps({"score": s}) for s in (5, 3, 2)),
                       encoding="utf-8")
    assert quality.e1_relevance(reviews)["status"] == "fail"


def test_e2_counts_adopted_movements_and_is_never_a_gate(tmp_path):
    shots = tmp_path / "shots.json"
    shots.write_text(json.dumps({"shots": [
        {"movements": [{"source": "experience"}]},
        {"movements": [{"source": "declared"}]},
    ]}), encoding="utf-8")
    out = quality.e2_adoption(shots)
    assert out["numerator"] == 1 and out["denominator"] == 2
    assert out["status"] == "not_measured" and out["diagnostic"] is True


# --------------------------------------------------------------------------- 总判


def test_q4_build_gate_fails_when_a_must_maps_to_no_index_edge():
    """§2.3 Q6b 前置①：required 边在索引里不存在 ⇒ 索引构建失败。

    这条判据**不能**由 Q1/Q2/Q4 代替——`score_entries` 会把解析不到的 `must`
    从 required 分母里剔掉，分母变小只会让比率变好看，缺陷不会被报出来。
    """
    bad = quality.q4_build_gate({"must_total": 10, "required_unresolved": 1,
                                 "unresolved_examples": [{"id": "hq_0009"}]})
    assert bad["status"] == "fail"
    assert bad["numerator"] == 9 and bad["denominator"] == 10
    assert "不同构" in bad["note"]

    good = quality.q4_build_gate({"must_total": 10, "required_unresolved": 0})
    assert good["status"] == "pass" and good["value"] == 1.0


def test_q4_build_gate_obeys_the_denominator_floor():
    """硬规则 1：分母为 0 一律判失败，不得记 not_measured 后放过。"""
    out = quality.q4_build_gate({"must_total": 0, "required_unresolved": 0})
    assert out["status"] == "fail" and out["denominator"] == 0
    assert "硬规则 1" in out["note"]


def test_overall_is_not_measured_when_evidence_is_missing(tmp_path):
    """缺证据时退出码必须是 2，绝不当成通过（§4.1b 硬规则 1）。"""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "raw_edges": 100, "valid_unique": 95, "duplicates": 2, "rejects": 3,
        "batches": [{"status": "done"}, {"status": "done"}]}), encoding="utf-8")
    rejects = tmp_path / "rejects.jsonl"
    rejects.write_text("\n".join(["{}"] * 3), encoding="utf-8")
    #: 用**空**的 held-out：这条测的是"证据缺失时必须 not_measured"，
    #: 与正式 held-out 是否落地无关（正式文件在 v1.5 已经落地）。
    empty_holdout = tmp_path / "empty_holdout.jsonl"
    empty_holdout.write_text("", encoding="utf-8")
    # 这条用例测的是"证据缺失 → not_measured"，所以先让 E3 有分母：入库索引进
    # 现在是 experience 0（分母 0 → 按 §4.1b 判 fail），会让 overall 变成 fail，
    # 掩盖掉本用例要断言的 not_measured。这里复制真实索引再追加一条**不带 forbid**
    # 的经验边，其它部分逐字节不变。
    nodes_path = "knowledge/hypergraph.nodes.jsonl"
    real_edges = (ROOT / "knowledge" / "hypergraph.edges.jsonl").read_text(
        encoding="utf-8").rstrip("\n").splitlines()
    probe = json.loads(real_edges[0])
    probe["edge_id"] = "hg:ut_experience_probe"
    probe["source_kind"] = "experience"
    probe["hardness"] = "soft"
    probe["members"] = [m for m in probe["members"] if m[0] != "forbid"]
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text("\n".join(real_edges + [json.dumps(probe, ensure_ascii=False)])
                          + "\n", encoding="utf-8")
    code = quality.main([
        "--run-id", "ut", "--holdout", str(empty_holdout),
        "--nodes", nodes_path, "--edges", str(edges_path),
        "--manifest", str(manifest), "--rejects", str(rejects),
        "--cases", "", "--out", str(tmp_path / "q.json"),
    ])
    assert code == 2
    report = json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))
    ids = {m["id"]: m["status"] for m in report["metrics"]}
    assert ids["Q0"] == "pass"
    assert ids["Q1-Q7"] == "not_measured"
    assert ids["E1"] == "not_measured"
    assert report["overall"] == "not_measured"


def test_shipped_index_ledger_is_never_silently_passed():
    """索引落盘后，manifest 的 `rejects` 必须与 rejects 明细行数相等。

    对不上就是账错——**必须判 fail，不能沉默通过**。这条断言两种状态都成立：
    账对得上时 `status == "pass"`；对不上时 `status == "fail"` 且注记里点名"账不对"。
    """
    manifest_path = ROOT / "knowledge" / "hypergraph.manifest.json"
    rejects_path = ROOT / "knowledge" / "hypergraph.rejects.jsonl"
    if not manifest_path.is_file():
        return  # 索引未落盘时由 Q0 记 not_measured，这里不重复报
    out = quality.q0_build_gate(manifest_path, rejects_path)
    if out.get("rejects_file_lines") == out.get("rejects"):
        assert out["status"] == "pass", out
    else:
        assert out["status"] == "fail", f"账对不上却判成了 {out['status']}：{out}"
        assert "账不对" in out["note"], out
