"""Ticket 02：前向空间设计转换器（brief -> 设计快照）TDD 测试。

钉死：把理解剧本后的散文语义（SceneBrief space/environment/gaze/props）与
计划意图（站位/动作/机位）确定性转换成版本化「空间设计快照」：每角色
position/rotation/motion/gaze/facing + provenance；每物品 position/rotation/
motion/owner/parent/kind；锚点经求解器解出 label->坐标（解不出如实记，
不伪造精确解）；每镜机位设计值。本文件不 import bpy；实现模块用 AST 对拍
不 import bpy（红线保持）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from block_director.cinema.spatial_design import (
    build_design_snapshot,
    resolve_camera_intents,
)

ROOT = Path(__file__).resolve().parents[1]


def _no_bpy_import(module: Path) -> bool:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any("bpy" in (alias.name or "") for alias in node.names):
                return False
        if isinstance(node, ast.ImportFrom):
            if "bpy" in (node.module or ""):
                return False
    return True


def _brief():
    """合成 SceneBrief 形状：散文语义层（与 contracts/brief.py 字段一致）。"""
    return {
        "speakers": [
            {"speaker": "米迦尔", "listener": "伊恩"},
            {"speaker": "伊恩", "listener": "米迦尔"},
        ],
        "gaze": [
            {"from": "米迦尔", "to": "伊恩", "scope": "all"},
        ],
        "beats": [],
        "space": [
            {"character": "米迦尔", "relative_to": "伊恩",
             "relation": "side_by_side", "distance_class": "near"},
        ],
        "environment": [
            {"label": "生蚝摊", "direction": "left", "distance": "near",
             "size": "m", "mood": ""},
            {"label": "银币摊", "direction": "right", "distance": "mid",
             "size": "m", "mood": ""},
        ],
        "arc": {},
        "props": [
            {"id": "银币", "kind": "coin", "owner": "偷盗者",
             "state_changes": [{"to": "双手捧着"}]},
        ],
        "notes": [],
    }


def _plan():
    """合成计划形状（ShotPlan.to_dict 的 dict 版本，够转换器消费的字段）。"""
    return {
        "shot_id": "shot_001",
        "intent": "建立",
        "shot_type": "MS",
        "duration_frames": 120,
        "order": 1,
        "characters": ["米迦尔", "伊恩"],
        "actions": [
            {"action_type": "walk_to", "character_id": "伊恩",
             "params": {"target_position": [2.0, -1.0, 0.0]}},
            {"action_type": "look_at", "character_id": "米迦尔",
             "params": {"target": "伊恩"}},
        ],
        "dialogues": [],
        "prompt": "",
        "camera": {"side": "front", "lens": 35.0},
        "axis_note": "",
        "continuity_in": "",
        "gaze": [{"from": "米迦尔", "to": "伊恩"}],
        "vfx": [],
        "composition": {},
        "rule_justifications": [],
        "responsibility": None,
    }


def _cast_positions():
    """角色站位声明（plan_intent 源：initial_location）。"""
    return {
        "米迦尔": [0.0, 0.0, 0.0],
        "伊恩": [2.0, 0.0, 0.0],
        "偷盗者": [4.0, 1.0, 0.0],
    }


def test_design_converter_pure_layer_never_imports_bpy():
    source = ROOT / "block_director" / "cinema" / "spatial_design.py"
    assert _no_bpy_import(source)


def test_character_full_fields_enter_snapshot():
    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    assert snap["schema_version"].startswith("spatial-design-snapshot/")
    chars = {item["name"]: item for item in snap["characters"]}
    assert "米迦尔" in chars and "伊恩" in chars
    mika = chars["米迦尔"]
    # 站位声明直接入位（不脑补），来源 plan_intent
    assert mika["position"]["x"] == 0.0
    assert mika["provenance"] == "plan_intent"
    assert mika["unit"]["position"] == "m"
    # 视线：brief + plan 都说米迦尔看伊恩；目标站位已知 -> 方向向量可算
    assert mika["gaze"]["target_id"] == "伊恩"
    direction = mika["gaze"]["direction"]
    assert direction is not None and len(direction) == 3
    # 旋转与 facing 有结构、可空
    assert mika["rotation"] is None or isinstance(mika["rotation"], dict)
    ian = chars["伊恩"]
    # 运动意图：walk_to target -> motion 路径/终点
    assert ian["motion"]["end"] == [2.0, -1.0, 0.0]
    assert ian["motion"]["provenance"] == "plan_intent"


def test_cast_facings_drive_per_shot_heading_and_camera_side():
    plan = {
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "duration_frames": 48,
            "characters": ["米迦尔"],
            "shot_type": "MS",
            "camera": {"side": "front", "lens": 35.0},
        }],
    }
    snap = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={"米迦尔": [0.0, 0.0, 0.0]},
        cast_facings={"米迦尔": [1.0, 0.0, 0.0]},
        scene_id="market",
    )

    character = snap["characters"][0]
    camera = snap["camera_intents"][0]
    assert character["facing"] == [1.0, 0.0, 0.0]
    assert character["facing_by_shot"] == [{
        "shot_id": "shot_001",
        "direction": [1.0, 0.0, 0.0],
    }]
    # A front camera is on the side the subject faces, not a global +Y axis.
    assert camera["position"][0] > 0.0
    assert abs(camera["position"][1]) < 1e-9


def test_anchor_resolved_via_solver():
    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    anchors = {item["label"]: item for item in snap["anchors"]}
    assert "生蚝摊" in anchors and "银币摊" in anchors
    oyster = anchors["生蚝摊"]
    # 锚点坐标来自求解器（algorithmic_measurement），不是模型猜
    assert oyster["provenance"] == "algorithmic_measurement"
    assert len(oyster["position"]) == 3
    assert all(isinstance(v, (int, float)) for v in oyster["position"])


def test_anchor_unresolved_is_honest_not_fake():
    brief = _brief()
    brief["environment"] = [
        # direction 取闭集外（非法语义）-> 转换器无法确定落位，必须如实记
        {"label": "神秘物件", "direction": "diagonal", "distance": "near",
         "size": "m", "mood": ""},
    ]
    snapshot = build_design_snapshot(
        brief=brief, plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    # 非法语义不能伪造"精确解"：标 resolved=False + 留痕。
    anchor = snapshot["anchors"][0]
    assert anchor["label"] == "神秘物件"
    assert anchor["resolved"] is False
    assert anchor.get("unresolved_reason")
    reasons = [note for note in snapshot["notes"] if "神秘物件" in note]
    assert reasons, "未解析锚点必须留痕，不许静默伪造"


def test_plan_environment_anchors_enter_snapshot():
    """R2-F5/F7：粗排参考 JSON 的 anchors 必须包含 plan.environment.anchors。

    粗排 headless 路径不传 brief（deterministic 空兜底），但 Stage A 的计划
    已含闭集方位锚点。若转换器只读 brief.environment，银币摊/海面等明确
    主体就丢了——shot_002 空墙根因。两种契约形状都要进快照：
    ``{label, direction, distance}``（plan 闭集词）与 SDL
    ``{name, relation}``。
    """
    plan = dict(_plan())
    plan["environment"] = {
        "anchors": [
            {"label": "银币摊", "direction": "right", "distance": "mid",
             "size": "m", "mood": ""},
            {"name": "生蚝摊", "relation": "left_of 米迦尔 2m"},
        ],
    }
    snapshot = build_design_snapshot(
        brief={}, plan=plan, cast_positions=_cast_positions(),
        scene_id="market")
    anchors = {item["label"]: item for item in snapshot["anchors"]}
    assert "银币摊" in anchors and anchors["银币摊"]["resolved"] is True
    assert "生蚝摊" in anchors and anchors["生蚝摊"]["resolved"] is True
    coin = anchors["银币摊"]
    assert coin["position"][0] > 0  #: right -> +X
    assert coin["provenance"] == "algorithmic_measurement"


def test_duplicate_anchor_labels_are_deduped_not_crashed():
    """R2 真跑 20261020-market-real-final2：锚点不按 label 去重。

    同一物理锚点会以两种契约形状各来一次：brief.environment 的
    ``{label, direction, distance}`` 与 plan.environment.anchors 的 SDL
    ``{name, relation}``。不清重在 manifest 生成同名体块（anchor_海面），
    场景构建第二次 `_place_box` 抛"体块对象已存在"，粗排门整体中断。
    断言：同标签只留一条；首个 resolved 生效且不被后续覆盖；顺序保持。
    """
    brief = {
        "environment": [
            {"label": "海面", "direction": "back", "distance": "far",
             "size": "l", "mood": ""},
            {"label": "生蚝摊", "direction": "left", "distance": "near",
             "size": "s", "mood": ""},
        ],
        "props": [],
    }
    plan = dict(_plan())
    plan["environment"] = {
        "anchors": [
            {"name": "海面", "relation": "正后景深处的高饱和晴天海面"},
            {"name": "生蚝摊", "relation": "画面左侧近景的摊档陈设"},
        ],
    }
    snapshot = build_design_snapshot(
        brief=brief, plan=plan, cast_positions=_cast_positions(),
        scene_id="market")
    anchors = snapshot["anchors"]
    labels = [str(a.get("label") or "") for a in anchors]
    assert labels == ["海面", "生蚝摊"], f"锚点应去重且保序，实际 {labels}"
    by_label = {str(a.get("label") or ""): a for a in anchors}
    #: 首个 resolved（brief direction+distance）生效，带 note，不被后覆盖
    sea = by_label["海面"]
    assert sea["resolved"] is True
    assert sea.get("note"), "首条 direction+distance 解析应保留 note"
    assert sea["position"] == [0.0, -12.0, 0.0]


def test_unresolved_anchor_replaced_by_later_resolved():
    """同标签首条 unresolved 时，允许被后续 resolved 条目替换（不丢主体）。"""
    brief = {
        "environment": [
            {"label": "银币摊", "direction": "diagonal", "distance": "near",
             "size": "m", "mood": ""},
        ],
        "props": [],
    }
    plan = dict(_plan())
    plan["environment"] = {
        "anchors": [
            {"label": "银币摊", "direction": "right", "distance": "near",
             "size": "m", "mood": ""},
        ],
    }
    snapshot = build_design_snapshot(
        brief=brief, plan=plan, cast_positions=_cast_positions(),
        scene_id="market")
    anchors = [a for a in snapshot["anchors"]
               if str(a.get("label") or "") == "银币摊"]
    assert len(anchors) == 1
    assert anchors[0]["resolved"] is True
    assert anchors[0]["position"][0] > 0.0


def test_camera_intent_from_framing():
    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    cams = {item["shot_id"]: item for item in snap["camera_intents"]}
    assert "shot_001" in cams
    cam = cams["shot_001"]
    # 机位来自 framing 求解（algorithmic_measurement）：position/target/lens 齐
    assert cam["provenance"] == "algorithmic_measurement"
    assert len(cam["position"]) == 3 and len(cam["target"]) == 3
    assert cam["lens"] > 0.0
    assert cam["fov_deg"] > 0.0


def test_auto_two_person_camera_stays_off_axis_and_keeps_screen_side():
    """自动双人机位必须离开人物连线，且角色列表反序也不能换到另一侧。"""
    plan = {
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 48,
                "characters": ["米迦尔", "伊恩"],
                "shot_type": "MS",
                "camera": {},
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 48,
                "characters": ["伊恩", "米迦尔"],
                "shot_type": "MS",
                "camera": {},
            },
        ],
    }
    snapshot = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={
            "米迦尔": [-0.9, 0.0, 0.0],
            "伊恩": [0.9, 0.0, 0.0],
        },
        cast_facings={
            "米迦尔": [1.0, 0.0, 0.0],
            "伊恩": [-1.0, 0.0, 0.0],
        },
        scene_id="dialogue",
    )

    cameras = {item["shot_id"]: item for item in snapshot["camera_intents"]}
    sides = []
    for camera in cameras.values():
        x, y = camera["position"][:2]
        sides.append((0.9 - (-0.9)) * (y - 0.0))

    assert sides[0] != pytest.approx(0.0), cameras
    assert sides[1] != pytest.approx(0.0), cameras
    assert sides[0] * sides[1] > 0.0, cameras


def test_explicit_two_person_camera_side_remains_director_intent():
    """显式 side 是导演声明，不因自动轴线法线而改到另一侧。"""
    plan = {
        "shot_id": "shot_001",
        "order": 1,
        "duration_frames": 48,
        "characters": ["米迦尔", "伊恩"],
        "shot_type": "MS",
        "camera": {"side": "right"},
    }
    snapshot = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={
            "米迦尔": [-0.9, 0.0, 0.0],
            "伊恩": [0.9, 0.0, 0.0],
        },
        cast_facings={
            "米迦尔": [1.0, 0.0, 0.0],
            "伊恩": [-1.0, 0.0, 0.0],
        },
        scene_id="dialogue",
    )

    camera = snapshot["camera_intents"][0]
    assert camera["side"] == "right"
    assert camera["side_provenance"] == "plan_intent"
    assert abs(camera["position"][0]) < 1e-9
    assert camera["position"][1] < 0.0


def test_empty_shot_is_valid_snapshot():
    plan = dict(_plan())
    plan["characters"] = []
    plan["actions"] = []
    snap = build_design_snapshot(
        brief={}, plan=plan, cast_positions={}, scene_id="empty")
    assert snap["characters"] == []
    assert snap["camera_intents"]  # 空镜仍有机位设计（建立/留白/转场）


def test_deterministic_two_builds_identical():
    first = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    second = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == \
        json.dumps(second, sort_keys=True, ensure_ascii=False)


def test_plan_character_without_position_is_honest():
    """角色在计划里但无站位声明：不脑补坐标，记 note 且 position 可空/缺省显式。"""
    plan = dict(_plan())
    plan["characters"] = ["神秘人"]
    cast = dict(_cast_positions())
    cast.pop("神秘人", None)
    snap = build_design_snapshot(
        brief=_brief(), plan=plan, cast_positions=cast, scene_id="market")
    names = [item["name"] for item in snap["characters"]]
    assert "神秘人" in names
    notes = [note for note in snap["notes"] if "神秘人" in note]
    assert notes, "计划里无站位的角色必须留痕，不得静默落默认坐标"


def test_owned_prop_with_cast_position_resolves_to_hand():
    """手持道具（brief.props owner）在 owner 有站位时，用冻结手部几何
    确定性解析坐标（剧本"偷盗者掌中银币"是明确归属，不是猜）；推导来源
    留痕（provenance + note），可被后续实测覆盖。"""
    from block_director.cinema.anchor import (
        DEFAULT_PROFILE,
        HAND_PROXY_FORWARD,
        HAND_PROXY_SIDE,
    )

    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    prop = next(p for p in snap["props"] if str(p.get("id") or "") == "银币")
    assert prop["position"] is not None, \
        "owner 有站位的持道具必须解析出坐标，否则 ECU 拍点无体块"
    owner_pos = _cast_positions()["偷盗者"]
    expected = (
        round(float(owner_pos[0]) + HAND_PROXY_SIDE, 4),
        round(float(owner_pos[1]) + HAND_PROXY_FORWARD, 4),
        round(DEFAULT_PROFILE.chest_z, 4),
    )
    got = tuple(prop["position"])
    assert got == expected, f"手持道具坐标应为 {expected}，实际 {got}"
    #: 推导来源可追溯：避免把"脑补"伪装成"剧本声明"
    assert prop["provenance"] == "algorithmic_measurement"
    note_hits = [n for n in snap["notes"]
                 if "银币" in n and "手" in n]
    assert note_hits, "由 owner 站位+冻结几何推导必须留痕说明"


@pytest.mark.parametrize(
    ("facing", "expected_xy"),
    [
        ([0.0, -1.0, 0.0], (3.78, 0.75)),
        ([1.0, 0.0, 0.0], (4.25, 0.78)),
    ],
)
def test_owned_prop_hand_position_follows_owner_facing(facing, expected_xy):
    """Hand props rotate with their owner instead of using global XY offsets."""
    from block_director.cinema.anchor import DEFAULT_PROFILE

    snap = build_design_snapshot(
        brief=_brief(),
        plan=_plan(),
        cast_positions=_cast_positions(),
        cast_facings={"偷盗者": facing},
        scene_id="market",
    )
    prop = next(p for p in snap["props"] if p["id"] == "银币")

    assert tuple(prop["position"][:2]) == expected_xy
    assert prop["position"][2] == round(DEFAULT_PROFILE.chest_z, 4)


def test_owned_prop_without_owner_position_stays_unresolved():
    """owner 在剧本/计划里但没有站位：不得用世界原点脑补，保持 None + note。"""
    cast = dict(_cast_positions())
    cast.pop("偷盗者", None)
    snap = build_design_snapshot(
        brief=_brief(), plan=_plan(), cast_positions=cast, scene_id="market")
    prop = next(p for p in snap["props"] if str(p.get("id") or "") == "银币")
    assert prop["position"] is None
    note_hits = [n for n in snap["notes"] if "银币" in n]
    assert note_hits, "无站位的持道具必须留痕，不得静默落坐标"


def test_unowned_prop_without_position_stays_unresolved():
    """非持道具（无 owner）且无坐标：不猜位置，维持原有纪律。"""
    brief = dict(_brief())
    brief["props"] = [{"id": "钱袋", "kind": "prop", "owner": None}]
    snap = build_design_snapshot(
        brief=brief, plan=_plan(), cast_positions=_cast_positions(),
        scene_id="market")
    prop = next(p for p in snap["props"] if str(p.get("id") or "") == "钱袋")
    assert prop["position"] is None


def test_resolve_camera_intents_aims_local_part():
    """局部拍对象（hand/face）时相机瞄准点必须落在被摄局部中心。

    旧冻结 reference 的 camera_intents 整身对准（target z 落在头高带）；
    细排构图重测前重解相机意图，hand 镜 target z 应等于 chest_z、face 镜应
    等于 head_center_z——否则局部主体框投影后 inside_ratio≈0 -> 构图硬闸
    20 分，细排 gate 永远过不了。
    """
    from block_director.cinema.anchor import DEFAULT_PROFILE, coarse_local_bounds
    from block_director.cinema.blockout import KIND_SIZE_BANDS

    cast = _cast_positions()
    plan = _plan()
    design = build_design_snapshot(
        brief=_brief(), plan=plan, cast_positions=cast, scene_id="market")
    reference = dict(design)
    reference["shots"] = [
        {
            "shot_id": "shot_001",
            "shot_type": "CU",
            "characters": ["米迦尔"],
            "composition": {"subject_position": "center"},
            "framing_target": {
                "kind": "character", "ref": "米迦尔", "part": "hand",
            },
        },
        {
            "shot_id": "shot_002",
            "shot_type": "ECU",
            "characters": ["偷盗者"],
            "framing_target": {
                "kind": "character", "ref": "偷盗者", "part": "face",
            },
        },
    ]
    refreshed = resolve_camera_intents(reference)
    intents = {str(i.get("shot_id") or ""): i
               for i in (refreshed.get("camera_intents") or [])}
    hand = intents.get("shot_001")
    face = intents.get("shot_002")
    assert hand is not None and face is not None
    assert abs(hand["target"][2] - DEFAULT_PROFILE.chest_z) < 1e-6
    assert abs(face["target"][2] - DEFAULT_PROFILE.head_center_z) < 1e-6
    character = next(
        item for item in reference["characters"]
        if str(item.get("name") or "") == "米迦尔")
    width, depth, height = KIND_SIZE_BANDS["character"]
    hand_bounds = coarse_local_bounds(
        kind="character", part="hand",
        low=(cast["米迦尔"][0] - width / 2.0,
             cast["米迦尔"][1] - depth / 2.0,
             cast["米迦尔"][2]),
        high=(cast["米迦尔"][0] + width / 2.0,
              cast["米迦尔"][1] + depth / 2.0,
              cast["米迦尔"][2] + height),
        facing=character["facing"])
    assert hand_bounds is not None
    hand_center = tuple(
        (hand_bounds[0][axis] + hand_bounds[1][axis]) / 2.0
        for axis in range(3))
    assert abs(hand["target"][0] - hand_center[0]) < 1e-6
    assert abs(hand["target"][1] - hand_center[1]) < 1e-6
    #: 站位本身不能被重解动（空间不漂移）
    assert refreshed["characters"] == reference["characters"]
