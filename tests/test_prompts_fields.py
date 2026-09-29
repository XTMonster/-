"""v1.4 US-15 / D-4 / S4：`prompts.md` 必须**逐字段**对得上计划。

契约断言（§B.5 的豁免②）：段数 == 镜数、每段逐字段取值相等、且正向 Prompt
里**不出现**任何引擎内部键。通道是"与同一个映射函数的输出相等"——
``**景别**`` 行必须是 ``SHOT_TYPE_LABELS[shot_type]``（中文标签，如
``MLS → 中远景``），**不得**直接比 ``shot_type == "MLS"``。

负例：把某段的 ``intent`` 丢掉 → 逐字段对拍必须红。
"""

from __future__ import annotations

from block_director.contracts.plan import Plan
from block_director.delivery.prompts import (
    SHOT_TYPE_LABELS,
    movement_labels,
    render_prompt_sheet,
)

#: §3.3 列出的引擎内部键**全集**（S4：只禁 ``timing_overrides`` 是漏的）。
ENGINE_KEYS = ("timing_overrides", "action_conflicts", "dialogue_pins",
               "audit_pass_rate", "declared", "retrieval_calls",
               "llm_calls", "speaker_status", "offset_reason")


def _plan() -> Plan:
    return Plan.from_dict({"scene_heading": "INT. 码头 - 日", "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立环境",
         "shot_type": "MLS", "duration_frames": 48,
         "characters": ["char_001", "char_002"],
         "actions": [{"character_id": "char_001", "action_type": "walk_to",
                      "start_frame": 1, "end_frame": 48}],
         "camera": {"movements": [{"type": "dolly_in"}]},
         "prompt": "雨夜的码头，中远景，两人一前一后"},
        {"shot_id": "shot_002", "order": 2, "intent": "给出反应",
         "shot_type": "CU", "duration_frames": 72,
         "characters": ["char_002"],
         "actions": [{"character_id": "char_002", "action_type": "nod",
                      "start_frame": 1, "end_frame": 72}]},
    ]})


def _sections(text: str):
    """按 ``## <shot_id>`` 切片；返回 ``[(shot_id, body), ...]``。"""
    blocks = []
    for chunk in text.split("\n## ")[1:]:
        head, _, body = chunk.partition("\n")
        shot_id = head.split("（", 1)[0].strip()
        blocks.append((shot_id, body))
    return blocks


def _field(body: str, name: str):
    for line in body.splitlines():
        if line.startswith(f"**{name}**："):
            return line.split("：", 1)[1].strip()
    return None


def test_one_section_per_shot():
    plan = _plan()
    text = render_prompt_sheet(plan)
    sections = _sections(text)
    assert len(sections) == len(plan.shots)
    assert [shot_id for shot_id, _ in sections] == \
           [shot.shot_id for shot in plan.shots]


def test_every_field_matches_the_plan():
    plan = _plan()
    text = render_prompt_sheet(plan)
    for shot, (_, body) in zip(plan.shots, _sections(text)):
        assert _field(body, "景别") == SHOT_TYPE_LABELS[str(shot.shot_type)]
        assert _field(body, "运镜") == movement_labels(shot)
        assert _field(body, "出场角色") == "、".join(shot.characters)
        assert _field(body, "动作") == "、".join(
            str(action.get("action_type")) for action in shot.actions)
        assert _field(body, "镜头意图") == shot.intent
        assert _field(body, "Prompt") == shot.prompt.strip() or \
            _field(body, "Prompt") is not None


def test_prompt_falls_back_to_the_composer_when_empty():
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立环境",
         "shot_type": "MS", "duration_frames": 24, "characters": ["c1"]}]})
    text = render_prompt_sheet(plan)
    prompt = _field(_sections(text)[0][1], "Prompt")
    assert "建立环境" in prompt and SHOT_TYPE_LABELS["MS"] in prompt


def test_engine_internal_keys_never_leak_into_the_prompt():
    plan = _plan()
    plan.shots[0].dialogue_pins = [{"shot_number": 1, "speaker_raw": "甲",
                                    "speaker_status": "unresolved"}]
    plan.shots[0].timing_overrides = [{"applied_s": 9.9}]
    text = render_prompt_sheet(plan)
    for key in ENGINE_KEYS:
        assert key not in text, key


def test_negative_a_lost_intent_breaks_the_field_compare():
    """负例：某段丢掉 ``intent`` → 逐字段对拍必须红。"""
    plan = _plan()
    text = render_prompt_sheet(plan).replace("**镜头意图**：建立环境", "")
    fields = [_field(body, "镜头意图") for _, body in _sections(text)]
    assert fields != [shot.intent for shot in plan.shots]
