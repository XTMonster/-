"""v1.4 S9：``with_labels`` 必须真的落进 SDL、读得回来、能迁移。

v1.3 的 ``SDLScene`` 根本没有这个字段，``sdl_to_spec`` 也不写回，
于是"用户关掉标签 → 保存 → 重新打开"会把关闭状态丢掉。
"""

from __future__ import annotations

import json

from block_director.contracts.cast import SceneSpec
from block_director.contracts.plan import Plan
from block_director.contracts.sdl import SDL_VERSION, SDLProject
from block_director.layer2_sdl import build_sdl, migrate_sdl, sdl_to_spec
from block_director.layer9_persistence import load_project, save_project


def _plan() -> Plan:
    return Plan.from_dict({"scene_heading": "INT. 房间 - 日", "shots": [
        {"shot_id": "shot_001", "intent": "x", "shot_type": "MS",
         "duration_frames": 48, "characters": ["char_001"]}]})


def test_build_sdl_writes_the_flag_from_the_spec():
    spec = SceneSpec.from_plan(_plan())
    spec.with_labels = False
    sdl = build_sdl(_plan(), spec=spec)
    assert sdl.with_labels is False
    assert sdl.to_dict()["with_labels"] is False


def test_save_load_rebuild_keeps_the_flag(tmp_path):
    spec = SceneSpec.from_plan(_plan())
    spec.with_labels = False
    save_project(tmp_path, build_sdl(_plan(), spec=spec))
    loaded = load_project(tmp_path)
    assert loaded.sdl.with_labels is False
    assert sdl_to_spec(loaded.sdl).with_labels is False


def test_default_is_true():
    assert SDLProject().with_labels is True
    assert build_sdl(_plan()).with_labels is True


def test_v13_project_migrates_and_keeps_the_default():
    payload = json.loads(json.dumps(build_sdl(_plan()).to_dict()))
    payload["version"] = "1.3"
    payload.pop("with_labels", None)
    migrated, notes = migrate_sdl(payload)
    assert migrated["version"] == SDL_VERSION
    assert "未知版本" not in " ".join(notes)
    assert SDLProject.from_dict(migrated).with_labels is True
