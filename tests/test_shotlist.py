"""分镜表解析（v1.3 执行计划 附录 C）。

验收基准是用户真实交来的那份 6 镜分镜表：声明总时长必须是 **33 秒**
（v1.2 会把它规划成 39.5 秒，并压成 2 个镜号）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from block_director.layer1_input import (
    looks_like_shot_list,
    parse_script,
    parse_shot_list,
    parse_text,
)

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "fixtures" / "shotlist_market.md"


def _market():
    return parse_script(MARKET)


# --------------------------------------------------------------------------- #
# 识别
# --------------------------------------------------------------------------- #
def test_detects_a_shot_list():
    assert looks_like_shot_list(MARKET.read_text(encoding="utf-8"))


def test_does_not_mistake_a_narrative_script_for_a_shot_list():
    fountain = (ROOT / "fixtures" / "script_simple.fountain").read_text(
        encoding="utf-8")
    assert not looks_like_shot_list(fountain)
    assert not looks_like_shot_list("")
    assert not looks_like_shot_list("INT. 房间 - 日\n\n小明坐下。\n")


def test_parse_text_routes_shot_lists_to_the_shot_list_parser():
    script = parse_text(MARKET.read_text(encoding="utf-8"))
    assert script.source_format == "shotlist"
    assert script.declared_shots


def test_narrative_scripts_still_go_through_the_old_path():
    script = parse_script(ROOT / "fixtures" / "script_simple.fountain")
    assert script.source_format == "fountain"
    assert script.declared_shots == []


# --------------------------------------------------------------------------- #
# 真实分镜表：这是本次改动的验收基准
# --------------------------------------------------------------------------- #
def test_market_shot_list_declares_six_shots_and_33_seconds():
    script = _market()
    assert len(script.scenes) == 4                 # 4 个节点
    assert [shot.shot_number for shot in script.declared_shots] == \
        [1, 2, 3, 4, 5, 6]
    assert script.declared_total_seconds == pytest.approx(33.0)
    assert script.dialogue_count == 6
    assert sorted(script.character_names) == sorted(["米迦尔", "伊恩", "偷盗者"])
    assert script.warnings == []                   # 节点时长自洽


def test_market_node_totals_are_self_consistent():
    script = _market()
    for node in script.declared_nodes:
        assert node.declared_seconds == pytest.approx(node.declared_shot_seconds)


def test_market_per_shot_declarations():
    shots = {shot.shot_number: shot for shot in _market().declared_shots}
    assert shots[1].declared_seconds == pytest.approx(5.0)
    assert shots[1].shot_type == "MCU"             # 近景（地面草影）→ 中近景
    assert shots[1].camera_move == "static"        # 固定镜头
    assert shots[2].shot_type == "CU"              # 面部特写
    assert shots[2].camera_move == "dolly_in"      # 快速推镜
    assert shots[5].camera_move == "follow_subject"  # 跟拍镜头
    assert shots[6].declared_seconds == pytest.approx(7.0)
    # 画面内容里的分段被解析成时间码
    assert shots[1].timecodes == [(0.0, 3.0), (3.0, 5.0)]
    assert shots[6].timecodes == [(0.0, 2.0), (2.0, 3.0), (3.0, 6.0)]


def test_market_per_shot_dialogue_declarations():
    shots = {shot.shot_number: shot for shot in _market().declared_shots}
    assert shots[2].dialogue_count == 1
    assert shots[2].declared_dialogue_seconds == pytest.approx(3.0)
    assert shots[4].dialogue_count == 2            # 放心吧。+ 看我怎么惩罚他…
    assert shots[4].declared_dialogue_seconds == pytest.approx(5.0)
    assert shots[6].declared_dialogue_seconds == pytest.approx(7.0)
    assert shots[1].dialogue_count == 0


def test_market_characters_come_only_from_known_speakers():
    """``角色：背景有大量路人（约30人）…`` 不该凭空造出一个角色。"""
    shots = {shot.shot_number: shot for shot in _market().declared_shots}
    assert shots[1].characters == []
    assert shots[2].characters == ["米迦尔", "伊恩"]
    assert shots[3].characters == ["伊恩"]
    assert shots[5].characters == ["偷盗者"]


def test_market_scene_headings_come_from_location_and_time():
    headings = {scene.heading for scene in _market().scenes}
    assert headings == {"第十四街区码头市场 - 午后"}


# --------------------------------------------------------------------------- #
# 自洽校验：只报警、不阻断
# --------------------------------------------------------------------------- #
MINIMAL = """\
# 节点1：测试（总时长：10秒）

镜号：1
地点：房间
时间：白天
拍摄距离：近景
预估时长：4秒

镜号：2
地点：房间
时间：白天
拍摄距离：特写
预估时长：3秒
"""


def test_node_total_mismatch_is_reported_not_fatal():
    script, shot_list = parse_shot_list(MINIMAL)
    assert script.scenes                      # 仍然解析成功
    assert any("声明总时长" in problem for problem in shot_list.problems)


def test_missing_shot_duration_is_reported():
    text = MINIMAL.replace("预估时长：3秒\n", "")
    _script, shot_list = parse_shot_list(text)
    assert any("没有「预估时长」声明" in problem for problem in shot_list.problems)


def test_a_shot_list_without_nodes_still_parses():
    text = "镜号：1\n地点：房间\n预估时长：3秒\n\n镜号：2\n地点：房间\n预估时长：4秒\n"
    script, shot_list = parse_shot_list(text)
    assert [shot.shot_number for shot in shot_list.shots] == [1, 2]
    assert script.declared_total_seconds == pytest.approx(7.0)


def test_garbage_never_raises():
    for text in ("", "   ", "镜号：\n", "节点\n", "镜号：abc\n", "镜号：1\n" * 3):
        script, shot_list = parse_shot_list(text)
        assert script is not None and shot_list is not None


def test_dialogue_quotes_are_required_so_fields_are_not_eaten():
    """``角色：米迦尔、伊恩`` 是字段，不是台词——靠引号区分。"""
    text = "镜号：1\n角色：米迦尔、伊恩\n地点：房间\n预估时长：3秒\n"
    script, shot_list = parse_shot_list(text)
    assert shot_list.shots[0].field("角色") == "米迦尔、伊恩"
    assert script.dialogue_count == 0


# --------------------------------------------------------------------------- #
# 规划提示必须带上这些声明（R015 的提示侧）
# --------------------------------------------------------------------------- #
def test_plan_prompt_carries_the_declared_shot_list():
    from block_director.layer5_orchestrator.planner import build_plan_payload

    script = _market()
    payload = build_plan_payload(None, parsed=script)
    system = payload.messages[0].content
    assert "分镜表声明" in system and "硬约束" in system
    assert "镜号1" in system and "镜号6" in system
    assert "合计声明时长：33 秒" in system
    assert "共 6 个镜号" in system
    # 台词文本也在提示里，模型没有理由再自己编
    assert "伊恩，这里就交给我吧！" in system
    assert "哈哈，一定是命运眷顾，我发财了！" in system


def test_narrative_scripts_add_no_declared_block():
    from block_director.layer5_orchestrator.planner import build_plan_payload

    script = parse_script(ROOT / "fixtures" / "script_simple.fountain")
    system = build_plan_payload(None, parsed=script).messages[0].content
    assert "分镜表声明" not in system
