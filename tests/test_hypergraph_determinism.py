"""§6「重抽取成本」的取证：缓存指纹 ＋ 两次构建逐字节一致（离线，不联网）。

规格点名的落点是 `tests/test_hypergraph_determinism.py`（执行文档 v1.4 §6 的
取证表）：**同一指纹两次运行，索引文件逐字节一致**。这里同时钉住四件事：

1. 指纹是"**恰好 `CACHE_KEY_FIELDS` 这些**分量"的纯函数——多一个少一个都报错，
   任一个变了指纹就必须变（否则改了 prompt / 换了 chunk 策略 / 改了别名表
   会静默复用旧索引）；
2. 语料分量覆盖**正文**，不只是 id 列表（同样的 id、改过的正文也算新语料）；
3. 同输入两次构建，`edges/rejects/report/manifest` 四个文件逐字节相同。
4. §0.1b 缓存指纹行的第八格是**词表/别名表**：机械发现覆盖哪些名字（两边都钉死）、
   改别名表指纹必动、入库 manifest 的该格必须等于现算值。
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import subprocess
import sys

import pytest

from block_director.knowledge import hypergraph as hg

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_hypergraph as bh  # noqa: E402
from tools.kb_fetch import vocabulary as vocab  # noqa: E402

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
    #: 抽取缓存与它两本账也必须在 tmp 里：它们是**跨进程持久**的（落在 `work/`），
    #: 用例往里写会让另一条用例命中"为别的卡片写的回复"——实测抓到过
    #: （`card_a` 的一条条目让 `--only-missing` 那条用例整批返回空）。
    monkeypatch.setattr(bh, "ATOM_CACHE", tmp_path / "hypergraph.atom_cache.jsonl")
    monkeypatch.setattr(bh, "CACHE_STATS", tmp_path / "hypergraph.cache_stats.json")
    monkeypatch.setattr(bh, "ATOM_REJECTS", tmp_path / "hypergraph.atom_rejects.jsonl")
    monkeypatch.setattr(bh, "VOCAB", vocab_path)
    monkeypatch.setattr(bh, "EDGES", paths["hypergraph.edges.jsonl"])
    monkeypatch.setattr(bh, "REJECTS", paths["hypergraph.rejects.jsonl"])
    monkeypatch.setattr(bh, "MANIFEST", paths["hypergraph.manifest.json"])
    monkeypatch.setattr(bh, "REPORT", paths["report.json"])
    return {"paths": paths,
            "raw": _raw_edge_for(str(cards[0]["id"]), edge)}


# --------------------------------------------------------------------------- 指纹


def test_fingerprint_requires_exactly_the_declared_components():
    """分量表**写死**在这里，不是"跟着 `CACHE_KEY_FIELDS` 走"。

    写死是刻意的：分量表是 §0.1b 缓存指纹行的契约（"六元指纹 ＋ 校验门代码版本
    ＋ 词表指纹 ＋ **重绑规则版本**"，共 9 格），
    用 `CACHE_KEY_FIELDS` 去算断言等于让实现自己给自己出题——加了一个方差
    却忘了进哈希，这条用例照样绿。
    """
    components = {key: key + "-value" for key in bh.CACHE_KEY_FIELDS}
    assert tuple(bh.CACHE_KEY_FIELDS) == (
        "corpus_sha256", "model", "prompt_version", "chunker_version",
        "decode", "schema_version", "validation_rules_version",
        "vocabulary_fingerprint", "rebind_version")
    assert len(components) == 9
    assert bh.fingerprint_of(components)
    #: §2.3 的七元里**必须**含校验门代码版本：`--rematch` 只重跑第 2 段，
    #: 门一变、索引就变，指纹不跟着变就会把两份不同的索引指成同一个。
    assert "validation_rules_version" in bh.CACHE_KEY_FIELDS
    #: §0.1b 缓存指纹行的第八格：**词表/别名表**。别名表是落地判据的输入，
    #: 改它会改索引，而改的人不会想起换版本号（§20.4 的实测）。
    assert "vocabulary_fingerprint" in bh.CACHE_KEY_FIELDS
    #: **第九格（2026-10-07 加）**：机械重绑（`rebind/v1`）的规则版本。
    #: 重绑**改边的内容**（`sources[]`）却**不改任何输入** ⇒ 没有这一格，
    #: "重绑前／后"两份不同的索引会共用同一枚指纹——正是本模块 docstring
    #: 点名要防的那个洞（与第八格同一形状的教训）。
    assert "rebind_version" in bh.CACHE_KEY_FIELDS
    with pytest.raises(ValueError):
        bh.fingerprint_of({**components, "extra": "x"})
    with pytest.raises(ValueError):
        bh.fingerprint_of({key: "v" for key in bh.CACHE_KEY_FIELDS[:-1]})


def test_lexicon_discovery_covers_the_alias_tables_and_nothing_else():
    """机械发现的两边都要钉死：**该进的进、不该进的不进**。

    手抄一份"参与指纹的表"清单会漂移（v1.5 扩类暴露的正是"各抄一份"），
    所以实现按"全大写名字"机械发现；但机械发现必须被用例看着，否则它自己也会
    变成一处没人复核的隐式清单。
    """
    discovered = set(vocab.lexicon_tables())
    expected = {
        "EMOTIONS", "SHOT_SIZE_NAMES", "LIGHTING", "CAMERA_ANGLES",
        "COMPOSITION_RULES_ZH", "PACING_ZH", "VFX_ZH", "EXTRA_VFX", "ACTIONS",
        "SFX", "AXIS_TOPICS", "DELIVERIES", "MUSIC_STRATEGIES", "PROPS",
        "GENRE_ZH", "MOVEMENT_ZH", "HOLDOUT_KINDS", "UNQUERYABLE_KINDS",
        "HOLDOUT_CAP", "VFX_TYPES",
    }
    assert expected <= discovered, f"词表没被机械发现：{sorted(expected - discovered)}"
    #: 本模块之外还有**两张**表按角色并进来：索引侧别名表，与 `grounding` 的否定词表
    #: （后者是阶段二精确度门的另一半输入，`tests/test_lexicon_inputs.py` 钉住它）。
    assert discovered - expected == {"hg_value_aliases", "grounding_negation_cues"}, \
        f"机械发现混进了非词表常量：{sorted(discovered - expected)}"
    #: 反面控制：编译好的正则不是词表，模块/导入别名也不是。
    assert "_LENS_RE" not in discovered
    assert not {"json", "re", "common", "hg"} & discovered
    #: 这两张表都真的参与了判定，而都不在本模块的 globals 里，是**显式**并进去的
    #: （`LEXICON_EXTRA_TABLES`）。判据是角色不是模块：门读到的数据表都要进来。
    assert discovered & {"hg_value_aliases", "grounding_negation_cues"} == \
        {"hg_value_aliases", "grounding_negation_cues"}
    assert vocab.LEXICON_EXTRA_TABLES == ("hg_value_aliases", "grounding_negation_cues")


def test_lexicon_fingerprint_moves_when_an_alias_table_changes(monkeypatch):
    """§20.8 第 4 条的回归：**改别名表 ⇒ 指纹必须动**（前七格一个都不动）。

    两处别名表分别控制一次：`vocabulary` 侧的开放型词表，与索引侧的
    `hg.VALUE_ALIASES`。两次都必须让指纹移动。
    """
    baseline = vocab.lexicon_fingerprint()
    assert bh.fingerprint_components(
        _real_cards(1), _ScriptedClient({}))["vocabulary_fingerprint"] == baseline

    # 1) 开放型词表：与 §20.4 实测的 `安静` 同形状（给既有取值补一个别名）。
    monkeypatch.setattr(vocab, "EMOTIONS",
                        vocab.EMOTIONS + (("测试情绪", ("测试别名",)),))
    with_alias = vocab.lexicon_fingerprint()
    assert with_alias != baseline, "`EMOTIONS` 改了，词表指纹却没动"
    monkeypatch.undo()
    assert vocab.lexicon_fingerprint() == baseline, "撤销之后必须回到原指纹"

    # 2) 索引侧别名表：`static` → `固定` 这类映射是索引侧唯一那份。
    monkeypatch.setattr(hg, "VALUE_ALIASES", {**hg.VALUE_ALIASES, "测试": "测试"})
    assert vocab.lexicon_fingerprint() != baseline, "`VALUE_ALIASES` 改了，词表指纹却没动"


def test_rekey_manifest_recomputes_the_lexicon_component_from_code(tmp_path):
    """`rekey_manifest()` 对第八格**不读旧值，而是现算**。

    其余七格都能从 manifest 自己读回来（它们是"记录下来的设置"），只有这一格
    必须现算——它的用途就是"别名表被改过就露馅"，读旧值等于把洞留在原地。
    """
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    stale = dict(manifest)
    stale["cache_key"] = {**manifest["cache_key"], "vocabulary_fingerprint": "stale"}
    stale["fingerprint"] = bh.fingerprint_of(stale["cache_key"])
    target = tmp_path / "hypergraph.manifest.json"
    target.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")

    result = bh.rekey_manifest(target, cards=_real_cards(1))
    assert result["cache_key"]["vocabulary_fingerprint"] == vocab.lexicon_fingerprint()
    assert result["cache_key"]["vocabulary_fingerprint"] != "stale"
    rewritten = json.loads(target.read_text(encoding="utf-8"))
    assert bh.fingerprint_of(rewritten["cache_key"]) == rewritten["fingerprint"]


def test_committed_manifest_vocabulary_fingerprint_matches_the_tables():
    """入库索引的词表分量必须等于**现在**这份别名表算出来的值。

    这条是"同一指纹 ⇒ 同一索引"在别名表这一维上的闸门：改了别名表却没重签
    manifest，本用例当场变红，而不是等到某次检索结果漂移才被发现。
    """
    if not MANIFEST_FILE.exists():
        pytest.skip("仓库里还没有超图 manifest")
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    assert manifest["cache_key"]["vocabulary_fingerprint"] == vocab.lexicon_fingerprint()


def test_lexicon_fingerprint_is_stable_across_processes_and_hash_seeds():
    """缓存键必须**跨进程**稳定：`PYTHONHASHSEED` 不能影响它。

    词表里有字典与集合，它们的迭代顺序在随机哈希下会变。本函数对字典按键排序、
    对集合按元素排序，所以三档哈希种子必须给出同一个值——这不是"锦上添花"：
    一个随机的分量会让每次运行都判成"该重抽了"，或者更糟：**同一份索引被记成
    两枚指纹**（那正是这一整轮要关掉的那类洞）。
    """
    script = ("from tools.kb_fetch import vocabulary as v; "
              "print(v.lexicon_fingerprint())")
    digests = []
    for seed in ("0", "12345", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                             capture_output=True, text=True, check=True,
                             encoding="utf-8", errors="replace")
        digests.append(out.stdout.strip())
    assert len(set(digests)) == 1, digests
    assert digests[0] == vocab.lexicon_fingerprint()


def test_every_component_changes_the_fingerprint():
    base = {key: "value" for key in bh.CACHE_KEY_FIELDS}
    baseline = bh.fingerprint_of(base)
    for key in bh.CACHE_KEY_FIELDS:
        mutated = dict(base)
        mutated[key] = "changed"
        assert bh.fingerprint_of(mutated) != baseline, f"{key} 没进指纹"


def test_global_dedupe_collapses_cross_window_copies_and_unions_sources():
    """同一 `(type, members, scope)` 在索引里只能有一条。

    第 2 段是按**窗口**分组的，同一个耦合出现在两个窗口就会各留一条——实测
    852 条边里只有 708 个不同 `norm_key`（144 条副本）。§2.3 的去重键是全局的，
    所以补这一刀；副本的 `sources` 必须**并起来**（出处不能因为去重而丢）。
    """
    def make(source: str, occurrences: int) -> hg.HyperEdge:
        return hg.HyperEdge(
            type="EMOTION_PACK",
            members=(hg.Member("allow", "emotion", "emotion:荒诞"),
                     hg.Member("qualifier", "intensity", "intensity:high")),
            source_kind="theory", hardness="hard", occurrences=occurrences,
            confidence=0.6, confidence_max=0.6, sources=(source,),
            source_span={"chunk_id": "c1", "start": 0, "end": 4},
            extractor={"prompt_version": "test"}, provenance_kind="生成卡片")

    first, second = make("card_a", 2), make("card_b", 3)
    kept, report = bh.dedupe_by_norm_key([first, second])
    assert len(kept) == 1 and report["dropped"] == 1
    assert set(kept[0].sources) == {"card_a", "card_b"}, "副本的出处必须并起来"
    assert kept[0].occurrences == 5, "重复出现次数要相加"

    # scope 不同（理论 vs 教训）**不得**合并：去重键带 scope。
    lesson = hg.HyperEdge(**{**{f.name: getattr(first, f.name)
                                for f in dataclasses.fields(first)},
                             "source_kind": "lesson"})
    kept2, _report2 = bh.dedupe_by_norm_key([first, lesson])
    assert len(kept2) == 2


def test_only_missing_backfills_edges_without_losing_the_old_atoms(tmp_path, monkeypatch):
    """`--only-missing`：只抽"没有原子边"的卡，并且**并入**旧原子边。

    实测动机（2026-10-01）：整轮抽取后仍有 167 张生成卡（占 9.6%）一条原子边
    都没拿到——它们在批次里被模型跳过了。重抽整库既慢又不保证覆盖它们，
    而只喂这些卡一批，模型就会认真对待。
    """
    def card(ident: str, content: str) -> dict:
        # `title` 是批次提示的必填项：缺它时抽取器会以 `KeyError: 'title'` 整批
        # 拒收（这正是这条测试第一次跑出来的原因，记在这里免得下次再踩）。
        return {"id": ident, "title": ident, "content": content,
                "domain": "cinematography", "keywords": [], "tags": [], "emotion": "",
                "chunk_id": f"ch-{ident}",
                "source_span": {"chunk_id": f"ch-{ident}", "start": 0, "end": len(content)}}

    cards = [card("card_a", "低机位让人物显得高大。"), card("card_b", "长焦压缩空间。")]
    prepared = _prepare(tmp_path, monkeypatch, cards)
    vocab = json.loads((tmp_path / "vocab.json").read_text(encoding="utf-8"))["vocab"]
    raw_edge = _read_jsonl(EDGES_FILE)[0]

    # 第一趟：整轮抽取只拿到了 card_a 的边（card_b 被跳过）。
    bh.run([cards[0]], vocab, _ScriptedClient(_raw_edge_for("card_a", raw_edge)))
    assert bh.cards_with_atoms() == {"card_a"}

    # 第二趟：只补 card_b，并且不许把 card_a 的原子边冲掉。
    summary = bh.run(cards, vocab, _ScriptedClient(_raw_edge_for("card_b", raw_edge)),
                     extract_only=[cards[1]], keep_atoms=True)
    assert bh.cards_with_atoms() == {"card_a", "card_b"}
    # 两张卡的原子边是同一条耦合、来源不同：归并后应当合成**一条带两个来源**的边。
    assert summary["merge"]["merged_edges"] == 1
    assert summary["merge"]["multi_card_edges"] == 1
    manifest = json.loads(prepared["paths"]["hypergraph.manifest.json"].read_text(
        encoding="utf-8"))
    assert manifest["cards"] == 2, "指纹与卡片数仍按**全量**算，不是只算补抽的那张"


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
    #: 第八格不是"记录在 manifest 里的设置"，而是**从代码现算**的词表指纹：
    #: 它必须等于 `vocabulary.lexicon_fingerprint()`（生产者在词汇那一侧，只有一处）。
    assert components["vocabulary_fingerprint"] == vocab.lexicon_fingerprint()
    assert len(components["vocabulary_fingerprint"]) == 64


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
    #: **两个 `schema_version` 不是同一个量**（2026-10-07 重签时浮现的既有缺陷）：
    #:
    #: * `manifest["schema_version"]` 是**盖在边上的**那个版本（`hg.SCHEMA_VERSION`），
    #:   它进 `edge_id` 的公式（`hypergraph.edge_id`），所以它必须**逐字等于**
    #:   `hg.SCHEMA_VERSION`，否则边的 id 与自述互相矛盾（门⑩/⑥ 的自洽判据会红）；
    #: * `cache_key["schema_version"]` 是**缓存键的形态**：`hg.schema_version_with_fingerprint()`
    #:   （`hg/v2+<schema_fingerprint 前 12>`），用途是"闭集一改、指纹当场变"。
    #:
    #: 旧断言写的是"两者相等"——它在入库 manifest 上一直绿，只因为那份 manifest 是
    #: **旧代码**的产物（那时两处都写 `hg/v2`）；**任何一次真重建都会红**。
    #: 这里改成各自对**自己的生产者**断言（更严）：两格都要有出处，且**不再假装它们同义**。
    assert cache_key["schema_version"] == hg.schema_version_with_fingerprint()
    assert manifest["schema_version"] == hg.SCHEMA_VERSION
    #: 边上的自述必须与 manifest 顶层一致（两者都是"盖章的版本"）。
    edges_first = json.loads(
        (bh.EDGES).read_text(encoding="utf-8").split("\n")[0])
    assert edges_first["schema_version"] == manifest["schema_version"]


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
def test_index_cards_include_the_curated_handwritten_ones():
    """手写策展卡必须在抽取器的输入里。

    它们原先只存在于运行时的 `CARDS`，不在 `cards_generated/*.jsonl`，
    于是 `load_cards()` 把 132 张人工把关的硬规则整批漏在索引之外——实测
    held-out 涉及的 1075 张卡里有 268 张"一条边都没有"，示例正是
    `axis_180`／`axis_cross`／`comp_thirds`。
    """
    from block_director.knowledge.corpus import HANDWRITTEN_CARDS

    cards = bh.load_cards()
    ids = {str(card["id"]) for card in cards}
    handwritten = {card.id for card in HANDWRITTEN_CARDS}
    assert handwritten, "运行时应当有手写策展卡"
    assert handwritten <= ids, "手写卡没进抽取器输入：" + str(sorted(handwritten - ids)[:5])

    sample = next(card for card in cards if str(card["id"]) in handwritten)
    assert sample["source_span"]["chunk_id"].startswith("curated/")
    assert sample["source_span"]["start"] == 0
    assert sample["source_span"]["end"] == len(sample["content"]) > 0
    assert sample["provenance_kind"] == "权威文档"
    assert sample["source_ref"]["license"] == "OwnWork"


# --------------------------------------------------------------------------- #
# S0（PLAN_HYPERGRAPH_v3.md）：**schema 闭集**也必须进缓存指纹
#
# 现场：缓存指纹的第八格（词表/别名表）早已是"从代码现算"（§20.4 实测：补一个别名
# 让边数 540→539，而前七个分量一个都不动），**第六格 `schema_version` 却是手写常量**。
# 于是往 `QUALIFIER_KINDS` 里加一个 qualifier（计划里的 `seq_phase`／`carry_shots`）
# **不会**让缓存失效 ⇒ 断点续跑命中旧批次、新槽位从未被抽取，而一切照绿。
# --------------------------------------------------------------------------- #
def test_adding_a_schema_constant_moves_the_cache_key(monkeypatch):
    """往 schema 闭集里加一个键 ⇒ 第六格与整枚指纹**都必须变**（静默 no-op 的洞）。"""
    before = bh.fingerprint_components(_real_cards(1), _ScriptedClient({}))
    assert before["schema_version"].startswith(hg.SCHEMA_VERSION + "+"), before

    monkeypatch.setattr(hg, "QUALIFIER_KINDS", tuple(hg.QUALIFIER_KINDS) + ("seq_phase",),
                        raising=False)
    after = bh.fingerprint_components(_real_cards(1), _ScriptedClient({}))
    assert after["schema_version"] != before["schema_version"], (
        "加了 qualifier 而 schema 版本格没变：缓存会把新槽位当成旧代产物")
    assert bh.fingerprint_of(after) != bh.fingerprint_of(before), (
        "schema 变了而整枚指纹没变：旧 key 仍会被命中")


def test_the_schema_fingerprint_is_order_sensitive_and_deterministic():
    """闭集的**顺序**也是契约（表是闭集）：调序要换代；同一状态必须可复算。"""
    baseline = hg.schema_version_with_fingerprint()
    assert baseline == hg.schema_version_with_fingerprint()
    original = hg.QUALIFIER_KINDS
    try:
        hg.QUALIFIER_KINDS = tuple(reversed(original))
        assert hg.schema_version_with_fingerprint() != baseline, "调序没有换代"
    finally:
        hg.QUALIFIER_KINDS = original
    assert hg.schema_version_with_fingerprint() == baseline


def test_rekey_manifest_recomputes_the_schema_cell_from_code(tmp_path):
    """`rekey_manifest()` 对第六格**不读旧值，而是现算**（与第八格同一纪律）。"""
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    stale = {**manifest, "cache_key": {**manifest["cache_key"],
                                       "schema_version": "hg/v0"}}
    stale["fingerprint"] = bh.fingerprint_of(stale["cache_key"])
    target = tmp_path / "hypergraph.manifest.json"
    target.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")

    result = bh.rekey_manifest(target, cards=_real_cards(1))
    assert result["cache_key"]["schema_version"] == hg.schema_version_with_fingerprint()
    assert result["cache_key"]["schema_version"] != "hg/v0"
    rewritten = json.loads(target.read_text(encoding="utf-8"))
    assert bh.fingerprint_of(rewritten["cache_key"]) == rewritten["fingerprint"]


# --------------------------------------------------------------------------- #
# P14-106：S0 修的是"闭集没进指纹"，这一批修的是**同一形状、深一层**——
# `VALUE_DOMAINS`／`REQUIRED_MEMBERS`／`OPTIONAL_MEMBERS` 同样决定"收不收"
# （门⑨ 的取值面、必填成员、`forbid` 槽位白名单），却都不在第六格的载荷里。
# 于是 S2 要做的第一件事（给 `seq_phase` 填取值域）会静默命中旧批次。
# 判据按"做坏必须红"写：**改这三组里的任何一组，指纹都必须变**；
# 而闭集本身**一个字没动**——所以旧值不同**只能**来自覆盖面变大。
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("attr,mutate", [
    ("VALUE_DOMAINS", lambda table: {**table, "seq_phase": ("setup", "peak")}),
    ("REQUIRED_MEMBERS",
     lambda table: {**table, "EMOTION_PACK": table["EMOTION_PACK"] + (("allow", "genre"),)}),
    ("OPTIONAL_MEMBERS",
     lambda table: {**table, "TROPE": table["TROPE"] + (("forbid", "pacing"),)}),
])
def test_every_closed_set_that_decides_acceptance_moves_the_schema_key(attr, mutate):
    """三组"决定收不收"的闭集各自都必须有**鉴别力**（缺一组就是一个静默 no-op 洞）。"""
    baseline = hg.schema_version_with_fingerprint()
    original = getattr(hg, attr)
    try:
        setattr(hg, attr, mutate(original))
        assert hg.schema_version_with_fingerprint() != baseline, (
            f"改了 hg.{attr} 而 schema 指纹没变：这一组不在覆盖面上，"
            "缓存会把新判据当成旧代产物")
    finally:
        setattr(hg, attr, original)
    assert hg.schema_version_with_fingerprint() == baseline, "撤回后没有复原（不可复算）"


def test_filling_a_deferred_value_domain_is_not_a_silent_no_op():
    """S2 的第一步（把 `seq_phase` 的取值域填上）必须**当场**让第六格换代。

    这是本批扩围的**用途**证明：不是"多算了几格"，而是"S2 落地时不再静默"。
    用 S1a 那代与 S0 那代的字面量做锚（`tests/test_qualifier_lazy_keys.py` 记账）：
    `hg/v2+1a90c089bb8f` 是**含覆盖面**的这一代。
    """
    baseline = hg.schema_version_with_fingerprint()
    assert baseline == "hg/v2+1a90c089bb8f"
    original = hg.VALUE_DOMAINS
    try:
        hg.VALUE_DOMAINS = {**original, "seq_phase": ("setup", "escalation", "release")}
        assert hg.schema_version_with_fingerprint() != baseline
    finally:
        hg.VALUE_DOMAINS = original
    assert hg.VALUE_DOMAINS["seq_phase"] is None, "这组应当仍是「延后」状态"
    assert hg.schema_version_with_fingerprint() == baseline
