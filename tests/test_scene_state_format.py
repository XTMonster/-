"""§7.3 场景状态摘要的纯计算测试。"""

from __future__ import annotations

from block_director.observation.state import (
    CameraState,
    CharacterState,
    SceneState,
    format_scene_state,
)


def _state(detailed: bool = False) -> SceneState:
    return SceneState(
        frame=24, total_frames=216,
        current_shot_id="shot_001", current_camera_id="BD_Cam_shot_001",
        detailed=detailed,
        camera=CameraState(id="BD_Cam_shot_001", shot_id="shot_001",
                           shot_type="MS", position=(0.0, 3.951, 1.05),
                           target=(0.0, 0.0, 1.0), lens=50.0,
                           composition_score=(88.0 if detailed else None),
                           visible_characters=["char_001"] if detailed else []),
        characters=[
            CharacterState(id="char_001", name="小明",
                           position=(-0.75, 0.0, 0.0), facing=(0.0, 1.0, 0.0),
                           in_frame=True if detailed else None,
                           screen_position=(0.33, 0.62) if detailed else None,
                           height_fraction=0.42 if detailed else None),
            CharacterState(id="char_002", name="小红",
                           position=(0.75, 0.0, 0.0), facing=(0.0, 1.0, 0.0),
                           in_frame=False if detailed else None,
                           screen_position=(1.21, 0.62) if detailed else None,
                           height_fraction=0.40 if detailed else None,
                           occluded=False if detailed else None),
        ],
    )


def test_light_summary_has_header_and_entities():
    text = format_scene_state(_state())
    assert "帧 24/216" in text
    assert "shot_001" in text
    assert "相机 BD_Cam_shot_001（MS）" in text
    assert "char_001 小明" in text and "char_002 小红" in text


def test_light_summary_has_no_projection():
    text = format_scene_state(_state())
    # 提示语里会提到"屏幕投影"这个词，所以要断言的是"没有投影数值"
    assert "屏幕 (" not in text
    assert "在画" not in text
    assert "构图 " not in text
    assert "高度占比" not in text
    assert "check_visibility" in text      # 明确告诉模型去哪儿拿投影信息


def test_detailed_summary_includes_projection():
    text = format_scene_state(_state(detailed=True))
    assert "屏幕 (0.33, 0.62)" in text
    assert "高度占比 0.42" in text
    assert "构图 88.0" in text
    assert "可见 char_001" in text


def test_out_of_frame_character_is_emphasised():
    assert "**不在画**" in format_scene_state(_state(detailed=True))


def test_occluded_character_is_flagged():
    state = _state(detailed=True)
    state.characters[0].occluded = True
    assert "**被遮挡**" in format_scene_state(state)


def test_empty_scene_is_described_not_crashed():
    text = format_scene_state(SceneState())
    assert "尚未设置" in text and "尚未放置" in text


def test_notes_are_surfaced():
    state = _state()
    state.notes.append("shot_002 机位被房间边界夹回")
    assert "注意：shot_002 机位被房间边界夹回" in format_scene_state(state)


def test_state_serialises_for_audit():
    data = _state(detailed=True).to_dict()
    assert data["current_shot_id"] == "shot_001"
    assert data["characters"][0]["screen_position"] == [0.33, 0.62]
    assert data["camera"]["composition_score"] == 88.0
