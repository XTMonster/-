"""Ticket 02：粗排处方应用器 + 修正留痕（纯层，不 import bpy）。

- 修改只发生在粗编排参考 JSON，不写 Blender 场景；
- 每条应用记录含 before/after 与指纹；两次应用逐位一致（确定性）；
- 未知实体/未知轴返回显式未应用记录而不是吞错。
"""

from __future__ import annotations

import pytest

from block_director.contracts.coarse_reference import (
    COARSE_REFERENCE_SCHEMA_VERSION,
    coarse_reference_content_fingerprint,
    dump_coarse_reference,
    validate_coarse_reference,
)
from block_director.cinema.blockout_report import (
    E_BLOCKOUT_FRAMING_TARGET_OCCLUDED,
)
from block_director.cinema.coarse_revision import (
    E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED,
    _occluder_geometry,
    _strafe_sign_towards_free_side,
    apply_coarse_prescriptions,
    build_coarse_prescriptions,
    resolve_prop_ref,
    effective_shot_reference,
)


def _reference(**overrides):
    doc = {
        "schema_version": COARSE_REFERENCE_SCHEMA_VERSION,
        "scene_id": "dock_fly_bomb",
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.8, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": [-0.5, 5.5, 2.0],
            "target": [-0.2, 0.0, 0.8],
            "lens": 35.0, "fov_deg": 54.4,
            "movement": None, "provenance": "script_declaration",
            "resolved": True,
        }],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "飞扑建立空间", "characters": ["米迦尔"],
            "actions": [],
        }],
        "revisions": [],
        "notes": [],
    }
    doc.update(overrides)
    return doc


def test_target_prescription_rewrites_camera_target():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p1", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "target",
        "target_value": {"x": -0.8, "y": 0.0, "z": 0.9},
    }])
    assert new_ref["camera_intents"][0]["target"] == [-0.8, 0.0, 0.9]
    assert (
        new_ref["camera_intents"][0]["provenance"]
        == "agent_local_revision"
    )
    assert records[0]["applied"] is True
    assert records[0]["before"]["target"] == [-0.2, 0.0, 0.8]
    assert validate_coarse_reference(new_ref) == []


def test_distance_prescription_moves_position_along_sightline():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p2", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "distance",
        "target_value": {"position": {"x": -0.2, "y": 4.7, "z": 1.9},
                         "target": {"x": -0.2, "y": 0.0, "z": 0.8}},
    }])
    assert new_ref["camera_intents"][0]["position"] == [-0.2, 4.7, 1.9]
    assert records[0]["applied"] is True


def test_position_z_prescription_raises_camera():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p3", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "position.z",
        "target_value": 5.9445,
    }])
    assert new_ref["camera_intents"][0]["position"][2] == 5.9445
    assert records[0]["applied"] is True


def test_unknown_shot_is_reported_not_applied():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p4", "scope": "camera", "shot_id": "ghost",
        "entity": "cam_ghost", "component": "target",
        "target_value": {"x": 0.0, "y": 0.0, "z": 0.0},
    }])
    #: 实体未变（留痕写的是 revisions 元数据，不影响世界坐标内容）
    assert new_ref["camera_intents"] == ref["camera_intents"]
    assert records[0]["applied"] is False
    assert "ghost" in records[0]["reason"]
    assert len(new_ref["revisions"]) == 1


def test_unknown_component_is_reported_not_applied():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p5", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "lens_magic",
        "target_value": 999.0,
    }])
    assert new_ref["camera_intents"] == ref["camera_intents"]
    assert records[0]["applied"] is False
    assert "lens_magic" in records[0]["reason"]


def test_zero_change_prescription_is_noop_not_applied():
    """R2-F6：target 已指向质心时同值处方不再计 applied=true。

    真跑 round2 的 empty_wall 处方 before==after 仍标 applied，导致修正
    循环在无实质修改的空转上耗完预算。零变化必须记 no_op、指纹不变。
    """
    ref = _reference()
    #: target 已经是处方目标值：应用前后完全一致
    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p_zero", "scope": "camera",
        "shot_id": "shot_001", "entity": "cam_shot_001",
        "component": "target",
        "target_value": {"x": -0.2, "y": 0.0, "z": 0.8},
    }])
    assert new_ref["camera_intents"] == ref["camera_intents"]
    assert records[0]["applied"] is False
    assert records[0]["no_op"] is True
    assert "零变化" in records[0]["reason"] or "no-op" in records[0]["reason"]
    #: 零变化处方仍留审计 revision，但世界坐标指纹必须相同
    assert coarse_reference_content_fingerprint(new_ref) == \
        coarse_reference_content_fingerprint(ref)
    assert len(new_ref.get("revisions") or []) == 1


