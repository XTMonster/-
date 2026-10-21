"""Shared camera-reference contract for design and Blender construction.

The coarse design snapshot and the scene builder must consume the same cast
facing. Otherwise a front camera solves to opposite world positions and the
spatial diff reports every shot as mirrored even though neither subsystem is
internally inconsistent.
"""

from __future__ import annotations

import sys
import types

from PIL import Image

from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.evidence import EvidenceStore
from block_director.contracts.plan import Plan, ShotPlan, ShotType
from block_director.contracts.observation import ObservationBundle
from block_director.cinema.schedule import travelled_positions
from block_director.cinema.spatial_design import build_design_snapshot
from block_director.layer5_orchestrator import coarse_pipeline


def _plan() -> Plan:
    return Plan(
        scene_heading="node_1_3",
        shots=[ShotPlan(
            shot_id="shot_001",
            order=1,
            intent="三人建立镜头",
            shot_type=ShotType.ELS,
            duration_frames=120,
            characters=["米迦尔", "偷盗者", "伊恩"],
            actions=[],
            camera={"side": "front", "lens": 24.0},
        )],
    )


def test_coarse_pipeline_forwards_cast_facings_to_design_snapshot(
    monkeypatch, tmp_path,
):
    captured = {}

    def fake_design(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "spatial-design-snapshot/v1",
            "scene_id": "node_1_3",
            "characters": [],
            "props": [],
            "anchors": [],
            "camera_intents": [],
            "notes": [],
        }

    scene_module = types.SimpleNamespace(
        build_blockout_scene=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "block_director.layer3_engine.blockout_scene",
        scene_module,
    )
    monkeypatch.setattr(coarse_pipeline, "build_design_snapshot", fake_design)
    monkeypatch.setattr(
        coarse_pipeline,
        "build_blockout_manifest",
        lambda **_kwargs: {},
    )
    def fake_loop(**kwargs):
        reference = kwargs["reference"]
        manifest = {
            "schema_version": "blockout-manifest/v1",
            "scene_id": "node_1_3",
            "primitives": [{
                "id": f"char_{index}",
                "kind": "character",
                "source": {"type": "character", "id": name},
            } for index, name in enumerate(("米迦尔", "偷盗者", "伊恩"))],
            "cameras": [{
                "camera_id": "cam_shot_001",
                "shot_id": "shot_001",
                "position": [0.0, 5.0, 2.0],
                "target": [0.0, 0.0, 1.0],
                "lens": 24.0,
                "start_frame": 1,
                "end_frame": 120,
            }],
            "shot_table": [{
                "shot_id": "shot_001",
                "order": 1,
                "character_ids": ["米迦尔", "偷盗者", "伊恩"],
                "prop_ids": [],
                "shot_type": "ELS",
            }],
        }
        report = {
            "schema_version": "blockout-report/v1",
            "manifest_fingerprint": manifest_fingerprint(manifest),
            "verdict": "fail",
            "findings": [],
            "checks": [{
                "check_id": "composition",
                "shot_id": "shot_001",
                "actual": 70.0,
                "threshold": 80.0,
                "verdict": "fail",
            }],
            "visual_states": [],
        }
        world_state = {
            "schema_version": "runtime-world/v1",
            "characters": {
                name: {
                    "position": position,
                    "facing": facing,
                }
                for name, position, facing in (
                    ("米迦尔", [-1.5, 0.0, 0.0], [1.0, 0.0, 0.0]),
                    ("偷盗者", [1.5, 0.0, 0.0], [-1.0, 0.0, 0.0]),
                    ("伊恩", [0.0, 2.0, 0.0], [0.0, 0.9962, 0.0872]),
                )
            },
            "cameras": {
                "shot_001": {
                    "position": [0.0, 5.0, 2.0],
                    "target": [0.0, 0.0, 1.0],
                    "lens_mm": 24.0,
                },
            },
            "props": {},
            "anchors": {},
        }
        preview = tmp_path / "observation" / "preview"
        preview.mkdir(parents=True, exist_ok=True)
        frame_records = []
        for phase, frame in (("first", 1), ("middle", 60), ("last", 120)):
            path = preview / f"shot_001_{phase}.png"
            Image.new("RGBA", (8, 8), (40, 80, 120, 255)).save(path)
            frame_records.append({
                "shot_id": "shot_001",
                "frame": frame,
                "phase": phase,
                "png": str(path),
                "readable": True,
            })
        observation = ObservationBundle.from_payload(
            reference=reference,
            manifest=manifest,
            report=report,
            world_state=world_state,
            evidence_dir=str(tmp_path / "observation"),
            frame_records=frame_records,
            complete_hint=True,
        )
        return {
            "status": "blocked",
            "blocked_code": "fixture_blocked",
            "blocked_reason": "fixture",
            "reference": reference,
            "report": report,
            "manifest": manifest,
            "world_state": world_state,
            "rounds": [],
            "observations": [observation.to_dict()],
            "best_observation": observation.to_dict(),
            "best_observation_id": observation.observation_id,
        }

    monkeypatch.setattr(
        coarse_pipeline,
        "run_coarse_revision_loop",
        fake_loop,
    )

    facings = {
        "米迦尔": [1.0, 0.0, 0.0],
        "偷盗者": [-1.0, 0.0, 0.0],
        "伊恩": [0.0, 0.9962, 0.0872],
    }
    coarse_pipeline.run_coarse_pipeline(
        plan=_plan(),
        out_dir=tmp_path / "coarse",
        cast_positions={
            "米迦尔": [-1.5, 0.0, 0.0],
            "偷盗者": [1.5, 0.0, 0.0],
            "伊恩": [0.0, 2.0, 0.0],
        },
        cast_facings=facings,
        scene_id="node_1_3",
    )

    assert captured["cast_facings"] == facings
    store = EvidenceStore.load(tmp_path / "coarse" / "coarse" / "evidence_store.json")
    assert len(store.history("shot_001")) == 1
    assert len(store.history("shot_001")[0].frames) == 3


