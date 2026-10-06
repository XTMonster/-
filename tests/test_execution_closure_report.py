"""`tools/knowledge/execution_closure_report.py`：**执行闭环诊断**（诊断，不设门）。

裁决（GLM-5.3）：**③ 先诊断、不设门**；先做能精确映射到成片字段的 kind，
**绑不到成片字段的 kind 一律进"未映射"桶并计数**（`axis_side` 那批**不许当违规报**）。

这些用例守住四件事：
① `forbid` **只在全部前提（非 forbid 成员）精确匹配之后**才判——否则就是本仓实测过的假阳性；
② 只要边里有**一个** kind 映射不到成片字段 ⇒ **整条边判不了**（`edge_indecidable`），不算违规；
③ 成员值是 `kind:value` 写法，比较前要**剥前缀**；
④ "这一镜注入了什么"**只从 `audit_log.jsonl` 的 `retrieval_call` 读**，不读 `shots.json` 自述。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge import execution_closure_report as ecr  # noqa: E402


def _edge(edge_id, members, edge_type="STAGING_PACK"):
    return {"record": "edge", "edge_id": edge_id, "type": edge_type,
            "members": [list(item) for item in members]}


def _inject(shot_id, *edge_ids):
    return {"scope": "shot", "shot_id": shot_id, "edge_ids": list(edge_ids),
            "case_ids": []}


def test_a_forbid_is_checked_only_after_every_premise_matches():
    """前提中 ⇒ 生效；前提不中 ⇒ 这条边对这一镜**不适用**，`forbid` 不算违规。"""
    edges = {"e1": _edge("e1", [["qualifier", "intent", "intent:推进"],
                                ["forbid", "shot_size", "shot_size:CU"]])}
    hot = {"s1": {"shot_id": "s1", "intent_type": "推进", "shot_type": "CU"}}
    cold = {"s1": {"shot_id": "s1", "intent_type": "铺垫", "shot_type": "CU"}}

    violated = ecr.analyze([_inject("s1", "e1")], edges, hot)
    assert violated["counts"]["edge_active"] == 1
    assert violated["counts"]["violations"] == 1
    assert violated["violations"][0]["forbid"] == "CU", "成员值要剥掉 `kind:` 前缀"

    inactive = ecr.analyze([_inject("s1", "e1")], edges, cold)
    assert inactive["counts"]["edge_inactive"] == 1
    assert inactive["counts"].get("violations", 0) == 0, "前提不中就不许判违规"


def test_an_unmapped_kind_makes_the_whole_edge_undecidable():
    """`axis_side` 绑不到成片字段 ⇒ **整条边**进未映射桶，`forbid` 不许当违规报。"""
    edges = {"e1": _edge("e1", [["qualifier", "axis_side", "axis_side:neutral"],
                                ["forbid", "shot_size", "shot_size:CU"]])}
    shots = {"s1": {"shot_id": "s1", "shot_type": "CU"}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    assert out["counts"]["edge_indecidable"] == 1
    assert out["counts"].get("violations", 0) == 0
    assert out["unmapped_forbid_kinds"] == {"axis_side": 1}
    assert out["counts"].get("forbid_members_seen", 0) == 0


def test_premise_missing_from_the_film_is_inactive_not_a_violation():
    """成片侧根本没有这个字段（本例 `movement`）⇒ 前提不成立 ⇒ 不适用，**不是违规**。"""
    edges = {"e1": _edge("e1", [["qualifier", "movement", "movement:dolly_in"],
                                ["forbid", "shot_size", "shot_size:CU"]])}
    shots = {"s1": {"shot_id": "s1", "shot_type": "CU", "movements": []}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    assert out["counts"]["edge_inactive"] == 1
    assert out["counts"].get("violations", 0) == 0
    assert out["observed_field_domain"].get("movements[].kind", {}) == {}


def test_injection_comes_from_the_audit_events_not_from_shots_json(tmp_path):
    """`retrieval_call` 才是"注入了什么"的真源；`shots.json` 里写什么都不算数。"""
    log = tmp_path / "audit_log.jsonl"
    log.write_text("\n".join([
        json.dumps({"kind": "llm_request", "data": {"purpose": "understand"}}),
        json.dumps({"kind": "retrieval_call",
                    "data": {"scope": "shot", "shot_id": "s1",
                             "edge_ids": ["e1"], "case_ids": ["c1"]}}),
    ]) + "\n", encoding="utf-8")
    events = ecr.injections(log)
    assert len(events) == 1 and events[0]["edge_ids"] == ["e1"]
    assert events[0]["scope"] == "shot"


def test_the_bindings_table_is_the_documented_seven_kinds():
    """绑定表 = `APPLICABILITY_SEMANTICS_v1.md` 第一步点名的**7 个相等式 kind**。

    加一个 kind 进来之前先问两句：① 成片里**真的有**这个字段吗？② 两边**词表**是同一个吗？
    （实测就有 4 个"看着能绑"的 kind 词表对不上，见 `vocabulary_gap`。）
    """
    assert set(ecr.BINDINGS) == {"shot_size", "intent", "lens", "movement",
                                 "action", "transition", "vfx"}
    assert ecr.BINDINGS["lens"][0] == ("camera.lens",)
    assert ecr.BINDINGS["movement"][0] == ("movements[].kind", "declared_camera_move")


def test_lens_values_are_normalised_before_comparison():
    """`35mm`（索引）与 `35.0`（成片）是**同一个**焦距——不归一就会漏判违规。"""
    assert ecr._lens_mm("35mm") == ecr._lens_mm("35") == ecr._lens_mm("35.0")
    edges = {"e1": _edge("e1", [["qualifier", "intent", "intent:推进"],
                                ["forbid", "lens", "lens:35mm"]])}
    shots = {"s1": {"shot_id": "s1", "intent_type": "推进",
                    "camera": {"lens": 35.0}}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    assert out["counts"]["violations"] == 1, "35mm 撞 35.0 必须判出来"


def test_a_disjoint_vocabulary_is_reported_as_such():
    """两边都有值、但**一个都对不上** ⇒ `disjoint`（词表落差），而不是"没违规"。"""
    edges = {"e1": _edge("e1", [["qualifier", "action", "action:推门"]])}
    shots = {"s1": {"shot_id": "s1", "action_types": ["walk_to"]}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    gap = out["vocabulary_gap"]["action"]
    assert gap["state"] == "disjoint" and gap["disjoint"] is True
    assert gap["overlap"] == []


def test_one_side_missing_is_not_a_vocabulary_gap():
    """成片侧根本没有这个字段 ⇒ `film_side_missing`（**没数据**），不是词表落差。"""
    edges = {"e1": _edge("e1", [["qualifier", "vfx", "vfx:flame"]])}
    shots = {"s1": {"shot_id": "s1"}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    gap = out["vocabulary_gap"]["vfx"]
    assert gap["state"] == "film_side_missing" and gap["disjoint"] is False


def test_the_vocabulary_counters_cover_every_injected_edge_not_just_active_ones():
    """踩过的坑：词表统计写在判定的 `continue` 之后 ⇒ 只有"生效"的边被记，
    其它 kind 一起变成空集合、看着像"没问题"。这条钉住"注入了就记"。"""
    edges = {"e1": _edge("e1", [["qualifier", "axis_side", "axis_side:neutral"]]),
             "e2": _edge("e2", [["qualifier", "shot_size", "shot_size:CU"]])}
    shots = {"s1": {"shot_id": "s1", "shot_type": "MS"}}
    out = ecr.analyze([_inject("s1", "e1", "e2")], edges, shots)
    assert out["counts"]["edge_indecidable"] == 1, "e1 判不了"
    assert out["vocabulary_gap"]["shot_size"]["knowledge_values"] == ["CU"], (
        "即使 e2 那一条**不适用**（前提 shot_size:CU 对不上 MS），它的取值也要进词表统计")


def test_the_alias_table_maps_the_knowledge_side_onto_the_film_enum():
    """裁决 F3：别名表的**规范侧是成片侧的英文枚举**。`固定` ⇒ `static`，
    所以 `forbid movement:固定` 撞上成片的 `static` 时必须判出来。"""
    edges = {"e1": _edge("e1", [["qualifier", "intent", "intent:推进"],
                                ["forbid", "movement", "movement:固定"]])}
    shots = {"s1": {"shot_id": "s1", "intent_type": "推进",
                    "declared_camera_move": "static"}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    assert out["counts"]["violations"] == 1
    assert out["value_aliases"]["version"] == ecr.VALUE_ALIASES_VERSION


def test_a_value_the_film_never_uses_is_a_vocab_miss_not_a_silent_pass():
    """`zoom_in` 既不在别名表里、成片侧也从没用过 ⇒ 必须**逐条记进 `vocab_miss`**。"""
    edges = {"e1": _edge("e1", [["qualifier", "movement", "movement:zoom_in"],
                                ["forbid", "shot_size", "shot_size:CU"]])}
    shots = {"s1": {"shot_id": "s1", "shot_type": "CU", "movements": [{"kind": "dolly_in"}]}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    assert out["vocab_miss"] == {"movement": {"zoom_in": 1}}
    assert out["counts"].get("violations", 0) == 0


def test_a_value_that_is_already_the_film_enum_is_not_a_miss():
    """`dolly_in` 本来就是成片侧的枚举 ⇒ **不算 miss**（它直接可比）。"""
    edges = {"e1": _edge("e1", [["qualifier", "movement", "movement:dolly_in"]])}
    shots = {"s1": {"shot_id": "s1", "movements": [{"kind": "dolly_in"}]}}
    out = ecr.analyze([_inject("s1", "e1")], edges, shots)
    assert out["vocab_miss"] == {}
    assert out["member_outcomes_by_kind"]["movement"]["matched"] == 1


def test_the_edge_ledger_closes_so_every_injected_edge_is_accounted_for():
    """**边口径必须闭合**：`injected_edges` ＝ 各种判定之和，**一条都不许下落不明**。

    这条是审查当场逼出来的：第一版把"镜头没建成"的那些边静默 `continue` 掉，
    于是 `95 + 224 + 1 = 320 ≠ 344`，差 24 条**没人解释**。
    """
    edges = {"e1": _edge("e1", [["qualifier", "shot_size", "shot_size:CU"]]),
             "e2": _edge("e2", [["qualifier", "axis_side", "axis_side:neutral"]])}
    shots = {"s1": {"shot_id": "s1", "shot_type": "MS"}}
    events = [_inject("s1", "e1", "e2"),            # 一个建成镜头的
              _inject("no_such_shot", "e1", "e2")]  # 一个**没有对应镜头**的
    out = ecr.analyze(events, edges, shots)
    ledger = out["ledger"]
    total = (ledger["edge_indecidable"] + ledger["edge_inactive"] + ledger["edge_active"]
             + ledger["injected_edge_missing_from_index"]
             + ledger["edges_in_events_without_a_built_shot"])
    assert ledger["injected_edges"] == 4
    assert total == ledger["injected_edges"], "差 %d 条没有去向" % (
        ledger["injected_edges"] - total)
    assert ledger["edges_in_events_without_a_built_shot"] == 2


def test_uncovered_kinds_are_listed_not_silently_dropped():
    """判决书**不许只报"能算的那部分"**：没纳入的 kind 也要逐条列出来（带条数）。"""
    edges = {"e1": _edge("e1", [["qualifier", "shot_size", "shot_size:CU"]]),
             "e2": _edge("e2", [["qualifier", "axis_side", "axis_side:neutral"]]),
             "e3": _edge("e3", [["qualifier", "emotion", "emotion:愤怒"]])}
    shots = {"s1": {"shot_id": "s1", "shot_type": "CU"}}
    out = ecr.analyze([_inject("s1", "e1", "e2", "e3")], edges, shots)
    assert out["covered_kinds"] == {"shot_size": 1}
    assert out["not_covered_kinds"] == {"axis_side": 1, "emotion": 1}, (
        "没纳入的 kind 必须逐条出现——`emotion` 属于②类（成片里没有这个字段）")
    assert sum(out["member_kinds_seen"].values()) == 3


def test_cli_writes_the_diagnostic_payload_offline(tmp_path):
    run = tmp_path / "run"
    (run / "export" / "export").mkdir(parents=True)
    (run / "audit_log.jsonl").write_text(json.dumps(
        {"kind": "retrieval_call",
         "data": {"scope": "shot", "shot_id": "s1", "edge_ids": ["e1"]}}) + "\n",
        encoding="utf-8")
    (run / "export" / "export" / "shots.json").write_text(json.dumps(
        {"shots": [{"shot_id": "s1", "shot_type": "CU", "intent_type": "推进"}]}),
        encoding="utf-8")
    edges = tmp_path / "edges.jsonl"
    edges.write_text(json.dumps(_edge("e1", [["qualifier", "intent", "intent:推进"],
                                            ["forbid", "shot_size", "shot_size:CU"]])) + "\n",
                     encoding="utf-8")
    out = tmp_path / "out.json"
    code = ecr.main(["--run", str(run), "--edges", str(edges), "--out", str(out)])
    assert code == 0 and out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["counts"]["violations"] == 1
    assert "pass line" in payload["note"], "必须自述这是诊断、没有 pass line"
