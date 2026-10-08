"""v1.6 C1（FR-A1）：SDL 1.6 与 1.5→1.6 迁移（brief.environment / rhythm_arc）。"""

from __future__ import annotations

import copy
import json

from block_director.contracts.brief import SceneBrief
from block_director.contracts.plan import Plan
from block_director.contracts.sdl import SDL_VERSION, SDLProject
from block_director.layer2_sdl import build_sdl, migrate_sdl, validate_sdl
from block_director.layer2_sdl.sdl_migrate import KNOWN_VERSIONS
from block_director.layer9_persistence import project_io


def _plan() -> Plan:
    return Plan.from_dict({
        "scene_heading": "EXT. 码头市场 - 黄昏",
        "shots": [{"shot_id": "shot_001", "order": 1, "intent": "建立",
                   "shot_type": "MLS", "duration_frames": 96,
                   "characters": ["char_001"]}],
    })


def _brief() -> SceneBrief:
    return SceneBrief.from_dict({
        "environment": [{"label": "拱廊拱顶", "direction": "above",
                         "distance": "near", "size": "l",
                         "mood": "蓝绿色铸钢雕花铁艺"},
                        {"label": "糖果摊位", "direction": "left",
                         "distance": "mid", "size": "m", "mood": ""}],
        "rhythm_arc": [{"shot_id": "shot_001", "tension": 3, "note": "平稳"}],
    })


#: v1.6 新增的**可选**键；"旧字段逐字节不变"的比对要先把它们摘掉。
NEW_BRIEF_KEYS = ("environment", "rhythm_arc")


def _as_v15_file(payload: dict) -> dict:
    """把一份当前版本的文件**降级**成真正的 1.5 文件（删掉 v1.6 新键）。"""
    data = copy.deepcopy(payload)
    data["version"] = "1.5"
    brief = data.get("brief")
    if isinstance(brief, dict):
        for key in NEW_BRIEF_KEYS:
            brief.pop(key, None)
    return data


def _strip_new(payload: dict) -> dict:
    data = copy.deepcopy(payload)
    brief = data.get("brief")
    if isinstance(brief, dict):
        for key in NEW_BRIEF_KEYS:
            brief.pop(key, None)
    return data


# --------------------------------------------------------------------------- #
# 版本与兼容声明
# --------------------------------------------------------------------------- #
def test_sdl_version_is_1_6():
    assert SDL_VERSION == "1.6"


def test_known_versions_are_append_only():
    for version in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"):
        assert version in KNOWN_VERSIONS
    assert KNOWN_VERSIONS[-1] == SDL_VERSION


def test_a_v15_file_is_not_reported_as_unknown():
    fixture = _as_v15_file(build_sdl(_plan(), brief=_brief()).to_dict())
    _payload, notes = migrate_sdl(fixture)
    assert not any("未知版本" in note for note in notes), notes


# --------------------------------------------------------------------------- #
# 1.5 → 1.6：只增字段，旧字段逐字节不变
# --------------------------------------------------------------------------- #
def test_v15_migration_defaults_the_new_brief_fields():
    fixture = _as_v15_file(build_sdl(_plan(), brief=_brief()).to_dict())
    payload, _notes = migrate_sdl(fixture)
    assert payload["version"] == SDL_VERSION
    assert payload["brief"]["environment"] == []
    assert payload["brief"]["rhythm_arc"] == []


def test_v15_migration_leaves_every_old_field_byte_identical():
    fixture = _as_v15_file(build_sdl(_plan(), brief=_brief()).to_dict())
    expected = copy.deepcopy(fixture)
    expected["version"] = SDL_VERSION
    payload, _notes = migrate_sdl(copy.deepcopy(fixture))
    assert _strip_new(payload) == expected


def test_migrating_a_v15_file_twice_is_stable():
    fixture = _as_v15_file(build_sdl(_plan(), brief=_brief()).to_dict())
    once, notes = migrate_sdl(fixture)
    twice, second_notes = migrate_sdl(once)
    assert twice == once
    assert notes and second_notes == []


# --------------------------------------------------------------------------- #
# environment / rhythm_arc 的落盘与读回
# --------------------------------------------------------------------------- #
def test_brief_environment_and_rhythm_arc_survive_the_sdl_round_trip():
    sdl = build_sdl(_plan(), brief=_brief())
    restored = SDLProject.from_dict(sdl.to_dict())
    brief = SceneBrief.from_dict(restored.brief)
    assert brief.environment == _brief().environment
    assert brief.rhythm_arc == _brief().rhythm_arc
    assert validate_sdl(restored) == []


def test_project_io_saves_and_loads_a_v16_project(tmp_path):
    sdl = build_sdl(_plan(), brief=_brief())
    project_io.save_project(tmp_path, sdl)
    loaded = project_io.load_project(tmp_path)
    assert loaded.ok
    assert loaded.notes == []                # 已是最新版本：无迁移说明
    assert loaded.sdl.version == SDL_VERSION
    brief = SceneBrief.from_dict(loaded.sdl.brief)
    assert brief.environment[0]["label"] == "拱廊拱顶"
    assert brief.environment[0]["direction"] == "above"
    assert brief.environment[0]["mood"] == "蓝绿色铸钢雕花铁艺"
    assert brief.environment[1]["distance"] == "mid"
    assert brief.rhythm_arc[0]["shot_id"] == "shot_001"
    assert brief.rhythm_arc[0]["tension"] == 3


def test_project_io_migrates_a_v15_project_losslessly(tmp_path):
    fixture = _as_v15_file(build_sdl(_plan(), brief=_brief()).to_dict())
    path = project_io.project_file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    loaded = project_io.load_project(tmp_path)
    assert loaded.ok
    assert loaded.sdl.version == SDL_VERSION
    assert any("1.5" in note for note in loaded.notes)
    brief = SceneBrief.from_dict(loaded.sdl.brief)
    assert brief.environment == []          # 旧工程没有环境件：无损为空
    assert brief.rhythm_arc == []
    # 旧字段一样不少：镜头时长、角色名册照旧
    assert loaded.sdl.shots[0].duration_frames == 96
    assert [member.id for member in loaded.sdl.characters] == ["char_001"]
