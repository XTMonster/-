"""成员落地判据（grounding）：一条边的成员，到底是不是卡片说的？

**唯一真源。** 两个消费者共用这里的原语，避免各抄一份：

* `tools/holdout_pool.grounded_conflict_pairs` —— 门⑤ 的「可断言冲突数」：
  `forbid` 成员在**自己的来源卡**里找得到理据的那些对；
* `tools/kb_fetch.build_hypergraph.unsupported_prohibition_hosts` —— 阶段二的
  **精确度门**：禁令必须有宿主。

为什么需要第二个：抽取提示的规则 4b 要求「卡里出现 *避免/不要* 时把那个取值写成
`forbid`」，并（在旧措辞里）点名挂在 `EMOTION_PACK` 上。于是一张**只讲运镜**的卡被
逼着补出 `emotion` 与 `intensity` 才能凑满必填槽位——**宿主是编出来的**。
实测（540 条边）：`gen_cine_0247`「摄影机始终处于某种运动中，避免长时间静止固定」
就是这样长出一条 `EMOTION_PACK:emotion=平静,intensity=low,forbid_movement=固定`。

**落地判据不能全局施加。** 按「每个成员都要在卡里逐字出现」去卡，会判掉
**538/540** 条边（抽取器本来就在做抽象：`beat_type=coverage`、`intensity=mid`
这类推断在卡里永远找不到字面）。所以真正可用的形态是**加条件**：
只在这条边是**某条禁令的宿主**时，才要求它的必填 `allow` 主体在卡里落地。
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence, Set

#: 否定词：卡里出现这些词，才认为「禁止某个取值」是**卡里写的**，不是抽取器编的。
NEGATION_CUES = ("不要", "避免", "切忌", "禁忌", "禁用", "别用", "不宜", "不能", "不可",
                 "禁止", "切勿", "杜绝", "avoid", "never", "don't", "do not",
                 "should not", "must not")


def value_of(node_id: str) -> str:
    """`kind:取值` → `取值`（与 `tools/holdout_pool.value_of` 同一口径）。"""
    return str(node_id).split(":", 1)[1] if ":" in str(node_id) else str(node_id)


def asserted_text(card: Dict) -> str:
    """一张卡**对外的全部文字**：标题、正文、关键词、标签。

    四段一起算，与门⑤ 的 `grounded_conflict_pairs` 同口径 —— 两个判据读同一张卡时
    必须看到同一份文字，否则「这条禁令有没有依据」会因为读的地方不同而给出两个答案。
    """
    parts = [str(card.get("title") or ""), str(card.get("content") or "")]
    for key in ("keywords", "tags"):
        value = card.get(key) or ()
        if isinstance(value, str):
            parts.append(value)
        else:
            parts.extend(str(item) for item in value)
    return " ".join(part for part in parts if part)


def surface_names(node_id: str, node: Optional[object] = None) -> Set[str]:
    """一个节点「能被文字写出来」的全部说法：取值、名字、别名。

    `node` 可以缺省（索引里引用了没有节点记录的悬空 id）——那时只认取值本身。
    """
    names = {value_of(node_id)}
    if node is not None:
        names.add(str(getattr(node, "name", "") or ""))
        names.add(str(getattr(node, "value", "") or ""))
        names.update(str(alias) for alias in (getattr(node, "aliases", ()) or ()))
    return {name for name in names if name}


def member_is_grounded(member, node: Optional[object], text: str) -> bool:
    """这条成员（`(role, kind, node_id)`）的取值/名字/别名有没有出现在 `text` 里。"""
    node_id = member[2] if isinstance(member, (tuple, list)) else str(member)
    return any(name in text for name in surface_names(node_id, node))


def has_negation_cue(text: str) -> bool:
    """卡里有没有「不要/避免/…」这类否定表述。"""
    return any(cue in text for cue in NEGATION_CUES)


def texts_for(sources: Iterable[str], cards_by_id: Dict[str, Dict]) -> str:
    """一张边引用的**全部**来源卡的文字拼起来（出处不能因为只看一张就丢）。"""
    return "\n".join(asserted_text(cards_by_id[str(source)])
                     for source in sources if str(source) in cards_by_id)


def required_allow_members(edge, required_slots: Sequence[Sequence[str]]):
    """这条边的**必填 `allow` 成员**（边的「主体」）。"""
    slots = {(str(role), str(kind)) for role, kind in required_slots}
    return [member for member in edge.members
            if member.role == "allow" and (member.role, member.kind) in slots]


def ungrounded_required_subjects(edge, required_slots: Sequence[Sequence[str]],
                                 nodes: Dict[str, object],
                                 text: str):
    """必填 `allow` 成员里，**一个说法都没在卡里出现过**的那些。"""
    return [member for member in required_allow_members(edge, required_slots)
            if not member_is_grounded(member, nodes.get(member.node_id), text)]


def grounded_forbids(edge, nodes: Dict[str, object], text: str):
    """`forbid` 成员里，取值/名字/别名**在卡里出现过**的那些。"""
    return [member for member in edge.members
            if member.role == "forbid"
            and member_is_grounded(member, nodes.get(member.node_id), text)]
