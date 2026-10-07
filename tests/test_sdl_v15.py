"""SDL 1.5 与迁移器（执行文档 v1.5 卡 P2-T3 / TDD §3.3 §3.9）。"""

from __future__ import annotations

import copy

from block_director.contracts.plan import Plan
from block_director.contracts.sdl import (
    SDL_VERSION,
    SDLEnvironment,
    SDLProject,
    SDLShot,
)
from block_director.layer2_sdl import build_sdl, migrate_sdl, sdl_to_plan, validate_sdl
from block_director.layer2_sdl.sdl_migrate import KNOWN_VERSIONS
from block_director.layer9_persistence import project_io


def demo_plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "INT. 咖啡馆 - 日",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立关系",
             "shot_type": "MLS", "duration_frames": 96,
             "characters": ["char_001", "char_002"],
             "actions": [{"character_id": "char_001", "action_type": "nod",
                          "start_frame": 1, "end_frame": 96}]},
            {"shot_id": "shot_002", "order": 2, "intent": "反应",
             "shot_type": "MCU", "duration_frames": 120,
             "characters": ["char_002"]},
        ]})


BUILD = {"results": [
    {"shot_id": "shot_001", "start_frame": 1, "end_frame": 96,
     "camera": "BD_Cam_shot_001", "camera_position": [0.0, 3.975, 0.95],
     "camera_target": [0.0, 0.0, 0.8], "lens": 35.0, "warnings": []},
    {"shot_id": "shot_002", "start_frame": 97, "end_frame": 216,
     "camera": "BD_Cam_shot_002", "camera_position": [0.75, 2.469, 1.05],
     "camera_target": [0.75, 0.0, 1.1], "lens": 50.0, "warnings": []},
]}

#: v1.5 新增的**可选**键；"旧字段逐字节不变"的比对要先把它们摘掉。
NEW_SHOT_KEYS = ("beats", "composition", "rule_justifications")
NEW_ENVIRONMENT_KEYS = ("anchors", "light")


def _as_v14_file(payload: dict) -> dict:
    """把一份当前版本的文件**降级**成真正的 1.4 文件（删掉 1.5 新键）。"""
    data = copy.deepcopy(payload)
    data["version"] = "1.4"
    for scene in data.get("scenes") or []:
        environment = scene.get("environment") or {}
        for key in NEW_ENVIRONMENT_KEYS:
            environment.pop(key, None)
        for shot in scene.get("shots") or []:
            for key in NEW_SHOT_KEYS:
                shot.pop(key, None)
    return data


def _strip_new(payload: dict) -> dict:
    data = copy.deepcopy(payload)
    for scene in data.get("scenes") or []:
        environment = scene.get("environment") or {}
        for key in NEW_ENVIRONMENT_KEYS:
            environment.pop(key, None)
        for shot in scene.get("shots") or []:
            for key in NEW_SHOT_KEYS:
                shot.pop(key, None)
    return data


# --------------------------------------------------------------------------- #
# 版本与兼容声明
# --------------------------------------------------------------------------- #
def test_sdl_version_is_1_5():
    assert SDL_VERSION == "1.5"


def test_known_versions_keep_every_shipped_version():
    """KNOWN_VERSIONS **只增不改**：升到 1.5 不许把 1.4 挤出去。

    旧写法 ``("1.0", ..., SDL_VERSION)`` 把当前版本当成"上一个版本"，升到
    1.5 时 "1.4" 会消失——那时刚刚落盘的 1.4 工程反倒被记成"未知版本"。
    """
    for version in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5"):
        assert version in KNOWN_VERSIONS
    assert KNOWN_VERSIONS[-1] == SDL_VERSION


def test_a_v14_file_is_not_reported_as_unknown():
    fixture = _as_v14_file(build_sdl(demo_plan(), build_summary=BUILD)
                           .to_dict())
    _payload, notes = migrate_sdl(fixture)
    assert not any("未知版本" in note for note in notes), notes


