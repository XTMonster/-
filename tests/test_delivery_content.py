"""§15.4 / §15.5 镜头清单与 Prompt 表的纯计算测试。"""

from __future__ import annotations

import json

from block_director.contracts.plan import Plan, ShotPlan
from block_director.delivery.manifest import build_manifest
from block_director.delivery.prompts import compose_prompt, render_prompt_sheet


def demo_plan() -> Plan:
    first = ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "建立两人关系",
        "shot_type": "MLS", "duration_frames": 96,
        "characters": ["char_001", "char_002"],
        "dialogue_ids": ["line_01"],
        "actions": [{"character_id": "char_001", "action_type": "nod"}],
    })
    second = ShotPlan.from_dict({
        "shot_id": "shot_002", "order": 2, "intent": "推进对话",
        "shot_type": "MCU", "duration_frames": 120,
        "characters": ["char_002"],
        "prompt": "咖啡馆内，单人近景，暖色光线",
    })
    return Plan(shots=[first, second], scene_heading="INT. 咖啡馆 - 日")


BUILD_SUMMARY = {
    "results": [
        {"shot_id": "shot_001", "start_frame": 1, "end_frame": 96,
         "camera": "BD_Cam_shot_001", "camera_position": [0.0, 3.975, 0.95],
         "lens": 35.0, "warnings": []},
        {"shot_id": "shot_002", "start_frame": 97, "end_frame": 216,
         "camera": "BD_Cam_shot_002", "camera_position": [0.75, 2.469, 1.05],
         "lens": 50.0, "warnings": ["取景 shot_002：机位被房间边界夹回"]},
    ]
}


# --------------------------------------------------------------------------- #
# 镜头清单
# --------------------------------------------------------------------------- #
def test_manifest_shape_and_metadata():
    manifest = build_manifest(demo_plan(), build_summary=BUILD_SUMMARY,
                              resolution=(1280, 720), style="温暖写实",
                              generated_at="2026-09-28T22:00:00+08:00")
    assert manifest["fps"] == 24
    assert manifest["resolution"] == [1280, 720]
    assert manifest["style"] == "温暖写实"
    assert manifest["generated_at"] == "2026-09-28T22:00:00+08:00"
    assert manifest["total_frames"] == 216
    assert len(manifest["shots"]) == 2
    json.dumps(manifest, ensure_ascii=False)      # 必须可 JSON 序列化


def test_manifest_takes_frames_from_build_summary():
    manifest = build_manifest(demo_plan(), build_summary=BUILD_SUMMARY)
    first, second = manifest["shots"]
    assert (first["start_frame"], first["end_frame"]) == (1, 96)
    assert (second["start_frame"], second["end_frame"]) == (97, 216)
    assert second["duration_seconds"] == 5.0


def test_manifest_falls_back_when_build_summary_missing():
    """没有构建结果时也要能产出清单（按计划时长自行排片）。"""
    manifest = build_manifest(demo_plan())
    assert [s["start_frame"] for s in manifest["shots"]] == [1, 97]
    assert manifest["total_frames"] == 216


def test_manifest_carries_paths_and_camera():
    first = build_manifest(demo_plan(), build_summary=BUILD_SUMMARY)["shots"][0]
    assert first["video_file"] == "blockout_shot_001.mp4"
    assert first["first_frame"] == "first_frames/shot_001.png"
    assert first["camera"]["name"] == "BD_Cam_shot_001"
    assert first["camera"]["lens"] == 35.0


def test_manifest_marks_degraded_shots():
    shots = build_manifest(demo_plan(), build_summary=BUILD_SUMMARY)["shots"]
    assert shots[0]["degraded"] is False
    assert shots[1]["degraded"] is True
    assert "夹回" in shots[1]["warnings"][0]


# --------------------------------------------------------------------------- #
# Prompt 表
# --------------------------------------------------------------------------- #
def test_prompt_sheet_lists_every_shot():
    sheet = render_prompt_sheet(demo_plan(), style="写实电影质感")
    assert "## shot_001" in sheet and "## shot_002" in sheet
    assert "建立两人关系" in sheet


def test_prompt_sheet_headers_are_well_spaced():
    """标题与场景引用之间要有空行，否则渲染出来会黏在一起。"""
    sheet = render_prompt_sheet(demo_plan())
    assert "# BlockDirector — 分镜 Prompt 表\n\n> 场景：" in sheet
    assert "\n\n- 参考视频分辨率：" in sheet


def test_prompt_sheet_uses_plan_prompt_when_present():
    sheet = render_prompt_sheet(demo_plan())
    assert "咖啡馆内，单人近景，暖色光线" in sheet


def test_prompt_sheet_composes_prompt_from_intent_when_absent():
    sheet = render_prompt_sheet(demo_plan(), style="柔和自然光")
    # shot_001 没有 prompt 字段，应由意图 + 景别 + 风格拼出来
    assert "建立两人关系，中远景，固定机位，柔和自然光" in sheet


def test_prompt_sheet_includes_frame_ranges_and_paths():
    sheet = render_prompt_sheet(demo_plan())
    assert "1–96" in sheet and "97–216" in sheet
    assert "export/blockout_shot_001.mp4" in sheet
    assert "export/first_frames/shot_001.png" in sheet


def test_prompt_sheet_mentions_characters_and_actions():
    sheet = render_prompt_sheet(demo_plan())
    assert "char_001、char_002" in sheet
    assert "nod" in sheet


def test_compose_prompt_skips_empty_parts():
    assert compose_prompt("", "MS", "") == "中景，固定机位"
    assert compose_prompt("转身", "CU", "冷调") == "转身，特写，固定机位，冷调"
