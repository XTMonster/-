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
            + manifest["rejects"] + manifest["clue_gate_dropped"]
            ) == manifest["raw_segments"], (
        "账目必须闭合：案例 + 重复 + 配额 + 拒收 + **线索闸门丢弃** == 参评候选数"
        "（闸门关着时最后一格恒为 0）")
    assert manifest["reject_ratio"] <= builder.BUILD_REJECT_RATIO
    assert manifest["segments_total"] >= manifest["raw_segments"] >= 1
    assert manifest["fingerprint"] and manifest["corpus_fingerprint"]
    assert manifest["size_gate"]["passed"] is True
    # §2.3d T1 的消费对象：门是**已提交语料里显式枚举的套路条数**（只许升）。
    assert manifest["per_type"]["sequence_pattern"] >= builder.SEQUENCE_FLOOR


def _clue_file(tmp_path, mapping):
    path = tmp_path / "clues.jsonl"
    path.write_text("".join(
        json.dumps({"case_id": case_id, "zh": zh}, ensure_ascii=False) + "\n"
        for case_id, zh in mapping.items()), encoding="utf-8")
    return path


def test_the_clue_gate_drops_only_cases_without_a_key(tmp_path):
    """入库闸门：`after` 之前豁免、之后必须**有中文检索键**才许进（glm-5.3 会诊 F1）。

    为什么这条是必要的：L3 服务的是**中文**逐镜查询，而没有 `zh` 键的英文案例对产品
    恒 0 命中（实测：只喂英文原文时 676 条里只剩 1 条假命中）。所以扩库的正确顺序是
    **先注线索、非空才入库**——否则 `线索数 / 案例数` 这条守门比例只会被稀释。
    """
    cases = [{"case_id": f"c{index}", "case_type": "narrative"} for index in range(5)]
    path = _clue_file(tmp_path, {"c2": "要拍固定机位时把相机锁死", "c4": ""})

    kept, dropped, report = builder.apply_clue_gate(cases, path)
    assert [case["case_id"] for case in kept] == ["c2"]
    assert dropped == ["c0", "c1", "c3", "c4"], dropped   # 空串不算键
    assert report == {"required_after": 0, "protected": 0, "keyed": 1,
                      "kept": 1, "dropped": 4}

    #: `after=3`：前三条豁免（历史不因新规则被删），后两条仍要有键。
    kept, dropped, report = builder.apply_clue_gate(cases, path, after=3)
    assert [case["case_id"] for case in kept] == ["c0", "c1", "c2"]
    assert dropped == ["c3", "c4"], dropped


def test_the_protect_band_is_by_id_not_by_position(tmp_path):
    """保护带必须**按 id**——按下标那条路在"扩了 `--max-cases`"之后会**换掉**历史案例。

    2026-10-04 实测的形状：上一版发货 810 条，把 `--max-cases` 从 810 抬到 1400 之后，
    `--require-clue-after 810` 保住的是"**按 `case_id` 排序后**的前 810 条"，它与上一版
    那 810 条**不是同一批**——实测换掉了 **149 条**，`tests/test_source_traces.py`
    当场抓到 **9 条来源**没了任何产物（它们的案例全被换出去，卡片里也没有）。
    这条用例把那个形状钉死：按下标豁免的是**位置**，按 `protect_ids` 豁免的才是**案例**。
    """
    cases = [{"case_id": f"c{index:03d}", "case_type": "narrative"}
             for index in reversed(range(6))]
    path = _clue_file(tmp_path, {"c003": "要拍缓推镜头时让镜头慢慢靠近"})

    #: 按下标：前 3 条（`c005/c004/c003`）豁免——豁免的是**位置**。
    kept_by_index, _dropped, _report = builder.apply_clue_gate(cases, path, after=3)
    assert [case["case_id"] for case in kept_by_index] == ["c005", "c004", "c003"]

    #: 按 id：`c002` 是"历史"，按下标那条路会把它丢掉，按 id 这条路保住它。
    kept_by_id, dropped_by_id, report = builder.apply_clue_gate(
        cases, path, protect_ids=["c002"])
    assert [case["case_id"] for case in kept_by_id] == ["c003", "c002"]
    assert dropped_by_id == ["c005", "c004", "c001", "c000"]
    assert report == {"required_after": 0, "protected": 1, "keyed": 1,
                      "kept": 2, "dropped": 4}
    assert "c002" not in {case["case_id"] for case in kept_by_index}, \
        "这条用例的前提是「按下标会把历史案例换出去」——形状变了"


