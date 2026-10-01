"""分片 held-out 的合并工具（`tools/holdout_merge.py`）的对拍测试。

合并是 oracle 的唯一入口，所以这里测的不是"能不能跑通"，而是四件会让
oracle 不可信的事：重复条目、不合规条目、id 编号、以及卡片全集的写法。
"""

from __future__ import annotations

import json
import pathlib

from tools import holdout_merge


def _entry(card: str, q: str, must: list, ident: str = "hq_0001") -> dict:
    return {
        "id": ident, "from_card": card, "q": q,
        "must": list(must), "top1": [must[0]], "never": [],
        "annotator": {"model_id": "glm-4.6", "family": "zhipu",
                      "model_version": "glm-4.6"},
        "independence": "strong",
    }


def _write(path: pathlib.Path, rows: list) -> pathlib.Path:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def test_merge_dedupes_validates_and_renumbers(tmp_path):
    # `intensity` 有查询键（`强度`）之后，`q` 必须把它写出来——否则
    # `holdout_merge` 会用门⑨ 的 `query_shortfall` 把这条判成"够不着自己的 must"
    # （这正是合并要拦的那类条目）。
    good = _entry("gen_cine_0001", "情绪=荒诞；运镜=固定；强度=high",
                  ["EMOTION_PACK:emotion=荒诞,intensity=high"])
    other = _entry("gen_cine_0002", "题材=film；情绪=荒诞",
                   ["TROPE:genre=film,emotion=荒诞"])
    # 取值域由门③判（`unknown_values`），合并这一步判的是**格式**：
    # 未知边类型、top1 不在 must 里、缺字段这类问题在这里就被拦下。
    broken = _entry("gen_cine_0003", "情绪=荒诞；强度=high", ["NOPE_PACK:emotion=荒诞"])
    shard_a = _write(tmp_path / "partial0.jsonl", [good, other])
    shard_b = _write(tmp_path / "partial1.jsonl", [good, broken])   # good 是重复

    report = holdout_merge.run([str(shard_a), str(shard_b)],
                               tmp_path / "holdout.jsonl",
                               cards=["gen_cine_0001", "gen_cine_0002", "gen_cine_0003"])

    assert report["raw"] == 4 and report["after_dedupe"] == 3
    assert report["valid"] == 2 and report["invalid"] == 1
    rows = [json.loads(line) for line in
            (tmp_path / "holdout.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert [row["id"] for row in rows] == ["hq_0001", "hq_0002"], "id 必须连续重编号"
    assert (tmp_path / "holdout.cards.json").exists()
    assert json.loads((tmp_path / "holdout.cards.covered.json").read_text(encoding="utf-8")) \
        == ["gen_cine_0001", "gen_cine_0002"]
    assert report["cards_missing"] == ["gen_cine_0003"], "没覆盖到的卡要如实报出来"


def test_merge_dry_run_writes_nothing(tmp_path):
    shard = _write(tmp_path / "partial0.jsonl",
                   [_entry("gen_cine_0001", "情绪=荒诞；强度=high",
                           ["EMOTION_PACK:emotion=荒诞,intensity=high"])])
    out = tmp_path / "holdout.jsonl"
    report = holdout_merge.run([str(shard)], out, dry_run=True, cards=["gen_cine_0001"])
    assert report["dry_run"] is True and report["valid"] == 1
    assert not out.exists() and not out.with_suffix(".cards.json").exists()


def test_merge_intercepts_rows_whose_edges_are_not_in_the_index(tmp_path):
    """**门⑩ 也要在合并口拦**（2026-10-01 补）。

    产出侧（`holdout_pool.finalise`）一直在拦"`must` 指向不存在的边"，但合并是
    oracle 的**唯一入口**：`holdout_fill` 那条自由标注通道、以及任何手工分片都
    绕过它。混进库之后，收尾时门⑩ 整份判红，**分不清是哪一批产出的**——正是
    这个文件头部注释担心的那件事。这里用一个真索引（`AXIS_RULE` 存在、
    `EMOTION_PACK` 不存在的那种）验证：不可解析的条目进 `unresolvable`，不进 `valid`。
    """
    from tools.holdout_score import load_graph
    import pathlib as _pathlib

    root = _pathlib.Path(__file__).resolve().parents[1]
    nodes = root / "knowledge" / "hypergraph.nodes.jsonl"
    edges = root / "knowledge" / "hypergraph.edges.jsonl"
    if not (nodes.is_file() and edges.is_file()):
        import pytest

        pytest.skip("索引未入库")
    graph = load_graph(nodes, edges)

    # 拿索引里**真实存在**的一条边当"好"条目，再把它改成不存在的取值当"坏"条目。
    spec = None
    for edge in graph.edges:
        members = [f"{m.kind}={str(m.node_id).split(':', 1)[1]}"
                   for m in edge.members if str(m.role) != "forbid"]
        if len(members) >= 2:
            spec = "%s:%s" % (edge.type, ",".join(members))
            break
    assert spec, "索引里找不到一条 ≥2 成员的边"
    # `q` 的形状由门⑨ 判，这里只关心门⑩，所以直接构造一条"够得着"的查询串：
    from tools import check_holdout as CH

    def _q_for(spec_text: str) -> str:
        #: 查询键的真源是 schema 的 `QUERY_KEYS`（`键 -> kind`，**不含** `禁<键>`）。
        #: 这里反查 kind → 键，让 `q` 覆盖 `must` 的每个可查询槽位。
        from block_director.knowledge import hypergraph as _hg

        key_for = {kind: zh for zh, kind in _hg.QUERY_KEYS.items()}
        pairs = []
        for part in spec_text.split(":", 1)[1].split(","):
            kind, value = part.split("=", 1)
            key = key_for.get(kind)
            if key:
                pairs.append(f"{key}={value}")
        return "；".join(pairs)

    good = _entry("gen_cine_0001", _q_for(spec), [spec])
    # 造一条"**格式合法、查询也够得着、但索引里没有这条边**"的条目：把最后一个
    # 成员换成本 kind 的**另一个合法取值**（仍在节点表里），`q` 同时写出这个新取值。
    # 这样门②（写法）与门⑨（够得着）都过，只有门⑩ 判得出来。
    etype, body = spec.split(":", 1)
    parts = body.split(",")
    kind, value = parts[-1].split("=", 1)
    others = sorted({str(node.node_id).split(":", 1)[1] for node in graph.nodes.values()
                     if getattr(node, "type", "") == kind
                     and str(node.node_id).split(":", 1)[1] != value})
    if not others:
        import pytest

        pytest.skip(f"节点表里 {kind} 只有一个取值，造不出'合法但不存在'的边")
    swapped = parts[:-1] + [f"{kind}={others[0]}"]
    bogus_spec = "%s:%s" % (etype, ",".join(swapped))
    bogus = _entry("gen_cine_0002", _q_for(bogus_spec), [bogus_spec])
    shard = _write(tmp_path / "partial0.jsonl", [good, bogus])
    report = holdout_merge.run([str(shard)], tmp_path / "out.jsonl",
                               cards=["gen_cine_0001", "gen_cine_0002"], graph=graph)
    assert report["index_available"] is True
    assert report["valid"] == 1, report
    assert report["unresolvable"] == 1, report
    rows = [json.loads(line) for line in
            (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert [row["from_card"] for row in rows] == ["gen_cine_0001"]
    # 索引不可用时**不假装通过**：低层 `merge(graph=None)` 如实记
    # `index_available: false`（`run()` 缺省会自动去装入库的索引，所以这里直接调
    # 低层函数验证那条分支）。
    _valid, counts = holdout_merge.merge([good, bogus], vocab=None, graph=None)
    assert counts["index_available"] is False


def test_merge_expands_directories_and_rejects_unknown_inputs(tmp_path):
    directory = tmp_path / "shards"
    directory.mkdir()
    _write(directory / "partial0.jsonl",
           [_entry("gen_cine_0001", "情绪=荒诞",
                   ["EMOTION_PACK:emotion=荒诞,intensity=high"])])
    assert [path.name for path in holdout_merge.expand([str(directory)])] == ["partial0.jsonl"]
    assert [path.name for path in
            holdout_merge.expand([str(directory / "partial*.jsonl")])] == ["partial0.jsonl"]
    assert holdout_merge.expand([str(tmp_path / "nope.jsonl")]) == []


def test_merge_main_returns_nonzero_when_nothing_valid(tmp_path, capsys):
    broken = _write(tmp_path / "partial0.jsonl",
                    [_entry("gen_cine_0001", "情绪=荒诞", ["NOPE:emotion=荒诞"])])
    code = holdout_merge.main(["--inputs", str(broken),
                               "--out", str(tmp_path / "holdout.jsonl")])
    assert code == 1
    assert json.loads(capsys.readouterr().out.splitlines()[0])["valid"] == 0


def test_merge_refuses_to_invent_cards_it_was_not_given(tmp_path):
    """`--cards` 是"这次要求标注的全量"；不给就用运行时的语料全集。"""
    shard = _write(tmp_path / "partial0.jsonl",
                   [_entry("gen_cine_0001", "情绪=荒诞；强度=high",
                           ["EMOTION_PACK:emotion=荒诞,intensity=high"])])
    report = holdout_merge.run([str(shard)], tmp_path / "holdout.jsonl",
                               cards=["gen_cine_0001", "gen_cine_0009"])
    assert report["cards"] == 2 and report["cards_covered"] == 1
    assert report["cards_missing"] == ["gen_cine_0009"]
    assert report["ghost_cards"] == []


#: 一份**自足**的冻结词表（不读仓库产物，测试才不会被语料增长带跑）。
VOCAB = {"emotion": ["荒诞", "压抑"], "shot_size": ["MS"], "lens": ["50mm"],
         "movement": ["固定"], "genre": ["film"]}


def test_merge_drops_a_query_that_cannot_reach_its_own_must_edge(tmp_path):
    """门⑨ 的判据必须在**合并**这一步就生效——它是 oracle 的唯一入口。

    一条 `must` 里凡是有查询键的槽位，`q` 里就必须逐字出现，否则这条查询
    永远召不回它自己的期望边（Q1/Q2 数学不可达）。
    """
    reachable = _entry("gen_cine_0001", "景别=MS；镜头=50mm",
                       ["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board"])
    unreachable = _entry("gen_cine_0002", "景别=MS",
                         ["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board"])
    shard = _write(tmp_path / "partial0.jsonl", [reachable, unreachable])

    report = holdout_merge.run([str(shard)], tmp_path / "holdout.jsonl",
                               cards=["gen_cine_0001", "gen_cine_0002"],
                               vocab=VOCAB)

    assert report["valid"] == 1 and report["unreachable"] == 1
    assert "50mm" in report["rejected_examples"][0]["reason"]
    rows = [json.loads(line) for line in
            (tmp_path / "holdout.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert [row["id"] for row in rows] == ["hq_0001"]
    assert rows[0]["from_card"] == "gen_cine_0001"


def test_merge_drops_values_outside_the_frozen_vocab(tmp_path):
    """门③ 的 unknown 侧同样在合并时生效（词表外取值 = 一个种子都挂不上）。"""
    bad = _entry("gen_cine_0001", "情绪=悲伤",
                 ["EMOTION_PACK:emotion=悲伤,intensity=high"])
    shard = _write(tmp_path / "partial0.jsonl", [bad])

    report = holdout_merge.run([str(shard)], tmp_path / "holdout.jsonl",
                               cards=["gen_cine_0001"], vocab=VOCAB)

    assert report["valid"] == 0 and report["unknown_values"] == 1
    assert "悲伤" in report["rejected_examples"][0]["reason"]


def test_merge_without_a_vocab_still_enforces_reachability():
    """没给词表时只跳过门③ 的 unknown 侧——门⑨ 的判据不依赖词表，照旧执行。"""
    rows = [_entry("gen_cine_0001", "景别=MS",
                   ["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board"])]
    valid, counts = holdout_merge.merge(rows, None)
    assert valid == [] and counts["unreachable"] == 1
    assert counts["unknown_values"] == 0


def test_merge_counts_every_rejection_bucket_separately():
    """三类拒收**分开记账**：格式（门②）、词表外取值（门③）、不可达（门⑨）。"""
    rows = [
        _entry("gen_cine_0001", "景别=MS；镜头=50mm",
               ["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board"]),
        _entry("gen_cine_0002", "景别=MS", ["NOPE:shot_size=MS"]),
        _entry("gen_cine_0003", "情绪=悲伤",
               ["EMOTION_PACK:emotion=悲伤,intensity=high"]),
        _entry("gen_cine_0004", "景别=MS",
               ["SHOT_PATTERN:shot_size=MS,lens=50mm,headroom_policy=board"]),
    ]
    valid, counts = holdout_merge.merge(rows, VOCAB)
    assert len(valid) == 1
    assert (counts["invalid"], counts["unknown_values"], counts["unreachable"]) == (1, 1, 1)
    assert counts["raw"] == 4 and counts["after_dedupe"] == 4
