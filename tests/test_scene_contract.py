"""v1.4 P11 / BW-4b / F2：语义收敛层。

`SceneContract` 回答三个问题，而且都必须是**确定性**的：
谁看谁（``facing_target``）、谁在说话（``speaker_status``）、哪里没落实
（``unresolved[]``）。最要紧的一条是 F2：**说话人解析不出来时不许伪造
``character_id``**——宁可留空并标注 ``unresolved``，也不要把它安到一个
猜出来的角色头上。
"""

from __future__ import annotations

from block_director.contracts.brief import SceneBrief
from block_director.contracts.plan import Plan, ShotPlan
from block_director.knowledge.hypergraph import (
    HyperEdge,
    Hypergraph,
    Member,
    Node,
    parse_query,
)
from block_director.layer5_orchestrator.scene_contract import (
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    SceneContract,
    declared_constraint_query,
    resolve_speaker,
    shot_constraint_query,
)


def _plan() -> Plan:
    return Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "对峙", "shot_type": "MS",
         "duration_frames": 48, "characters": ["char_001", "char_002"],
         "dialogues": [{"character_id": "char_001", "text": "我先上船。"},
                       {"character_id": "char_009", "text": "等等。"}]},
        {"shot_id": "shot_002", "order": 2, "intent": "反应", "shot_type": "MCU",
         "duration_frames": 48, "characters": ["char_002"]},
    ]})


def _brief() -> SceneBrief:
    return SceneBrief.from_dict({
        "source": "model",
        "gaze": [{"from": "char_001", "to": "char_002", "scope": "shot_001"}],
    })


def test_facing_target_comes_from_the_brief():
    contract = SceneContract.from_plan(_plan(), brief=_brief())
    assert contract.shot("shot_001").facing_target == {"char_001": "char_002"}
    assert contract.shot("shot_002").facing_target == {}


def test_resolved_and_unresolved_speakers():
    contract = SceneContract.from_plan(_plan(), brief=_brief())
    first = contract.shot("shot_001")
    statuses = {item["speaker_raw"]: item["speaker_status"]
                for item in first.dialogues}
    assert statuses["char_001"] == STATUS_RESOLVED
    assert statuses["char_009"] == STATUS_UNRESOLVED


def test_unresolved_speaker_never_fakes_an_id():
    """F2 的负例：不许把认不出来的说话人安到某个角色头上。"""
    contract = SceneContract.from_plan(_plan(), brief=_brief())
    entry = next(item for item in contract.shot("shot_001").dialogues
                 if item["speaker_status"] == STATUS_UNRESOLVED)
    assert entry["speaker"] == ""
    assert contract.unresolved
    assert contract.unresolved[0]["shot_id"] == "shot_001"


def test_resolve_speaker_is_exact_match_only():
    assert resolve_speaker("char_001", ["char_001"]) == ("char_001",
                                                         STATUS_RESOLVED)
    assert resolve_speaker("她", ["char_001"]) == ("", STATUS_UNRESOLVED)
    assert resolve_speaker("", ["char_001"]) == ("", STATUS_UNRESOLVED)


def test_aliases_resolve_the_speaker():
    """``莉莉安娜（贵妇）`` 里的别名能落到正式 id 上（D-3 的消费侧）。"""
    class _Parsed:
        character_aliases = {"char_007": ["贵妇"]}

    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
         "duration_frames": 24, "characters": ["char_007"],
         "dialogues": [{"character_id": "贵妇", "text": "别管他。"}]}]})
    contract = SceneContract.from_plan(plan, parsed=_Parsed())
    entry = contract.shot("shot_001").dialogues[0]
    assert entry["speaker_status"] == STATUS_RESOLVED
    assert entry["speaker"] == "char_007"


def test_clean_contract_has_no_unresolved():
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
         "duration_frames": 24, "characters": ["char_001"],
         "dialogues": [{"character_id": "char_001", "text": "好。"}]}]})
    contract = SceneContract.from_plan(plan)
    assert contract.ok and contract.unresolved == []


# --------------------------------------------------------------------------- #
# v1.4 §2.3b 的检索路由：契约串的生产者
#
# 在它出现之前，`block_for_shot`/`block_for_plan` 拿到的是中文自由文本，而超图的
# 入口 `parse_query` **只认 `键=值`**——于是含 `forbid` 的那一栏在真实运行里
# 一个种子都命中不了，三栏里只剩两栏。这里把"生产 → 解析 → 命中"整条链钉住。
# --------------------------------------------------------------------------- #

def _query_shot() -> ShotPlan:
    return ShotPlan(shot_id="shot_007", intent="逼近", shot_type="MS",
                    duration_frames=48, order=7,
                    actions=[{"action_type": "跺脚"}],
                    dialogues=[{"character_id": "char_001", "text": "让开。"}],
                    vfx=[{"type": "flame"}],
                    camera={"lens": "85mm",
                            "movements": [{"type": "dolly_in"}]})


