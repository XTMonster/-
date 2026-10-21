"""Fix B TDD：粗排机位设计必须尊重 ``framing_target``（人物拍对象）。

回归 final12 真跑（``docs/evidence/20261020-market-real-final12/``，
run ``df5538a9578a``）：shot_003 是三人镜（MCU，characters=
[偷盗者, 米迦尔, 伊恩]），``framing_target={kind:character, ref:偷盗者}``。
旧实现 ``_camera_intent`` 无视拍对象，按**全组质心** (−0.6, 2.13) 求解且
MCU 自动放宽为 MLS，相机落到 [−0.6, 6.79, ...]——米迦尔/伊恩恰好在相机
与拍对象（偷盗者）之间，``E_BLOCKOUT_EMPTY_WALL`` +
``E_FOREGROUND_OCCLUSION`` 恒报，处方只拉远相机永远消不掉，粗排 gate
4 次评估不过、best=-7、无法进入细排。

Fix B：``kind=character`` 且 ref 在站位声明里时，机位以**该角色**为
subject（组列表只含主体 → 多人 MLS 放宽分支自然不触发）；无
``framing_target`` 时保持组质心旧行为零变化。判定与阈值一字未动。

本文件不 import bpy。
"""

from __future__ import annotations

import pytest

from block_director.cinema.anchor import coarse_local_bounds
from block_director.cinema.blockout import KIND_SIZE_BANDS
from block_director.cinema.framing import required_distance, shot_frame_for
from block_director.cinema.spatial_design import build_design_snapshot


def _shot_003_plan(*, with_target: bool) -> dict:
    """final12 shot_003 的确定性复刻（站位/景别/角色清单对齐真跑）。"""
    shot = {
        "shot_id": "shot_003",
        "intent": "释放——偷盗者捧金狂喜大笑，情绪向外释放",
        "shot_type": "MCU",
        "duration_frames": 265,
        "order": 3,
        "characters": ["偷盗者", "米迦尔", "伊恩"],
        "actions": [],
        "dialogues": [],
        "camera": {},
        "gaze": [],
        "vfx": [],
        "framing_target": None,
    }
    if with_target:
        shot["framing_target"] = {
            "kind": "character", "ref": "偷盗者",
            "part": "face", "anchor_offset": None,
        }
    return {"scene_heading": "EXT. 第十四街区码头市场 - 白天", "shots": [shot]}


def _cast_positions() -> dict:
    """final12 真跑站位（SceneSpec.from_plan 的 initial_location）。"""
    return {
        "偷盗者": [0.0, 0.0, 0.0],
        "米迦尔": [0.0, 3.2, 0.0],
        "伊恩": [-1.8, 3.2, 0.0],
    }


def _camera(plan: dict) -> dict:
    snap = build_design_snapshot(
        brief={}, plan=plan, cast_positions=_cast_positions(),
        scene_id="market")
    cams = {item["shot_id"]: item for item in snap["camera_intents"]}
    assert "shot_003" in cams, f"应有 shot_003 机位，实际 {sorted(cams)}"
    return cams["shot_003"]


def test_camera_intent_aims_framing_target_character_not_group_centroid():
    """拍对象=偷盗者：机位必须瞄偷盗者，而不是三人质心。"""
    cam = _camera(_shot_003_plan(with_target=True))
    assert cam["resolved"] is True
    #: 瞄拍对象站位（偷盗者 [0,0,0]，EYE_Z 级 target），而非组质心
    #: (−0.6, 2.13)。容差放 0.35m：aim 偏移允许 target 略离中心。
    assert abs(cam["target"][0]) < 0.35, f"target.x 应近 0，实际 {cam['target']}"
    assert abs(cam["target"][1]) < 0.35, f"target.y 应近 0，实际 {cam['target']}"


