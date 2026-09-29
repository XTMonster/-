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
    assert payload["version"] == "1.3"
    assert payload["fps"] == 24
    shot = payload["scenes"][0]["shots"][0]
    assert shot["duration_frames"] == 48
    assert shot["prompt"] == "" and shot["actions"] == []
    assert notes and "1.0" in notes[-1]


def test_migrate_is_idempotent_for_current_version():
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    payload, notes = migrate_sdl(sdl.to_dict())
    assert payload["version"] == "1.3" and notes == []
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
    # v1.3：默认站位改成"两人相对而立"。v1.2 是并排朝前（间距 1.5、一律 +Y），
    # 两个正在对话的人谁也不看谁——与"互相看向对方"的剧本语义相反。
    assert member["initial_location"] == [-0.9, 0.0, 0.0]
    assert member["initial_facing"] == [1.0, 0.0, 0.0]
    other = data["characters"][1]
    assert other["initial_location"] == [0.9, 0.0, 0.0]
    assert other["initial_facing"] == [-1.0, 0.0, 0.0]


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
    # v1.3：补进来的角色用**相对而立**的默认站位（v1.2 是并排朝前）。
    first, second = sdl.characters
    assert first.initial_location == (-0.9, 0.0, 0.0)
    assert second.initial_location == (0.9, 0.0, 0.0)
    assert tuple(first.initial_facing) == (1.0, 0.0, 0.0)
    assert tuple(second.initial_facing) == (-1.0, 0.0, 0.0)


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


def test_v12_roster_is_not_healed():
    """1.2 起写入器就保证名册完整，缺失的引用因此是**真错误**。

    v1.2 的文件由本插件自己写出，``characters`` 一定完整；引用到不存在的
    角色说明文件被手改坏过。迁移只给"还没有名册这个结构"的更老文件补名册，
    否则坏项目会被悄悄补成一个看似能用的半成品。
    """
    legacy = {
        "version": "1.2",
        "name": "旧项目",
        "characters": [],
        "scenes": [{"heading": "INT. 咖啡馆 - 日", "shots": [
            {"id": "shot_001", "shot_type": "MS", "duration_frames": 48,
             "characters": ["ghost"]}]}],
    }
    payload, notes = migrate_sdl(legacy)
    assert payload["characters"] == []
    assert not any("补齐角色表" in note for note in notes)
    assert "S2" in {item.rule for item in
                    validate_sdl(SDLProject.from_dict(payload))}


def test_older_versions_still_get_a_healed_roster():
    """1.1 及更早的文件没有可靠名册，结构补全仍然照做。"""
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