def test_revision_history_is_written_with_fingerprints():
    ref = _reference()
    before_fp = coarse_reference_content_fingerprint(ref)
    new_ref, records = apply_coarse_prescriptions(
        ref, [{
            "prescription_id": "p6", "scope": "camera",
            "shot_id": "shot_001", "entity": "cam_shot_001",
            "component": "position.z", "target_value": 6.0,
        }],
        revision_id="rev-20261018-1", round_no=1)
    assert len(new_ref["revisions"]) == 1
    rev = new_ref["revisions"][0]
    assert rev["revision_id"] == "rev-20261018-1"
    assert rev["round"] == 1
    assert rev["fingerprint_before"] == before_fp
    assert rev["fingerprint_after"] == coarse_reference_content_fingerprint(
        new_ref)
    assert rev["prescriptions"][0]["prescription_id"] == "p6"


def test_no_prescriptions_returns_identical_reference():
    ref = _reference()
    new_ref, records = apply_coarse_prescriptions(ref, [])
    assert dump_coarse_reference(new_ref) == dump_coarse_reference(ref)
    assert records == []


def test_application_is_deterministic():
    p = [{
        "prescription_id": "p7", "scope": "camera", "shot_id": "shot_001",
        "entity": "cam_shot_001", "component": "position.z",
        "target_value": 6.25,
    }]
    a1, _ = apply_coarse_prescriptions(_reference(), p)
    a2, _ = apply_coarse_prescriptions(_reference(), p)
    assert dump_coarse_reference(a1) == dump_coarse_reference(a2)


def _report_with_empty_wall(shot_id: str) -> dict:
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "abc",
        "verdict": "fail",
        "findings": [{
            "check_id": "E_BLOCKOUT_EMPTY_WALL", "shot_id": shot_id,
            "severity": "error", "message": "主体可见比例低于阈值",
        }],
        "checks": [],
        "notes": [],
    }


def test_empty_wall_prescription_aims_at_framing_target_character():
    """D：OTS/双人镜空墙处方必须瞄声明主体，不是两人中点。

    真跑 market_coin shot_007（伊恩+米迦尔 OTS，声明拍米迦尔）空墙处方
    指向两人质心，处方永远修不到主体上。framing_target.kind=character 时
    ``_subject_centroid`` 必须优先取目标角色坐标（脚底 z + 0.9 躯干中心）。
    """
    ref = _reference(**{
        "characters": [
            {"name": "伊恩", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
            {"name": "米迦尔", "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
        ],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "反打", "characters": ["伊恩", "米迦尔"],
            "actions": [],
            "framing_target": {"kind": "character", "ref": "米迦尔",
                               "part": "none", "anchor_offset": None},
        }],
    })
    prescriptions = build_coarse_prescriptions(
        report=_report_with_empty_wall("shot_001"), reference=ref,
        only_hard=True)
    target = [p for p in prescriptions
              if p["prescription_id"] == "p_coarse_shot_001_empty_wall"]
    assert target, f"应产出 empty_wall 处方，实际 {prescriptions}"
    #: 目标必须是米迦尔的躯干中心（0.9, 0.0, 0.9），不是两人中点 (0.0, 0.0, 0.9)
    assert target[0]["target_value"] == {"x": 0.9, "y": 0.0, "z": 0.9}


