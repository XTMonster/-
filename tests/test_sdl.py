"""§5 SDL 组装 / 校验 / 迁移测试。"""

from __future__ import annotations

from block_director.contracts.cast import CastMember, SceneSpec
from block_director.contracts.enums import Severity
from block_director.contracts.plan import Plan, ShotPlan
from block_director.contracts.sdl import SDLProject
from block_director.layer2_sdl import build_sdl, migrate_sdl, sdl_to_plan, sdl_to_spec, validate_sdl


def demo_plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "INT. 咖啡馆 - 日",
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立关系",
             "shot_type": "MLS", "duration_frames": 96,
             "characters": ["char_001", "char_002"],
             "actions": [{"character_id": "char_001", "action_type": "nod",
                          "start_frame": 1, "end_frame": 96}],
             "dialogues": [{"character_id": "char_001", "text": "你好",
                            "start_frame": 10, "end_frame": 40}]},
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


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
def test_build_sdl_from_plan_and_build_summary():
    sdl = build_sdl(demo_plan(), build_summary=BUILD, project_name="咖啡馆")
    assert sdl.name == "咖啡馆"
    assert len(sdl.scenes) == 1 and len(sdl.shots) == 2
    first = sdl.shots[0]
    assert (first.start_frame, first.end_frame) == (1, 96)
    assert first.camera.id == "BD_Cam_shot_001"
    assert first.camera.lens == 35.0
    assert first.dialogues[0]["text"] == "你好"
    assert sdl.total_frames == 216


def test_build_sdl_works_without_a_build_summary():
    sdl = build_sdl(demo_plan())
    assert len(sdl.shots) == 2
    assert sdl.shots[0].duration_frames == 96
    assert validate_sdl(sdl) == []          # 没排片也能自洽


def test_sdl_round_trips_through_dict():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    restored = SDLProject.from_dict(sdl.to_dict())
    assert restored.to_dict() == sdl.to_dict()


def test_sdl_converts_back_to_plan_and_spec():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    plan = sdl_to_plan(sdl)
    spec = sdl_to_spec(sdl)
    assert [shot.shot_id for shot in plan.shots] == ["shot_001", "shot_002"]
    assert plan.shots[0].duration_frames == 96
    assert isinstance(spec, SceneSpec) and len(spec.cast) == 2
    assert spec.cast[0].id == "char_001"


# --------------------------------------------------------------------------- #
# 校验（§5.2 七条）
# --------------------------------------------------------------------------- #
def test_clean_sdl_has_no_findings():
    assert validate_sdl(build_sdl(demo_plan(), build_summary=BUILD)) == []


def test_unknown_character_reference_is_error():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    sdl.scenes[0].shots[0].characters.append("ghost")
    rules = {item.rule for item in validate_sdl(sdl)}
    assert "S2" in rules


def test_dialogue_that_overflows_the_shot_is_error():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    sdl.scenes[0].shots[0].dialogues[0]["end_frame"] = 90   # 90+12 > 96
    rules = {item.rule for item in validate_sdl(sdl)}
    assert "S6" in rules


def test_duration_mismatch_is_error():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    sdl.scenes[0].shots[0].duration_frames = 50      # 与 1-96 不符
    rules = {item.rule for item in validate_sdl(sdl)}
    assert "S5" in rules


def test_overlapping_actions_are_error():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    shot = sdl.scenes[0].shots[0]
    shot.actions.append({"character_id": "char_001", "action_type": "nod",
                         "start_frame": 20, "end_frame": 60})
    rules = {item.rule for item in validate_sdl(sdl)}
    assert "S3" in rules


def test_character_inside_a_wall_is_error():
    plan = demo_plan()
    spec = SceneSpec.from_plan(plan)
    spec.walls = [{"position": [0.0, 0.0, 0.75], "size": [4.0, 4.0, 1.5]}]
    sdl = build_sdl(plan, build_summary=BUILD, spec=spec)
    rules = {item.rule for item in validate_sdl(sdl)}
    assert "S4" in rules


