"""L3 零依赖适配器（ADR-0014 的 ② 魔改第一块）：精确 → BM25 →（可选）重排。

判据只钉四件事，全部离线、确定性：
1. **精确层优先**：查询点名的 `键=值` 在文本里逐字命中的案例排最前；
2. **确定性**：同一输入永远同一顺序，同分按 `case_id`（不许靠字典序碰运气）；
3. **只做重排，不造案例**：返回的都是入参里的 `case_id`，且不超过 `top_k`；
4. **增强不许弄挂主路**：注入的重排器抛错或返回空 ⇒ 退回词法序并**具名记账**。

另有一条**依赖审计**：这个模块只许 import 标准库与仓库自己的模块——
它是"零依赖适配器"这句话的机器判据（会诊两侧都要求不许因引入而拉依赖）。
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.knowledge import Case  # noqa: E402
from block_director.knowledge import lexical_adapter as LA  # noqa: E402


def _case(case_id: str, excerpt: str) -> Case:
    return Case(case_id=case_id, case_type="narrative", title=case_id,
                excerpt=excerpt, source_ref={})


def test_the_exact_contract_pair_outranks_a_better_lexical_match():
    """查询点名了 `运镜=固定` ⇒ **提到"固定"**的案例排最前（取值是两边的共同词汇）。"""
    exact = _case("case_exact", "固定机位：把相机锁死，让人在画面里走。")
    noise = _case("case_noise", "码头 市场 午后 木架 摊位 帆布 顶棚 青石 地面 船 吊臂")
    query = "景别=MS；运镜=固定；意图=收束"
    out = LA.LexicalAdapter().retrieve(query, top_k=2, cases=[noise, exact])
    assert [case.case_id for case in out] == ["case_exact", "case_noise"]
    #: 取值读取器：`禁<键>=值` 的**取值**同样进召回面（禁的语义留给超图层）。
    assert LA.query_values("景别=MS；禁运镜=固定") == ["MS", "固定"]


def test_the_order_is_deterministic_and_never_invents_cases():
    """同分按 `case_id`；返回的都是入参里的 id，且 ≤ `top_k`。"""
    cases = [_case(f"case_{index:02d}", "码头 市场 午后 木架 摊位") for index in (1, 2, 3)]
    first = LA.LexicalAdapter().retrieve("码头 市场", top_k=2, cases=cases)
    again = LA.LexicalAdapter().retrieve("码头 市场", top_k=2, cases=cases)
    assert [case.case_id for case in first] == [case.case_id for case in again]
    assert len(first) == 2
    assert {case.case_id for case in first} <= {case.case_id for case in cases}
    #: 空池 / 空查询都不许抛，也不许造东西。
    assert LA.LexicalAdapter().retrieve("码头", top_k=3, cases=[]) == []


def test_an_injected_reranker_reorders_within_the_pool_only():
    """重排器只许在池内重排——返回池外的 id 会被丢掉（与 `_filtered` 同一纪律）。"""
    cases = [_case("case_a", "甲"), _case("case_b", "乙"), _case("case_c", "丙")]
    seen = {}

    def rerank(query, pool):
        seen["ids"] = [case.case_id for case in pool]
        return ["case_c", "case_a", "case_ghost"]

    out = LA.LexicalAdapter(rerank=rerank).retrieve("甲", top_k=3, cases=cases)
    assert [case.case_id for case in out] == ["case_c", "case_a", "case_b"]
    assert "case_ghost" not in seen["ids"]


def test_a_broken_or_empty_reranker_falls_back_and_says_why():
    """重排器抛错 ⇒ 词法序 ＋ `rerank_failed:…`；返回空 ⇒ 词法序 ＋ `rerank_empty`。"""
    cases = [_case("case_a", "码头 市场"), _case("case_b", "码头 船")]
    baseline = [case.case_id for case in
                LA.LexicalAdapter().retrieve("码头 市场", top_k=2, cases=cases)]

    def boom(query, pool):
        raise RuntimeError("upstream down")

    adapter = LA.LexicalAdapter(rerank=boom)
    out = adapter.retrieve("码头 市场", top_k=2, cases=cases)
    assert [case.case_id for case in out] == baseline
    assert adapter.last_reason == "rerank_failed:RuntimeError"

    empty = LA.LexicalAdapter(rerank=lambda query, pool: [])
    out = empty.retrieve("码头 市场", top_k=2, cases=cases)
    assert [case.case_id for case in out] == baseline
    assert empty.last_reason == "rerank_empty"


def test_the_adapter_pulls_no_new_dependency():
    """**零依赖**是这句承诺的机器判据：只许标准库 ＋ 本仓库自己的模块。"""
    tree = ast.parse((ROOT / "block_director" / "knowledge" / "lexical_adapter.py")
                     .read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:                     # 相对 import = 本包内
                continue
            imported.add((node.module or "").split(".")[0])
    third_party = {name for name in imported if name not in sys.stdlib_module_names}
    assert third_party <= {"block_director"}, (
        f"零依赖适配器引入了第三方模块：{sorted(third_party)}")


def test_the_query_pair_reader_keeps_the_value_verbatim():
    """`键=值` 读取器**不改写取值**（不猜同义、不做别名映射——那是超图层的活）。"""
    assert LA.query_pairs("景别=MS；运镜=固定") == ["景别=MS", "运镜=固定"]
    assert LA.query_pairs("禁运镜=固定；意图=收束") == ["禁运镜=固定", "意图=收束"]
    assert LA.query_pairs("米迦尔自信面朝画面左侧") == []
