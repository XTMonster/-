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
    assert report["plan_scope"]["cap"] == 2000
    assert report["shot_scope"]["cap"] == 800
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
