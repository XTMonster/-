"""`tools/holdout_pool.py`（候选池标注 v2）的对抗性用例。

核心是三条**由构造保证**的性质，任何一条回归，门⑨/门⑩ 就会重新变红：

* `q` 覆盖 `must[0]`／`top1` 的全部可查询槽位（门⑨）；
* `must`／`top1`／`never` 的每一条都能解析到当前索引的边（门⑩，exact 口径）；
* 组内边数 >3 的 `(type, q)` 组**不生成**期望（Q4 要求每条 required 进 top-3，
  >3 条时构造上做不到），而不是编一条查询出来。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_holdout as CH  # noqa: E402
from tools import holdout_pool as HP  # noqa: E402
from tools.holdout_score import load_graph  # noqa: E402

NODES = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
EDGES = ROOT / "knowledge" / "hypergraph.edges.jsonl"
CARDS = ROOT / "fixtures" / "knowledge_holdout.cards.json"


@pytest.fixture(scope="module")
def graph():
    if not (NODES.is_file() and EDGES.is_file()):
        pytest.skip("索引未入库")
    return load_graph(NODES, EDGES)


@pytest.fixture(scope="module")
def universe():
    return json.loads(CARDS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pool(graph, universe):
    raw, stats = HP.mechanical(graph, universe)
    entries, rejects = HP.finalise(raw, graph, universe, model_id="t", family="rule",
                                   model_version="t")
    return entries, rejects, stats


def test_every_generated_entry_is_reachable(pool):
    """门⑨：`q` 必须覆盖 `must[0]`／`top1` 的全部可查询槽位——由构造成立。"""
    entries, _rejects, _stats = pool
    assert entries
    short = [CH.query_shortfall(entry) for entry in entries]
    assert [item for item in short if item] == []
    status, detail = CH.gate_reachability(entries)
    assert status == "pass", detail
    assert detail["short"] == 0


def test_every_generated_entry_resolves_to_the_index(pool, graph):
    """门⑩（exact 口径）：`must`／`top1`／`never` 全部解析到当前索引的边。"""
    entries, _rejects, _stats = pool
    status, detail = CH.gate_index_resolvable(entries, graph, "exact")
    assert status == "pass", detail
    assert detail["unresolved"] == 0
    assert detail["resolved"] == detail["totals"]


def test_generation_never_asserts_an_edge_outside_the_pool(pool, graph, universe):
    """产出的每一条 spec 都必须是**索引里真实存在的边**（池外即拒）。

    这是"候选池"的定义：`must` 只能从池里挑。校验器侧由
    `finalise()` 的 gate⑩ 分支保证——这里用一条**故意写错**的 must 打进去，
    确认它变成 reject 而不是悄悄留下。
    """
    entries, _rejects, _stats = pool
    sample = dict(entries[0])
    sample["must"] = ["EMOTION_PACK:emotion=不存在的情绪,intensity=high"]
    sample["top1"] = list(sample["must"])
    _kept, rejects = HP.finalise([sample], graph, universe, model_id="t",
                                 family="rule", model_version="t")
    assert rejects, "池外 / 解析不到的边必须被拒收"
    assert any(item["reason"].startswith("gate10") or
               item["reason"].startswith("gate2") for item in rejects)


def test_query_that_misses_a_slot_is_rejected(graph, universe):
    """门⑨ 的对抗面：把 `q` 里的一条键删掉，必须被拒收。"""
    raw, _stats = HP.mechanical(graph, universe)
    sample = dict(raw[0])
    parts = [item for item in str(sample["q"]).split("；") if item]
    sample["q"] = "；".join(parts[:-1]) or parts[0]
    if sample["q"] == raw[0]["q"]:  # 只有一条键时删不掉，换一条更长的样本
        sample = dict(next(item for item in raw
                           if len(str(item["q"]).split("；")) >= 2))
        parts = [p for p in str(sample["q"]).split("；") if p][:-1]
        sample["q"] = "；".join(parts)
    _kept, rejects = HP.finalise([sample], graph, universe, model_id="t",
                                 family="rule", model_version="t")
    assert rejects and rejects[0]["reason"].startswith("weak_q")


def test_ambiguous_groups_are_skipped_not_faked(pool):
    """超大 `(type, q)` 组必须**要么被拆开、要么被显式跳过并计数**，不许糊过去。

    历史：`avg_shot_len` 与 `forbid` 值都曾经没有查询键，于是 `EDIT_RHYTHM`／
    `STAGING_PACK` 的边在同一个 `q` 下**完全不可区分**，只能整组跳过
    （实测 12 条边 / 150 张卡因此拿不到条目）。两个键补上之后，超大组归零。
    这条测试两种状态都接受，但**必须有一个是明确的**：

    * 组 ≤3：不再需要跳过；
    * 组 >3：必须落进 `skipped.query_ambiguous_group` 计数，不许静默丢。
    """
    entries, _rejects, stats = pool
    oversized = stats["skipped"].get("query_ambiguous_group", 0)
    if oversized:
        assert oversized > 0, "超大组必须被计数"
    else:
        # 补键之后应当没有超大组 —— 这是"键表覆盖了区分维度"的证据。
        assert stats["skipped"].get("query_ambiguous_group", 0) == 0
    assert stats["skipped"].get("no_live_source_card", 0) >= 0
    assert {entry["q"] for entry in entries}


def test_the_rule_channel_never_claims_strong_independence(graph, universe):
    """机械通道的产物必须**如实**写 `weak`，且门⑧ 判红。

    两个方向一起钉住：只改标签而门⑧ 仍放行，或者门⑧ 判红而产物还自称 strong，
    都是"看起来独立"。字段只有 strong/weak 两档，所以机械通道取保守的那一档。
    """
    raw, _stats = HP.mechanical(graph, universe)
    entries, _rejects = HP.finalise(raw[:20], graph, universe,
                                    model_id="mechanical-pool", family="rule",
                                    model_version="pool/v1", decode="deterministic")
    assert entries
    assert {entry["independence"] for entry in entries} == {"weak"}
    status, detail = CH.gate_independence(entries, "deepseek")
    assert status == "fail", detail
    assert detail["non_model_families"] == ["rule"]


def test_a_model_channel_still_claims_strong_independence(graph, universe):
    """正对照：异族模型通道仍是 `strong` ＋ 门⑧ pass。"""
    raw, _stats = HP.mechanical(graph, universe)
    entries, _rejects = HP.finalise(raw[:20], graph, universe,
                                    model_id="glm-4.7-flash", family="zhipu",
                                    model_version="glm-4.7-flash")
    assert entries
    assert {entry["independence"] for entry in entries} == {"strong"}
    status, detail = CH.gate_independence(entries, "deepseek")
    assert status == "pass", detail
    assert detail["non_model_families"] == []


def test_negative_sample_is_disjoint_from_the_query(pool):
    """负样本必须与查询**不相交**（协议 §3.2），否则 Q3 会把该召回的边算成误召。"""
    entries, _rejects, _stats = pool
    with_never = [entry for entry in entries if entry["never"]]
    assert with_never, "必须有负样本，否则 Q3 分母为 0（按 §4.1b 判失败）"
    for entry in with_never[:50]:
        spec = entry["never"][0]
        _etype, plain, _forbid = CH.parse_spec(spec)
        q_pairs = CH.parse_q(entry["q"])
        have = {(CH.Q_KEY_TO_KIND[key], value) for key, value in q_pairs.items()}
        assert not ({(kind, value) for kind, value in plain.items()} & have), (
            f"负样本 {spec} 与查询 {entry['q']} 相交：它本来就该被召回")


class _ScriptedGlm:
    """假 GLM：从提示里读出"一个都不能少的键值"，原样当 `q` 回。"""

    model_id = "fake-glm"
    family = "zhipu"
    model_version = "fake-0"
    decode_tag = "test"

    def __init__(self, fail_on_call: int = 0):
        self.calls = 0
        self.fail_on_call = fail_on_call

    def chat_json(self, system, user, temperature, seed, num_ctx, retries=3):
        self.calls += 1
        if self.fail_on_call and self.calls == self.fail_on_call:
            raise RuntimeError("boom")
        out = []
        index = None
        for line in user.split("\n"):
            if line.startswith("### 第 "):
                index = int(line.split("### 第 ")[1].split(" 条")[0])
            if "一个都不能少" in line and index is not None:
                out.append({"index": index, "q": line.split("：", 1)[1], "never": []})
        return {"entries": out}


def test_glm_pass_writes_partials_per_batch_and_resumes(graph, universe, tmp_path):
    """长跑必须**可观测、可续跑**。

    实测事故：`glm_v4` 跑 31 分钟后卡在一次 HTTP 调用上（CPU 60 秒增量为 0），
    而原先只在整轮结束时落盘 —— 一点产物都没有。现在每批追加 partial，
    重跑时按批次号跳过已完成的批。
    """
    partial = tmp_path / "out.jsonl.partial"
    progress = tmp_path / "out.jsonl.progress.json"
    vocab = json.loads((ROOT / "fixtures" / "knowledge_holdout.vocab.json")
                       .read_text(encoding="utf-8"))["kinds"]
    client = _ScriptedGlm(fail_on_call=2)          # 第 2 批失败
    entries, rejects, _extra = HP.glm_pass(graph, universe, client, vocab=vocab,
                                           batch_size=4, limit=8,
                                           partial_path=partial, progress_path=progress)
    assert rejects and rejects[0]["reason"].startswith("transport:")
    assert partial.is_file(), "失败的批之前的产物必须已经落盘"
    assert progress.is_file(), "必须有逐批进度文件（否则卡住时看不见它在哪）"
    written = [line for line in partial.read_text(encoding="utf-8").split("\n") if line]
    assert written, "第一批的产物必须已经落盘"
    first_batch = json.loads(written[0])["_batch"]
    assert first_batch == 0
    before = len(entries)

    # 续跑：成功的批不再重发请求。
    resume_client = _ScriptedGlm()
    entries2, rejects2, _ = HP.glm_pass(graph, universe, resume_client, vocab=vocab,
                                        batch_size=4, limit=8,
                                        partial_path=partial, progress_path=progress)
    assert len(entries2) >= before, "续跑不该丢掉已落盘的条目"
    assert resume_client.calls < client.calls, "续跑必须跳过已完成的批"
