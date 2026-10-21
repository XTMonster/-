"""Coarse evidence must retain the staging that was effective per shot."""

from __future__ import annotations

from PIL import Image

from block_director.cinema.evidence_builder import build_shot_evidence_store
from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.observation import build_observation_bundle


def _write_frame(path, colour):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 6), colour).save(path)


def test_shot_slice_materializes_each_shots_effective_character_position(tmp_path):
    reference = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [2.0, 0.0, 1.0],
                "lens": 35.0,
            },
            {
                "shot_id": "shot_002",
                "position": [0.0, -3.0, 1.5],
                "target": [-2.0, 0.0, 1.0],
                "lens": 35.0,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["甲"],
                "actions": [],
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["甲"],
                "actions": [],
            },
        ],
        "shot_staging": {
            "shot_001": {
                "甲": {
                    "position": {"x": 2.0, "y": 0.2, "z": 0.0},
                    "provenance": "agent_local_revision",
                    "reason": "第一镜向画面右侧调位",
                },
            },
            "shot_002": {
                "甲": {
                    "position": {"x": -2.0, "y": -0.1, "z": 0.0},
                    "provenance": "agent_local_revision",
                    "reason": "第二镜向画面左侧调位",
                },
            },
        },
        "revisions": [],
        "notes": [],
    }
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene",
        "primitives": [],
        "cameras": [],
        "shot_table": [
            {"shot_id": "shot_001"},
            {"shot_id": "shot_002"},
        ],
    }
    frames = []
    for shot_id in ("shot_001", "shot_002"):
        for phase, frame, colour in (
            ("first", 1, (255, 0, 0, 255)),
            ("middle", 12, (0, 255, 0, 255)),
            ("last", 24, (0, 0, 255, 255)),
        ):
            path = tmp_path / shot_id / f"{phase}.png"
            _write_frame(path, colour)
            frames.append({
                "shot_id": shot_id,
                "frame": frame,
                "phase": phase,
                "png": str(path),
            })
    report = {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "verdict": "fail",
        "findings": [],
        "checks": [
            {
                "check_id": "composition",
                "shot_id": shot_id,
                "actual": 70.0,
                "threshold": 80.0,
                "verdict": "fail",
            }
            for shot_id in ("shot_001", "shot_002")
        ],
        "visual_states": [],
    }
    world_state = {
        "schema_version": "runtime-world/v1",
        "characters": {
            "甲": {
                "position": [0.0, 0.0, 0.0],
                "facing": [0.0, 1.0, 0.0],
            },
        },
        "cameras": {},
        "props": {},
        "render_staging": {
            "shot_001": {
                "characters": {
                    "甲": {
                        "planned_position": {"x": 2.0, "y": 0.2, "z": 0.0},
                        "actual_origin": [2.0, 0.2, 0.8],
                        "provenance": "agent_local_revision",
                        "reason": "第一镜向画面右侧调位",
                    },
                },
                "restored": True,
                "restore_verified": True,
            },
            "shot_002": {
                "characters": {
                    "甲": {
                        "planned_position": {
                            "x": -2.0, "y": -0.1, "z": 0.0,
                        },
                        "actual_origin": [-2.0, -0.1, 0.8],
                        "provenance": "agent_local_revision",
                        "reason": "第二镜向画面左侧调位",
                    },
                },
                "restored": True,
                "restore_verified": True,
            },
        },
    }
    observation = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=tmp_path / "evidence",
        frame_records=frames,
    )

    store = build_shot_evidence_store(
        run_id="run",
        scene_id="scene",
        plan={"shots": reference["shots"]},
        observations=[observation],
    )

    first = store.history("shot_001")[0].shot_slice["reference"]
    second = store.history("shot_002")[0].shot_slice["reference"]
    assert first["characters"][0]["position"] == {
        "x": 2.0, "y": 0.2, "z": 0.0,
    }
    assert second["characters"][0]["position"] == {
        "x": -2.0, "y": -0.1, "z": 0.0,
    }
    assert first["characters"][0]["position_provenance"] == (
        "agent_local_revision")
    assert first["characters"][0]["effective_shot_id"] == "shot_001"
    assert second["characters"][0]["effective_shot_id"] == "shot_002"
    assert first["staging"]["overlay"]["甲"]["reason"] == (
        "第一镜向画面右侧调位")
    assert first["staging"]["render_audit"]["restore_verified"] is True
    assert first["staging"]["render_audit"]["characters"]["甲"][
        "planned_position"] == {"x": 2.0, "y": 0.2, "z": 0.0}


