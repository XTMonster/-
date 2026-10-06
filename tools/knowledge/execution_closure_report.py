"""**执行闭环诊断**：被注入的知识，到底有没有在成片字段上被违反？（**诊断，不设门**）

裁决（人工裁决通道 GLM-5.3，`docs/evidence/20261006-channel-fallback/glm53.answer.json` F2）：
**③ 先诊断、不设门**——`R001–R019` 里没有一条要求校验超边执行，设门＝用实现反向发明规范。
先做**能精确映射到成片字段**的 kind，**绑不到成片字段的 kind 一律进"未映射"桶并计数**
（`axis_side` 那 66 条假违规必须落在这一桶里，**不许当违规报**）。

读什么（**只从审计事件读"注入了什么"**，不读 `shots.json` 的自述——§4.1b 硬规则 2）：

* `audit_log.jsonl` 的 `retrieval_call` 事件：每条带 `data.scope`／`data.shot_id`／
  `data.edge_ids`（这一镜**真的注入了**哪些超边）、`data.case_ids`；
* `knowledge/hypergraph.edges.jsonl`：按 `edge_id` 取 `members`（`["forbid", kind, "kind:value"]`）；
* `shots.json`：成片侧字段（`shot_type`／`intent_type`／`movements[].kind`／`declared_camera_move`）。

映射表（v1，**只收能精确对上的三个 kind**）：

| 边成员 kind | 成片侧字段 |
|---|---|
| `shot_size` | `shot.shot_type` |
| `movement` | `shot.declared_camera_move`（若在）＋ `shot.movements[].kind` |
| `intent` | `shot.intent_type` |

其余 kind 全部进 `unmapped`（按 kind 计数）。**没有 pass line、不接进 `run_tests.ps1` 的通过与否**——
形态照 `tools/ab_triple_baseline.py`（诊断：写产物、只报告）。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any, Dict, Iterable, List, Sequence, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import common  # noqa: E402

#: kind → 成片侧字段名（**只收能精确对上的**；加进来之前先问：这个字段真的等价吗？）
MAPPING: Dict[str, Tuple[str, ...]] = {
    "shot_size": ("shot_type",),
    "movement": ("declared_camera_move", "movements[].kind"),
    "intent": ("intent_type",),
}


def load_edges(path: pathlib.Path) -> Dict[str, Dict[str, Any]]:
    """`edge_id -> 边记录`（只走全仓唯一的 JSONL 读入口）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for row in common.read_jsonl(path):
        if str(row.get("record") or "edge") != "edge":
            continue
        edge_id = str(row.get("edge_id") or "")
        if edge_id:
            out[edge_id] = row
    return out


def injections(path: pathlib.Path) -> List[Dict[str, Any]]:
    """从 `audit_log.jsonl` 取 `retrieval_call` 事件（**注入集的唯一来源**）。"""
    out: List[Dict[str, Any]] = []
    for row in common.read_jsonl(path):
        if str(row.get("kind") or "") != "retrieval_call":
            continue
        data = row.get("data") or {}
        out.append({"scope": str(data.get("scope") or ""),
                    "shot_id": data.get("shot_id"),
                    "edge_ids": [str(item) for item in (data.get("edge_ids") or [])],
                    "case_ids": [str(item) for item in (data.get("case_ids") or [])]})
    return out


def shot_values(shot: Dict[str, Any], field: str) -> List[str]:
    """成片侧某个字段的**取值集合**（字段不在／为空 ⇒ 空列表，不编默认值）。"""
    if field == "shot_type":
        return [str(shot.get("shot_type"))] if shot.get("shot_type") else []
    if field == "intent_type":
        return [str(shot.get("intent_type"))] if shot.get("intent_type") else []
    if field == "declared_camera_move":
        value = shot.get("declared_camera_move")
        return [str(value)] if value else []
    if field == "movements[].kind":
        return [str(item.get("kind")) for item in (shot.get("movements") or [])
                if isinstance(item, dict) and item.get("kind")]
    return []


def member_value(raw: str, kind: str) -> str:
    """把成员值 `kind:value` 拆成 `value`（索引里存的是带前缀的写法）。"""
    text = str(raw or "")
    prefix = str(kind or "") + ":"
    return text[len(prefix):] if text.startswith(prefix) else text


