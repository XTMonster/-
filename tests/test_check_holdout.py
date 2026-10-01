"""Adversarial tests for tools/check_holdout.py (the held-out coverage gates).

Each test states the failure it guards against; the point of the file is that a
lying or half-finished held-out set must not be able to report `pass`.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests._holdout_index import index_args, read_jsonl, write_index  # noqa: E402
from tools import check_holdout  # noqa: E402

from block_director.knowledge import hypergraph as hg  # noqa: E402

# --- fixtures derived from the schema -------------------------------------------
# Hard-coding "6 edge types / 16 kinds" is what broke when the schema expanded to
# 13 types; everything below is read from the single source so it tracks the schema.
VALUE = {kind: f"{kind}_v" for kind in set(hg.NODE_TYPES) | set(hg.QUALIFIER_KINDS)}
VOCAB = {kind: [VALUE[kind]] for kind in hg.NODE_TYPES}
KEY_FOR = {kind: zh for zh, kind in hg.QUERY_KEYS.items()}


def spec_for(etype: str) -> str:
    slots = [f"{kind}={VALUE[kind]}" for _role, kind in hg.REQUIRED_MEMBERS[etype]]
    return f"{etype}:" + ",".join(slots)


def q_for(spec: str, etype: str = "") -> str:
    """A query that names exactly the kinds the given `must` spec covers.

    Keeping the two in step is what the self-consistency gate checks, so the fixture
    has to be built from the same source rather than written out by hand.
    """
    kinds = {chunk.split("=", 1)[0].replace("forbid_", "")
             for chunk in spec.split(":", 1)[1].split(",")}
    if etype:
        kinds |= {kind for _role, kind in (hg.OPTIONAL_MEMBERS.get(etype) or ())}
    pairs = [f"{KEY_FOR[kind]}={VALUE[kind]}" for kind in sorted(kinds) if kind in KEY_FOR]
    if not pairs:
        # 该边的必填槽位都不是查询键（如 AXIS_RULE 的 pair/axis_side）——用可选槽位里
        # 能表达的 kind 兜底；仍然保持"q 只命名 must 里出现过的 kind"这条自洽约束。
        pairs = [f"{KEY_FOR['shot_size']}={VALUE['shot_size']}"]
    return "；".join(pairs)


#: the default spec/query pair used by most tests
DEFAULT_SPEC = spec_for("EMOTION_PACK")
Q_ALL = q_for(DEFAULT_SPEC)


def entry(idx: int = 1, **over: object) -> dict:
    base = {
        "id": f"hq_{idx:04d}",
        "from_card": f"card_{idx}",
        "q": Q_ALL,
        "must": [DEFAULT_SPEC],
        "top1": [DEFAULT_SPEC],
        "never": [],
        "expect_movements": ["固定"],
        "annotator": {"model_id": "m-a", "family": "fam-a", "model_version": "1",
                      "prompt_sha256": "x"},
        "independence": "strong",
    }
    base.update(over)
    return base


def write(tmp_path: pathlib.Path, records, name: str = "holdout.jsonl") -> pathlib.Path:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")
    return path


def full_run(tmp_path: pathlib.Path, records, *extra: str,
             index_records=None, with_index: bool = True) -> int:
    """A pilot run with both external inputs supplied, so no gate is not_measured."""
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(sorted({r["from_card"] for r in records})), encoding="utf-8")
    argv = [str(write(tmp_path, records)), "--pilot",
            "--vocab", str(vocab), "--cards", str(cards),
            "--extractor-family", "deepseek"]
    if with_index:
        argv += index_args(
            tmp_path, records if index_records is None else index_records)
    return check_holdout.main(argv + list(extra))


def report(path: pathlib.Path, *extra: str, pilot: bool = True) -> dict:
    buf = io.StringIO()
    argv = [str(path), "--json"]
    if pilot:
        argv.insert(1, "--pilot")
    nodes, edges = write_index(path.parent, read_jsonl(path))
    argv += ["--nodes", str(nodes), "--edges", str(edges), *extra]
    with redirect_stdout(buf):
        check_holdout.main(argv)
    return json.loads(buf.getvalue())


def q7_entry(idx: int = 1, **over: object) -> dict:
    """A record whose `q` names a value its own `must` forbids (Q7 冲突条目)."""
    spec = (f"EMOTION_PACK:emotion={VALUE['emotion']},intensity={VALUE['intensity']},"
            f"forbid_movement={VALUE['movement']}")
    return entry(idx, must=[spec], top1=[spec],
                 q=f"{KEY_FOR['emotion']}={VALUE['emotion']}；"
                   f"{KEY_FOR['movement']}={VALUE['movement']}；"
                   # v1.5：`intensity` 有查询键了，必填槽位必须出现在 `q` 里
                   # （门⑨ 的"可达性"判据，与门⑩ 的"可解析"是两回事）。
                   f"{KEY_FOR['intensity']}={VALUE['intensity']}", **over)


def valid_records() -> list:
    """A minimal set that satisfies every gate under `--pilot`.

    One entry per edge type in the schema (gate ④), every query-expressible
    vocabulary value used (gate ③), one Q7 conflict (gate ⑤) and a human verdict on
    everything that needs one (gate ⑦) — i.e. what a real pilot batch has to look like.
    """
    review = {"reviewed_by": "human", "verdict": "accepted"}
    out = []
    for i, etype in enumerate(hg.EDGE_TYPES, 1):
        spec = spec_for(etype)
        out.append(entry(i, must=[spec], top1=[spec], q=q_for(spec, etype), review=review))
    out.append(q7_entry(len(out) + 1, review=review))
    return out


# ---------------------------------------------------------------- 门② 逐条格式

def test_valid_pilot_set_passes_every_gate(tmp_path):
    assert full_run(tmp_path, valid_records()) == 0


def test_empty_must_fails(tmp_path):
    assert full_run(tmp_path, [entry(must=[], top1=[])]) == 1


def test_more_than_three_must_fails(tmp_path):
    spec = q7_entry()["must"][0]
    four = [spec, spec + ",lens=50mm", spec + ",lens=35mm", spec + ",lens=24mm"]
    assert full_run(tmp_path, [entry(must=four)]) == 1


def test_top1_must_be_subset_of_must(tmp_path):
    other = "SHOT_PATTERN:shot_size=中景,lens=50mm,headroom_policy=board"
    assert full_run(tmp_path, [entry(top1=[other])]) == 1


def test_must_and_never_must_not_overlap(tmp_path):
    assert full_run(tmp_path, [entry(never=entry()["must"])]) == 1


def test_unknown_edge_type_fails(tmp_path):
    assert full_run(tmp_path, [entry(must=["TRIPLE:emotion=x,intensity=mid"])]) == 1


def test_missing_required_slot_fails(tmp_path):
    """EMOTION_PACK 缺 intensity —— 与 §2.3 的校验门④同源。"""
    assert full_run(tmp_path, [entry(must=["EMOTION_PACK:emotion=气急败坏"])]) == 1


def test_unknown_kind_fails(tmp_path):
    spec = "EMOTION_PACK:emotion=x,intensity=mid,mood=y"
    assert full_run(tmp_path, [entry(must=[spec])]) == 1


def test_illegal_role_on_a_legal_kind_fails(tmp_path):
    """`forbid_<kind>` 只能挂在 schema 允许它的边类型上。

    真缺陷（2026-10-01 修）：两个校验器原先只查"kind 是不是已知 kind"，
    不查"这个 kind 能不能以这个 role 挂在这个边类型上"。于是
    `EMOTION_PACK:…,forbid_lighting=逆光` 一路放行 —— 而
    `hypergraph.OPTIONAL_MEMBERS[EMOTION_PACK]` 只允许
    `forbid_movement`／`forbid_shot_size`／`forbid_vfx`。抽取器照 schema 建边，
    这样的边**在索引里根本不存在**（实测 890 条边零非法成员），标注断言的就是
    一条永远召不回的边；上一代 oracle 实测落了 **243 个**这种槽位
    （`forbid_pacing` 49／`forbid_lighting` 48／`forbid_camera_angle` 36…）。
    """
    assert check_holdout.illegal_members(
        "EMOTION_PACK", {"emotion", "intensity"}, {"lighting"}) == ["forbid_lighting"]
    # 合法角色是**正对照**：同一条边上 `forbid_movement` 必须放行（门⑤ 要靠它）。
    assert check_holdout.illegal_members(
        "EMOTION_PACK", {"emotion", "intensity"}, {"movement"}) == []
    spec = "EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_lighting=逆光"
    rec = entry(must=[spec], top1=[spec], q="情绪=气急败坏；强度=high；光线=逆光")
    assert full_run(tmp_path, [rec]) == 1


def test_duplicate_id_fails(tmp_path):
    assert full_run(tmp_path, [q7_entry(1), q7_entry(1)]) == 1


def test_annotator_requires_family(tmp_path):
    assert full_run(tmp_path, [entry(annotator={"model_id": "m"})]) == 1


def test_unparseable_q_fails(tmp_path):
    assert full_run(tmp_path, [entry(q="情绪")]) == 1


def test_q_key_must_come_from_the_frozen_key_set(tmp_path):
    """协议 §2.1 冻结了 q 的键集；自造键必须当场失败。"""
    assert full_run(tmp_path, [entry(q="心情=气急败坏")]) == 1


def test_dialogue_key_maps_to_scene_type(tmp_path):
    """`对白=有` 是合法的（折进 qualifier `scene_type`），不得被判未知键。"""
    assert check_holdout.Q_KEY_TO_KIND["对白"] == "scene_type"
    rec = entry(q="情绪=气急败坏；对白=有")
    data = report(write(tmp_path, [rec]))
    assert "不在协议" not in " ".join(data["gate_2_format"]["problems"])


def test_review_block_shape_is_checked(tmp_path):
    bad = [q7_entry(1, review={"reviewed_by": "human", "verdict": "maybe"})]
    assert full_run(tmp_path, bad) == 1
    good = valid_records()
    good[0]["review"] = {"reviewed_by": "human", "verdict": "accepted"}
    assert full_run(tmp_path, good) == 0


# ---------------------------------------------------------------- 门⑤ 禁忌覆盖

def test_q7_conflict_is_counted(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_5_forbid"]["q7_conflicts"] == 1
    assert data["gate_5_forbid"]["status"] == "pass"


def test_q7_is_zero_when_the_forbidden_value_is_absent_from_q(tmp_path):
    rec = q7_entry()
    rec["q"] = "情绪=气急败坏；动作=跺脚"
    data = report(write(tmp_path, [rec]))
    assert data["gate_5_forbid"]["q7_conflicts"] == 0
    assert data["gate_5_forbid"]["status"] == "fail"


def test_forbid_member_coverage_is_its_own_gate(tmp_path):
    """门⑤b：每个 forbid 成员都得有 ≥1 条冲突用例（否则"从不召回某个禁忌"永远测不到）。"""
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_5b_forbid_members"]["status"] == "pass"
    assert data["gate_5b_forbid_members"]["members"] == 1


def test_q7_kind_must_match_not_only_the_value(tmp_path):
    """只比值会让 `景别=中景` 撞上 `forbid_movement=中景`——必须同类同值。"""
    rec = entry(must=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_movement=中景"],
                top1=["EMOTION_PACK:emotion=气急败坏,intensity=high,forbid_movement=中景"],
                q="情绪=气急败坏；景别=中景")
    data = report(write(tmp_path, [rec]))
    assert data["gate_5_forbid"]["q7_conflicts"] == 0


def test_human_review_gate_flags_unreviewed_q5_q7_entries(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))  # 有 expect_movements 且是 Q7，却没人裁
    assert data["gate_7_human_review"]["status"] == "fail"
    assert data["gate_7_human_review"]["human_reviewed"] == 0


def test_pilot_entries_do_not_count_towards_the_1200(tmp_path):
    rec = q7_entry(review={"reviewed_by": "human", "verdict": "accepted"}, pilot=True)
    data = report(write(tmp_path, [rec]), pilot=False)
    assert data["gate_1_total"]["entries"] == 0
    assert data["gate_1_total"]["entries_pilot"] == 1
    assert data["gate_1_total"]["status"] == "fail"


# ---------------------------------------------------------------- 门⑩ 可达性（R54）

SPEC_MS50 = "SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board"


def test_gate11_relation_is_selectable_and_defaults_to_exact(tmp_path):
    """门⑪的期望关系可切，但**默认必须是规格字面的 exact**。

    背景（见 docs/knowledge/ORACLE_ALIGNMENT.md）：标注方看不到索引，
    成员集完全相等在构造上只有 ~37% 可满足；卡级口径（这张卡有没有边）是 94%。
    实现只把开关装上并把三档都量出来，选哪一档由规格裁决——
    所以默认不变、另两档永远只是诊断量，除非显式传 `--expectation-relation`。
    """
    # 索引里那条边来自 card_1，成员比标注**多一个可选槽位**——这正是现实里
    # 最常见的情形：完全相等判不过，只多不少判得过。
    narrow = spec_for("EMOTION_PACK")
    wider = narrow + f",movement={VALUE['movement']}"
    source = entry(9, from_card="card_1", must=[wider], top1=[wider],
                   q=q_for(wider, "EMOTION_PACK"))
    want = entry(1, from_card="card_1", must=[narrow], top1=[narrow], q=q_for(narrow))
    holdout = write(tmp_path, [want])
    nodes, edges = write_index(tmp_path, [source])

    def gate(relation: str) -> dict:
        buf = io.StringIO()
        with redirect_stdout(buf):
            check_holdout.main([str(holdout), "--pilot", "--json",
                                "--expectation-relation", relation,
                                "--nodes", str(nodes), "--edges", str(edges)])
        return json.loads(buf.getvalue())["gate_10_index_resolvable"]

    exact = gate("exact")
    assert exact["status"] == "fail"
    assert exact["expectation_relation"] == "exact"
    assert exact["card_edge_matches"] >= 1, "卡级诊断量必须同时报出来"

    subset = gate("subset")
    assert subset["expectation_relation"] == "subset"
    assert subset["subset_relation_matches"] >= 1

    card = gate("card_edge")
    assert card["status"] == "pass", "卡级口径下这张卡有边，应当判过"
    assert card["expectation_relation"] == "card_edge"


def test_gate11_card_edge_relation_does_not_relax_never(tmp_path):
    """`never` 不参与放宽：负样本的语义是"这条**不该**命中"。"""
    spec = spec_for("EMOTION_PACK")
    # 索引里只有一张卡 card_9 的边；目标条目 from_card=card_9，但它把 EMOTION_PACK
    # 写进了 never——卡级口径若把它算命中，负样本就成了空谈。
    indexed = entry(9, from_card="card_9", must=[spec], top1=[spec], q=q_for(spec))
    want = entry(1, from_card="card_9", must=[spec], top1=[spec], never=[spec],
                 q=q_for(spec))
    holdout = write(tmp_path, [want])
    nodes, edges = write_index(tmp_path, [indexed])
    detail = gate_only(holdout, nodes, edges, "card_edge")
    assert detail["totals"]["never"] == 1
    assert detail["resolved"]["never"] == 1, "never 命中的是索引里真有的那条边"


def gate_only(holdout: pathlib.Path, nodes: pathlib.Path, edges: pathlib.Path,
              relation: str) -> dict:
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_holdout.main([str(holdout), "--pilot", "--json",
                            "--expectation-relation", relation,
                            "--nodes", str(nodes), "--edges", str(edges)])
    return json.loads(buf.getvalue())["gate_10_index_resolvable"]


def test_gate10_flags_a_query_that_cannot_reach_its_own_must_edge(tmp_path):
    """协议 §3.1：`must` = "抽不到这条边我就认为检索失败了"。

    这条查询只写了 `景别=MS`，而它的 `must` 还要求 `镜头=50mm` —— 该边**从这条
    查询根本召不回**，Q1/Q2 在这种条目上数学不可达。产出侧
    （`holdout_fill.query_shortfall`）已经在拦，但**校验器一直没有**，于是已经写进
    `fixtures/knowledge_holdout.jsonl` 的那批弱查询谁也没报出来。
    """
    rec = entry(must=[SPEC_MS50], top1=[SPEC_MS50], q="景别=MS")
    data = report(write(tmp_path, [rec], "unreach.jsonl"))
    assert data["gate_2_format"]["status"] == "pass"      # 格式本身没毛病
    assert data["gate_9_reachability"]["status"] == "fail"
    assert data["gate_9_reachability"]["short"] == 1
    assert "lens=50mm" in data["gate_9_reachability"]["examples"][0]["unreachable"]


def test_gate10_passes_when_q_names_every_queryable_slot(tmp_path):
    """负对照：把 `must` 能表达的槽位全写进 `q`，门⑩ 必须绿。"""
    rec = entry(must=[SPEC_MS50], top1=[SPEC_MS50], q="景别=MS；镜头=50mm")
    data = report(write(tmp_path, [rec], "reach.jsonl"))
    assert data["gate_9_reachability"]["status"] == "pass"
    assert data["gate_9_reachability"]["short"] == 0


def test_gate10_only_judges_the_expected_edge_not_never(tmp_path):
    """`never` 本来就该跟查询不相交，不得被门⑩ 判红（否则负样本全废）。"""
    rec = entry(must=[SPEC_MS50], top1=[SPEC_MS50],
                never=["TROPE:genre=anime,emotion=emotion_v"],
                q="景别=MS；镜头=50mm")
    data = report(write(tmp_path, [rec], "never.jsonl"))
    assert data["gate_9_reachability"]["status"] == "pass"


# ---------------------------------------------------------------- 门⑪ 可解析（R54）


def test_gate11_flags_a_must_the_index_does_not_carry(tmp_path):
    """§2.3 Q6b 前置①：索引里没有这条 required 边 ⇒ 索引构建失败。

    这里让 held-out 多写一条索引里不存在的边：门⑪ 必须点名它，而不是让下游
    把这条 `must` 从分母里静默剔掉（那会让 Q1/Q2/Q4/Q6b 一起变好看）。
    """
    good = entry(1, review={"reviewed_by": "human", "verdict": "accepted"})
    bad = q7_entry(2, review={"reviewed_by": "human", "verdict": "accepted"})
    records = [good, bad]
    assert full_run(tmp_path, records, index_records=[good]) == 1
    nodes, edges = write_index(tmp_path, [good])
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_holdout.main([str(write(tmp_path, records)), "--pilot",
                            "--nodes", str(nodes), "--edges", str(edges), "--json"])
    data = json.loads(buf.getvalue())
    assert data["gate_10_index_resolvable"]["status"] == "fail"
    assert data["gate_10_index_resolvable"]["unresolved"] > 0
    assert data["gate_10_index_resolvable"]["unresolved_ratio"] > 0
    assert data["gate_10_index_resolvable"]["examples"]


def test_gate11_is_not_measured_without_an_index(tmp_path):
    """缺索引 → `not_measured`（退出码 2），绝不当作通过（§4.1b 硬规则 1）。"""
    # 用"其余门全过"的夹具，这样唯一的非 pass 就是门⑪ 的 not_measured
    # （fail 优先于 not_measured，混进别的红门就测不出退出码 2 了）。
    path = write(tmp_path, valid_records(), "noindex.jsonl")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check_holdout.main([str(path), "--pilot", "--json",
                                 "--nodes", str(tmp_path / "missing.nodes.jsonl"),
                                 "--edges", str(tmp_path / "missing.edges.jsonl")])
    assert rc == 2
    data = json.loads(buf.getvalue())
    assert data["gate_10_index_resolvable"]["status"] == "not_measured"
    assert "索引缺失" in data["gate_10_index_resolvable"]["reason"]


def test_gate11_passes_when_the_index_carries_every_spec(tmp_path):
    """负对照：索引与 fixture 同源派生时，门⑪ 必须绿。"""
    data = report(write(tmp_path, valid_records(), "resolvable.jsonl"))
    assert data["gate_10_index_resolvable"]["status"] == "pass"
    assert data["gate_10_index_resolvable"]["unresolved"] == 0
    assert data["gate_10_index_resolvable"]["index_edges"] > 0


def test_gate11_reports_the_subset_relation_as_a_diagnostic(tmp_path):
    """§2.3 前置① 的字面判据是"成员集完全相等"，而 §2.3c 又写死"标注方不可见索引"。

    两条放在一起在构造上不可能全过（`AXIS_RULE` 的可选 `axis_topic` 就是结构性一例）。
    门⑪ 的 status 仍按规格字面（完全相等），但必须同时把"标注 ⊆ 索引"这一层
    作为**诊断量**报出来——否则会把结构性冲突误读成标注噪声。
    """
    wide = SPEC_MS50 + ",composition_rule=rule_of_thirds"   # 索引里的那条边
    narrow = entry(1, must=[SPEC_MS50], top1=[SPEC_MS50],
                   q="景别=MS；镜头=50mm",
                   review={"reviewed_by": "human", "verdict": "accepted"})
    index_record = entry(99, must=[wide], top1=[wide], q="景别=MS；镜头=50mm")
    nodes, edges = write_index(tmp_path, [index_record])
    path = write(tmp_path, [narrow], "subset.jsonl")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check_holdout.main([str(path), "--pilot", "--json",
                                 "--nodes", str(nodes), "--edges", str(edges)])
    assert rc == 1
    gate = json.loads(buf.getvalue())["gate_10_index_resolvable"]
    assert gate["status"] == "fail"                 # 规格字面：完全相等 → 仍然红
    assert gate["unresolved"] == 2                  # must + top1 都是"少一个成员"
    assert gate["strict_relation_matches"] == 0
    assert gate["subset_relation_matches"] == 2     # 但"只多不少"这一层是满足的
    assert gate["subset_relation_ratio"] == 1.0
    assert "规格级裁决" in gate["note"]
    # 根因分类：这条不是"索引里没这条知识"，而是"索引那条边多带了成员"。
    assert gate["unresolved_by_cause"] == {"plain_subset_index_has_extra_members": 2}
    assert gate["unresolved_closeness"] == {"3": 2}   # plain 的三个成员全被覆盖


def test_gate11_classifies_why_a_spec_did_not_resolve(tmp_path):
    """门⑪ 的未命中必须能按**根因**分类，否则"73% 未命中"根本没法处分。

    三种根因对应三种完全不同的动作：

    * `value_not_in_index` —— 标注侧抄错词表取值（改提示／重标就能修）；
    * `no_edge_with_those_plain_members` —— 索引里没有这条知识（只能重抽取／补语料）；
    * `plain_subset_index_has_extra_members` —— 边在，只是索引那条边多带了成员。

    这一层是**诊断量**：门⑪ 的 status 仍按规格字面的「成员集完全相等」判，
    分类只是把"83% 未命中"拆成可处分的几堆，不参与判据。
    """
    narrow = entry(1, must=[SPEC_MS50], top1=[SPEC_MS50],
                   q="景别=MS；镜头=50mm",
                   review={"reviewed_by": "human", "verdict": "accepted"})
    typo_spec = "SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=borad"
    typo = entry(2, must=[typo_spec], top1=[typo_spec],
                 q="景别=MS；镜头=50mm",
                 review={"reviewed_by": "human", "verdict": "accepted"})
    # 索引里只有一条**不同留白策略**的同类边：`lens=50mm` 这个节点在（`_node_id_for`
    # 认得出它），但没有一条 SHOT_PATTERN 边同时要 board 留白，所以 narrow 只被
    # 覆盖 2/3 个 plain 成员。
    other = entry(99,
                  must=["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=cinematic"],
                  top1=["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=cinematic"],
                  q="景别=MS；镜头=50mm")
    # 再来一条把 `headroom_policy=board` 这个**节点**带进索引的边（它不是 narrow
    # 要找的那条边），这样 narrow 的未命中根因就落在"边不存在"而不是"取值不存在"。
    filler = entry(98, must=["SHOT_PATTERN:shot_size=LS,lens=35mm,headroom_policy=board"],
                   top1=["SHOT_PATTERN:shot_size=LS,lens=35mm,headroom_policy=board"],
                   q="景别=LS；镜头=35mm")
    nodes, edges = write_index(tmp_path, [other, filler])
    path = write(tmp_path, [narrow, typo], "causes.jsonl")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check_holdout.main([str(path), "--pilot", "--json",
                                 "--nodes", str(nodes), "--edges", str(edges)])
    assert rc == 1
    gate = json.loads(buf.getvalue())["gate_10_index_resolvable"]
    assert gate["status"] == "fail"
    assert gate["unresolved_by_cause"] == {
        "no_edge_with_those_plain_members": 2,   # narrow 的 must + top1
        "value_not_in_index": 2,                 # typo 的 must + top1
    }
    # 差多远：narrow 只被覆盖 2/3 个 plain 成员；typo 一个都没算。
    assert gate["unresolved_closeness"] == {"2": 2, "0": 2}
    assert gate["unresolved_by_edge_type"] == {"SHOT_PATTERN": 4}


# ---------------------------------------------------------------- 门④ 边类覆盖

def test_edge_type_coverage_gate_flags_short_types(tmp_path):
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_4_edge_types"]["status"] == "fail"
    for missing in ("SHOT_PATTERN", "AXIS_RULE", "TROPE", "EDIT_RHYTHM", "LIGHT_PACK"):
        assert missing in data["gate_4_edge_types"]["short_pairs"]


def test_edge_type_coverage_counts_distinct_card_query_pairs(tmp_path):
    """同一条 q 复制 30 次不算覆盖——必须来自 ≥30 个不同的 (卡片,查询) 对。"""
    copies = [q7_entry(i) for i in range(1, 4)]
    data = report(write(tmp_path, copies), "--pilot")
    assert data["gate_4_edge_types"]["short_pairs"]["SHOT_PATTERN"] == 0
    assert data["gate_4_edge_types"]["must_pairs_per_type" if False else "status"] == "fail"
    # 三张不同的卡 + 同一个查询 → EMOTION_PACK 有 3 对
    assert data["gate_2_format"]["must_pairs_per_type"]["EMOTION_PACK"] == 3


def test_edge_type_coverage_counts_distinct_cards(tmp_path):
    """同一张卡刷 30 条也不算——每类边至少来自 10 张不同的卡。"""
    same_card = [q7_entry(i) for i in range(1, 4)]
    for rec in same_card:
        rec["from_card"] = "card_1"
    data = report(write(tmp_path, same_card),
                  "--min-cards-per-type", "2", pilot=False)
    assert data["gate_4_edge_types"]["thin_cards"]["EMOTION_PACK"] == 1


# ---------------------------------------------------------------- 门③ 种子覆盖

def test_seed_coverage_not_measured_without_vocab(tmp_path):
    data = report(write(tmp_path, valid_records()))
    assert data["gate_3_seed_coverage"]["status"] == "not_measured"
    assert data["overall"] == "not_measured"


def test_seed_coverage_detects_missing_value(tmp_path):
    vocab = tmp_path / "vocab.json"
    widened = dict(VOCAB, emotion=[VALUE["emotion"], "狂喜"])
    vocab.write_text(json.dumps(widened, ensure_ascii=False), encoding="utf-8")
    data = report(write(tmp_path, valid_records()), "--vocab", str(vocab))
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert data["gate_3_seed_coverage"]["missing_values"]["emotion"] == ["狂喜"]


def test_seed_coverage_is_two_directional(tmp_path):
    """用了词表外的值 → 必须失败（这就是 norm_key 对不上、Q4 归零的那个坑）。"""
    vocab = tmp_path / "vocab.json"
    narrowed = dict(VOCAB)
    narrowed["emotion"] = ["别的情绪"]
    vocab.write_text(json.dumps(narrowed, ensure_ascii=False), encoding="utf-8")
    data = report(write(tmp_path, valid_records()), "--vocab", str(vocab))
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert VALUE["emotion"] in data["gate_3_seed_coverage"]["unknown_values"]["emotion"]


def test_q_value_that_contradicts_must_is_rejected(tmp_path):
    """自洽门：q 说"特写"而必须边说"中景"——查询与约束互相打架，必须当场失败。"""
    rec = q7_entry()
    rec["q"] = "情绪=气急败坏；景别=特写"
    data = report(write(tmp_path, [rec]))
    assert data["gate_2_format"]["status"] == "fail"
    assert "不一致" in " ".join(data["gate_2_format"]["problems"])


def test_edge_type_gate_scales_down_to_what_the_index_can_assert():
    """门④ 的对数要求取 `min(--min-per-type, 该类可断言对数)`（2026-10-01 用户裁决）。

    旧判据"每类 ≥30 对"是 schema 只有 6 类时的常数；v1.6 有 16 类，同一份许可语料
    摊到每类只剩 20 上下，而三类的原子边数 ≈ 覆盖卡片数（跨卡归并无从下手）——
    门限在构造上够不到。新增的 `assertable` 由**索引侧**给出（与 oracle 生成了什么无关），
    所以这不是自证：**能给到 30 的类必须交满 30，给不到的按它真能给的要求**。
    """
    pairs = {"ACTION_BEAT": 335, "MUSIC_PACK": 16}
    cards = {"ACTION_BEAT": 300, "MUSIC_PACK": 16}
    # 不给 assertable → 退回旧判据（行为不变）
    status, detail = check_holdout.gate_edge_types(pairs, cards, 30, 10)
    assert status == check_holdout.FAIL
    assert detail["short_pairs"] == {"MUSIC_PACK": 16}
    assert detail["assertable_provided"] is False
    # 给了 → ACTION_BEAT 仍要 30（它有 335），MUSIC_PACK 只要 16（它就只有 16）
    status, detail = check_holdout.gate_edge_types(
        pairs, cards, 30, 10, assertable={"ACTION_BEAT": 335, "MUSIC_PACK": 16})
    assert status == check_holdout.PASS
    assert detail["required_pairs_per_type"] == {"ACTION_BEAT": 30, "MUSIC_PACK": 16}
    # 覆盖不足仍然红：MUSIC_PACK 只交了 10 对时不许过
    status, _detail = check_holdout.gate_edge_types(
        {"ACTION_BEAT": 335, "MUSIC_PACK": 10}, cards, 30, 10,
        assertable={"ACTION_BEAT": 335, "MUSIC_PACK": 16})
    assert status == check_holdout.FAIL


def test_assertable_cap_never_raises_the_bar():
    """`assertable` 只能把要求**压到实际能给**，不许把某个类的要求抬到 30 以上。"""
    status, detail = check_holdout.gate_edge_types(
        {"TROPE": 40}, {"TROPE": 40}, 30, 10, assertable={"TROPE": 500})
    assert status == check_holdout.PASS
    assert detail["required_pairs_per_type"]["TROPE"] == 30


def test_same_value_required_and_forbidden_in_one_edge_is_rejected(tmp_path):
    rec = entry(must=["EMOTION_PACK:emotion=气急败坏,intensity=high,shot_size=中景,"
                      "forbid_shot_size=中景"])
    data = report(write(tmp_path, [rec]))
    assert data["gate_2_format"]["status"] == "fail"
    assert "自相矛盾" in " ".join(data["gate_2_format"]["problems"])


def test_different_value_required_and_forbidden_in_one_edge_is_accepted(tmp_path):
    """同 kind 的**不同取值**既要求又禁止不是矛盾，是合法的约束。

    反例（必须过门②）：`movement=crane_up` ＋ `forbid_movement=dolly_out`
    = "用 crane_up、别用 dolly_out"。旧判据是 kind 级的
    (`set(plain) & set(forbid)`)，把这条**完全合法**的边整条拒收；而
    `knowledge/hypergraph.edges.jsonl` 里实测有 8 条这样的边（抽取器照
    `OPTIONAL_MEMBERS[EMOTION_PACK]` 产出），它们因此**在 oracle 语法里
    根本写不出来** → 门⑩ 结构性未解析。这条对抗性用例把"kind 级 vs 取值级"
    钉死：改回 kind 级它就会红。
    """
    spec = ("EMOTION_PACK:emotion=气急败坏,intensity=high,"
            "movement=crane_up,forbid_movement=dolly_out")
    rec = entry(must=[spec], top1=[spec],
                q="情绪=气急败坏；强度=high；运镜=crane_up")
    data = report(write(tmp_path, [rec]))
    assert data["gate_2_format"]["status"] == "pass", data["gate_2_format"]["problems"]


def test_every_index_edge_can_be_written_as_a_spec():
    """**索引里每一条边都必须能被 oracle 语法写出来**，否则门⑩ 结构性不可达。

    这是本轮"同 kind 多值"缺陷（31 条归并边）与"同 kind 同时 allow+forbid"
    缺陷（8 条）的守卫：前者在规格语法里无法单值表达，后者被 kind 级 clash
    判据误杀。任一类回归，门⑩ 就会重新出现"构造上写不出来"的规格。
    """
    import pathlib as _pathlib

    root = _pathlib.Path(__file__).resolve().parents[1]
    edges_path = root / "knowledge" / "hypergraph.edges.jsonl"
    if not edges_path.is_file():  # pragma: no cover - 索引未入库时的历史状态
        pytest.skip("索引未入库")
    unexpressible = []
    for line in edges_path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if not line:
            continue
        edge = json.loads(line)
        kinds = [m[1] for m in edge["members"] if m[0] != "forbid"]
        if len(set(kinds)) != len(kinds):
            unexpressible.append((edge["edge_id"], "same_kind_multi_value"))
            continue
        slots = []
        for role, kind, node_id in edge["members"]:
            value = str(node_id).split(":", 1)[1]
            slots.append(("forbid_%s=%s" if role == "forbid" else "%s=%s") % (kind, value))
        try:
            check_holdout.parse_spec("%s:%s" % (edge["type"], ",".join(slots)))
        except check_holdout.EntryError as exc:
            unexpressible.append((edge["edge_id"], str(exc)[:60]))
    assert unexpressible == [], (
        "索引里有 oracle 语法写不出来的边，门⑩ 会对它们结构性未解析："
        f"{unexpressible[:6]}（共 {len(unexpressible)} 条）")


def test_must_values_must_come_from_the_vocabulary(tmp_path):
    """must 的取值不在词表里 → Q4 会静默归零，门③ 必须抓住。"""
    vocab = tmp_path / "vocab.json"
    narrowed = dict(VOCAB, lens=["35mm"])          # fixture 用的是 VALUE["lens"]
    vocab.write_text(json.dumps(narrowed, ensure_ascii=False), encoding="utf-8")
    data = report(write(tmp_path, valid_records()), "--vocab", str(vocab))
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert VALUE["lens"] in data["gate_3_seed_coverage"]["unknown_values"]["lens"]


def test_seed_support_gate_needs_more_than_one_use(tmp_path):
    """一个取值只被用了一次不算覆盖（要求 ≥N 个不同的 (卡片,查询) 对）。"""
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({"_fingerprint": "sha256:abc", "kinds": VOCAB},
                                ensure_ascii=False), encoding="utf-8")
    # 单条记录 → 每个取值只在 1 个 (卡片,查询) 对上出现 → 低于 --min-seed-support 2
    data = report(write(tmp_path, [q7_entry(1)]), "--vocab", str(vocab),
                  "--min-seed-support", "2", pilot=False)
    assert data["gate_3_seed_coverage"]["status"] == "fail"
    assert data["gate_3_seed_coverage"]["thin_values"]


def test_vocab_fingerprint_is_required_outside_pilot(tmp_path):
    """正式集必须把词表绑到索引构建上；缺指纹只能记 not_measured。"""
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_holdout.main([str(write(tmp_path, valid_records())),
                            "--vocab", str(vocab), "--json"])
    data = json.loads(buf.getvalue())
    assert data["gate_3_seed_coverage"]["status"] == "not_measured"
    assert "fingerprint" in data["gate_3_seed_coverage"]["reason"]


def test_vocab_fingerprint_form_is_accepted(tmp_path):
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({"_fingerprint": "sha256:abc", "kinds": VOCAB},
                                ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(sorted({r["from_card"] for r in valid_records()})),
                     encoding="utf-8")
    rc = check_holdout.main([str(write(tmp_path, valid_records())), "--pilot",
                             "--vocab", str(vocab), "--cards", str(cards),
                             "--extractor-family", "deepseek",
                             *index_args(tmp_path, valid_records())])
    assert rc == 0


# ---------------------------------------------------------------- 门⑧ 换族诚实性

def test_strong_independence_is_checked_against_the_extractor(tmp_path):
    """谎报 strong：标注族与抽取族相同却写 strong —— 必须被抓住。"""
    rec = q7_entry(1, review={"reviewed_by": "human", "verdict": "accepted"})
    rec["annotator"]["family"] = "deepseek"          # 与抽取器同族
    rec["independence"] = "strong"
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1"]), encoding="utf-8")
    data = report(write(tmp_path, [rec]), "--vocab", str(vocab), "--cards", str(cards),
                  "--extractor-family", "deepseek")
    assert data["gate_8_independence"]["status"] == "fail"
    assert data["gate_8_independence"]["liar_count"] == 1


def test_same_family_is_fine_when_declared_weak(tmp_path):
    """同厂不同型号 = weak，不算谎报（协议 §5.1 的滑杆）。"""
    rec = q7_entry(1, review={"reviewed_by": "human", "verdict": "accepted"})
    rec["annotator"]["family"] = "deepseek"
    rec["independence"] = "weak"
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1"]), encoding="utf-8")
    data = report(write(tmp_path, [rec]), "--vocab", str(vocab), "--cards", str(cards),
                  "--extractor-family", "deepseek")
    assert data["gate_8_independence"]["status"] == "pass"


def test_rule_generated_oracle_is_not_cross_family_evidence(tmp_path):
    """机械/规则通道（`family="rule"`）**必须判红**：它是索引自己派生出来的。

    实测事故：`holdout_pool --mechanical` 的 2191 条产物写 `family="rule"` ＋
    `independence="strong"`。旧门⑧ 只找"与抽取器同族的 strong"，于是判 **pass** ——
    而 `ORACLE_DECISION_v15.md` §二 白纸黑字写着门⑧ 存在的意义就是禁止这条绕过
    （"那等于自己考自己"）。`family != extractor_family` 是必要条件，不是充分条件。
    """
    rec = q7_entry(1, review={"reviewed_by": "human", "verdict": "accepted"})
    rec["annotator"]["family"] = "rule"          # 机械通道的标注族
    rec["independence"] = "strong"
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1"]), encoding="utf-8")
    data = report(write(tmp_path, [rec]), "--vocab", str(vocab), "--cards", str(cards),
                  "--extractor-family", "deepseek")
    assert data["gate_8_independence"]["status"] == "fail"
    assert data["gate_8_independence"]["non_model_families"] == ["rule"]
    assert data["gate_8_independence"]["liar_count"] == 0, (
        "它不是'同族谎报 strong'，而是'根本不是标注者'——两类缺陷必须分开记")


def test_missing_annotator_family_is_not_cross_family_evidence(tmp_path):
    """`annotator.family` 为空同样不算换族证据（缺字段不等于独立）。"""
    rec = q7_entry(1, review={"reviewed_by": "human", "verdict": "accepted"})
    rec["annotator"] = {k: v for k, v in rec["annotator"].items() if k != "family"}
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1"]), encoding="utf-8")
    data = report(write(tmp_path, [rec]), "--vocab", str(vocab), "--cards", str(cards),
                  "--extractor-family", "deepseek")
    assert data["gate_8_independence"]["status"] == "fail"
    assert data["gate_8_independence"]["non_model_families"] == [""]


def test_a_real_model_family_still_passes_gate_8(tmp_path):
    """正对照：异族模型标注必须放行，否则上面两条就只是"把门调红"。"""
    rec = q7_entry(1, review={"reviewed_by": "human", "verdict": "accepted"})
    rec["annotator"]["family"] = "zhipu"
    rec["annotator"]["model_id"] = "glm-4.7-flash"
    rec["independence"] = "strong"
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1"]), encoding="utf-8")
    data = report(write(tmp_path, [rec]), "--vocab", str(vocab), "--cards", str(cards),
                  "--extractor-family", "deepseek")
    assert data["gate_8_independence"]["status"] == "pass"
    assert data["gate_8_independence"]["non_model_families"] == []
    assert data["gate_8_independence"]["annotator_families"] == ["zhipu"]


def test_independence_gate_reads_the_extractor_manifest(tmp_path):
    """给 manifest 也能自动取抽取族（真实用法）。"""
    man = tmp_path / "hypergraph.manifest.json"
    man.write_text(json.dumps({"extractor": {"family": "deepseek", "model_id": "deepseek-chat"}}),
                   encoding="utf-8")
    rec = q7_entry(1, review={"reviewed_by": "human", "verdict": "accepted"})
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1"]), encoding="utf-8")
    data = report(write(tmp_path, [rec]), "--vocab", str(vocab), "--cards", str(cards),
                  "--extractor-manifest", str(man))
    assert data["gate_8_independence"]["status"] == "pass"
    assert data["gate_8_independence"]["extractor_family"] == "deepseek"


def test_independence_gate_discovers_the_repo_manifest(tmp_path):
    """不给参数时自动读 `knowledge/hypergraph.manifest.json`——抽取族是仓库产物，
    不该逼每个调用方再传一次；否则门⑧ 会永远停在 not_measured。"""
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_8_independence"]["status"] == "pass"
    assert data["gate_8_independence"]["extractor_family"] == "deepseek"


def test_independence_gate_is_not_measured_without_any_manifest(tmp_path, monkeypatch):
    """仓库根下也没有 manifest（例如脱离仓库跑）时才记 not_measured。"""
    monkeypatch.setattr(check_holdout, "_ROOT", tmp_path)
    data = report(write(tmp_path, [q7_entry()]))
    assert data["gate_8_independence"]["status"] == "not_measured"


def test_missing_vocab_file_is_a_clean_error(tmp_path):
    """坏路径必须给出 JSON 错误 + 退出码 1，不能抛 traceback。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = check_holdout.main([str(write(tmp_path, valid_records())), "--pilot",
                                 "--vocab", str(tmp_path / "nope.json"), "--json"])
    assert rc == 1
    assert "error" in json.loads(buf.getvalue())


