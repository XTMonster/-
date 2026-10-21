"""composition fail 时的站位错开处方（2026-10-21 真跑：
默认站位让同镜角色重叠 -> 构图 20 分；先错开站位再动相机）。
"""

from __future__ import annotations

from block_director.cinema.coarse_revision import (
    apply_coarse_prescriptions,
    build_coarse_prescriptions,
    effective_shot_reference,
)


def _reference():
    return {
        "characters": [
            {"name": "米迦尔", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [1.0, 0.0, 0.0]},
            {"name": "伊恩", "position": {"x": -0.3, "y": 0.0, "z": 0.0},
             "facing": [0.0, 1.0, 0.0]},
        ],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [-0.3, 3.0, 1.2],
             "target": [-0.3, 0.0, 1.4], "lens": 50.0},
        ],
        "shots": [
            {"shot_id": "shot_001", "characters": ["米迦尔", "伊恩"]},
        ],
    }


def test_composition_fail_emits_character_separation():
    ref = _reference()
    report = {
        "verdict": "fail",
        "checks": [
            {"check_id": "composition", "shot_id": "shot_001",
             "actual": 20.0, "threshold": 80.0, "verdict": "fail"},
        ],
        "findings": [],
    }
    prescriptions = build_coarse_prescriptions(
        report=report, reference=ref, only_hard=False)
    separation = [p for p in prescriptions
                  if p.get("component") == "character_position"]
    assert separation, prescriptions
    p = separation[0]
    assert p["entity"] in {"米迦尔", "伊恩"}
    assert p["derived_from"]["check_id"] == "composition"
    assert p["scope"] == "character"


def test_separation_applies_to_reference():
    ref = _reference()
    report = {
        "verdict": "fail",
        "checks": [
            {"check_id": "composition", "shot_id": "shot_001",
             "actual": 20.0, "threshold": 80.0, "verdict": "fail"},
        ],
        "findings": [],
    }
    prescriptions = build_coarse_prescriptions(
        report=report, reference=ref, only_hard=False)
    new_ref, records = apply_coarse_prescriptions(ref, prescriptions)
    global_by_name = {c["name"]: c for c in new_ref["characters"]}
    assert global_by_name["米迦尔"]["position"] == {
        "x": -0.3, "y": 0.0, "z": 0.0}
    assert global_by_name["伊恩"]["position"] == {
        "x": -0.3, "y": 0.0, "z": 0.0}
    effective = effective_shot_reference(new_ref, "shot_001")
    by_name = {c["name"]: c for c in effective["characters"]}
    a = by_name["米迦尔"]["position"]
    b = by_name["伊恩"]["position"]
    gap = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
    assert gap > 0.8, (a, b)
    assert a["z"] == 0.0
    assert b["z"] == 0.0
    assert any(r.get("applied") for r in records)


def test_no_separation_when_characters_already_separated():
    ref = _reference()
    ref["characters"][1]["position"] = {"x": 0.0, "y": 2.0, "z": 0.0}
    report = {
        "verdict": "fail",
        "checks": [
            {"check_id": "composition", "shot_id": "shot_001",
             "actual": 20.0, "threshold": 80.0, "verdict": "fail"},
        ],
        "findings": [],
    }
    prescriptions = build_coarse_prescriptions(
        report=report, reference=ref, only_hard=False)
    separation = [p for p in prescriptions
                  if p.get("component") == "character_position"]
    assert not separation


def test_character_move_resolves_dependent_camera_intent_again():
    """角色站位改变后，依赖该角色的机位不能继续瞄旧局部中心。

    final16 R2-10 真跑第 2 轮把米迦尔从 ``(0, 1.8)`` 移到
    ``(0.0543, 2.2521)``，但 shot_004/005/007 的 camera target 仍停在
    旧站位。后续 push/pull 只沿旧视线推拉，构图振荡 47 轮仍无法收敛。
    应用角色位移后，同一镜的相机意图必须从新站位重新求解。
    """
    ref = _reference()
    ref["characters"] = [ref["characters"][0]]
    ref["characters"][0]["position"] = {
        "x": -0.3, "y": 0.0, "z": 0.0}
    ref["characters"][0]["facing"] = [0.0, 1.0, 0.0]
    ref["camera_intents"][0]["target"] = [-0.3, 0.0, 1.3855]
    ref["shots"][0]["shot_type"] = "MCU"
    ref["shots"][0]["camera"] = {"composition": {
        "subject_position": "center"}}
    ref["shots"][0]["framing_target"] = {
        "kind": "character", "ref": "米迦尔",
        "part": "face", "anchor_offset": None,
    }

    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p_move_moved_camera",
        "scope": "character",
        "shot_id": "shot_001",
        "entity": "米迦尔",
        "component": "character_position",
        "target_value": {"x": 1.1, "y": 2.0, "z": 0.0},
    }])

    assert records[0]["applied"] is True
    moved = effective_shot_reference(
        new_ref, "shot_001")["characters"][0]["position"]
    assert new_ref["characters"][0]["position"] == {
        "x": -0.3, "y": 0.0, "z": 0.0}
    assert moved == {"x": 1.1, "y": 2.0, "z": 0.0}
    target = new_ref["camera_intents"][0]["target"]
    assert abs(target[0] - 1.1) < 0.25, target
    assert abs(target[1] - 2.0) < 0.25, target