def test_camera_intent_framing_target_keeps_close_mcu_not_mls():
    """拍对象单主体：不触发多人 MLS 放宽，机位应是近景 MCU 距离。"""
    cam = _camera(_shot_003_plan(with_target=True))
    #: MLS 放宽后相机 y≈6.79（final12 实测）；MCU 单人距离 ≈1.7m，
    #: 所以 y（横向偏移轴）必须远小于 4.0。
    assert cam["position"][1] < 4.0, \
        f"MCU 单人机位不应退成 MLS 距离，实际 position={cam['position']}"
    assert cam["lens"] > 0.0 and cam["fov_deg"] > 0.0


def test_camera_intent_without_framing_target_keeps_group_centroid():
    """无 framing_target：保持组质心 + 多人 MLS 放宽（旧行为零变化）。"""
    cam = _camera(_shot_003_plan(with_target=False))
    assert cam["resolved"] is True
    #: 组质心 x = (−1.8+0+0)/3 = −0.6；y = (0+3.2+3.2)/3 ≈ 2.133
    assert abs(cam["target"][0] - (-0.6)) < 0.35, \
        f"无拍对象应瞄组质心 x≈−0.6，实际 {cam['target']}"
    assert abs(cam["target"][1] - (2.0 * 3.2 / 3.0)) < 0.35, \
        f"无拍对象应瞄组质心 y≈2.13，实际 {cam['target']}"
    #: MLS 放宽：相机退得更远（y 明显大于单人 MCU 的 <4.0）
    assert cam["position"][1] > 4.5, \
        f"多人无拍对象应 MLS 放宽，实际 position={cam['position']}"


def test_camera_intent_target_character_ref_missing_falls_back_group():
    """拍对象角色不在站位声明（脏引用）：不脑补，回退组质心旧行为。"""
    plan = _shot_003_plan(with_target=True)
    plan["shots"][0]["framing_target"] = {
        "kind": "character", "ref": "不存在角色", "part": "face",
        "anchor_offset": None,
    }
    cam = _camera(plan)
    assert cam["resolved"] is True
    assert abs(cam["target"][0] - (-0.6)) < 0.35, \
        f"脏引用应回退组质心，实际 {cam['target']}"


def _local_camera(
    part: str,
    *,
    shot_type: str = "CU",
    composition: dict | None = None,
) -> tuple[dict, tuple[float, float, float]]:
    """单角色局部拍对象：返回相机意图与冻结几何推导的局部中心。"""
    position = (2.0, -1.0, 0.0)
    plan = {
        "scene_heading": "INT. 局部锚点测试",
        "shots": [{
            "shot_id": "shot_local", "intent": f"{part} 局部",
            "shot_type": shot_type, "duration_frames": 48, "order": 1,
            "characters": ["偷盗者"], "actions": [], "dialogues": [],
            "camera": {
                "side": "front",
                "composition": composition,
            },
            "gaze": [], "vfx": [],
            "framing_target": {
                "kind": "character", "ref": "偷盗者", "part": part,
                "anchor_offset": None,
            },
        }],
    }
    snapshot = build_design_snapshot(
        brief={}, plan=plan, cast_positions={"偷盗者": position},
        scene_id="local")
    camera = next(
        item for item in snapshot["camera_intents"]
        if item["shot_id"] == "shot_local")

    width, depth, height = KIND_SIZE_BANDS["character"]
    bounds = coarse_local_bounds(
        kind="character", part=part,
        low=(position[0] - width / 2.0,
             position[1] - depth / 2.0, position[2]),
        high=(position[0] + width / 2.0,
              position[1] + depth / 2.0, position[2] + height),
        facing=(0.0, 1.0, 0.0))
    assert bounds is not None
    center = tuple(
        (bounds[0][axis] + bounds[1][axis]) / 2.0 for axis in range(3))
    return camera, center