def test_the_shipped_manifest_accounts_for_the_clue_gate_without_inventing_numbers():
    """发货的 manifest 必须把"线索闸门"**如实、自洽**地记账。

    这条原叫 `..._is_off_by_default_in_the_shipped_manifest`，判据是"那一格恒为 0、
    且不许有 `clue_gate` 键"——钉的是"闸门关着"这**一种**形态。2026-10-04 起发货的
    索引**本来就是走闸门落地的**（会诊 F1：先注线索、非空才入库；
    `build_cases --require-clue … --require-clue-after 810`），于是判据从"闸门永远关"
    演进成"**开没开都要自洽，且数字不许凭空来**"——比原判据**更严**：原判据只挡一种
    写法，这条把两种写法都钉住，并加了对账。

    "先注线索、非空才入库"在账上的**直接表达式**是 `keyed == clue_attached.clues`：
    闸门只许丢掉**没有键**的案例，丢一条带键的就是把检索面白送出去。
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    gate = manifest.get("clue_gate")
    if gate is None:
        assert manifest["clue_gate_dropped"] == 0, (
            "没有 `clue_gate` 账时那一格必须是 0——否则'丢弃数'是个无出处的数")
        return
    assert manifest["clue_gate_dropped"] == gate["dropped"], (
        "`clue_gate_dropped` 与 `clue_gate.dropped` 对不上")
    assert gate["kept"] == manifest["cases"], (
        "`clue_gate.kept` 必须等于最终案例数（闸门之后就是索引）")
    #: **先注线索、非空才入库**：带中文检索键的案例一条都不许被闸门丢掉。
    assert gate["keyed"] == manifest["clue_attached"]["clues"], (
        "闸门丢掉了带中文检索键的案例——那正是这条闸门要保住的东西")
    #: 闸门只删不加 ⇒ 闸门前的接受数 = 现案例数 ＋ 丢掉数，且它落在参评候选之内。
    accepted_before_gate = manifest["cases"] + gate["dropped"]
    assert accepted_before_gate <= manifest["raw_segments"], (
        accepted_before_gate, manifest["raw_segments"])
    assert gate["required_after"] <= manifest["cases"], gate


def test_the_gate_re_signs_the_clues_so_the_pair_stays_consistent(tmp_path):
    """过滤之后**必须重签**线索：不重签，读者会因为摘要对不上整份拒用（中文恒 0 命中）。

    这一条走的是真读者（`case_index.read_search_zh`）：它自己按案例分片算摘要，
    所以"重签对没对"不是我说了算。
    """
    out_dir = tmp_path / "index"
    (out_dir / "cases").mkdir(parents=True)
    cases = [{"case_id": "c1", "case_type": "narrative", "title": "t1",
              "excerpt": "A slow dolly in.", "beat_sequence": [],
              "source_ref": {"title": "s", "url": "https://example.invalid/a",
                             "author": "a", "license": "PublicDomain",
                             "retrieved_at": "2026-10-02T00:00:00+00:00",
                             "sha256": "0" * 64}, "score": 0.0},
             {"case_id": "c2", "case_type": "narrative", "title": "t2",
              "excerpt": "Cut on the eyeline.", "beat_sequence": [],
              "source_ref": {"title": "s", "url": "https://example.invalid/a",
                             "author": "a", "license": "PublicDomain",
                             "retrieved_at": "2026-10-02T00:00:00+00:00",
                             "sha256": "0" * 64}, "score": 0.0}]
    common.write_jsonl(out_dir / "cases" / "part-000.jsonl", cases)
    digest = case_index.cases_digest(case_index.case_paths(out_dir))

    clues = _clue_file(tmp_path, {
        "c1": "要拍缓推镜头时让镜头慢慢靠近",
        "c2": "",                       # 空串不算键：不许进线索文件
        "c9": "这条指向一条不在索引里的案例",  # 不在保留集合里：不许进
    })
    info = builder.attach_clues(clues, ["c1", "c2"], digest, out_dir)
    assert info["clues"] == 1, info
    #: 真读者：摘要对得上才算同代。
    lines, reason = case_index.read_search_zh(out_dir, out_dir)
    assert reason == "", reason
    assert list(lines) == ["c1"], lines


def test_attach_clues_refuses_a_digest_the_reader_would_reject(tmp_path):
    """自证：摘要写错时，读者必须**整份拒用**（否则上面那条只是自我感觉良好）。"""
    out_dir = tmp_path / "index"
    (out_dir / "cases").mkdir(parents=True)
    common.write_jsonl(out_dir / "cases" / "part-000.jsonl",
                       [{"case_id": "c1", "case_type": "narrative", "title": "t",
                         "excerpt": "x", "beat_sequence": [], "source_ref": {},
                         "score": 0.0}])
    clues = _clue_file(tmp_path, {"c1": "要拍缓推镜头时让镜头慢慢靠近"})
    builder.attach_clues(clues, ["c1"], "0" * 64, out_dir)     # 故意写错摘要
    lines, reason = case_index.read_search_zh(out_dir, out_dir)
    assert lines == {} and reason == "search_zh_stale"


def test_recount_keeps_the_domain_breakdown_after_cases_are_filtered(tmp_path):
    """闸门/过滤丢掉一批案例之后，`recount()` 必须按**剩下的**案例重算 `per_domain`。

    案例行上**没有** `domain` 字段（domain 是**计划期**的概念，不属案例契约），
    所以 `recount()` 只能靠 `build_cases()` 留下的私有账 `report["_case_domains"]`
    （`case_id -> domain`）。不留这张表，每一格都会算成空串 ⇒
    `per_domain == {"": n}`：分域账当场失真，**而和数仍然对**——所以
    `test_the_manifest_accounting_adds_up` 那条"和数"判据**抓不到它**。
    这正是 2026-10-04 落地 `--require-clue` 时实测踩到的形状。
    """
    docs = _synthetic_docs()
    second = json.loads(json.dumps(docs[0]))
    second["domain"] = "cinematography"
    second["source_ref"] = {**second["source_ref"], "url": "https://example.org/book2"}
    second["text"] = (
        "用长焦镜头压缩空间的时候，前后景几乎贴在一起，人物像从背景里浮出来，"
        "背景被虚化成一块柔光，纵深感因此被削平。"
        "手持跟拍会让画面带着呼吸感，但也把构图交给运气，肩扛镜头想要走长还得靠"
        "稳定器压住抖动，否则观众先看到的是晃。"
        "顺光会让脸显得扁平，暗调反而能靠轮廓把注意力收拢到眼睛上，侧逆光是常用的"
        "折中，但要当心鼻影把半个脸吃掉。"
        "大光圈把焦点压得极薄，两个演员只要前后差半步就有一个虚掉，走位必须事先在"
        "地面上标好点位，否则对焦只有一次机会。"
    )
    cases, _rejected, report = builder.build_cases([*docs, second], max_cases=10_000,
                                                   per_source=40)
    assert set(report["per_domain"]) >= {"storyboard", "cinematography"}, \
        report["per_domain"]

    #: 只留第二个域的那批，`recount()` 必须给出一本**只含该域**的账（不是 `{"": n}`）。
    kept = [row for row in cases
            if str((row.get("source_ref") or {}).get("url") or "").endswith("book2")]
    assert kept, "第二个域的正文没有产出任何案例，这条用例量不到东西"
    after = builder.recount(kept, report)
    assert set(after["per_domain"]) == {"cinematography"}, after["per_domain"]
    assert sum(after["per_domain"].values()) == len(kept) == after["cases"]

    #: 私有账（下划线前缀）**不许**进 manifest——它只是 `recount()` 的输入。
    out = tmp_path / "knowledge"
    manifest = builder.write_outputs(kept, after, docs=[], out_dir=out,
                                     out_manifest=out / "cases.manifest.json")
    assert not [key for key in manifest if str(key).startswith("_")], \
        sorted(manifest.keys())


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


def test_the_shipped_manifest_records_how_to_rebuild_itself():
    """`--check` 必须能**按产物自己记的参数**复算（会诊 D4）。

    现场（2026-10-05）：发货索引是走闸门落地的（`--require-clue` ＋
    `--require-clue-keep` ＋ `--max-cases 810`），而 `--check` 原来只按**命令行**
    重算 ⇒ 默认参数一跑就是另一份索引（实测 `cases_match: false`、exit 1）。
    "这份产物是怎么来的"必须能从产物本身读出来，否则那条检查只是一句空话。

    判据分三段：① manifest 记了 `build_args`；② 闸门那两个输入**在仓库里存在**
    （不能指向 gitignore 的草稿区，否则换台机器就复算不了）；③ 保护表里的
    case_id 必须是**这份索引里的**（点错表等于没设保护带）。
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    args = manifest.get("build_args")
    assert args, "manifest 没记 build_args：`--check` 只能靠命令行猜"
    assert args["max_cases"] == 810 and args["require_clue"], args

    root = ROOT
    clues = root / args["require_clue"]
    protect = root / args["require_clue_keep"]
    assert clues.is_file(), f"线索输入不在仓库里：{clues}"
    assert protect.is_file(), f"保护表不在仓库里：{protect}"

    live = {str(case.case_id) for case in case_index.read_cases(CASES_PATH)}
    protected = {str(row.get("case_id")) for row in common.read_jsonl(protect)}
    assert protected, "保护表是空的"
    assert protected <= live, (
        f"保护表里有 {len(protected - live)} 个 case_id 不在发货索引里——保护带点错了表"
    )
    #: 保护带的意义是**来源痕迹**：每个这样的来源至少留一条。
    assert manifest["clue_gate"]["protected"] == len(protected)