def test_empty_wall_prescription_falls_back_to_all_characters_without_target():
    """无 framing_target 声明时保持全员质心回退（旧行为零变化）。"""
    ref = _reference(**{
        "characters": [
            {"name": "伊恩", "position": {"x": -0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
            {"name": "米迦尔", "position": {"x": 0.9, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
        ],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "反打", "characters": ["伊恩", "米迦尔"],
            "actions": [],
            "framing_target": None,
        }],
    })
    prescriptions = build_coarse_prescriptions(
        report=_report_with_empty_wall("shot_001"), reference=ref,
        only_hard=True)
    target = [p for p in prescriptions
              if p["prescription_id"] == "p_coarse_shot_001_empty_wall"]
    assert target
    #: 两人质心：x = (-0.9 + 0.9)/2 = 0.0，y = 0.0，z = 0.9
    assert target[0]["target_value"] == {"x": 0.0, "y": 0.0, "z": 0.9}


def test_empty_wall_prescription_aims_at_prop_world_position():
    """R2：拍对象为道具（银币特写）时空墙处方瞄道具世界坐标。

    旧实现只认角色，银币特写空墙处方瞄到持币角色整身质心（+0.9 躯干偏移），
    循环永远修不对拍对象；道具坐标来自粗排世界参考 JSON props[].position。
    """
    ref = _reference(**{
        "props": [{
            "id": "银币", "kind": "prop", "owner": "偷盗者",
            "position": {"x": 0.22, "y": 0.25, "z": 0.9107},
            "rotation": None, "motion": None,
            "provenance": "algorithmic_measurement",
            "unit": {"position": "m"},
        }],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "银币特写", "characters": ["偷盗者"],
            "actions": [],
            "framing_target": {"kind": "prop", "ref": "银币",
                               "part": "none", "anchor_offset": None},
        }],
    })
    prescriptions = build_coarse_prescriptions(
        report=_report_with_empty_wall("shot_001"), reference=ref,
        only_hard=True)
    target = [p for p in prescriptions
              if p["prescription_id"] == "p_coarse_shot_001_empty_wall"]
    assert target, f"应产出 empty_wall 处方，实际 {prescriptions}"
    #: 瞄准道具世界坐标，而非持币角色质心（0, 0, 0.9）
    assert target[0]["target_value"] == {
        "x": 0.22, "y": 0.25, "z": 0.9107}
    new_ref, records = apply_coarse_prescriptions(ref, prescriptions)
    assert records[0]["applied"] is True
    assert new_ref["camera_intents"][0]["target"] == [0.22, 0.25, 0.9107]


def test_resolve_prop_ref_dedup_duplicate_ids_still_unique():
    """final12 实测根因：``_target_block_name`` 把 ``source.id`` 与去
    ``prop_`` 前缀的原始 id 各入列一次，``prop_银币-金子`` 自带重复项；
    ``resolve_prop_ref`` 若把重复项当多个候选，唯一性判据恒失败 ->
    道具拍对象永远 unresolved。同一物理道具的重复项不是独立候选，
    先去重保序再判唯一，ref=``银币`` 应解析到 ``银币-金子``。
    """
    assert resolve_prop_ref("银币", ["银币-金子", "银币-金子"]) == "银币-金子"
    #: 精确 ref 同样不该被重复项卡死
    assert resolve_prop_ref("银币-金子",
                            ["银币-金子", "银币-金子"]) == "银币-金子"


def test_resolve_prop_ref_two_distinct_matches_still_ambiguous():
    """去重只消除"同一 id 的重复入列"，不能把两个真不同的匹配道具
    误判成唯一候选——歧义仍返回 None，宁保持 unresolved 也不乱指。"""
    #: ref=``币`` 非精确命中，却同时包含于两个真不同的道具 id -> 歧义
    assert resolve_prop_ref("币", ["银币", "银币-金子"]) is None
    assert resolve_prop_ref("银元", ["银币", "银币-金子"]) is None
    assert resolve_prop_ref("", ["银币-金子", "银币-金子"]) is None


def test_resolve_prop_ref_exact_and_unique_containment():
    """T1：精确命中优先；唯一"包含/前后缀"候选才解析；无候选/空 ref 返回
    None（不猜、宁保持 unresolved）。"""
    #: 精确命中
    assert resolve_prop_ref("银币-金子", ["黑红色火焰", "银币-金子"]) == \
        "银币-金子"
    #: 唯一包含候选：ref=银币 -> 银币-金子（final12 真跑场景）
    assert resolve_prop_ref("银币", ["黑红色火焰", "银币-金子"]) == "银币-金子"
    #: 无候选
    assert resolve_prop_ref("宝石", ["银币-金子"]) is None
    #: 空 ref / 空列表
    assert resolve_prop_ref("", ["银币-金子"]) is None
    assert resolve_prop_ref(None, ["银币-金子"]) is None
    assert resolve_prop_ref("银币", []) is None
    assert resolve_prop_ref("银币", None) is None