@pytest.mark.parametrize("part", ["hand", "face"])
def test_local_camera_target_uses_same_xyz_local_anchor(part):
    """局部机位 x/y 不得继续停在整身中心，z 也要落同一局部中心。"""
    camera, center = _local_camera(
        part, composition={"subject_position": "center"})
    assert camera["resolved"] is True
    for axis, label in enumerate(("x", "y", "z")):
        assert abs(camera["target"][axis] - center[axis]) < 1e-9, (
            f"{part} local target.{label} 应来自局部锚点 "
            f"{center[axis]:.4f}，实际 {camera['target']}")


@pytest.mark.parametrize("part", ["hand", "face"])
def test_local_camera_height_does_not_reuse_whole_body_frame(part):
    """局部机位高度与局部 target 同源，不能沿用整身取景的相机高度。"""
    camera, center = _local_camera(part)
    assert abs(camera["position"][2] - center[2]) < 0.05, (
        f"{part} local camera.z 应与局部中心 {center[2]:.4f} 对齐，"
        f"实际 {camera['position']}")


@pytest.mark.parametrize(
    ("part", "shot_type"), [("hand", "CU"), ("face", "MCU")])
def test_local_camera_distance_is_solved_from_local_subject_size(
    part, shot_type
):
    """局部机位距离按局部框占画高反解，不再沿用整身景别距离。"""
    camera, center = _local_camera(part, shot_type=shot_type)
    width, depth, character_height = KIND_SIZE_BANDS["character"]
    bounds = coarse_local_bounds(
        kind="character", part=part,
        low=(2.0 - width / 2.0, -1.0 - depth / 2.0, 0.0),
        high=(2.0 + width / 2.0, -1.0 + depth / 2.0, character_height),
        facing=(0.0, 1.0, 0.0))
    assert bounds is not None
    local_height = bounds[1][2] - bounds[0][2]
    expected = required_distance(
        local_height / 0.65, shot_frame_for(shot_type).lens)
    planar = (
        (camera["position"][0] - center[0]) ** 2
        + (camera["position"][1] - center[1]) ** 2) ** 0.5
    assert abs(planar - expected) < 0.02


def test_local_camera_defaults_to_off_center_thirds():
    """没有显式构图声明时，局部正拍也要落到三分线附近。"""
    camera, center = _local_camera("face", shot_type="MCU")
    assert abs(camera["target"][0] - center[0]) > 0.02


def test_local_camera_explicit_center_is_not_overridden():
    """显式 composition=center 必须压过局部默认离轴。"""
    camera, center = _local_camera(
        "face", shot_type="MCU",
        composition={"subject_position": "center"})
    assert abs(camera["target"][0] - center[0]) < 1e-9


def _multi_character_camera(
    *,
    shot_type: str,
    target: str,
    part: str,
    camera: dict | None = None,
) -> dict:
    plan = {
        "scene_heading": "EXT. 第十四街区码头市场 - 白天",
        "shots": [{
            "shot_id": "shot_multi",
            "intent": "多人同框中的声明主体",
            "shot_type": shot_type,
            "duration_frames": 96,
            "order": 1,
            "characters": ["米迦尔", "伊恩"],
            "actions": [],
            "dialogues": [],
            "camera": camera or {},
            "gaze": [],
            "vfx": [],
            "framing_target": {
                "kind": "character",
                "ref": target,
                "part": part,
                "anchor_offset": None,
            },
        }],
    }
    snapshot = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={
            "米迦尔": [0.0, 3.2, 0.0],
            "伊恩": [-1.8, 3.2, 0.0],
            "偷盗者": [0.0, 0.0, 0.0],
        },
        cast_facings={
            "米迦尔": [-1.0, 0.0, 0.0],
            "伊恩": [1.0, 0.0, 0.0],
            "偷盗者": [0.0, 1.0, 0.0],
        },
        scene_id="market",
    )
    return next(
        item for item in snapshot["camera_intents"]
        if item["shot_id"] == "shot_multi")