def test_missing_version_is_a_warning_not_an_error():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    sdl.version = ""
    findings = validate_sdl(sdl)
    assert all(item.rule != "S1" or item.severity is Severity.WARNING
               for item in findings)


# --------------------------------------------------------------------------- #
# 迁移（§5.3）
# --------------------------------------------------------------------------- #
def test_migrate_v10_folds_frames_into_duration():
    legacy = {
        "name": "旧项目",
        "scenes": [{"heading": "INT. 咖啡馆 - 日", "shots": [
            {"id": "shot_001", "shot_type": "MS", "start_frame": 1,
             "end_frame": 48}]}],
    }
    payload, notes = migrate_sdl(legacy)
    assert payload["version"] == "1.2"
    assert payload["fps"] == 24
    shot = payload["scenes"][0]["shots"][0]
    assert shot["duration_frames"] == 48
    assert shot["prompt"] == "" and shot["actions"] == []
    assert notes and "1.0" in notes[-1]


def test_migrate_is_idempotent_for_current_version():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    payload, notes = migrate_sdl(sdl.to_dict())
    assert payload["version"] == "1.2" and notes == []
    assert SDLProject.from_dict(payload).to_dict() == sdl.to_dict()


def test_migrated_project_still_validates():
    legacy = {
        "scenes": [{"heading": "INT. 咖啡馆 - 日", "shots": [
            {"id": "shot_001", "shot_type": "MS", "duration_frames": 48,
             "characters": [], "actions": [], "dialogues": []}]}],
    }
    payload, _notes = migrate_sdl(legacy)
    sdl = SDLProject.from_dict(payload)
    assert sdl.shots[0].start_frame == 0, "迁移不该编造帧号"
    assert validate_sdl(sdl) == []          # 校验会把它排到第 1 帧
    assert sdl.shots[0].start_frame == 1


def test_cast_serialises_with_the_documented_field_names():
    """SDL 落盘键必须与 §5.1 / §16.1 的 initial_location / initial_facing 一致。"""
    data = build_sdl(demo_plan(), build_summary=BUILD).to_dict()
    member = data["characters"][0]
    assert set(member) == {"id", "name", "color", "initial_location",
                           "initial_facing"}
    assert member["initial_location"] == [-0.75, 0.0, 0.0]
    assert member["initial_facing"] == [0.0, 1.0, 0.0]


def test_migrate_heals_a_missing_cast_roster():
    """旧项目引用了角色却没写 characters 名单：迁移要补齐，而不是让 S2 拒绝它。"""
    legacy = {
        "name": "旧项目",
        "scenes": [{"heading": "INT. 咖啡馆 - 日", "shots": [
            {"id": "shot_001", "shot_type": "MS", "duration_frames": 48,
             "characters": ["char_001"],
             "dialogues": [{"character_id": "char_002", "text": "你好",
                            "start_frame": 5, "end_frame": 30}]}]}],
    }
    payload, notes = migrate_sdl(legacy)
    roster = [member["id"] for member in payload["characters"]]
    assert roster == ["char_001", "char_002"]
    assert any("补齐角色表" in note for note in notes)
    assert "迁移" in notes[-1]               # 版本说明始终收尾
    sdl = SDLProject.from_dict(payload)
    assert validate_sdl(sdl) == []
    assert sdl.characters[0].initial_location == (-0.75, 0.0, 0.0)


def test_current_version_is_not_healed():
    """已经是当前版本的项目仍按原样校验：迁移不许替坏数据打掩护。"""
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    payload = sdl.to_dict()
    payload["scenes"][0]["shots"][0]["characters"] = ["ghost"]
    migrated, notes = migrate_sdl(payload)
    assert migrated["characters"] == payload["characters"]
    assert notes == []
    assert "S2" in {item.rule for item in
                    validate_sdl(SDLProject.from_dict(migrated))}