def _report_with_finding(shot_id: str, check_id: str) -> dict:
    return {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": "abc",
        "verdict": "fail",
        "findings": [{
            "check_id": check_id, "shot_id": shot_id,
            "severity": "error", "message": "硬伤",
        }],
        "checks": [],
        "notes": [],
    }


def test_framing_target_occluded_first_prescription_pulls_back():
    """A declared target hidden behind geometry must receive its own repair."""
    ref = _reference(**{
        "props": [{
            "id": "银币", "kind": "prop", "owner": "偷盗者",
            "position": {"x": 0.22, "y": 0.25, "z": 0.9107},
            "rotation": None, "motion": None,
            "provenance": "algorithmic_measurement",
            "unit": {"position": "m"},
        }],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "银币特写", "characters": ["偷盗者"],
            "actions": [],
            "framing_target": {"kind": "prop", "ref": "银币",
                               "part": "none", "anchor_offset": None},
        }],
    })
    report = _report_with_finding(
        "shot_001", E_BLOCKOUT_FRAMING_TARGET_OCCLUDED)
    report["checks"] = [{
        "check_id": "framing_target", "shot_id": "shot_001",
        "actual": 0.17, "visible_ratio": 0.1,
        "threshold": 0.05, "visible_threshold": 0.5,
        "verdict": "fail",
    }]

    prescriptions = build_coarse_prescriptions(
        report=report, reference=ref, only_hard=True)
    repair = [
        p for p in prescriptions
        if p["prescription_id"]
        == "p_coarse_shot_001_framing_target_occluded"
    ]

    assert repair, f"应产出拍对象遮挡处方，实际 {prescriptions}"
    assert repair[0]["component"] == "distance"
    assert repair[0]["direction"] == "out"
    assert repair[0]["derived_from"]["check_id"] == (
        E_BLOCKOUT_FRAMING_TARGET_OCCLUDED)
    new_ref, records = apply_coarse_prescriptions(ref, repair)
    assert records[0]["applied"] is True
    assert new_ref["camera_intents"][0]["position"][1] > (
        ref["camera_intents"][0]["position"][1])


def test_framing_target_occluded_strafes_after_pull_back():
    """Repeated target occlusion must progress instead of pulling back forever."""
    ref = _reference()
    ref["revisions"] = [{
        "revision_id": "coarse-round-1",
        "round": 1,
        "fingerprint_before": "before",
        "fingerprint_after": "after",
        "prescriptions": [{
            "prescription_id":
                "p_coarse_shot_001_framing_target_occluded",
            "shot_id": "shot_001",
            "component": "distance",
            "applied": True,
            "before": None,
            "after": None,
            "reason": "",
        }],
    }]
    report = _report_with_finding(
        "shot_001", E_BLOCKOUT_FRAMING_TARGET_OCCLUDED)

    prescriptions = build_coarse_prescriptions(
        report=report, reference=ref, only_hard=True)
    repair = [
        p for p in prescriptions
        if p["prescription_id"]
        == "p_coarse_shot_001_framing_target_occluded"
    ]

    assert repair, f"应继续产出拍对象遮挡处方，实际 {prescriptions}"
    assert repair[0]["component"] == "strafe"
    assert repair[0]["target_value"]["position"]["z"] == (
        ref["camera_intents"][0]["position"][2])


def test_framing_target_unresolved_resolves_prop_to_world_position():
    """T2：E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED 且拍对象可解析（ref=银币
    命中道具 id 银币-金子）时，处方把相机 target 指向道具世界坐标（与
    empty_wall 同款 component=target），应用后参考 JSON 同步更新。"""
    ref = _reference(**{
        "props": [{
            "id": "银币-金子", "kind": "prop", "owner": "偷盗者",
            "position": {"x": 0.22, "y": 0.25, "z": 0.9107},
            "rotation": None, "motion": None,
            "provenance": "algorithmic_measurement",
            "unit": {"position": "m"},
        }],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "银币特写", "characters": ["偷盗者"],
            "actions": [],
            "framing_target": {"kind": "prop", "ref": "银币",
                               "part": "none", "anchor_offset": None},
        }],
    })
    prescriptions = build_coarse_prescriptions(
        report=_report_with_finding("shot_001",
                                    E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED),
        reference=ref, only_hard=True)
    target = [p for p in prescriptions
              if p["prescription_id"] == "p_coarse_shot_001_framing_target"]
    assert target, f"应产出 framing_target 处方，实际 {prescriptions}"
    assert target[0]["component"] == "target"
    assert target[0]["direction"] == "towards_subject"
    assert target[0]["target_value"] == {
        "x": 0.22, "y": 0.25, "z": 0.9107}
    new_ref, records = apply_coarse_prescriptions(ref, prescriptions)
    assert records[0]["applied"] is True
    assert new_ref["camera_intents"][0]["target"] == [0.22, 0.25, 0.9107]