def test_auto_front_face_camera_uses_over_shoulder_when_support_blocks_ray():
    """final12 shot_005：伊恩正挡在米迦尔面部与正面机位之间。

    这不是评分阈值问题，而是机位在物理上被另一个同镜角色完全挡住。模型没
    声明 ``camera.side`` 时，求解器必须确定性地改用过肩机位，并留下来源，
    而不是把相机继续放在两人连线上等处方循环。
    """
    camera = _multi_character_camera(
        shot_type="CU", target="米迦尔", part="face")

    assert camera["side"] == "over_shoulder"
    assert camera["side_provenance"] == "occlusion_avoidance"
    assert camera["position"][1] < 3.2
    assert 3.2 - camera["position"][1] > 0.5


def test_auto_front_camera_stays_front_when_support_is_behind_camera():
    """负向对照：同镜角色站在机位身后时不得无故改成过肩。

    final12 shot_003 的偷盗者面向 +Y；米迦尔/伊恩在 y=3.2，而正面机位在
    y≈2.39，因此支撑角色在相机之后。该镜已实测构图通过，自动绕行不得
    改变它。
    """
    plan = {
        "scene_heading": "EXT. 市场",
        "shots": [{
            "shot_id": "shot_group",
            "intent": "三人镜只拍偷盗者",
            "shot_type": "MCU",
            "duration_frames": 96,
            "order": 1,
            "characters": ["偷盗者", "米迦尔", "伊恩"],
            "actions": [],
            "dialogues": [],
            "camera": {},
            "gaze": [],
            "vfx": [],
            "framing_target": {
                "kind": "character",
                "ref": "偷盗者",
                "part": "face",
                "anchor_offset": None,
            },
        }],
    }
    snapshot = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={
            "偷盗者": [0.0, 0.0, 0.0],
            "米迦尔": [0.0, 3.2, 0.0],
            "伊恩": [-1.8, 3.2, 0.0],
        },
        cast_facings={
            "偷盗者": [0.0, 1.0, 0.0],
            "米迦尔": [-1.0, 0.0, 0.0],
            "伊恩": [1.0, 0.0, 0.0],
        },
        scene_id="market",
    )
    camera = snapshot["camera_intents"][0]

    assert camera["side"] == "front"
    assert camera["side_provenance"] == "auto_front"
    assert abs(camera["position"][0]) < 0.1
    assert camera["position"][1] < 3.2


def test_explicit_front_camera_side_is_not_silently_overridden():
    """显式 ``side=front`` 是导演意图；遮挡交给审核/处方，不被静默改写。"""
    camera = _multi_character_camera(
        shot_type="CU", target="米迦尔", part="face",
        camera={"side": "front"})

    assert camera["side"] == "front"
    assert camera["side_provenance"] == "plan_intent"
    assert camera["position"][0] < -2.0
    assert abs(camera["position"][1] - 3.2) < 1e-9


def _prop_camera_plan(*, prop_ref: str = "银币") -> tuple[dict, dict]:
    brief = {
        "props": [{
            "id": "银币-金子",
            "kind": "银币化为金子",
            "owner": "偷盗者",
            "state_changes": [{"to": "金子"}],
        }],
    }
    plan = {
        "scene_heading": "EXT. 第十四街区码头市场 - 白天",
        "shots": [{
            "shot_id": "shot_coin",
            "intent": "大特写偷盗者掌中银币",
            "shot_type": "ECU",
            "duration_frames": 120,
            "order": 1,
            "characters": ["偷盗者"],
            "actions": [],
            "dialogues": [],
            "camera": {
                "composition": {"subject_position": "center"},
            },
            "gaze": [],
            "vfx": [],
            "framing_target": {
                "kind": "prop",
                "ref": prop_ref,
                "part": "none",
                "anchor_offset": None,
            },
        }],
    }
    return brief, plan