def test_the_constraint_query_uses_the_frozen_keys_and_skips_empty_values():
    query = shot_constraint_query(_query_shot())
    # **2026-10-02 改的是取值拼法，不是断言强度**：`对白=有` 里的"有"根本不在查询
    # 词表里（`scene_type` 的取值是 establish/dialogue/…），它是一个死值——命不中
    # 任何节点，还占掉 `q` 的一位；"这一镜有人说话"在词表里的说法是 `dialogue`。
    # 见 `tests/test_scene_contract_query_vocab.py` 的更强不变量：
    # **契约串里每个取值都必须能在入库索引的节点表里找到**。
    assert query == "景别=MS；镜头=85mm；运镜=dolly_in；动作=跺脚；特效=flame；对白=dialogue"
    # 空字段**不写**：`情绪=` 这种空值会造出永不命中的种子，把 `seed_miss`
    # 伪装成"知识库里没有"。
    bare = ShotPlan(shot_id="s", intent="x", shot_type="", duration_frames=24)
    assert shot_constraint_query(bare) == ""
    # 确定性：同一镜两次调用逐字符相同。
    assert shot_constraint_query(_query_shot()) == query


def test_the_contract_query_actually_seeds_the_hypergraph():
    nodes = [Node(node_id="shot_size:MS", type="shot_size", name="MS",
                  value="MS"),
             Node(node_id="intensity:high", type="intensity", name="high",
                  value="high"),
             Node(node_id="movement:固定机位", type="movement", name="固定机位",
                  aliases=("固定",))]
    edge = HyperEdge(type="SHOT_PATTERN", source_kind="theory", hardness="hard",
                     members=(Member("allow", "shot_size", "shot_size:MS"),
                              Member("qualifier", "intensity", "intensity:high"),
                              Member("forbid", "movement", "movement:固定机位")))
    graph = Hypergraph(nodes, [edge])
    query = shot_constraint_query(_query_shot())
    assert parse_query(query)["shot_size"] == ["MS"]
    selected, text, trace = graph.retrieve(query)
    assert trace.seed_miss is False and trace.seeds == ["shot_size:MS"]
    assert selected and "禁={" in text and "固定机位" in text


def test_the_two_query_producers_agree_without_drifting():
    """`ShotContract.constraint_query()` 与 `shot_constraint_query(ShotPlan)`
    必须逐字符一致——两条生产者漂了，检索路由就会一镜一个口径。

    **夹具必须长得像生产线**（2026-10-03 实测的教训）：这一条原先给的是
    `{"lens": "85mm"}` + 没有声明，而两条生产者在那样的输入下**必然**相等——
    于是"契约那条把浮点 `50.0` 原样发出（索引里是 `50mm` ⇒ 死值）、漏掉剧本
    声明的运镜、不折 `static→固定`"这三个真缺陷一个都没被它挡住。
    现在用的都是真实形状：`lens` 是**浮点**（`shots.json` 实测 `50.0`）、
    `declared_camera_move` 是引擎名（`static`，查询词表里要折成 `固定`）。
    """
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_007", "order": 7, "intent": "逼近", "shot_type": "MS",
         "duration_frames": 48, "characters": ["char_001"],
         "declared_camera_move": "static",
         "actions": [{"action_type": "跺脚"}],
         "dialogues": [{"character_id": "char_001", "text": "让开。"}],
         "vfx": [{"type": "flame"}],
         "camera": {"lens": 50.0, "movements": [{"type": "dolly_in"}]}}]})
    contract = SceneContract.from_plan(plan)
    assert (contract.shot("shot_007").constraint_query()
            == shot_constraint_query(plan.shots[0]))
    # 逐字段钉住：声明先进串并折成查询词表的 `固定`、焦距折成 `50mm`（不是 `50.0`）。
    query = shot_constraint_query(plan.shots[0])
    assert "运镜=固定" in query and "static" not in query
    assert "镜头=50mm" in query and "50.0" not in query


def test_the_plan_scope_query_comes_from_the_declared_shot_list():
    """计划阶段没有计划，但剧本里有**声明**（镜别/手法）——那也能拼契约串。"""
    from block_director.layer1_input.model import ParsedShotDeclaration

    declared = [
        ParsedShotDeclaration(shot_number=1, shot_type="MS", camera_move="dolly_in"),
        ParsedShotDeclaration(shot_number=2, shot_type="CU", camera_move="固定"),
        ParsedShotDeclaration(shot_number=3),          # 什么都没声明：不猜
    ]
    query = declared_constraint_query(declared, per_kind=1)
    assert query == "景别=MS；运镜=dolly_in"
    assert declared_constraint_query([]) == ""
    # 摘要（自由文本）拼在后面时，`parse_query` 仍然只认 `键=值` 的片段。
    combined = f"{query}；两人在厨房争吵"
    assert parse_query(combined)["shot_size"] == ["MS"]
