"""评分器（spec §15.3）。纯函数：任务元信息 + 模型答案 -> 对/错。

不依赖 bpy、不依赖主链路；fix 类用 demo schema 对拍工具参数可执行性。
score_task 的入参 `meta` 至少含 kind 与 ground_truth，fix 类可带 schemas。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from block_director.layer5_orchestrator.tool_schema import validate_args

from tools.spatial_ruler_ab.arms import DEMO_ACTION_TOOL_SCHEMAS


#: estimate 任务的容差：答案与地面真值的绝对差不超过它就算对。
ESTIMATE_TOLERANCE = 0.05


def _norm_pairs(value: Any) -> list:
    """把 [[角色, 帧], ...] 规整成可比较的排序列表（容忍顺序差异）。"""
    return sorted((str(a), int(b)) for a, b in (value or []))


def _base(meta: Mapping[str, Any], kind: str, ans_ok: bool,
          **detail: Any) -> Dict[str, Any]:
    return {"correct": bool(ans_ok),
            "detail": {"kind": kind, **detail}}


def score_task(meta: Mapping[str, Any], answer: Any) -> Dict[str, Any]:
    """按任务族判定模型答案对错；返回 {"correct", "detail"}。"""
    kind = meta["kind"]
    gt: Any = meta["ground_truth"]
    schemas = meta.get("schemas") or DEMO_ACTION_TOOL_SCHEMAS

    if kind == "verdict":
        if not isinstance(answer, dict):
            return _base(meta, kind, False, reason="答案不是 JSON 对象")
        ok = (answer.get("passed") is gt.get("passed")
              and set(answer.get("failed") or []) == set(gt["failed"]))
        return _base(meta, kind, ok, expected=gt,
                     got={"passed": answer.get("passed"),
                          "failed": answer.get("failed")})

    if kind == "estimate":
        if not isinstance(answer, dict) or "value" not in answer:
            return _base(meta, kind, False, reason="答案缺 value")
        try:
            diff = abs(float(answer["value"]) - float(gt["value"]))
        except (TypeError, ValueError):
            return _base(meta, kind, False, reason="value 非数值")
        return _base(meta, kind, diff <= ESTIMATE_TOLERANCE,
                     expected=gt["value"], got=answer["value"],
                     diff=round(diff, 4), tolerance=ESTIMATE_TOLERANCE)

    if kind == "direction":
        val = answer.get("direction") if isinstance(answer, dict) else None
        ok = val in gt["acceptable"]
        return _base(meta, kind, ok, expected=gt["acceptable"], got=val)

    if kind == "fix":
        if not isinstance(answer, dict) or "tool" not in answer:
            return _base(meta, kind, False, reason="答案缺 tool")
        schema = schemas.get(answer["tool"])
        args_ok = (schema is not None
                   and not validate_args(schema, answer.get("tool_args") or {}))
        # 03b：处方只给方向（allowed_tools），模型选出的工具必须落在
        # 处方白名单内且参数按 demo schema 可执行；不再对拍具体参数值。
        allowed = gt.get("allowed_tools") or [gt["tool"]]
        ok = answer["tool"] in allowed and args_ok
        return _base(meta, kind, ok, expected_tool=gt.get("tool"),
                     allowed_tools=allowed,
                     got_tool=answer["tool"], args_executable=args_ok)

    if kind == "prescription_verdict":
        accept = answer.get("accept") if isinstance(answer, dict) else None
        ok = accept is not None and bool(accept) is bool(gt.get("accept"))
        return _base(meta, kind, ok, expected=gt.get("accept"), got=accept)

    if kind == "dynamic_facts":
        if not isinstance(answer, dict):
            return _base(meta, kind, False, reason="答案不是 JSON 对象")
        ok = (_norm_pairs(answer.get("exits")) == _norm_pairs(gt["exits"])
              and _norm_pairs(answer.get("reentries"))
              == _norm_pairs(gt["reentries"])
              and int(answer.get("direction_changes", -1))
              == int(gt["direction_changes"])
              and sorted(map(str, answer.get("hero_bands") or []))
              == sorted(map(str, gt["hero_bands"])))
        return _base(meta, kind, ok, expected=gt,
                     got={k: answer.get(k) for k in
                          ("exits", "reentries", "direction_changes",
                           "hero_bands")})

    if kind == "action_roles":
        if not isinstance(answer, dict):
            return _base(meta, kind, False, reason="答案不是 JSON 对象")
        missing = [k for k in ("attacker", "victim", "result_frame")
                   if k not in answer]
        if missing:
            return _base(meta, kind, False,
                         reason=f"答案缺键 {missing}", got=answer)
        ok = (answer["attacker"] == gt["attacker"]
              and answer["victim"] == gt["victim"]
              and int(answer["result_frame"]) == int(gt["result_frame"]))
        return _base(meta, kind, ok, expected=gt,
                     got={k: answer.get(k) for k in
                          ("attacker", "victim", "result_frame")})

    if kind == "continuity_verdict":
        if not isinstance(answer, dict) or "continuous" not in answer:
            return _base(meta, kind, False, reason="答案缺 continuous")
        ok = bool(answer["continuous"]) is bool(gt["continuous"])
        detail = {"expected": bool(gt["continuous"]),
                  "got": answer.get("continuous")}
        conf = answer.get("confidence")
        if conf is not None:
            detail["confidence"] = conf
        return _base(meta, kind, ok, **detail)

    if kind == "priority_order":
        if not isinstance(answer, dict) or "priority" not in answer:
            return _base(meta, kind, False, reason="答案缺 priority")
        got = answer["priority"]
        ok = (isinstance(got, list)
              and [str(x) for x in got] == [str(x) for x in gt["priority"]])
        return _base(meta, kind, ok, expected=gt["priority"], got=got)

    if kind == "robustness_verdict":
        if not isinstance(answer, dict) or "still_pass" not in answer:
            return _base(meta, kind, False, reason="答案缺 still_pass")
        ok = bool(answer["still_pass"]) is bool(gt["still_pass"])
        return _base(meta, kind, ok, expected=bool(gt["still_pass"]),
                     got=answer.get("still_pass"))

    return _base(meta, kind, False, reason=f"未知任务族 {kind!r}")
