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
    # 空文件同样判失败：分母 0 不是"没有越权案例"，是"没有案例可查"（§4.1b）。
    empty = tmp_path / "empty_cases.jsonl"
    empty.write_text("", encoding="utf-8")
    blank = quality.e3_cases(empty)
    assert blank["status"] == "fail" and blank["denominator"] == 0


# --------------------------------------------------------------------------- E1 / E2


def test_e1_needs_human_scores_and_never_guesses():
    assert quality.e1_relevance(None)["status"] == "not_measured"


def _case_index(tmp_path, case_ids, fingerprint="fp-current"):
    """写一份最小的 L3 索引＋manifest：E1 的打分必须绑在**这一份**上。"""
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(
        json.dumps({"case_id": cid, "case_type": "narrative",
                    "excerpt": "原文摘句", "source_ref": {}}, ensure_ascii=False)
        for cid in case_ids), encoding="utf-8")
    (tmp_path / "cases.manifest.json").write_text(
        json.dumps({"fingerprint": fingerprint}), encoding="utf-8")
    #: 打分行要自带**案例集合**摘要（会诊 D1）；夹具在这里把"当前这一份"记下来，
    #: `_review_row` 默认就用它——于是"同一份索引"的用例天然同代，而想造
    #: "只换案例集合"的场景时，另建一份索引并把 `_CURRENT['digest']` 指过去即可。
    from block_director.knowledge.cases import case_paths, cases_digest

    _CURRENT["digest"] = cases_digest(case_paths(tmp_path))
    return cases


#: 当前夹具索引的案例集合摘要（`_case_index` 写，`_review_row` 读）。
_CURRENT: dict = {"digest": ""}


def _reviews(tmp_path, rows, name="e1.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False)
                              for row in rows), encoding="utf-8")
    return path


def _review_row(case_id, score, fingerprint="fp-current", reviewer="human",
                digest=None):
    row = {"case_id": case_id, "score": score, "reviewed_by": reviewer}
    if fingerprint is not None:
        row["cases_fingerprint"] = fingerprint
    stamp = _CURRENT["digest"] if digest is None else digest
    if stamp:
        row["cases_digest"] = stamp
    return row


def test_e1_uses_the_human_scores_when_they_cover_the_current_index(tmp_path):
    cases = _case_index(tmp_path, ["c1", "c2", "c3", "c4"])
    reviews = tmp_path / "e1.jsonl"
    reviews.write_text("\n".join(json.dumps({"score": s}) for s in (5, 4, 3, 5)),
                       encoding="utf-8")
    reviews = _reviews(tmp_path, [_review_row(f"c{i}", s) for i, s in
                                  enumerate((5, 4, 3, 5), 1)])
    out = quality.e1_relevance(reviews, cases_path=cases)
    assert out["status"] == "pass" and out["value"] == 0.75
    assert "stale_evidence" not in out

    below = _reviews(tmp_path, [_review_row(f"c{i}", s) for i, s in
                                enumerate((5, 3, 2), 1)], name="e1_below.jsonl")
    assert quality.e1_relevance(below, cases_path=cases)["status"] == "fail"


def test_e1_reports_how_far_it_is_from_the_sample_floor(tmp_path):
    """§4.1b 给 E1 写了「判分样本 ≥ 1200」，而链上只有一次运行的 18 条。

    这个缺口必须**报出来**，但不许因此改判定：E1 的分母是 18 不是 0，按 §4.1b
    硬规则 1 该判失败就判失败。把它记成 `not_measured` 是"用样本量把红的说成灰的"，
    跟把它当成 0.1667 的结论一样不诚实——正确的做法是**两个都写出来**。
    """
    cases = _case_index(tmp_path, ["c1", "c2", "c3", "c4"])
    reviews = _reviews(tmp_path, [_review_row(f"c{i}", s) for i, s in
                                  enumerate((5, 4, 3, 5), 1)])
    out = quality.e1_relevance(reviews, cases_path=cases)
    assert out["status"] == "pass", "判定不许因为样本量而改变"
    assert out["denominator"] == 4
    assert out["sample_floor"] == quality.E1_SAMPLE_FLOOR == 1200
    assert out["sample_shortfall"] == 1196
    assert out["sample_floor_met"] is False
    assert "还不具备" in out["note"] and "1200" in out["note"]

    # 正对照：样本够时不再提这条（也不会多出一个永远为假的字段）。
    many = _reviews(tmp_path, [_review_row(f"c{i % 4 + 1}", 5)
                               for i in range(quality.E1_SAMPLE_FLOOR)],
                    name="e1_many.jsonl")
    big = quality.e1_relevance(many, cases_path=cases)
    assert big["sample_floor_met"] is True and big["sample_shortfall"] == 0
    assert "还不具备" not in big["note"]


