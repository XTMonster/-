"""L3 案例语料（执行文档 v1.4 §2.3b / §2.3c 的 K1–K4 口径 ／ §3.1）。

判据只用**入库产物**（``knowledge/cases.jsonl`` ＋ ``cases.manifest.json``）
与**仓库里已提交的输入**（``knowledge/source_notes/*.md`` ＋ ``knowledge/sources.yaml``），
不依赖 ``work/`` 下的中间产物——那些是被 `.gitignore` 挡住的、跑不出来的环境里
也应当能复核的部分。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from block_director.knowledge.cases import (
    BEAT_TYPES,
    CASE_TYPES,
    CONSTRAINT_KEYS,
)
from block_director.knowledge import cases as case_index
from tools.kb_fetch import build_cases as builder
from tools.kb_fetch import common

ROOT = Path(__file__).resolve().parents[1]
#: 案例索引是**分片**布局（`knowledge/cases/part-*.jsonl`）：判据读的是**索引目录**，
#: 由 `read_cases()` 认分片（也认旧的单文件）。页面上仍写 `knowledge/cases.jsonl`
#: 的地方都在说"这一份索引"，不是"这一份文件"。
CASES_PATH = ROOT / "knowledge"
MANIFEST_PATH = ROOT / "knowledge" / "cases.manifest.json"
NOTES_DIR = ROOT / "knowledge" / "source_notes"

#: §2.3c 写死的 L3 数量门。
MIN_CASES = 300


def _rows() -> list:
    return [row.to_dict() for row in case_index.read_cases(CASES_PATH)]


def test_the_committed_cases_come_from_the_committed_corpus():
    """**L3 必须是这一份语料的产物**——这一条原来根本不存在。

    2026-10-02 的代价：语料从 59 个来源长到 75 之后，`knowledge/cases.jsonl` 整整一天
    没人重建，而本文件的每一条用例都只查**形状与数量下限**，没有一条查"它是不是当前
    语料的产物"。于是 `anime` 域在 L3 里停在 13 篇（重建后是 **120** 篇），插件检索到
    的仍是一天前的案例，**而链路全绿**。

    现在把两层的语料摘要对拍：L3 与 L1/L2 是同一份语料的两个投影，必须记同一枚
    `corpus_sha256`（生产者在 `build_hypergraph.corpus_digest`，两侧共用）。这一格是
    **入库的**，所以干净克隆里也能复核；`build_cases --check` 那条路依赖 `work/` 下的
    中间产物，在这里不作判据。
    """
    cases_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    hyper = json.loads((ROOT / "knowledge" / "hypergraph.manifest.json")
                       .read_text(encoding="utf-8"))
    assert "cards_sha256" in cases_manifest, (
        "L3 的 manifest 必须记下它由哪一份卡片语料产出（否则无从判断是否陈旧）")
    assert cases_manifest["cards_sha256"] == hyper["cache_key"]["corpus_sha256"], (
        "L3 的语料摘要与超图的不一致——两层里至少有一层是从旧语料产出的，"
        "请重跑 `python -m tools.kb_fetch.build_cases`（P14-3）或 `build_hypergraph`（P14-2）")


def test_scanned_illustration_captions_never_become_cases():
    """扫描件的说明文字不许进 L3——**它会当上 `excerpt`**。

    实测（2026-10-02）：拿真实运行的逐镜查询去打 L3，6 条返回里 **2 条**是
    `[Illustration: MELTON MEADOWS. A.` 这种说明文字，双模型面板给 1–2 分，
    E1（案例相关性 ≥70%）得 **0.0**。成因是 `pick_excerpt` 取段首那一对句子，
    而说明句正好排在段首。判据必须在**切窗之前**丢掉这些句子。
    """
    caption = "[Illustration: MELTON MEADOWS. A. Lewis, phot.]"
    assert builder.is_artifact_sentence(caption)
    assert builder.is_artifact_sentence("ILLUSTRATION: THE FILM-MOVING MECHANISM.")
    # 正对照：正常的工艺句子不许被误杀（它只是**提到**了图）。
    assert not builder.is_artifact_sentence(
        "用油斑装置做反射测光时结果不可靠，因为油膜受吸收定律支配。")

    # 形态沿用 `_synthetic_docs()`（已知能产出 narrative 案例），只把说明句塞到最前面——
    # 那正是"说明句当上段首、进而当上 excerpt"的现场。
    doc = _synthetic_docs()[0]
    doc["text"] = caption + " " + doc["text"]
    cases, _rejected, report = builder.build_cases([doc], max_cases=100, per_source=10)
    assert report["per_type"]["narrative"] >= 1, "这段散文本身是可用的语料"
    for row in cases:
        assert not builder.is_artifact_sentence(row["excerpt"]), row["excerpt"]
        assert "illustration" not in row["excerpt"].lower()


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


def test_every_sequence_pattern_is_re_derivable_and_comes_from_a_licensed_source():
    """独立复算（**不再依赖自撰笔记**，2026-10-01）：

    ① 每一条 `sequence_pattern` 的节拍序列必须能从 **`excerpt` 自己**重新推出来
       （切段 → 判节拍 → 去重），且与落盘行逐字相同（含顺序）——顺序写反、节拍与
       文本对不上都会在这里翻红；
    ② 它的 `source_ref.url` 必须出现在**已提交的** `knowledge/sources.yaml` 里，
       即这条套路确实来自一个入库许可来源，而不是随手编的。

    旧版本比的是 `knowledge/source_notes/*.md`（自撰笔记）。用户裁决
    `docs/adr/0013-theory-must-be-authored-by-others.md` 把那批笔记移出语料之后，
    "套路出自自撰笔记"这条判据本身就该消失 —— 换成上面两条，判据**没有放宽**：
    仍然要求可复算、仍然要求出处可查。
    """
    import yaml

    payload = yaml.safe_load((ROOT / "knowledge" / "sources.yaml").read_text(encoding="utf-8"))
    licensed = {str(item.get("url", "")) for item in payload["sources"]}
    rows = [row for row in _rows() if row["case_type"] == "sequence_pattern"]
    assert rows, "L3 里一条 sequence_pattern 都没有（门限要求 ≥1）"
    for row in rows:
        assert row["source_ref"]["url"] in licensed, row["case_id"]
        # 两种写法都覆盖：箭头先折成逗号，再按句读切（与 `prose_sequence_pattern_of`
        # 同一条切分口径；`_beat_of` / `BEAT_TYPES` 都是实现里的同一份表）。
        pieces = re.split(r"[，、；,;]", builder.ARROW_RE.sub("，", row["excerpt"]))
        derived = []
        for piece in pieces:
            beat = builder._beat_of(piece)
            if beat is not None and beat in builder.BEAT_TYPES and beat not in derived:
                derived.append(beat)
        assert derived == row["beat_sequence"], (
            row["case_id"], derived, row["beat_sequence"])
        assert len(derived) >= 2


def test_the_case_corpus_holds_no_self_written_sources():
    """ADR-0013 守卫：**L3 案例层里不许再有自撰来源**。

    这条测试原来比的是"自撰笔记能逐个字段重建出同一批案例"。用户裁决
    `docs/adr/0013-theory-must-be-authored-by-others.md`（"理论不要自己写，
    要别人写的"）之后，那批笔记退出语料，于是这条判据的前提消失了 ——
    换成**它的反面**，也就是裁决本身：

      ① `knowledge/cases.jsonl` 里**零条** `repo://`（`OWNWORK_SCHEME`）案例；
      ② `knowledge/sources.yaml` 里**零条** `mode: manual`；
      ③ 每条案例的 `source_ref.url` 都是 `http(s)://` —— 与生成卡的署名门同口径。

    仓库里的 `knowledge/source_notes/*.md` 仍作为设计文档保留，它们**不再是语料**。
    """
    import yaml

    rows = _rows()
    own = [row["case_id"] for row in rows
           if str(row["source_ref"]["url"]).startswith(common.OWNWORK_SCHEME)]
    assert own == [], f"案例层还有自撰来源：{own[:5]}"
    payload = yaml.safe_load((ROOT / "knowledge" / "sources.yaml").read_text(encoding="utf-8"))
    manual = [item.get("url") for item in payload["sources"]
              if str(item.get("mode")) == "manual"]
    assert manual == [], f"sources.yaml 还有 mode: manual：{manual}"
    bad = [row["case_id"] for row in rows
           if not str(row["source_ref"]["url"]).startswith(("http://", "https://"))]
    assert bad == [], f"非 http(s) 来源：{bad[:5]}"


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
                                        "sequence_enumerations_not_measured",
                                        "sequence_pattern_dropped"))]
    assert shape == []
    assert any(problem.startswith("cases_too_few")
               for problem in verdict["problems"])
    # 合成语料里一条显式枚举都没有 → 这条门**测不到东西**，按 §4.1b 的分母下界
    # 判失败（旧口径在这里报的是 `sequence_pattern_too_few`，见 `SEQUENCE_FLOOR`
    # 的注释：常量的旧依据是自撰笔记，已被用户裁决移出语料）。
    # 注意：这份合成语料**确实有一条**散文顺序枚举（"先…然后…最后…"），所以
    # 新的门限（产出 ≥ 语料里的枚举数 ≥1）是**满足**的 —— 唯一该红的是"远不到 300 篇"。
    # 这正好证明新判据不是"凡是小语料都红"，而是真的在比产出与枚举数。
    assert report_a["enumerations_in_corpus"] == 1
    assert report_a["per_type"]["sequence_pattern"] == 1
    assert all(problem.startswith("cases_too_few") for problem in verdict["problems"])


def test_the_sequence_gate_fails_when_the_corpus_has_more_enumerations_than_cases():
    """**漏抽即红**：语料里有 3 条显式枚举、只产出 1 条 → 判失败。

    这是"改门限"之后这条门真正的鉴别力所在：它不再比一个来自已删数据的魔数，
    而是比"产出 == 语料真实存在的枚举数"。配额截断、切分退化、近重复误杀
    都会在这里翻红。
    """
    cases = [{"case_id": "case_x_pseq001", "case_type": "sequence_pattern",
              "title": "镜序套路：示范", "excerpt": "先建立，再覆盖，最后反应。",
              "beat_sequence": ["establish", "coverage", "reaction"],
              "source_ref": {"url": "https://example.org/x", "title": "t",
                             "author": "a", "license": "PublicDomain",
                             "retrieved_at": "2026-01-01", "sha256": "0" * 64},
              "score": 0.0}]
    report = {"cases": 1, "min_cases": 1, "reject_ratio": 0.0,
              "per_type": {"narrative": 0, "sequence_pattern": 1, "lesson": 0},
              "enumerations_in_corpus": 3}
    verdict = builder.evaluate(cases, report)
    assert verdict["passed"] is False
    assert any(problem.startswith("sequence_pattern_dropped:1<3")
               for problem in verdict["problems"]), verdict["problems"]


def test_the_case_budget_is_shared_across_sources_not_taken_in_url_order():
    """配额**轮转**分配：URL 靠后的来源不许被前面的吃干。

    实测事故（2026-10-01 重建后）：一遍到底的写法按 URL 字母序谁先来谁吃满 810 条，
    结果 9 个域里 `anime` / `production` / `blocking` **一条案例都没有**——而动漫与
    制片正是用户点名要的域。轮转之后每个来源先各拿 1 条，只有预算连来源数都不够时
    才会出现空来源。
    """
    docs = []
    #: 六条**互不近重复**的顺序枚举（SimHash 按 excerpt 判近重复，所以每条都得换词、
    #: 换节拍组合、换句式，不能只改一个数字）。
    enumerations = (
        "先给一个建立镜头交代码头的位置关系，再切到两人正反打的覆盖镜头，"
        "最后落到信封上的一处细节。",
        "开场先用远景交代空荡的街道，随后插入招牌上的细节，"
        "最后落在主角脸上的反应。",
        "first establish the empty street with a long shot, then cut to coverage "
        "of the two men, and finally dissolve to a close-up of the letter.",
        "首先用远景交代整条街道的走向，接着切成中景让观众看清两人的站位，"
        "最后用一次淡出收尾。",
        "开场先交代餐厅的整体位置，再切到杯子的特写，最后落在两人的反应镜头上。",
        "先用全景交代桌面的文件，随后插入窗外雨的细节。",
    )
    for index, body in enumerate(enumerations):
        docs.append({"source_ref": {"url": f"https://example.org/book{index}",
                                    "title": f"示范书{index}", "author": "作者",
                                    "license": "PublicDomain",
                                    "retrieved_at": "2026-01-01",
                                    "sha256": "0" * 64},
                         "text": body, "mode": "http", "domain": "storyboard"})
    # 预算只够每个来源 1 条（6 份来源 / 预算 6）。
    cases, _rejected, report = builder.build_cases(docs, max_cases=6, per_source=40)
    per_source = report["per_source"]
    assert len(per_source) == 6, per_source
    assert all(count >= 1 for count in per_source.values()), per_source
    assert len(cases) == 6


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


# --------------------------------------------------------------------------- #
# **分片布局**（2026-10-04）。为什么这一组必须存在：体积门是"**单文件** ≤ 512 KB、
# **总量** ≤ 20 MB"，不是"整库只有一份文件"——`knowledge/cards_generated/` 本来就是
# "一域一份"。案例层把整库塞进一份 `cases.jsonl`，于是配额被迫按单文件反推
# （`DEFAULT_MAX_CASES = 810`，实测 499 KB），供给被掐掉九成
# （`raw_segments = 10463` 只收 810，`quota_truncated = 9376`）。
# 分片解掉的是那个**隐含**约束，一个门都没放宽：每片 ≤ 512 KB、总量 ≤ 20 MB。
# --------------------------------------------------------------------------- #


def _probe_rows(count: int = 8) -> list:
    """合成案例行：分片用例只关心"整库有多大、切点落在哪"，不必跑语料构建。

    直接用行（而不是 `build_cases()`）是刻意的：语料层有 SimHash 近重复门，
    为它造"内容真的不同"的正文会把这条用例变成语料层的测试。这里要测的是**切法**。
    """
    rows = []
    for index in range(count):
        rows.append({
            "case_id": f"case_probe_{index:03d}", "case_type": "narrative",
            "title": f"标题 {index}",
            #: 每行 ~300 B，8 行 ≈ 2.4 KB —— 用 `target_bytes=900` 就能切出多片。
            "excerpt": f"第 {index} 条：逆光勾边与浅景深在同一个镜头里互相打架。"
                       "轮廓光要压在背景上方两档，对焦点落在近眼。",
            "beat_sequence": [],
            "source_ref": {
                "url": f"https://example.org/probe-{index}", "title": f"来源 {index}",
                "author": "作者", "license": "PublicDomain",
                "retrieved_at": "2026-01-01",
                "sha256": f"{index:064d}",
            },
            "score": 0.0,
        })
    return rows


def _probe_report(rows: list) -> dict:
    return {"cases": len(rows), "raw_segments": len(rows), "quota_truncated": 0,
            "duplicates": 0, "rejects": 0, "reject_ratio": 0.0,
            "per_type": {"narrative": len(rows)}, "per_domain": {"storyboard": len(rows)},
            "per_source": {f"probe-{index}": 1 for index in range(len(rows))},
            "segments_total": len(rows), "enumerations_in_corpus": 1, "min_cases": 1}


def test_the_sharded_layout_is_a_byte_faithful_split(tmp_path):
    """分片**只是同一份索引的切法**：各片按序拼接 == 一份单文件的字节。"""
    from block_director.knowledge import cases as C

    cases = _probe_rows()
    report = _probe_report(cases)
    assert len(cases) >= 4, "夹具太小，量不出切点"
    #: 切点必须**只落在行边界**，且同一个输入得到同一组分片。
    assert builder.plan_shards(cases, target_bytes=900) == \
        builder.plan_shards(cases, target_bytes=900)
    assert len(builder.plan_shards(cases, target_bytes=900)) >= 2

    out = tmp_path / "knowledge"
    manifest = builder.write_outputs(cases, report, docs=[], out_dir=out,
                                     out_manifest=out / "cases.manifest.json",
                                     )
    shards = C.case_paths(out)
    assert shards, "分片布局没落地"
    for path in shards:
        assert path.stat().st_size <= builder.MAX_CASE_FILE_BYTES, path
    joined = b"".join(path.read_bytes() for path in shards)
    reference = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                        for row in cases).encode("utf-8")
    assert joined == reference, "分片拼接后与单文件不是同一份字节"
    assert [row.to_dict() for row in C.read_cases(out)] == cases
    assert manifest["size_gate"]["passed"], manifest["size_gate"]
    sizes = manifest["size_gate"]["sizes"]
    assert sum(size for name, size in sizes.items()
               if name != "cases.manifest.json") == len(joined)
    #: 分片账目与目录里真实的文件一一对应（否则"入库了几片"没人对得上）。
    assert sorted(item["name"] for item in manifest["shards"]) == \
        sorted(f"cases/{path.name}" for path in shards)


def test_the_clue_shards_round_trip_through_the_consumer(tmp_path):
    """线索也分片，且**消费者按同一口径**读得回来（代际摘要不因分片而变）。"""
    from block_director.knowledge import cases as C
    from tools.kb_fetch import case_search_zh as ZH

    cases = _probe_rows()
    report = _probe_report(cases)
    out = tmp_path / "knowledge"
    builder.write_outputs(cases, report, docs=[], out_dir=out,
                          out_manifest=out / "cases.manifest.json")
    digest = ZH.cases_digest(out)
    rows = [{"case_id": row["case_id"], "zh": "镜头缓缓推近市场摊位的货物细节",
             "cases_sha256": digest, "model": "stub", "family": "zhipu",
             "prompt_sha256": "0" * 64} for row in cases]
    assert ZH.write_lines(out / "cases", rows)["files"]
    lines, reason = C.read_search_zh(out, out)
    assert reason == "", reason
    assert set(lines) == {row["case_id"] for row in cases}
    #: 分片线索与旧布局的单文件线索**同代**（摘要口径相同）。
    assert digest == C.cases_digest(C.case_paths(out))
    #: 拿旧布局的入参（一份 jsonl）也读得回来。
    single = tmp_path / "legacy.jsonl"
    single.write_text(joined_text := "".join(
        json.dumps(row, ensure_ascii=False) + "\n" for row in cases), encoding="utf-8")
    (tmp_path / "knowledge2").mkdir()
    (tmp_path / "knowledge2" / "cases.jsonl").write_text(joined_text, encoding="utf-8")
    legacy_digest = ZH.cases_digest(tmp_path / "knowledge2" / "cases.jsonl")
    assert legacy_digest == C.cases_digest(C.case_paths(tmp_path / "knowledge2"))
