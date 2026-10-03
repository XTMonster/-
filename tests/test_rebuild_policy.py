"""`rebuild_project` 的策略：**校验报告**与**重建闸门**分开。

现场（2026-10-03）：64 镜真跑收尾的 `project.bdproj` 带 26 条 S6，
旧写法在 `not loaded.ok` 处直接 `return 1`——于是"改一镜、重出一镜"
（§14.2，这个 CLI 存在的**唯一**理由）对真实运行是断的：越是需要修的
工程越打不开。

这里钉两件事，缺一不可：
1. 校验**照跑**，S6 照样报出来（不是把校验关掉）；
2. 带着 finding 的项目**仍然**重建（闸门属于 `export_project` 的渲染审计）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.cast import CastMember  # noqa: E402
from block_director.contracts.sdl import (  # noqa: E402
    SDLProject,
    SDLScene,
    SDLShot,
)
from block_director.layer9_persistence import (  # noqa: E402
    load_project,
    save_project,
    validation_report,
)
from tools import rebuild_project  # noqa: E402


def _overflowing_project() -> SDLProject:
    """一个**自己装不下对白**的工程：72 帧的镜头配一句排到第 70 帧的台词。"""
    shot = SDLShot(id="shot_001", intent="推进", shot_type="MS",
                   duration_frames=72, start_frame=1, end_frame=72,
                   characters=["char_001"],
                   dialogues=[{"character_id": "char_001", "text": "我先上船。",
                               "start_frame": 40, "end_frame": 70}])
    scene = SDLScene(id="scene_001", number=1, heading="测试场", shots=[shot])
    return SDLProject(name="rebuild-policy", version="1.4", fps=24,
                      characters=[CastMember(id="char_001", name="char_001")],
                      scenes=[scene])


def test_validation_still_reports_the_finding(tmp_path):
    save_project(tmp_path, _overflowing_project())
    loaded = load_project(tmp_path)
    report = validation_report(loaded)
    assert report["ok"] is False
    assert report["rules"] == ["S6"]
    assert report["errors"] and report["errors"][0]["rule"] == "S6"
    #: 报告里必须带上"是哪一镜、错在哪"，否则人只看到一句"校验不过"。
    assert report["errors"][0]["target"] == "shot_001"
    assert "装不下对白" in report["errors"][0]["message"]


def test_a_project_with_findings_is_still_rebuilt(tmp_path):
    save_project(tmp_path, _overflowing_project())
    loaded = load_project(tmp_path)
    verdict = rebuild_project.rebuild_verdict(loaded)
    assert verdict["proceed"] is True
    assert verdict["blocked_reason"] == ""
    assert verdict["validation"]["ok"] is False          # 如实
    assert verdict["validation"]["rules"] == ["S6"]      # 一条不少


def test_a_clean_project_reports_ok(tmp_path):
    shot = SDLShot(id="shot_001", intent="推进", shot_type="MS",
                   duration_frames=72, start_frame=1, end_frame=72,
                   characters=["char_001"])
    scene = SDLScene(id="scene_001", number=1, heading="测试场", shots=[shot])
    project = SDLProject(name="clean", version="1.4", fps=24,
                         characters=[CastMember(id="char_001", name="char_001")],
                         scenes=[scene])
    save_project(tmp_path, project)
    report = validation_report(load_project(tmp_path))
    assert report["ok"] is True
    assert report["errors"] == []


def test_unreadable_project_still_fails_loudly(tmp_path):
    """策略放宽的是"带 finding"，不是"读不出来"——那条仍然是硬失败。"""
    from block_director.layer9_persistence.project_io import ProjectError

    (tmp_path / "project.bdproj").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ProjectError):
        load_project(tmp_path)