def test_shot_evidence_preserves_only_this_shots_rag_attribution(tmp_path):
    reference = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, 3.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
            },
            {
                "shot_id": "shot_002",
                "position": [3.0, 0.0, 1.5],
                "target": [0.0, 0.0, 1.0],
                "lens": 35.0,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["甲"],
                "actions": [],
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["甲"],
                "actions": [],
            },
        ],
        "revisions": [],
        "notes": [],
    }
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene",
        "primitives": [],
        "cameras": [],
        "shot_table": [
            {"shot_id": "shot_001"},
            {"shot_id": "shot_002"},
        ],
    }

    def observation(score, marker):
        frames = []
        for shot_id in ("shot_001", "shot_002"):
            for phase, frame, colour in (
                ("first", 1, (255, 0, 0, 255)),
                ("middle", 12, (0, 255, 0, 255)),
                ("last", 24, (0, 0, 255, 255)),
            ):
                path = tmp_path / marker / shot_id / f"{phase}.png"
                _write_frame(path, colour)
                frames.append({
                    "shot_id": shot_id,
                    "frame": frame,
                    "phase": phase,
                    "png": str(path),
                })
        report = {
            "schema_version": "blockout-report/v1",
            "manifest_fingerprint": manifest_fingerprint(manifest),
            "verdict": "fail",
            "findings": [],
            "checks": [
                {
                    "check_id": "composition",
                    "shot_id": shot_id,
                    "actual": score,
                    "threshold": 80.0,
                    "verdict": "fail",
                }
                for shot_id in ("shot_001", "shot_002")
            ],
            "rag_provenance": {
                "status": "retrieved",
                "injected_blocks": {"shot_002": "报告级错误归属"},
            },
        }
        return build_observation_bundle(
            reference=reference,
            manifest=manifest,
            report=report,
            world_state={
                "schema_version": "runtime-world/v1",
                "characters": {},
                "cameras": {},
                "props": {},
            },
            evidence_dir=tmp_path / marker,
            frame_records=frames,
        )

    initial = observation(70.0, "initial")
    candidate = observation(72.0, "candidate")
    proposal = {
        "schema_version": "coarse-proposal/v1",
        "provider_kind": "agent_model",
        "observation_id": initial.observation_id,
        "reason": "根据镜头语言知识把第一镜人物向画面右侧调整",
        "knowledge_provenance": {
            "status": "retrieved",
            "injected_blocks": {"shot_001": "硬规则：视线留白必须在眼线方向"},
            "per_shot_trace": {
                "shot_001": {
                    "backend": "bm25",
                    "degraded": False,
                    "query": "第一镜构图 70 分",
                    "actual_injected_tokens": 24,
                    "hit_ids": ["card-eye-line"],
                    "dropped_ids": [],
                },
            },
        },
    }
    rounds = [{
        "round_no": 1,
        "observation_id": initial.observation_id,
        "candidate_observation_id": candidate.observation_id,
        "provider_kind": "agent_model",
        "proposal": proposal,
        "prescriptions": [{
            "prescription_id": "p1",
            "shot_id": "shot_001",
            "applied": True,
        }],
    }]

    store = build_shot_evidence_store(
        run_id="run",
        scene_id="scene",
        plan={"shots": reference["shots"]},
        observations=[initial, candidate],
        rounds=rounds,
    )

    first_rag = store.history("shot_001")[1].rag
    second_rag = store.history("shot_002")[1].rag
    assert first_rag["status"] == "retrieved"
    assert first_rag["provider_kind"] == "agent_model"
    assert first_rag["proposal_reason"] == proposal["reason"]
    assert first_rag["backend"] == "bm25"
    assert first_rag["actual_injected_tokens"] == 24
    assert first_rag["hit_ids"] == ["card-eye-line"]
    assert first_rag["injected"] is True
    assert first_rag["block"] == "硬规则：视线留白必须在眼线方向"
    assert second_rag == {
        "shot_id": "shot_002",
        "status": "no_hits",
        "provider_kind": "agent_model",
        "proposal_reason": proposal["reason"],
        "injected": False,
    }