def test_framing_target_unresolved_unresolvable_explicit_not_applied():
    """T2：E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED 且拍对象不可解析（参考
    JSON 无该道具）时，产出 unresolved=True 的显式未应用处方，reason 明确，
    应用后 applied=False —— 修正循环据此如实收敛，不空转三轮回调。"""
    ref = _reference(**{
        "props": [],
        "shots": [{
            "shot_id": "shot_001", "order": 1, "duration_frames": 72,
            "intent": "银币特写", "characters": ["偷盗者"],
            "actions": [],
            "framing_target": {"kind": "prop", "ref": "银币",
                               "part": "none", "anchor_offset": None},
        }],
    })  #: 无该道具，拍对象声明 kind=prop 也解析不到
    prescriptions = build_coarse_prescriptions(
        report=_report_with_finding("shot_001",
                                    E_BLOCKOUT_FRAMING_TARGET_UNRESOLVED),
        reference=ref, only_hard=True)
    unresolved = [p for p in prescriptions
                  if p.get("unresolved") is True]
    assert unresolved, f"应产出 unresolved 处方，实际 {prescriptions}"
    assert unresolved[0]["applied"] is False
    assert "无法解析" in unresolved[0]["reason"]
    new_ref, records = apply_coarse_prescriptions(ref, prescriptions)
    assert records[0]["applied"] is False
    assert "无法解析" in records[0]["reason"]
    #: 世界坐标未被凭空改写
    assert new_ref["camera_intents"] == ref["camera_intents"]


def test_foreground_occlusion_first_prescription_pulls_back():
    """T2：E_FOREGROUND_OCCLUSION 且该镜尚无拉远留痕 -> 沿视线拉远 15%
    （旧行为，component=distance, direction=out）。"""
    ref = _reference()
    prescriptions = build_coarse_prescriptions(
        report=_report_with_finding("shot_001", "E_FOREGROUND_OCCLUSION"),
        reference=ref, only_hard=True)
    occ = [p for p in prescriptions
           if p["prescription_id"] == "p_coarse_shot_001_foreground_occlusion"]
    assert occ, f"应产出拉远处方，实际 {prescriptions}"
    assert occ[0]["component"] == "distance"
    assert occ[0]["direction"] == "out"
    #: 沿视线拉远：position.y 增大（相机在 +y 侧看向 -y）
    assert occ[0]["target_value"]["position"]["y"] > \
        occ[0]["current_value"]["position"]["y"]


def _reference_with_applied_revision(component: str) -> dict:
    """构造已应用过某类相机处方的参考 JSON（T2 strafe 渐进判定用）。"""
    return _reference(**{
        "revisions": [{
            "revision_id": "coarse-round-1", "round": 1,
            "fingerprint_before": "b", "fingerprint_after": "a",
            "prescriptions": [{
                "prescription_id": f"p_coarse_shot_001_{component}",
                "shot_id": "shot_001", "component": component,
                "applied": True, "before": None, "after": None,
                "reason": "",
            }],
        }],
    })


def test_foreground_occlusion_strafes_after_pull_back():
    """T2：已拉远仍被前景遮挡 -> 横向绕行（component=strafe），相机在
    视线水平垂直方向侧移，z 高度不变；判定来自 revisions 留痕而非猜测。"""
    ref = _reference_with_applied_revision("distance")
    prescriptions = build_coarse_prescriptions(
        report=_report_with_finding("shot_001", "E_FOREGROUND_OCCLUSION"),
        reference=ref, only_hard=True)
    strafe = [p for p in prescriptions
              if p["prescription_id"] == "p_coarse_shot_001_strafe"]
    assert strafe, f"应产出绕行处方，实际 {prescriptions}"
    assert strafe[0]["component"] == "strafe"
    assert strafe[0]["direction"] == "right"
    pos = strafe[0]["target_value"]["position"]
    cur = strafe[0]["current_value"]["position"]
    #: 侧移量非零，且 z 不变（x/y 地面上的水平绕行）
    assert (pos["x"] != cur["x"] or pos["y"] != cur["y"])
    assert pos["z"] == cur["z"]
    new_ref, records = apply_coarse_prescriptions(ref, prescriptions)
    assert records[0]["applied"] is True


