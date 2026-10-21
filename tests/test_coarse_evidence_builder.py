"""Coarse evidence must project the physical state of the named shot."""

from __future__ import annotations

import copy
import json

from PIL import Image

from block_director.cinema.evidence_builder import build_shot_evidence_store
from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.coarse_proposal import CoarseProposalRequest
from block_director.contracts.knowledge import Card
from block_director.contracts.messages import (
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.contracts.observation import ObservationBundle
from block_director.knowledge.retriever import KnowledgeRetriever
from block_director.layer5_orchestrator.coarse_agent import (
    AgentCoarseProposalProvider,
)


def _fixture():
    reference = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [
            {"name": "甲", "position": {"x": 0.0, "y": 0.0, "z": 0.0}},
            {"name": "乙", "position": {"x": 0.0, "y": 0.0, "z": 0.0}},
        ],
        "camera_intents": [
            {"shot_id": "shot_001", "position": [0.0, 3.0, 1.5],
             "target": [0.0, 0.0, 1.0], "lens": 35.0},
            {"shot_id": "shot_002", "position": [0.0, 4.0, 1.5],
             "target": [0.0, 0.0, 1.0], "lens": 50.0},
        ],
        "shots": [
            {"shot_id": "shot_001", "order": 1, "characters": ["甲"]},
            {"shot_id": "shot_002", "order": 2, "characters": ["乙"]},
        ],
    }
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene",
        "primitives": [],
        "cameras": [
            {"shot_id": "shot_001", "camera_id": "cam_shot_001",
             "start_frame": 1, "end_frame": 24},
            {"shot_id": "shot_002", "camera_id": "cam_shot_002",
             "start_frame": 25, "end_frame": 48},
        ],
        "shot_table": [
            {"shot_id": "shot_001", "order": 1, "character_ids": ["甲"],
             "start_frame": 1, "end_frame": 24},
            {"shot_id": "shot_002", "order": 2, "character_ids": ["乙"],
             "start_frame": 25, "end_frame": 48},
        ],
    }
    report = {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "verdict": "fail",
        "findings": [],
        "checks": [
            {"check_id": "composition", "shot_id": "shot_001",
             "actual": 70.0, "threshold": 80.0, "verdict": "fail"},
            {"check_id": "composition", "shot_id": "shot_002",
             "actual": 72.0, "threshold": 80.0, "verdict": "fail"},
        ],
        "visual_states": [],
    }
    world_state = {
        "schema_version": "runtime-world/v1",
        # Deliberately the state at an arbitrary third frame. It must not leak
        # into either shot's evidence slice.
        "characters": {
            "甲": {"position": [9.0, 9.0, 0.0], "facing": [0.0, 1.0, 0.0]},
            "乙": {"position": [8.0, 8.0, 0.0], "facing": [0.0, 1.0, 0.0]},
        },
        "cameras": {
            "shot_001": {"position": [9.0, 3.0, 1.5],
                         "target": [9.0, 0.0, 1.0], "lens_mm": 35.0},
            "shot_002": {"position": [8.0, 4.0, 1.5],
                         "target": [8.0, 0.0, 1.0], "lens_mm": 50.0},
        },
        "props": {},
        "anchors": {},
        "shot_states": {
            "shot_001": {
                "frame": 1,
                "characters": {
                    "甲": {"position": [1.0, 0.0, 0.0],
                           "facing": [0.0, 1.0, 0.0]},
                    "乙": {"position": [2.0, 0.0, 0.0],
                           "facing": [0.0, 1.0, 0.0]},
                },
                "cameras": {
                    "shot_001": {"position": [1.0, 3.0, 1.5],
                                 "target": [1.0, 0.0, 1.0],
                                 "lens_mm": 35.0},
                },
                "props": {},
                "anchors": {},
            },
            "shot_002": {
                "frame": 25,
                "characters": {
                    "甲": {"position": [3.0, 0.0, 0.0],
                           "facing": [0.0, 1.0, 0.0]},
                    "乙": {"position": [4.0, 0.0, 0.0],
                           "facing": [0.0, 1.0, 0.0]},
                },
                "cameras": {
                    "shot_002": {"position": [4.0, 4.0, 1.5],
                                 "target": [4.0, 0.0, 1.0],
                                 "lens_mm": 50.0},
                },
                "props": {},
                "anchors": {},
            },
        },
    }
    bundle = ObservationBundle.from_payload(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir="memory/attempt-001",
        frame_records=[],
        complete_hint=False,
    )
    return bundle


