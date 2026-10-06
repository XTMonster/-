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

def _identity(value: str) -> str:
    return value


def _lens_mm(value: str) -> str:
    """`35mm` / `35` / `35.0` 归一成同一个串（**只做单位与尾零归一，不做近似**）。"""
    text = str(value).strip().lower().removesuffix("mm")
    try:
        return str(float(text))
    except ValueError:
        return str(value).strip().lower()


#: kind → （成片侧字段, 取值归一化）。**只收"能精确判等"的 kind**；
#: 加进来之前先问两句：① 成片里**真的有**这个字段吗？② 两边的**取值词表**是同一个吗？
#:
#: 7 个"相等式"kind 是 `docs/knowledge/APPLICABILITY_SEMANTICS_v1.md` 第一步点名的；
#: 但**实测**（`work/_peek_kind_domains.py`）发现其中 4 个的**词表对不上**——
#: `action` 索引里是中文动作（上下场/推门…）、成片记的是 `action_types`（`walk_to`/`nod`…）；
#: `vfx` 成片根本没有这个字段；`transition` 一边是 `cut/dissolve/whip`、一边是 `declared.transition`（"淡入"）；
#: `movement` 只**部分**同词表（`dolly_in` 两边都有，`固定` 对不上）。这些不是"没违规"，
#: 是**比不了**——所以本工具除了判等，还要单独报 **词表落差**（`vocabulary_gap`）。
BINDINGS: Dict[str, Tuple[Tuple[str, ...], Any]] = {
    "shot_size": (("shot_type",), _identity),
    "intent": (("intent_type",), _identity),
    "lens": (("camera.lens",), _lens_mm),
    "movement": (("movements[].kind", "declared_camera_move"), _identity),
    "action": (("action_types[]",), _identity),
    "transition": (("declared.transition", "transition_in", "transition_out"), _identity),
    "vfx": (("vfx[].type",), _identity),
    #: `axis_side` 是**值的绑定**（只绑 `neutral` 一个取值）：两边对"中性机位"的定义是同一个
    #: ——产品侧 `axis.py:455` 原文"``neutral`` = 机位恰好落在轴线上，画面没有左右信息"，
    #: 而索引侧的取值就叫 `neutral`。`left`/`right` **不绑**（校准已证明它们跟 ±1 对不上，
    #: 见 `docs/evidence/20261007-axis-family-ruling/axis_convention_calibration.json`），
    #: 它们会落进 `premise_value_unbound` 并**逐条列出**，**绝不当成"通过了"**。
    "axis_side": (("axis.status",), _identity),
}

#: 值的绑定表：只有列在这里的取值才算"绑上了"。**不在表里的值 ⇒ `value_unbound`**。
VALUE_BINDINGS: Dict[str, Dict[str, str]] = {"axis_side": {"neutral": "neutral"}}

#: 向后兼容的名字（老读法：`MAPPING[kind]` 就是字段元组）。
MAPPING: Dict[str, Tuple[str, ...]] = {kind: fields for kind, (fields, _norm) in BINDINGS.items()}

#: **别名表**（裁决 F3：这也算**新判据**，所以必须具名、版本化、可复核）：
#: 规范侧＝**成片侧的英文枚举**；一个知识侧串**只许**映射到一个枚举；
#: 映射不中的知识侧取值**必须显式计入 `vocab_miss`**，**绝不默认通过**。
#: 本表只收"两边都观察到过、且语义等价"的对；没把握的不许编。
VALUE_ALIASES: Dict[str, Dict[str, str]] = {
    "movement": {"固定": "static", "固定机位": "static"},
}
VALUE_ALIASES_VERSION = 1

