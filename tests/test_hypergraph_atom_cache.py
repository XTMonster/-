"""§2.3 的**抽取结果缓存／断点续跑**：把"逐字节可复现"从文档搬到代码。

为什么有这一条（2026-10-02，`ACCEPTANCE_STATUS.md` §28.1）：`build_hypergraph`
原先**没有原子边缓存**，正常构建每次都对全部 chunk 重新调模型，而抽取器不可复现
——同一份语料连建两次得到 `edges 662 / atoms 2527` 与 `edges 667 / atoms 2484`。
于是门⑥ 的覆盖率量的是"这一轮抽样运气如何"。

判据（执行文档，不是本文件自定）：

* `改进执行文档v1.4.md:1704`：**"缓存命中时（不重抽取）索引文件逐字节一致"**；
* `改进执行文档v1.4.md:903`：断点续跑绑在指纹上；manifest 顶层存 `fingerprint` 与
  `chunks:[{chunk_id, sha256, status, edges, reject_reason, extractor_fingerprint}]`；
  顶层指纹不等 ⇒ 忽略全部 `done`；相等才按 chunk sha256 跳过 `done`。

这里钉住的是**行为**，不是实现细节：真抽取路径上"第二次构建"必须一个模型调用都
不发、且四个产物文件逐字节相同——用的桩故意是**不可复现**的（每次调用回不同的边），
所以一旦缓存没命中，字节必然不同、用例当场变红。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from block_director.knowledge import hypergraph as hg

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import atom_cache as ac  # noqa: E402
from tools.kb_fetch import build_hypergraph as bh  # noqa: E402

NODES_FILE = ROOT / "knowledge" / "hypergraph.nodes.jsonl"

#: 两张**自造**卡：v16 要求"每个必填槽位的依据逐字落在被命名的那张卡里"，
#: 而"依据里要出现这个取值本身"（`pacing:long` 的中文面是"长"）。用真语料里的卡
#: 就得反过来挑"哪张卡恰好写了这两个槽位"，那是本文件不该承担的事。
TEXT_T1 = "长镜头要把节奏放长，拍摄时间也要留足，观众才有余量看清调度。"
TEXT_T2 = "节奏放长时，镜头里的信息要一次给足，不能让观众反复找焦点。"


def _read_jsonl(path: pathlib.Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _cards() -> list:
    return [
        {"id": "t1", "domain": "anime", "title": "长镜头", "content": TEXT_T1,
         "source_span": {"chunk_id": "chunk#1", "start": 0, "end": len(TEXT_T1)}},
        {"id": "t2", "domain": "anime", "title": "节奏", "content": TEXT_T2,
         "source_span": {"chunk_id": "chunk#1", "start": 0, "end": len(TEXT_T2)}},
    ]


#: 变体的取值换成同 kind 的另一个合法取值（两者在节点表里都有，且都没有中文面，
#: 所以"依据要提到取值"这一条对它们不构成要求）——两条边在索引里都是真边。
FLIP_VALUE = "avg_shot_len:3-8s"


def _raw_edge(card_id: str = "t1", *, flipped: bool = False) -> dict:
    """抽取器的**原始返回格式**：成员是四元组，第 4 项是逐字依据（v15/v16）。"""
    return {
        "type": "EDIT_RHYTHM",
        "members": [["allow", "pacing", "pacing:long", "长镜头要把节奏放长"],
                    ["qualifier", "avg_shot_len",
                     FLIP_VALUE if flipped else "avg_shot_len:>8s",
                     "拍摄时间也要留足"]],
        "source_kind": "theory", "hardness": "hard", "confidence": 0.7,
        "source_card": card_id,
    }


class _FlippingClient:
    """**故意不可复现**的桩：第 n 次调用回第 n 个变体。

    真抽取路径上如果第二次构建仍然调了模型，它就会拿到与第一次不同的边——
    "逐字节一致"这条断言当场会红。所以它同时是"缓存命中"和"复现"两个判据的探针。
    """

    family = "deepseek"
    model_id = "test-model"
    model_version = "v0"

    def __init__(self, card_id: str = "t1"):
        self.card_id = card_id
        self.calls = 0

    def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=2):
        self.calls += 1
        #: 奇数调用给原边、偶数调用给换过取值的边：真抽取路径上"第二次构建"如果
        #: 还调模型，拿到的就是**另一条边**，字节必然不同。
        return {"edges": [_raw_edge(self.card_id, flipped=self.calls % 2 == 0)]}


def _prepare(tmp_path, monkeypatch) -> dict:
    """把 `run()` 的五条落盘路径、词表与缓存指到 tmp；返回路径表。"""
    wanted = {"pacing:long", "avg_shot_len:>8s", FLIP_VALUE}
    nodes = [node for node in _read_jsonl(NODES_FILE) if node["node_id"] in wanted]
    assert {node["node_id"] for node in nodes} == wanted, "节点表里缺本例要用的取值"
    vocab_path = tmp_path / "vocab.json"
    vocab_path.write_text(json.dumps({"nodes": nodes, "vocab": {}}, ensure_ascii=False),
                          encoding="utf-8")
    paths = {name: tmp_path / name for name in
             ("hypergraph.edges.jsonl", "hypergraph.rejects.jsonl",
              "hypergraph.manifest.json", "report.json", "atom_rejects.jsonl",
              "atoms.jsonl", "atom_cache.jsonl")}
    monkeypatch.setattr(bh, "ATOMS", paths["atoms.jsonl"])
    monkeypatch.setattr(bh, "VOCAB", vocab_path)
    monkeypatch.setattr(bh, "EDGES", paths["hypergraph.edges.jsonl"])
    monkeypatch.setattr(bh, "REJECTS", paths["hypergraph.rejects.jsonl"])
    monkeypatch.setattr(bh, "MANIFEST", paths["hypergraph.manifest.json"])
    monkeypatch.setattr(bh, "REPORT", paths["report.json"])
    monkeypatch.setattr(bh, "ATOM_REJECTS", paths["atom_rejects.jsonl"])
    monkeypatch.setattr(bh, "ATOM_CACHE", paths["atom_cache.jsonl"])
    return {"paths": paths}


def _bytes(paths) -> dict:
    return {name: (path.read_bytes() if path.is_file() else b"")
            for name, path in paths.items()}


# ------------------------------------------------------------------ 模块：缓存键


def test_the_cache_key_moves_only_when_an_input_moves():
    """提示 / 模型 / 温度 / 提示版本 / 解码行——五个输入各改一个，键都必须变。

    第六个"输入"是**提示文本本身**：它已经把词表、节点表与卡片正文含进去了，
    所以"改词表不换版本号"这种漂移在这里就露馅。
    """
    base = dict(prompt_sha256="p", model="m@v", temperature=0.0,
                prompt_version="extract/v0", decode="temperature=0;seed=0")
    key = ac.unit_key(**base)
    assert ac.unit_key(**base) == key, "同样的输入必须算同一个键"
    for field, value in (("prompt_sha256", "q"), ("model", "m@v2"),
                         ("temperature", 0.2), ("prompt_version", "extract/v1"),
                         ("decode", "temperature=0.2;seed=0")):
        assert ac.unit_key(**{**base, field: value}) != key, f"{field} 变了键却没变"
    assert ac.unit_key(**{**base, "temperature": 0}) == key, (
        "`0` 与 `0.0` 是同一个温度，不能因为数值类型不同而假性未命中")
    #: 分隔符必须挡住拼接歧义：("ab","c") 与 ("a","bc") 不是同一段提示。
    assert ac.prompt_digest("ab", "c") != ac.prompt_digest("a", "bc")


def test_the_cache_only_counts_successes_as_hits(tmp_path):
    """传输失败**不进缓存**：它不该被记成"这批抽过了"，否则失败会被固化下来。"""
    cache = ac.AtomCache(tmp_path / "cache.jsonl", "fp")
    cache.put("k-error", {"status": "error", "reject_reason": "URLError: down"})
    cache.put("k-done", {"status": "done", "reply": {"edges": []}})
    assert cache.get("k-error") is None
    assert cache.get("k-missing") is None
    assert cache.get("k-done")["reply"] == {"edges": []}
    assert cache.stats["hit"] == 1 and cache.stats["miss"] == 2


def test_hits_are_decided_by_the_unit_key_not_by_the_run_fingerprint(tmp_path):
    """命中判据是**单元键**，不是六元指纹——"门改了不必重抽"（§6）靠的就是这一条。

    指纹里那几格**不影响原样回复**的分量（校验门版本、别的 chunk 的正文）换了，
    单元键（提示 ＋ 模型 ＋ 温度 ＋ 解码行）没换 ⇒ 照样命中；反过来单元键换了
    （提示变了、卡片正文变了、模型或温度变了）就一定未命中——判据比六元指纹更细。
    """
    path = tmp_path / "cache.jsonl"
    first = ac.AtomCache(path, "fp-old")
    first.put("k", {"status": "done", "reply": {"edges": []}})
    first.save()
    #: 换了校验门 ⇒ 六元指纹变，但这一批的提示没变：缓存仍然命中（审计字段跟着更新）。
    later = ac.AtomCache(path, "fp-new")
    assert later.get("k") is not None
    assert later.entries["k"]["fingerprint"] == "fp-old", "读到的是写它时的那枚指纹"
    later.save()
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["fingerprint"] == (
        "fp-new"), "落盘时盖章成当前这一轮的指纹"


def test_saving_is_byte_stable_regardless_of_insertion_order(tmp_path):
    """缓存文件自己也不许抖：同一批条目的两种插入顺序必须落出同样的字节。"""
    one, two = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    rows = [("k1", {"status": "done", "reply": {"edges": []}}),
            ("k2", {"status": "done", "reply": {"edges": [1]}})]
    a = ac.AtomCache(one, "fp")
    for key, row in rows:
        a.put(key, row)
    a.save()
    b = ac.AtomCache(two, "fp")
    for key, row in reversed(rows):
        b.put(key, row)
    b.save()
    assert one.read_bytes() == two.read_bytes()


# ------------------------------------------------------------------ 模块：账与续跑


def _ledger_cards():
    return [
        {"id": "c1", "content": "甲", "source_span": {"chunk_id": "k1"}},
        {"id": "c2", "content": "乙", "source_span": {"chunk_id": "k1"}},
        {"id": "c3", "content": "丙", "source_span": {"chunk_id": "k2"}},
    ]


def _edge(node_id: str, sources):
    """一条最小可用的超边：`edge_id` 是**算出来的**（不是构造参数）。"""
    return hg.HyperEdge(type="EMOTION_PACK",
                        members=(hg.Member(role="allow", kind="emotion",
                                           node_id=node_id),),
                        sources=tuple(sources))


def test_the_chunk_ledger_has_the_six_fields_and_attributes_edges_by_chunk():
    units = [{"key": "u1", "status": "done", "cards": ["c1", "c2", "c3"]}]
    edge = _edge("emotion:荒诞", ["c1", "c3"])
    ledger = ac.chunk_ledger(_ledger_cards(), units, [edge])
    assert [row["chunk_id"] for row in ledger] == ["k1", "k2"]
    for row in ledger:
        assert set(row) == {"chunk_id", "sha256", "status", "edges",
                            "reject_reason", "extractor_fingerprint"}
        assert row["status"] == "done" and row["reject_reason"] is None
    assert ledger[0]["edges"] == [edge.edge_id] and ledger[1]["edges"] == [edge.edge_id]
    assert ledger[0]["sha256"] != ledger[1]["sha256"], "两个 chunk 的正文不同"


def test_the_ledger_records_errors_and_pending_chunks():
    """没抽到的 chunk 不能悄悄写成 `done`：`error` 带原因、没被任何批次覆盖的是 `pending`。"""
    units = [{"key": "u1", "status": "error", "cards": ["c1"], "reject_reason": "URLError"}]
    ledger = ac.chunk_ledger(_ledger_cards(), units, [])
    by_chunk = {row["chunk_id"]: row for row in ledger}
    assert by_chunk["k1"]["status"] == "error"
    assert "URLError" in by_chunk["k1"]["reject_reason"]
    assert by_chunk["k2"]["status"] == "pending"
    #: 后续一个成功的批次救回来 ⇒ 这一格必须是 `done`（`error` 不许覆盖成功）。
    saved = ac.chunk_ledger(
        _ledger_cards(),
        units + [{"key": "u2", "status": "done", "cards": ["c1"], "reject_reason": None}],
        [])
    assert {row["chunk_id"]: row["status"] for row in saved}["k1"] == "done"


def test_the_extractor_fingerprint_moves_when_a_covering_unit_changes():
    """一个 chunk 的 `extractor_fingerprint` 由**覆盖它的批次键**决定（不是写死的）。"""
    cards = _ledger_cards()
    a = ac.chunk_ledger(cards, [{"key": "u1", "status": "done", "cards": ["c1"]}], [])
    b = ac.chunk_ledger(cards, [{"key": "u2", "status": "done", "cards": ["c1"]}], [])
    assert a[0]["extractor_fingerprint"] != b[0]["extractor_fingerprint"]


def test_resume_skips_done_chunks_only_when_the_sha_still_matches():
    """§2.3 的续跑判据：`done` **且** sha 不变才跳；正文一变必须重抽。"""
    cards = _ledger_cards()
    ledger = ac.chunk_ledger(cards, [{"key": "u1", "status": "done", "cards": ["c1"]}], [])
    skip, redo = ac.resume_plan(ledger, ledger)
    assert skip == ["k1"] and sorted(redo) == ["k2"], "k2 从没抽过（pending）"

    moved = ac.chunk_ledger(
        [{"id": "c1", "content": "甲改过了", "source_span": {"chunk_id": "k1"}}],
        [{"key": "u1", "status": "done", "cards": ["c1"]}], [])
    skip2, redo2 = ac.resume_plan(ledger, moved)
    assert skip2 == [] and redo2 == ["k1"], "正文变了还跳过 = 拿旧边冒充新语料"


# ------------------------------------------------------------------ 集成：真抽取路径


def test_a_second_build_with_the_same_corpus_never_calls_the_model(tmp_path, monkeypatch):
    """**核心判据**：同一份语料第二次构建 ⇒ 0 次模型调用 ＋ 四个产物逐字节一致。"""
    cards = _cards()
    prep = _prepare(tmp_path, monkeypatch)
    client = _FlippingClient()

    first = bh.run(cards, {}, client)
    assert client.calls > 0, "冷缓存必须真调模型"
    assert first["report"]["passed"], first["report"]
    before = _bytes(prep["paths"])
    assert prep["paths"]["atom_cache.jsonl"].is_file(), "抽取结果要落盘成缓存"
    ledger = json.loads(prep["paths"]["hypergraph.manifest.json"]
                        .read_text(encoding="utf-8"))["chunks"]
    assert [row["chunk_id"] for row in ledger] == ["chunk#1"]
    assert ledger[0]["status"] == "done" and ledger[0]["edges"], (
        "per-chunk 账要把这一轮抽出来的边记在它来源的 chunk 上")

    calls_after_first = client.calls
    second = bh.run(cards, {}, client)
    assert client.calls == calls_after_first, (
        "同一指纹下第二次构建不该再调模型（§2.3：缓存命中时不重抽）——"
        "调了就说明缓存没接上")
    assert _bytes(prep["paths"]) == before, (
        "缓存命中时索引文件必须逐字节一致（§6「重确定性下降」的回归基线）")
    assert second["report"]["passed"] == first["report"]["passed"]


def test_a_changed_card_body_invalidates_the_cache(tmp_path, monkeypatch):
    """语料正文一变，指纹与缓存键都要动 ⇒ 必须重抽，不许拿旧边冒充新语料。"""
    cards = _cards()
    _prepare(tmp_path, monkeypatch)
    client = _FlippingClient()
    bh.run(cards, {}, client)
    calls_after_first = client.calls
    edited = [dict(cards[0]), dict(cards[1])]
    edited[1]["content"] = str(edited[1]["content"]) + "（2026-10-02 追加一句）"
    bh.run(edited, {}, client)
    assert client.calls > calls_after_first, "语料改了还命中缓存 = 缓存键漏了正文"


def test_the_replace_path_re_asks_the_model_and_refreshes_the_cache(tmp_path, monkeypatch):
    """`--replace-cards` 是**清洗**路径：它必须重新问模型，否则坏的边永远清不掉。"""
    cards = _cards()
    _prepare(tmp_path, monkeypatch)
    client = _FlippingClient()
    bh.run(cards, {}, client)
    calls_after_first = client.calls
    wanted = [str(card["id"]) for card in cards]
    bh.run(cards, {}, client, extract_only=cards, replace_atoms_for=wanted)
    assert client.calls > calls_after_first, (
        "清洗路径被缓存挡住 ⇒ 旧的（要清的）边会被原样端回来")


def test_the_manifest_carries_the_per_chunk_ledger_of_the_shipped_index():
    """§2.3 的 per-chunk manifest 必须落在**入库**的 manifest 里。

    "没写"与"没跑"要分得开：没有这本账，断点续跑就无从谈起，而 manifest 会看起来
    一切正常。
    """
    manifest_path = ROOT / "knowledge" / "hypergraph.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ledger = manifest.get("chunks")
    assert isinstance(ledger, list) and ledger, (
        "manifest 没有 `chunks` 账：§2.3 的断点续跑（按 chunk sha256 跳过 done）"
        "在实现里就没有落点")
    for row in ledger:
        assert set(row) == {"chunk_id", "sha256", "status", "edges",
                            "reject_reason", "extractor_fingerprint"}
        assert row["status"] in ("done", "error", "pending")
    #: 账必须对着**活语料**：每张卡的 chunk 都在账里（否则"跳过 done"会误判）。
    cards = bh.load_cards()
    known = {row["chunk_id"] for row in ledger}
    missing = sorted({ac.chunk_id_of(card) for card in cards} - known)
    assert not missing, f"这些 chunk 不在 per-chunk 账里：{missing[:5]}"
