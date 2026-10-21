"""T3：镜头拍摄对象契约 ``framing_target``（SDL 1.8 ＋ 迁移）。

判据：
1. ``ShotPlan.framing_target`` 往返（kind/ref/part），缺失键 = None（未声明）；
2. SDL 保存/读回该字段；v1.4 旧文件迁移后补默认
   ``{"kind": "character", "part": "none", "ref": ""}`` 且 S 规则校验通过；
3. ``KNOWN_VERSIONS`` 只增不改：1.8 在列、末位 = 当前版本；
4. 草案 schema 带 ``framing_target`` 且 kind/part 是闭集。
"""

from __future__ import annotations

import copy

from block_director.contracts.plan import Plan, ShotPlan
from block_director.contracts.sdl import SDL_VERSION, SDLProject
from block_director.layer2_sdl import build_sdl, migrate_sdl, validate_sdl
from block_director.layer2_sdl.sdl_builder import sdl_to_plan
from block_director.layer2_sdl.sdl_migrate import KNOWN_VERSIONS


def _plan(with_target: bool = False) -> Plan:
    shot = {
        "shot_id": "shot_001", "order": 1, "intent": "右手特写",
        "shot_type": "CU", "duration_frames": 84,
        "characters": ["char_001"],
    }
    if with_target:
        shot["framing_target"] = {"kind": "character", "ref": "char_001",
                                  "part": "hand"}
    return Plan.from_dict({"scene_heading": "EXT. 码头 - 日",
                           "shots": [shot]})


def test_framing_target_roundtrip_plan():
    shot = _plan(with_target=True).shots[0]
    assert shot.framing_target is not None
    assert shot.framing_target.kind == "character"
    assert shot.framing_target.ref == "char_001"
    assert shot.framing_target.part == "hand"
    assert ShotPlan.from_dict(shot.to_dict()).framing_target \
        == shot.framing_target


def test_missing_framing_target_is_none_and_key_always_present():
    shot = _plan().shots[0]
    assert shot.framing_target is None
    payload = shot.to_dict()
    assert "framing_target" in payload
    assert payload["framing_target"] is None
    assert ShotPlan.from_dict(payload).framing_target is None


def test_sdl_saves_and_reads_framing_target():
    plan = _plan(with_target=True)
    payload = build_sdl(plan).to_dict()
    shot = payload["scenes"][0]["shots"][0]
    assert shot["framing_target"] == {"kind": "character",
                                      "ref": "char_001", "part": "hand",
                                      "anchor_offset": None}
    loaded = SDLProject.from_dict(payload)
    restored = sdl_to_plan(loaded)
    assert restored.shots[0].framing_target == plan.shots[0].framing_target


def test_v14_file_migration_defaults_framing_target_and_validates():
    data = copy.deepcopy(build_sdl(_plan()).to_dict())
    data["version"] = "1.4"
    for scene in data.get("scenes") or []:
        for shot in scene.get("shots") or []:
            shot.pop("framing_target", None)
    migrated, notes = migrate_sdl(data)
    assert migrated["version"] == SDL_VERSION
    shot = migrated["scenes"][0]["shots"][0]
    assert shot["framing_target"] == {"kind": "character",
                                      "part": "none", "ref": ""}
    sdl = SDLProject.from_dict(migrated)
    assert [finding for finding in validate_sdl(sdl) if finding.is_error] == []
    assert any("framing_target" in note for note in notes)


def test_known_versions_are_append_only_with_18():
    for version in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6",
                    "1.7", "1.8"):
        assert version in KNOWN_VERSIONS
    assert KNOWN_VERSIONS[-1] == SDL_VERSION


def test_draft_schema_has_framing_target_closed_sets():
    from block_director.layer5_orchestrator.shot_schema import (
        emit_shot_draft_schema,
    )
    schema = emit_shot_draft_schema(["char_001"], ["char_001"], [])
    framing_target = schema["properties"]["framing_target"]
    assert framing_target["properties"]["kind"]["enum"] == ["character",
                                                           "prop"]
    assert "hand" in framing_target["properties"]["part"]["enum"]
    assert "none" in framing_target["properties"]["part"]["enum"]