#: **不是条件**的 kind（提案 ③ 类）：忽略，不参与"判不判得了"，也不参与前提匹配。
#:
#: * `pair`：`AXIS_RULE` 的**必填槽**（`knowledge/hypergraph.py:190`），可它**只有一个取值
#:   `pair:any_two`**——一个恒真的前提。当条件用等于没条件，所以**显式忽略**（不是"判不了"）。
#: * `axis_topic`：**话题**（视线轴／越轴／中性机位／关系轴／运动轴），表达"这条边在说哪条轴"，
#:   不是"这一镜必须满足什么"。
#:
#: 为什么要单列一张表：把它们算进"判不了"会让 `AXIS_RULE` 那 66 条**整体**被判不了，
#: 而它们真正需要判的**只有 `axis_side` 一个槽**。
NOT_A_CONDITION: Dict[str, str] = {
    "pair": "恒真前提（唯一取值 pair:any_two）",
    "axis_topic": "话题（不是条件）",
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
    if field == "axis.status":
        axis = shot.get("axis") or {}
        value = axis.get("status")
        return [str(value)] if value else []
    if field == "shot_type":
        return [str(shot.get("shot_type"))] if shot.get("shot_type") else []
    if field == "intent_type":
        return [str(shot.get("intent_type"))] if shot.get("intent_type") else []
    if field == "declared_camera_move":
        value = shot.get("declared_camera_move")
        return [str(value)] if value else []
    if field == "camera.lens":
        lens = (shot.get("camera") or {}).get("lens")
        return [str(lens)] if lens not in (None, "") else []
    if field == "action_types[]":
        return [str(item) for item in (shot.get("action_types") or [])]
    if field == "vfx[].type":
        return [str((item or {}).get("type")) for item in (shot.get("vfx") or [])
                if isinstance(item, dict) and item.get("type")]
    if field in ("declared.transition", "transition_in", "transition_out"):
        if field == "declared.transition":
            value = (shot.get("declared") or {}).get("transition")
        else:
            value = shot.get(field)
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


def knowledge_side_value(kind: str, raw: str) -> Tuple[str, bool]:
    """知识侧的取值 → （规范化后的串, 是否**命中别名表**）。

    裁决 F3：别名表也是**新判据**——所以：① 只映射到**成片侧的枚举**（规范侧）；
    ② 没命中的**原样返回并标 `False`**，由调用方记进 `vocab_miss` 并逐条列出，
    **绝不默认通过**（"一条错别名就静默吞掉一条潜在违规"）。
    """
    value = member_value(raw, kind)
    aliases = VALUE_ALIASES.get(kind) or {}
    if value in aliases:
        return aliases[value], True
    return value, False


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
    #: **所有**被注入成员按 kind 计数（不看角色、不看能不能判）——用来把"**没纳入**"写出来。
    #: 提案（`APPLICABILITY_SEMANTICS_v1.md` §4）那句"未纳入要写出来，不能因为没算就当没有"，
    #: 靠的就是这张表：**覆盖的**是哪些 kind、**没覆盖的**是哪些 kind、各多少条。
    member_kinds = collections.Counter()
    forbid_values: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    field_domain: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    shots_seen = collections.Counter()
    #: 词表落差：同一边的两侧取值集合，用来回答"这次判等**有没有意义**"。
    knowledge_values: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    film_values: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    #: 每个 kind 的**成员三分**（审查点名要的）：`matched` / `unmatched` / `film_side_empty`。
    #: 为什么必须有：只看"违规 0"会把"**无物可违**"读成"查了通过"。
    member_outcomes: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    #: 判决书要能回答"**可判的 forbid 成员**有多少"（裁决 F4 的设门前置条件 (a)），
    #: 以及"知识侧有多少取值**连别名表都命中不了**"（F3 的 `vocab_miss`）。
    judgeable_forbid_members = 0
    vocab_miss: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    #: 值没绑定的前提（例如 `axis_side:left/right`）逐条列出——**判不了 ≠ 通过**。
    unbound_values: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    #: 成片侧**整个字段缺席**的前提（老产物没有这一栏）——按 kind 计数。
    field_absent_values: collections.Counter = collections.Counter()

    for event in injected:
        shot_id = str(event.get("shot_id") or "")
        shot = shots.get(shot_id)
        if shot is None:
            counts["events_without_a_built_shot"] += 1
            #: **这些边不能被静默丢掉**：口径表里"边总数 = 各种判定之和"必须闭合。
            #: （踩过的坑：这里只 `continue`，于是 344 = 95+224+1 差 24 条没人解释——
            #: 被审查当场抓住："三分之和与分母差 24 条去向未说明"。）
            counts["edges_in_events_without_a_built_shot"] += len(event.get("edge_ids") or [])
            continue
        shots_seen[shot_id] += 1
        for edge_id in event.get("edge_ids") or []:
            edge = edges.get(edge_id)
            if edge is None:
                counts["injected_edge_missing_from_index"] += 1
                continue
            members = [member for member in (edge.get("members") or [])
                       if isinstance(member, (list, tuple)) and len(member) == 3]
            for member in members:
                member_kinds[str(member[1])] += 1
            #: **词表落差先记**：对**所有**被注入的边都记（不看能不能判、也不看前提成不成立）——
            #: 它回答的是"这两套词表是不是同一个"，与"这一镜有没有被违反"是两件事。
            #: （踩过的坑：把它写在判定的 `continue` 之后，就只有"生效"的那条边被统计到，
            #: `action`/`transition`/`vfx` 一起变成空集合，看着像"没问题"。）
            for member in members:
                kind = str(member[1])
                if kind not in BINDINGS:
                    continue
                fields, normalizer = BINDINGS[kind]
                normalized, aliased = knowledge_side_value(kind, str(member[2]))
                if kind in VALUE_ALIASES and not aliased:
                    #: 知识侧写了个**别名表里没有**的取值 ⇒ 记 `vocab_miss`，逐条列出来
                    #: （裁决 F3：**绝不默认通过**）。
                    vocab_miss[kind][normalizer(normalized)] += 1
                knowledge_values[kind][normalizer(normalized)] += 1
                have = {normalizer(raw) for field in fields
                        for raw in shot_values(shot, field)}
                for raw in [raw for field in fields for raw in shot_values(shot, field)]:
                    film_values[kind][normalizer(raw)] += 1
                want = normalizer(normalized)
                if not have:
                    member_outcomes[kind]["film_side_empty"] += 1
                elif want in have:
                    member_outcomes[kind]["matched"] += 1
                else:
                    member_outcomes[kind]["unmatched"] += 1
            #: ① 有未映射的 kind（任何角色）⇒ 整条边判不了
            unmapped_here = [str(member[1]) for member in members
                             if str(member[1]) not in MAPPING
                             and str(member[1]) not in NOT_A_CONDITION]
            if unmapped_here:
                counts["edge_indecidable"] += 1
                for kind in unmapped_here:
                    unmapped[kind] += 1
                continue
            observed: List[str] = []
            for member in members:
                if str(member[1]) in NOT_A_CONDITION:
                    continue
                fields, _normalizer = BINDINGS[str(member[1])]
                for field in fields:
                    observed.extend(shot_values(shot, field))
                    field_domain[field].update(shot_values(shot, field))

            def matched(kind: str, raw: str) -> bool:
                """这一条成员的值，和成片侧**对应字段**的取值**归一之后**比。（两边都要归一！）

                踩过的坑：只归一了一边 ⇒ `lens:35mm` 撞不上成片的 `35.0`，
                真违规被记成 `no_match`——那是**漏判**，比假阳性更隐蔽。
                """
                fields, normalizer = BINDINGS[kind]
                aliased_value, _used_alias = knowledge_side_value(kind, raw)
                want = normalizer(aliased_value)
                have = {normalizer(value) for field in fields
                        for value in shot_values(shot, field)}
                return want in have

            #: ② 前提（非 forbid）必须全中；`no value` 与 `值不等` 都算"不适用"
            premise_ok = True
            value_unbound = False
            field_absent = False
            for member in members:
                role, kind = str(member[0]), str(member[1])
                if role == "forbid" or kind in NOT_A_CONDITION:
                    continue
                counts["premise_members_seen"] += 1
                fields, _norm = BINDINGS[kind]
                if not any(shot_values(shot, field) for field in fields):
                    #: **成片侧这个字段整个不存在**（例如老产物没有 `axis` 那一栏）⇒
                    #: 这不是"前提不成立"，是**这一代产物还没有这个字段**。分开记，
                    #: 免得把"没得比"读成"不适用"。
                    counts["premise_field_absent"] += 1
                    field_absent_values[kind] += 1
                    field_absent = True
                    premise_ok = False
                    break
                bound_values = VALUE_BINDINGS.get(kind)
                if bound_values is not None:
                    _mapped, known = knowledge_side_value(kind, str(member[2]))
                    if not known and member_value(str(member[2]), kind) not in bound_values:
                        #: 这个**取值**没绑定（`left`/`right`）：判不了 ≠ 适用 ≠ 通过。
                        counts["premise_value_unbound"] += 1
                        unbound_values[kind][member_value(str(member[2]), kind)] += 1
                        value_unbound = True
                        premise_ok = False
                        break
                if not matched(kind, str(member[2])):
                    premise_ok = False
                    break
            if not premise_ok:
                #: `edge_unbound`（值没绑定）与 `edge_inactive`（前提不成立）**分开记**——
                #: 混在一起会把"不知道怎么判"读成"不适用"。
                if value_unbound:
                    counts["edge_unbound"] += 1
                elif field_absent:
                    counts["edge_field_absent"] += 1
                else:
                    counts["edge_inactive"] += 1
                continue
            counts["edge_active"] += 1
            #: ③ 前提全中：再看 forbid
            for member in members:
                role, kind = str(member[0]), str(member[1])
                if role != "forbid":
                    continue
                counts["forbid_members_seen"] += 1
                if kind in BINDINGS:
                    judgeable_forbid_members += 1
                value = member_value(str(member[2]), kind)
                forbid_values[kind][value] += 1
                if matched(kind, str(member[2])):
                    counts["violations"] += 1
                    violations.append({"shot_id": shot_id, "edge_id": edge_id,
                                       "kind": kind, "forbid": value,
                                       "observed": observed})
            else:
                counts["no_match"] += 1

    vocabulary_gap = {}
    for kind in BINDINGS:
        know = set(knowledge_values[kind])
        film = set(film_values[kind])
        if not know and not film:
            state = "no_data"
        elif not film:
            state = "film_side_missing"
        elif not know:
            state = "knowledge_side_missing"
        elif know & film:
            state = "overlapping"
        else:
            state = "disjoint"
        vocabulary_gap[kind] = {
            "knowledge_values": sorted(know)[:12],
            "film_values": sorted(film)[:12],
            "overlap": sorted(know & film)[:12],
            #: `disjoint=True` 才是"**两边都有值、但一个都对不上**"——那才是词表落差；
            #: 单边为空是"这条臂这次没数据"，不是落差。
            "state": state,
            "disjoint": state == "disjoint",
        }

    #: `vocab_miss` 的最终定义：**既不在别名表里、又不是成片侧已经在用的取值**
    #: ⇒ 这个映射不出去。（已经是成片枚举的（例如 `dolly_in`）不算 miss——它本来就能直接比。）
    vocab_miss = {kind: {value: count for value, count in counter.items()
                         if value not in film_values[kind]}
                  for kind, counter in vocab_miss.items()}
    vocab_miss = {kind: counter for kind, counter in vocab_miss.items() if counter}

    return {
        "shots_with_injection": len(shots_seen),
        "counts": dict(counts),
        #: **口径表**：每个聚合数都能由下面的原子量唯一重算（这是审查要的那张表）。
        #: 边口径：`injected_edges = indecidable + inactive + active ＋ missing_from_index
        #: ＋ edges_in_events_without_a_built_shot`；**缺一不可**。
        "ledger": {
            "injected_edges": sum(len(event.get("edge_ids") or []) for event in injected),
            "edge_indecidable": counts.get("edge_indecidable", 0),
            "edge_inactive": counts.get("edge_inactive", 0),
            "edge_unbound": counts.get("edge_unbound", 0),
            "edge_field_absent": counts.get("edge_field_absent", 0),
            "edge_active": counts.get("edge_active", 0),
            "injected_edge_missing_from_index": counts.get("injected_edge_missing_from_index", 0),
            "edges_in_events_without_a_built_shot":
                counts.get("edges_in_events_without_a_built_shot", 0),
        },
        #: 覆盖与否**分两张表**列出来（判决书不许只报"能算的那部分"）。
        "covered_kinds": {kind: count for kind, count in member_kinds.most_common()
                          if kind in BINDINGS},
        "not_covered_kinds": {kind: count for kind, count in member_kinds.most_common()
                              if kind not in BINDINGS and kind not in NOT_A_CONDITION},
        #: ③ 类（**故意忽略**）与"没绑定"分开列——它们不是"没覆盖"，是"按规矩不算条件"。
        "ignored_kinds": {kind: count for kind, count in member_kinds.most_common()
                          if kind in NOT_A_CONDITION},
        "member_kinds_seen": dict(member_kinds.most_common()),
        #: ③ 类（不是条件）与"取值没绑定"两张表明着列出来。
        "not_a_condition_kinds": {kind: member_kinds[kind] for kind in NOT_A_CONDITION
                                  if member_kinds.get(kind)},
        "value_bindings": {kind: dict(values) for kind, values in VALUE_BINDINGS.items()},
        "unbound_values": {kind: dict(counter) for kind, counter in unbound_values.items()
                           if counter},
        "field_absent_kinds": dict(field_absent_values.most_common()),
        "member_outcomes_by_kind": {kind: dict(counter) for kind, counter
                                    in member_outcomes.items()},
        #: 裁决 F3 的 `vocab_miss`（别名表命中不了的知识侧取值，逐条列出）＋
        #: 裁决 F4 的设门前置条件 (a)：**可判的 forbid 成员**有多少。
        "value_aliases": {"version": VALUE_ALIASES_VERSION, **VALUE_ALIASES},
        "vocab_miss": {kind: dict(counter) for kind, counter in vocab_miss.items()},
        "judgeable_forbid_members": judgeable_forbid_members,
        "unmapped_forbid_kinds": dict(unmapped.most_common()),
        "bindings": {kind: list(fields) for kind, (fields, _norm) in BINDINGS.items()},
        "vocabulary_gap": vocabulary_gap,
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
    #: 成片产物在不同世代落在不同层（`export/export/`、`export/`、根）：按**已知的三种位置**
    #: 依次找，找到就停——不猜第四种，也不因为"没找到"就静默算成空集。
    candidates = ([pathlib.Path(args.shots)] if args.shots else
                  [run / "export" / "export" / "shots.json",
                   run / "export" / "shots.json",
                   run / "shots.json"])
    shots_path = next((path for path in candidates if path.is_file()), None)
    if shots_path is None:
        print(json.dumps({"error": "找不到 shots.json", "tried": [str(p) for p in candidates]},
                         ensure_ascii=False))
        return 2
    #: 审计日志也有已知的两种落点（交付目录根／`runs/`）——同样只认这两种，不猜第三种。
    audit_candidates = [run / "audit_log.jsonl", run / "runs" / "audit_log.jsonl"]
    audit_path = next((path for path in audit_candidates if path.is_file()), None)
    if audit_path is None:
        print(json.dumps({"error": "找不到 audit_log.jsonl",
                          "tried": [str(p) for p in audit_candidates]}, ensure_ascii=False))
        return 2
    payload = json.loads(shots_path.read_text(encoding="utf-8"))
    shots_rows = payload.get("shots") if isinstance(payload, dict) else payload
    shots = {str(row.get("shot_id")): row for row in (shots_rows or [])}
    result = analyze(injections(audit_path), load_edges(pathlib.Path(args.edges)),
                     shots)
    result["run"] = str(run)
    result["shots_file"] = str(shots_path)
    result["audit_log"] = str(audit_path)
    pathlib.Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("violations",)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
