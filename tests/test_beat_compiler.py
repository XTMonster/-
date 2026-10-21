"""拍点 → actions 的编译（执行文档 v1.5 §4.1/§4.2；卡 P3-T1）。

五条必须钉住：t→帧换算、同角色同层串行且跨层并行、对白窗口、
**起点接力**（§六十四）、以及"锚点解析不出来就记 problem 且**不猜坐标**"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator.beat_compiler import (  # noqa: E402
    BEAT_DURATION_TABLE,
    WALK_METRES_PER_FRAME,
    compile_beats,
    merge_with_actions,
)

FIXTURE = ROOT / "fixtures" / "mock_llm_responses" / "drafts_simple.json"


def _shot(beats, *, duration=96, shot_id="shot_001", dialogues=None):
    """一个**鸭子类型**的镜头。

    刻意不用 ``ShotPlan``：``ShotPlan.beats`` 由卡 P2-T2 落地，而编译器只读
    ``shot_id`` / ``duration_frames`` / ``characters`` / ``beats`` /
    ``dialogues`` 这几个属性——用真实类型会让这张卡**绑死**在另一张卡的进度上
    （卡 P2-T2 的验收另有其测试）。
    """

    class _Shot:
        pass

    shot = _Shot()
    shot.shot_id = shot_id
    shot.intent = "x"
    shot.shot_type = "MS"
    shot.duration_frames = duration
    shot.characters = ["char_001", "char_002"]
    shot.beats = list(beats)
    shot.dialogues = list(dialogues or [])
    return shot


def _beat(t, subject, verb, **kwargs):
    payload = {"t": t, "subject": subject, "verb": verb}
    payload.update(kwargs)
    return payload


# --------------------------------------------------------------------------- #
# t → 帧
# --------------------------------------------------------------------------- #
def test_t_is_converted_to_frames_and_the_window_is_clamped_into_the_shot():
    shot = _shot([_beat(0.5, "char_001", "nod")], duration=100)
    actions, problems = compile_beats(shot)
    assert problems == []
    assert actions[0]["start_frame"] == 50
    assert (actions[0]["end_frame"] - actions[0]["start_frame"] + 1) == \
        BEAT_DURATION_TABLE["nod"]
    assert actions[0]["end_frame"] <= 100


def test_walk_duration_is_estimated_from_the_distance_not_a_fixed_table():
    shot = _shot([_beat(0.0, "char_001", "walk_to", target="door")], duration=200)
    anchors = {"door": [4.0, 0.0, 0.0]}
    cast = {"char_001": [0.0, 0.0, 0.0]}
    actions, problems = compile_beats(shot, anchors, cast)
    assert problems == []
    walk = actions[0]
    expected = round(4.0 / WALK_METRES_PER_FRAME)
    assert walk["end_frame"] - walk["start_frame"] + 1 == expected
    assert walk["params"]["target_position"] == [4.0, 0.0, 0.0]
    assert walk["params"]["from"] == [0.0, 0.0, 0.0]


def test_a_walk_window_never_runs_past_the_shot():
    shot = _shot([_beat(0.9, "char_001", "walk_to", target="door")], duration=40)
    actions, _problems = compile_beats(shot, {"door": [30.0, 0.0, 0.0]},
                                       {"char_001": [0.0, 0.0, 0.0]})
    assert actions[0]["end_frame"] <= 40


# --------------------------------------------------------------------------- #
# 起点接力
# --------------------------------------------------------------------------- #
def test_the_walk_start_is_the_current_position_not_the_script_origin():
    """§六十四：缺省起点 = 角色**当前位置**，不是剧本起始站位。"""
    shot = _shot([_beat(0.0, "char_001", "walk_to", target="door")])
    anchors = {"door": [2.0, 0.0, 0.0]}
    script_origin = {"char_001": [0.0, 0.0, 0.0]}
    actions, _problems = compile_beats(shot, anchors, script_origin,
                                       current_positions={"char_001":
                                                          [8.0, -1.0, 0.0]})
    assert actions[0]["params"]["from"] == [8.0, -1.0, 0.0]


def test_exit_frame_starts_where_the_character_is():
    shot = _shot([_beat(0.2, "char_002", "exit_frame", target="offstage")])
    anchors = {"offstage": [12.0, 0.0, 0.0]}
    cast = {"char_002": [-3.0, 0.0, 0.0]}
    actions, problems = compile_beats(shot, anchors, cast)
    assert problems == []
    assert actions[0]["action_type"] == "walk_to", "语义动词编译成 walk_to"
    assert actions[0]["params"]["from"] == [-3.0, 0.0, 0.0]
    assert actions[0]["params"]["target_position"] == [12.0, 0.0, 0.0]


# --------------------------------------------------------------------------- #
# face_to
# --------------------------------------------------------------------------- #
def test_face_to_a_character_adds_a_look_at_with_real_geometry():
    shot = _shot([_beat(0.0, "char_001", "nod", face_to="char_002")])
    cast = {"char_001": {"position": [0.0, 0.0, 0.0],
                         "facing": [1.0, 0.0, 0.0]},
            "char_002": {"position": [0.0, 3.0, 0.0]}}
    actions, problems = compile_beats(shot, None, cast)
    look = next(item for item in actions if item["action_type"] == "look_at")
    # 站在原点、面朝 +X，目标在 +Y ⇒ 相对身体转 +90°（head_track_angles 的约定）
    assert look["params"]["yaw_deg"] == 90.0
    assert problems == []


def test_face_to_a_screen_direction_uses_a_fixed_yaw():
    shot = _shot([_beat(0.0, "char_001", "turn_head", face_to="screen_right")])
    actions, problems = compile_beats(shot)
    look = next(item for item in actions if item["action_type"] == "look_at")
    assert look["params"]["yaw_deg"] > 0
    # 头层一次只有一条动作：`face_to` 排在 `turn_head` **之后**，不叠帧、不报重叠。
    turn = next(item for item in actions if item["action_type"] == "turn_head")
    assert look["start_frame"] > turn["end_frame"]
    assert problems == []


def test_face_to_folds_into_the_look_at_verb_instead_of_adding_a_second_one():
    """`look_at` + `face_to` 只产出**一条** look_at（face_to 是它的参数）。"""
    shot = _shot([_beat(0.0, "char_001", "look_at", face_to="screen_left")])
    actions, problems = compile_beats(shot)
    assert [item["action_type"] for item in actions] == ["look_at"]
    assert actions[0]["params"]["yaw_deg"] < 0
    assert problems == []


def test_face_to_an_unknown_character_records_a_problem_and_does_not_guess():
    shot = _shot([_beat(0.0, "char_001", "nod", face_to="char_009")])
    actions, problems = compile_beats(shot)
    assert any("不猜朝向" in item for item in problems)
    assert [item["action_type"] for item in actions] == ["nod"]


# --------------------------------------------------------------------------- #
# 道具交互
# --------------------------------------------------------------------------- #
def test_prop_verbs_pass_through_with_the_prop_name():
    shot = _shot([_beat(0.1, "char_001", "pick_up", target="lamp")])
    actions, problems = compile_beats(shot)
    assert problems == []
    assert actions[0]["action_type"] == "pick_up"
    assert actions[0]["params"]["prop"] == "lamp"


# --------------------------------------------------------------------------- #
# 不猜：锚点/目标解析不出来
# --------------------------------------------------------------------------- #
def test_an_unresolvable_target_is_reported_and_the_beat_is_skipped():
    shot = _shot([_beat(0.3, "char_001", "walk_to", target="ghost_anchor")])
    actions, problems = compile_beats(shot, {"door": [1.0, 0.0, 0.0]},
                                      {"char_001": [0.0, 0.0, 0.0]})
    assert actions == []
    assert any("不猜坐标" in item for item in problems)


def test_an_empty_target_is_not_invented():
    """没有 target 就是"不想动"：落在角色当前位置，绝不编一个目的地。"""
    shot = _shot([_beat(0.0, "char_001", "walk_to")])
    actions, problems = compile_beats(shot, None, {"char_001": [1.5, 2.5, 0.0]})
    assert problems == []
    assert actions[0]["params"]["target_position"] == [1.5, 2.5, 0.0]
    assert actions[0]["params"]["from"] == [1.5, 2.5, 0.0]


# --------------------------------------------------------------------------- #
# 同角色按层仲裁
# --------------------------------------------------------------------------- #
def test_overlapping_actions_for_one_subject_are_pushed_apart_and_recorded():
    shot = _shot([_beat(0.0, "char_001", "nod"),
                  _beat(0.01, "char_001", "shake_head")], duration=96)
    actions, problems = compile_beats(shot)
    nod = next(item for item in actions if item["action_type"] == "nod")
    shake = next(item for item in actions
                 if item["action_type"] == "shake_head")
    assert shake["start_frame"] > nod["end_frame"], (
        "同角色同 head 层的动作必须串行")
    assert any("串行" in item for item in problems)


def test_actions_on_different_layers_of_one_subject_may_overlap():
    shot = _shot([_beat(0.1, "char_001", "sit"),
                  _beat(0.1, "char_001", "nod")], duration=96)
    actions, problems = compile_beats(shot)
    sit = next(item for item in actions if item["action_type"] == "sit")
    nod = next(item for item in actions if item["action_type"] == "nod")
    assert sit["start_frame"] == nod["start_frame"]
    assert not any("同层动作时间重叠" in item for item in problems)


def test_root_motion_and_head_performance_can_overlap():
    shot = _shot([_beat(0.2, "char_001", "walk_to", target="door"),
                  _beat(0.2, "char_001", "nod")], duration=96)
    actions, problems = compile_beats(
        shot, {"door": [2.0, 0.0, 0.0]},
        {"char_001": [0.0, 0.0, 0.0]})
    walk = next(item for item in actions if item["action_type"] == "walk_to")
    nod = next(item for item in actions if item["action_type"] == "nod")
    assert walk["start_frame"] == nod["start_frame"]
    assert not any("同层动作时间重叠" in item for item in problems)


# --------------------------------------------------------------------------- #
# 对白窗口
# --------------------------------------------------------------------------- #
def test_a_beat_covering_the_speakers_whole_dialogue_window_is_flagged():
    dialogues = [{"character_id": "char_001", "text": "走。",
                  "start_frame": 1, "end_frame": 48}]
    shot = _shot([_beat(0.0, "char_001", "walk_to", target="door")],
                 duration=96, dialogues=dialogues)
    actions, problems = compile_beats(shot, {"door": [5.0, 0.0, 0.0]},
                                      {"char_001": [0.0, 0.0, 0.0]})
    assert actions[0]["start_frame"] <= 1 and actions[0]["end_frame"] >= 48
    assert any("对白窗" in item for item in problems)


def test_a_partial_overlap_with_dialogue_is_not_flagged():
    dialogues = [{"character_id": "char_001", "text": "走。",
                  "start_frame": 40, "end_frame": 90}]
    shot = _shot([_beat(0.0, "char_001", "nod")], duration=96,
                 dialogues=dialogues)
    _actions, problems = compile_beats(shot)
    assert not any("对白窗" in item for item in problems)


# --------------------------------------------------------------------------- #
# 合并（§4.2）
# --------------------------------------------------------------------------- #
def test_compiled_wins_over_an_overlapping_written_duplicate():
    compiled = [{"character_id": "c", "action_type": "nod",
                 "start_frame": 1, "end_frame": 12}]
    written = [{"character_id": "c", "action_type": "nod",
                "start_frame": 2, "end_frame": 13},
               {"character_id": "c", "action_type": "sit",
                "start_frame": 20, "end_frame": 40}]
    merged = merge_with_actions(compiled, written)
    assert [item["action_type"] for item in merged] == ["nod", "sit"]
    assert merged[0]["start_frame"] == 1, "重复时以编译结果为准"


def test_non_duplicates_are_kept_as_is():
    compiled = [{"character_id": "c", "action_type": "nod",
                 "start_frame": 1, "end_frame": 12}]
    written = [{"character_id": "d", "action_type": "nod",
                "start_frame": 1, "end_frame": 12}]
    merged = merge_with_actions(compiled, written)
    assert len(merged) == 2


# --------------------------------------------------------------------------- #
# 形状兼容
# --------------------------------------------------------------------------- #
def test_the_compiled_shape_matches_the_existing_actions_fixture():
    """输出形状必须与既有 `actions[]` **逐字段兼容**（下游一行都不用改）。"""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    written_keys = set()
    for draft in fixture["drafts"]:
        for action in draft.get("actions", []):
            written_keys |= set(action)
    assert written_keys, "夹具里没有动作，这条断言就没有意义"
    shot = _shot([_beat(0.0, "char_001", "walk_to", target="door"),
                  _beat(0.2, "char_002", "nod", face_to="screen_left")],
                 duration=96)
    actions, _problems = compile_beats(shot, {"door": [2.0, 0.0, 0.0]},
                                       {"char_001": [0.0, 0.0, 0.0],
                                        "char_002": [1.0, 1.0, 0.0]})
    for action in actions:
        assert set(action) <= written_keys | {"target_position"}, (
            f"编译出的键 {sorted(action)} 超出了既有 actions[] 的形状")
    assert {"character_id", "action_type", "start_frame", "end_frame"} <= \
        set(actions[0])


def test_compilation_is_deterministic():
    shot = _shot([_beat(0.1, "char_001", "nod"),
                  _beat(0.1, "char_001", "look_at", face_to="screen_left")])
    assert compile_beats(shot) == compile_beats(shot)


def test_a_shot_without_beats_compiles_to_nothing():
    assert compile_beats(_shot([])) == ([], [])
