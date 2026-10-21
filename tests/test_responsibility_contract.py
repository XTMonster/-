"""卡 A6：分工声明契约（v1.7 TDD §14.1 / SDL 1.7）。"""

from __future__ import annotations

import copy

from block_director.contracts.plan import Plan, Responsibility, ShotPlan
from block_director.contracts.sdl import SDLProject
from block_director.layer2_sdl import build_sdl, migrate_sdl, validate_sdl
from block_director.layer2_sdl.sdl_builder import sdl_to_plan
from block_director.layer5_orchestrator.planner import plan_parameters
from block_director.layer5_orchestrator.tool_schema import validate_args


def _plan(responsibility: Responsibility | None = None) -> Plan:
    return Plan.from_dict({
        "scene_heading": "EXT. 码头市场 - 黄昏",
        "shots": [{
            "shot_id": "shot_001", "order": 1, "intent": "建立",
            "shot_type": "MLS", "duration_frames": 96,
            "characters": ["char_001"],
        }],
    })


def _declared_plan() -> Plan:
    plan = _plan()
    plan.shots[0].responsibility = Responsibility(
        white_model=["位置/机位"], prompt=["表情"], ref_image=["风格图"],
        skip_white_model=False)
    return plan


def _as_v16_file() -> dict:
    data = build_sdl(_plan()).to_dict()
    data["version"] = "1.6"
    for scene in data.get("scenes") or []:
        for shot in scene.get("shots") or []:
            shot.pop("responsibility", None)
    return data


def test_v16_file_loads_zero_errors():
    payload, notes = migrate_sdl(_as_v16_file())
    sdl = SDLProject.from_dict(payload)
    errors = [finding for finding in validate_sdl(sdl)
              if finding.is_error]
    assert errors == []
    assert all(shot.responsibility is None for shot in sdl.shots)
    assert any("responsibility" in note for note in notes)
    assert payload["version"] == "1.8"


def test_roundtrip():
    plan = _declared_plan()
    assert Plan.from_dict(plan.to_dict()) == plan
    sdl = build_sdl(plan)
    restored = sdl_to_plan(SDLProject.from_dict(sdl.to_dict()))
    assert restored.shots[0].responsibility == plan.shots[0].responsibility


def test_undeclared_is_none_not_empty():
    shot = _plan().shots[0]
    assert shot.responsibility is None
    assert ShotPlan.from_dict(shot.to_dict()).responsibility is None


def test_serialized_key_always_present():
    declared = _declared_plan().to_dict()
    undeclared = _plan().to_dict()
    for payload in (declared, undeclared):
        for shot in payload["shots"]:
            assert "responsibility" in shot
    assert declared["shots"][0]["responsibility"]["white_model"] == ["位置/机位"]
    assert undeclared["shots"][0]["responsibility"] is None


def test_emit_plan_schema_accepts_optional_key():
    schema = plan_parameters()
    base_shot = {"shot_id": "shot_001", "intent": "建立", "shot_type": "MLS",
                 "duration_frames": 96}
    with_key = dict(base_shot, responsibility={
        "white_model": ["机位"], "prompt": [], "ref_image": [],
        "skip_white_model": True})
    assert validate_args(schema, {"shots": [with_key]}) == []
    assert validate_args(schema, {"shots": [base_shot]}) == []
    assert validate_args(schema, {"shots": [dict(
        base_shot, responsibility="yes")]}) != []


def test_bad_type_finding_not_crash():
    payload = _as_v16_file()
    payload["scenes"][0]["shots"][0]["responsibility"] = "yes"
    migrated, notes = migrate_sdl(payload)
    assert any("responsibility" in note for note in notes)
    assert migrated["scenes"][0]["shots"][0]["responsibility"] is None