# ---------------------------------------------------------------- 门⑥ 来源覆盖

def test_source_coverage_detects_missing_card(tmp_path):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps(["card_1", "card_2", "card_3"]), encoding="utf-8")
    data = report(write(tmp_path, [q7_entry()]), "--cards", str(cards))
    assert data["gate_6_sources"]["status"] == "fail"
    assert data["gate_6_sources"]["missing_cards"] == ["card_2", "card_3"]


# ---------------------------------------------------------------- 门① 总量 + CLI

def test_real_thresholds_fail_without_pilot(tmp_path):
    data = report(write(tmp_path, [q7_entry()]), pilot=False)
    assert data["gate_1_total"]["status"] == "fail"
    assert data["gate_1_total"]["min_entries"] == 1200


def test_missing_file_returns_one(tmp_path):
    assert check_holdout.main([str(tmp_path / "nope.jsonl")]) == 1


def test_empty_file_fails_every_per_entry_gate(tmp_path):
    """空集不得判过：0 条时格式门/边类门必须红，不能因为"没有条目可违反"而变绿。"""
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    data = report(path)
    assert data["gate_1_total"]["status"] == "fail"
    assert data["gate_2_format"]["status"] == "fail"
    assert data["gate_4_edge_types"]["status"] == "fail"
    assert data["overall"] == "fail"


