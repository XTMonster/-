"""§4.1b 的 Q6b **读数通道**必须有执行者，而且读数必须是真的。

背景（2026-10-03 的独立审计）：§4.1b 写着"必须读实际发给模型的 prompt……
并断言注入 token 整场 ≤ `rag.plan_prefetch_tokens`（默认 2000）、每镜 ≤
`rag.max_tokens_per_call`（默认 800）（**是两个键，不是一个**）"，而链上跑的
Q6b 是对**夹具的 `q`** 重渲染——量的是"按这条查询检索会注入什么"，不是"这一跑
真的注入了什么"。`tools/knowledge/injection_audit.py` 补的就是这一条。

这组用例钉住三件事：

* 定位**精确**：量到的块逐字等于渲染进去的那一段（不多吃阶段 S 的剧本理解块、
  也不少吃被截断的尾巴）——这是"读数"与"读数器自述"的分界线；
* 上限是**两个键**：改一个只动它自己那一档；
* required 边的半边**join 不到就记 not_measured**，绝不读成 0 条丢弃。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge.tokens import TRUNCATION_NOTE, estimate_tokens
from block_director.layer5_orchestrator.editor import EDITOR_SYSTEM_PROMPT
from block_director.layer5_orchestrator.planner import PLAN_SYSTEM_PROMPT
from block_director.layer5_orchestrator.understand import BRIEF_BLOCK_HEADER
from tools.knowledge.injection_audit import (
    audit_trace,
    locate_knowledge,
    scope_markers,
    shot_id_of,
)

#: 一段**结构上逼真**的知识块：三栏、案例栏内部有空行、末尾带截断说明。
KNOWLEDGE = (
    "【硬约束（禁/许）】\n"
    "[INTENT_PACK] intent=intent:铺垫 shot_size=shot_size:MS movement=固定\n"
    "\n"
    "【经验建议（软）】\n"
    "[STAGING_PACK] 景别=MS 构图=occlusion\n"
    "\n"
    "【参考案例（仅参考）】\n"
    "[case_a] 通用：甲\n作者原文甲\n出处：某书／某人／PublicDomain\n"
    "\n"
    "[case_b] 通用：乙\n作者原文乙\n出处：某书／某人／PublicDomain"
    + TRUNCATION_NOTE
)

BRIEF = (BRIEF_BLOCK_HEADER + "\n- 情绪走向：铺垫→引爆\n"
         "\n【这一行故意以方括号开头，用来试审计会不会吃掉它】\n"
         "- 注视：米迦尔 → 伊恩（scope=all）")

SCRIPT = "【第十四街区码头市场 - 午后】\n· 对白\n米迦尔：我先上船。"


#: 与 :func:`_toy_graph` 的两个成员同名的注入块（成员名必须**真的出现在
#: prompt 里**才算没被丢掉——`_member_present` 读的就是 prompt 的文本）。
EDGE_KNOWLEDGE = (
    "【硬约束（禁/许）】\n"
    "[EMOTION_PACK] emotion=荒诞 movement=固定机位"
    + TRUNCATION_NOTE
)


def _plan_text(knowledge: str = KNOWLEDGE, brief: str = BRIEF) -> str:
    return (PLAN_SYSTEM_PROMPT.replace("{script}", SCRIPT)
            .replace("{knowledge}", knowledge).replace("{brief}", brief))


def _editor_text(knowledge: str = KNOWLEDGE) -> str:
    return (EDITOR_SYSTEM_PROMPT.replace("{scene_text}", SCRIPT)
            .replace("{knowledge}", knowledge)
            .replace("{shot_plan}", '{"shot_id": "shot_007"}'))


def _row(purpose: str, text: str, request_id: str = "rq1") -> dict:
    return {"purpose": purpose, "request_id": request_id,
            "prompt": [{"role": "system", "content": text}]}


def test_the_located_block_is_byte_for_byte_what_was_injected():
    """两个 scope 都必须**逐字**量到注入的那一段（多一个换行都不行）。"""
    markers = scope_markers()
    plan = locate_knowledge(_plan_text(), markers["plan"])
    assert plan is not None and plan["locator"] == "terminator"
    assert plan["block"] == KNOWLEDGE
    assert plan["tokens"] == estimate_tokens(KNOWLEDGE)

    shot = locate_knowledge(_editor_text(), markers["shot"])
    assert shot is not None and shot["locator"] == "terminator"
    assert shot["block"] == KNOWLEDGE


def test_the_block_does_not_swallow_the_brief_or_the_script():
    """阶段 S 的剧本理解块紧跟知识块，而且**它自己可以带方括号段落**。

    这是"段落前缀启发式"会踩的坑（`BRIEF` 里就故意放了一行以 `【` 开头的
    文本）。定位用的是模板字面量终止符，所以不吃它：知识块必须**只**是
    `KNOWLEDGE`，而剧本正文一个字都不许进来。
    """
    markers = scope_markers()
    located = locate_knowledge(_plan_text(), markers["plan"])
    assert located["block"] == KNOWLEDGE
    assert "这一行故意以方括号开头" not in located["block"]
    assert "我先上船" not in located["block"]


def test_a_truncated_block_keeps_its_truncation_note():
    """截断说明必须算进读数里——它也是真的发给了模型的一段文字。

    走"段落前缀"兜底时最容易漏掉它（它以 `…` 起，不是 `【`/`[`），所以这条
    同时钉住兜底规则的第三个前缀。
    """
    markers = scope_markers()
    located = locate_knowledge(_editor_text(), markers["shot"])
    assert located["block"].endswith(TRUNCATION_NOTE)
    assert located["tokens"] == estimate_tokens(KNOWLEDGE)


def test_shot_id_is_read_from_the_prompt():
    """逐次 `llm_trace` 记录里没有 `shot_id`；镜身份只能从 prompt 里读。"""
    assert shot_id_of(_editor_text()) == "shot_007"
    assert shot_id_of("没有镜头计划的正文") == ""


def test_the_two_caps_are_two_keys_not_one():
    """§4.1b 点名"**是两个键，不是一个**"：改一档只动它自己那一档。"""
    rows = [_row("plan", _plan_text(), "plan1"),
            _row("editor", _editor_text(), "shot1")]
    tight_shot = audit_trace(rows, plan_cap=2000,
                             shot_cap=estimate_tokens(KNOWLEDGE) - 1)
    assert tight_shot["plan_scope"]["status"] == "pass"
    assert tight_shot["shot_scope"]["status"] == "fail"
    assert tight_shot["shot_scope"]["over"][0]["request_id"] == "shot1"
    assert tight_shot["token_caps"]["status"] == "fail"
    assert tight_shot["plan_scope"]["cap_key"] == "rag.plan_prefetch_tokens"
    assert tight_shot["shot_scope"]["cap_key"] == "rag.max_tokens_per_call"

    tight_plan = audit_trace(rows, plan_cap=estimate_tokens(KNOWLEDGE) - 1,
                             shot_cap=800)
    assert tight_plan["plan_scope"]["status"] == "fail"
    assert tight_plan["shot_scope"]["status"] == "pass"

    exact = audit_trace(rows, plan_cap=estimate_tokens(KNOWLEDGE),
                        shot_cap=estimate_tokens(KNOWLEDGE))
    assert exact["token_caps"]["status"] == "pass"      # 等于上限不算超


def test_calls_without_a_knowledge_block_are_not_counted_as_measured():
    """没有知识块的调用（review/react/repair/understand）不进任何一档。"""
    report = audit_trace([_row("review", "没有任何注入块的提示词")])
    assert report["plan_scope"]["status"] == "not_measured"
    assert report["shot_scope"]["status"] == "not_measured"
    assert report["token_caps"]["status"] == "not_measured"
    assert report["calls_without_knowledge"] == 1


def _toy_graph():
    from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node

    nodes = [
        Node("emotion:荒诞", "emotion", "荒诞", ("absurd",)),
        Node("movement:static", "movement", "固定机位", ("固定", "static")),
    ]
    edge = HyperEdge.from_dict({
        "type": "EMOTION_PACK",
        "members": [["allow", "emotion", "emotion:荒诞"],
                    ["allow", "movement", "movement:static"]],
        "source_kind": "theory", "hardness": "hard",
    })
    return Hypergraph(nodes, [edge]), edge


def _mirror(query: str, shot_id: str = "shot_007") -> dict:
    return {"status": "ok", "queries": {shot_id: [query]}}


Q = "情绪=荒诞；运镜=固定"


def test_required_edges_present_in_the_prompt_are_not_reported_as_dropped():
    """正对照：required 边两个成员都在 prompt 里 → 丢弃 0 条、判通过。"""
    graph, edge = _toy_graph()
    entry = {"id": "h1", "q": Q,
             "must": [[edge.type, [[m.role, m.kind, m.node_id]
                                   for m in edge.members]]]}
    report = audit_trace([_row("editor", _editor_text(EDGE_KNOWLEDGE))],
                         graph=graph, entries=[entry], mirror=_mirror(Q))
    drops = report["required_edges_dropped_by_budget"]
    assert drops["status"] == "pass"
    assert (drops["matched_shots"], drops["required_edges"], drops["dropped"]) == (1, 1, 0)
    assert report["complete"] is True


def test_a_required_edge_missing_from_the_prompt_is_reported_as_dropped():
    """反向突变：把 `荒诞` 从注入块里拿掉 → 那一条必须记成"被预算丢掉"。"""
    graph, edge = _toy_graph()
    entry = {"id": "h1", "q": Q,
             "must": [[edge.type, [[m.role, m.kind, m.node_id]
                                   for m in edge.members]]]}
    stripped = _editor_text(EDGE_KNOWLEDGE.replace("荒诞", "别的"))
    report = audit_trace([_row("editor", stripped)], graph=graph,
                         entries=[entry], mirror=_mirror(Q))
    drops = report["required_edges_dropped_by_budget"]
    assert drops["status"] == "fail"
    assert drops["dropped"] == 1
    assert drops["examples"][0]["shot_id"] == "shot_007"


def test_the_drop_half_is_not_measured_when_the_join_is_empty():
    """join 不到就 `not_measured`——**绝不**读成"0 条被丢"（那是把未知当通过）。"""
    graph, edge = _toy_graph()
    entry = {"id": "h1", "q": Q,
             "must": [[edge.type, [[m.role, m.kind, m.node_id]
                                   for m in edge.members]]]}
    report = audit_trace([_row("editor", _editor_text())], graph=graph,
                         entries=[entry], mirror=_mirror("景别=MCU"))
    drops = report["required_edges_dropped_by_budget"]
    assert drops["status"] == "not_measured"
    assert drops["matched_shots"] == 0
    assert "不得" in drops["note"]
    assert report["complete"] is False


def test_the_committed_long_run_measures_both_caps():
    """入库证据上的真跑读数：token 半边必须**量出来**并且达标。

    这条不是"跑通即可"——它断言两个 scope 都真的有块、次数非零、最大值也和
    上限一起被报出来。哪天定位器失效（读不到块），它会以 `not_measured` 变红，
    而不是安静地报 0。
    """
    trace = ROOT / "docs" / "evidence" / "20261003_real_long" / "llm_trace.jsonl"
    if not trace.is_file():                     # pragma: no cover - 证据被删时
        pytest.skip("入库的长跑证据不在（这不是通过，是证据缺失）")
    rows = [json.loads(line) for line in
            trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = audit_trace(rows)
    assert report["plan_scope"]["status"] == "pass"
    assert report["shot_scope"]["status"] == "pass"
    assert report["plan_scope"]["calls"] >= 1
    assert report["shot_scope"]["calls"] >= 60
    #: 2026-10-08 用户裁决把两个**预算**抬到 5 万 / 6 万（`rag.max_tokens_per_call`
    #: / `rag.plan_prefetch_tokens`）。这条断言钉的是"审计读的是**当前**配置里的
    #: 那一格"，不是"历史上那一跑的上限"——所以跟着配置走；判据（=不超过上限）没动。
    assert report["plan_scope"]["cap"] == 60000
    assert report["shot_scope"]["cap"] == 50000
    assert report["shot_scope"]["max_tokens"] > 0
    assert set(report["shot_scope"]["locators"]) == {"terminator"}


def test_the_chain_runs_the_injection_audit_and_requires_the_artifact():
    """静态断言：链上必须真的跑它、要求产物落盘、并且**判** token 那一半。

    静态断言挡不住"读数器坏了"，但它挡得住这次发现的那种形状——
    "文档点名了一条通道、链上没有人执行它"。注释行不算活行。
    """
    text = (ROOT / "tools" / "run_tests.ps1").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    calls = [line for line in lines if "injection_audit.py" in line]
    assert calls, "链上没有调用 tools/knowledge/injection_audit.py"
    assert any("injection_audit.json" in line for line in calls), calls
    #: **2026-10-06（P14-257）**：这一格此前**写死** `20261003_real_long`——那是 bm25 时代的跑
    #: （SS84：`/v1/retrieve` 从没被调用过、逐镜查询是旧形状），于是 Q6b 的 required 半边
    #: **永远 join 不上 oracle、永远 `not_measured`**。现在不再点名日期，而是要求它走
    #: **与 knowledge 块同一个 `$knowledgeRun`**（守门：
    #: `test_chain_evidence_is_measured.py::test_q6b_reads_the_same_real_run_as_the_rest_of_the_knowledge_block`）。
    #: 这一条**保留原意并加强**：仍要求"喂的是真跑的 prompt"，而且**那一跑必须真的在库里**。
    assert any("--llm-trace" in line and "$knowledgeRun" in line for line in calls), (
        "链上喂的必须是一份真跑的 prompt：走 `$knowledgeRun`，不许写死某个日期路径")
    defined = re.search(r"\$knowledgeRun\s*=\s*'([^']+)'", text)
    assert defined, "链上必须定义 `$knowledgeRun`"
    run_dir = ROOT / defined.group(1)
    assert (run_dir / "llm_trace.jsonl").is_file(), (
        "喂的那一跑必须带 llm_trace.jsonl（真跑的 prompt）：%s" % run_dir)
    assert (run_dir / "audit_log.jsonl").is_file(), (
        "喂的那一跑必须带 audit_log.jsonl（逐次事件）：%s" % run_dir)
    assert any("Test-Path" in line and "injection_audit.json" in line
               for line in lines), "链上必须检查产物真的写出来了"
    assert any("token_caps.status" in line for line in lines), (
        "链上必须真的判 token 那一半，而不是只打印一行")


# ---------------------------------------------------------------------------
# v1.6 D-05（卡 F3）："条件模式取反"进【经验建议（软）】栏，渲染为「若…则…」。
#
# E-run ⑤（docs/evidence/20261008-v10-nodes1-4-run/README.md §5）：SHOT_PATTERN
# 边（"当 MS＋50mm＋变焦时，别用 CU"）被渲染层写成无条件「禁 CU」，13 镜全部
# 拿到这条硬约束，其中 4 镜的"违反"正是剧本写死的 CU/dolly_in。修法只允许在
# 渲染层分栏，判据**只读边自己的结构化字段**（type / members / qualifiers），
# 不许读文本启发式；超图 schema（hypergraph.py，hg/v2）一个字不动。
# ---------------------------------------------------------------------------

from block_director.contracts.enums import RagBackend  # noqa: E402
from block_director.knowledge.retriever import KnowledgeRetriever  # noqa: E402


def _conditional_graph():
    """一条**条件模式取反**：MS＋50mm＋变焦 ⇒ 别用 CU（E-run ⑤ 的真形状）。"""
    from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node

    nodes = [
        Node(node_id="shot_size:MS", type="shot_size", name="MS", aliases=("MS",)),
        Node(node_id="lens:50mm", type="lens", name="50mm", aliases=("50mm",)),
        Node(node_id="headroom_policy:cinematic", type="headroom_policy",
             name="cinematic"),
        Node(node_id="movement:zoom_in", type="movement", name="zoom_in",
             aliases=("zoom_in",)),
        Node(node_id="shot_size:CU", type="shot_size", name="CU", aliases=("CU",)),
    ]
    edge = HyperEdge.from_dict({
        "type": "SHOT_PATTERN",
        "members": [
            ["allow", "shot_size", "shot_size:MS"],
            ["allow", "lens", "lens:50mm"],
            ["qualifier", "headroom_policy", "headroom_policy:cinematic"],
            ["allow", "movement", "movement:zoom_in"],
            ["forbid", "shot_size", "shot_size:CU"],
        ],
        "source_kind": "theory", "hardness": "hard",
    })
    return Hypergraph(nodes, [edge]), edge


def _conditional_retriever(graph, token_limit: int = 800):
    return KnowledgeRetriever(cards=[], backend=RagBackend.HYPERGRAPH,
                              capabilities=("hypergraph",), hypergraph=graph,
                              token_limit=token_limit)


def test_a_conditional_pattern_negation_lands_in_the_soft_column_as_if_then():
    """SHOT_PATTERN 的条件取反不许再以无条件「禁 CU」形态进硬约束栏。"""
    graph, _edge = _conditional_graph()
    retriever = _conditional_retriever(graph)
    hard, soft = retriever.edge_columns("景别=MS；运镜=zoom_in", scope="shot")
    assert "禁={" not in hard
    assert "CU" not in hard          # 被禁的取值不得以无条件禁令形态出现
    assert "【经验建议（软）】" in soft
    assert "若<" in soft and ">则不要用<" in soft and "CU" in soft
    columns = retriever.last_trace["shot_scope"]["columns"]
    assert columns["hard_edges"] == 0
    assert columns["soft_edges"] == 1
    assert columns["conditional_edges"] == 1


def test_an_unconditional_forbid_edge_stays_in_the_hard_column():
    """EMOTION_PACK 的 forbid（无条件/上下文 qualifier 限定）仍是硬约束。"""
    from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node

    nodes = [
        Node(node_id="emotion:荒诞", type="emotion", name="荒诞",
             aliases=("荒诞",)),
        Node(node_id="intensity:high", type="intensity", name="high", value="high"),
        Node(node_id="movement:固定机位", type="movement", name="固定机位",
             aliases=("固定机位", "固定")),
    ]
    edge = HyperEdge.from_dict({
        "type": "EMOTION_PACK",
        "members": [["allow", "emotion", "emotion:荒诞"],
                    ["qualifier", "intensity", "intensity:high"],
                    ["forbid", "movement", "movement:固定机位"]],
        #: D-05 的判据不读 hardness：soft 但带 forbid 的边也照旧是硬约束
        #: （tests/test_knowledge_cases_wiring.py 的同名纪律）。
        "source_kind": "lesson", "hardness": "soft",
    })
    graph = Hypergraph(nodes, [edge])
    retriever = _conditional_retriever(graph)
    hard, soft = retriever.edge_columns("情绪=荒诞；运镜=固定机位", scope="shot")
    assert "禁={" in hard and "固定机位" in hard
    assert "若<" not in soft and "固定机位" not in soft
    columns = retriever.last_trace["shot_scope"]["columns"]
    assert columns["hard_edges"] == 1
    assert columns["soft_edges"] == 0
    assert columns["conditional_edges"] == 0


def test_a_forbid_scoped_by_a_condition_qualifier_is_rendered_conditionally():
    """`applies_to_shot_size` 这类条件/上下文 qualifier 把 forbid 限定成条件。"""
    from block_director.knowledge.hypergraph import HyperEdge, Hypergraph, Node

    nodes = [
        Node(node_id="emotion:荒诞", type="emotion", name="荒诞",
             aliases=("荒诞",)),
        Node(node_id="intensity:high", type="intensity", name="high", value="high"),
        Node(node_id="shot_size:CU", type="shot_size", name="CU", aliases=("CU",)),
        Node(node_id="movement:固定机位", type="movement", name="固定机位",
             aliases=("固定机位", "固定")),
    ]
    edge = HyperEdge.from_dict({
        "type": "EMOTION_PACK",
        "members": [["allow", "emotion", "emotion:荒诞"],
                    ["qualifier", "intensity", "intensity:high"],
                    ["qualifier", "applies_to_shot_size", "shot_size:CU"],
                    ["forbid", "movement", "movement:固定机位"]],
        "source_kind": "experience", "hardness": "hard",
    })
    graph = Hypergraph(nodes, [edge])
    retriever = _conditional_retriever(graph)
    hard, soft = retriever.edge_columns("情绪=荒诞；运镜=固定机位", scope="shot")
    assert "禁={" not in hard
    assert "若<" in soft and ">则不要用<" in soft and "固定机位" in soft
    columns = retriever.last_trace["shot_scope"]["columns"]
    assert columns["conditional_edges"] == 1


def test_the_shared_token_cap_still_governs_conditional_lines_atomically():
    """条件行与其余两栏共用同一个 token 上限；装不下整条丢，绝不截断。"""
    graph, edge = _conditional_graph()
    tight = _conditional_retriever(graph, token_limit=1)
    block = tight.block_for_shot("景别=MS；运镜=zoom_in", limit=1)
    assert "若<" not in block and "则不要用<" not in block
    assert estimate_tokens(block) <= 1
    assert edge.edge_id in tight.last_trace["shot_scope"]["dropped_edge_ids"]

    roomy = _conditional_retriever(graph, token_limit=800)
    full = roomy.block_for_shot("景别=MS；运镜=zoom_in", limit=800)
    assert "若<" in full and "则不要用<" in full and "CU" in full
    assert estimate_tokens(full) <= 800


def test_conditional_column_rendering_is_deterministic():
    """同一查询两次渲染必须逐字相同（含 trace 的分栏计数）。"""
    graph, _edge = _conditional_graph()
    retriever = _conditional_retriever(graph)
    first = retriever.edge_columns("景别=MS；运镜=zoom_in", scope="shot")
    second = retriever.edge_columns("景别=MS；运镜=zoom_in", scope="shot")
    assert first == second
    assert retriever.last_trace["shot_scope"]["columns"]["conditional_edges"] == 1
