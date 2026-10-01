"""L3 案例语料（执行文档 v1.4 §2.3b / §2.3c 的 K1–K4 口径 ／ §3.1）。

判据只用**入库产物**（``knowledge/cases.jsonl`` ＋ ``cases.manifest.json``）
与**仓库里已提交的输入**（``knowledge/source_notes/*.md`` ＋ ``knowledge/sources.yaml``），
不依赖 ``work/`` 下的中间产物——那些是被 `.gitignore` 挡住的、跑不出来的环境里
也应当能复核的部分。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from block_director.knowledge.cases import (
    BEAT_TYPES,
    CASE_TYPES,
    CONSTRAINT_KEYS,
)
from tools.kb_fetch import build_cases as builder
from tools.kb_fetch import common

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "knowledge" / "cases.jsonl"
MANIFEST_PATH = ROOT / "knowledge" / "cases.manifest.json"
NOTES_DIR = ROOT / "knowledge" / "source_notes"

#: §2.3c 写死的 L3 数量门。
MIN_CASES = 300


def _rows() -> list:
    return [json.loads(line) for line in
            CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_case_corpus_meets_the_floor_and_has_unique_ids():
    rows = _rows()
    assert len(rows) >= MIN_CASES, f"L3 案例 {len(rows)} < {MIN_CASES}"
    ids = [row["case_id"] for row in rows]
    assert len(set(ids)) == len(ids)
    assert [row["case_id"] for row in rows] == sorted(ids)   # 落盘顺序稳定


def test_every_case_has_a_complete_source_ref_and_a_whitelisted_license():
    """K1 出处完整性 100% ＋ K2 许可合规率 100%（§2.3c）。"""
    for row in _rows():
        missing = common.source_ref_problems(row["source_ref"])
        assert not missing, f"{row['case_id']} 缺 {missing}"
        license_name = row["source_ref"]["license"]
        assert common.license_allowed(license_name), (row["case_id"], license_name)


def test_every_excerpt_passes_the_quote_gate():
    """"改写而非转载"的可判定口径：≤2 句、≤120 字（§2.3d）。"""
    for row in _rows():
        ok, reason = common.quote_check(row["excerpt"])
        assert ok, f"{row['case_id']}: {reason}"
        assert row["title"] and row["title"] != row["excerpt"]


def test_case_types_and_beat_sequences_stay_inside_the_frozen_vocabulary():
    for row in _rows():
        assert row["case_type"] in CASE_TYPES, row["case_id"]
        beats = row["beat_sequence"]
        if row["case_type"] == "sequence_pattern":
            assert len(beats) >= 2, row["case_id"]
            assert all(beat in BEAT_TYPES for beat in beats), row["case_id"]
        else:
            assert beats == [], row["case_id"]


def test_no_case_row_carries_a_constraint():
    """E3：L3 **永不产出约束**——连字段都不许出现。"""
    for row in _rows():
        for key in CONSTRAINT_KEYS:
            assert key not in row, (row["case_id"], key)


def test_the_manifest_accounting_adds_up():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rows = _rows()
    assert manifest["cases"] == len(rows)
    assert sum(manifest["per_type"].values()) == len(rows)
    assert sum(manifest["per_domain"].values()) == len(rows)
    assert (manifest["cases"] + manifest["duplicates"] + manifest["quota_truncated"]
            + manifest["rejects"]) == manifest["raw_segments"]
    assert manifest["reject_ratio"] <= builder.BUILD_REJECT_RATIO
    assert manifest["segments_total"] >= manifest["raw_segments"] >= 1
    assert manifest["fingerprint"] and manifest["corpus_fingerprint"]
    assert manifest["size_gate"]["passed"] is True
    # §2.3d T1 的消费对象：门是**已提交语料里显式枚举的套路条数**（只许升）。
    assert manifest["per_type"]["sequence_pattern"] >= builder.SEQUENCE_FLOOR


def test_every_sequence_pattern_is_re_derivable_from_a_committed_note():
    """独立复算：套路必须**从已提交的笔记原文**重新推得出来，且节拍与箭头同序。

    这条判据刻意**不读实现自报字段**：它把 `knowledge/cases.jsonl` 的每一行拿回
    `knowledge/source_notes/*.md` 去对——①``excerpt`` 必须是原文（脱装饰后）的
    连续子串；②按 `→` 切开的每一段必须各自落到一个节拍上；③由此得到的节拍序列
    必须与落盘行**逐字相同**（含顺序）。顺序写反、节拍与文本对不上、拿散文段冒充
    套路，三种都会在这里翻红。
    """
    notes = {path.name: path.read_text(encoding="utf-8")
             for path in NOTES_DIR.glob("*.md")}
    rows = [row for row in _rows() if row["case_type"] == "sequence_pattern"]
    assert len(rows) >= builder.SEQUENCE_FLOOR
    for row in rows:
        url = row["source_ref"]["url"]
        assert url.startswith(common.OWNWORK_SCHEME), row["case_id"]
        body = notes[url.rsplit("/", 1)[-1]].replace("**", "")
        assert common.quote_is_verbatim(row["excerpt"], body), row["case_id"]
        derived = []
        for part in builder.ARROW_RE.split(row["excerpt"]):
            beat = builder._beat_of(part)
            if beat is not None and beat not in derived:
                derived.append(beat)
        assert derived == row["beat_sequence"], (
            row["case_id"], derived, row["beat_sequence"])
        assert len(derived) >= 2


def _manual_docs() -> list:
    """从**已提交的**自撰笔记重建输入行。

    v1.5：用户裁决"理论不要自己写"之后，`sources.yaml` 里**不再有** `mode: manual`
    条目，但笔记文件仍留在仓库里作设计文档。所以这里不再从 `sources.yaml` 找来源，
    而是**就地声明**这些笔记（域按文件名前缀取）——这条测试要验的是"同一份笔记
    重建出同一批案例"的可复算性，不是"语料里还有自撰笔记"。
    """
    domain_by_prefix = {
        "anime": "anime", "axis": "axis_theory", "blocking": "blocking",
        "camera_angle": "cinematography", "editing": "editing",
        "lighting": "cinematography", "production": "production",
        "storyboard": "storyboard", "modern_action": "blocking",
        "modern_anime": "anime", "modern_axis": "axis_theory",
        "modern_blocking": "blocking", "modern_cinematography": "cinematography",
        "modern_composition": "composition", "modern_editing": "editing",
        "modern_performance": "performance", "modern_production": "production",
        "modern_sound": "editing", "modern_storyboard": "storyboard",
    }
    docs = []
    # 标题取**已提交的案例行**里逐条记录的那个（那是这批笔记当初的权威标题）。
    # 自己另编一个标题会让"重建是否逐字段相同"变成比标题，而不是比可复算性。
    ref_by_url = {}
    for row in _rows():
        source = row.get("source_ref") or {}
        url = str(source.get("url", ""))
        if url.startswith(common.OWNWORK_SCHEME) and url not in ref_by_url:
            ref_by_url[url] = dict(source)
    for path in sorted(NOTES_DIR.glob("*.md")):
        url = f"{common.OWNWORK_SCHEME}{path.relative_to(ROOT).as_posix()}"
        domain = "cinematography"
        for prefix, candidate in domain_by_prefix.items():
            if path.stem.startswith(prefix):
                domain = candidate
                break
        raw = path.read_bytes()
        docs.append({
            # 出处字段逐字段沿用**已提交案例**里那份（标题/作者/许可/抓取时间/sha256），
            # 正文取仓库里的笔记；这样"重建"比的是**可复算性**，不是我在测试里另编的元数据。
            "source_ref": {**(ref_by_url.get(url) or {}),
                           "url": url,
                           "sha256": hashlib.sha256(raw).hexdigest()},
            "text": raw.decode("utf-8"),
            "mode": "manual",
            "domain": domain,
        })
    return docs


def test_the_manual_notes_rebuild_identically_from_committed_inputs():
    """可复算性：同一份笔记 ＋ 同一份 sources.yaml → 逐字段相同的案例。"""
    docs = _manual_docs()
    rebuilt, _rejected, _report = builder.build_cases(docs, max_cases=10_000,
                                                      per_source=40)
    by_id = {row["case_id"]: row for row in rebuilt}
    assert by_id, "自撰笔记一条都没派生出来"
    for row in _rows():
        if not row["source_ref"]["url"].startswith(common.OWNWORK_SCHEME):
            continue
        assert row["case_id"] in by_id, row["case_id"]
        assert by_id[row["case_id"]] == row


def _synthetic_docs() -> list:
    base = {
        "url": "https://example.org/book", "title": "示范书", "author": "作者",
        "license": "PublicDomain", "retrieved_at": "2026-01-01",
        "sha256": "0" * 64,
    }
    text = (
        "先给一个建立镜头交代清楚人物与环境的位置关系，然后切到覆盖正反打的"
        "对话段落，最后落到听者的反应镜头上收束这段交流。"
        "广角镜头会把前后景的纵深关系夸大，而长焦镜头则会把空间压缩得扁平，"
        "选哪一支要看你想让观众读到什么。"
        "构图讲究三分与视线空间，主体放在三分线上时画面更容易读。"
        "不要在同一场戏里反复越轴，那是新手最常见的误区之一，观众会立刻迷失方向。"
        "剪辑节奏偏短的时候，连续的硬切会把紧张感推上去；偏长则以留白见长。"
        "光线用逆光勾边可以让轮廓从背景里跳出来，但正面就会失去层次。"
    )
    return [{"source_ref": dict(base), "text": text, "mode": "manual",
             "domain": "storyboard"}]


def test_the_builder_is_deterministic_and_gated():
    docs = _synthetic_docs()
    first, rejected_a, report_a = builder.build_cases(docs, max_cases=10_000,
                                                      per_source=40)
    second, rejected_b, report_b = builder.build_cases(docs, max_cases=10_000,
                                                       per_source=40)
    assert first == second and report_a == report_b
    assert rejected_a == rejected_b
    assert first and all(row["case_type"] in CASE_TYPES for row in first)
    # `evaluate()` 是**语料级**的门（≥300 篇、≥SEQUENCE_FLOOR 条显式套路）：
    # 一份合成的小语料（没有箭头枚举、也远不到 300 篇）必然过不了这两道语料级门。
    # 要断言的是"除了这两道语料级门，逐行形状一条问题都没有"。
    verdict = builder.evaluate(first, report_a)
    assert verdict["passed"] is False
    shape = [problem for problem in verdict["problems"]
             if not problem.startswith(("cases_too_few",
                                        "sequence_pattern_too_few"))]
    assert shape == []
    assert any(problem.startswith("cases_too_few")
               for problem in verdict["problems"])
    assert any(problem.startswith("sequence_pattern_too_few")
               for problem in verdict["problems"])


def test_the_builder_rejects_a_broken_source_instead_of_absorbing_it():
    docs = _synthetic_docs()
    # ① 缺 sha256（K1 的必填字段）→ 整篇拒收，且原因点名是哪一项。
    broken = json.loads(json.dumps(docs))
    broken[0]["source_ref"]["sha256"] = ""
    cases, rejected, _report = builder.build_cases(broken)
    assert cases == []
    assert any("source_ref_incomplete" in item["reason"] for item in rejected)
    # ② 许可不在白名单（K2）→ 拒收。
    broken = json.loads(json.dumps(docs))
    broken[0]["source_ref"]["license"] = "AllRightsReserved"
    cases, rejected, _report = builder.build_cases(broken)
    assert cases == []
    assert any("license_not_allowed" in item["reason"] for item in rejected)
    # ③ 全是样板文字的段落不产生案例（不是"抓到多少算多少"）。
    boiler = json.loads(json.dumps(docs))
    boiler[0]["text"] = ("Project Gutenberg eBook of something. "
                         "This eBook is for the use of anyone anywhere. "
                         "Copyright applies to this redistribution. " * 6)
    cases, _rejected, _report = builder.build_cases(boiler)
    assert cases == []


def test_evaluate_reports_an_undersized_corpus():
    docs = _synthetic_docs()
    cases, _rejected, report = builder.build_cases(docs)
    verdict = builder.evaluate(cases[:2], {**report, "cases": 2})
    assert verdict["passed"] is False
    assert any(problem.startswith("cases_too_few") for problem in verdict["problems"])
def test_prose_sequence_pattern_recognises_ordered_enumerations():
    """散文里的**显式顺序枚举**要能派生套路（外部他人著作的主要写法）。

    背景：`sequence_pattern` 原先只认箭头（`→`/`->`），而箭头是**我们自己笔记**的
    写法；用户裁决"理论必须由他人写"之后那批笔记退出语料，外部 Gutenberg／OCW
    散文里根本没有箭头 —— 实测 59 篇语料 **0 条**箭头套路。补上这条通道：
    "先…再…最后…" / "first…then…finally…" 同样是**显式枚举**，判据一条没放宽。
    """
    from tools.kb_fetch import build_cases as bc

    english = ("First the director opens on an establishing shot of the street, "
               "then he cuts to coverage of the two men talking, and finally he "
               "lands on a close-up insert of the letter.")
    got = bc.prose_sequence_pattern_of(english)
    assert got, "英文顺序枚举没被识别"
    _excerpt, beats = got[0]
    assert len(set(beats)) >= 2
    assert beats == [b for b in beats if b in bc.BEAT_TYPES]
    # 节拍顺序必须与文本顺序一致（门里的复核同一口径）。
    assert bc.beat_positions(_excerpt, beats) == sorted(bc.beat_positions(_excerpt, beats))

    chinese = "先给一个建立镜头交代环境，再切到两人的覆盖镜头，最后落到信件特写。"
    got_cn = bc.prose_sequence_pattern_of(chinese)
    assert got_cn, "中文顺序枚举没被识别"


def test_prose_sequence_pattern_rejects_order_free_enumeration():
    """**没有顺序标记**的并列枚举不是套路——这是这条分支以前被删掉的原因。

    "There is the long shot, the intermediate and the close-up" 只是**列举景别**，
    不是镜序；把它判成 `sequence_pattern` 会让 `beat_sequence` 变成编造的顺序。
    """
    from tools.kb_fetch import build_cases as bc

    enumeration = "There is the long shot, the intermediate and the close-up or insert."
    assert bc.prose_sequence_pattern_of(enumeration) == []
    # 同理：只提到一个节拍不算。
    single = "First, the director opens on an establishing shot of the whole street."
    assert bc.prose_sequence_pattern_of(single) == []
