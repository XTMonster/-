"""§14 项目保存/加载测试。"""

from __future__ import annotations

import json

import pytest

from block_director.layer2_sdl import build_sdl
from block_director.layer9_persistence import (
    PROJECT_FILENAME,
    load_project,
    project_exists,
    project_file,
    save_project,
)
from block_director.layer9_persistence.project_io import ProjectError

from test_sdl import BUILD, demo_plan


def test_save_then_load_round_trips(tmp_path):
    sdl = build_sdl(demo_plan(), build_summary=BUILD, project_name="咖啡馆")
    path = save_project(tmp_path, sdl)
    assert path.name == PROJECT_FILENAME and project_exists(tmp_path)

    loaded = load_project(tmp_path)
    assert loaded.ok
    assert loaded.sdl.to_dict()["scenes"] == sdl.to_dict()["scenes"]
    assert loaded.sdl.name == "咖啡馆"
    assert loaded.summary()["shots"] == 2


def test_saved_file_is_readable_json_with_metadata(tmp_path):
    save_project(tmp_path, build_sdl(demo_plan(), build_summary=BUILD))
    raw = json.loads(project_file(tmp_path).read_text(encoding="utf-8"))
    assert raw["version"] == "1.2"
    assert "saved_at" in raw
    assert raw["fps"] == 24


def test_load_missing_project_gives_guidance(tmp_path):
    with pytest.raises(ProjectError) as excinfo:
        load_project(tmp_path / "nope")
    message = str(excinfo.value)
    assert PROJECT_FILENAME in message and "--project" in message


def test_broken_json_is_reported(tmp_path):
    project_file(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(ProjectError):
        load_project(tmp_path)


def test_loading_an_old_project_migrates_it(tmp_path):
    legacy = {
        "name": "旧项目",
        "scenes": [{"heading": "INT. 咖啡馆 - 日", "shots": [
            {"id": "shot_001", "shot_type": "MS", "start_frame": 1,
             "end_frame": 48}]}],
    }
    project_file(tmp_path).write_text(json.dumps(legacy), encoding="utf-8")
    loaded = load_project(tmp_path)
    assert loaded.sdl.version == "1.2"
    assert loaded.notes and "迁移" in loaded.notes[-1]
    assert loaded.sdl.shots[0].duration_frames == 48
    assert loaded.sdl.shots[0].start_frame == 1


def test_loaded_project_exposes_validation_findings(tmp_path):
    sdl = build_sdl(demo_plan(), build_summary=BUILD)
    sdl.scenes[0].shots[0].characters.append("ghost")
    save_project(tmp_path, sdl)
    loaded = load_project(tmp_path)
    assert not loaded.ok
    assert any(item.rule == "S2" for item in loaded.findings)