def test_character_move_supersedes_same_round_stale_camera_prescription():
    """同批按旧站位生成的推拉处方，不得留成 applied 的最终审计结论。"""
    ref = _reference()
    ref["characters"] = [ref["characters"][0]]
    ref["characters"][0]["position"] = {
        "x": -0.3, "y": 0.0, "z": 0.0}
    ref["characters"][0]["facing"] = [0.0, 1.0, 0.0]
    ref["camera_intents"][0]["target"] = [-0.3, 0.0, 1.3855]
    ref["shots"][0]["shot_type"] = "MCU"
    ref["shots"][0]["camera"] = {"composition": {
        "subject_position": "center"}}
    ref["shots"][0]["framing_target"] = {
        "kind": "character", "ref": "米迦尔",
        "part": "face", "anchor_offset": None,
    }

    new_ref, records = apply_coarse_prescriptions(ref, [
        {
            "prescription_id": "p_move",
            "scope": "character",
            "shot_id": "shot_001",
            "entity": "米迦尔",
            "component": "character_position",
            "target_value": {"x": 1.1, "y": 2.0, "z": 0.0},
        },
        {
            "prescription_id": "p_stale_push",
            "scope": "camera",
            "shot_id": "shot_001",
            "entity": "cam_shot_001",
            "component": "distance",
            "target_value": {
                "position": {"x": -1.0, "y": 1.2, "z": 1.3855},
                "target": {"x": -0.3, "y": 0.0, "z": 1.3855},
            },
        },
    ])

    assert records[0]["applied"] is True
    assert records[1]["applied"] is False
    assert records[1]["superseded"] is True
    assert "重解" in records[1]["reason"]
    target = new_ref["camera_intents"][0]["target"]
    assert abs(target[0] - 1.1) < 0.25, target
    assert abs(target[1] - 2.0) < 0.25, target


def test_shot_local_character_move_does_not_leak_to_next_shot():
    ref = _reference()
    ref["camera_intents"].append({
        "shot_id": "shot_002",
        "position": [0.0, 3.0, 1.2],
        "target": [-0.3, 0.0, 1.4],
        "lens": 50.0,
    })
    ref["shots"].append({
        "shot_id": "shot_002",
        "characters": ["米迦尔", "伊恩"],
    })

    new_ref, records = apply_coarse_prescriptions(ref, [{
        "prescription_id": "p_local_move",
        "scope": "character",
        "shot_id": "shot_001",
        "entity": "米迦尔",
        "component": "character_position",
        "target_value": {"x": 1.1, "y": 2.0, "z": 0.0},
        "reason": "只调整第一镜人物关系",
        "evidence_refs": ["composition:shot_001"],
    }])

    assert records[0]["applied"] is True
    by_name = {char["name"]: char for char in new_ref["characters"]}
    assert by_name["米迦尔"]["position"] == {
        "x": -0.3, "y": 0.0, "z": 0.0}
    assert new_ref["shot_staging"]["shot_001"]["米迦尔"]["position"] == {
        "x": 1.1, "y": 2.0, "z": 0.0}
    assert "shot_002" not in new_ref["shot_staging"]

    shot_one = effective_shot_reference(new_ref, "shot_001")
    shot_two = effective_shot_reference(new_ref, "shot_002")
    shot_one_char = next(
        char for char in shot_one["characters"] if char["name"] == "米迦尔")
    shot_two_char = next(
        char for char in shot_two["characters"] if char["name"] == "米迦尔")
    assert shot_one_char["position"] == {"x": 1.1, "y": 2.0, "z": 0.0}
    assert shot_two_char["position"] == {"x": -0.3, "y": 0.0, "z": 0.0}

    cameras = {
        item["shot_id"]: item for item in new_ref["camera_intents"]}
    assert cameras["shot_001"]["target"][0] > 0.0
    assert cameras["shot_002"]["target"] == [-0.3, 0.0, 1.4]
