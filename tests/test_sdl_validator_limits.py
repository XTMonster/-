"""v1.4 X8/S8：群众上限与特效/群众枚举必须来自**契约层单一真源**。

v1.3 的 ``sdl_validator`` 自己写了一份 ``CROWD_LIMIT = 40`` 与
``CROWD_MODES = ("static", "walk")`` / ``VFX_KINDS = (...)``；
枚举一旦与 ``contracts/enums.py`` 漂移，校验器会拒收引擎真的支持的特效。
"""

from __future__ import annotations

from block_director.contracts.enums import CROWD_MODES, VFX_TYPES
from block_director.contracts.sdl import SDLProject
from block_director.layer2_sdl import sdl_validator, validate_sdl


def _project(crowd, vfx=()) -> SDLProject:
    shot = {"id": "shot_001", "intent": "x", "shot_type": "MS",
            "duration_frames": 48, "start_frame": 1, "end_frame": 48,
            "characters": [], "actions": [], "dialogues": [],
            "vfx": [{"id": f"vfx_{i}", "type": kind}
                    for i, kind in enumerate(vfx)]}
    scene = {"id": "scene_001", "number": 1, "heading": "INT. 市场 - 日",
             "environment": {"crowd": crowd}, "shots": [shot]}
    return SDLProject.from_dict({"name": "上限", "version": "1.4", "fps": 24,
                                 "characters": [], "scenes": [scene]})


def test_validator_enum_tables_come_from_the_contract_layer():
    assert sdl_validator.CROWD_MODES is CROWD_MODES
    assert sdl_validator.VFX_KINDS is VFX_TYPES


def test_every_contract_vfx_type_is_accepted():
    sdl = _project([], vfx=list(VFX_TYPES))
    rules = [item.rule for item in validate_sdl(sdl)]
    assert "S9" not in rules


def test_unknown_vfx_type_is_still_rejected():
    sdl = _project([], vfx=["hologram"])
    assert "S9" in [item.rule for item in validate_sdl(sdl)]


def test_crowd_limit_is_injectable():
    """配置把上限调到 60 时，50 人的**合法**项目不得被判 S8 错。"""
    sdl = _project([{"count": 50, "mode": "walk"}])
    assert "S8" in [item.rule for item in validate_sdl(sdl)]          # 默认 40
    assert "S8" not in [item.rule for item in validate_sdl(sdl, crowd_limit=60)]


def test_default_limit_matches_the_config_default():
    from block_director.contracts.config import AppConfig

    sdl = _project([{"count": 45, "mode": "walk"}])
    errors = validate_sdl(sdl)
    if AppConfig().crowd.max_instances >= 45:
        assert "S8" not in [item.rule for item in errors]
    else:
        assert "S8" in [item.rule for item in errors]
