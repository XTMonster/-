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


def test_the_shipped_sidecar_matches_the_shipped_cases():
    """入库的那对产物必须同代（否则检索会静默走偏）。"""
    cases_path = ROOT / "knowledge" / "cases.jsonl"
    sidecar = ROOT / "knowledge" / C.SEARCH_ZH_FILE
    if not sidecar.is_file():
        import pytest

        pytest.skip("线索文件未入库")
    lines, reason = C.read_search_zh(ROOT / "knowledge", cases_path)
    assert reason == "", reason
    assert len(lines) >= 0.5 * len(C.read_cases(cases_path)), (
        f"线索覆盖太低：{len(lines)}/{len(C.read_cases(cases_path))}")
    #: 抽 20 条逐条核对"确实是中文 / 没有约束词"。
    for case_id, zh in list(lines.items())[:20]:
        assert any("\u4e00" <= ch <= "\u9fff" for ch in zh)
        assert not any(word in zh for word in ZH.CONSTRAINT_WORDS), (case_id, zh)
