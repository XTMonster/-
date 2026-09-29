"""§6「重抽取成本」的取证：六元指纹 ＋ 两次构建逐字节一致（离线，不联网）。

规格点名的落点是 `tests/test_hypergraph_determinism.py`（执行文档 v1.4 §6 的
取证表）：**同一六元指纹两次运行，索引文件逐字节一致**。这里同时钉住三件事：

1. 指纹是"**恰好六个**分量"的纯函数——多一个少一个都报错，六个里任一个变了
   指纹就必须变（否则改了 prompt / 换了 chunk 策略会静默复用旧索引）；
2. 语料分量覆盖**正文**，不只是 id 列表（同样的 id、改过的正文也算新语料）；
3. 同输入两次构建，`edges/rejects/report/manifest` 四个文件逐字节相同。
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_hypergraph as bh  # noqa: E402

EDGES_FILE = ROOT / "knowledge" / "hypergraph.edges.jsonl"
NODES_FILE = ROOT / "knowledge" / "hypergraph.nodes.jsonl"
MANIFEST_FILE = ROOT / "knowledge" / "hypergraph.manifest.json"


def _read_jsonl(path: pathlib.Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _real_cards(limit: int = 2) -> list:
    """从入库卡片里挑两张带 `source_span` 的（`to_edge` 要求可定位的出处）。"""
    cards = []
    for path in sorted((ROOT / "knowledge" / "cards_generated").glob("*.jsonl")):
        for card in _read_jsonl(path):
            if card.get("source_span") and int(card["source_span"].get("start", -1)) >= 0:
                cards.append(card)
                if len(cards) >= limit:
                    return cards
    return cards


def _raw_edge_for(card_id: str, edge: dict) -> dict:
    """把一条已入库的超边摊回抽取器的**原始返回格式**（测试注入用）。"""
    return {
        "type": edge["type"],
        "members": [list(member) for member in edge["members"]],
        "source_kind": edge["source_kind"],
        "hardness": edge["hardness"],
        "confidence": edge["confidence"],
        "source_card": card_id,
    }


class _ScriptedClient:
    """确定性桩：每批都返回同一条原始超边。"""

    family = "deepseek"
    model_id = "test-model"
    model_version = "v0"

    def __init__(self, raw_edge: dict):
        self.raw_edge = raw_edge

    def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=2):
        return {"edges": [dict(self.raw_edge)]}


def _prepare(tmp_path, monkeypatch, cards) -> dict:
    """把 `run()` 落盘的四条路径与 VOCAB 指到 tmp；返回路径表。"""
    edge = _read_jsonl(EDGES_FILE)[0]
    node_ids = {member[2] for member in edge["members"]}
    nodes = [node for node in _read_jsonl(NODES_FILE) if node["node_id"] in node_ids]
    vocab_path = tmp_path / "vocab.json"
    vocab_path.write_text(json.dumps({"nodes": nodes, "vocab": {}}, ensure_ascii=False),
                          encoding="utf-8")
    paths = {name: tmp_path / name for name in
             ("hypergraph.edges.jsonl", "hypergraph.rejects.jsonl",
              "hypergraph.manifest.json", "report.json")}
    monkeypatch.setattr(bh, "ATOMS", tmp_path / "hypergraph.atoms.jsonl")
    monkeypatch.setattr(bh, "VOCAB", vocab_path)
    monkeypatch.setattr(bh, "EDGES", paths["hypergraph.edges.jsonl"])
    monkeypatch.setattr(bh, "REJECTS", paths["hypergraph.rejects.jsonl"])
    monkeypatch.setattr(bh, "MANIFEST", paths["hypergraph.manifest.json"])
    monkeypatch.setattr(bh, "REPORT", paths["report.json"])
    return {"paths": paths,
            "raw": _raw_edge_for(str(cards[0]["id"]), edge)}


# --------------------------------------------------------------------------- 指纹


def test_fingerprint_requires_exactly_the_six_components():
    components = {key: key + "-value" for key in bh.CACHE_KEY_FIELDS}
    assert len(components) == 6
    assert bh.fingerprint_of(components)
    with pytest.raises(ValueError):
        bh.fingerprint_of({**components, "extra": "x"})
    with pytest.raises(ValueError):
        bh.fingerprint_of({key: "v" for key in bh.CACHE_KEY_FIELDS[:-1]})


def test_every_component_changes_the_fingerprint():
    base = {key: "value" for key in bh.CACHE_KEY_FIELDS}
    baseline = bh.fingerprint_of(base)
    for key in bh.CACHE_KEY_FIELDS:
        mutated = dict(base)
        mutated[key] = "changed"
        assert bh.fingerprint_of(mutated) != baseline, f"{key} 没进指纹"


def test_corpus_digest_covers_content_not_only_ids():
    cards = [{"id": "c1", "content": "第一版", "chunk_id": "ch1",
              "source_ref": {"sha256": "aa"}},
             {"id": "c2", "content": "第二版", "chunk_id": "ch2",
              "source_ref": {"sha256": "bb"}}]
    same_but_reordered = [cards[1], cards[0]]
    assert bh.corpus_digest(cards) == bh.corpus_digest(same_but_reordered)

    edited = [dict(cards[0], content="改过的正文"), cards[1]]
    assert bh.corpus_digest(edited) != bh.corpus_digest(cards)

    new_chunk = [dict(cards[0], chunk_id="ch9"), cards[1]]
    assert bh.corpus_digest(new_chunk) != bh.corpus_digest(cards)

    new_source = [dict(cards[0], source_ref={"sha256": "zz"}), cards[1]]
    assert bh.corpus_digest(new_source) != bh.corpus_digest(cards)


def test_components_carry_the_recorded_settings():
    cards = _real_cards(1)
    components = bh.fingerprint_components(cards, _ScriptedClient({}))
    assert components["prompt_version"] == bh.PROMPT_VERSION
    assert components["decode"] == bh.DECODE
    assert "temperature=0" in components["decode"]
    assert components["model"].startswith("test-model@")
    assert components["schema_version"]
    assert components["chunker_version"]


# --------------------------------------------------------------------------- 逐字节


def test_two_runs_over_the_same_key_are_byte_identical(tmp_path, monkeypatch):
    cards = _real_cards(2)
    if not cards:
        pytest.skip("仓库里没有带 source_span 的卡片")
    setup = _prepare(tmp_path, monkeypatch, cards)
    paths = setup["paths"]

    bh.run(cards, {}, _ScriptedClient(setup["raw"]))
    first = {name: path.read_bytes() for name, path in paths.items()}
    manifest = json.loads(paths["hypergraph.manifest.json"].read_text(encoding="utf-8"))

    bh.run(cards, {}, _ScriptedClient(setup["raw"]))
    second = {name: path.read_bytes() for name, path in paths.items()}

    # 先证明这次构建**真的产出了东西**：否则"两个空文件逐字节相同"是空断言。
    written_edges = _read_jsonl(paths["hypergraph.edges.jsonl"])
    assert len(written_edges) >= 1
    assert written_edges[0]["edge_id"].startswith("hg:")
    assert written_edges[0]["type"] == setup["raw"]["type"]
    for name in paths:
        assert first[name] == second[name], f"{name} 两次构建不一致"
    assert set(manifest["cache_key"]) == set(bh.CACHE_KEY_FIELDS)
    assert bh.fingerprint_of(manifest["cache_key"]) == manifest["fingerprint"]


def test_manifest_does_not_leak_the_card_id_list_into_the_key():
    """六元指纹是**分量**的哈希，不是"把卡片 id 抄一份进去"。"""
    cards = _real_cards(1)
    components = bh.fingerprint_components(cards, _ScriptedClient({}))
    assert str(cards[0]["id"]) not in json.dumps(components, ensure_ascii=False)
    assert len(components["corpus_sha256"]) == 64


# --------------------------------------------------------------------------- 入库件


def test_committed_manifest_is_self_consistent():
    if not MANIFEST_FILE.exists():
        pytest.skip("仓库里还没有超图 manifest")
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    cache_key = manifest["cache_key"]
    assert set(cache_key) == set(bh.CACHE_KEY_FIELDS)
    assert bh.fingerprint_of(cache_key) == manifest["fingerprint"]
    # 五个"记录在别处"的分量必须与 manifest 自己的字段一致——否则同一事实两个真源
    extractor = manifest["extractor"]
    assert cache_key["model"] == f"{extractor['model_id']}@{extractor['model_version']}"
    assert cache_key["prompt_version"] == manifest["prompt_version"]
    assert cache_key["chunker_version"] == manifest["chunker_version"]
    assert cache_key["decode"] == manifest["decode"]
    assert cache_key["schema_version"] == manifest["schema_version"]


def test_committed_manifest_corpus_digest_matches_the_cards_on_disk():
    if not MANIFEST_FILE.exists():
        pytest.skip("仓库里还没有超图 manifest")
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    cards = bh.load_cards()
    if not cards:
        pytest.skip("仓库里没有生成卡")
    assert manifest["cache_key"]["corpus_sha256"] == bh.corpus_digest(cards)
    assert manifest["cards"] == len(cards)


# --------------------------------------------------------------------------- 并发


class _EchoClient:
    """回显本批第一张卡的 id：批与批的回复不同，所以"顺序"是可观测的。"""

    family = "deepseek"
    model_id = "echo-model"
    model_version = "v0"

    def chat_json(self, system, user, temperature, seed, num_ctx, key="", retries=2):
        import re

        ids = re.findall(r"### (\S+?)（", user)
        assert ids, "提示里没有卡片 id"
        return {"edges": [{
            "type": "SHOT_PATTERN", "source_card": ids[0], "source_kind": "theory",
            "hardness": "hard", "confidence": 0.8,
            "members": [["allow", "shot_size", "shot_size:MS"],
                        ["allow", "lens", "lens:50mm"],
                        ["qualifier", "headroom_policy", "headroom_policy:board"]],
        }]}


def _cards_in_one_domain(limit: int) -> list:
    path = sorted((ROOT / "knowledge" / "cards_generated").glob("*.jsonl"))[0]
    return [card for card in _read_jsonl(path) if card.get("source_span")][:limit]


def test_parallel_stage_one_keeps_the_serial_order(tmp_path, monkeypatch):
    """§2.3 / R51：第 1 段可并发，但**产物顺序必须与串行一致**（否则缓存指纹失效）。"""
    cards = _cards_in_one_domain(16)
    if len(cards) < 9:
        pytest.skip("生成卡不足两个批次")
    edge = _read_jsonl(EDGES_FILE)[0]
    node_ids = {member[2] for member in edge["members"]} | {"shot_size:MS", "lens:50mm",
                                                            "headroom_policy:board"}
    nodes = [node for node in _read_jsonl(NODES_FILE) if node["node_id"] in node_ids]
    vocab_path = tmp_path / "vocab.json"
    vocab_path.write_text(json.dumps({"nodes": nodes, "vocab": {}}, ensure_ascii=False),
                          encoding="utf-8")
    monkeypatch.setattr(bh, "VOCAB", vocab_path)
    for name in ("ATOMS", "EDGES", "REJECTS", "MANIFEST", "REPORT"):
        monkeypatch.setattr(bh, name, tmp_path / f"{name.lower()}.json")

    serial, _rejects, log1 = bh.extract(cards, {}, _EchoClient(), concurrency=1)
    parallel, _rejects2, log2 = bh.extract(cards, {}, _EchoClient(), concurrency=6)

    assert len(log1) >= 2, "至少要有两个批次，否则并发路径根本没被走到"
    assert [item.edge_id for item in serial] == [item.edge_id for item in parallel]
    assert [item.edge_id for item in serial] and \
        [item.sources for item in serial] == [item.sources for item in parallel]
    assert [entry["batch"] for entry in log1] == [entry["batch"] for entry in log2]


def test_rematch_rebuilds_from_the_persisted_atoms_without_the_model(tmp_path, monkeypatch):
    """第 2 段是纯函数：只换归并口径时不该重抽（`--rematch`）。"""
    cards = _real_cards(2)
    if not cards:
        pytest.skip("仓库里没有带 source_span 的卡片")
    setup = _prepare(tmp_path, monkeypatch, cards)
    monkeypatch.setattr(bh, "ATOMS", tmp_path / "atoms.jsonl")

    bh.run(cards, {}, _ScriptedClient(setup["raw"]))
    first = (tmp_path / "hypergraph.edges.jsonl").read_bytes()
    # 第二次不再经过任何模型调用：把 client 换成会抛异常的桩
    summary = bh.rematch(cards, {})
    assert summary["edges"] >= 1
    assert (tmp_path / "hypergraph.edges.jsonl").read_bytes() == first