def test_headless_coarse_gate_forwards_scene_spec_facings(
    monkeypatch, tmp_path,
):
    from block_director.contracts.cast import SceneSpec
    from tools.run_headless import _make_coarse_gate

    captured = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        baseline = tmp_path / "coarse" / "coarse_world_baseline.json"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text("{}", encoding="utf-8")
        return {
            "gates": {"coarse": "pass", "baseline": "frozen"},
            "artifacts": {"baseline": str(baseline)},
        }

    monkeypatch.setattr(coarse_pipeline, "run_coarse_pipeline", fake_runner)
    plan = _plan()
    gate = _make_coarse_gate(tmp_path)

    decision = gate(plan)

    expected = {
        member.name: list(member.initial_facing)
        for member in SceneSpec.from_plan(plan).cast
    }
    assert decision["ready"] is True
    assert captured["cast_facings"] == expected


def test_design_camera_uses_subject_position_at_each_shot_start():
    plan = Plan(
        scene_heading="walk_handover",
        shots=[
            ShotPlan(
                shot_id="shot_001",
                order=1,
                intent="伊恩走向右台",
                shot_type=ShotType.MS,
                duration_frames=48,
                characters=["伊恩"],
                actions=[{
                    "action_type": "walk_to",
                    "character_id": "伊恩",
                    "params": {"target_position": [4.0, 0.0, 0.0]},
                }],
                camera={"side": "front", "lens": 35.0},
            ),
            ShotPlan(
                shot_id="shot_002",
                order=2,
                intent="到达后近景",
                shot_type=ShotType.CU,
                duration_frames=48,
                characters=["伊恩"],
                actions=[],
                camera={"side": "front", "lens": 50.0},
            ),
        ],
    )
    initial = {"伊恩": [0.0, 0.0, 0.0]}
    projected = travelled_positions(plan, initial)
    assert projected["shot_002"]["伊恩"][0] == 4.0

    design = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions=initial,
        cast_facings={"伊恩": [0.0, 1.0, 0.0]},
        scene_id="walk_handover",
    )
    cameras = {
        item["shot_id"]: item for item in design["camera_intents"]
    }
    # The second camera must frame the carried position, not the scene's
    # initial origin. A front camera's target can shift horizontally by the
    # normal composition offset; a 4 m world handover is far larger.
    assert cameras["shot_002"]["target"][0] > 3.0