def test_broken_json_line_is_reported(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "x"\n', encoding="utf-8")
    assert check_holdout.main([str(path)]) == 1


def test_human_readable_output_lists_gate_status(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        check_holdout.main([str(write(tmp_path, valid_records())), "--pilot"])
    text = buf.getvalue()
    assert "gate_1_total" in text
    assert "overall" in text


def test_out_writes_utf8_json_for_the_harness(tmp_path):
    """`--out` 必须由 Python 写 UTF-8（PowerShell 的 `>` 会写 UTF-16，下游 json.loads 会炸）。

    `tools/run_tests.ps1` 的 RK 证据钩子就是靠它把门报告落进
    `docs/evidence/<run-id>/holdout_gates.json` 的。
    """
    out = tmp_path / "gates.json"
    rc = full_run(tmp_path, valid_records(), "--out", str(out), "--json")
    assert rc == 0
    raw = out.read_bytes()
    assert not raw.startswith(b"\xff\xfe") and not raw.startswith(b"\xef\xbb\xbf")
    report = json.loads(raw.decode("utf-8"))
    assert report["overall"] == check_holdout.PASS
    assert report["gate_10_index_resolvable"]["status"] == check_holdout.PASS


def test_acceptance_chain_judges_gate_7_with_the_recorded_reviewer_classes():
    """门⑦ 在验收链里必须按**已记录的口径**判，否则机器复核做了也白做。

    2026-10-01 用户把 Q5/Q7/E3 交给 DeepSeek ＋ GLM 双模型（"我没有经验"），
    随后又明确授权机器侧承担这一层。协议 §5.6 的 `reviewed_by` 字段**没有被
    改写**：复核工具照旧写 `"llm-panel"`，报告里 `reviewed_by_class` 说清是谁裁的。

    这条不变量断过一次：链里跑门时**没有**传 `--reviewer-classes`，于是默认只认
    `human`，双模型复核的成果对 RK-13 完全不可见；而文档已经写成"验收链显式传"。
    机器的判据与文档分叉，正是这份文件存在的理由。
    """
    chain = (ROOT / "tools" / "run_tests.ps1").read_text(encoding="utf-8")
    calls = [line for line in chain.splitlines() if "check_holdout.py" in line]
    assert calls, "验收链必须跑一遍 held-out 门（不跑就是没测）"
    for line in calls:
        assert "--reviewer-classes human,llm-panel" in line, line
    # 反过来也要钉住：链里不许出现"只认人"的写法，那会把门⑦ 永久钉成红。
    offenders = [line for line in calls if "--reviewer-classes " in line
                 and "llm-panel" not in line]
    assert not offenders, offenders
