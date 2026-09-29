"""v1.4 P11 / BW-4b / F2：语义收敛层。

`SceneContract` 回答三个问题，而且都必须是**确定性**的：
谁看谁（``facing_target``）、谁在说话（``speaker_status``）、哪里没落实
（``unresolved[]``）。最要紧的一条是 F2：**说话人解析不出来时不许伪造
``character_id``**——宁可留空并标注 ``unresolved``，也不要把它安到一个
猜出来的角色头上。
"""

from __future__ import annotations

from block_director.contracts.brief import SceneBrief
from block_director.contracts.plan import Plan
from block_director.layer5_orchestrator.scene_contract import (
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    SceneContract,
    resolve_speaker,
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