def test_design_camera_uses_subject_facing_after_turn_body():
    plan = Plan(
        scene_heading="turn_handover",
        shots=[
            ShotPlan(
                shot_id="shot_001",
                order=1,
                intent="伊恩转身面向左",
                shot_type=ShotType.MS,
                duration_frames=48,
                characters=["伊恩"],
                actions=[{
                    "action_type": "turn_body",
                    "character_id": "伊恩",
                    "params": {"angle_deg": 90.0},
                }],
                camera={"side": "front", "lens": 35.0},
            ),
            ShotPlan(
                shot_id="shot_002",
                order=2,
                intent="转身后的正面近景",
                shot_type=ShotType.CU,
                duration_frames=48,
                characters=["伊恩"],
                actions=[],
                camera={"side": "front", "lens": 50.0},
            ),
        ],
    )
    design = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={"伊恩": [0.0, 0.0, 0.0]},
        cast_facings={"伊恩": [0.0, 1.0, 0.0]},
        scene_id="turn_handover",
    )
    ian = next(
        item for item in design["characters"] if item["name"] == "伊恩")
    shot_two_facing = next(
        item["direction"] for item in ian["facing_by_shot"]
        if item["shot_id"] == "shot_002")
    assert shot_two_facing[0] < -0.99
    assert abs(shot_two_facing[1]) < 1e-6

    cameras = {
        item["shot_id"]: item for item in design["camera_intents"]
    }
    # A front camera stays in front of the turned subject: -X, not +Y.
    assert cameras["shot_002"]["position"][0] < -1.0
    assert abs(cameras["shot_002"]["position"][1]) < 1e-6


def test_design_camera_uses_walk_heading_after_position_handover():
    plan = Plan(
        scene_heading="walk_turn_handover",
        shots=[
            ShotPlan(
                shot_id="shot_001",
                order=1,
                intent="伊恩向右走",
                shot_type=ShotType.MS,
                duration_frames=48,
                characters=["伊恩"],
                actions=[{
                    "action_type": "walk_to",
                    "character_id": "伊恩",
                    "params": {"target_position": [4.0, 0.0, 0.0]},
                }],
                camera={"side": "front", "lens": 35.0},
            ),
            ShotPlan(
                shot_id="shot_002",
                order=2,
                intent="到达后的正面近景",
                shot_type=ShotType.CU,
                duration_frames=48,
                characters=["伊恩"],
                actions=[],
                camera={"side": "front", "lens": 50.0},
            ),
        ],
    )
    design = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={"伊恩": [0.0, 0.0, 0.0]},
        cast_facings={"伊恩": [0.0, 1.0, 0.0]},
        scene_id="walk_turn_handover",
    )
    ian = next(
        item for item in design["characters"] if item["name"] == "伊恩")
    shot_two = next(
        item for item in ian["facing_by_shot"]
        if item["shot_id"] == "shot_002")
    assert shot_two["direction"][0] > 0.99
    assert abs(shot_two["direction"][1]) < 1e-6

    camera = next(
        item for item in design["camera_intents"]
        if item["shot_id"] == "shot_002")
    # Facing +X means a front camera sits on +X of the carried position.
    assert camera["target"][0] > 3.0
    assert camera["position"][0] > camera["target"][0]


def test_plain_dict_plan_uses_the_same_per_shot_facing_projection():
    plan = {
        "scene_heading": "dict_turn_handover",
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "intent": "伊恩转身",
                "shot_type": "MS",
                "duration_frames": 48,
                "characters": ["伊恩"],
                "actions": [{
                    "action_type": "turn_body",
                    "character_id": "伊恩",
                    "params": {"angle_deg": 90.0},
                }],
                "camera": {"side": "front", "lens": 35.0},
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "intent": "转身后",
                "shot_type": "CU",
                "duration_frames": 48,
                "characters": ["伊恩"],
                "actions": [],
                "camera": {"side": "front", "lens": 50.0},
            },
        ],
    }
    design = build_design_snapshot(
        brief={},
        plan=plan,
        cast_positions={"伊恩": [0.0, 0.0, 0.0]},
        cast_facings={"伊恩": [0.0, 1.0, 0.0]},
        scene_id="dict_turn_handover",
    )
    ian = next(
        item for item in design["characters"] if item["name"] == "伊恩")
    shot_two = next(
        item for item in ian["facing_by_shot"]
        if item["shot_id"] == "shot_002")
    assert shot_two["direction"][0] < -0.99
