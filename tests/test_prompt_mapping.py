"""两条 prompt 都必须教"构图知识怎么落进六类边"——否则整域卡片会一条都产不出来。

实测教训（2026-09-30）：

* 抽取侧不教映射时，索引里 **0 条边**带 `composition_rule`；`composition` 域的
  170 张卡在标注侧也**一条都产不出**——模型的 `must` 里写 `COMPOSITION`／
  `COMPOSITION_RULE`，被 `bad_type` 整条拒收（最近 200 条 reject 里 188 条是这个）。
* 教了映射之后：抽取侧重跑得到 **97 个 `composition_rule` 成员**、
  标注侧 6 张构图卡一次调用 6 条全过。

这两条 prompt 是"知识能不能进索引/进 held-out"的开关，所以用测试钉住，
免得以后有人精简提示词时把这段删掉。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools import holdout_candidates, holdout_fill, holdout_review_llm  # noqa: E402
from tools import check_holdout  # noqa: E402
from tools.kb_fetch import build_hypergraph as bh  # noqa: E402
from tools.kb_fetch import holdout_gen  # noqa: E402

#: **单一真源**：类型清单从超图 schema 读，别再手抄一份（v1.5 扩到 13 类时正是
#: "测试抄了一份六类"把扩类卡住的）。
FROZEN_TYPES = tuple(hg.EDGE_TYPES)


def _drafting_prompts() -> dict:
    """每一条**会把 schema 写进正文**的开发侧提示（键集/槽位必须与 schema 同源）。"""
    card = {"id": "c1", "domain": "anime", "title": "t", "keywords": [], "content": "x"}
    return {
        "kb_fetch.holdout_gen.SYSTEM_PROMPT": holdout_gen.SYSTEM_PROMPT,
        "holdout_fill.GAP_PROMPT": holdout_fill.GAP_PROMPT,
        "holdout_candidates.prompt_for": holdout_candidates.prompt_for(card),
        "holdout_review_llm.SYSTEM": holdout_review_llm.SYSTEM,
    }


#: 一条"查询键清单"句子的形状：`键/键/键/…`，且至少 5 个 token 是真键。
#: 阈值取 5 是为了把正文里顺带出现的"构图/机位/动作/打击感/声画"这类**举例**排除掉，
#: 同时任何一条**真正的键清单**（17 个）都必然落进网里——那正是会漂的地方。
_KEY_RUN = re.compile(r"[\u4e00-\u9fff]{1,6}(?:[/／][\u4e00-\u9fff]{1,6}){4,}")
_MIN_KEYS_IN_A_RUN = 5


def _key_runs(text: str):
    for match in _KEY_RUN.finditer(text):
        run = [token for token in re.split(r"[/／]", match.group(0)) if token]
        if sum(1 for token in run if token in hg.QUERY_KEYS) >= _MIN_KEYS_IN_A_RUN:
            yield run


def _assert_prompt_is_renderable(name: str, text: str) -> None:
    """提示词必须与 schema 同构：类型齐、键齐、且键清单就是那一份冻结清单。"""
    for edge_type in FROZEN_TYPES:
        assert edge_type in text, f"{name} 少了边类型 {edge_type}"
    for key in hg.QUERY_KEYS:
        assert key in text, f"{name} 少了冻结查询键 {key}"
    assert check_holdout.query_key_text() in text, (
        f"{name} 里没有逐字出现冻结键清单——键必须由 "
        f"`check_holdout.query_key_text()` 渲染，不许手抄")
    for run in _key_runs(text):
        unknown = [token for token in run if token not in hg.QUERY_KEYS]
        assert not unknown, (
            f"{name} 的键清单里出现了协议里不存在的键 {unknown}——"
            f"`check_holdout.parse_q` 会把用到它们的条目整条拒收")


def test_extractor_prompt_names_every_frozen_type_and_the_composition_mapping():
    text = bh.SYSTEM_PROMPT
    for edge_type in FROZEN_TYPES:
        assert edge_type in text, f"抽取 prompt 少了边类型 {edge_type}"
    assert "composition_rule" in text, "构图知识点映射没写进抽取 prompt"
    assert "camera_angle" in text and "vfx" in text and "sfx" in text
    assert "forbid" in text


def test_annotator_prompt_names_every_frozen_type_and_the_composition_mapping():
    text = holdout_gen.SYSTEM_PROMPT
    for edge_type in FROZEN_TYPES:
        assert edge_type in text, f"标注 prompt 少了边类型 {edge_type}"
    assert "composition_rule" in text
    # 只允许冻结的那几类，且明确点名"不要发明 COMPOSITION／SHAKE 之类"
    assert ("COMPOSITION" in text or "SHAKE" in text) and "整条作废" in text


def test_gap_prompt_carries_the_same_mapping_rule():
    for edge_type in FROZEN_TYPES:
        assert edge_type in holdout_fill.GAP_PROMPT


def test_every_prompt_that_restates_the_schema_is_derived_from_it():
    """四份提示都必须与 schema 同源——**这是"第二份 schema"的机器闸**。

    历史缺陷（2026-10-01，实测）：

    * `holdout_fill.GAP_PROMPT` 手抄的是"六类 ＋ 16 键 ＋ `AXIS_RULE` 只写
      `pair`/`axis_side`"，与基础提示拼在一起时自相矛盾，模型照旧写不可达的边；
      在已交付的 oracle 上实测 `TRANSITION_PACK` **158/158 不可达**、
      `AXIS_RULE` 一个可锚槽位都没有；
    * `holdout_gen.SYSTEM_PROMPT` 一度手抄了一份**多出** `强度`/`头留白`/`平均镜长`
      的键清单，而 `parse_q` 只认冻结键集 → 用到它们的条目**整条作废**。
    """
    # 只有**写期望**的提示需要教"这条边怎么被锚上"；复核员只判合规，不写模板。
    prompts = _drafting_prompts()
    for name, text in prompts.items():
        _assert_prompt_is_renderable(name, text)


def _missing_slots_best(text: str, edge_type: str, window: int = 200):
    """**最少**缺几个必填槽位（逐处看 `edge_type:` 之后 `window` 字符）。

    提示里可以有多处提到同一类型（规则 0 的简写示例、rule 2 的模板、收尾的示例），
    只要**其中一处**把必填槽位写全就算教到了。一处都没有（旧 GAP_PROMPT 的 rule 2
    只写六类，另外七类没有任何模板）时，整列槽位都算缺。
    """
    slot_kinds = [kind for _role, kind in hg.REQUIRED_MEMBERS[edge_type]]
    best = list(slot_kinds)
    start = 0
    while True:
        index = text.find(edge_type + ":", start)
        if index < 0:
            break
        chunk = text[index:index + window]
        missing = [kind for kind in slot_kinds if kind not in chunk]
        if len(missing) < len(best):
            best = missing
        if not best:
            break
        start = index + 1
    return best


def test_drafting_prompts_spell_out_every_required_slot():
    """每类边的必填槽位必须写进模板——少一个槽位就是"必填写全"教不会。"""
    for name in ("kb_fetch.holdout_gen.SYSTEM_PROMPT", "holdout_fill.GAP_PROMPT",
                 "holdout_candidates.prompt_for"):
        text = _drafting_prompts()[name]
        for edge_type in FROZEN_TYPES:
            missing = _missing_slots_best(text, edge_type)
            assert not missing, f"{name} 的 {edge_type} 模板少了必填槽位 {missing}"


def _anchorable_kinds(edge_type: str):
    """这条边**能被查询锚上**的成员 kind（有查询键的那些）。"""
    members = list(hg.REQUIRED_MEMBERS[edge_type]) + list(
        hg.OPTIONAL_MEMBERS.get(edge_type, ()))
    return [kind for _role, kind in members if kind in check_holdout.QUERYABLE_KINDS]


def test_every_edge_type_has_a_query_anchor_and_the_prompts_say_so():
    """每类边必须至少有一个**有查询键**的成员，提示也必须把它写出来。

    这是 `AXIS_RULE` 与 `TRANSITION_PACK` 两次真实缺陷的机器闸：两者的必填槽位里
    都有"在查询空间里没有取值"的常量（`pair`/`axis_side`、`scene_type`），于是
    **整类边一个种子都挂不上**、召回恒为 0——实测 `TRANSITION_PACK` 在已交付的
    oracle 里 158/158 不可达，`AXIS_RULE` 263 条里只有 16 条能命中索引。
    """
    # 只有**写期望**的提示需要教"这条边怎么被锚上"；复核员只判合规，不写模板。
    prompts = {name: text for name, text in _drafting_prompts().items()
               if name != "holdout_review_llm.SYSTEM"}
    for edge_type in FROZEN_TYPES:
        anchorable = _anchorable_kinds(edge_type)
        assert anchorable, f"{edge_type} 没有任何可锚成员 —— schema 本身不可检索"
        for name, text in prompts.items():
            best = max(
                (sum(1 for kind in anchorable if kind in text[i:i + 200])
                 for i in range(len(text)) if text.startswith(edge_type + ":", i)),
                default=0)
            assert best >= 1, (
                f"{name} 没教 {edge_type} 怎么被查询锚上——它需要 {anchorable} 里至少一个")


def test_key_run_detector_actually_catches_a_hand_copied_list():
    """给上面的机器闸一个**对抗性**自检：坏清单必须被抓到，举例句必须不被误伤。"""
    # 追加的必须是**真不在** `QUERY_KEYS` 里的键：`强度` 在 v1.5 已经是真键，
    # 拿它当"手抄多出来的"会误报——而那正是探测器按 schema 判、判对了的表现。
    bad = "1. `q` 的键只能用：" + check_holdout.query_key_text() + "/头留白/平均镜长。"
    runs = list(_key_runs(bad))
    assert runs, "键清单没被识别出来，闸是空的"
    assert [token for run in runs for token in run if token not in hg.QUERY_KEYS] == \
        ["头留白", "平均镜长"]
    # 正文里顺带的举例（只有 3 个真键）必须**不**被判成键清单。
    assert not list(_key_runs("构图/机位/动作/打击感/声画知识优先选对应的新类型"))


def test_prompt_versions_are_non_empty_and_bumped():
    assert bh.PROMPT_VERSION.startswith("extract/")
    assert holdout_gen.PROMPT_VERSION.startswith("holdout/")
    assert holdout_fill.GAP_PROMPT_VERSION.startswith("holdout-gap/")
