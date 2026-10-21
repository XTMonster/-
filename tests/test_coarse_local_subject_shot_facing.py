"""R2-10 regression: local hand geometry must follow the shot's facing.

The camera solver already consumes ``facing_by_shot``.  The coarse preview
must use the same per-shot heading when it builds a hand/face proxy, otherwise
the proxy is measured at a different point than the camera is aimed at and the
composition gate can never converge by pushing the camera.
"""

from __future__ import annotations

import math

import pytest

from block_director.cinema.anchor import coarse_local_bounds, facing_for_shot
from block_director.cinema.blockout import KIND_SIZE_BANDS
from block_director.cinema.composition import (
    PASS_SCORE,
    SubjectBox,
    evaluate_composition,
)
from block_director.cinema.framing import (
    ASPECT_16_9,
    SENSOR_WIDTH,
    vertical_fov,
)
from block_director.cinema.mesh_visibility import camera_basis, project_ndc
from block_director.cinema.spatial_design import resolve_camera_intents


def _reference() -> dict:
    """The shot_001 shape from the final16 run, reduced to its semantics."""
    return {
        "characters": [{
            "name": "米迦尔",
            "position": {"x": 0.0543, "y": 2.2521, "z": 0.0},
            #: The scene-wide gaze points south; this shot turns the hand west.
            "facing": [0.0, -1.0, 0.0],
            "facing_by_shot": [{
                "shot_id": "shot_001",
                "direction": [-1.0, 0.0, 0.0],
            }],
        }],
        "shots": [{
            "shot_id": "shot_001",
            "order": 1,
            "intent": "右手响指",
            "shot_type": "CU",
            "duration_frames": 84,
            "characters": ["米迦尔"],
            "camera": {},
            "framing_target": {
                "kind": "character",
                "ref": "米迦尔",
                "part": "hand",
            },
        }],
    }


def _local_box(reference: dict, facing) -> SubjectBox:
    char = reference["characters"][0]
    width, depth, height = KIND_SIZE_BANDS["character"]
    position = char["position"]
    low = (position["x"] - width / 2.0,
           position["y"] - depth / 2.0,
           position["z"])
    high = (position["x"] + width / 2.0,
            position["y"] + depth / 2.0,
            position["z"] + height)
    bounds = coarse_local_bounds(
        kind="character", part="hand", low=low, high=high, facing=facing)
    assert bounds is not None

    intent = resolve_camera_intents(reference)["camera_intents"][0]
    forward = tuple(intent["target"][axis] - intent["position"][axis]
                    for axis in range(3))
    length = math.sqrt(sum(value * value for value in forward))
    forward = tuple(value / length for value in forward)
    basis = camera_basis(
        position=intent["position"],
        forward=forward,
        up=(0.0, 0.0, 1.0),
        vfov_deg=math.degrees(
            vertical_fov(intent["lens"], SENSOR_WIDTH, ASPECT_16_9)),
        aspect=ASPECT_16_9,
        near=0.1,
        far=100.0,
    )
    points = [
        project_ndc(basis, (x, y, z))
        for x in (bounds[0][0], bounds[1][0])
        for y in (bounds[0][1], bounds[1][1])
        for z in (bounds[0][2], bounds[1][2])
    ]
    assert all(point is not None for point in points)
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return SubjectBox(
        name="米迦尔:hand",
        left=min(xs), right=max(xs), top=max(ys), bottom=min(ys),
        facing=1.0,
    )


def test_hand_local_subject_uses_the_shot_facing_and_lands_on_a_third():
    """A front hand shot must be measured in the same frame as the camera.

    This is intentionally a regression for the real shot_001 mismatch:
    scene-wide facing ``-Y`` puts the proxy at ``y=2.0021`` while the solver
    aims at the shot-facing proxy at ``y=2.4721``.  The former projects outside
    the right edge (score 42.8), the latter lands on the left third (score
    88.1).  The expected head is the independently computed geometry, not a
    recomputation of the preview's scoring formula.
    """
    reference = _reference()
    facing = facing_for_shot(reference["characters"][0], "shot_001")
    assert facing == pytest.approx((-1.0, 0.0, 0.0))

    shot_box = _local_box(reference, facing)
    assert abs((shot_box.left + shot_box.right) / 2.0 - 1.0 / 3.0) < 0.08
    shot_report = evaluate_composition(
        [shot_box], primary=shot_box.name,
        expected_height=1.0, headroom_applies=False)
    assert shot_report.score > PASS_SCORE

    #: The old consumer used the scene-wide facing.  This negative control
    #: proves the assertion is sensitive to the defect rather than merely
    #: checking an always-passing value.
    wrong_box = _local_box(reference, reference["characters"][0]["facing"])
    assert wrong_box.inside_ratio() < 0.5
    wrong_report = evaluate_composition(
        [wrong_box], primary=wrong_box.name,
        expected_height=1.0, headroom_applies=False)
    assert wrong_report.score < PASS_SCORE
