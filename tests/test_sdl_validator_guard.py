"""v1.4 X2：SDL 校验器对坏数据必须**报 finding**，而不是抛异常。

SDL 是外部输入（旧工程、手改文件、别的工具写的）。v1.3 的
``int(entry.get("count") or 0)`` 与 ``int(move.get("end_frame") or span)``
遇到 "很多" / None 这类值会直接抛 ValueError，让加载整条挂掉。
"""

from __future__ import annotations

from block_director.contracts.sdl import (
    SDLProject,
    SDLScene,
    SDLShot,
)
from block_director.layer2_sdl import validate_sdl


def _project(scene_extra: dict, shots: list) -> SDLProject:
    """直接构造 SDLProject：坏数据往往连反序列化都过不去，校验器要单独测。"""
    from block_director.contracts.sdl import SDLEnvironment

    environment = SDLEnvironment(**{key: value
                                    for key, value in scene_extra.items()
                                    if key in ("walls", "props", "crowd")})
    scene = SDLScene(id="scene_001", number=1, heading="INT. 坏数据 - 日",
                     environment=environment,
                     shots=[SDLShot(**shot) for shot in shots])
    return SDLProject(name="坏数据", version="1.4", fps=24, characters=[],
                      scenes=[scene])


def _shot(**extra) -> dict:
    payload = {"id": "shot_001", "intent": "x", "shot_type": "MS",
               "duration_frames": 48, "start_frame": 1, "end_frame": 48,
               "characters": [], "actions": [], "dialogues": []}
    payload.update(extra)
    return payload


def test_garbage_crowd_count_yields_a_finding_not_an_exception():
    sdl = _project({"crowd": [{"count": "很多", "mode": "walk"}]}, [_shot()])
    rules = [item.rule for item in validate_sdl(sdl)]
    assert "S8" in rules


def test_none_crowd_count_is_a_finding():
    sdl = _project({"crowd": [{"count": None, "mode": "walk"}]}, [_shot()])
    assert "S8" in [item.rule for item in validate_sdl(sdl)]


def test_non_object_crowd_entry_is_a_finding():
    sdl = _project({"crowd": ["三十人"]}, [_shot()])
    assert "S8" in [item.rule for item in validate_sdl(sdl)]


def test_garbage_movement_end_frame_is_a_finding():
    from block_director.contracts.sdl import SDLCamera

    shot = _shot(camera=SDLCamera(movements=[{"type": "dolly_in",
                                             "end_frame": "很长"}]))
    sdl = _project({}, [shot])
    assert "S10" in [item.rule for item in validate_sdl(sdl)]


def test_garbage_action_frames_are_findings():
    shot = _shot(actions=[{"character_id": "char_001",
                           "start_frame": "开始", "end_frame": "结束"}])
    sdl = _project({}, [shot])
    assert "S3" in [item.rule for item in validate_sdl(sdl)]


def test_garbage_wall_and_character_boxes_are_findings():
    from block_director.contracts.cast import CastMember

    sdl = _project({"walls": [{"position": "墙", "size": [1, 1, 1]}]},
                   [_shot()])
    sdl.characters = [CastMember(id="char_001", name="米迦尔",
                                 initial_location="很远")]
    rules = [item.rule for item in validate_sdl(sdl)]
    assert "S4" in rules


def test_valid_project_still_reports_nothing():
    sdl = _project({"walls": [{"position": [0, 5, 1], "size": [8, 0.2, 2]}]},
                   [_shot()])
    assert validate_sdl(sdl) == []


def test_broken_project_file_is_reported_not_raised(tmp_path):
    """``load_project`` 的捕获面必须放宽（v1.4 X2 的第二半）。"""
    import pytest

    from block_director.layer9_persistence import load_project
    from block_director.layer9_persistence.project_io import (
        PROJECT_FILENAME,
        ProjectError,
    )

    (tmp_path / PROJECT_FILENAME).write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ProjectError):
        load_project(tmp_path)