def test_foreground_occlusion_strafe_alternates_direction():
    """T2：已绕行仍被挡 -> 反向绕行（sign 交替），保证连续修正不会在同
    一方向反复空转。"""
    ref = _reference_with_applied_revision("distance")
    ref["revisions"].append({
        "revision_id": "coarse-round-2", "round": 2,
        "fingerprint_before": "b", "fingerprint_after": "a",
        "prescriptions": [{
            "prescription_id": "p_coarse_shot_001_strafe",
            "shot_id": "shot_001", "component": "strafe",
            "applied": True, "before": None, "after": None, "reason": "",
        }],
    })
    prescriptions = build_coarse_prescriptions(
        report=_report_with_finding("shot_001", "E_FOREGROUND_OCCLUSION"),
        reference=ref, only_hard=True)
    strafe = [p for p in prescriptions
              if p["prescription_id"] == "p_coarse_shot_001_strafe"]
    assert strafe
    assert strafe[0]["direction"] == "left"
    #: 反向：x/y 地面侧移符号与首轮相反
    pos = strafe[0]["target_value"]["position"]
    cur = strafe[0]["current_value"]["position"]
    #: 独立复算首轮 +sign 侧移（视线水平垂直方向，量级 0.15*视线距离），
    #: 不依赖被测私有函数，避免“自己验证自己”。
    dx = -0.2 - cur["x"]
    dy = 0.0 - cur["y"]
    horiz = (dx * dx + dy * dy) ** 0.5
    perp_x, perp_y = -dy / horiz, dx / horiz
    dist = (dx ** 2 + dy ** 2 + (0.8 - cur["z"]) ** 2) ** 0.5
    amount = 0.15 * max(dist, 1e-6)
    first_delta = (perp_x * amount, perp_y * amount)
    assert pos["x"] - cur["x"] == pytest.approx(-first_delta[0])
    assert pos["y"] - cur["y"] == pytest.approx(-first_delta[1])
    assert pos["z"] == cur["z"]


