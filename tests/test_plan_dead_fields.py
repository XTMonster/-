"""v1.4 X10：``Plan`` 里的死字段必须被删除，不能只当没看见。

``screen_direction`` 从 v1.3 起就没有任何生产者（``rg "screen_direction"``
在 ``block_director/contracts/plan.py`` 里零命中），而 R019 另走
``rule_checker.screen_facing_for`` 的实时计算。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from block_director.contracts.plan import Plan, ShotPlan

ROOT = Path(__file__).resolve().parents[1]


def test_plan_has_no_screen_direction_field():
    assert not hasattr(ShotPlan("s", "", "MS", 1), "screen_direction")


def test_plan_to_dict_has_no_screen_direction_key():
    payload = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "intent": "x", "shot_type": "MS",
         "duration_frames": 24}]}).to_dict()
    assert "screen_direction" not in payload["shots"][0]


def test_declared_shot_number_round_trips():
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "intent": "x", "shot_type": "MS",
         "duration_frames": 24, "declared_shot_number": 7}]})
    assert plan.shots[0].declared_shot_number == 7
    assert plan.to_dict()["shots"][0]["declared_shot_number"] == 7


def test_declared_camera_move_round_trips():
    """声明的拍摄手法是**检索前已知的输入**（Q5 的入口形状），必须能进出计划。

    2026-10-03：它以前只活在 `ParsedShotDeclaration.camera_move` 里，
    `_pin_declared_camera` 只把**非 static** 的声明写进 `camera.movements`
    （引擎运镜词表里没有"不动"），于是"剧本声明固定机位"这条信息在逐镜检索
    之前就断了——实测第 1 镜真实发出的契约串只有 `景别=MCU`。
    """
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "intent": "x", "shot_type": "MS",
         "duration_frames": 24, "declared_camera_move": "static"}]})
    assert plan.shots[0].declared_camera_move == "static"
    assert plan.to_dict()["shots"][0]["declared_camera_move"] == "static"
    # 缺省是空串（不是 None）：契约串那一侧拿 `getattr(..., "")` 读它，
    # 空串与"没有声明"是同一件事，不制造第三种状态。
    bare = Plan.from_dict({"shots": [
        {"shot_id": "shot_002", "intent": "y", "shot_type": "MS",
         "duration_frames": 24}]})
    assert bare.shots[0].declared_camera_move == ""


def test_repo_wide_scan_finds_no_screen_direction_outside_fixtures():
    """死字段扫描：``contracts/plan.py`` 与派生夹具里零命中。

    注释/文档里出现这个词是允许的（它记录了 v1.4 的决策）；要守住的是
    **字段本身**与**会被序列化的产物**。
    """
    result = subprocess.run(
        ["rg", "-n", "screen_direction",
         str(ROOT / "block_director" / "contracts" / "plan.py"),
         str(ROOT / "fixtures")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    hits = [line for line in result.stdout.splitlines() if line.strip()]
    assert hits == [], hits
