"""Validate `fixtures/knowledge_holdout.jsonl` against the held-out coverage gates.

Spec: execution plan v1.4 §4.1b (held-out 覆盖门) + `fixtures/knowledge_holdout.protocol.md`.

Pure stdlib, no bpy, no repo imports: it can run anywhere.

Gates
    ① total          — ≥1200 **non-pilot** entries
    ② format         — field shape, required slots, `top1 ⊆ must`, `must ∩ never = ∅`,
                       no self-contradictory edge, and **q ↔ must consistency**
                       (a query value that contradicts the required edges is rejected)
    ③ seed coverage  — both directions, all 14 kinds, `must`/`never` values inside the
                       vocabulary, and (outside pilot) a bound vocabulary fingerprint
    ④ edge types     — every type carried by ≥N *distinct* (card, query) pairs from ≥M cards
    ⑤ forbid count   — ≥60 Q7 conflict entries
    ⑤b forbid members— every forbidden value has ≥1 conflict case
    ⑥ sources        — card set and `from_card` set match both ways
    ⑦ human review   — Q5/Q7 entries carry a human verdict

新增（R54，v1.5 复查后补的两条"协议写了、机器没查"的口子）：

    ⑩ reachability  — 每条条目的 `must`/`top1` 边**必须能从这个 `q` 检出**
                      （协议 §3.1 对 `must` 的定义；标注提示词规则 0）。
                      够不着的边 = 这条查询永远召不回它自己的期望边。
    ⑪ resolvable    — 每条 `must`/`top1`/`never` 必须映射到**当前索引里的边**
                      （§2.3 的 Q6b 前置①：不存在则"索引构建失败"）。
                      需要 `--nodes/--edges`；索引缺失时记 `not_measured`
                      （§4.1b 硬规则 1：缺证据不得判通过）。

Exit codes
    0  every gate passed
    1  at least one gate failed
    2  at least one gate is `not_measured` — per the plan's hard rule 1, missing evidence
       must never be reported as a pass
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import re
import sys
from typing import Dict, List, Sequence, Tuple

#: **单一真源**：边类型/节点 kind/必填槽位一律从超图 schema 读。
#: 这里原先各抄了一份（六类型、16 个 kind 硬编码），新增边类型时两边会漂——
#: v1.5 扩到 13 类时正是这么暴露的：校验器认不出新类型，抽取器却已经在产。
#: 直接 `python tools/check_holdout.py …` 运行时 `sys.path[0]` 是 `tools/`，
#: 所以先把仓库根挂上去——否则 CLI 会 ModuleNotFoundError（文档里的验收命令就是这么跑的）。
_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from block_director.knowledge import hypergraph as _hg  # noqa: E402
from block_director.utils.console import force_utf8_streams  # noqa: E402

EDGE_TYPES = tuple(_hg.EDGE_TYPES)
NODE_KINDS = tuple(_hg.NODE_TYPES)
QUALIFIER_KINDS = tuple(_hg.QUALIFIER_KINDS)
ALLOWED_KINDS = frozenset(_hg.ALLOWED_KINDS)

#: required slots per edge type (execution plan §2.3 validation gate ④)
REQUIRED_SLOTS = {
    etype: tuple(kind for _role, kind in _hg.REQUIRED_MEMBERS[etype])
    for etype in EDGE_TYPES
}

#: protocol §2.1 — the frozen Chinese query keys.
#: **单一真源 = `hypergraph.QUERY_KEYS`**：检索器、生成器与校验器必须逐键一致，
#: 所以这里读它而不是再抄一份——抄的那份已经漂过一次（它带 `意图→intent`，
#: 而 schema 当时还没有这个键）。
#: 主键（`构图`…）＋ v1.6 的 **`forbid` 键**（`禁构图`…，同样映射到 `composition_rule`）。
#: 顺序很重要：主键在前，所以下面按 `_hg.QUERY_KEYS` 建的 `QUERY_KEY_OF_KIND`
#: 取到的仍是主键（提示词要的是主键，不是 `禁<键>`）。
Q_KEY_TO_KIND = {**_hg.QUERY_KEYS, **_hg.FORBID_QUERY_KEYS}

#: the kinds a vocabulary must cover — every node kind. Kinds reached only through a
#: qualifier (e.g. `scene_type` via the 对白 key) are checked only when present.
REQUIRED_VOCAB_KINDS = frozenset(NODE_KINDS)

KNOWN_TYPES = frozenset(EDGE_TYPES)

#: `q` 里**能表达**的 kind（其余成员是 schema 常量，或根本没有查询键）。
#: 门⑩ 用它判"这条 `must` 边是否真的能从这条查询检出"——协议 §3.1 的原话。
#: **单一真源**：`tools/holdout_fill.py` 从这里 import，不得再抄第二份
#: （此前 `query_shortfall()` 只存在于产出侧、门侧没有，于是产出的文件里
#: 有 1183/4539 条"查询够不着自己的 `must` 边"要到收尾才被发现）。
QUERYABLE_KINDS = frozenset(Q_KEY_TO_KIND.values()) - {"scene_type", "beat_type"}

#: kind -> the frozen Chinese key that carries it (`""` if a kind has no query key).
#: Only meaningful for `QUERYABLE_KINDS`; the qualifier kinds (`intensity`, `pair`, …)
#: are schema constants inside an edge and never appear in `q`.
QUERY_KEY_OF_KIND = {str(kind): str(key) for key, kind in _hg.QUERY_KEYS.items()}

#: 哪些键是 `forbid` 键（`q` 里用它点名"不要这个取值"）。门③ 的支撑统计与
#: 门⑨ 的可达性都用得到：它们必须**按同一个 kind** 计，但又不能冒充主键。
FORBID_KEYS = frozenset(_hg.FORBID_QUERY_KEYS)

PASS, FAIL, NA = "pass", "fail", "not_measured"
ID_RE = re.compile(r"^hq_\d{4,}$")

SPEC_RE = re.compile(r"^(?P<etype>[A-Za-z_]+):(?P<slots>.+)$")
SLOT_RE = re.compile(r"^(?P<forbid>forbid_)?(?P<kind>[a-z_]+)=(?P<value>.+)$")


class EntryError(ValueError):
    """A single record violates the frozen protocol."""


def parse_q(text: str) -> Dict[str, str]:
    """``情绪=荒诞；动作=跺脚`` -> {``情绪``: ``荒诞``, ``动作``: ``跺脚``}."""
    if not isinstance(text, str) or not text.strip():
        raise EntryError("q 为空")
    pairs: Dict[str, str] = {}
    for chunk in re.split(r"[；;]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise EntryError(f"q 片段缺少 '=': {chunk!r}")
        key, _, value = chunk.partition("=")
        key, value = key.strip(), value.strip()
        if not key or not value:
            raise EntryError(f"q 片段为空键或空值: {chunk!r}")
        if key not in Q_KEY_TO_KIND:
            raise EntryError(f"q 的键 {key!r} 不在协议 §2.1 的冻结键集里")
        if key in pairs and pairs[key] != value:
            raise EntryError(f"q 的键 {key!r} 出现了两个不同取值")
        pairs[key] = value
    if not pairs:
        raise EntryError("q 解析后为空")
    return pairs


def parse_spec(spec: str) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    """Return (edge_type, plain_slots, forbid_slots) for one `must`/`never` entry."""
    m = SPEC_RE.match(spec.strip())
    if not m:
        raise EntryError(f"边写法不合法（应为 TYPE:槽位=取值,…）: {spec!r}")
    etype = m.group("etype")
    if etype not in KNOWN_TYPES:
        raise EntryError(f"未知边类型 {etype!r}（只允许 {sorted(KNOWN_TYPES)}）")
    plain: Dict[str, str] = {}
    forbid: Dict[str, str] = {}
    for raw in m.group("slots").split(","):
        raw = raw.strip()
        if not raw:
            continue
        sm = SLOT_RE.match(raw)
        if not sm:
            raise EntryError(f"槽位写法不合法: {raw!r}（在 {spec!r} 内）")
        kind = sm.group("kind")
        if kind not in ALLOWED_KINDS:
            raise EntryError(f"未知 kind {kind!r}（在 {spec!r} 内）")
        (forbid if sm.group("forbid") else plain)[kind] = sm.group("value").strip()
    missing = [s for s in REQUIRED_SLOTS[etype] if s not in plain]
    if missing:
        raise EntryError(f"{etype} 缺必填槽位 {missing}（在 {spec!r} 内）")
    # 「自相矛盾」的判据是**同 kind 同取值**，不是同 kind。
    # 原先写成 `set(plain) & set(forbid)`（kind 级），于是
    # `EMOTION_PACK:emotion=冷淡,intensity=mid,movement=crane_up,forbid_movement=dolly_out`
    # 这种**完全合法**的约束被整条拒收——它要求 crane_up、禁止 dolly_out，
    # 两者是不同的取值，并不冲突。实测 `knowledge/hypergraph.edges.jsonl` 里有
    # **8 条**这样的边（抽取器照 schema 产出，`illegal_members()` 也放行，
    # 因为 `forbid_movement` 就在 `OPTIONAL_MEMBERS[EMOTION_PACK]` 里），
    # kind 级判据让它们**在 oracle 语法里根本表达不出来** → 门⑩ 结构性未解析。
    # 真正的矛盾（`shot_size=中景` ＋ `forbid_shot_size=中景`）仍然照旧被拒。
    clash = sorted(kind for kind in set(plain) & set(forbid)
                   if plain[kind] == forbid[kind])
    if clash:
        raise EntryError(
            f"同一条边里 {clash} 同时被要求和禁止**同一个取值**（自相矛盾）")
    illegal = illegal_members(etype, plain, forbid)
    if illegal:
        legal = set(_hg.REQUIRED_MEMBERS[etype]) | set(_hg.OPTIONAL_MEMBERS.get(etype, ()))
        raise EntryError(
            f"{etype} 上不允许 {illegal}（在 {spec!r} 内）——"
            f"该 (role, kind) 不在 §2.3 的必填＋选填成员表里：{sorted(legal)}。"
            f"索引是照这张表建的（实测 890 条边零非法成员），所以这样的边"
            f"**在索引里根本不可能存在**，标注等于断言一条永远召不回的边"
            f"（上一代 oracle 实测有 243 个 `forbid_<kind>` 就是这么落进去的）")
    return etype, plain, forbid


def illegal_members(etype: str, plain, forbid) -> List[str]:
    """列出这条边里**角色不合法**的成员（`plain`／`forbid` 是 kind 的容器）。

    为什么必须在这里拦：`parse_spec` 原先只查"kind 是否是已知 kind"，不查
    "这个 kind 能不能以这个 role 挂在这个边类型上"。于是
    `EMOTION_PACK:...,forbid_lighting=低调` 一路放行——而
    `block_director/knowledge/hypergraph.py` 的 `OPTIONAL_MEMBERS[EMOTION_PACK]`
    只允许 `forbid_movement`／`forbid_shot_size`／`forbid_vfx`。抽取器照 schema
    建边、非法成员根本进不了索引（实测 890 条边里零个非法成员），
    这种标注断言的就是一条**构造上不存在**的边。
    """
    legal = set(_hg.REQUIRED_MEMBERS[etype]) | set(_hg.OPTIONAL_MEMBERS.get(etype, ()))
    ok_plain = {kind for role, kind in legal if role != "forbid"}
    ok_forbid = {kind for role, kind in legal if role == "forbid"}
    bad = sorted({str(kind) for kind in plain if kind not in ok_plain})
    bad += sorted("forbid_%s" % kind for kind in forbid if kind not in ok_forbid)
    return bad


def spec_key(spec: str) -> Tuple[str, frozenset]:
    """Normalised identity of one edge spec — used for set comparisons.

    Comparing raw strings (the old behaviour) both misses "same edge written with
    different slot order" and can report "no overlap" for two spellings of the very
    same edge.
    """
    etype, plain, forbid = parse_spec(spec)
    items = frozenset([("allow", k, v) for k, v in plain.items()] +
                      [("forbid", k, v) for k, v in forbid.items()])
    return etype, items


# --------------------------------------------------------------------------- 提示词渲染
#
# 下面三个渲染函数是**唯一**被允许生成"键集 / 必填槽位"文案的地方。任何提示词
# （`kb_fetch.holdout_gen`、`holdout_fill`、`holdout_candidates`、`holdout_review_llm`）
# 都必须 import 它们，**不得再抄第二份**——`holdout_fill.GAP_PROMPT` 就抄过一份
# "六类 ＋ 16 键 ＋ AXIS_RULE 只写 pair/axis_side" 的旧表，于是补跑轮的提示与基础
# 提示自相矛盾，模型照样写不可达的边（实测 TRANSITION_PACK 158/158 不可达）。


def query_key_text(sep: str = "/") -> str:
    """协议 §2.1 的冻结查询键，按 schema 顺序拼成一行（用于提示词）。"""
    return sep.join(str(key) for key in Q_KEY_TO_KIND)


#: `QUERYABLE_KINDS` 的**有序**版本（按 `QUERY_KEYS` 的声明顺序）——提示词要求确定性输出。
QUERYABLE_KINDS_SORTED: Tuple[str, ...] = tuple(
    dict.fromkeys(str(kind) for kind in Q_KEY_TO_KIND.values()
                  if kind in QUERYABLE_KINDS))


def required_slot_template(etype: str, placeholder: bool = True) -> str:
    """一条边的必填槽位模板，槽位名与顺序都从 `REQUIRED_MEMBERS` 派生。

    ``placeholder=True``  -> ``EMOTION_PACK:emotion=<emotion>,intensity=<intensity>``
    ``placeholder=False`` -> ``EMOTION_PACK:emotion ＋ intensity``
    """
    if etype not in REQUIRED_SLOTS:
        raise EntryError(f"未知边类型 {etype!r}")
    slots = list(REQUIRED_SLOTS[etype])
    if placeholder:
        return "%s:%s" % (etype, ",".join("%s=<%s>" % (kind, kind) for kind in slots))
    return "%s:%s" % (etype, "＋".join(slots))


def required_slot_templates(placeholder: bool = True) -> List[str]:
    """Every edge type's required-slot template, in `EDGE_TYPES` order."""
    return [required_slot_template(etype, placeholder) for etype in EDGE_TYPES]


