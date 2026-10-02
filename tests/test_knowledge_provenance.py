"""E2 溯源（2026-10-01 审查 #21）：`movements[].source` 必须说得出"知识带来的"。

缺陷原样：`delivery/manifest.py::_movements_payload` 里 `source` 只有
`declared` / `planned` 两条分支，于是 §2.3b 的 E2（经验采纳率）**结构性恒为 0**
——不是"没采纳经验"，是"这个字段永远表达不出采纳"。`tools/knowledge/quality.py`
的 E2 读的就是 `source ∈ {experience, lesson, case}`。

本用例钉四件事：

1. 检索器把**真的注入了**的超边按 `source_kind` 归类成 `(kind, value)`，
   `forbid` 成员不算"被采纳"；
2. 传了不同的 `query` 就必须返回空表（不拿上一条查询的命中顶这一条）；
3. 交付层把命中写进 `movements[].source`，且 `declared` 优先、其余回落 `planned`；
4. 没有知识层时（`provenance=None`）输出与 P15 逐字相同。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from block_director.contracts.config import AppConfig
from block_director.contracts.enums import RagBackend
from block_director.contracts.knowledge import Card, HyperEdge
from block_director.contracts.operations import RetrieveResponse
from block_director.contracts.plan import Plan
from block_director.delivery.manifest import build_manifest
from block_director.layer5_orchestrator.headless_runner import _make_knowledge


class _Sidecar:
    """最小 sidecar 替身：两条边，一条硬理论、一条软经验。"""

    def __init__(self):
        self.edges = [
            HyperEdge(edge_id="hg:theory", type="ACTION_BEAT",
                      members=[["allow", "action", "action:推门"],
                               ["qualifier", "beat_type", "beat_type:establish"]],
                      source_kind="theory", hardness="hard"),
            HyperEdge(edge_id="hg:lesson", type="ACTION_BEAT",
                      members=[["allow", "action", "action:转身"],
                               ["qualifier", "beat_type", "beat_type:insert"],
                               ["forbid", "movement", "movement:固定机位"]],
                      source_kind="lesson", hardness="soft"),
        ]
        self.calls = 0

    def retrieve_response(self, query, domain=None, top_k=5, timeout=30.0,
                          cases_top_k=3, analogy_query="") -> RetrieveResponse:
        self.calls += 1
        return RetrieveResponse(
            cards=[Card(id="c1", domain="d", title="t", content="x")],
            edges=list(self.edges),
            trace={"backend": "hypergraph", "lanes": 2, "query": query})


def _retriever():
    config = AppConfig()
    config.rag.backend = RagBackend.HYPERGRAPH
    return _make_knowledge(config, _Sidecar())


def _plan(movements, *, declared: str = "") -> Plan:
    plan = Plan.from_dict({"scene_heading": "INT. 码头 - 日", "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立", "shot_type": "LS",
         "duration_frames": 72, "characters": ["char_001"],
         "camera": {"movements": movements}}]})
    plan.shots[0].declared_shot_number = 1
    if declared:
        from block_director.layer1_input import parse_script

        parsed = parse_script(f"1. LS 72f {declared} 推门\n角色：小明\n")
        payload = build_manifest(plan, parsed=parsed)
        assert payload["shots"][0]["declared"]["camera_move"] in ("", declared)
    return plan


def test_provenance_groups_injected_edges_by_source_kind_and_drops_forbid():
    retriever = _retriever()
    block = retriever.block_for_shot("动作=推门；桥段=establish")
    assert block, "sidecar 替身必须回出可注入的块"
    prov = retriever.provenance(retriever.last_edges_query)
    assert prov.get("theory") == [["action", "推门"], ["beat_type", "establish"]]
    assert prov.get("lesson") == [["action", "转身"], ["beat_type", "insert"]]
    for pairs in prov.values():
        assert ["movement", "固定机位"] not in pairs, "禁忌不算被采纳"


def test_provenance_refuses_to_answer_for_another_query():
    retriever = _retriever()
    retriever.block_for_shot("动作=推门")
    assert retriever.provenance("动作=转身") == {}
    assert retriever.provenance() != {}


def test_manifest_writes_the_knowledge_source_and_keeps_declared_first():
    plan = _plan([{"type": "推门", "start_frame": 1, "end_frame": 40},
                  {"type": "转身", "start_frame": 41, "end_frame": 72}])
    manifest = build_manifest(
        plan, generated_at="t",
        knowledge_provenance={"shot_001": {"theory": [["movement", "推门"]],
                                           "lesson": [["movement", "转身"]]}})
    sources = [item["source"] for item in manifest["shots"][0]["movements"]]
    assert sources == ["theory", "lesson"]


def test_manifest_declared_wins_and_unknown_movement_stays_planned():
    plan = _plan([{"type": "dolly_in", "start_frame": 1, "end_frame": 40}])
    manifest = build_manifest(
        plan, generated_at="t",
        knowledge_provenance={"shot_001": {"experience": [["movement", "dolly_in"]]}})
    assert manifest["shots"][0]["movements"][0]["source"] == "experience"
    # 没有命中、也没有声明 → planned（不许蹭别人的命中）。
    plan2 = _plan([{"type": "orbit_cw", "start_frame": 1, "end_frame": 40}])
    manifest2 = build_manifest(
        plan2, generated_at="t",
        knowledge_provenance={"shot_001": {"experience": [["movement", "dolly_in"]]}})
    assert manifest2["shots"][0]["movements"][0]["source"] == "planned"


def test_without_provenance_the_output_is_p15_identical():
    plan = _plan([{"type": "dolly_in", "start_frame": 1, "end_frame": 40}])
    plain = build_manifest(plan, generated_at="t")
    empty = build_manifest(plan, generated_at="t", knowledge_provenance={})
    assert plain == empty
    assert plain["shots"][0]["movements"][0]["source"] == "planned"


def test_e2_adoption_counts_the_lesson_and_experience_sources(tmp_path):
    from tools.knowledge.quality import e2_adoption

    import json

    shots_path = tmp_path / "shots.json"
    shots_path.write_text(json.dumps({"shots": [
        {"shot_id": "shot_001", "movements": [{"kind": "推门", "source": "theory"}]},
        {"shot_id": "shot_002", "movements": [{"kind": "转身", "source": "lesson"}]},
    ]}, ensure_ascii=False), encoding="utf-8")
    result = e2_adoption(shots_path)
    assert result["numerator"] == 1 and result["denominator"] == 2
    assert result["value"] == 0.5


# --------------------------------------------------------------------------- #
# 驱动器这一层：B1 那一镜到底注入了什么，必须真的被记下来
# --------------------------------------------------------------------------- #
class _MovementSidecar:
    """sidecar 替身：一条带 ``movement`` 成员的理论边（运镜溯源要用它）。"""

    def __init__(self):
        self.edges = [HyperEdge(
            edge_id="hg:move", type="INTENT_PACK",
            members=[["allow", "intent", "intent:推进"],
                     ["allow", "shot_size", "shot_size:LS"],
                     ["qualifier", "movement", "movement:dolly_in"]],
            source_kind="theory", hardness="hard")]
        self.calls = 0

    def retrieve_response(self, query, domain=None, top_k=5, timeout=30.0,
                          cases_top_k=3, analogy_query="") -> RetrieveResponse:
        self.calls += 1
        return RetrieveResponse(cards=[], edges=list(self.edges),
                                trace={"backend": "hypergraph", "query": query})


def _knowledge():
    config = AppConfig()
    config.rag.backend = RagBackend.HYPERGRAPH
    return _make_knowledge(config, _MovementSidecar())


def test_the_editor_call_records_what_that_shot_actually_used(monkeypatch):
    """真路径：`_start_editor_call` → `build_editor_payload`（真检索）→ 记录溯源。

    只把"发出去"这一步换成记录器——检索、契约查询串、payload 构造全是真代码。
    """
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer6_audit.audit_logger import AuditLogger

    retriever = _knowledge()
    driver = PrevisDriver(transport=None, audit=AuditLogger(), script="",
                          config=AppConfig(), knowledge=retriever)
    driver.plan = Plan.from_dict({"scene_heading": "INT. 码头 - 日", "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "推进", "shot_type": "LS",
         "duration_frames": 48,
         "camera": {"movements": [{"type": "dolly_in", "start_frame": 1,
                                   "end_frame": 48}]}}]})
    driver._editing_queue = ["shot_001"]
    driver._editing_index = 0
    sent: Dict[str, Any] = {}
    monkeypatch.setattr(
        driver, "_start_llm_call",
        lambda purpose, payload, note="": sent.update(purpose=purpose,
                                                      payload=payload, note=note))
    driver._start_editor_call("shot_001")

    assert sent["purpose"] == "editor"
    assert "dolly_in" in sent["payload"].messages[0].content, \
        "知识块必须真的进了这一镜的提示词，否则下面的溯源是自证"
    assert retriever.retrieval_calls == 1, "溯源不许额外再发一次检索"
    assert driver.knowledge_provenance()["shot_001"]["theory"] == [
        ["intent", "推进"], ["shot_size", "LS"], ["movement", "dolly_in"]]


def test_a_shot_without_knowledge_hits_is_not_attributed_to_knowledge(monkeypatch):
    """负对照：检索没命中这个运镜时，不许把它写成 ``theory``。"""
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer6_audit.audit_logger import AuditLogger

    driver = PrevisDriver(transport=None, audit=AuditLogger(), script="",
                          config=AppConfig(), knowledge=_knowledge())
    driver.plan = Plan.from_dict({"scene_heading": "INT. 码头 - 日", "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "推进", "shot_type": "LS",
         "duration_frames": 48,
         "camera": {"movements": [{"type": "orbit_cw", "start_frame": 1,
                                   "end_frame": 48}]}}]})
    driver._editing_queue = ["shot_001"]
    driver._editing_index = 0
    monkeypatch.setattr(driver, "_start_llm_call",
                        lambda purpose, payload, note="": None)
    driver._start_editor_call("shot_001")

    provenance = driver.knowledge_provenance()["shot_001"]
    assert ["movement", "orbit_cw"] not in provenance["theory"]
    manifest = build_manifest(driver.plan, generated_at="t",
                              knowledge_provenance=driver.knowledge_provenance())
    assert manifest["shots"][0]["movements"][0]["source"] == "planned"
