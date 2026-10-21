"""R2 Ticket 10：粗排参考 JSON 必须携带拍对象与分工语义（B 修复）。

真跑 20261019-r2-market-coin-accept-3 的 root cause：``_attach_plan_shots``
只带 ``shot_id/order/intent/duration_frames/characters/actions/camera`` 六个
键，丢 ``framing_target`` 与 ``responsibility``。而 ``blockout_report`` 的
``_framing_target_checks`` 从这些 shot 读 ``framing_target``（于是检查照发），
skip 豁免（J3）也需要 ``responsibility.skip_white_model``。参考 JSON 作为
单一真源必须携带这两个语义键。
"""

from __future__ import annotations

from block_director.contracts.plan import (
    FramingTarget,
    Plan,
    Responsibility,
    ShotPlan,
    ShotType,
)
from block_director.layer5_orchestrator.coarse_pipeline import (
    _attach_plan_shots,
)
from block_director.cinema.spatial_design import resolve_camera_intents


def _shot(**overrides):
    base = dict(
        shot_id="shot_001", order=1, intent="银币特写",
        shot_type=ShotType.CU, duration_frames=48,
        characters=["米迦尔"], actions=[], camera={})
    base.update(overrides)
    return ShotPlan(**base)


def test_attach_plan_shots_carries_framing_target_and_responsibility():
    plan = Plan(
        scene_heading="港口市场",
        shots=[_shot(
            framing_target=FramingTarget(kind="prop", ref="银币", part="none"),
            responsibility=Responsibility(
                white_model=[], prompt=["分镜师"], ref_image=["美术组"],
                skip_white_model=True))])
    reference = _attach_plan_shots(
        {"schema_version": "coarse-world-reference/v1",
         "characters": [], "props": [], "anchors": [],
         "camera_intents": [], "shots": [], "revisions": [],
         "notes": []},
        plan)
    shot = reference["shots"][0]
    #: Plan 对象分支必须携带这两个语义键（此前只带六键）
    assert shot["shot_id"] == "shot_001"
    assert shot["framing_target"]["kind"] == "prop"
    assert shot["framing_target"]["ref"] == "银币"
    assert shot["responsibility"]["skip_white_model"] is True
    assert shot["responsibility"]["prompt"] == ["分镜师"]


def test_attach_plan_shots_dict_plan_keeps_semantic_keys():
    """dict 形状 plan：原样拷贝，语义键必须保留（emit_plan 直出）。"""
    plan = {
        "scene_heading": "港口市场",
        "shots": [{
            "shot_id": "shot_001", "order": 1, "intent": "银币特写",
            "shot_type": "CU", "duration_frames": 48,
            "characters": ["米迦尔"], "actions": [], "camera": {},
            "framing_target": {"kind": "character", "ref": "米迦尔",
                               "part": "face", "anchor_offset": None},
            "responsibility": {"white_model": ["机位"], "prompt": [],
                               "ref_image": [], "skip_white_model": False},
        }],
    }
    reference = _attach_plan_shots(
        {"schema_version": "coarse-world-reference/v1",
         "characters": [], "props": [], "anchors": [],
         "camera_intents": [], "shots": [], "revisions": [],
         "notes": []},
        plan)
    shot = reference["shots"][0]
    assert shot["framing_target"]["ref"] == "米迦尔"
    assert shot["responsibility"]["skip_white_model"] is False


def test_attach_plan_shots_unchanged_when_shot_lacks_semantic_keys():
    """旧计划（无责任/无拍对象）零行为差：不凭空补键。"""
    plan = Plan(scene_heading="旧场", shots=[_shot()])
    reference = _attach_plan_shots(
        {"schema_version": "coarse-world-reference/v1",
         "characters": [], "props": [], "anchors": [],
         "camera_intents": [], "shots": [], "revisions": [],
         "notes": []},
        plan)
    #: 数据类恒有该属性 -> 恒出键（None），与 to_dict()（未声明时是 null）
    #: 同口径；下游 isinstance(..., Mapping) 判未声明，零语义差。
    assert reference["shots"][0]["framing_target"] is None
    assert reference["shots"][0]["responsibility"] is None


def test_attach_plan_shots_keeps_shot_type_for_detail_camera_refresh():
    """镜头景别必须穿过参考 JSON，细排重解相机时不得退化成默认 MS。

    真跑 ``20261021-node123-detail-gate-pre``：参考 JSON 丢 ``shot_type``，
    细排重解把 ELS 的 24mm/9.03m 改成 MS 的 35mm/4.66m，构图从 85.5
    掉到 75.3。这里用公开的重解入口锁住整条语义链。
    """
    plan = Plan(
        scene_heading="港口市场",
        shots=[_shot(
            shot_type=ShotType.ELS,
            duration_frames=120,
            characters=["米迦尔", "伊恩", "偷盗者"])])
    reference = _attach_plan_shots(
        {"schema_version": "coarse-world-reference/v1",
         "scene_id": "market",
         "characters": [
             {"name": "米迦尔",
              "position": {"x": -1.5, "y": 0.0, "z": 0.0},
              "facing": [0.0, 1.0, 0.0]},
             {"name": "伊恩",
              "position": {"x": 0.0, "y": 0.0, "z": 0.0},
              "facing": [0.0, 1.0, 0.0]},
             {"name": "偷盗者",
              "position": {"x": 1.5, "y": 0.0, "z": 0.0},
              "facing": [0.0, 1.0, 0.0]},
         ],
         "props": [], "anchors": [], "camera_intents": [],
         "shots": [], "revisions": [], "notes": []},
        plan)

    refreshed = resolve_camera_intents(reference)
    camera = refreshed["camera_intents"][0]

    assert reference["shots"][0]["shot_type"] == "ELS"
    assert camera["lens"] == 24.0
    assert camera["position"][1] > 8.0