def anchor_members(etype: str) -> List[str]:
    """这条边**真能被查询锚上**的成员 kind（有查询键的那些）。

    必填槽位里可能全是"在查询空间里没有取值"的常量（`pair`/`axis_side`、
    `scene_type`、`headroom_policy`……），这类边光写必填槽位是**检索不到的**：
    `AXIS_RULE` 只有补上可选的 `axis_topic` 才挂得上种子。这就是
    `TRANSITION_PACK` 158/158 不可达、`AXIS_RULE` 263 条只命中 16 条的根因。
    """
    members = list(_hg.REQUIRED_MEMBERS.get(etype, ())) + list(
        _hg.OPTIONAL_MEMBERS.get(etype, ()))
    seen: List[str] = []
    for _role, kind in members:
        if kind in QUERYABLE_KINDS and kind not in seen:
            seen.append(str(kind))
    return seen


def anchor_slot_template(etype: str) -> str:
    """必填槽位模板 ＋（若必填一个可锚槽位都没有）一个可锚的选填槽位。

    ``AXIS_RULE:pair=<pair>,axis_side=<axis_side>,axis_topic=<axis_topic>``
    """
    template = required_slot_template(etype)
    required_kinds = set(REQUIRED_SLOTS[etype])
    extra = [kind for kind in anchor_members(etype) if kind not in required_kinds]
    if extra:
        template += "," + ",".join("%s=<%s>" % (kind, kind) for kind in extra)
    return template


def anchor_slot_templates() -> List[str]:
    """Every edge type's anchorable template, in `EDGE_TYPES` order."""
    return [anchor_slot_template(etype) for etype in EDGE_TYPES]


def queryable_slot_hint(sep: str = "、") -> str:
    """``kind``→中文键 的对照，只含**真能写进 `q`** 的 kind（门⑨ 的同一口径）。

    提示词用这一行取代"每条 AXIS_RULE 都手写一遍 axis_topic"之类的特判：凡是这里
    列出的槽位，只要出现在 `must` 里，`q` 里就必须有同名键、同取值。
    """
    return sep.join("`%s`→`%s`" % (kind, QUERY_KEY_OF_KIND[kind])
                    for kind in QUERYABLE_KINDS_SORTED)


def forbid_slot_hint(sep: str = "；") -> str:
    """`forbid_<kind>` 的**合法位置**，从 `REQUIRED_MEMBERS`／`OPTIONAL_MEMBERS` 渲染。

    为什么必须渲染而不是手抄一句"禁忌槽位只允许出现在 EMOTION_PACK 上"：
    那句话只说了**哪一类边**，没说**哪些 kind**。标注员于是写出
    `EMOTION_PACK:…,forbid_lighting=…`——而 schema 里 EMOTION_PACK 的 forbid
    只收 `movement`／`shot_size`／`vfx`，抽取器照 schema 建边，
    这样的边在索引里根本不存在（`illegal_members()` 现在会当场拒收，
    但补跑轮会拿同一个缺口反复重试，把 GPU 时间烧在构造上不可能通过的条目上）。
    """
    parts: List[str] = []
    for etype in EDGE_TYPES:
        members = tuple(_hg.REQUIRED_MEMBERS[etype]) + tuple(_hg.OPTIONAL_MEMBERS.get(etype, ()))
        kinds = [kind for role, kind in members if role == "forbid"]
        if kinds:
            parts.append("%s: %s" % (etype, "／".join("`forbid_%s`" % k for k in kinds)))
    return sep.join(parts)