def test_shot_slice_uses_that_shots_physical_state_not_the_global_frame():
    store = build_shot_evidence_store(
        run_id="run",
        scene_id="scene",
        plan={"shots": _fixture().reference["shots"]},
        observations=[_fixture()],
    )

    first = store.get("shot_001", 0).shot_slice["world_state"]
    second = store.get("shot_002", 0).shot_slice["world_state"]

    assert first["characters"] == {
        "甲": {"position": [1.0, 0.0, 0.0],
              "facing": [0.0, 1.0, 0.0]},
    }
    assert set(first["cameras"]) == {"shot_001"}
    assert first["cameras"]["shot_001"]["position"] == [1.0, 3.0, 1.5]
    assert second["characters"] == {
        "乙": {"position": [4.0, 0.0, 0.0],
              "facing": [0.0, 1.0, 0.0]},
    }
    assert set(second["cameras"]) == {"shot_002"}
    assert second["cameras"]["shot_002"]["position"] == [4.0, 4.0, 1.5]


def test_correction_belongs_to_the_candidate_it_created_not_the_triggering_shot():
    first = _fixture()
    candidate_world = copy.deepcopy(first.world_state)
    candidate_world["shot_states"]["shot_001"]["characters"]["甲"]["position"] = [
        1.5,
        0.5,
        0.0,
    ]
    candidate = ObservationBundle.from_payload(
        reference=first.reference,
        manifest=first.manifest,
        report=first.report,
        world_state=candidate_world,
        evidence_dir="memory/attempt-002",
        frame_records=[],
        complete_hint=False,
    )
    prescription = {
        "prescription_id": "move_jia",
        "shot_id": "shot_001",
        "scope": "character",
        "entity": "甲",
        "applied": True,
    }

    store = build_shot_evidence_store(
        run_id="run",
        scene_id="scene",
        plan={"shots": first.reference["shots"]},
        observations=[first, candidate],
        rounds=[{
            "round_no": 1,
            "observation_id": first.observation_id,
            "candidate_observation_id": candidate.observation_id,
            "proposal": {
                "knowledge_provenance": {
                    "status": "injected",
                    "scope": "coarse",
                    "shot_id": "shot_001",
                },
            },
            "prescriptions": [
                prescription,
                {**prescription, "shot_id": "shot_002",
                 "entity": "乙"},
            ],
            "disposition": "applied_and_remeasured",
        }],
    )

    trigger = store.get("shot_001", 0)
    rebuilt = store.get("shot_001", 1)

    assert trigger.correction_candidates == []
    assert trigger.applied_operations == []
    assert trigger.rag == {}
    assert [row["prescription_id"] for row in rebuilt.correction_candidates] == [
        "move_jia"]
    assert [row["disposition"] for row in rebuilt.applied_operations] == [
        "applied"]
    assert rebuilt.rag["scope"] == "coarse"
    assert rebuilt.remeasurement["status"] == "measured"


def test_retrieval_hits_are_not_injection_when_canonical_events_dropped_them():
    first = _fixture()
    candidate_world = copy.deepcopy(first.world_state)
    candidate_world["shot_states"]["shot_002"]["characters"]["乙"][
        "position"] = [4.5, 0.5, 0.0]
    candidate = ObservationBundle.from_payload(
        reference=first.reference,
        manifest=first.manifest,
        report=first.report,
        world_state=candidate_world,
        evidence_dir="memory/attempt-002",
        frame_records=[],
        complete_hint=False,
    )
    event = {
        "retrieval_event_id": "retrieval-0007",
        "stage": "coarse",
        "scope": "shot",
        "shot_id": "shot_002",
        "hit_ids": ["card-eye-line", "edge-eye-line"],
        "hit_card_ids": ["card-eye-line"],
        "hit_edge_ids": ["edge-eye-line"],
        "injected_card_ids": [],
        "actual_injected_tokens": 0,
        "drops": [{
            "id": "card-eye-line",
            "kind": "card",
            "reason": "token_budget",
        }],
        "actual_backend": "bm25",
        "degraded": False,
        "injected": False,
    }

    store = build_shot_evidence_store(
        run_id="run",
        scene_id="scene",
        plan={"shots": first.reference["shots"]},
        observations=[first, candidate],
        rounds=[{
            "round_no": 1,
            "observation_id": first.observation_id,
            "candidate_observation_id": candidate.observation_id,
            "proposal": {
                "knowledge_provenance": {
                    "status": "retrieved",
                    "per_shot_trace": {
                        "shot_002": {
                            "status": "retrieved",
                            "hit_ids": ["card-eye-line"],
                            "actual_injected_tokens": 0,
                            "injected": False,
                        },
                    },
                    "events": [event],
                },
            },
            "prescriptions": [{
                "prescription_id": "move-yi",
                "shot_id": "shot_002",
                "scope": "character",
                "entity": "乙",
                "applied": True,
            }],
            "disposition": "applied_and_remeasured",
        }],
    )

    rag = store.get("shot_002", 1).rag

    assert rag["hit_ids"] == ["card-eye-line", "edge-eye-line"]
    assert rag["injected"] is False
    assert rag["status"] == "no_hits"
    assert rag["events"][0]["retrieval_event_id"] == "retrieval-0007"


