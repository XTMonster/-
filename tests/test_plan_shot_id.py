"""v1.4 安全审计 F1：``shot_id`` 不得越过导出目录。

``shot_id`` 会被直接拼进文件名（``blockout_<id>.mp4``、
``first_frames/<id>.png``、``depth_shot_<id>/``），所以它是**路径片段**而不是
自由文本。旧实现（``contracts/plan.py`` 的 ``from_dict`` 直接 ``str(...)``）
照单全收：计划里写 ``../../..`` 就能把文件写到导出目录之外。入口有三条——
LLM 输出、手改的 ``project.bdproj``、重放的旧 ``audit_log.jsonl``——所以校验
必须落在**契约边界**上（所有路径都过 ``Plan.from_dict``）。

负例：每个非法 id 都必须抛 ``ValueError``；SDL 那条加载路径必须**报 finding**
而不是崩掉。
"""

from __future__ import annotations

import pytest

from block_director.contracts.plan import Plan, validate_shot_id
from block_director.contracts.sdl import SDLProject
from block_director.layer2_sdl import validate_sdl

GOOD_IDS = ("shot_001", "shot-002", "shot.003", "A" * 64)

BAD_IDS = (
    "",
    "../../../../Users/Public/pwned",
    "..\\..\\windows\\system32\\x",
    "a/b",
    "a\\b",
    "shot 001",
    "镜号1",
    "A" * 65,
)


@pytest.mark.parametrize("shot_id", GOOD_IDS)
def test_legal_ids_pass(shot_id):
    assert validate_shot_id(shot_id) == shot_id


@pytest.mark.parametrize("shot_id", BAD_IDS)
def test_illegal_ids_are_rejected_at_the_contract_boundary(shot_id):
    with pytest.raises(ValueError):
        validate_shot_id(shot_id)
    with pytest.raises(ValueError):
        Plan.from_dict({"shots": [
            {"shot_id": shot_id, "intent": "x", "shot_type": "MS",
             "duration_frames": 24}]})


def test_path_traversal_cannot_reach_the_filesystem():
    """独立复核：非法 id 连**解析**都过不去，更谈不上落盘。"""
    from pathlib import Path

    with pytest.raises(ValueError):
        Plan.from_dict({"shots": [
            {"shot_id": "../../../../Users/Public/bd_pwned", "intent": "x",
             "shot_type": "MS", "duration_frames": 24}]})
    # 证据：恶意 id 只有在通过解析之后才可能被拼成路径；这里根本没走到。
    candidate = Path("C:/out/run/export") / "blockout_../../../../Users/Public/bd_pwned.mp4"
    assert ".." in str(candidate)          # 说明"拼出来是穿越路径"这件事是真的


def test_loading_a_broken_project_reports_a_finding():
    payload = {
        "name": "坏项目", "version": "1.4", "fps": 24, "characters": [],
        "scenes": [{"id": "scene_001", "number": 1, "heading": "h",
                    "environment": {},
                    "shots": [{"id": "../../evil", "intent": "x",
                               "shot_type": "MS", "duration_frames": 24,
                               "start_frame": 1, "end_frame": 24,
                               "characters": [], "actions": [],
                               "dialogues": []}]}],
    }
    sdl = SDLProject.from_dict(payload)
    rules = [item.rule for item in validate_sdl(sdl)]
    assert "S11" in rules
