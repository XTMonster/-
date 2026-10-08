"""P2-T3：SDL 1.5 与 1.4→1.5 迁移（执行文档 v1.5 TDD §3.3/§3.9 / FR-13）。

四条必须钉住：

1. ``KNOWN_VERSIONS`` **只增不改**——必须仍然认识 1.0…1.6 全部版本（旧写法
   把 ``SDL_VERSION`` 当成"上一个版本"，升版本会把上一个版本悄悄挤出去，
   于是刚落盘的旧工程反成"未知版本"）；
2. 1.4 工程 dict → ``migrate_sdl`` → 新字段缺省、旧字段**逐字节不变**；
3. 1.5 落盘/读回：``build_sdl`` → ``to_dict`` → ``from_dict`` → ``sdl_to_plan``
   保住 beats / composition / rule_justifications / environment；
4. 迁移后 ``validate_sdl`` **零新增 finding**（坏数据只报 finding，不抛异常）。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.contracts.sdl import SDL_VERSION  # noqa: E402
from block_director.layer2_sdl import (  # noqa: E402
    build_sdl,
    migrate_sdl,
    sdl_to_plan,
    validate_sdl,
)
from block_director.layer2_sdl.sdl_migrate import KNOWN_VERSIONS  # noqa: E402


def _sdl_14_payload() -> dict:
    """一份**结构完整**的 1.4 工程（含角色、场景、一镜、对白、运镜）。"""
    return {
        "name": "LegacyProject",
        "version": "1.4",
        "fps": 24,
        "characters": [
            {"id": "char_001", "name": "林可", "color": "#CC4444",
             "initial_location": [0.0, 0.0, 0.0],
             "initial_facing": [0.0, 1.0, 0.0]},
        ],
        "scenes": [{
            "id": "scene_001", "number": 1, "heading": "INT. 房间 - 日",
            "environment": {"ground_size": [20.0, 20.0], "walls": [],
                            "props": [], "lighting": "clay_studio",
                            "room": None, "crowd": []},
            "shots": [{
                "id": "shot_001", "intent": "推进", "shot_type": "MS",
                "duration_frames": 72, "start_frame": 1, "end_frame": 72,
                "transition_in": "cut", "transition_out": "cut",
                "active_speakers": ["char_001"], "characters": ["char_001"],
                "actions": [], "dialogues": [], "gaze": [], "vfx": [],
                "prompt": "中景，林可站着。",
                "camera": {"id": "BD_Cam_shot_001",
                           "position": [0.0, -3.0, 1.5],
                           "target": [0.0, 0.0, 1.0], "lens": 50.0,
                           "movement": "static", "movements": [], "request": {}},
            }],
        }],
        "continuity": {"axis_note": [], "character_pose": {}},
        "warnings": [], "brief": {}, "with_labels": True,
    }


def test_sdl_version_is_16():
    assert SDL_VERSION == "1.6"


def test_known_versions_is_append_only():
    assert KNOWN_VERSIONS == ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6")


def test_migrate_14_to_15_only_fills_defaults():
    original = _sdl_14_payload()
    migrated, notes = migrate_sdl(copy.deepcopy(original))
    assert migrated["version"] == SDL_VERSION
    scene = migrated["scenes"][0]
    # 新字段：缺省填充
    assert scene["environment"]["anchors"] == []
    assert scene["environment"]["light"] == {}
    shot = scene["shots"][0]
    assert shot["beats"] == []
    assert shot["composition"] == {}
    assert shot["rule_justifications"] == []
    # 旧字段：逐字节不变（把新键摘掉再比，等价于"只增不改"）
    for key in ("name", "fps", "characters", "characters"):
        assert migrated[key] == original[key]
    assert shot["prompt"] == original["scenes"][0]["shots"][0]["prompt"]
    assert shot["duration_frames"] == 72
    # 认识 1.4 ⇒ 不产生"未知版本"告警
    assert not any("未知版本" in note for note in notes)


def test_migrated_14_project_validates_clean():
    migrated, _ = migrate_sdl(_sdl_14_payload())
    from block_director.contracts.sdl import SDLProject

    findings = validate_sdl(SDLProject.from_dict(migrated))
    assert findings == [], [str(f) for f in findings]


def test_round_trip_preserves_new_fields():
    plan = Plan(
        scene_heading="EXT. 码头 - 黄昏",
        shots=[ShotPlan(
            shot_id="shot_001", intent="推进", shot_type="MS",
            duration_frames=72, order=1, characters=["char_001"],
            beats=[{"t": 0.2, "subject": "char_001", "verb": "walk_to",
                    "target": "door", "face_to": "camera", "pace": "slow",
                    "react": ""}],
            composition={"rule": "lead_room", "subject_position": "right_third"},
            rule_justifications=[{"rule": "R001", "action": "follow",
                                  "reason": "", "precedent": ""}],
        )],
        environment={"anchors": [{"name": "door", "depth": "bg",
                                  "relation": "behind 甲", "position": []}],
                     "light": {"time_of_day": "dusk", "mood": "soft"}},
    )
    sdl = build_sdl(plan)
    again = sdl_to_plan(sdl)
    assert again.shots[0].beats[0]["verb"] == "walk_to"
    assert again.shots[0].composition["rule"] == "lead_room"
    assert again.shots[0].rule_justifications[0]["rule"] == "R001"
    assert again.environment["anchors"][0]["name"] == "door"
    assert again.environment["light"]["mood"] == "soft"


def test_sdl_15_dict_is_json_serialisable_and_reloadable():
    plan = Plan(scene_heading="INT. x", shots=[
        ShotPlan(shot_id="shot_001", intent="a", shot_type="MS",
                 duration_frames=48, order=1)])
    sdl = build_sdl(plan)
    payload = json.loads(json.dumps(sdl.to_dict(), ensure_ascii=False))
    assert payload["version"] == SDL_VERSION
    reloaded = sdl_to_plan(type(sdl).from_dict(payload))
    assert reloaded.shots[0].shot_id == "shot_001"
