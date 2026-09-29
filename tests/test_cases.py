"""L3 案例层（执行文档 v1.4 §2.3b / §2.3d T1 / §3.1）。

这一层要钉住四件事：

1. **三态语义**：``off`` 静默空（不算降级）／``hybrid`` 永远可用／``lightrag``
   没有适配器时**降级并留痕**（具名原因）；
2. **永不产出约束**（E3 的机制侧）：``Case`` 契约里没有 ``forbid`` 字段，
   渲染出来的文本里也不能出现"必须/禁止"这类措辞；
3. **原子注入**：一条案例装不下就整条丢弃，绝不截断（截断会切掉出处）；
4. **指纹留痕**：§2.3b 要求 trace 记 ``lightrag_index_fingerprint``。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from block_director.contracts.knowledge import Case
from block_director.knowledge import cases as case_mod
from block_director.knowledge.cases import (
    CASE_BACKENDS,
    CASE_COLUMN_TITLE,
    CASE_TYPES,
    DEGRADED_NO_ADAPTER,
    CaseIndex,
    carries_constraint,
    load_index,
    render_case,
    render_cases,
)


def _case(case_id: str, title: str, excerpt: str, *, beats=(),
          case_type: str = "narrative") -> Case:
    return Case(case_id=case_id, case_type=case_type, title=title,
                excerpt=excerpt, beat_sequence=list(beats),
                source_ref={"url": f"https://example.org/{case_id}",
                            "title": "参考书", "author": "作者",
                            "license": "PublicDomain"})


def _three_cases():
    # BM25Okapi 在 <3 篇语料上 IDF 全为负，任何查询都拿不到分——这不是缺陷，
    # 是它在单文档语料上的已知退化（sidecar 的用例同样按 3 篇起）。
    return [
        _case("case_1", "荒诞时刻的甩镜", "情绪荒诞时先甩镜，再落回固定机位。",
              beats=["establish", "coverage", "reaction"],
              case_type="sequence_pattern"),
        _case("case_2", "静止长镜的留白", "长镜静止时靠表演推进，不靠剪辑。"),
        _case("case_3", "越轴与银幕方向", "越轴会翻转银幕方向，要用中性镜头过渡。"),
    ]


@pytest.fixture(autouse=True)
def _clean_adapters():
    """每个用例都从"没有注册过适配器"开始（注册表是进程级的）。"""
    case_mod.reset_lightrag_adapters()
    yield
    case_mod.reset_lightrag_adapters()


# --------------------------------------------------------------------------- 三态

def test_the_backend_vocabulary_is_the_frozen_one():
    assert CASE_BACKENDS == ("lightrag", "hybrid", "off")
    assert CASE_TYPES == ("narrative", "sequence_pattern", "lesson")


def test_off_is_silent_and_never_counted_as_degraded():
    index = CaseIndex(_three_cases(), "off")
    assert index.enabled is False
    assert index.degraded is False
    assert index.reason == ""
    assert index.lanes == 1
    assert index.retrieve("荒诞") == []


def test_lightrag_without_an_adapter_degrades_to_hybrid_with_a_named_reason():
    index = CaseIndex(_three_cases(), "lightrag")
    assert index.requested == "lightrag"
    assert index.effective == "hybrid"          # §2.3b 的降级路径
    assert index.degraded is True
    assert index.reason == DEGRADED_NO_ADAPTER
    assert index.lanes == 2                     # 降级后仍然是两通道
    hits = index.retrieve("荒诞 甩镜", top_k=1)
    assert [hit.case_id for hit in hits] == ["case_1"]


def test_hybrid_does_not_claim_to_be_degraded():
    index = CaseIndex(_three_cases(), "hybrid")
    assert index.effective == "hybrid"
    assert index.degraded is False
    assert index.reason == ""


def test_a_registered_adapter_makes_lightrag_effective(tmp_path):
    class _Adapter:
        def __init__(self):
            self.calls = 0

        def retrieve(self, query, *, top_k, cases):
            self.calls += 1
            return [cases[2]]

    adapter = _Adapter()
    case_mod.register_lightrag_adapter(lambda _index_dir: adapter)
    _write_corpus(tmp_path, [case.to_dict() for case in _three_cases()],
                  lightrag=True)
    # 适配器由 `load_index` 探测（它才知道 index_dir）；直接构造 `CaseIndex`
    # 而不给适配器＝这条通道不可用，必须降级（见上一个用例）。
    index = load_index(tmp_path, "lightrag")
    assert index.effective == "lightrag"
    assert index.degraded is False
    assert [hit.case_id for hit in index.retrieve("越轴")] == ["case_3"]
    assert adapter.calls == 1


def test_a_failing_adapter_degrades_with_the_exception_type():
    def _boom(_index_dir):
        raise RuntimeError("索引没建好")

    case_mod.register_lightrag_adapter(_boom)
    index = CaseIndex(_three_cases(), "lightrag")
    # 工厂抛错＝这个适配器不可用 → 回到 §2.3b 的降级路径。
    assert index.effective == "hybrid"
    assert index.reason == DEGRADED_NO_ADAPTER

    class _Broken:
        def retrieve(self, query, *, top_k, cases):
            raise RuntimeError("查询失败")

    index = CaseIndex(_three_cases(), "lightrag", adapter=_Broken())
    hits = index.retrieve("荒诞 甩镜")
    assert index.effective == "hybrid"
    assert index.reason == "lightrag_query_failed:RuntimeError"
    # 退回 BM25，不是空转：命中集非空，且最相关的那条排第一。
    assert hits and hits[0].case_id == "case_1"


# --------------------------------------------------------------------------- 装配

def _write_corpus(directory: Path, rows, *, manifest=True, lightrag=False) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cases.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    if manifest:
        (directory / "cases.manifest.json").write_text(
            json.dumps({"fingerprint": "case-fp"}), encoding="utf-8")
    if lightrag:
        (directory / "lightrag.fingerprint.json").write_text(
            json.dumps({"fingerprint": "lr-fp"}), encoding="utf-8")


def test_load_index_reads_the_fingerprints(tmp_path):
    rows = [case.to_dict() for case in _three_cases()]
    _write_corpus(tmp_path, rows, lightrag=True)
    case_mod.register_lightrag_adapter(lambda _dir: type(
        "A", (), {"retrieve": lambda self, q, *, top_k, cases: cases[:1]})())
    index = load_index(tmp_path, "lightrag")
    assert index.fingerprint == "case-fp"
    assert index.lightrag_index_fingerprint == "lr-fp"
    assert index.effective == "lightrag"
    assert index.describe()["lightrag_index_fingerprint"] == "lr-fp"


def test_a_missing_index_degrades_with_a_reason(tmp_path):
    index = load_index(tmp_path, "lightrag")
    assert index.reason == "cases_index_missing"
    assert index.degraded is True and index.effective == "off"
    assert index.lanes == 1


def test_a_broken_index_is_reported_not_swallowed(tmp_path):
    (tmp_path / "cases.jsonl").write_text("{not json}\n", encoding="utf-8")
    index = load_index(tmp_path, "hybrid")
    assert index.reason.startswith("cases_index_unreadable")
    assert index.degraded is True


def test_an_empty_index_is_reported_not_swallowed(tmp_path):
    (tmp_path / "cases.jsonl").write_text("\n", encoding="utf-8")
    index = load_index(tmp_path, "hybrid")
    assert index.reason == "cases_index_empty"


def test_off_never_touches_the_disk(tmp_path):
    index = load_index(tmp_path / "does-not-exist", "off")
    assert index.reason == "" and index.degraded is False


# --------------------------------------------------------------------------- 渲染

def test_rendered_text_carries_the_attribution_and_the_beat_sequence():
    text = render_case(_three_cases()[0])
    assert text.startswith("[case_1] 荒诞时刻的甩镜")
    assert "序列：establish→coverage→reaction" in text
    assert "出处：参考书／作者／PublicDomain" in text


def test_the_case_column_never_speaks_in_constraints():
    """"参考案例（仅参考）"栏**只能**是建议口径——出现约束措辞即 E3 破功。"""
    text, dropped = render_cases(_three_cases(), token_limit=4000)
    assert text.startswith(f"【{CASE_COLUMN_TITLE}】")
    assert dropped == []
    for token in ("禁止", "必须", "不得", "forbid"):
        assert token not in text


def test_render_is_atomic_and_reports_what_it_dropped():
    text, dropped = render_cases(_three_cases(), token_limit=1)
    assert text == ""
    assert dropped == ["case_1", "case_2", "case_3"]
    text, dropped = render_cases(_three_cases(), token_limit=1000)
    assert dropped == []
    assert text.count("[case_") == 3


def test_the_case_dto_still_has_no_constraint_field():
    """E3 的机制保证：不是"约定不写"，而是**类型里就没有这个字段**。"""
    assert "forbid" not in Case.__dataclass_fields__
    assert "constraint" not in Case.__dataclass_fields__
    assert carries_constraint({"forbid": ["movement=固定"]}) is True
    assert carries_constraint({"case_id": "x", "excerpt": "y"}) is False