def test_coarse_audit_trace_prompt_and_shot_evidence_share_canonical_events(
    tmp_path,
):
    first = _fixture()
    for shot in first.reference["shots"]:
        shot["shot_type"] = "CU"
        shot["intent"] = "axis composition"

    frames = []
    for shot_id in ("shot_001", "shot_002"):
        for phase, frame in (("first", 1), ("middle", 12), ("last", 24)):
            path = tmp_path / f"{shot_id}-{phase}.png"
            Image.new("RGB", (8, 6), (20, 40, 60)).save(path)
            frames.append({
                "shot_id": shot_id,
                "phase": phase,
                "frame": frame,
                "path": str(path),
                "file_sha256": "a" * 64,
                "pixel_sha256": "b" * 64,
                "readable": True,
            })

    audit_events = []
    retriever = KnowledgeRetriever(
        cards=[
            Card(
                id="axis-composition",
                domain="composition",
                title="Axis composition",
                content="axis composition keeps the subject readable.",
            ),
            Card(
                id="unrelated-lighting",
                domain="lighting",
                title="Practical light",
                content="A practical lamp motivates the warm key.",
            ),
            Card(
                id="unrelated-sound",
                domain="sound",
                title="Room tone",
                content="Room tone maintains an even background.",
            ),
        ],
        backend="bm25",
        top_k=1,
        audit=audit_events.append,
    )
    captured = {}

    class FakeTransport:
        def chat(self, payload):
            captured["payload"] = payload
            return ChatReply(tool_calls=[ToolCall(
                id="coarse-four-way",
                function=FunctionCall(
                    name="emit_coarse_proposal",
                    arguments=json.dumps({
                        "schema_version": "coarse-proposal/v1",
                        "reason": "restore composition",
                        "prescriptions": [{
                            "prescription_id": "move-jia",
                            "scope": "character",
                            "shot_id": "shot_001",
                            "entity": "甲",
                            "component": "character_position",
                            "target_value": {
                                "x": 1.5,
                                "y": 0.0,
                                "z": 0.0,
                            },
                            "reason": "axis composition",
                            "evidence_refs": ["composition:shot_001"],
                        }],
                    }),
                ),
            )])

    request = CoarseProposalRequest(
        round_no=1,
        observation_id="obs-four-way",
        reference=first.reference,
        report=first.report,
        frames=tuple(frames),
    )
    proposal = AgentCoarseProposalProvider(
        transport=FakeTransport(),
        knowledge=retriever,
    )(request=request)
    provenance = proposal["knowledge_provenance"]

    trace_events = retriever.trace_payload()["retrieval_events"]
    provenance_ids = [
        event["retrieval_event_id"] for event in provenance["events"]
    ]
    audit_ids = [
        event["retrieval_event_id"] for event in audit_events
    ]
    trace_ids = [
        event["retrieval_event_id"] for event in trace_events
    ]
    assert provenance_ids == audit_ids == trace_ids
    assert provenance["event_count"] == len(trace_ids) == 2

    prompt = json.dumps(
        [message.content for message in captured["payload"].messages],
        ensure_ascii=False,
    )
    assert "[axis-composition]" in prompt
    assert provenance["summary"]["injected_card_ids"] == ["axis-composition"]
    assert provenance["summary"]["actual_injected_tokens"] == sum(
        event["actual_injected_tokens"] for event in trace_events
    )

    candidate_world = copy.deepcopy(first.world_state)
    candidate_world["shot_states"]["shot_001"]["characters"]["甲"][
        "position"] = [1.5, 0.0, 0.0]
    candidate = ObservationBundle.from_payload(
        reference=first.reference,
        manifest=first.manifest,
        report=first.report,
        world_state=candidate_world,
        evidence_dir="memory/attempt-002",
        frame_records=[],
        complete_hint=False,
    )
    store = build_shot_evidence_store(
        run_id="run",
        scene_id="scene",
        plan={"shots": first.reference["shots"]},
        observations=[first, candidate],
        rounds=[{
            "round_no": 1,
            "observation_id": first.observation_id,
            "candidate_observation_id": candidate.observation_id,
            "proposal": proposal,
            "prescriptions": [{
                "prescription_id": "move-jia",
                "shot_id": "shot_001",
                "scope": "character",
                "entity": "甲",
                "applied": True,
            }],
            "disposition": "applied_and_remeasured",
        }],
    )
    first_rag = store.get("shot_001", 1).rag
    second_rag = store.get("shot_002", 1).rag
    assert [
        event["retrieval_event_id"] for event in first_rag["events"]
    ] == [provenance["per_shot_events"]["shot_001"][0][
        "retrieval_event_id"]]
    assert [
        event["retrieval_event_id"] for event in second_rag["events"]
    ] == [provenance["per_shot_events"]["shot_002"][0][
        "retrieval_event_id"]]
    assert first_rag["actual_injected_tokens"] == (
        first_rag["events"][0]["actual_injected_tokens"])
    assert second_rag["actual_injected_tokens"] == (
        second_rag["events"][0]["actual_injected_tokens"])
    assert first_rag["injected"] is True
    assert second_rag["injected"] is True