def test_occluder_geometry_resolves_character_and_prop():
    """T2-几何：空间尺 OcclusionEvent 归因的坐标侧——occluder 主体 id ->
    世界坐标（角色优先、道具次之、解析不到返回 None 不猜）。"""
    ref = _reference(**{
        "characters": [
            {"name": "米迦尔", "position": {"x": 1.5, "y": 1.1, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
            {"name": "偷盗者", "position": {"x": -0.3, "y": 1.1, "z": 0.0},
             "facing": [0.0, 1.0, 0.0], "rotation": None,
             "gaze": None, "motion_by_shot": []},
        ],
        "props": [{
            "id": "银币-金子", "kind": "prop", "owner": "偷盗者",
            "position": {"x": -0.08, "y": 1.35, "z": 0.9107},
            "rotation": None, "motion": None,
            "provenance": "algorithmic_measurement",
            "unit": {"position": "m"},
        }],
    })
    assert _occluder_geometry(ref, "米迦尔") == {
        "x": 1.5, "y": 1.1, "z": 0.0}
    assert _occluder_geometry(ref, "银币-金子") == {
        "x": -0.08, "y": 1.35, "z": 0.9107}
    assert _occluder_geometry(ref, "不存在的角色") is None


def test_strafe_sign_towards_free_side_geometry():
    """T2-几何：绕行方向由遮挡体相对视线的水平方位决定（远离遮挡体侧），
    替代固定 right/left 交替。"""
    #: 相机看向 (0,5,1)：x/y 地面视线的水平垂直方向为 (-1,0,0)
    pos = {"x": 0.0, "y": 0.0, "z": 0.0}
    target = {"x": 0.0, "y": 5.0, "z": 1.0}
    #: 遮挡体在 +x（视线水平垂直方向 -x 那侧），相机应绕到 -x（远离遮挡）
    occluder_plus_x = {"x": 1.0, "y": 1.0, "z": 0.0}
    assert _strafe_sign_towards_free_side(
        pos, target, occluder_plus_x) == 1  #: +1 沿 perp=(-1,0,0) = 远离 +x
    occluder_minus_x = {"x": -1.0, "y": 1.0, "z": 0.0}
    assert _strafe_sign_towards_free_side(
        pos, target, occluder_minus_x) == -1
    #: 遮挡体恰在视线轴上（投影近零）-> 正向（避免零判）
    occluder_axis = {"x": 0.0, "y": 1.0, "z": 0.5}
    assert _strafe_sign_towards_free_side(
        pos, target, occluder_axis) == 1


def test_foreground_occlusion_moves_occluder_character():
    """T2-随机应变：遮挡体是可动同框角色 -> 直接平移站位到视线轴外
    （space尺 _REPAIR 的 move_character 落到粗排参考 JSON，世界坐标
    实时更新），而不是只绕相机。"""
    ref = _reference_with_applied_revision("distance")
    ref["characters"].append({
        "name": "伊恩", "position": {"x": 0.0, "y": 1.8, "z": 0.0},
        "facing": [0.0, 1.0, 0.0], "rotation": None,
        "gaze": None, "motion_by_shot": []})
    ref["shots"][0]["characters"].append("伊恩")
    report = _report_with_finding("shot_001", "E_FOREGROUND_OCCLUSION")
    report["findings"][0]["occluders"] = ["伊恩"]
    prescriptions = build_coarse_prescriptions(
        report=report, reference=ref, only_hard=True)
    move = [p for p in prescriptions
            if p["prescription_id"] == "p_coarse_shot_001_clear_occluder"]
    assert move, f"应产出角色平移处方，实际 {prescriptions}"
    assert move[0]["scope"] == "character"
    assert move[0]["entity"] == "伊恩"
    assert move[0]["component"] == "character_position"
    #: 伊恩站位被移开（与初始 (0,1.8,0) 不同），且仍留在地面
    assert move[0]["target_value"]["x"] != 0.0 \
        or move[0]["target_value"]["y"] != 1.8
    assert move[0]["target_value"]["z"] == 0.0
    #: 应用后参考 JSON 的角色位置实时更新
    new_ref, records = apply_coarse_prescriptions(ref, prescriptions)
    assert records[0]["applied"] is True
    ian = next(c for c in new_ref["characters"]
               if c["name"] == "伊恩")
    assert ian["position"] == {"x": 0.0, "y": 1.8, "z": 0.0}
    effective_ian = next(
        c for c in effective_shot_reference(
            new_ref, "shot_001")["characters"]
        if c["name"] == "伊恩")
    assert effective_ian["position"] == move[0]["target_value"]
    assert validate_coarse_reference(new_ref) == []


def test_foreground_occlusion_strafe_away_from_prop_occluder():
    """T2-几何：遮挡体是道具（不可动）-> 相机绕行方向远离遮挡体侧。"""
    ref = _reference_with_applied_revision("distance")
    ref["props"] = [{
        "id": "银币-金子", "kind": "prop", "owner": "偷盗者",
        "position": {"x": 0.2, "y": 1.35, "z": 0.9},
        "rotation": None, "motion": None,
        "provenance": "algorithmic_measurement",
        "unit": {"position": "m"},
    }]
    report = _report_with_finding("shot_001", "E_FOREGROUND_OCCLUSION")
    report["findings"][0]["occluders"] = ["银币-金子"]
    prescriptions = build_coarse_prescriptions(
        report=report, reference=ref, only_hard=True)
    strafe = [p for p in prescriptions
              if p["prescription_id"] == "p_coarse_shot_001_strafe"]
    assert strafe, f"应产出绕行处方，实际 {prescriptions}"
    cur = strafe[0]["current_value"]["position"]
    new_pos = strafe[0]["target_value"]["position"]
    #: 独立复算：遮挡体在视线哪一侧 -> 相机向相反侧绕
    assert _strafe_sign_towards_free_side(
        cur, {"x": -0.2, "y": 0.0, "z": 0.8},
        {"x": 0.2, "y": 1.35, "z": 0.9}) == (1 if strafe[0]["direction"] == "right" else -1)