def test_e1_scores_that_predate_the_index_are_not_evidence(tmp_path):
    """**真实漏网**（2026-10-02）：仓库里那份 E1 打分有 9/16 条的 case_id 在当前
    索引里已经不存在，却照样能被算成一个 0.0 的 E1。脱钩的打分记 `not_measured`
    ＋ `stale_evidence`，并把当时算出来的分数一并报出来（信息保留，不许读成通过）。
    """
    cases = _case_index(tmp_path, ["c1", "c2", "c3", "c4"])
    # ① 全部用例都对得上、指纹也对得上 ⇒ 不是陈旧证据（分母按好坏算）。
    fresh = _reviews(tmp_path, [_review_row(f"c{i}", 1) for i in (1, 2, 3, 4)],
                     name="fresh.jsonl")
    assert quality.e1_relevance(fresh, cases_path=cases)["status"] == "fail"

    # ② 有 case_id 掉出当前索引 ⇒ 陈旧。
    gone = _reviews(tmp_path, [_review_row("c1", 1), _review_row("c_gone", 1)],
                    name="gone.jsonl")
    out = quality.e1_relevance(gone, cases_path=cases)
    assert out["status"] == "not_measured" and out["stale_evidence"] is True
    assert out["denominator"] == 2 and "c_gone" in out["note"]

    # ③ 全对得上但没有携带索引指纹 ⇒ 无法证明它量的是这一份索引。
    unbound = _reviews(tmp_path, [_review_row(f"c{i}", 5, fingerprint=None)
                                  for i in (1, 2)], name="unbound.jsonl")
    out = quality.e1_relevance(unbound, cases_path=cases)
    assert out["status"] == "not_measured" and out["stale_evidence"] is True
    assert "指纹" in out["note"]

    # ④ 指纹是上一代的 ⇒ 同样不算证据（哪怕 case_id 恰好重合）。
    old = _reviews(tmp_path, [_review_row("c1", 5, fingerprint="fp-old"),
                              _review_row("c2", 5, fingerprint="fp-old")],
                   name="old.jsonl")
    assert quality.e1_relevance(old, cases_path=cases)["status"] == "not_measured"

    # ⑤ 没写是谁裁的 ⇒ 记录不完整，不算证据。
    anon = _reviews(tmp_path, [_review_row("c1", 5, reviewer="")],
                    name="anon.jsonl")
    assert quality.e1_relevance(anon, cases_path=cases)["status"] == "not_measured"

    # ⑥ 没有给索引路径 ⇒ 无法证明覆盖，同样不许判过（缺证据不是通过）。
    assert quality.e1_relevance(fresh)["status"] == "not_measured"


def test_e1_evidence_dies_when_only_the_case_set_changes(tmp_path):
    """**只换案例集合**（语料一个字没动）也必须判陈旧——语料指纹对此不敏感（D1）。

    现场（2026-10-05）：案例 810 → 1097 那一版把 `cases_digest` 从 `e1148200…`
    改成 `227869414e0e014b…`，而 `cases.manifest.json` 的 `fingerprint`（**语料**
    指纹）仍是 `69791dbacd…`——于是链上拿着**上一代索引**的打分继续报 0.0885，
    既不报 `stale_evidence`，也没人看得出换代。`cases_digest` 只有"案例集合"能改，
    它才是代际的真钥匙。
    """
    same_corpus = "fp-current"          # 两份索引的**语料**指纹故意相同
    tmp_path.joinpath("a").mkdir()
    before = _case_index(tmp_path / "a", ["c1", "c2"])
    rows = [_review_row("c1", 5), _review_row("c2", 5)]
    reviews = _reviews(tmp_path, rows, name="d1.jsonl")
    assert quality.e1_relevance(reviews, cases_path=before)["status"] == "pass"

    tmp_path.joinpath("b").mkdir()
    after = _case_index(tmp_path / "b", ["c1", "c2", "c3"], fingerprint=same_corpus)
    _CURRENT["digest"] = ""             # 别让后面的用例继承
    out = quality.e1_relevance(reviews, cases_path=after)
    assert out["status"] == "not_measured" and out["stale_evidence"] is True, out
    assert "案例集合" in out["note"], out["note"]

    #: 自证：把 `cases_digest` 从打分行里拿掉（旧产物）同样不算证据——缺证据 != 通过。
    unstamped = _reviews(tmp_path, [{"case_id": "c1", "score": 5,
                                     "reviewed_by": "human",
                                     "cases_fingerprint": same_corpus}],
                         name="d1_unstamped.jsonl")
    out = quality.e1_relevance(unstamped, cases_path=after)
    assert out["status"] == "not_measured" and out["stale_evidence"] is True, out


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
