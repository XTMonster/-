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