def analyze(injected: Sequence[Dict[str, Any]], edges: Dict[str, Dict[str, Any]],
            shots: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """纯函数：注入集 × 边成员 × 成片字段 ⇒ 逐边判定。**不设门**。

    **判定的顺序完全照裁决**（`docs/evidence/20261006-channel-fallback/glm53.answer.json` F2）：

    1. 这条边里**只要有一个成员的 kind 映射不到成片字段**（例如 `axis_side`）⇒ 整条边
       **判不了**（`edge_indecidable`），把它记进未映射桶——**绝不当违规报**。
       为什么：本仓实测过"按直觉补 forbid 校验"会当场产生假阳性（66 条全来自 `axis_side`）。
    2. 否则先看**全部前提**（非 `forbid` 成员）是否与这一镜的成片取值**精确匹配**：
       不匹配 ⇒ 这条边对这一镜**不适用**（`edge_inactive`），`forbid` **不判违**。
    3. 前提全中 ⇒ 这条边**生效**；此时 `forbid` 的值出现在成片字段里才算**违规**，
       否则记 `no_match`（两者都留样例，供人看取值域对不对得上）。
    """
    violations: List[Dict[str, Any]] = []
    unmapped = collections.Counter()
    counts = collections.Counter()
    forbid_values: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    field_domain: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    shots_seen = collections.Counter()

    for event in injected:
        shot_id = str(event.get("shot_id") or "")
        shot = shots.get(shot_id)
        if shot is None:
            counts["events_without_a_built_shot"] += 1
            continue
        shots_seen[shot_id] += 1
        for edge_id in event.get("edge_ids") or []:
            edge = edges.get(edge_id)
            if edge is None:
                counts["injected_edge_missing_from_index"] += 1
                continue
            members = [member for member in (edge.get("members") or [])
                       if isinstance(member, (list, tuple)) and len(member) == 3]
            #: ① 有未映射的 kind（任何角色）⇒ 整条边判不了
            unmapped_here = [str(member[1]) for member in members
                             if str(member[1]) not in MAPPING]
            if unmapped_here:
                counts["edge_indecidable"] += 1
                for kind in unmapped_here:
                    unmapped[kind] += 1
                continue
            observed: List[str] = []
            for member in members:
                for field in MAPPING[str(member[1])]:
                    observed.extend(shot_values(shot, field))
                    field_domain[field].update(shot_values(shot, field))
            #: ② 前提（非 forbid）必须全中；`no value` 与 `值不等` 都算"不适用"
            premise_ok = True
            for member in members:
                role, kind = str(member[0]), str(member[1])
                if role == "forbid":
                    continue
                counts["premise_members_seen"] += 1
                if member_value(str(member[2]), kind) not in observed:
                    premise_ok = False
                    break
            if not premise_ok:
                counts["edge_inactive"] += 1
                continue
            counts["edge_active"] += 1
            #: ③ 前提全中：再看 forbid
            for member in members:
                role, kind = str(member[0]), str(member[1])
                if role != "forbid":
                    continue
                counts["forbid_members_seen"] += 1
                value = member_value(str(member[2]), kind)
                forbid_values[kind][value] += 1
                if value in observed:
                    counts["violations"] += 1
                    violations.append({"shot_id": shot_id, "edge_id": edge_id,
                                       "kind": kind, "forbid": value,
                                       "observed": observed})
                else:
                    counts["no_match"] += 1

    return {
        "shots_with_injection": len(shots_seen),
        "counts": dict(counts),
        "unmapped_forbid_kinds": dict(unmapped.most_common()),
        "forbid_values_by_kind": {kind: dict(counter.most_common())
                                  for kind, counter in forbid_values.items()},
        "observed_field_domain": {field: dict(counter.most_common())
                                  for field, counter in field_domain.items()},
        "violations": violations[:50],
        "note": "诊断，不设门：没有 pass line，也不接进 run_tests.ps1 的通过与否",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge-execution-closure")
    parser.add_argument("--run", required=True, help="一次运行的目录（内含 audit_log.jsonl）")
    parser.add_argument("--shots", default="",
                        help="shots.json（默认在 --run 下自动找 export/export/shots.json）")
    parser.add_argument("--edges", default="knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    run = pathlib.Path(args.run)
    shots_path = pathlib.Path(args.shots) if args.shots else run / "export" / "export" / "shots.json"
    if not shots_path.is_file():
        shots_path = run / "shots.json"
    payload = json.loads(shots_path.read_text(encoding="utf-8"))
    shots_rows = payload.get("shots") if isinstance(payload, dict) else payload
    shots = {str(row.get("shot_id")): row for row in (shots_rows or [])}
    result = analyze(injections(run / "audit_log.jsonl"), load_edges(pathlib.Path(args.edges)),
                     shots)
    result["run"] = str(run)
    result["shots_file"] = str(shots_path)
    pathlib.Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("violations",)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
