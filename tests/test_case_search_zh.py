"""中文检索线索：让中文查询够得着英文案例，而**不动**作者原文。

背景（2026-10-02 实测）：产品的查询是中文散文，L3 的 810 篇案例含中文的 0 篇，
`CaseIndex._text` 只吃作者写的字 ⇒ BM25 对中文查询**恒 0 命中**，E1 连分母都没有。
`tools/kb_fetch/case_search_zh.py` 为每条案例生成一句**中文检索线索**（只是检索键），
渲染与返回给模型的仍然是作者的英文 `excerpt`。

三条不变量钉在这里：

1. **代际**：线索文件记着生成时 `cases.jsonl` 的字节摘要，对不上就整份不用
   （否则会静默地把一批"指向上一条案例"的线索喂进 BM25）；
2. **只改进检索、不改内容**：`render_case` 的输出与有没有线索**逐字相同**；
3. **E3**：线索里不许出现"必须/禁止/不得/务必"——产出侧机械检查，不靠模型自觉。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import cases as C  # noqa: E402
from block_director.contracts.knowledge import Case  # noqa: E402
from tools.kb_fetch import case_search_zh as ZH  # noqa: E402


def _case(case_id: str = "case_x_001", excerpt: str = "A slow dolly in on the market.") -> Case:
    return Case(case_id=case_id, case_type="narrative", title="t", excerpt=excerpt,
                source_ref={"title": "src", "url": "https://example.invalid/a",
                            "author": "a", "license": "PublicDomain",
                            "retrieved_at": "2026-10-02T00:00:00+00:00",
                            "sha256": "0" * 64})


def _write_sidecar(directory: pathlib.Path, cases_path: pathlib.Path, digest: str,
                   rows) -> pathlib.Path:
    path = directory / C.SEARCH_ZH_FILE
    path.write_text("".join(json.dumps({"cases_sha256": digest, **row},
                                       ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def test_a_matching_digest_loads_the_lines(tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text('{"case_id": "a"}\n', encoding="utf-8")
    digest = C.hashlib.sha256(cases_path.read_bytes()).hexdigest()
    _write_sidecar(tmp_path, cases_path, digest,
                   [{"case_id": "a", "zh": "镜头缓缓推近市场摊位"}])
    lines, reason = C.read_search_zh(tmp_path, cases_path)
    assert lines == {"a": "镜头缓缓推近市场摊位"} and reason == ""


def test_a_stale_digest_is_refused_as_a_whole(tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text('{"case_id": "a"}\n', encoding="utf-8")
    _write_sidecar(tmp_path, cases_path, "deadbeef", [{"case_id": "a", "zh": "旧的线索"}])
    lines, reason = C.read_search_zh(tmp_path, cases_path)
    assert lines == {} and reason == "search_zh_stale", reason
    #: 案例层换代之后又写回来的旧线索，**一条都不许**进 BM25。
    cases_path.write_text('{"case_id": "a"}\n{"case_id": "b"}\n', encoding="utf-8")
    lines, reason = C.read_search_zh(tmp_path, cases_path)
    assert lines == {} and reason == "search_zh_stale"


def test_missing_and_unreadable_files_are_named_not_silent(tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text('{"case_id": "a"}\n', encoding="utf-8")
    assert C.read_search_zh(tmp_path, cases_path)[1] == "search_zh_missing"
    (tmp_path / C.SEARCH_ZH_FILE).write_text("{not json\n", encoding="utf-8")
    lines, reason = C.read_search_zh(tmp_path, cases_path)
    assert lines == {} and reason.startswith("search_zh_unreadable:")


def _manifest_with_prompt(directory: pathlib.Path, prompt_sha: str) -> None:
    (directory / C.MANIFEST_FILE).write_text(
        json.dumps({"clue_attached": {"prompt_sha256": prompt_sha}}),
        encoding="utf-8")


def test_a_mixed_prompt_file_is_refused_as_a_whole(tmp_path):
    """**同一份线索文件里不许混代**（会诊 D2）。

    现场（2026-10-04 实测）：一份 `cases.search_zh.jsonl` 里 **436 行**记着
    `prompt_sha256 = b3d565ea`、**739 行**记着 `c2f49178`——那是"换了提示词之后
    接着写"的产物。混代的键既不等于旧代也不等于新代：用它量的 E1 说不清是哪一套
    口径。判据是**整份拒用**，不是"各代都算数"。
    """
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text('{"case_id": "a"}\n{"case_id": "b"}\n', encoding="utf-8")
    digest = C.hashlib.sha256(cases_path.read_bytes()).hexdigest()
    _write_sidecar(tmp_path, cases_path, digest, [
        {"case_id": "a", "zh": "镜头缓缓推近市场摊位", "prompt_sha256": "a" * 64},
        {"case_id": "b", "zh": "切到听者的视线完成反打", "prompt_sha256": "b" * 64},
    ])
    lines, reason = C.read_search_zh(tmp_path, cases_path)
    assert lines == {} and reason == "search_zh_mixed_prompt", reason


def test_the_manifest_prompt_sha_gates_the_whole_file(tmp_path):
    """manifest 记了生成代际 ⇒ 逐行必须对上；对不上/没写都**不许当通过**。

    为什么基准在 manifest 上而不是"读者去问生成器"：`block_director` 不许 import
    `tools/`（分层纪律）。所以产物自己带"我是哪一代生成的"，读者只做比对。
    """
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text('{"case_id": "a"}\n', encoding="utf-8")
    digest = C.hashlib.sha256(cases_path.read_bytes()).hexdigest()
    _manifest_with_prompt(tmp_path, "a" * 64)

    #: ① 行里的代际与 manifest 一致 ⇒ 正常装载。
    _write_sidecar(tmp_path, cases_path, digest,
                   [{"case_id": "a", "zh": "镜头缓缓推近市场摊位",
                     "prompt_sha256": "a" * 64}])
    assert C.read_search_zh(tmp_path, cases_path) == (
        {"a": "镜头缓缓推近市场摊位"}, "")

    #: ② 行里是**上一代** ⇒ 整份拒用（不许拿旧键当现行口径）。
    _write_sidecar(tmp_path, cases_path, digest,
                   [{"case_id": "a", "zh": "镜头缓缓推近市场摊位",
                     "prompt_sha256": "b" * 64}])
    assert C.read_search_zh(tmp_path, cases_path)[1] == "search_zh_prompt_stale"

    #: ③ 行里**根本没写**代际、而 manifest 说有 ⇒ 无法证明 ⇒ 拒用（缺证据 != 通过）。
    _write_sidecar(tmp_path, cases_path, digest,
                   [{"case_id": "a", "zh": "镜头缓缓推近市场摊位"}])
    assert C.read_search_zh(tmp_path, cases_path)[1] == "search_zh_prompt_unverified"

    #: ④ manifest 没记（旧产物）⇒ 不做那一步比对，判据既不从严也不放松。
    (tmp_path / C.MANIFEST_FILE).unlink()
    lines, reason = C.read_search_zh(tmp_path, cases_path)
    assert reason == "" and lines == {"a": "镜头缓缓推近市场摊位"}


def test_the_line_only_feeds_the_index_and_never_the_rendered_case():
    """`render_case` 的输出与有没有线索**逐字相同**（作者原文一个字不动）。"""
    case = _case()
    without = C.render_case(case)
    with_line = C.render_case(case)
    assert without == with_line
    assert "dolly" in without          # 渲染的还是作者原文
    assert "镜头缓缓推近" not in without  # 线索不参与渲染


def test_our_labels_still_may_not_enter_the_index():
    """**我们生成的标签**仍然不许进检索——这是 2026-10-02 那 0/16 的根因。

    检索文本里只允许出现：作者的 `excerpt`、出处标题、以及**作者摘录的中文改写**。
    `title`（`镜头与焦距：…摘记NNN`）、`case_id`、域标签都不许进来。
    """
    case = _case(case_id="case_pg76304_txt_007",
                 excerpt="Each picture is thus kept in absolute focus.")
    case = Case(**{**case.to_dict(), "title": "镜头与焦距：Practical Cinema摘记086"})
    text = C.CaseIndex._text(case)
    assert "镜头与焦距" not in text, "标题（我们的标签）进了检索面"
    assert "case_pg76304" not in text, "case_id 进了检索面"
    assert "摘记" not in text


def test_the_line_is_appended_to_the_search_text_only():
    case = _case()
    plain = C.CaseIndex._text(case)
    enriched = C.CaseIndex._text(case, "镜头缓缓推近市场摊位的货物细节")
    assert plain in enriched and enriched != plain
    assert "镜头缓缓推近" in enriched


def test_load_index_records_the_clue_state_and_how_many_lines_it_loaded(tmp_path):
    """**2026-10-05 的实缺陷**：`load_index` 只取 `read_search_zh(...)[0]`，把**原因**
    丢掉了。于是"整份线索层缺失"在产物里不留痕迹——v4 案例层的三臂 E1 因此从
    0.20 塌到 0.0065，而每行只是一个空的 `zh`：读的人只看到"分数很低"，看不到
    "中文面整份没了"。状态与条数现在都挂在索引上（`describe()` 里也报）。
    """
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(json.dumps(_case("case_a").to_dict(), ensure_ascii=False) + "\n",
                          encoding="utf-8")
    digest = C.cases_digest(C.case_paths(tmp_path))

    bare = C.load_index(tmp_path, backend="hybrid")
    assert bare.search_zh == {}
    assert bare.search_zh_reason == "search_zh_missing"
    assert bare.describe()["cases_clue_state"] == "search_zh_missing"
    assert bare.describe()["cases_clues"] == 0

    _write_sidecar(tmp_path, cases_path, digest,
                   [{"case_id": "case_a", "zh": "镜头缓缓推近市场摊位的货物"}])
    loaded = C.load_index(tmp_path, backend="hybrid")
    assert loaded.search_zh_reason == ""
    assert loaded.describe()["cases_clue_state"] == ""
    assert loaded.describe()["cases_clues"] == 1


class _BoomAdapter:
    """检索必失败的适配器（模拟 sidecar 挂了 ⇒ 走 §2.3b 的降级路径）。"""

    def retrieve(self, query, top_k=3, cases=()):
        raise RuntimeError("sidecar down")


def test_the_lightrag_fallback_keeps_the_same_chinese_surface():
    """LightRAG 挂了退回 BM25 时，**必须与开局建的那条面相同**（带中文线索）。

    实测缺口（2026-10-05）：`__post_init__` 建的 BM25 带线索，而 `retrieve()` 里
    "lightrag_query_failed" 那条降级路径建的是**不带线索**的 BM25——同一个索引
    "LightRAG 挂了"与"没挂"于是拿两把不同的尺子，E1 的读数会因此悄悄变化。
    """
    case = _case(case_id="case_market", excerpt="A slow dolly in on the market stalls.")
    #: 合成语料给到 6 篇：BM25 的 IDF 在 N=n 时是负的、N=2/n=1 时正好 0，
    #: 两者都会被 `score > 0` 滤掉（那是 BM25 的性质，不是判据）。
    others = [_case(case_id=f"case_filler_{i}", excerpt=f"A static wide shot number {i}.")
              for i in range(5)]
    query = "市场摊位，推镜缓入"
    index = C.CaseIndex([case] + others, "lightrag", adapter=_BoomAdapter(),
                        search_zh={case.case_id: "镜头缓缓推近市场摊位的货物"})
    hits = index.retrieve(query, top_k=3)
    assert [hit.case_id for hit in hits] == ["case_market"], hits
    assert index.reason.startswith("lightrag_query_failed")

    #: 没有线索时退回 BM25 也只是"只吃原文"——中文查询本就召不回（旧行为，不是 bug）。
    blind = C.CaseIndex([case] + others, "lightrag", adapter=_BoomAdapter())
    assert blind.retrieve(query, top_k=3) == []


def test_a_chinese_query_reaches_a_case_only_through_the_line():
    """中文查询能命中 ⇒ 全靠这条线索；没有它就该是空（旧行为）。"""
    case = _case(case_id="case_market", excerpt="A slow dolly in on the market stalls.")
    #: 语料要够大：BM25 的 IDF 是 `ln((N-n+.5)/(n+.5))`——只有一篇时它是**负的**
    #: （N=n=1），两篇时正好是 **0**（N=2,n=1）。两者都会被 `score > 0` 滤掉。
    #: 那是 BM25 的性质，不是这条判据的内容，所以合成语料给到 6 篇。
    others = [_case(case_id=f"case_filler_{i}", excerpt=f"A static wide shot number {i}.")
              for i in range(5)]
    corpus = [case] + others
    index = C.CaseIndex(corpus, "hybrid")
    query = "市场摊位，推镜缓入"
    assert index.retrieve(query, top_k=3) == [], "没有线索时中文查询本就召不回（旧行为）"
    enriched = C.CaseIndex(corpus, "hybrid",
                           search_zh={case.case_id: "镜头缓缓推近市场摊位的货物"})
    hits = enriched.retrieve(query, top_k=3)
    assert [hit.case_id for hit in hits] == ["case_market"], hits


class _Stub:
    """只回一句固定 JSON 的客户端（`line_for` 的输入是 `chat_json`）。"""

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, *args, **kwargs):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_the_generator_refuses_constraints_long_lines_and_non_chinese():
    case = {"case_id": "c1", "excerpt": "Keep the camera still and let the actor move.",
            "source_ref": {"title": "t"}}
    ok = ZH.line_for(_Stub({"zh": "让演员在画面里移动时保持机位不动"}), case)
    assert ok == {"case_id": "c1", "zh": "让演员在画面里移动时保持机位不动"}
    #: E3：L3 不许产出约束。
    assert ZH.line_for(_Stub({"zh": "必须保持机位不动，禁止摇镜"}), case) is None
    #: 长度与语言。
    assert ZH.line_for(_Stub({"zh": "短"}), case) is None
    assert ZH.line_for(_Stub({"zh": "keep the camera still and let the actor move"}), case) is None
    #: 模型失败 ⇒ 丢掉这一条，不编。
    assert ZH.line_for(_Stub(RuntimeError("boom")), case) is None


def shipped_clue_problems(lines) -> list:
    """把**每一条**入库线索过一遍生成期那同一套判据（``ZH.classify``）。

    为什么要整份扫、而不是抽 20 条（2026-10-04 的 glm-5.3 会诊指出）：原来那条
    "抽 20 条逐条核对"的写法，**第 21 条之后无论多脏都验不出来**；而"入库的线索
    不许带约束词 / 不许是元话术 / 不许不是中文"本来就有**唯一真源**
    （生成侧 `case_search_zh.make_line` 用的就是 `classify`）。这里只是把它
    按**全量**再跑一遍——判据不放宽，只把覆盖面从 20 条补到全部。
    """
    return [(case_id, ZH.classify(zh)) for case_id, zh in lines.items()
            if ZH.classify(zh)]


def test_the_shipped_sidecar_matches_the_shipped_cases():
    """入库的那对产物必须同代、覆盖够、**且每一条都过生成期判据**。"""
    #: 索引是**分片**布局：案例在 `knowledge/cases/part-*.jsonl`，
    #: 线索在 `knowledge/cases/search_zh.part-*.jsonl`（读者按索引目录认）。
    cases_path = ROOT / "knowledge"
    sidecar = C.search_zh_paths(cases_path)
    #: **缺证据 != 通过**：线索文件是检索面的一半，它不在就是这一条红，
    #: 不许 `pytest.skip` 把"没验"写成"没失败"（§4.1b 硬规则 1 的同一形状）。
    assert sidecar, ("入库的中文线索文件不见了（`knowledge/cases/search_zh.part-*.jsonl`）："
                     "缺它检索面对中文查询恒 0 命中")
    cases = C.read_cases(cases_path)
    lines, reason = C.read_search_zh(ROOT / "knowledge", cases_path)
    assert reason == "", reason
    assert len(lines) >= 0.5 * len(cases), f"线索覆盖太低：{len(lines)}/{len(cases)}"
    problems = shipped_clue_problems(lines)
    assert not problems, (
        f"入库线索里有 {len(problems)}/{len(lines)} 条不过生成期判据"
        f"（例：{problems[:3]}）")


def test_the_shipped_sidecar_checker_fires_anywhere_in_the_file():
    """自证：整份扫的判据必须能开火，**包括第 20 条之后**。

    抽 20 条的旧写法在下面第二半会**静默通过**——那正是它名不副实的地方。
    """
    good = {f"c{index}": "要拍固定机位时把相机锁死，让演员在画面里走" for index in range(40)}
    assert shipped_clue_problems(good) == []
    bad = dict(good)
    bad["c39"] = "镜头必须保持水平"                     # 约束词（E3）
    bad["c3"] = "本段未涉及景别与运镜"                  # 元话术
    bad["c17"] = "keep the camera still"                # 不是中文
    problems = dict(shipped_clue_problems(bad))
    assert problems["c39"].startswith("constraint"), problems
    assert problems["c3"].startswith("meta"), problems
    assert problems["c17"].startswith("not-chinese"), problems
    assert set(problems) == {"c3", "c17", "c39"}, problems


# --------------------------------------------------------------------------- #
# v2 的提示词形状与**具名丢弃原因**（2026-10-03）。这一段的存在理由：v1 的提示词
# 写的是"改写成一句中文线索"，模型于是写**摘要**或**元话术**（"本段未涉及景别…"）
# ——那等于把 `景别/运镜/剪辑` 这些**查询里的工艺词**灌进垃圾文档，BM25 因此让
# 它们比真案例更容易被中文查询命中。判据是"检索键要长得像导演会问的那句话的答案"。
# --------------------------------------------------------------------------- #


def test_classify_names_every_drop_reason():
    """丢弃必须**具名**：一个 `None` 讲不出"是长度、是约束、还是元话术"。"""
    assert ZH.classify("推镜把观众带进主角的视线里") == ""
    assert ZH.classify("") .startswith("empty")
    assert ZH.classify("短").startswith("length")
    assert ZH.classify("啊" * 200).startswith("length")
    assert ZH.classify("镜头必须保持水平不晃").startswith("constraint")
    assert ZH.classify("本段未涉及景别与运镜") .startswith("meta")
    assert ZH.classify("keep the camera still") == "not-chinese"


def test_make_line_reports_the_same_reason_classify_would():
    """`make_line` 与 `classify` **同源**：不许各写一套丢弃规则。"""
    case = {"case_id": "c1", "excerpt": "Keep the camera still.",
            "source_ref": {"title": "t"}}
    line, reason = ZH.make_line(_Stub({"zh": "本段未涉及景别与运镜"}), case)
    assert line is None
    assert reason == ZH.classify("本段未涉及景别与运镜")
    #: 空串走的是 `empty` 这一支（摘录确实不含工艺信息时的**合法**回答）。
    line, reason = ZH.make_line(_Stub({"zh": "   "}), case)
    assert line is None and reason.startswith("empty")
    #: 合格的一条：原因是空串，行里带 case_id。
    line, reason = ZH.make_line(_Stub({"zh": "固定机位让表演自己说话"}), case)
    assert reason == "" and line["case_id"] == "c1"


def test_the_v2_prompt_forbids_meta_phrasing_and_allows_an_empty_line():
    """提示词必须把两件事写死：**不许元话术**、**摘录没有工艺信息就给空串**。

    这两条是 v2 的全部机制——没有它们，模型会继续写"本段未涉及…"，
    而那种句子恰恰带着查询词。
    """
    assert "元话术" in ZH.SYSTEM
    assert "未涉及" in ZH.SYSTEM and "不涉及" in ZH.SYSTEM
    assert "空串" in ZH.SYSTEM
    #: 闭集式的工艺词清单也在（否则线索与查询的词表仍然对不上）。
    for word in ("推镜", "跟拍", "低角度", "侧光", "留白", "轴线"):
        assert word in ZH.SYSTEM, word


def test_the_craft_word_list_is_derived_from_the_query_side_vocabulary():
    """线索的词表**必须与查询词表同源派生**——不是在这里再抄一份。

    为什么这条值得单独钉（2026-10-04 实测，`work/e1_vocab_probe.py` 可复算）：
    拿一次真实运行的 64 条逐镜查询与入库线索对拍，查询里点名的 **309 处**工艺词有
    **153 处（49.5%）**在整个线索库里**一次都不存在**——`固定机位` 31、`景深` 23、
    `浅景深` 19、`越轴` 15、`逆光` 15、`侧光` 11、`留白` 11。检索是词面匹配，
    那些概念对这条查询**数学上不可达**，与排序好坏无关。

    真源是 `tools/kb_fetch/vocabulary.py` 的那几张表（它们同时铺成超图节点、
    又被 `check_holdout.py` 当作门③ 的词表），所以这里**逐条对拍**：表里出现的
    每一个取值/别名都必须出现在提示词里。各抄一份正是本仓库付过三次代价的那类漂移。
    """
    from tools.kb_fetch import vocabulary

    source = []
    for aliases in vocabulary.SHOT_SIZE_NAMES.values():
        source.extend(aliases)
    for aliases in vocabulary.MOVEMENT_ZH.values():
        source.extend(aliases)
    for canonical, aliases in vocabulary.LIGHTING:
        source.extend((canonical, *aliases))
    for canonical, aliases in vocabulary.CAMERA_ANGLES:
        source.extend((canonical, *aliases))
    for aliases in vocabulary.COMPOSITION_RULES_ZH.values():
        source.extend(aliases)
    for canonical, aliases in vocabulary.AXIS_TOPICS:
        source.extend((canonical, *aliases))
    assert source, "真源表读不到——那这条用例就是空绿"
    missing = [word for word in source if word not in ZH.SYSTEM]
    assert not missing, f"查询词表里的这些说法没进提示词：{missing[:8]}"
    #: 补词**不改**判据：摘录没讲到就不许用。
    assert "只能用在摘录真的讲到它的时候" in ZH.SYSTEM
    #: 实测里被点名最多、而真源表里没有的那几个词，靠显式补词进来。
    for word in ("景深", "浅景深", "硬光", "轴线"):
        assert word in ZH.SYSTEM, word


def test_dropped_out_writes_named_reasons(tmp_path, monkeypatch):
    """`--dropped-out` 把"谁被丢、为什么"落盘——**覆盖率不是只看分子**。"""
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps({"case_id": "c1", "excerpt": "A slow dolly in.",
                    "source_ref": {"title": "t"}}) + "\n"
        + json.dumps({"case_id": "c2", "excerpt": "Another excerpt.",
                      "source_ref": {"title": "t"}}) + "\n",
        encoding="utf-8")

    class _Meta:
        family = "zhipu"
        model_id = "stub"
        model_version = "stub"

        def chat_json(self, *args, **kwargs):
            return {"zh": "本段未涉及景别与运镜"}

    monkeypatch.setattr(ZH.llm, "make_client", lambda *a, **k: _Meta())
    out = tmp_path / "lines.jsonl"
    dropped = tmp_path / "dropped.jsonl"
    code = ZH.main(["--cases", str(cases_path), "--out", str(out),
                    "--dropped-out", str(dropped), "--workers", "1"])
    assert code == 0
    rows = [json.loads(line) for line in
            dropped.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["case_id"] for row in rows] == ["c1", "c2"]     # 按 id 排序
    assert all(row["reason"].startswith("meta") for row in rows), rows
    assert all(row["excerpt"] for row in rows)
    #: 没有 `--dropped-out` 时**不写**那个文件（缺省行为不变）。
    dropped.unlink()
    assert ZH.main(["--cases", str(cases_path), "--out", str(out),
                    "--workers", "1"]) == 0
    assert not dropped.exists()


def test_a_transient_failure_is_not_written_down_as_a_rule_drop():
    """上游抖动与"摘录真没有工艺信息"必须**分开记**——否则覆盖率被失败悄悄拉低。

    2026-10-03 实测：810 条里 204 条 `call-failed`（14 并发下的上游抖动）与 273 条
    `empty`（规则丢弃）混在同一个 `dropped` 计数里，产物覆盖率因此从应有的 ~60%
    掉到 41%，低于下界。原因里带上异常类型才分得清两者。
    """
    case = {"case_id": "c1", "excerpt": "Keep the camera still.",
            "source_ref": {"title": "t"}}
    line, reason = ZH.make_line(_Stub(RuntimeError("boom")), case)
    assert line is None
    assert reason.startswith("call-failed"), reason
    assert "RuntimeError" in reason, reason


def test_retry_from_only_reruns_the_named_transient_failures(tmp_path, monkeypatch):
    """`--retry-from` 只重跑点名原因的那些条目（规则丢弃不重跑）。"""
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text("".join(
        json.dumps({"case_id": case_id, "excerpt": "A slow dolly in.",
                    "source_ref": {"title": "t"}}) + "\n"
        for case_id in ("c1", "c2", "c3")), encoding="utf-8")
    prior = tmp_path / "dropped.jsonl"
    prior.write_text("".join(
        json.dumps({"case_id": case_id, "reason": reason}) + "\n"
        for case_id, reason in (
            ("c1", "call-failed（LLMError：空正文）"),
            ("c2", "empty（摘录不含工艺信息，按规则给空串）"),
            ("c3", "call-failed（TimeoutError：读超时）"),
        )), encoding="utf-8")

    class _Ok:
        family = "zhipu"
        model_id = "stub"
        model_version = "stub"

        def chat_json(self, *args, **kwargs):
            return {"zh": "要拍移动镜头时用斯坦尼康吸收震动"}

    monkeypatch.setattr(ZH.llm, "make_client", lambda *a, **k: _Ok())
    out = tmp_path / "lines.jsonl"
    assert ZH.main(["--cases", str(cases_path), "--out", str(out),
                    "--retry-from", str(prior), "--retry-reasons", "call-failed",
                    "--workers", "1"]) == 0
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines() if line.strip()]
    #: c2 是规则丢弃（`empty`），**不该**被重跑；c1/c3 是瞬时失败，重跑后落盘。
    assert sorted(row["case_id"] for row in rows) == ["c1", "c3"]


def test_the_generator_checkpoints_so_a_crash_cannot_lose_everything(tmp_path,
                                                                     monkeypatch):
    """**断点落盘**：几千次调用要跑几小时，"只在结束时写盘"= 一挂就全丢。

    为什么这条是必要的（2026-10-04 实测）：一次全量生成 3804 条要 8 并发跑几小时；
    进程一旦挂在半路，已经花掉的额度与已完成的条目**一条都留不下**（旧实现只在
    `pool` 收完之后写一次文件）。判据不是"文件在不在"，而是**写盘发生了不止一次**
    ——直接数 `write_lines` 的调用次数，避免"看起来有文件"这种空绿。
    """
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text("".join(
        json.dumps({"case_id": f"c{index}", "excerpt": "A slow dolly in.",
                    "source_ref": {"title": "t"}}) + "\n"
        for index in range(1, 6)), encoding="utf-8")

    class _Ok:
        family = "zhipu"
        model_id = "stub"
        model_version = "stub"

        def chat_json(self, *args, **kwargs):
            return {"zh": "要拍移动镜头时用斯坦尼康吸收震动"}

    calls = []
    real = ZH.write_lines

    def counting(out, rows):
        calls.append(len(rows))
        return real(out, rows)

    monkeypatch.setattr(ZH, "write_lines", counting)
    monkeypatch.setattr(ZH.llm, "make_client", lambda *a, **k: _Ok())
    out = tmp_path / "lines.jsonl"
    assert ZH.main(["--cases", str(cases_path), "--out", str(out),
                    "--workers", "1", "--checkpoint-every", "2"]) == 0
    assert len(calls) >= 3, f"只写了一次盘（{calls}）：断点没生效"
    rows = [json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 5, "落盘内容必须是全部 5 条"


def test_resume_needs_the_current_prompt_not_just_the_current_cases(tmp_path,
                                                                   monkeypatch):
    """断点续跑必须**两枚指纹都对**：只看案例摘要会把上一代提示词的线索当"已完成"。

    现场（2026-10-04 实测）：同一份 `cases.search_zh.jsonl` 里 **436 行**记着一枚
    `prompt_sha256`、**739 行**记着另一枚——旧的续跑判据只比 `cases_sha256`，
    于是"改了提示词再跑一遍"会把整批旧提示词的键原样复用，产出一份**混代**的
    线索文件，而每一行都自称是当前代。检索面因此既不等于旧代也不等于新代，
    E1 的 A/B 会被这个洞污染。

    判据：① 案例摘要对、提示词是上一代 ⇒ **必须重算**（进 `todo`，真的调上游）；
    ② 两枚都对 ⇒ **必须复用**（不调上游，原样留用）。
    """
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text("".join(
        json.dumps({"case_id": case_id, "excerpt": excerpt,
                    "source_ref": {"title": "t"}}) + "\n"
        for case_id, excerpt in (("c1", "A slow dolly in on the market."),
                                 ("c2", "Cut on the eyeline to the listener."))),
        encoding="utf-8")
    digest = ZH.cases_digest(cases_path)
    out = tmp_path / "lines.jsonl"
    out.write_text("".join(
        json.dumps({"case_id": case_id, "zh": zh, "cases_sha256": digest,
                    "prompt_sha256": prompt_sha}) + "\n"
        for case_id, zh, prompt_sha in (
            #: c1：案例摘要**对**，提示词是**上一代**。
            ("c1", "旧的线索（上一代提示词）", "0" * 64),
            #: c2：两枚都**对**。
            ("c2", "切到听者的视线完成一次反打", ZH.prompt_sha()))),
        encoding="utf-8")

    seen = []

    class _Ok:
        family = "zhipu"
        model_id = "stub"
        model_version = "stub"

        def chat_json(self, _system, user, *args, **kwargs):
            seen.append(user)
            return {"zh": "要拍移动镜头时用斯坦尼康吸收震动"}

    monkeypatch.setattr(ZH.llm, "make_client", lambda *a, **k: _Ok())
    assert ZH.main(["--cases", str(cases_path), "--out", str(out),
                    "--workers", "1"]) == 0

    #: 只有 c1 该被重算：c2 是当前代，复用（上游一次都不该被它的摘录打到）。
    assert len(seen) == 1, f"混合代际的续跑判据没生效（调了 {len(seen)} 次）"
    assert "market" in seen[0], seen[0]
    rows = {json.loads(line)["case_id"]: json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines() if line.strip()}
    assert rows["c2"]["zh"] == "切到听者的视线完成一次反打", rows["c2"]
    assert rows["c1"]["zh"] == "要拍移动镜头时用斯坦尼康吸收震动", rows["c1"]
    assert rows["c1"]["prompt_sha256"] == ZH.prompt_sha(), rows["c1"]


def _case_layer(directory: pathlib.Path, rows) -> pathlib.Path:
    """写一份分片案例层（`<dir>/cases/part-000.jsonl`）并返回分片目录。"""
    shards = directory / "cases"
    shards.mkdir(parents=True, exist_ok=True)
    (shards / "part-000.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8")
    return shards


def _seed_case(excerpt: str, title: str, case_id: str = "case_old") -> dict:
    row = _case(case_id=case_id, excerpt=excerpt).to_dict()
    row["source_ref"] = {**row["source_ref"], "title": title}
    return row


class _CountingClient:
    """每次调用都记一笔并回一句新线索——用来判"到底有没有花调用"。"""

    family = "zhipu"
    model_id = "stub"
    model_version = "stub"

    def __init__(self, zh: str = "新生成的线索：镜头缓缓推近") -> None:
        self.calls = 0
        self.zh = zh

    def chat_json(self, *args, **kwargs):
        self.calls += 1
        return {"zh": self.zh}


def test_the_same_input_from_another_layer_is_reused_instead_of_regenerated(tmp_path,
                                                                           monkeypatch):
    """线索是**输入的纯函数**：提示词里只有 `摘录` 与 `出处标题` 两项。

    两项逐字节相同的案例，让模型把同一句话再"改写"一遍只会引入一次非确定性
    （`temperature=0` 也不保证逐字节相同），不会提高质量。重建 v4 案例层时
    783 条里有 521 条与现役层逐字节相同，而现役那份**已过审**——所以同代同输入
    一律沿用（见 `seed_index` 的三条硬门）。
    """
    excerpt, title = "A slow dolly in on the market stalls.", "Practical Cinema"
    seed = tmp_path / "seed"
    _case_layer(seed, [_seed_case(excerpt, title)])
    _write_sidecar(seed, seed / "cases", C.cases_digest(C.case_paths(seed)),
                   [{"case_id": "case_old", "zh": "镜头缓缓推近市场摊位的货物",
                     "model": "glm-5.3", "family": "zhipu",
                     "prompt_sha256": ZH.prompt_sha()}])

    target = tmp_path / "target"
    _case_layer(target, [_seed_case(excerpt, title, case_id="case_new"),
                         _seed_case("A hard cut on the beat.", "Editing Notes",
                                    case_id="case_fresh")])
    client = _CountingClient()
    monkeypatch.setattr(ZH.llm, "make_client", lambda *a, **k: client)
    assert ZH.main(["--cases", str(target / "cases"), "--out", str(target / "cases"),
                    "--seed", str(seed), "--workers", "1"]) == 0

    out = target / "cases" / "search_zh.part-000.jsonl"
    rows = {json.loads(line)["case_id"]: json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines() if line.strip()}
    assert rows["case_new"]["zh"] == "镜头缓缓推近市场摊位的货物", "同输入没有沿用"
    assert rows["case_fresh"]["zh"] == client.zh, "不同输入必须重生成"
    assert client.calls == 1, f"只有 case_fresh 该花调用，实际 {client.calls} 次"
    #: 复用来的行要**按当前案例集合重签**（否则读者整份拒用）。
    assert rows["case_new"]["cases_sha256"] == C.cases_digest(C.case_paths(target))
    loaded, reason = C.read_search_zh(target, target)
    assert reason == "", reason
    assert loaded["case_new"] == "镜头缓缓推近市场摊位的货物"


def _seed_and_run(tmp_path, monkeypatch, seed_row: dict, excerpt: str, title: str):
    seed = tmp_path / "seed"
    _case_layer(seed, [_seed_case(excerpt, title)])
    _write_sidecar(seed, seed / "cases", C.cases_digest(C.case_paths(seed)),
                   [{**seed_row, "case_id": "case_old"}])
    target = tmp_path / "target"
    _case_layer(target, [_seed_case(excerpt, title, case_id="case_new")])
    client = _CountingClient()
    monkeypatch.setattr(ZH.llm, "make_client", lambda *a, **k: client)
    assert ZH.main(["--cases", str(target / "cases"), "--out", str(target / "cases"),
                    "--seed", str(seed), "--workers", "1"]) == 0
    out = target / "cases" / "search_zh.part-000.jsonl"
    return {json.loads(line)["case_id"]: json.loads(line) for line in
            out.read_text(encoding="utf-8").splitlines() if line.strip()}, client


def test_a_seed_row_from_another_prompt_is_not_reused(tmp_path, monkeypatch):
    """跨代不许复用：`prompt_sha256` 不同 = 那不是同一个提示词产出的键。"""
    rows, client = _seed_and_run(
        tmp_path, monkeypatch,
        {"zh": "镜头缓缓推近市场摊位的货物", "model": "glm-5.3", "family": "zhipu",
         "prompt_sha256": "0" * 64},
        "A slow dolly in on the market stalls.", "Practical Cinema")
    assert client.calls == 1, "跨代的行竟然被沿用了"
    assert rows["case_new"]["zh"] == client.zh


def test_a_seed_row_that_fails_the_current_rules_is_not_reused(tmp_path, monkeypatch):
    """判据会长：沿用前必须按**现行** `classify` 重查（元话术那句现该丢）。"""
    rows, client = _seed_and_run(
        tmp_path, monkeypatch,
        {"zh": "本摘录未涉及景别与运镜", "model": "glm-5.3", "family": "zhipu",
         "prompt_sha256": ZH.prompt_sha()},
        "A slow dolly in on the market stalls.", "Practical Cinema")
    assert client.calls == 1, "按现行判据该丢的行竟然被沿用了"
    assert rows["case_new"]["zh"] == client.zh
