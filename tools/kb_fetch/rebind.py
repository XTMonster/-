"""卡↔槽位绑定的**机械重绑**（user 2026-10-07 批准，代号「换卡」）。

问题（实测）：1,262 个"未被来源佐证"的槽位里 **84.2%** 的取值**确实写在别的卡正文里**
——错的是**担保关系**（这条边引用了不写这个取值的卡），不是知识本身。
qwen3.8-max-0902 三角色会诊一致指出：把这种事交给"同一抽取器再抽一遍"是**重新掷骰子**
（条件分布不变 ⇒ 分布不变），真正确定性的修法是**机械重绑**。

规则（**确定性、可复现**，与影子实验逐字同一条）：

1. 对每个**未被佐证**的成员（`attestation.label_for` 的口径：取值的 surface 在这条边
   **自己的来源卡**正文里找不到）；
2. 在**候选池**里（见下，`rebind/v2` 起＝**重绑前就已经有边**的卡，按调用方给的字典顺序）
   找**正文真的写了**该 surface 的卡；
3. 取前 `PER_MEMBER_CANDIDATES`（3）张，**追加**进这条边的 `sources[]`（**不删原来源**，
   所以边的出处没有被抹掉，改动可回滚）；
4. 只在**确实找不到**候选时才留原样（那种情况重绑也修不了，属另一类问题）。

**它不是判据**：不改 `attestation` 的口径、不改任何门限；它只决定"哪几张卡为这条成员担保"。
效果以 **C1 同口径复判** 为准（实测 `corrupt 67/90 → 37/90`），不是以 attestation 为准
——后者与候选判据同源，会**构造性**满足。

## `rebind/v2`：候选池收窄为"**重绑前就已经有边**的卡"（2026-10-07，`v1` 的门⑥ 欠账）

`v1` 在**全库**里找候选，于是把 11 张**本来零边**的卡（`comp_lead_room`、
`cine_move_pan_left` 这类手写卡 ＋ 5 张生成卡）追加进了一些边的 `sources[]`。
副作用是它们从"词表表达不出"变成"可断言卡"，而 held-out 冻结夹具里没有它们的条目
⇒ 门⑥ 的 `edge_backed_without_entry` 由 0 变 11、`overall: fail`。

`card_scope_audit` 的模块文档早就把这件事写死了："**补边是有害的**"——把"整轮抽取
一条边都没抽出来"的卡单卡重抽成"有边"，等于把噪声写进索引换一个绿字。重绑的职责是
修**担保关系**，不是**扩大可断言面**；所以 `v2` 把候选限制在**重绑输入边里已经出现过的
卡 id**（`edge_backed_cards()`）：

* 这个集合是**可复现的可观测量**（重绑前就能从输入算出来，不依赖 held-out 夹具，
  所以"索引依赖仪器"那种环形耦合不会出现）；
* `v2` 因此是**保范围**的——重绑**永不改变**"哪些卡有边"这个集合，门⑥ 的欠账不会
  被规则自己制造出来，同时它也**不会自己解锁自己**（若将来抽取真给某张未覆盖卡
  加了边，门⑥ 照旧如实判红）；
* 实测代价：1,063 个可重绑槽位里 **11 个**（全是 `composition_rule:lead_room`，
  唯一候选只有手写卡 `comp_lead_room`）掉回"零候选"，另 1,052 个不变；
  90 条 C1 样本**一条不受影响**（`work/_measure_restricted_rebind.py`）。

**v2 同时修掉一处可推导性缺陷**：`v1` 落库的那份索引是从**影子脚本**的候选次序
（`attestation.load_cards()` 的字典序）promote 回来的，而构建器 `_apply_rebind` 用的是
`build_hypergraph.load_cards()` 的次序——两者在个别边上给出**不同的候选**（实测
`hg:1bb82beaeb5d` 等）。v2 起索引一律**由构建器路径重建**（`--rematch`，不调模型），
所以"库里的索引 == 构建器产物"是构造性的，不再靠对拍脚本自证。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

#: 规则版本。它**进 `CACHE_KEY_FIELDS`**：改了重绑规则必须让索引指纹跟着变，
#: 否则同一条缓存键会同时指向"重绑前"和"重绑后"两份不同的索引。
REBIND_VERSION = "rebind/v2"

#: **裁决剪枝**（`prune/v1`，2026-10-07 用户裁决："用…qwen3.8max0902 解决，代替人工裁决"）。
#:
#: 对象：**零候选**的成员——取值的 surface 在全库任何卡正文里都找不到，所以机械重绑
#: 也修不了。判官（`qwen3.8-max-0902` @ 阿里云百炼，`reasoning_effort=max`）逐条给
#: `keep` / `wrong_card`（卡的**主题**与取值不是一回事）/ `wrong_value`（取值本身错），
#: 判决落在 `docs/evidence/20261007-v15-zerocand-verdict/verdict.json`。
#:
#: 规则只有一条：**判成 `wrong_card`/`wrong_value` 的成员，从它所属的那条边上摘掉**
#: （边被摘空则整条删）。它与重绑同属"卡↔槽位绑定"这一件事，所以进**同一个**缓存键
#: 分量（见 `binding_rules_version()`）——不新开第 10 格，`CACHE_KEY_FIELDS` 的契约不变。
PRUNE_VERSION = "prune/v1"

#: 入库的裁决记录（判词 ＋ 逐条理由）。**单一真源**：索引重建读的就是它。
PRUNE_VERDICT_PATH = "docs/evidence/20261007-v15-zerocand-verdict/verdict.json"


def binding_rules_version(applied: bool = False) -> str:
    """第 9 格 `rebind_version` 的取值：**卡↔槽位绑定的全部规则**版本。

    `rebind/v1`（全库候选）→ `rebind/v2`（保范围）→ `rebind/v2+prune/v1`（＋裁决剪枝）。
    改其中任何一条，指纹当场就变——已入库运行的 `pins.index` 会**如实**标异代。

    `applied=False` 时只算重绑（剪枝**没生效**就不该改指纹——否则已入库运行会因为
    一条没执行的决定白白失配）。谁生效由**记录本身**决定（见 `load_prune_verdicts`）。
    """
    return ("%s+%s" % (REBIND_VERSION, PRUNE_VERSION)) if applied else REBIND_VERSION


def load_prune_verdicts(root=None) -> List[dict]:
    """读裁决记录 → 要摘掉的成员清单（`[]` = 一条都不摘）。纯读，不猜。

    **两条闸门**：① 记录里 `apply` 必须**显式为真**（缺省＝不执行——索引不会因为
    躺在别的目录里的一份记录而悄悄改）；② 只认 `wrong_card`/`wrong_value`。
    """
    import json
    import pathlib

    base = pathlib.Path(root) if root is not None else \
        pathlib.Path(__file__).resolve().parents[2]
    path = base / PRUNE_VERDICT_PATH
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(payload, dict) or payload.get("apply") is not True:
        return []
    out: List[dict] = []
    for row in rows or []:
        verdict = str(row.get("verdict") or "keep")
        if verdict in ("keep", "missing"):
            continue
        out.append({"edge_id": str(row.get("edge_id")), "kind": str(row.get("kind")),
                    "value": str(row.get("value")), "verdict": verdict,
                    "why": str(row.get("why") or "")})
    return out


def prune_members(edges: Sequence[dict], verdicts: Sequence[dict]
                  ) -> Tuple[List[dict], Dict[str, Any]]:
    """按裁决摘掉成员；边被摘空就整条删。**确定性**，没判决的一律不动。"""
    #: 只认**要摘**的判决（`wrong_card` / `wrong_value`）：`keep` 与没判决的一律不动
    #: ——即使调用方把整份裁决记录（含 keep）递进来也一样。
    wanted: Dict[Tuple[str, str, str], str] = {
        (row["edge_id"], row["kind"], row["value"]): row["verdict"]
        for row in verdicts
        if str(row.get("verdict") or "") in ("wrong_card", "wrong_value")}
    out: List[dict] = []
    removed_members = removed_edges = touched = 0
    for edge in edges:
        edge_id = str(edge.get("edge_id"))
        members = list(edge.get("members") or [])
        kept = []
        for member in members:
            key = (edge_id, str(member[1]), str(member[2]).split(":", 1)[-1])
            if key in wanted:
                removed_members += 1
                continue
            kept.append(member)
        if len(kept) == len(members):
            out.append(edge)
            continue
        touched += 1
        if not kept:
            removed_edges += 1
            continue
        record = dict(edge)
        record["members"] = kept
        out.append(record)
    return out, {"prune_version": PRUNE_VERSION, "verdicts": len(verdicts),
                 "edges": len(out), "edges_touched": touched,
                 "members_removed": removed_members, "edges_removed": removed_edges}

#: 每个成员最多追加几张候选卡。
PER_MEMBER_CANDIDATES = 3


def edge_backed_cards(edges: Sequence[dict]) -> set:
    """输入边里**已经出现过**的卡 id（＝重绑前的可断言面）。**纯函数。**

    它就是 `v2` 的候选池：重绑只能把担保挪给**本来就在担保别的成员**的卡，
    于是重绑永不改变"哪些卡有边"这个集合（门⑥ 的欠账不会由规则自己制造出来）。
    """
    return {str(source) for edge in edges for source in (edge.get("sources") or [])}


def candidate_cards(forms: Sequence[str], blobs: Dict[str, str],
                    limit: int = PER_MEMBER_CANDIDATES, *,
                    pool: Sequence[str] | None = None) -> List[str]:
    """正文里真的写了这些 surface 之一的卡 id（按 `blobs` 的顺序，取前 `limit` 张）。

    `pool` 非空时只认池里的卡（`v2` 的保范围约束）；`None`/空集＝不设限（`v1` 的行为，
    保留给"只看规则本身"的单测与历史对拍）。
    """
    wanted = [form for form in forms if form]
    if not wanted:
        return []
    allowed = set(pool) if pool is not None else None
    found: List[str] = []
    for card_id, blob in blobs.items():
        if allowed is not None and str(card_id) not in allowed:
            continue
        if any(form in blob for form in wanted):
            found.append(str(card_id))
            if len(found) >= limit:
                break
    return found


def rebind_edges(edges: Sequence[dict], blobs: Dict[str, str],
                 labels: Any, surfaces: Any, *,
                 candidate_pool: Sequence[str] | None = None
                 ) -> Tuple[List[dict], Dict[str, Any]]:
    """按上面的规则重绑；返回 ``(新边表, 统计)``。纯函数、确定性。

    `labels` 是 ``(edge, member) -> "attested"|"unattested"|"not-checkable"`` 的判定函数，
    `surfaces` 是 ``member_node_id -> [surface, ...]``——两者都由调用方注入，
    这样本模块不依赖 `attestation`（避免与判据形成环形依赖）。

    `candidate_pool` 见 `edge_backed_cards()`：不给就退化成 `v1` 的"全库"行为；
    构建器（`build_hypergraph._apply_rebind`）**必须**给，否则门⑥ 会重新长出孤儿卡。
    """
    out: List[dict] = []
    touched = added = 0
    no_candidate = 0
    for edge in edges:
        record = dict(edge)
        sources = list(record.get("sources") or [])
        extra: List[str] = []
        members_rebound: List[str] = []
        for member in record.get("members") or []:
            if labels(record, member) != "unattested":
                continue
            key = str(member[2])
            candidates = candidate_cards(surfaces(key), blobs,
                                         pool=candidate_pool)
            if not candidates:
                no_candidate += 1
                continue
            picked = [cid for cid in candidates
                      if cid not in sources and cid not in extra]
            if picked:
                extra.extend(picked)
                members_rebound.append(key)
        if extra:
            record["sources"] = sources + extra
            touched += 1
            added += len(extra)
        out.append(record)
    return out, {"rebind_version": REBIND_VERSION, "edges": len(out),
                 "edges_touched": touched, "sources_added": added,
                 "members_without_candidate": no_candidate,
                 "candidate_pool": (len(set(candidate_pool))
                                    if candidate_pool is not None else None)}