# --------------------------------------------------------------------------- #
# 1.4 → 1.5：只增字段，旧字段逐字节不变
# --------------------------------------------------------------------------- #
def test_v14_migration_defaults_the_new_fields():
    fixture = _as_v14_file(build_sdl(demo_plan(), build_summary=BUILD)
                           .to_dict())
    payload, _notes = migrate_sdl(fixture)
    assert payload["version"] == "1.5"
    environment = payload["scenes"][0]["environment"]
    assert environment["anchors"] == []
    assert environment["light"] == {}
    for shot in payload["scenes"][0]["shots"]:
        assert shot["beats"] == []
        assert shot["composition"] == {}
        assert shot["rule_justifications"] == []


def test_v14_migration_leaves_every_old_field_byte_identical():
    fixture = _as_v14_file(build_sdl(demo_plan(), build_summary=BUILD)
                           .to_dict())
    expected = copy.deepcopy(fixture)
    expected["version"] = "1.5"
    # ``migrate_sdl`` 只做浅拷贝：它就地写进传进来的嵌套 dict（既有行为）。
    # 要比对"旧字段没被改"，输入必须是独立的一份。
    payload, _notes = migrate_sdl(copy.deepcopy(fixture))
    assert _strip_new(payload) == expected


def test_v14_migration_adds_no_validator_finding():
    fixture = _as_v14_file(build_sdl(demo_plan(), build_summary=BUILD)
                           .to_dict())
    before = validate_sdl(SDLProject.from_dict(fixture))
    payload, _notes = migrate_sdl(copy.deepcopy(fixture))
    after = validate_sdl(SDLProject.from_dict(payload))
    assert [item.to_dict() for item in after] == \
        [item.to_dict() for item in before]


def test_loading_a_v14_project_behaves_like_before_the_upgrade():
    """1.4 工程加载后：旧字段逐项相同，新字段只是缺省。"""
    fixture = _as_v14_file(build_sdl(demo_plan(), build_summary=BUILD)
                           .to_dict())
    payload, _notes = migrate_sdl(copy.deepcopy(fixture))
    migrated = SDLProject.from_dict(payload)
    raw = SDLProject.from_dict(fixture)      # 未迁移的同一份文件（from_dict 容错）
    assert migrated.to_dict()["scenes"][0]["shots"][0]["camera"] == \
        raw.to_dict()["scenes"][0]["shots"][0]["camera"]
    assert migrated.characters == raw.characters
    assert [shot.id for shot in migrated.shots] == [shot.id for shot in raw.shots]
    assert [shot.duration_frames for shot in migrated.shots] == \
        [shot.duration_frames for shot in raw.shots]
    assert migrated.scenes[0].environment.anchors == []
    assert migrated.scenes[0].environment.light == {}


def test_migrating_a_v14_file_twice_is_stable():
    fixture = _as_v14_file(build_sdl(demo_plan(), build_summary=BUILD)
                           .to_dict())
    once, notes = migrate_sdl(fixture)
    twice, second_notes = migrate_sdl(once)
    assert twice == once
    assert notes and second_notes == []


def test_pre_1_2_roster_repair_still_runs_after_the_version_bump():
    legacy = {
        "version": "1.1",
        "scenes": [{"heading": "INT. 咖啡馆 - 日", "shots": [
            {"id": "shot_001", "shot_type": "MS", "duration_frames": 48,
             "characters": ["char_007"]}]}],
    }
    payload, notes = migrate_sdl(legacy)
    assert [member["id"] for member in payload["characters"]] == ["char_007"]
    assert any("补齐角色表" in note for note in notes)
    assert validate_sdl(SDLProject.from_dict(payload)) == []


# --------------------------------------------------------------------------- #
# 新字段的落盘 / 读回
# --------------------------------------------------------------------------- #
def _plan_with_v15_fields() -> Plan:
    plan = demo_plan()
    plan.environment = {
        "anchors": [{"name": "door", "depth": "bg", "relation": "behind 甲",
                     "position": [1.0, 2.0, 0.0]}],
        "light": {"time_of_day": "day", "mood": "bright", "key_direction": "front"},
    }
    plan.shots[0].beats = [{"t": 0.2, "subject": "char_001", "verb": "look_at",
                            "target": "char_002"}]
    plan.shots[0].composition = {"rule": "thirds",
                                 "subject_position": "left_third"}
    plan.shots[0].rule_justifications = [
        {"rule": "R001", "action": "break", "reason": "表现关系破裂",
         "precedent": "the_shining"}]
    return plan


