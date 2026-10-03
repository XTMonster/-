"""Q5 的"计划形状"必须与**真实生产者**对拍。

`tools/holdout_expect_movements.py` 的抬头点名了本文件："两处不一致时测试当场红"——
而它**从来没有存在过**（2026-10-03 用 `rg` 全仓查过：只有那句注释命中）。
于是"引擎到底能发哪些键"这件事在三处各写一份（`scene_contract.QUERY_KEYS`、
`tools/holdout_expect_movements.PLAN_QUERY_KEYS`、`tools/knowledge/quality.PLAN_QUERY_KEYS`），
没有任何一处与真正的生产者对拍——这正是本项目已经付过两次代价的"各抄一份"形状
（v1.5 的 6 类型/16 kind 漂移、v1.6 的查询键漂移）。

这组用例钉三件事：

* 三处声明**互相一致**，且**等于 `shot_constraint_query()` 真正会产出的键集**；
* 夹具里带 `expect_movements` 的条目**全都**是计划形状（工具的选择规则没有失效）；
* Q5 的 join 在**结构上**是否还够得着——以及够得着的那一族有没有被标注。
  最后一条是"下一步该干什么"的机器可读版本：全族都没标时它不会假装通过，
  但它**不**把 Q5 判成绿（那是 `quality.py` 的事）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator import scene_contract as SC  # noqa: E402
from tools.holdout_expect_movements import (  # noqa: E402
    PLAN_QUERY_KEYS as TOOL_QUERY_KEYS,
    plan_shape,
)
from tools.knowledge.quality import PLAN_QUERY_KEYS as QUALITY_QUERY_KEYS  # noqa: E402

HOLDOUT = ROOT / "fixtures" / "knowledge_holdout.jsonl"


def _keys(query: str) -> frozenset:
    return frozenset(part.split("=", 1)[0].strip()
                     for part in str(query).split("；") if "=" in part)


def _probe_shot(**overrides):
    """一个**每个字段都有值**的假镜头：把生产者的键集撑到最大。"""

    class Shot:
        shot_type = "MS"
        intent_type = "铺垫"
        declared_camera_move = "dolly_in"
        camera = {"lens": 50.0, "movements": [{"type": "follow_subject"}]}
        actions = [{"action_type": "walk"}]
        vfx = [{"type": "flame"}]
        dialogues = [{"text": "走。", "character_id": "char_001"}]

    for key, value in overrides.items():
        setattr(Shot, key, value)
    return Shot()


def _entries():
    return [json.loads(line) for line in
            HOLDOUT.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_three_declarations_agree():
    """三处声明必须逐字一致——它们说的是同一件事实。"""
    assert tuple(TOOL_QUERY_KEYS) == tuple(QUALITY_QUERY_KEYS), (
        "tools/holdout_expect_movements.py 与 tools/knowledge/quality.py 的 "
        "PLAN_QUERY_KEYS 漂了")
    assert set(SC.QUERY_KEYS) >= set(TOOL_QUERY_KEYS), (
        "`scene_contract.QUERY_KEYS` 是查询键的声明表，必须覆盖生产者的键集")


def test_the_declared_key_set_equals_what_the_producer_really_emits():
    """核心断言：**声明的键集 == 真实生产者会产出的键集**。

    这一条才是"两处不一致时当场红"的实现。它两边都掐：

    * 生产者**多**发一个键（比如将来加 `节奏=`）而声明没跟上 → 红；
    * 声明里写着一个生产者**永远发不出**的键（`PLAN_QUERY_KEYS` 变宽）→ 红。

    反向对照在 :func:`test_a_key_the_producer_cannot_emit_is_not_declared`。
    """
    emitted = _keys(SC.shot_constraint_query(_probe_shot()))
    assert emitted == set(TOOL_QUERY_KEYS), (
        f"生产者发的是 {sorted(emitted)}，声明的是 {sorted(TOOL_QUERY_KEYS)}")
    # 同一镜的两条生产者必须逐字符同源（§40 的纪律）。
    contract = SC.SceneContract.from_plan(_plan_with(_probe_shot()))
    assert contract.shots[0].constraint_query() == \
        SC.shot_constraint_query(_probe_shot())


def _plan_with(shot):
    from block_director.contracts.plan import Plan, ShotPlan

    return Plan(shots=[ShotPlan(shot_id="shot_001", order=1, intent="铺垫",
                                duration_frames=24, shot_type="MS",
                                intent_type="铺垫",
                                declared_camera_move="dolly_in",
                                camera=dict(shot.camera),
                                actions=[dict(item) for item in shot.actions],
                                vfx=[dict(item) for item in shot.vfx],
                                dialogues=[dict(item) for item in shot.dialogues])])


def test_a_key_the_producer_cannot_emit_is_not_declared():
    """反向对照：把镜头上的某个字段清空，对应的键就**不该**出现。

    没有这一条，"声明 == 生产者"可以靠"声明把生产者的全集抄一遍"满足，
    却证明不了"空值不写键"（空值凭空加键会把 `seed_miss` 伪装成"知识库里没有"）。
    """
    bare = _probe_shot(shot_type="CU", intent_type="", declared_camera_move="",
                       camera={}, actions=[], vfx=[], dialogues=[])
    assert SC.shot_constraint_query(bare) == "景别=CU"


def test_every_annotated_entry_is_plan_shaped():
    """工具的选择规则（`plan_shape`）在**入库夹具**上必须成立。"""
    annotated = [entry for entry in _entries() if entry.get("expect_movements")]
    assert len(annotated) >= 30, "§4.1b 第一步：带 expect_movements 的条目 ≥ 30"
    bad = [entry["id"] for entry in annotated if not plan_shape(entry)]
    assert not bad, f"这些条目的 q 键集不在计划可表达空间里：{bad[:5]}"


def test_at_least_one_annotatable_family_can_join_the_emitted_query():
    """Q5 的 join **在结构上**必须还有出路，而且那条出路要写清楚。

    历史（`ACCEPTANCE_STATUS.md` §38）：加意图轴之前，发出串是 `{景别, 运镜}`，
    而带 `expect_movements` 的 70 条 `q` 是 `{景别,运镜,镜头}`——**没有任何一族**
    能与发出串相等，Q5 的分母结构性为 0（§38.2 的"两条规则互斥"）。
    §50 之后发出串带上 `意图=`，`{意图,景别,运镜}` 这一族（176 条 `INTENT_PACK`）
    才第一次成为**可 join** 的。

    这条断言的是"出路存在"：能 join 的族**至少有一族**、且它们全部是计划形状
    （⇒ 可以用 `holdout_expect_movements.py` 补标注）。至于**那一族标了没有**，
    由下面那条用例如实报出来 —— 本文件不替 `quality.py` 判 Q5 的绿红。
    """
    emitted = _keys(SC.shot_constraint_query(
        _probe_shot(camera={}, actions=[], vfx=[], dialogues=[])))
    entries = _entries()
    joinable = [entry for entry in entries if _keys(entry.get("q")) == emitted]
    assert joinable, (
        f"没有任何条目的 q 键集等于发出串的键集 {sorted(emitted)}："
        f"Q5 的运行侧在结构上不可达（§38 的死结又回来了）")
    assert all(plan_shape(entry) for entry in joinable)


def test_which_joinable_entries_still_lack_expect_movements_is_recorded():
    """**如实报数**：可 join 的那一族里有多少条已经带 `expect_movements`。

    为 0 时这条用例**仍然通过**（这不是判据，是记账）——它保证这个数字一旦变化
    （比如标注轮真的落地了）就会被读出来，而不会有人以为"Q5 早就可测了"。
    计划形状**但不**可 join 的族（`{景别,运镜,镜头}`，带 `expect_movements` 的 70 条）
    也一并数出来：它们是 §38/§50 那条"两族互斥"的直接证据。
    """
    emitted = _keys(SC.shot_constraint_query(
        _probe_shot(camera={}, actions=[], vfx=[], dialogues=[])))
    entries = _entries()
    joinable = [entry for entry in entries if _keys(entry.get("q")) == emitted]
    annotated = [entry for entry in entries if entry.get("expect_movements")]
    annotated_keys = {_keys(entry.get("q")) for entry in annotated}
    facts = {
        "emitted_keys": sorted(emitted),
        "joinable_entries": len(joinable),
        "joinable_annotated": sum(1 for entry in joinable
                                  if entry.get("expect_movements")),
        "annotated_keys": sorted(tuple(sorted(keys)) for keys in annotated_keys),
    }
    assert facts["joinable_entries"] > 0
    assert facts["annotated_keys"], facts
    # 带标注的那一族**必须**与发出串不同——相同就说明这条用例的前提过期了，
    # 那时 Q5 的运行侧应当已经有非零分母（去 `knowledge_quality.json` 里对）。
    assert tuple(sorted(emitted)) not in facts["annotated_keys"], facts
