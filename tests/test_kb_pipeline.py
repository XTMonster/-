"""P14-1 语料管线的对抗性测试（执行文档 v1.4 §2.3c/§2.3d）。

全部离线：标注用 `scripted` 后端，抓取只用 `mode: manual` 的自撰笔记。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from tools.kb_fetch import (annotate, chunk, common, dedupe, extract_text, fetch,
                            import_cards, validate_licenses)


@pytest.fixture(autouse=True)
def isolated_work_dir(tmp_path, monkeypatch):
    """把所有管线的输出路径钉到 tmp_path。

    没有这层隔离时，单元测试会**写到仓库的 `work/`**——实测一次
    `validate_licenses.run()` 直接把真实语料的 `licensed.jsonl` 覆盖成 1 条，
    重跑管线才发现。管线的每个模块都有自己的输出常量，必须逐个钉住。
    """
    work = tmp_path / "work"
    cards_dir = tmp_path / "cards"
    monkeypatch.setattr(common, "WORK", work)
    monkeypatch.setattr(common, "RAW_DIR", work / "raw")
    monkeypatch.setattr(common, "CARDS_DIR", cards_dir)
    monkeypatch.setattr(fetch, "FETCHED", work / "fetched.jsonl")
    monkeypatch.setattr(fetch, "FETCH_REJECTS", work / "fetch_rejects.jsonl")
    monkeypatch.setattr(fetch, "RESOLVED", work / "sources.resolved.json")
    monkeypatch.setattr(fetch, "ROBOTS_DIR", work / "robots")
    monkeypatch.setattr(extract_text, "EXTRACTED", work / "extracted.jsonl")
    monkeypatch.setattr(extract_text, "FETCHED", work / "fetched.jsonl")
    monkeypatch.setattr(dedupe, "DEDUPED", work / "deduped.jsonl")
    monkeypatch.setattr(dedupe, "EXTRACTED", work / "extracted.jsonl")
    monkeypatch.setattr(validate_licenses, "LICENSED", work / "licensed.jsonl")
    monkeypatch.setattr(validate_licenses, "LICENSE_REJECTS", work / "license_rejects.jsonl")
    monkeypatch.setattr(validate_licenses, "DEDUPED", work / "deduped.jsonl")
    monkeypatch.setattr(chunk, "LICENSED", work / "licensed.jsonl")
    monkeypatch.setattr(chunk, "CHUNKS", work / "chunks.jsonl")
    monkeypatch.setattr(annotate, "CHUNKS", work / "chunks.jsonl")
    monkeypatch.setattr(annotate, "ANNOTATED", work / "annotated.jsonl")
    monkeypatch.setattr(annotate, "ANNOTATE_REJECTS", work / "annotate_rejects.jsonl")
    monkeypatch.setattr(annotate, "MANIFEST", work / "annotate.manifest.json")
    monkeypatch.setattr(import_cards, "ANNOTATED", work / "annotated.jsonl")
    monkeypatch.setattr(import_cards, "CHUNKS", work / "chunks.jsonl")
    monkeypatch.setattr(import_cards, "REPORT", work / "import_report.json")
    monkeypatch.setattr(import_cards, "COMMITTED_REPORT", cards_dir / "import_report.json")
    return work


# --------------------------------------------------------------------------- 基础件


def test_license_whitelist_is_exactly_the_frozen_set():
    assert common.LICENSE_WHITELIST == {
        "CC0", "CC-BY", "CC-BY-SA", "PublicDomain", "OwnWork", "ExplicitPermission",
    }


@pytest.mark.parametrize("license_name,expected", [
    ("CC-BY-SA", True), ("PublicDomain", True), ("OwnWork", True),
    ("AllRightsReserved", False), ("Unknown", False), ("", False),
])
def test_license_gate(license_name, expected):
    assert common.license_allowed(license_name) is expected


def test_source_ref_requires_all_six_fields():
    good = {f: "x" for f in common.SOURCE_REF_FIELDS}
    assert common.source_ref_problems(good) == []
    bad = dict(good)
    bad["sha256"] = "  "
    assert common.source_ref_problems(bad) == ["sha256"]


@pytest.mark.parametrize("quote,ok", [
    ("一句话。", True),
    ("第一句。第二句。", True),
    ("第一句。第二句。第三句。", False),
    ("字" * 121, False),
    ("", False),
])
def test_quote_rule(quote, ok):
    passed, _reason = common.quote_check(quote)
    assert passed is ok


def test_quote_must_be_verbatim_ignoring_whitespace():
    source = "机位高度决定权力关系。 低机位让 人物显得高大。"
    assert common.quote_is_verbatim("低机位让人物显得高大。", source)  # 只忽略空白差异
    assert not common.quote_is_verbatim("低机位让被摄者显得高大。", source)


def test_simhash_flags_near_duplicates_but_not_unrelated_text():
    a = "低机位让被摄者显得高大，仰角超过十五度观众会察觉。"
    b = "低机位让被摄者显得高大；仰角超过十五度，观众会察觉。"
    c = "剪辑点只有两种驱动力：信息驱动与情绪驱动。"
    assert common.hamming(common.simhash64(a), common.simhash64(b)) <= common.SIMHASH_MAX_HAMMING
    assert common.hamming(common.simhash64(a), common.simhash64(c)) > common.SIMHASH_MAX_HAMMING


# --------------------------------------------------------------------------- 切块 / 去重


def test_chunk_bounds_and_stable_ids():
    text = "\n\n".join("句子%d。这段文字用来测试切块。" % i for i in range(400))
    pieces = chunk.chunk_document(text)
    assert pieces
    assert all(len(p) <= chunk.MAX_CHARS + 64 for p in pieces)
    assert all(len(p) >= 1 for p in pieces)
    assert chunk.chunk_document(text) == pieces  # 确定性


def test_dedupe_marks_exact_and_near_duplicates():
    base = "构图的核心是把注意力引到主体上。三分法只是最省力的近似。"
    records = [
        {"source_ref": {"sha256": "a", "url": "u1"}, "text": base},
        {"source_ref": {"sha256": "a", "url": "u1"}, "text": base},
        {"source_ref": {"sha256": "b", "url": "u2"}, "text": base + "补一句。"},
        {"source_ref": {"sha256": "c", "url": "u3"}, "text": "剪辑的节奏来自长短镜的对比。完全不同的一段文本。"},
    ]
    kept, duplicates = dedupe.dedupe(records)
    assert duplicates == 2
    assert [bool(r["dup_of"]) for r in kept] == [False, True, True, False]


# --------------------------------------------------------------------------- 许可门 / 导入


def _source_ref(**over):
    ref = {"url": "repo://knowledge/source_notes/x.md", "title": "t", "author": "a",
           "license": "OwnWork", "retrieved_at": "2026-09-30", "sha256": "d" * 64}
    ref.update(over)
    return ref


def test_license_gate_rejects_bad_license_and_short_text():
    records = [
        {"source_ref": _source_ref(), "text": "x" * 700, "domain": "cinematography", "dup_of": ""},
        {"source_ref": _source_ref(license="AllRightsReserved"), "text": "x" * 700,
         "domain": "cinematography", "dup_of": ""},
        {"source_ref": _source_ref(sha256=""), "text": "x" * 700, "domain": "cinematography",
         "dup_of": ""},
        {"source_ref": _source_ref(), "text": "太短", "domain": "cinematography", "dup_of": ""},
        {"source_ref": _source_ref(), "text": "重复文档不入许可门", "domain": "cinematography",
         "dup_of": "u1"},
    ]
    kept, rejects = validate_licenses.run(records)
    assert len(kept) == 1
    reasons = " | ".join(r["reason"] for r in rejects)
    assert "license_not_whitelisted" in reasons
    assert "source_ref_missing:sha256" in reasons
    assert "text_too_short" in reasons


def _synthetic_content(domain: str, index: int) -> str:
    """彼此差异足够大的合成正文（用来验证去重计数，不验证语义）。"""
    import hashlib

    digest = hashlib.sha256(f"{domain}:{index}".encode("utf-8")).digest()
    alphabet = "".join(chr(0x4E00 + (byte % 2000)) for byte in digest)
    return f"{domain}｜第{index}条知识｜{alphabet}"


def _annotated(domain: str, count: int, text: str, quote: str, topic: str = "") -> list:
    return [{
        "chunk_id": f"{domain}#000",
        "sha256": "d" * 64,
        "domain": domain,
        "genre": "film",
        "theme": topic,
        "source_ref": _source_ref(),
        "cards": [{"title": f"{domain} 标题{i}",
                   "content": _synthetic_content(domain, i),
                   "quote": quote, "keywords": ["k"], "tags": ["t"], "rules": [],
                   "emotion": ""} for i in range(count)],
        "dropped_cards": [],
        "extractor": {"model_id": "scripted", "family": "scripted", "model_version": "s"},
    }]


def test_import_report_counts_and_k_gates(tmp_path, monkeypatch):
    quote = "低机位让人物显得高大。"
    annotated = []
    for domain in common.DOMAINS:
        annotated += _annotated(domain, 60, "text", quote, topic="lighting")
    # 60 张/域 已经过 K3；再加两条重复条目验证去重计数
    annotated += _annotated("cinematography", 60, "text", quote)

    report = import_cards.run(annotated, {"docs_deduped": 0})
    counts = report["counts"]
    assert counts["cards_deduped"] >= 1
    assert counts["cards_kept"] == 9 * 60
    assert counts["cards_candidates"] + counts["cards_deduped"] + counts["cards_rejected"] >= counts["cards_kept"]
    assert report["K1_source_ref_complete"] == 1.0
    assert report["counts"]["K2_license_ratio"] == 1.0
    assert report["K4_dedupe_ratio"] >= import_cards.K4_MIN_RATIO
    assert report["passed"] is True, report["problems"]
    assert report["topics"]["lighting"] >= 9 * 60
    # 每个域都要有 jsonl 与 yaml 两份产物，且逐字段一致
    for domain in common.DOMAINS:
        jsonl_path = tmp_path / "cards" / f"{domain}.jsonl"
        yaml_path = tmp_path / "cards" / f"{domain}.yaml"
        assert jsonl_path.is_file() and yaml_path.is_file()
        import yaml
        mirrored = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        on_disk = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
        assert mirrored == on_disk, f"{domain} 的 yaml/jsonl 不一致"


def test_import_rejects_quote_that_is_not_verbatim_or_too_long(tmp_path, monkeypatch):
    annotated = _annotated("anime", 1, "text", "甲" * 200)
    report = import_cards.run(annotated, {})
    assert report["counts"]["cards_rejected"] == 1
    assert "quote_too_long" in report["rejects"][0]["reason"]
    assert report["counts"]["cards_kept"] == 0


# --------------------------------------------------------------------------- 端到端（离线）


def test_manual_pipeline_end_to_end_with_scripted_annotator(tmp_path, monkeypatch):
    work = tmp_path / "work"
    sources = [s for s in common.load_sources() if s["mode"] == "manual"]
    assert sources, "sources.yaml 里必须有自撰笔记来源"

    fetched, rejects = fetch.run(sources, rate_seconds=0.0)
    assert not rejects
    assert len(fetched) == len(sources)

    records = [r for r in fetched if not r["source_ref"]["sha256"]]
    assert records == []
    assert all(len(r["text"]) > validate_licenses.MIN_DOC_CHARS for r in fetched)

    licensed, license_rejects = validate_licenses.run(fetched)
    assert not license_rejects

    chunks = chunk.run(licensed)
    assert len(chunks) >= len(licensed)
    assert all(c["chunker_version"] == common.CHUNKER_VERSION for c in chunks)

    # scripted 回答：每个 chunk 给两条卡片，quote 取该 chunk 里真实出现的短句
    responses = {}
    for item in chunks:
        sentence = common.split_sentences(item["text"])[0]
        quote = sentence[:60]
        responses[item["chunk_id"]] = [
            {"title": "脚本卡", "content": "这是一条来自自撰笔记的可执行知识，包含取舍与条件。",
             "quote": quote, "keywords": ["k1", "k2"], "tags": ["t"], "rules": [],
             "emotion": ""},
            {"title": "脚本卡二", "content": "第二条知识，同样要求具体到可以执行，不能是空话。",
             "quote": quote, "keywords": ["k1"], "tags": ["t"], "rules": [], "emotion": ""},
        ]
    script_path = tmp_path / "scripted.json"
    script_path.write_text(json.dumps({"responses": responses}, ensure_ascii=False),
                           encoding="utf-8")
    client = annotate.llm.make_client("scripted", "scripted-v1", str(script_path))

    annotated, annotate_rejects = annotate.run(chunks, client, limit=3)
    assert len(annotated) == 3
    assert all(len(r["cards"]) == 2 for r in annotated)
    assert not annotate_rejects

    # 断点续跑：同指纹下重跑不会重复产出
    again, _ = annotate.run(chunks, client, limit=3)
    assert len(again) == len(annotated) + 3  # 复用上一批 + 只补新的一批
    assert len({r["chunk_id"] for r in again}) == len(again)


def test_annotator_rejects_non_verbatim_quote():
    chunk_record = {"chunk_id": "x#000", "text": "机位高度决定权力关系。低机位让人物显得高大。",
                    "domain": "cinematography"}
    card, reason = annotate.validate_card(
        {"title": "t", "content": "这是一条足够长的知识改写，用来验证逐字引用校验。",
         "quote": "这句话在原文里并不存在。"}, chunk_record)
    assert card is None and reason == "quote_not_verbatim"


def test_sources_yaml_entries_are_wellformed():
    sources = common.load_sources()
    assert len(sources) >= 20
    for entry in sources:
        assert entry["license"] in common.LICENSE_WHITELIST
        assert entry["domain"] in common.DOMAINS
        if entry["mode"] == "manual":
            assert entry["url"].startswith(common.OWNWORK_SCHEME)
            rel = entry["url"][len(common.OWNWORK_SCHEME):]
            assert (common.ROOT / rel).is_file(), f"缺少自撰笔记：{rel}"


def test_pipeline_domain_order_matches_runtime_corpus():
    from block_director.knowledge import corpus

    assert tuple(common.DOMAINS) == tuple(corpus.DOMAINS)


# --------------------------------------------------------------------------- 交付验收


def test_shipped_corpus_meets_the_k_gates():
    """P14-1 的交付验收：入库语料必须过 K1–K4（§2.3c），且九域各 ≥60、占比 ≥5%。

    这一条读的是**随仓库入库**的产物（`knowledge/cards_generated/import_report.json`
    与运行时 `CARDS`），而不是本次运行的中间结果——否则"删掉产物"就恒绿。
    """
    from collections import Counter

    from block_director.knowledge import corpus

    report_path = pathlib.Path(common.ROOT) / "knowledge" / "cards_generated" / "import_report.json"
    assert report_path.is_file(), "缺少 import_report.json（先跑 tools.kb_fetch.import_cards）"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    counts = report["counts"]
    assert counts["cards_candidates"] > 0
    assert report["K1_source_ref_complete"] == 1.0
    assert counts["K2_license_ratio"] == 1.0
    assert report["K4_dedupe_ratio"] >= import_cards.K4_MIN_RATIO

    # 语料 = 手写卡 ＋ 生成卡（T8），验收按**整份语料**算
    domains = Counter(card.domain for card in corpus.CARDS)
    total = len(corpus.CARDS)
    assert total >= 900, f"整份语料只有 {total} 张（< 900）"
    for domain in corpus.DOMAINS:
        count = domains.get(domain, 0)
        assert count >= 60, f"{domain} 只有 {count} 张（< 60）"
        assert count / total >= 0.05, f"{domain} 占比 {count / total:.3f}（< 5%）"
    assert corpus.CARD_ID_COLLISIONS == ()
