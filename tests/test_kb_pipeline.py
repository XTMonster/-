"""P14-1 语料管线的对抗性测试（执行文档 v1.4 §2.3c/§2.3d）。

全部离线：标注用 `scripted` 后端，抓取只用 `mode: manual` 的自撰笔记。
"""

from __future__ import annotations

import http.server
import json
import pathlib
import threading

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
        #: v1.5 用户裁决：个人学习用途允许现代理论素材；单独记名便于以后筛选。
        "PersonalStudy",
    }


@pytest.mark.parametrize("license_name,expected", [
    ("CC-BY-SA", True), ("PublicDomain", True), ("OwnWork", True),
    ("PersonalStudy", True),
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


def _annotated_with(contents: Sequence[str], chunk_id: str) -> list:
    return [{
        "chunk_id": chunk_id,
        "sha256": "e" * 64,
        "domain": "cinematography",
        "genre": "film",
        "theme": "",
        "source_ref": _source_ref(),
        "cards": [{"title": f"标题{i}", "content": content,
                   "quote": "低机位让人物显得高大。", "keywords": ["k"], "tags": ["t"],
                   "rules": [], "emotion": ""} for i, content in enumerate(contents)],
        "dropped_cards": [],
        "extractor": {"model_id": "scripted", "family": "scripted", "model_version": "s"},
    }]


def test_generated_card_ids_survive_corpus_growth(tmp_path):
    """语料长大时，老卡必须保住自己的 id。

    否则 held-out 条目的 `from_card` 会静默地指向**另一张卡**：门③/门⑥ 只看
    "id 在不在集合里"，会一路全绿，而评测其实在拿别人的期望打分。
    """
    cards_dir = tmp_path / "cards"
    first = _annotated_with(["中中中中中中中中中中中中", "文文文文文文文文文文文文"], "old#000")
    import_cards.run(first, {})
    before = {row["content"]: row["id"]
              for row in common.read_jsonl(cards_dir / "cinematography.jsonl")}
    assert sorted(before.values()) == ["gen_cine_0001", "gen_cine_0002"]

    # 新卡的正文排序在最前面（U+4E00 < U+4E2D < U+6587）：按旧口径重排，
    # 老卡会被挤到 0002/0003，id 整体下移。
    grown = first + _annotated_with(["一一一一一一一一一一一一"], "new#000")
    import_cards.run(grown, {})
    after = {row["content"]: row["id"]
             for row in common.read_jsonl(cards_dir / "cinematography.jsonl")}

    assert after["中中中中中中中中中中中中"] == before["中中中中中中中中中中中中"]
    assert after["文文文文文文文文文文文文"] == before["文文文文文文文文文文文文"]
    assert after["一一一一一一一一一一一一"] == "gen_cine_0003"


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


# ----------------------------------------------------------- 增量入库（--incremental）

_SENTENCE = "机位高度决定权力关系：低机位让人物显得高大，高机位让人物显得渺小。"


class _CountingClient:
    """把 scripted 客户端包一层，用来断言"这一次到底调用了几次模型"。"""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def chat_json(self, *args, **kwargs):
        self.calls.append(str(kwargs.get("key", "")))
        return self._inner.chat_json(*args, **kwargs)


def _annotate_chunk(index: int, text: str = "") -> dict:
    body = text or f"{_SENTENCE}这是第 {index} 段的正文，用来验证增量入库。"
    return {"chunk_id": f"inc#{index:03d}", "sha256": common.sha256_text(body),
            "text": body, "domain": "cinematography", "genre": "film", "theme": "",
            "source_ref": {"url": "repo://knowledge/source_notes/x.md", "title": "增量测试笔记",
                           "author": "BlockDirector knowledge team", "license": "OwnWork",
                           "retrieved_at": "2026-10-01", "sha256": common.sha256_text(body)}}


def _scripted_annotator(tmp_path, chunks, model_id: str):
    responses = {c["chunk_id"]: [{
        "title": f"脚本卡{c['chunk_id']}",
        "content": "低机位抬升人物权力，高机位压低人物；高度差要大于视线高度才读得出来。",
        "quote": common.split_sentences(c["text"])[0][:60],
        "keywords": ["机位"], "tags": ["低机位"], "rules": [], "emotion": "",
    }] for c in chunks}
    path = tmp_path / f"scripted-{model_id}.json"
    path.write_text(json.dumps({"responses": responses}, ensure_ascii=False), encoding="utf-8")
    return annotate.llm.make_client("scripted", model_id, str(path))


def _manifest_of(tmp_path) -> dict:
    return json.loads((tmp_path / "work" / "annotate.manifest.json").read_text(encoding="utf-8"))


def test_incremental_annotate_reuses_the_old_pass_when_the_corpus_grows(tmp_path):
    first = [_annotate_chunk(0), _annotate_chunk(1)]
    client_a = _CountingClient(_scripted_annotator(tmp_path, first, "annotator-a"))
    annotated, _ = annotate.run(first, client_a, incremental=True)
    assert len(annotated) == 2 and len(client_a.calls) == 2

    grown = first + [_annotate_chunk(2)]
    client_b = _CountingClient(_scripted_annotator(tmp_path, grown, "annotator-b"))
    again, rejects = annotate.run(grown, client_b, incremental=True)

    assert not rejects
    assert len(again) == 3
    assert client_b.calls == ["inc#002"], "语料长大时只有新增的那一段该被抽"
    by_id = {r["chunk_id"]: r for r in again}
    # 换模型不让旧 pass 失效：每条记录带自己的 extractor，逐条可审计。
    assert by_id["inc#000"]["extractor"]["model_id"] == "annotator-a"
    assert by_id["inc#002"]["extractor"]["model_id"] == "annotator-b"
    manifest = _manifest_of(tmp_path)
    assert manifest["version"] == annotate.MANIFEST_VERSION
    assert manifest["mode"] == "incremental"
    assert manifest["reused_chunks"] == 2 and manifest["annotated_chunks"] == 1
    assert len(manifest["passes"]) == 2
    assert manifest["total_chunks"] == 3
    assert [p["model_id"] for p in manifest["passes"]] == ["annotator-a", "annotator-b"]


def test_incremental_annotate_reannotates_only_the_chunk_that_changed(tmp_path):
    first = [_annotate_chunk(0), _annotate_chunk(1)]
    annotate.run(first, _scripted_annotator(tmp_path, first, "m1"), incremental=True)

    changed = [_annotate_chunk(0), _annotate_chunk(1, text=_SENTENCE + "这一段被改写了。")]
    client = _CountingClient(_scripted_annotator(tmp_path, changed, "m2"))
    again, _ = annotate.run(changed, client, incremental=True)
    assert client.calls == ["inc#001"], "正文变了只重抽那一段，不牵连别的段"
    assert len(again) == 2


def test_incremental_annotate_is_invalidated_by_a_prompt_version_bump(tmp_path, monkeypatch):
    chunks = [_annotate_chunk(0), _annotate_chunk(1)]
    annotate.run(chunks, _scripted_annotator(tmp_path, chunks, "m1"), incremental=True)

    monkeypatch.setattr(common, "ANNOTATE_PROMPT_VERSION", "annotate/v5")
    client = _CountingClient(_scripted_annotator(tmp_path, chunks, "m2"))
    again, _ = annotate.run(chunks, client, incremental=True)
    assert client.calls == ["inc#000", "inc#001"], "口径升级必须整体重抽（§2.3）"
    assert len(again) == 2


def test_strict_mode_still_reannotates_when_the_fingerprint_moves(tmp_path):
    first = [_annotate_chunk(0), _annotate_chunk(1)]
    annotate.run(first, _scripted_annotator(tmp_path, first, "m1"))

    grown = first + [_annotate_chunk(2)]
    client = _CountingClient(_scripted_annotator(tmp_path, grown, "m1"))
    again, _ = annotate.run(grown, client)
    assert len(client.calls) == 3, "默认（strict）口径下指纹变了就整体重抽"
    assert len(again) == 3
    assert _manifest_of(tmp_path)["mode"] == "strict"


def test_v1_flat_manifest_is_migrated_into_a_pass(tmp_path):
    chunks = [_annotate_chunk(0), _annotate_chunk(1)]
    annotate.run(chunks, _scripted_annotator(tmp_path, chunks, "legacy-model"))

    manifest_path = tmp_path / "work" / "annotate.manifest.json"
    v2 = json.loads(manifest_path.read_text(encoding="utf-8"))
    decode = v2["decode"]
    v1 = {
        "fingerprint": annotate.fingerprint(chunks, "legacy-model", decode),
        "extractor": {"model_id": "legacy-model", "family": "scripted",
                      "model_version": "scripted"},
        "decode": decode,
        "chunker_version": common.CHUNKER_VERSION,
        "schema_version": common.SCHEMA_VERSION,
        "prompt_version": common.ANNOTATE_PROMPT_VERSION,
        "total_chunks": len(chunks),
        "chunks": [{"chunk_id": c["chunk_id"], "sha256": c["sha256"],
                    "status": "done", "cards": ["脚本卡"]} for c in chunks],
    }
    manifest_path.write_text(json.dumps(v1, ensure_ascii=False), encoding="utf-8")

    grown = chunks + [_annotate_chunk(2)]
    client = _CountingClient(_scripted_annotator(tmp_path, grown, "new-model"))
    again, _ = annotate.run(grown, client, incremental=True)
    assert client.calls == ["inc#002"], "v1 清单要迁移成 pass，而不是整体重抽"
    assert len(again) == 3
    migrated = _manifest_of(tmp_path)["passes"][0]
    assert migrated["legacy_fingerprint"] == v1["fingerprint"]
    assert migrated["model_id"] == "legacy-model"


def test_v1_manifest_with_a_stale_prompt_is_not_migrated(tmp_path):
    chunks = [_annotate_chunk(0)]
    annotate.run(chunks, _scripted_annotator(tmp_path, chunks, "legacy-model"))

    manifest_path = tmp_path / "work" / "annotate.manifest.json"
    v2 = json.loads(manifest_path.read_text(encoding="utf-8"))
    v1 = {"fingerprint": "deadbeef", "version": 1,
          "extractor": {"model_id": "legacy-model", "family": "scripted",
                        "model_version": "scripted"},
          "decode": v2["decode"], "chunker_version": common.CHUNKER_VERSION,
          "schema_version": common.SCHEMA_VERSION, "prompt_version": "annotate/v3",
          "total_chunks": 1,
          "chunks": [{"chunk_id": chunks[0]["chunk_id"], "sha256": chunks[0]["sha256"],
                      "status": "done", "cards": ["脚本卡"]}]}
    manifest_path.write_text(json.dumps(v1, ensure_ascii=False), encoding="utf-8")

    client = _CountingClient(_scripted_annotator(tmp_path, chunks, "new-model"))
    annotate.run(chunks, client, incremental=True)
    assert client.calls == ["inc#000"], "prompt 版本对不上就不迁移，宁可重抽"


class _OverlapClient:
    """记录「同时在飞的调用数」，用来证明 `--workers` 真的在并发。"""

    def __init__(self, inner):
        import threading

        self._inner = inner
        self._lock = threading.Lock()
        self.live = 0
        self.peak = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def chat_json(self, *args, **kwargs):
        import time

        with self._lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
        try:
            time.sleep(0.02)
            return self._inner.chat_json(*args, **kwargs)
        finally:
            with self._lock:
                self.live -= 1


def test_parallel_annotate_matches_serial_output(tmp_path, monkeypatch):
    chunks = [_annotate_chunk(i) for i in range(8)]
    inner = _scripted_annotator(tmp_path, chunks, "m1")

    def run_in(name, client, workers):
        work = tmp_path / name
        work.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(annotate, "ANNOTATED", work / "annotated.jsonl")
        monkeypatch.setattr(annotate, "ANNOTATE_REJECTS", work / "rejects.jsonl")
        monkeypatch.setattr(annotate, "MANIFEST", work / "manifest.json")
        return annotate.run(chunks, client, workers=workers)

    serial, _ = run_in("serial", inner, 1)
    overlap = _OverlapClient(inner)
    parallel, _ = run_in("parallel", overlap, 4)

    assert parallel == serial, "并发标注的产物必须与串行逐字段相同"
    assert overlap.peak > 1, "workers=4 时应当真的出现同时在飞的调用"
    serial_manifest = json.loads(
        (tmp_path / "serial" / "manifest.json").read_text(encoding="utf-8"))
    parallel_manifest = json.loads(
        (tmp_path / "parallel" / "manifest.json").read_text(encoding="utf-8"))
    assert serial_manifest["chunks"] == parallel_manifest["chunks"]
    assert serial_manifest["passes"] == parallel_manifest["passes"]


def test_incremental_rejects_are_kept_and_can_be_retried(tmp_path):
    chunks = [_annotate_chunk(0)]
    annotated, rejects = annotate.run(chunks, _scripted_annotator(tmp_path, [], "m1"),
                                      incremental=True)
    assert not annotated and len(rejects) == 1

    grown = [_annotate_chunk(0), _annotate_chunk(1)]
    client = _CountingClient(_scripted_annotator(tmp_path, grown, "m2"))
    again, rejects2 = annotate.run(grown, client, incremental=True)
    assert client.calls == ["inc#001"], "已判「无卡片」的段不该每轮重烧一次 API"
    assert len(again) == 1 and len(rejects2) == 1
    assert rejects2[0]["chunk_id"] == "inc#000"

    client3 = _CountingClient(_scripted_annotator(tmp_path, grown, "m3"))
    again3, rejects3 = annotate.run(grown, client3, incremental=True, retry_rejects=True)
    # 重抽只针对"被判无卡片"的那一段；已经抽出卡片的那段照旧复用。
    assert client3.calls == ["inc#000"]
    assert len(again3) == 2 and not rejects3


def _budget_record(url: str, budget: int = 0, domain: str = "composition") -> dict:
    body = "\n\n".join(f"第{i}段。" + "这是用于切块预算测试的正文，必须足够长。" * 60
                       for i in range(20))
    return {"source_ref": {"url": url, "title": "t", "author": "a",
                           "license": "PublicDomain", "retrieved_at": "2026-10-01",
                           "sha256": common.sha256_text(url)},
            "domain": domain, "mode": "http", "genre": "film", "theme": "",
            "chunk_budget": budget, "text": body, "chars": len(body)}


def test_source_declared_chunk_budget_beats_the_domain_budget():
    """来源自己声明的预算不随同域里其他来源的增减而改变。

    域预算是"这个域一共切多少段"，多一个来源就会把每个来源的配额改掉，
    于是老段的切法跟着变、正文 sha 跟着变，已有的标注全部作废。
    """
    records = [_budget_record("https://example.test/a.txt", 2),
               _budget_record("https://example.test/b.txt", 0)]
    chunks = chunk.run(records, per_domain_chunks=10)
    ids = [c["chunk_id"] for c in chunks]
    assert [i for i in ids if i.startswith("a_txt")] == ["a_txt#000", "a_txt#001"]
    # 另一个来源没有声明预算，仍然吃域预算：ceil(10 / 2) = 5
    assert len([i for i in ids if i.startswith("b_txt")]) == 5


def test_fetch_carries_the_source_chunk_budget():
    source = {"url": "repo://knowledge/source_notes/editing_rhythm.md", "title": "t",
              "author": "a", "license": "OwnWork", "domain": "editing",
              "mode": "manual", "chunk_budget": 7, "retrieved_at": "2026-10-01"}
    record = fetch.fetch_source(source, 30.0, 0.0)
    assert record["chunk_budget"] == 7


def test_chunk_budget_must_be_a_non_negative_integer(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - url: repo://knowledge/source_notes/editing_rhythm.md\n"
        "    title: t\n    author: a\n    license: OwnWork\n"
        "    domain: editing\n    mode: manual\n    chunk_budget: 很多\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="chunk_budget"):
        common.load_sources(path)
    path.write_text(
        "sources:\n"
        "  - url: repo://knowledge/source_notes/editing_rhythm.md\n"
        "    title: t\n    author: a\n    license: OwnWork\n"
        "    domain: editing\n    mode: manual\n    chunk_budget: -3\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="chunk_budget"):
        common.load_sources(path)


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


# --------------------------------------------------------------------------- 抓取纪律（§2.3c 的"绝不抓取"）


class _DisciplineServer:
    """极小 HTTP 服务器：``/start`` 302 到 ``robots.txt`` 明令禁止的路径。

    只用标准库，和 `tests/test_protocol_end_to_end.py` 的做法一致。``hits``
    记录每一条被真正请求到的路径，用来断言"被禁的路径根本没被取过"——不能
    只看最终有没有抛错，否则"取到了再报错"也会假绿。
    """

    SECRET = "SECRET-BODY-THAT-ROBOTS-FORBIDS\n"

    def __init__(self) -> None:
        outer = self
        self.hits: list = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):        # 静音
                return

            def _send(self, code, body=b"", headers=()):
                self.send_response(code)
                for key, value in headers:
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self):
                outer.hits.append(self.path)
                if self.path == "/robots.txt":
                    return self._send(200, b"User-agent: *\nDisallow: /private/\n")
                if self.path == "/start":
                    return self._send(302, headers=[("Location", "/private/secret.txt")])
                if self.path == "/tofile":
                    return self._send(302, headers=[("Location", "file:///C:/Windows/win.ini")])
                if self.path == "/toftp":
                    return self._send(302, headers=[("Location", "ftp://127.0.0.1:1/leak.txt")])
                if self.path == "/ok":
                    return self._send(200, (outer.SECRET * 400).encode())
                if self.path.startswith("/private/"):
                    return self._send(200, (outer.SECRET * 400).encode())
                return self._send(404)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):                    # noqa: D105
        self.server.shutdown()
        self.server.server_close()


def _http_source(url: str) -> dict:
    return {"url": url, "title": "t", "author": "a", "license": "PublicDomain",
            "domain": "cinematography", "mode": "http"}


def test_redirect_hop_must_pass_robots_again():
    """负例：`Disallow: /private/` 不能靠一条 302 绕过去。

    默认的 `urlopen` 会自己跟随重定向，而 `robots_allows` 只在**发起时**问过
    一次——于是 `/start` 可以把抓取带到被禁路径上。抓取纪律要求每一跳都重问。
    """
    with _DisciplineServer() as server:
        # 基准：直接抓被禁路径必须被拒（否则下面的断言会假绿）
        with pytest.raises(fetch.FetchError) as direct:
            fetch.fetch_source(_http_source(f"{server.base}/private/secret.txt"),
                               timeout=5.0, rate_seconds=0.0)
        assert "robots_disallow" in str(direct.value)

        with pytest.raises(fetch.FetchError) as redirected:
            fetch.fetch_source(_http_source(f"{server.base}/start"),
                               timeout=5.0, rate_seconds=0.0)
        assert "robots_disallow" in str(redirected.value), str(redirected.value)
        assert not [path for path in server.hits if path.startswith("/private/")], \
            f"被禁路径仍被请求过：{server.hits}"


def test_allowed_http_source_is_still_fetched():
    """反向：robots 允许的路径必须照常抓到——否则上面几条可能只是"全都拒收"。"""
    with _DisciplineServer() as server:
        record = fetch.fetch_source(_http_source(f"{server.base}/ok"),
                                    timeout=5.0, rate_seconds=0.0)
        assert _DisciplineServer.SECRET in record["text"]
        assert record["source_ref"]["sha256"]
        assert record["chars"] == len(record["text"])


def test_redirect_to_a_non_http_scheme_is_refused():
    """重定向目标也要过 scheme 白名单。

    标准库自己已经挡住 `file:`（"Redirection to url ... is not allowed"），
    但它的白名单是 `http/https/ftp`——`ftp:` 会被跟随。抓取纪律只认 http(s)，
    所以这一跳必须由我们的门而不是标准库来挡。
    """
    import urllib.error

    with _DisciplineServer() as server:
        with pytest.raises(fetch.FetchError) as ftp:
            fetch.fetch_source(_http_source(f"{server.base}/toftp"),
                               timeout=5.0, rate_seconds=0.0)
        assert "scheme_not_allowed" in str(ftp.value), str(ftp.value)

        with pytest.raises((fetch.FetchError, urllib.error.HTTPError)) as local:
            fetch.fetch_source(_http_source(f"{server.base}/tofile"),
                               timeout=5.0, rate_seconds=0.0)
        assert "not allowed" in str(local.value), str(local.value)


@pytest.mark.parametrize("url", ["file:///C:/Windows/win.ini", "ftp://example.com/x",
                                 "data:text/plain,hi"])
def test_http_source_scheme_allowlist_blocks_local_files(url):
    """`sources.yaml` 是输入；`mode: http` 只允许 http/https 两种 scheme。"""
    with pytest.raises(fetch.FetchError) as info:
        fetch.fetch_source(_http_source(url), timeout=5.0, rate_seconds=0.0)
    assert str(info.value).startswith("scheme_not_allowed:"), str(info.value)


def test_robots_cache_name_cannot_escape_its_directory(tmp_path):
    """netloc 来自外部输入，它含反斜杠/点；文件名不得因此越出 `work/robots/`。"""
    cache_dir = tmp_path / "robots"
    for netloc in ("..\\..\\evil.example", "../../evil.example", "..", ""):
        path = fetch._robots_cache_file(cache_dir, netloc)
        assert path.parent == cache_dir, f"netloc={netloc!r} -> {path}"
        assert path.name not in ("", ".txt"), f"netloc={netloc!r} -> {path.name!r}"


def test_robots_cache_dir_is_resolved_at_call_time(tmp_path, monkeypatch):
    """测试用的 `ROBOTS_DIR` 必须是**真的**隔离。

    写成默认参数（`cache_dir=ROBOTS_DIR`）会把对象绑死在导入那一刻，
    `monkeypatch.setattr(fetch, "ROBOTS_DIR", ...)` 静默失效——单元测试于是
    写到仓库真实的 `work/robots/`（把缓存污染成测试内容）。
    """
    pinned = tmp_path / "robots"
    monkeypatch.setattr(fetch, "ROBOTS_DIR", pinned)
    monkeypatch.setattr(fetch, "_http_get", lambda *a, **k: b"User-agent: *\n")
    allowed, reason = fetch.robots_allows("http://example.invalid/a", 5.0)
    assert allowed and not reason
    written = sorted(path.name for path in pinned.glob("*.txt"))
    assert written == ["example.invalid.txt"], written


# --------------------------------------------------------------------------- 路径围栏


def test_manual_source_cannot_escape_the_repo_root(tmp_path, monkeypatch):
    """`repo://` 来源不得借"同前缀的兄弟目录"越出仓库。

    旧实现用 `str(path).startswith(str(ROOT))`：`../白模预演codex_evil/x.md`
    解析成 `E:\\白模预演codex_evil\\x.md`，恰好以 `E:\\白模预演codex` 开头，
    于是任意相邻目录里的文件都会被当成 OwnWork 语料读进来。
    """
    repo = tmp_path / "repo"
    (repo / "knowledge").mkdir(parents=True)
    (repo / "knowledge" / "ok.md").write_text("正文" * 400, encoding="utf-8")
    outside = tmp_path / "repo_outside"
    outside.mkdir()
    (outside / "secret.md").write_text("不该被读到的正文" * 200, encoding="utf-8")
    monkeypatch.setattr(common, "ROOT", repo)

    for url in ("repo://../repo_outside/secret.md",
                "repo://knowledge/../../repo_outside/secret.md"):
        source = {"url": url, "title": "t", "author": "a", "license": "OwnWork",
                  "domain": "cinematography", "mode": "manual"}
        with pytest.raises(fetch.FetchError) as info:
            fetch.fetch_source(source, timeout=5.0, rate_seconds=0.0)
        assert "越出仓库" in str(info.value), str(info.value)

    # 反向：仓库内的笔记照常可读（否则上面的断言可能只是"全都拒收"）
    inside = {"url": "repo://knowledge/ok.md", "title": "t", "author": "a",
              "license": "OwnWork", "domain": "cinematography", "mode": "manual"}
    record = fetch.fetch_source(inside, timeout=5.0, rate_seconds=0.0)
    assert record["text"].startswith("正文")


# --------------------------------------------------------------------------- 入库体积门（§2.3c）


def test_inrepo_size_gate_fails_the_build(tmp_path):
    """超限即构建失败（不是警告）：单文件 513 KB，或总量越过 20 MB。"""
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "cinematography.yaml").write_bytes(b"x" * (common.MAX_CARD_FILE_BYTES + 1))
    gate = common.check_size_gate(cards)
    assert gate["passed"] is False and gate["oversize"]

    report = import_cards.build_report([], 0, 0, 0, {}, size_gate=gate)
    passed, problems = import_cards.evaluate(report)
    assert passed is False
    assert any("体积门" in problem for problem in problems), problems


def test_inrepo_size_gate_fails_when_the_total_is_over(tmp_path):
    """每一份都在单文件线内，但总量越过 20 MB —— 同样判失败。"""
    cards = tmp_path / "cards"
    cards.mkdir()
    chunk_bytes = 300 * 1024                   # < 单文件线（512 KB）
    files = common.MAX_CARDS_TOTAL_BYTES // chunk_bytes + 1
    for index in range(files):
        (cards / f"d{index:02d}.jsonl").write_bytes(b"x" * chunk_bytes)
    gate = common.check_size_gate(cards)
    assert not gate["oversize"], "单文件不该超限"
    assert gate["passed"] is False
    assert gate["total_bytes"] > common.MAX_CARDS_TOTAL_BYTES


def test_shipped_cards_are_within_the_inrepo_size_gate():
    """随仓库入库的生成卡必须过体积门（读的是真产物，不是本次运行的中间结果）。"""
    cards_dir = pathlib.Path(common.ROOT) / "knowledge" / "cards_generated"
    gate = common.check_size_gate(cards_dir)
    assert gate["file_count"] >= 9, gate
    assert gate["passed"] is True, gate["oversize"]
    assert gate["total_bytes"] <= common.MAX_CARDS_TOTAL_BYTES