def test_v15_fields_survive_the_sdl_round_trip():
    plan = _plan_with_v15_fields()
    sdl = build_sdl(plan, build_summary=BUILD)
    assert sdl.scenes[0].environment.anchors[0].name == "door"
    assert sdl.scenes[0].environment.anchors[0].position == [1.0, 2.0, 0.0]
    assert sdl.scenes[0].environment.light["time_of_day"] == "day"
    assert sdl.shots[0].beats[0]["verb"] == "look_at"

    restored = SDLProject.from_dict(sdl.to_dict())
    assert restored.scenes[0].environment.anchors[0].relation == "behind 甲"
    assert restored.scenes[0].environment.light["mood"] == "bright"
    assert restored.shots[0].composition == {"rule": "thirds",
                                             "subject_position": "left_third"}
    assert restored.shots[0].rule_justifications[0]["action"] == "break"

    back = sdl_to_plan(restored)
    assert back.environment["anchors"][0]["name"] == "door"
    assert back.environment["light"]["key_direction"] == "front"
    assert back.shots[0].beats == plan.shots[0].beats
    assert back.shots[0].composition == plan.shots[0].composition
    assert back.shots[0].rule_justifications == plan.shots[0].rule_justifications


def test_an_empty_declaration_keeps_the_sdl_shape_unchanged():
    """空声明 = 现状：新键存在但为空，validate / to_dict 形状不变。"""
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    data = sdl.to_dict()
    assert data["version"] == "1.5"
    assert data["scenes"][0]["environment"]["anchors"] == []
    assert data["scenes"][0]["environment"]["light"] == {}
    assert all(shot["beats"] == [] and shot["composition"] == {}
               for shot in data["scenes"][0]["shots"])
    assert validate_sdl(sdl) == []


def test_new_sdl_fields_default_when_the_keys_are_absent():
    """手写的 SDL 片段（无新键）也要能读出来——from_dict 缺键容错。"""
    sdl = SDLProject.from_dict({
        "version": "1.5",
        "scenes": [{"id": "scene_001",
                    "environment": {"lighting": "clay_studio"},
                    "shots": [{"id": "shot_001", "duration_frames": 24}]}],
    })
    assert sdl.scenes[0].environment.anchors == []
    assert sdl.scenes[0].environment.light == {}
    assert sdl.shots[0].beats == []
    assert isinstance(sdl.scenes[0].environment, SDLEnvironment)
    assert isinstance(sdl.shots[0], SDLShot)


# --------------------------------------------------------------------------- #
# 持久层接受 1.5
# --------------------------------------------------------------------------- #
def test_project_io_saves_and_loads_a_1_5_project(tmp_path):
    plan = _plan_with_v15_fields()
    sdl = build_sdl(plan, build_summary=BUILD)
    project_io.save_project(tmp_path, sdl)
    loaded = project_io.load_project(tmp_path)
    assert loaded.ok
    assert loaded.notes == []                # 已是最新版本：无迁移说明
    assert loaded.sdl.version == "1.5"
    assert loaded.sdl.scenes[0].environment.anchors[0].name == "door"
    assert loaded.sdl.shots[0].beats[0]["verb"] == "look_at"


def test_project_io_migrates_a_1_4_project(tmp_path):
    fixture = _as_v14_file(build_sdl(demo_plan(), build_summary=BUILD)
                           .to_dict())
    path = project_io.project_file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    loaded = project_io.load_project(tmp_path)
    assert loaded.ok
    assert loaded.sdl.version == "1.5"
    assert any("1.4" in note for note in loaded.notes)
    assert loaded.sdl.scenes[0].environment.anchors == []
