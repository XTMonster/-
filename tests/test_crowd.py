"""群众声明的确定性抽取与 SDL 往返（v1.3 §3.6）。"""

from __future__ import annotations

from pathlib import Path

from block_director.contracts.cast import SceneSpec, crowd_from_script
from block_director.contracts.plan import Plan
from block_director.layer1_input import parse_script, parse_text
from block_director.layer2_sdl import build_sdl, sdl_to_spec, validate_sdl

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / "fixtures" / "shotlist_market.md"

SHOTLIST = """\
节点1：市场（总时长：5秒）
镜号：1
拍摄手法：固定镜头
角色：背景有大量路人（约30人）在市场行走、交易
预估时长：5秒
"""


def _script(text: str):
    return parse_text(text, title="市场")


def test_crowd_is_extracted_from_the_declaration():
    entries = crowd_from_script(_script(SHOTLIST))
    assert [item["count"] for item in entries] == [30]
    assert entries[0]["mode"] == "walk"
    assert "路人" in entries[0]["label"]


def test_the_real_market_script_declares_thirty_extras():
    entries = crowd_from_script(parse_script(MARKET))
    assert entries and sum(item["count"] for item in entries) == 30


def test_crowd_is_capped_and_can_be_switched_off():
    assert sum(item["count"] for item in
               crowd_from_script(_script(SHOTLIST), max_instances=12)) == 12
    assert crowd_from_script(_script(SHOTLIST), enabled=False) == []
    assert crowd_from_script(_script(SHOTLIST), max_instances=0) == []


def test_a_script_without_extras_produces_none():
    text = ("节点1：房间（总时长：4秒）\n镜号：1\n角色：甲、乙\n"
            "预估时长：4秒\n")
    assert crowd_from_script(_script(text)) == []


def test_total_instances_never_exceed_the_cap():
    text = ("节点1：市场（总时长：4秒）\n镜号：1\n角色：人群 约20人\n"
            "预估时长：4秒\n镜号：2\n角色：路人 约20人\n预估时长：4秒\n")
    entries = crowd_from_script(_script(text), max_instances=25)
    # 同一场戏的多个镜头提到的是同一批人 → 取最大值（20），不是 40
    assert sum(item["count"] for item in entries) == 20
    capped = crowd_from_script(_script(text), max_instances=12)
    assert sum(item["count"] for item in capped) == 12


def test_spec_and_sdl_carry_the_crowd():
    plan = Plan.from_dict({
        "scene_heading": "第十四街区码头市场 - 午后",
        "shots": [{"shot_id": "shot_001", "order": 1, "intent": "建立",
                   "shot_type": "LS", "duration_frames": 120,
                   "characters": ["char_001"]}]})
    crowd = crowd_from_script(_script(SHOTLIST))
    spec = SceneSpec.from_plan(plan, crowd=crowd)
    assert spec.crowd == crowd
    sdl = build_sdl(plan, spec=spec)
    assert validate_sdl(sdl) == []
    assert sdl.scenes[0].environment.crowd[0]["count"] == 30
    assert sdl_to_spec(sdl).crowd == crowd