def load_entries(path: pathlib.Path) -> List[dict]:
    entries: List[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EntryError(f"{path.name}:{lineno} 不是合法 JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise EntryError(f"{path.name}:{lineno} 顶层不是对象")
        record["__line__"] = lineno
        entries.append(record)
    return entries


def validate_entry(record: dict) -> Tuple[Dict[str, str], int]:
    """Raise EntryError, or return (parsed q, number of Q7 conflict hits)."""
    for field in ("id", "from_card", "q", "must", "top1", "never", "annotator", "independence"):
        if field not in record:
            raise EntryError(f"缺字段 {field!r}")
    if not ID_RE.match(str(record["id"]).strip()):
        raise EntryError("id 必须形如 hq_0001")
    if not str(record["from_card"]).strip():
        raise EntryError("from_card 为空")
    ann = record["annotator"]
    if not isinstance(ann, dict):
        raise EntryError("annotator 必须是对象")
    for field in ("model_id", "family", "model_version"):
        if not str(ann.get(field) or "").strip():
            raise EntryError(f"annotator.{field} 不得为空（换族的证据链，见协议 §5.1）")
    if record["independence"] not in ("strong", "weak"):
        raise EntryError("independence 只能是 strong/weak")
    review = record.get("review")
    if review is not None:
        if not isinstance(review, dict) or not review.get("reviewed_by"):
            raise EntryError("review 若存在，必须是 {reviewed_by, verdict}")
        if review.get("verdict") not in ("accepted", "rejected", "amended"):
            raise EntryError("review.verdict 只能是 accepted/rejected/amended")
    must = record["must"]
    if not isinstance(must, list) or not 1 <= len(must) <= 3:
        raise EntryError("must 必须是 1–3 条")
    top1 = record["top1"]
    if not isinstance(top1, list):
        raise EntryError("top1 必须是数组")
    if not {spec_key(s) for s in top1} <= {spec_key(s) for s in must}:
        raise EntryError("top1 必须 ⊆ must")
    never = record["never"]
    if not isinstance(never, list):
        raise EntryError("never 必须是数组")
    if {spec_key(s) for s in never} & {spec_key(s) for s in must}:
        raise EntryError("must 与 never 不得相交")
    parsed_must = []
    for spec in list(must) + list(never):
        if not isinstance(spec, str):
            raise EntryError("must/never 的条目必须是字符串")
        parsed_must.append(parse_spec(spec))
    q = parse_q(record["q"])

    # q ↔ must 一致性：q 里的某个 kind，只要 must 里有该 kind 的槽位，
    # 就必须有一个取值相同。挡住"把词表整段抄进 q、而边说的是另一回事"。
    must_kinds: Dict[str, set] = {}
    for _etype, plain, forbid in [parse_spec(s) for s in must]:
        for kind, value in list(plain.items()) + list(forbid.items()):
            must_kinds.setdefault(kind, set()).add(value)
    for key, value in q.items():
        kind = Q_KEY_TO_KIND[key]
        if kind in must_kinds and value not in must_kinds[kind]:
            raise EntryError(
                f"q 的 {key}={value} 与 must 里的 {kind} 取值不一致"
                f"（must 说的是 {sorted(must_kinds[kind])}）")

    hits = 0
    for spec in must:
        _etype, _plain, forbid = parse_spec(spec)
        for kind, value in forbid.items():
            for zh, qvalue in q.items():
                # 「同类同值」：kind 必须对上（协议 §3.3 / 文档 §4.1b），
                # 只比值会让 `景别=中景` 撞上 `forbid_movement=中景`。
                if Q_KEY_TO_KIND.get(zh) == kind and qvalue == value:
                    hits += 1
    return q, hits


#: 机器复核（双模型面板）的记录必须自带这三样，否则**不可佐证**：
#: 两个**不同**的模型 id（换族之外还要"两条独立意见"）＋ 面板提示的指纹
#: （「协议先冻结」：同一次复核里所有记录必须同指纹）。缺任何一样，
#: 门⑦ **不认**这条记录 —— 否则门⑦ 读的就是"被测文件自己写的判决书"，
#: 而 §4.1b 硬规则 2 明写判据不得自证。
PANEL_TAG = "llm-panel"


def review_class(review: dict) -> Tuple[Optional[str], str]:
    """一条复核记录 → ``(被承认的裁决者类别, 不承认的原因)``。

    * ``human``：协议原文的裁决者，**不需要**佐证字段（人审本来就没有工具指纹）。
    * ``llm-panel``：必须有 ``source.models``（≥2 个且互不相同）与
      ``source.prompt_sha256``；缺了就当**没有裁决记录**并把原因如实报出来。
    * 其它字符串：一律不认（此前是"写什么算什么"）。
    """
    who = str((review or {}).get("reviewed_by") or "").strip().lower()
    if not who:
        return None, ""
    if who == "human":
        return "human", ""
    if who != PANEL_TAG:
        return None, f"reviewed_by={who!r} 不是 human/llm-panel"
    source = review.get("source") or {}
    models = [str(item).strip() for item in (source.get("models") or []) if str(item).strip()]
    if len(models) < 2:
        return None, "llm-panel 缺 source.models（双模型）"
    if len(set(models)) < 2:
        return None, f"llm-panel 的两个模型 id 相同：{models}"
    if not str(source.get("prompt_sha256") or "").strip():
        return None, "llm-panel 缺 source.prompt_sha256"
    return PANEL_TAG, ""


def gate_entries(entries: Sequence[dict]) -> Tuple[str, dict]:
    if not entries:
        # 硬规则 1：空集不得判"格式通过"——against a zero-entry file every
        # per-entry check is vacuously true, which is exactly the trap the rule names.
        return FAIL, {"entries": 0, "valid": 0, "problems": ["空集：没有任何条目可验"],
                      "problem_count": 1, "q7_conflicts": 0,
                      "must_pairs_per_type": {t: 0 for t in EDGE_TYPES},
                      "must_cards_per_type": {t: 0 for t in EDGE_TYPES},
                      "q7_forbid_members": {}, "needs_human": 0, "human_reviewed": 0,
                      "reviewed_by_class": {},
                      "uncorroborated_reviews": [], "uncorroborated_count": 0,
                      "panel_prompt_hashes": {},
                      "q7_member_count": 0, "_parsed_q": []}
    problems: List[str] = []
    seen: Dict[str, int] = {}
    q7 = 0
    q7_members: Dict[str, int] = {}
    needs_human = 0
    reviewed_by_class: Dict[str, int] = {}
    #: 复核记录必须**可被外部佐证**（§4.1b 硬规则 2「禁止自证」）。机器复核的
    #: 记录里要带 `source{models, prompt_sha256}`：没有它，门⑦ 读的就是"被测文件
    #: 自己写的判决书"——任何实现都能凭空填一个 `reviewed_by` 字符串。
    uncorroborated: List[str] = []
    panel_hashes: Dict[str, int] = {}
    #: 复核记录的**裁到什么程度**：一致裁决 vs 面板分歧（待人类裁决）。
    agreement_split: Dict[str, int] = collections.Counter()
    type_pairs: Dict[str, set] = {t: set() for t in EDGE_TYPES}
    type_cards: Dict[str, set] = {t: set() for t in EDGE_TYPES}
    parsed_q: List[Dict[str, str]] = []
    for record in entries:
        try:
            q, hits = validate_entry(record)
        except EntryError as exc:
            problems.append(f"line {record.get('__line__')}: {exc}")
            continue
        ident = str(record["id"])
        if ident in seen:
            problems.append(f"line {record.get('__line__')}: id {ident!r} 重复"
                            f"（首次在 line {seen[ident]}）")
        seen[ident] = record.get("__line__", 0)
        q7 += 1 if hits else 0
        parsed_q.append(q)
        qsig = tuple(sorted(q.items()))
        for spec in record["must"]:
            etype, _plain, forbid = parse_spec(spec)
            # 计数以「去重后的 (卡片, 查询)」为单位：同一条 q 复制 30 次不算覆盖
            type_pairs[etype].add((str(record["from_card"]), qsig))
            type_cards[etype].add(str(record["from_card"]))
            for kind, value in forbid.items():
                q7_members[f"{kind}={value}"] = q7_members.get(f"{kind}={value}", 0) + 1
        if hits or (record.get("expect_movements") or []):
            needs_human += 1
            review = record.get("review") or {}
            who, why = review_class(review)
            if who is None and why:
                uncorroborated.append(f"{ident}: {why}")
                who = ""
            if who == "llm-panel":
                stamp = str((review.get("source") or {}).get("prompt_sha256") or "")
                panel_hashes[stamp] = panel_hashes.get(stamp, 0) + 1
            if who:
                reviewed_by_class[who] = reviewed_by_class.get(who, 0) + 1
                #: 2026-10-03：面板**分歧**的条目也是"复核过"，但记录里写着
                #: `agreement: false` / `needs_human: true`。不把这两个数分开报，
                #: "已复核 176 条"会被读成"176 条都裁定了"——那是另一件事。
                agreement_split["一致" if review.get("agreement") is True
                                else "分歧（待人类裁决）"] += 1
    detail = {"entries": len(entries), "valid": len(parsed_q), "problems": problems[:20],
              "problem_count": len(problems), "q7_conflicts": q7,
              "must_pairs_per_type": {t: len(s) for t, s in type_pairs.items()},
              "must_cards_per_type": {t: len(s) for t, s in type_cards.items()},
              "q7_forbid_members": q7_members, "needs_human": needs_human,
              "human_reviewed": reviewed_by_class.get("human", 0),
              "reviewed_by_class": reviewed_by_class,
              "uncorroborated_reviews": uncorroborated[:10],
              "uncorroborated_count": len(uncorroborated),
              #: `reviewed_by_class` 只说"谁裁的"；这两个计数说"裁到什么程度"。
              "panel_agreement_split": dict(agreement_split),
              "panel_prompt_hashes": {k: v for k, v in panel_hashes.items()},
              "q7_member_count": len(q7_members),
              "_parsed_q": parsed_q}
    return (FAIL if problems else PASS), detail


def gate_total(entries: Sequence[dict], min_entries: int) -> Tuple[str, dict]:
    """Only non-pilot entries count towards the 1200 (protocol §2)."""
    pilot = [e for e in entries if e.get("pilot") is True]
    formal = [e for e in entries if e.get("pilot") is not True]
    n = len(formal)
    return (PASS if n >= min_entries else FAIL), {
        "entries": n, "entries_pilot": len(pilot), "min_entries": min_entries}


def gate_edge_types(pairs: Dict[str, int], cards: Dict[str, int],
                    per_type: int, min_cards: int,
                    assertable: Dict[str, int] | None = None) -> Tuple[str, dict]:
    """每类边都要被考到；**每类的对数据"该类能断言多少对"取小**。

    **门限口径变更（2026-10-01，用户裁决"改门限吧"）**。旧判据是"每类 ≥ `per_type`
    （30）条 `(卡片, 查询)` 要求 + ≥ `min_cards`（10）张不同的卡"。这个 30 是 schema
    **只有 6 类**、语料是另一批时的常数；v1.6 扩到 16 类之后，同一份**许可可得**的语料
    摊到每类只剩 20 上下（实测 `IMPACT_PACK` 22／`SOUND_PACK` 22／`MUSIC_PACK` 16），
    而这三类的原子边数 ≈ 覆盖卡片数、required 签名大多各不相同（跨卡归并无从下手）——
    它们**在构造上够不到 30**。供给侧也两度查到底：Gutenberg 与 OCW 两个能用的馆藏
    **都不产**这类知识（`REMAINING_DECISIONS.md` 附一～附六）。

    新判据：`required = min(per_type, assertable[type])` ——
    **"每类至多要求它真能给的那些对，但能给到 30 就必须交满 30"**。

    `assertable` 由**索引**侧给出（`tools/holdout_pool.py --report` 里的
    `assertable_pairs_per_type`：该类在词表内、且有来源卡的 `(卡片, 查询)` 对，
    **与 oracle 实际生成了什么无关**），所以这不是"拿自己的答案给自己判卷"：
    它仍然要求 oracle 把该类**能断言的对**全部对出来。
    没给 `assertable` 时退回旧判据（`required = per_type`），行为不变。
    """
    limits = {}
    for edge_type in pairs:
        cap = per_type if not assertable else int(assertable.get(edge_type, per_type))
        limits[edge_type] = min(per_type, cap)
    short = {t: n for t, n in pairs.items() if n < limits.get(t, per_type)}
    thin = {t: n for t, n in cards.items() if n < min_cards}
    return (PASS if not short and not thin else FAIL), {
        "min_pairs_per_type": per_type, "min_cards_per_type": min_cards,
        "required_pairs_per_type": limits, "assertable_provided": bool(assertable),
        "short_pairs": short, "thin_cards": thin}


def gate_forbid(q7: int, min_forbid: int,
                assertable: int | None = None) -> Tuple[str, dict]:
    """Q7 冲突条目要有；**要求数取 `min(60, 可断言冲突数)`**。

    **门限口径变更（2026-10-01，与门④ 同一条授权"改门限吧"）**。旧判据是
    "Q7 冲突条目 ≥ 60"。实测这份**许可语料**能支撑的冲突极其有限：索引里 101 个
    `forbid` 成员中，**只有 9 个**能在它自己的来源卡里找到理据（取值／名字／别名
    出现在正文里，且同一张卡里有"不要/避免/切忌…"类否定词）。

    也就是说 60 这个数只能靠**卡里没有依据**的冲突凑出来 —— 而那正是双模型复核把
    **93/116** 条 Q7 条目判掉的原因（`REMAINING_OPTIONS.md` 附七）。

    新判据：`required = min(60, assertable_conflicts)`。`assertable_conflicts` 由
    **索引侧**给出（`holdout_pool --assertable-out` 写出的值：带 `forbid` 成员、
    且至少一个来源卡在正文里给出理据的边所能配出的 `(卡片,查询)` 冲突对数），
    与 oracle 实际生成了什么无关，所以不是自证；不给这个数时**行为与旧版一致**。
    """
    required = min_forbid if assertable is None else min(min_forbid, int(assertable))
    return (PASS if q7 >= required else FAIL), {
        "q7_conflicts": q7, "min": min_forbid, "required": required,
        "assertable_conflicts": assertable}


def gate_forbid_members(members: Dict[str, int], minimum: int = 1) -> Tuple[str, dict]:
    """Every `forbid` member must appear in ≥1 Q7 conflict case (§4.1b 门⑤)."""
    short = {k: v for k, v in members.items() if v < minimum}
    if not members:
        return FAIL, {"members": 0, "under_covered": {}}
    return (PASS if not short else FAIL), {"members": len(members), "under_covered": short}


def gate_human_review(needs: int, reviewed_by_class: Dict[str, int], minimum: int,
                      classes: Sequence[str] = ("human",), *,
                      uncorroborated: int = 0,
                      panel_prompt_hashes: Optional[Dict[str, int]] = None
                      ) -> Tuple[str, dict]:
    """Q5/Q7 条目必须有**裁决记录**；接受哪些裁决者由 `classes` 指定。

    **裁决者类别（2026-10-01，用户明确授权"不理协议了，你能做尽量做"）**：
    协议 §5.5 原本只认 `reviewed_by == "human"`。用户长期不在家、无法做人审，
    明确授权由机器侧的**双模型复核**（`tools/holdout_review_llm.py`，DeepSeek ＋ GLM
    两个异族模型）承担这一层。

    实现上**没有伪造任何记录**：复核工具照旧写 `reviewed_by: "llm-panel"`（真实），
    本门改成**接受哪些类别**可配 —— 默认仍是 `("human",)`（协议原样），
    验收链显式传 `--reviewer-classes human,llm-panel`。报告里同时给出
    `reviewed_by_class`，谁裁的写得清清楚楚。

    双模型分歧的条目仍会被复核工具标 `panel_disagreement` 并单独成表
    （`docs/knowledge/PANEL_DISAGREEMENTS.md`），人可以只复核那一份。

    **可佐证性（2026-10-01，§4.1b 硬规则 2）**：机器复核的记录只有自带
    `source{models ≥2 且互异, prompt_sha256}` 才计数（:func:`review_class`）；
    同一份文件里出现**两个不同的面板提示指纹**同样判失败——协议不冻结，
    前后两半就不是同一套判据。
    """
    accepted = tuple(str(name).lower() for name in classes)
    reviewed = sum(int(count) for name, count in reviewed_by_class.items()
                   if str(name).lower() in accepted)
    hashes = {str(key): int(value)
              for key, value in (panel_prompt_hashes or {}).items() if str(key)}
    detail = {"needs_human": needs, "human_reviewed": reviewed,
              "min_human_review": minimum, "accepted_reviewers": list(accepted),
              "reviewed_by_class": dict(reviewed_by_class),
              "uncorroborated_reviews": int(uncorroborated),
              "panel_prompt_hashes": hashes}
    if len(hashes) > 1:
        detail["reason"] = ("同一份 held-out 里出现了多个面板提示指纹："
                            f"{sorted(hashes)}（协议未冻结，复核不可比）")
        return FAIL, detail
    if needs == 0:
        return NA, detail
    return (PASS if reviewed >= min(needs, minimum) else FAIL), detail


#: 非模型标注族。机械/规则通道（`holdout_pool --mechanical` 写 `family="rule"`）的
#: oracle 是**从索引自己派生**的 —— `ORACLE_DECISION_v15.md` §二 的原话是
#: "「门⑧（换族）禁止『机械从索引派生 oracle』绕过」——那等于自己考自己"。
#: 空 family 同样不是标注者，一并收在这里。
#:
#: 实测事故（2026-10-01）：`holdout_pool --mechanical` 的 2191 条产物写
#: `family="rule"` ＋ `independence="strong"`，而旧门⑧ 只抓"与抽取器同族的 strong"，
#: 于是把一份自证文件判成 **pass**，RK-13 的全部指标都建立在这份文件之上。
NON_MODEL_ANNOTATOR_FAMILIES = frozenset({"rule", ""})


def gate_independence(entries: Sequence[dict], extractor_family: str) -> Tuple[str, dict]:
    """`independence: strong` has to be true, not just claimed.

    R49's whole point is that the annotator must not share the extractor's family;
    the field is an assertion about two *different* artefacts, so the checker has to
    compare it against the extractor's identity rather than trust the label.

    "Different from the extractor" is necessary but **not sufficient**: a family that
    is not a model family at all (`rule`) is the index grading itself. Both halves
    have to be rejected, otherwise the gate only catches the sloppier one and the
    cheaper bypass stays open.
    """
    if not extractor_family:
        return NA, {"reason": "未提供 --extractor-family / --extractor-manifest：无法核对换族"}
    families = {str((e.get("annotator") or {}).get("family") or "") for e in entries}
    non_model = sorted(f for f in families if f in NON_MODEL_ANNOTATOR_FAMILIES)
    liars = sorted({str(e.get("id")) for e in entries
                    if e.get("independence") == "strong"
                    and str((e.get("annotator") or {}).get("family") or "") == extractor_family})
    detail = {"extractor_family": extractor_family, "annotator_families": sorted(families),
              "non_model_families": non_model,
              "strong_but_same_family": liars[:20], "liar_count": len(liars)}
    if non_model:
        detail["reason"] = (
            f"标注族 {non_model} 不是模型族：这份 oracle 由索引自己派生（机械/规则通道），"
            "不构成协议 §5.1 的换族证据")
        return FAIL, detail
    return (PASS if not liars else FAIL), detail


def gate_seed_coverage(parsed_q: Sequence[Dict[str, str]], vocab: Dict[str, Sequence[str]],
                       must_values: Dict[str, set], has_fingerprint: bool,
                       min_support: int, support: Dict[str, Dict[str, set]]
                       ) -> Tuple[str, dict]:
    """Word-list coverage, **both directions**, over `q` **and** over `must`/`never`.

    Unused vocabulary value      -> the seed space has a blind spot.
    Used value outside the list  -> the label is not expressed in the index namespace,
                                    which silently sends Q4 to zero (the protocol's trap).
    A missing kind               -> whatever the vocabulary omits is simply never checked.
    No vocabulary fingerprint     -> the vocabulary cannot be bound to the index build.
    """
    missing_kinds = sorted(REQUIRED_VOCAB_KINDS - set(vocab))
    if missing_kinds:
        # 词表缺一个 kind 不是"没测到"，是**输入本身有缺陷**：那个 kind 的取值
        # 从此不受任何约束（§4.1b 硬规则 1：分母为 0 一律判失败，不是 not_measured）。
        return FAIL, {"reason": f"词表缺 kind：{missing_kinds}（缺哪个 kind，哪个 kind 就免检）",
                      "missing_kinds": missing_kinds}
    if not has_fingerprint:
        return NA, {"reason": "词表没有 _fingerprint：无法与索引构建绑定（协议 §6）"}

    used: Dict[str, set] = {}
    for q in parsed_q:
        for key, value in q.items():
            used.setdefault(Q_KEY_TO_KIND[key], set()).add(value)

    # 「用到了吗」只对**既能用查询键表达、又有边类型接受**的 kind 检查：
    #   * character/object 是索引侧节点类型，`q` 没有对应的中文键；
    #   * axis_topic 之类即使有键，也没有任何边类型收它 —— 要求它出现在 q 里
    #     等于要求标注者写一条永远命中不了种子的查询。
    # 两类都会在 `unreachable_kinds` 里显式报出来，**不静默忽略**（§0.5 第 2 条）。
    slotted = {kind for etype in EDGE_TYPES
               for group in (REQUIRED_SLOTS.get(etype) or (),)
               for kind in group}

    queryable = set(Q_KEY_TO_KIND.values()) & slotted
    unreachable = sorted((set(Q_KEY_TO_KIND.values()) - slotted) | (set(vocab) - slotted))
    missing: Dict[str, List[str]] = {}
    thin: Dict[str, List[str]] = {}
    for kind, values in vocab.items():
        if kind not in queryable:
            continue
        gap = [v for v in values if v not in used.get(kind, set())]
        if gap:
            missing[kind] = gap
        weak = [v for v in values
                if len(support.get(kind, {}).get(v, set())) < min_support]
        if weak:
            thin[kind] = weak

    unknown: Dict[str, List[str]] = {}
    for kind, values in list(used.items()) + list(must_values.items()):
        allowed = set(vocab.get(kind, []))
        if not allowed:
            continue
        extra = sorted(v for v in values if v not in allowed)
        if extra:
            unknown.setdefault(kind, [])
            unknown[kind] = sorted(set(unknown[kind]) | set(extra))

    detail = {"missing_values": missing, "unknown_values": unknown, "thin_values": thin,
              "min_support": min_support, "kinds_checked": len(vocab),
              "vocab_fingerprint": True, "unreachable_kinds": unreachable}
    return (PASS if not missing and not unknown and not thin else FAIL), detail


#: 门⑥ 的**分母下界**（§4.1b 硬规则 1：比率型判据的分母要带下界，分母太小/为空
#: 一律判失败）。这条门现在允许 `--exclude-cards` 把"词表表达不出的卡"挪出分母，
#: 而那是一条**能自己解开自己**的规则：把抽取关掉，所有卡都是"零条边"→ 分母空 →
#: 门反而绿。没有这条下界，门⑥ 就是恒真式。实测 2084/2113 = 98.6%，下界取 95%。
#: 它只可能把门**判得更严**：放开下界之前，任何一张被多剔的卡都会让门变红。
MIN_EXPRESSIBLE_SHARE = 0.95


def gate_sources(entries: Sequence[dict], cards: Sequence[str],
                 excluded: Sequence[str] = ()) -> Tuple[str, dict]:
    """Both directions: every **入库卡** has ≥1 entry, and no entry cites a ghost card.

    §4.1b 的原话是「**每张入库卡（L1/L2）**至少派生 1 条」，而 §2.3b 把 L1 定义成
    "镜头层面的拍摄理论/轴线/构图/运镜耦合"、L2 是"条件→取舍的经验"。所以**不是
    每一张卡都是入库卡**：`excluded`（`knowledge/card_scope.json` 里判为范围外的）
    不进这一门的分母，但**如实计数并报出来**——不许静默缩小分母。

    而且这一门的**分母本身有下界**（`MIN_EXPRESSIBLE_SHARE`）：见那里的注释，
    没有它，"零条边的卡不进分母"这条规则会把自己变成恒真式。
    """
    excluded_set = {str(item) for item in excluded}
    expected = [str(c) for c in cards if str(c) not in excluded_set]
    used = {str(e.get("from_card", "")) for e in entries}
    gap = [c for c in expected if c not in used]
    ghost = sorted(used - set(cards))
    share = (len(expected) / len(cards)) if cards else 0.0
    thin = share < MIN_EXPRESSIBLE_SHARE
    return (PASS if not gap and not ghost and not thin else FAIL), {
        "cards": len(cards), "cards_expected": len(expected),
        "cards_out_of_scope": sorted(excluded_set),
        "cards_out_of_scope_count": len(excluded_set),
        "expressible_share": round(share, 6),
        "min_expressible_share": MIN_EXPRESSIBLE_SHARE,
        "missing_cards": gap[:20], "missing_count": len(gap),
        "ghost_cards": ghost[:20], "ghost_count": len(ghost),
        "reason": ("可断言卡只占入库卡的 %.2f%%，低于下界 %.0f%%：`--exclude-cards` "
                   "把分母削得太狠（§4.1b 硬规则 1）"
                   % (share * 100, MIN_EXPRESSIBLE_SHARE * 100)) if thin else ""}


def query_shortfall(entry: dict) -> List[str]:
    """返回"查询没能覆盖到的、本可表达的槽位"清单（空 = 合格）。

    这是协议 §3.1 那句"`must` = **如果抽不到这条边我会认为检索失败了**"的机器
    实现：一条 `must` 边如果连它自己能在 `q` 里写出来的槽位都没被 `q` 点名，
    这条查询就**根本召不回**它——Q1/Q2 在这种条目上数学不可达。

    口径与产出侧**同一份**（`tools/holdout_fill.py` 从这里 import）：
    只看 `must[0]` 与全部 `top1`，只看 `plain` 槽位，`QUERYABLE_KINDS` 里不含
    `scene_type`/`beat_type`（这两个 kind 的 `must` 槽位历史上不要求写进 `q`）。
    **这条口径的覆盖面是有限的，报告里如实写明**——不在这里偷偷放宽或收紧，
    否则"覆盖 ≥2 个成员时 Q1=0.727/Q2=0.917"这条实测标定就对不上了。

    2026-10-02 记一笔**试过但撤掉**的收紧：把 `forbid_<kind>=v` 也要求"必须在 `q` 里
    点到名"看起来是补上这里的已知缺口，但**禁忌槽位有两种合法写法**——`禁运镜=固定`
    （回避式：我不想用固定）与 `运镜=固定`（冲突式：我想要固定，而这条边说不要）。
    后者正是 Q7 冲突条目本身（`tests/test_check_holdout.py::q7_entry` 就是照着它写的），
    按前者收紧会**把 Q7 的夹具判红**。所以这一门维持原口径；真正修的是**提示词**
    （`holdout_pool.required_q_hint` 曾经给"只以 forbid 出现的 kind"发主键形式的提示，
    见那里的注释与用例）。
    """
    try:
        pairs = parse_q(str(entry.get("q") or ""))
    except EntryError:
        return ["q_unparsable"]
    have = {(Q_KEY_TO_KIND[key], value) for key, value in pairs.items()
            if key in Q_KEY_TO_KIND}
    short: List[str] = []
    for spec in list(entry.get("must") or [])[:1] + list(entry.get("top1") or []):
        try:
            _etype, plain, _forbid = parse_spec(spec)
        except EntryError:
            continue
        for kind, value in plain.items():
            if kind in QUERYABLE_KINDS and (kind, value) not in have:
                short.append(f"{kind}={value}")
    return sorted(set(short))


def gate_reachability(entries: Sequence[dict]) -> Tuple[str, dict]:
    """门⑩：每条条目的期望边都必须能从它自己的 `q` 检出（协议 §3.1）。

    分母下界（§4.1b 硬规则 1）：没有任何条目 → 没有可判的东西，判失败。
    """
    if not entries:
        return FAIL, {"entries": 0, "short": 0,
                      "reason": "空集：没有条目可判"}
    short: List[dict] = []
    for record in entries:
        miss = query_shortfall(record)
        if miss:
            short.append({"id": record.get("id"), "line": record.get("__line__"),
                          "q": record.get("q"), "unreachable": miss[:4]})
    detail = {"entries": len(entries), "short": len(short),
              "short_ratio": round(len(short) / len(entries), 4),
              "examples": short[:5],
              "scope": "must[0] + top1，plain 槽位；QUERYABLE_KINDS 排除 "
                       "scene_type/beat_type（与产出侧同一份口径）"}
    return (FAIL if short else PASS), detail


def load_index(nodes_path: str, edges_path: str):
    """读当前索引。**懒 import** 是为了不引入 `holdout_score` 的循环依赖
    （`holdout_score` 在模块级 import 本模块的 `parse_spec`）。"""
    from tools.holdout_score import load_graph

    return load_graph(pathlib.Path(nodes_path), pathlib.Path(edges_path))


def _unresolved_cause(spec: str, by_type: Dict[str, list], node_lookup,
                      graph) -> Tuple[str, int]:
    """给一条**没通过严格 `norm_key` 相等**的 spec 定根因。

    返回 `(cause, covered_plain_members)`。三档对应三种完全不同的处分：

    * `unparsable` —— 写法本身不合法（由门② 先兜住，这里只是不炸）；
    * `value_not_in_index` —— spec 里的某个 `kind=取值` 在索引节点里不存在。
      **标注侧抄错了词表取值**（真实案例：提示模板把 ``avg_shot_len=<1s``
      写成 ``<<1s``，标注员逐字照抄，35 条 `must` 因此永远解析不到）；
    * `no_edge_of_type` / `no_edge_with_those_plain_members` —— 同类边不存在，
      或存在但没有一条覆盖全部 plain 成员。这是**索引里没有这条知识**，
      只能靠重抽取／补语料，改标注改不出来；
    * `plain_subset_index_has_extra_members` / `plain_subset_but_forbid_differs`
      —— 边其实在，只是索引那条边**多带了成员**（`axis_topic` 那类可选槽位）
      或 forbid 集不同。这一档是"标注方不可见索引"结构性冲突的直接证据。

    `covered_plain_members` 用来量"差多远"：值等于 `len(plain)` 说明差在
    forbid 或多出来的成员上（第一档），远小于 `len(plain)` 说明索引里根本
    没有这条知识（第二档）。**这一层是诊断，不参与门⑪的判据。**
    """
    try:
        etype, plain, forbid = parse_spec(spec)
    except EntryError:
        return "unparsable", 0
    for kind, value in list(plain.items()) + list(forbid.items()):
        if not node_lookup(graph, kind, value):
            return "value_not_in_index", 0
    same = by_type.get(etype) or []
    if not same:
        return "no_edge_of_type", 0
    want = {(kind, node_lookup(graph, kind, value)) for kind, value in plain.items()}
    want_forbid = {(kind, node_lookup(graph, kind, value))
                   for kind, value in forbid.items()}
    best = 0
    subset_same_forbid = False
    subset_diff_forbid = False
    for edge in same:
        edge_plain = {(m.kind, m.node_id) for m in edge.members if m.role != "forbid"}
        best = max(best, len(want & edge_plain))
        if not want <= edge_plain:
            continue
        edge_forbid = {(m.kind, m.node_id) for m in edge.members if m.role == "forbid"}
        if want_forbid == edge_forbid:
            subset_same_forbid = True
        else:
            subset_diff_forbid = True
    if subset_same_forbid:
        return "plain_subset_index_has_extra_members", best
    if subset_diff_forbid:
        return "plain_subset_but_forbid_differs", best
    return "no_edge_with_those_plain_members", best


#: 门⑪的**期望关系**（v1.5 解冻）。默认 `exact` = 规格字面（成员集完全相等）。
#: 另两档是可选口径，**默认不变**：选哪一档是规格裁决，实现只把开关装上、
#: 并把三档的数字都量出来（三种口径的天花板见 docs/knowledge/ORACLE_ALIGNMENT.md）。
#:  - `subset`    ：标注的 plain 成员 ⊆ 索引那条边（forbid 仍完全相等）；
#:  - `card_edge` ：该条目的卡在索引里有没有边（不看类型与成员）。
#: `never` 槽位不参与这两档放宽：负样本的语义是"这条**不该**命中"，
#: 用"这张卡有没有边"去判它是答非所问。
EXPECTATION_RELATIONS = ("exact", "subset", "card_edge")


def gate_index_resolvable(entries: Sequence[dict], graph,
                          relation: str = "exact") -> Tuple[str, dict]:
    """门⑪：每条 `must`/`top1`/`never` 必须映射到当前索引里的边。

    §2.3 的 Q6b 前置①：**"若某 query 的 required 边在归并后确实不存在，则索引
    构建失败（不留给 P14-4 去发现）"**。不作为的话，`holdout_score` 只能把这些
    标注从 required 分母里剔掉——分母变小、比率变好看，缺陷反而看不见。
    """
    if relation not in EXPECTATION_RELATIONS:
        raise EntryError(f"未知的期望关系 {relation!r}，只能取 {EXPECTATION_RELATIONS}")
    from tools.holdout_score import spec_to_norm_key
    from tools.holdout_score import spec_matches_by_subset
    from tools.holdout_score import _node_id_for

    if not entries:
        return FAIL, {"entries": 0, "specs": 0, "unresolved": 0,
                      "reason": "空集：没有条目可判"}
    by_type: Dict[str, list] = {}
    for edge in graph.edges:
        by_type.setdefault(str(edge.type), []).append(edge)
    # 卡级口径的索引：这张卡在索引里有没有边。**类型无关**。
    cards_with_edge = {str(source) for edge in graph.edges
                       for source in (getattr(edge, "sources", ()) or ())}
    per_field = {"must": [0, 0], "top1": [0, 0], "never": [0, 0]}
    subset_ok = 0          # 满足「标注 ⊆ 索引」的 spec 数（**包含**已满足严格相等的）
    strict_ok = 0          # 满足「成员集完全相等」的 spec 数
    card_edge_ok = 0       # must/top1 里"该卡在索引里有边"的 spec 数（诊断量）
    unresolved: List[dict] = []
    # 未命中的**根因**分类（诊断量，不改判据）。三档对应三种完全不同的处分：
    # `value_not_in_index`（词表/取值写错，标注侧可修）、
    # `no_edge_of_type`/`no_edge_with_those_plain_members`（索引里没有这条知识，
    # 只有重抽取或补语料才可能补上）、
    # `plain_subset_but_forbid_differs`（边在，只差 forbid 集）。
    causes: Dict[str, int] = {}
    unresolved_by_type: Dict[str, int] = {}
    #: `plain` 成员被索引边覆盖了几个（0..n）——用它看"差多远"，而不是只看 0/1。
    closeness: Dict[str, int] = {}
    specs = 0
    for record in entries:
        for field in ("must", "top1", "never"):
            for spec in record.get(field) or []:
                specs += 1
                per_field[field][1] += 1
                text = str(spec)
                strict = spec_to_norm_key(text, graph) is not None
                # 诊断量（不参与 status）：标注成员"只多不少"地落在某条索引边上。
                # 规格字面要求的是**完全相等**，而标注方不可见索引——两条一起
                # 在构造上把某一类边（如带可选 `axis_topic` 的 AXIS_RULE）判死。
                # 这是规格级冲突，门这里只如实把两层事实都摆出来。
                wider = strict or spec_matches_by_subset(text, graph)
                strict_ok += 1 if strict else 0
                subset_ok += 1 if wider else 0
                card_ok = (field != "never"
                           and str(record.get("from_card", "")) in cards_with_edge)
                card_edge_ok += 1 if card_ok else 0
                if field == "never":
                    matched = wider if relation == "subset" else strict
                else:
                    matched = {"exact": strict, "subset": wider,
                               "card_edge": card_ok}[relation]
                if matched:
                    per_field[field][0] += 1
                    continue
                cause, covered = _unresolved_cause(text, by_type, _node_id_for,
                                                   graph)
                causes[cause] = causes.get(cause, 0) + 1
                if cause != "unparsable":
                    etype = text.split(":", 1)[0].strip()
                    unresolved_by_type[etype] = unresolved_by_type.get(etype, 0) + 1
                closeness[str(covered)] = closeness.get(str(covered), 0) + 1
                if len(unresolved) < 8:
                    unresolved.append({"id": record.get("id"),
                                       "line": record.get("__line__"),
                                       "field": field, "spec": str(spec),
                                       "cause": cause})
    n_unresolved = specs - sum(v[0] for v in per_field.values())
    per_field_unresolved = {k: v[1] - v[0] for k, v in per_field.items()}
    detail = {"entries": len(entries), "specs": specs,
              "resolved": {k: v[0] for k, v in per_field.items()},
              "totals": {k: v[1] for k, v in per_field.items()},
              "unresolved_per_field": per_field_unresolved,
              "unresolved": n_unresolved,
              "unresolved_ratio": round(n_unresolved / specs, 4) if specs else 0.0,
              # 根因分类（诊断量）：把"73% 未命中"拆成"标注写错取值 / 索引里没这条
              # 知识 / 边在但 forbid 集不同"。测法见 `work/diag_gate10.py`。
              "unresolved_by_cause": causes,
              "unresolved_by_edge_type": unresolved_by_type,
              "unresolved_closeness": closeness,
              # 诊断量：把"标注成员 ⊆ 索引边"单独算一遍。它**不改判据**，
              # 只把"完全相等（规格字面）vs 只多不少（构造上可达）"这两层摆开，
              # 供规格裁决；见 holdout_score.spec_matches_by_subset 的说明。
              "strict_relation_matches": strict_ok,
              "subset_relation_matches": subset_ok,
              "subset_relation_ratio": (round(subset_ok / specs, 4)
                                        if specs else 0.0),
              # v1.5：可选口径。`expectation_relation` 是**实际用于判 status 的那一档**，
              # 另两档永远是诊断量——谁都不许悄悄改验收线。
              "expectation_relation": relation,
              "card_edge_matches": card_edge_ok,
              "card_edge_ratio": (round(card_edge_ok / specs, 4) if specs else 0.0),
              "index_edges": len(graph.edges),
              "examples": unresolved,
              "note": ("§2.3 Q6b 前置①：must/top1 指向不存在的边 = 索引构建失败；"
                       "never 指向不存在的边 = 那条负样本是空谈（Q3 测不到东西）。"
                       f" 逐字段未命中：{per_field_unresolved}"
                       f"；诊断：另有 {subset_ok}/{specs} 条满足"
                       f"「标注成员 ⊆ 索引边（forbid 完全相等）」——这一层与规格字面的"
                       f"「成员集完全相等」不同，标注方不可见索引时后者在构造上不可能"
                       f"全过（AXIS_RULE 的可选 axis_topic 就是结构性一例），属规格级裁决")}
    return (FAIL if n_unresolved else PASS), detail


def load_vocab(path: str, pilot: bool) -> Tuple[Dict[str, Sequence[str]] | None, bool]:
    """Accept either `{kind: [...]}` or `{"_fingerprint": str, "kinds": {kind: [...]}}`."""
    payload = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--vocab 必须是对象")
    if "kinds" in payload:
        fingerprint = bool(str(payload.get("_fingerprint") or "").strip())
        kinds = payload["kinds"]
    else:
        fingerprint = False
        kinds = payload
    if not isinstance(kinds, dict) or not all(
            isinstance(k, str) and isinstance(v, list) for k, v in kinds.items()):
        raise ValueError("--vocab 的 kinds 必须是 {kind: [value, ...]}")
    if pilot:
        # 试点阶段还没有索引可绑定；把指纹要求放行，但正式集必须带指纹
        return kinds, True
    if not fingerprint:
        return None, False
    return kinds, fingerprint


def main(argv: Sequence[str] | None = None) -> int:
    # **判据的退出码不许被控制台编码左右**：`--json` 打的那份报告里有 `⊆`
    # （`gate_10_index_resolvable.note` 的 "must/top1 ⊆ …"），cp936 编不出它 →
    # `UnicodeEncodeError` → 进程以未捕获异常退出，退出码 1 —— 而 1 在这里是
    # "有门失败"。实测与处置见 `block_director/utils/console.py`。
    force_utf8_streams()

    parser = argparse.ArgumentParser(prog="check_holdout")
    parser.add_argument("path", nargs="?", default="fixtures/knowledge_holdout.jsonl")
    parser.add_argument("--min-entries", type=int, default=1200)
    parser.add_argument("--min-per-type", type=int, default=30,
                        help="每类边至少被多少条 **去重后的 (卡片,查询)** 要求")
    parser.add_argument("--min-cards-per-type", type=int, default=10,
                        help="每类边的支撑条目至少来自多少张不同的卡")
    parser.add_argument("--assertable", default="",
                        help="门④ 的**可断言对**上限（JSON：{类型: 对数}，来自 "
                             "`tools/holdout_pool.py --report`）。给了它，每类的对数要求"
                             "取 `min(--min-per-type, 该类可断言对数)`：**能给到 30 的必须"
                             "交满 30，给不到的按它真能给的要求**（2026-10-01 用户裁决）。"
                             "不给就退回旧判据。")
    parser.add_argument("--min-forbid", type=int, default=60)
    parser.add_argument("--min-seed-support", type=int, default=1,
                        help="每个词表取值至少出现在多少条不同的 (卡片,查询) 里。"
                             "默认 **1** ＝ §4.1b 的原话（\"词表里每个 node value 至少"
                             "出现在 1 条 `q` 里\"）；`tools/knowledge/holdout_vocab.py`"
                             "的 `MIN_SUPPORT_EDGES` 必须与它同一个数。"
                             "取 3 会把只被 1–2 条边表达的取值剔出词表，那些边连带"
                             "其来源卡一起从门⑥ 消失（实测 28 张卡），"
                             "而且让索引里的 `forbid` 成员写不进任何 `q`。")
    parser.add_argument("--min-human-review", type=int, default=120,
                        help="Q5/Q7 条目里必须带人裁决的条数（协议 §5.5；pilot 时为 1）")
    parser.add_argument("--reviewer-classes", default="human",
                        help="门⑦ 接受哪些裁决者（逗号分隔）。默认 `human`（协议原样）；"
                             "用户授权机器双模型复核后可传 `human,llm-panel`——"
                             "记录本身**不会被改写**，报告里 `reviewed_by_class` 会写清谁裁的。")
    parser.add_argument("--vocab", default="", help="JSON: {kind: [value, ...]}"
                                                   " 或 {_fingerprint, kinds:{...}}（P14-1 产出）")
    parser.add_argument("--cards", default="", help="JSON: 卡片 id 数组（来源覆盖门）")
    parser.add_argument("--exclude-cards", default="",
                        help="不进分母的卡片清单（`knowledge/card_scope.json` 的 "
                             "`excluded` 数组，或旧键 `out_of_scope`，或直接一个 id 数组）："
                             "§4.1b 写的是「每张**入库卡（L1/L2）**至少派生 1 条」，而"
                             "**入库卡＝可断言卡**——冻结的 node 词表表达不出它的知识时，"
                             "`must` 在构造上落不到任何边（门⑩），这条要求无解。判据是"
                             "确定性的：索引对该卡零条边（`tools/kb_fetch/card_scope_audit.py`）。"
                             "剔了几张会在门⑥ 明细里如实计数（`cards_out_of_scope`）。")
    parser.add_argument("--extractor-family", default="",
                        help="抽取器的 family（或给 --extractor-manifest）；门⑧ 用它核对换族是否属实")
    parser.add_argument("--extractor-manifest", default="",
                        help="knowledge/hypergraph.manifest.json；自动读它的 extractor.family")
    parser.add_argument("--nodes", default="",
                        help="索引节点 JSONL（门⑪ 用）；缺省 knowledge/hypergraph.nodes.jsonl")
    parser.add_argument("--edges", default="",
                        help="索引超边 JSONL（门⑪ 用）；缺省 knowledge/hypergraph.edges.jsonl")
    parser.add_argument("--expectation-relation", default="exact",
                        choices=list(EXPECTATION_RELATIONS),
                        help="门⑪按哪种关系判「期望边存在」：exact（规格字面，默认）／"
                             "subset／card_edge。另两档永远是诊断量，改口径必须显式选")
    parser.add_argument("--pilot", action="store_true",
                        help="试点模式：门限放宽到 1，便于在语料落地前跑通管道")
    parser.add_argument("--json", action="store_true", help="只打印 JSON 报告")
    parser.add_argument("--out", default="",
                        help="把 JSON 报告写到这个路径（UTF-8，由 Python 写——"
                             "PowerShell 5.1 的 `>` 会写成 UTF-16，下游 json.loads 会炸）")
    args = parser.parse_args(list(argv) if argv is not None else None)

    path = pathlib.Path(args.path)
    if not path.is_file():
        print(json.dumps({"error": f"{path} 不存在"}, ensure_ascii=False))
        return 1

    min_entries = 1 if args.pilot else args.min_entries
    per_type = 1 if args.pilot else args.min_per_type
    min_cards = 1 if args.pilot else args.min_cards_per_type
    min_forbid = 1 if args.pilot else args.min_forbid
    min_support = 1 if args.pilot else args.min_seed_support
    min_review = 1 if args.pilot else args.min_human_review

    try:
        entries = load_entries(path)
    except EntryError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1

    report: Dict[str, object] = {"path": str(path), "pilot": bool(args.pilot)}
    statuses: List[str] = []

    status, detail = gate_total(entries, min_entries)
    statuses.append(status)
    report["gate_1_total"] = {"status": status, **detail}

    fstatus, fdetail = gate_entries(entries)
    statuses.append(fstatus)
    report["gate_2_format"] = {"status": fstatus,
                               **{k: v for k, v in fdetail.items() if k != "_parsed_q"}}

    assertable: Dict[str, int] | None = None
    assertable_conflicts: int | None = None
    if args.assertable:
        try:
            payload = json.loads(pathlib.Path(args.assertable).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"读不到 --assertable: {exc}"}, ensure_ascii=False))
            return 1
        # 接受两种形状：直接的 `{类型: 对数}`，或池工具的完整报告
        # （`{"assertable_pairs_per_type": {...}}`）。
        assertable = payload.get("assertable_pairs_per_type", payload)
        conflicts = payload.get("assertable_conflicts")
        assertable_conflicts = None if conflicts is None else int(conflicts)
    tstatus, tdetail = gate_edge_types(fdetail["must_pairs_per_type"],
                                       fdetail["must_cards_per_type"], per_type, min_cards,
                                       assertable=assertable)
    statuses.append(tstatus)
    report["gate_4_edge_types"] = {"status": tstatus, **tdetail}

    # 门⑤ 的口径与门④ 同源：两个 "assertable" 都来自同一份 `--assertable` 文件
    # （都是**索引侧**的属性）。缺它就退回旧判据。
    gstatus, gdetail = gate_forbid(fdetail["q7_conflicts"], min_forbid,
                                   assertable=assertable_conflicts)
    statuses.append(gstatus)
    report["gate_5_forbid"] = {"status": gstatus, **gdetail}

    mstatus, mdetail = gate_forbid_members(fdetail["q7_forbid_members"], 1)
    statuses.append(mstatus)
    report["gate_5b_forbid_members"] = {"status": mstatus, **mdetail}

    reviewer_classes = tuple(name.strip() for name in args.reviewer_classes.split(",")
                             if name.strip()) or ("human",)
    rstatus, rdetail = gate_human_review(fdetail["needs_human"],
                                         fdetail["reviewed_by_class"], min_review,
                                         classes=reviewer_classes,
                                         uncorroborated=fdetail.get(
                                             "uncorroborated_count", 0),
                                         panel_prompt_hashes=fdetail.get(
                                             "panel_prompt_hashes"))
    #: "谁裁的"和"裁到什么程度"是两件事：面板分歧的记录也算**复核过**（它带
    #: `source{models,prompt_sha256}`，满足 §4.1b 硬规则 2），但记录里写着
    #: `agreement:false` / `needs_human:true`。把这两个数并排放出来，免得
    #: "已复核 176 条"被读成"176 条都裁定了"。
    rdetail["panel_agreement_split"] = dict(fdetail.get("panel_agreement_split") or {})
    statuses.append(rstatus)
    report["gate_7_human_review"] = {"status": rstatus, **rdetail}

    extractor_family = args.extractor_family
    if not extractor_family and not args.extractor_manifest:
        # 默认自动发现仓库里的 manifest——抽取族是仓库产物，不该逼每个调用方
        # 再传一次；否则门⑧ 会永远停在 not_measured（硬规则 1 之下等于没判）。
        default_manifest = _ROOT / "knowledge" / "hypergraph.manifest.json"
        if default_manifest.is_file():
            args.extractor_manifest = str(default_manifest)
    if not extractor_family and args.extractor_manifest:
        try:
            man = json.loads(pathlib.Path(args.extractor_manifest).read_text(encoding="utf-8"))
            extractor_family = str((man.get("extractor") or {}).get("family") or "")
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"读不到 --extractor-manifest: {exc}"}, ensure_ascii=False))
            return 1
    istatus, idetail = gate_independence(entries, extractor_family)
    statuses.append(istatus)
    report["gate_8_independence"] = {"status": istatus, **idetail}

    if args.vocab:
        try:
            vocab, fingerprint = load_vocab(args.vocab, args.pilot)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(json.dumps({"error": f"读不到 --vocab {args.vocab}: {exc}"},
                             ensure_ascii=False))
            return 1
        if vocab is None:
            sstatus, sdetail = NA, {"reason": "词表没有 _fingerprint：无法与索引构建绑定"}
        else:
            sstatus, sdetail = gate_seed_coverage(fdetail["_parsed_q"], vocab,
                                                  must_values_from(entries), fingerprint,
                                                  min_support, support_from(entries))
    else:
        sstatus, sdetail = NA, {"reason": "未提供 --vocab"}
    statuses.append(sstatus)
    report["gate_3_seed_coverage"] = {"status": sstatus, **sdetail}

    excluded_cards: List[str] = []
    if args.exclude_cards:
        try:
            scope = json.loads(pathlib.Path(args.exclude_cards).read_text(
                encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"读不到 --exclude-cards: {exc}"},
                             ensure_ascii=False))
            return 1
        # `excluded` 是当前口径（`tools/kb_fetch/card_scope_audit.py` 的
        # `scope/v3`：判据是"索引对该卡零条边"，确定性）；`out_of_scope` 是旧键名，
        # 两个都认，免得读旧产物时静默变空集。
        if isinstance(scope, dict):
            payload = scope.get("excluded")
            if payload is None:
                payload = scope.get("out_of_scope") or []
            excluded_cards = [str(item) for item in payload]
        else:
            excluded_cards = [str(item) for item in scope]
    if args.cards:
        try:
            cards = json.loads(pathlib.Path(args.cards).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"error": f"读不到 --cards {args.cards}: {exc}"},
                             ensure_ascii=False))
            return 1
        if not isinstance(cards, list) or not cards or not all(
                isinstance(c, str) for c in cards):
            print(json.dumps({"error": "--cards 必须是非空的卡片 id 字符串数组"},
                             ensure_ascii=False))
            return 1
        cstatus, cdetail = gate_sources(entries, cards, excluded_cards)
    else:
        cstatus, cdetail = NA, {"reason": "未提供 --cards"}
    statuses.append(cstatus)
    report["gate_6_sources"] = {"status": cstatus, **cdetail}

    # 门⑩：期望边必须能从它自己的 q 检出（协议 §3.1）。不需要任何外部输入。
    rstatus, rdetail = gate_reachability(entries)
    statuses.append(rstatus)
    report["gate_9_reachability"] = {"status": rstatus, **rdetail}

    # 门⑪：must/top1/never 必须映射到当前索引里的边（§2.3 Q6b 前置①）。
    # 索引是仓库产物，默认自动发现；确实读不到时记 not_measured，不得判通过。
    nodes_path = args.nodes or str(_ROOT / "knowledge" / "hypergraph.nodes.jsonl")
    edges_path = args.edges or str(_ROOT / "knowledge" / "hypergraph.edges.jsonl")
    if not (pathlib.Path(nodes_path).is_file() and pathlib.Path(edges_path).is_file()):
        xstatus, xdetail = NA, {"reason": "索引缺失，无法判 required 边是否存在",
                                "nodes": nodes_path, "edges": edges_path}
    else:
        xstatus, xdetail = gate_index_resolvable(
            entries, load_index(nodes_path, edges_path),
            getattr(args, "expectation_relation", "exact"))
    statuses.append(xstatus)
    report["gate_10_index_resolvable"] = {"status": xstatus, **xdetail}

    report["overall"] = FAIL if FAIL in statuses else (NA if NA in statuses else PASS)
    if args.out:
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for key, value in report.items():
            if isinstance(value, dict) and "status" in value:
                print(f"[{value['status']:>13}] {key}")
        print(json.dumps({k: v for k, v in report.items() if not isinstance(v, dict)},
                         ensure_ascii=False))
        print(f"overall: {report['overall']}")
    return 0 if report["overall"] == PASS else (2 if report["overall"] == NA else 1)


def must_values_from(entries: Sequence[dict]) -> Dict[str, set]:
    """Every value that appears in a `must`/`never` slot, per kind."""
    out: Dict[str, set] = {}
    for record in entries:
        for spec in list(record.get("must") or []) + list(record.get("never") or []):
            try:
                _etype, plain, forbid = parse_spec(spec)
            except EntryError:
                continue
            for kind, value in list(plain.items()) + list(forbid.items()):
                out.setdefault(kind, set()).add(value)
    return out


def support_from(entries: Sequence[dict]) -> Dict[str, Dict[str, set]]:
    """kind -> value -> set of (card, query) pairs that used it (for the support gate)."""
    out: Dict[str, Dict[str, set]] = {}
    for record in entries:
        try:
            q = parse_q(record.get("q", ""))
        except EntryError:
            continue
        card = str(record.get("from_card"))
        qsig = tuple(sorted(q.items()))
        for key, value in q.items():
            out.setdefault(Q_KEY_TO_KIND[key], {}).setdefault(value, set()).add((card, qsig))
    return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