def test_prop_camera_target_resolves_alias_and_uses_local_bounds():
    """final12 shot_002：ref=银币、id=银币-金子 时必须拍道具本身。

    旧实现只对 ``kind=character`` 做局部求解，道具镜仍瞄持币角色整身，
    12 cm 的银币缩在画外/边缘。该测试同时钉住确定性别名解析、扁平道具
    测量窗、局部距离与相机高度同源。
    """
    from block_director.cinema.blockout import resolve_prop_kind

    brief, plan = _prop_camera_plan()
    snapshot = build_design_snapshot(
        brief=brief, plan=plan,
        cast_positions={"偷盗者": [0.0, 0.0, 0.0]},
        cast_facings={"偷盗者": [0.0, 1.0, 0.0]},
        scene_id="market",
    )
    prop = snapshot["props"][0]
    width, depth, height = resolve_prop_kind(prop["kind"]).size
    bounds = coarse_local_bounds(
        kind="prop", part="none",
        low=(prop["position"][0] - width / 2.0,
             prop["position"][1] - depth / 2.0,
             prop["position"][2] - height / 2.0),
        high=(prop["position"][0] + width / 2.0,
              prop["position"][1] + depth / 2.0,
              prop["position"][2] + height / 2.0),
    )
    assert bounds is not None
    center = tuple(
        (bounds[0][axis] + bounds[1][axis]) / 2.0 for axis in range(3))
    local_height = bounds[1][2] - bounds[0][2]
    camera = snapshot["camera_intents"][0]

    assert camera["resolved"] is True
    for axis in range(3):
        assert abs(camera["target"][axis] - center[axis]) < 1e-9
    assert abs(camera["position"][2] - center[2]) < 1e-9
    expected_distance = required_distance(
        local_height / 0.65, shot_frame_for("ECU").lens)
    planar = (
        (camera["position"][0] - center[0]) ** 2
        + (camera["position"][1] - center[1]) ** 2) ** 0.5
    assert abs(planar - expected_distance) < 0.02
    assert camera["side"] == "front"
    assert camera["side_provenance"] == "auto_front"


def test_prop_camera_does_not_guess_between_ambiguous_aliases():
    """两个道具都包含“银币”时不得随便挑一个，仍按角色整身如实回退。"""
    brief, plan = _prop_camera_plan()
    brief["props"].append({
        "id": "银币-焰光",
        "kind": "硬币",
        "owner": "偷盗者",
        "state_changes": [],
    })
    snapshot = build_design_snapshot(
        brief=brief, plan=plan,
        cast_positions={"偷盗者": [0.0, 0.0, 0.0]},
        cast_facings={"偷盗者": [0.0, 1.0, 0.0]},
        scene_id="market",
    )
    camera = snapshot["camera_intents"][0]

    assert abs(camera["target"][0]) < 1e-9
    assert abs(camera["target"][1]) < 1e-9
    assert camera["target"][2] > 1.0


def test_resolve_camera_intents_uses_prop_world_position():
    """细排重解也必须从冻结 reference 的 props[] 拍道具，不许回到角色。"""
    reference = {
        "characters": [{
            "name": "偷盗者",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "props": [{
            "id": "银币-金子",
            "kind": "银币化为金子",
            "owner": "偷盗者",
            "position": [0.22, 0.25, 0.9107],
        }],
        "shots": [{
            "shot_id": "shot_coin",
            "shot_type": "ECU",
            "characters": ["偷盗者"],
            "camera": {"composition": {"subject_position": "center"}},
            "framing_target": {
                "kind": "prop",
                "ref": "银币",
                "part": "none",
            },
        }],
    }
    from block_director.cinema.spatial_design import resolve_camera_intents

    camera = resolve_camera_intents(reference)["camera_intents"][0]

    assert abs(camera["target"][0] - 0.22) < 1e-9
    assert abs(camera["target"][1] - 0.25) < 1e-9
    assert abs(camera["target"][2] - 0.9107) < 1e-9
    assert abs(camera["position"][2] - 0.9107) < 1e-9
