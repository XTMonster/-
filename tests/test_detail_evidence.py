"""Detail observations become immutable, restorable shot evidence."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from PIL import Image

from block_director.cinema.evidence_builder import build_detail_shot_evidence
from block_director.contracts.blockout import manifest_fingerprint
from block_director.contracts.coarse_proposal import CoarseProposalRequest
from block_director.contracts.evidence import EvidenceStore
from block_director.contracts.knowledge import Card
from block_director.contracts.messages import (
    ChatReply,
    FunctionCall,
    ToolCall,
)
from block_director.contracts.observation import build_observation_bundle
from block_director.knowledge.retriever import KnowledgeRetriever
from block_director.layer5_orchestrator.coarse_agent import (
    AgentCoarseProposalProvider,
)


def _write_png(path, rgba):
    image = Image.new("RGBA", (4, 3))
    image.putdata([rgba] * 12)
    image.save(path)


def _observation(tmp_path, *, score=82.0, tag="base"):
    evidence_dir = (
        tmp_path / "detail" / "observations" / "shot_001" / tag
    )
    preview = evidence_dir / "preview"
    preview.mkdir(parents=True)
    frames = []
    for frame, phase, rgba in (
        (1, "first", (255, 0, 0, 255)),
        (12, "middle", (0, 255, 0, 255)),
        (24, "last", (0, 0, 255, 255)),
    ):
        path = preview / f"shot_001_f{frame:04d}.png"
        _write_png(path, rgba)
        frames.append({
            "shot_id": "shot_001",
            "frame": frame,
            "phase": phase,
            "png": str(path),
        })
    reference = {
        "schema_version": "coarse-world-reference/v1",
        "scene_id": "scene",
        "characters": [{
            "name": "甲",
            "position": {"x": 0.25, "y": 0.0, "z": 0.0},
            "facing": [0.0, 1.0, 0.0],
        }],
        "camera_intents": [{
            "shot_id": "shot_001",
            "position": [0.0, 3.0, 1.5],
            "target": [0.25, 0.0, 1.0],
            "lens": 35.0,
        }],
        "shots": [{
            "shot_id": "shot_001",
            "characters": ["甲"],
            "shot_type": "MS",
        }],
        "shot_staging": {
            "shot_001": {
                "甲": {
                    "position": {"x": 0.25, "y": 0.0, "z": 0.0},
                    "provenance": "agent_local_revision",
                },
            },
        },
    }
    manifest = {
        "schema_version": "blockout-manifest/v1",
        "scene_id": "scene",
        "primitives": [{
            "id": "char_jia",
            "kind": "character",
            "source": {"type": "character", "id": "甲"},
            "position": {"x": 0.25, "y": 0.0, "z": 0.0},
            "size": {"x": 0.6, "y": 0.6, "z": 1.7},
            "z_anchor": "foot",
        }],
        "cameras": [{
            "shot_id": "shot_001",
            "camera_id": "cam_shot_001",
            "position": [0.0, 3.0, 1.5],
            "target": [0.25, 0.0, 1.0],
        }],
        "shot_table": [{
            "shot_id": "shot_001",
            "character_ids": ["甲"],
            "prop_ids": [],
            "shot_type": "MS",
        }],
    }
    report = {
        "schema_version": "blockout-report/v1",
        "manifest_fingerprint": manifest_fingerprint(manifest),
        "verdict": "pass",
        "findings": [],
        "checks": [{
            "check_id": "composition",
            "shot_id": "shot_001",
            "actual": score,
            "threshold": 80.0,
            "verdict": "pass" if score > 80.0 else "fail",
        }],
    }
    world_state = {
        "schema_version": "runtime-world/v1",
        "characters": {
            "甲": {
                "position": [0.25, 0.0, 0.85],
                "facing": [0.0, 1.0, 0.0],
            },
        },
        "cameras": {
            "shot_001": {
                "position": [0.0, 3.0, 1.5],
                "target": [0.25, 0.0, 1.0],
                "lens_mm": 35.0,
            },
        },
        "props": {},
        "anchors": {},
        "shot_states": {
            "shot_001": {
                "frame": 1,
                "characters": {
                    "甲": {
                        "position": [0.25, 0.0, 0.85],
                        "facing": [0.0, 1.0, 0.0],
                    },
                },
                "cameras": {
                    "shot_001": {
                        "position": [0.0, 3.0, 1.5],
                        "target": [0.25, 0.0, 1.0],
                        "lens_mm": 35.0,
                    },
                },
                "props": {},
                "anchors": {},
            },
        },
    }
    bundle = build_observation_bundle(
        reference=reference,
        manifest=manifest,
        report=report,
        world_state=world_state,
        evidence_dir=evidence_dir,
        frame_records=frames,
    )
    return bundle, reference


def test_detail_observation_becomes_best_and_adopted_evidence(tmp_path):
    bundle, reference = _observation(tmp_path)
    store = EvidenceStore(run_id="run-detail", scene_id="scene")
    version = {
        "version": 0,
        "observation_id": bundle.observation_id,
        "score": 82.0,
        "passed": True,
        "physical_fingerprint": bundle.world_state_fingerprint,
        "disposition": "new_high",
        "candidate": reference,
        "operations": [],
        "knowledge_context": "composition guidance",
    }

    record = build_detail_shot_evidence(
        run_id="run-detail",
        scene_id="scene",
        plan={"shots": reference["shots"]},
        shot_id="shot_001",
        observation=bundle,
        version=version,
        detail_reason="detail_shot_passed",
    )
    store.append(record)
    store.mark_best("shot_001", 0)
    store.mark_adopted("shot_001", 0)

    assert record.verify_errors() == []
    assert record.frames[1]["phase"] == "middle"
    assert record.measurements["composition"]["score"] == 82.0
    assert record.disposition["status"] == "new_high"
    assert store.adopted_version("shot_001") == 0
    assert store.validate() == []


def test_semantic_review_uses_published_frame_paths(tmp_path):
    bundle, reference = _observation(tmp_path)
    evidence_dir = Path(bundle.evidence_dir)
    staging = evidence_dir / ".staging" / "preview"
    staging.mkdir(parents=True)
    report = copy.deepcopy(dict(bundle.report))
    visual_states = []
    for item in bundle.frames:
        staged = staging / Path(item.path).name
        shutil.copyfile(item.path, staged)
        visual_states.append({
            "shot_id": item.shot_id,
            "frame": item.frame,
            "phase": item.phase,
            "png": str(staged),
            "reviewed": True,
        })
    report["visual_states"] = visual_states
    observed = build_observation_bundle(
        reference=reference,
        manifest=bundle.manifest,
        report=report,
        world_state=bundle.world_state,
        evidence_dir=evidence_dir,
        frame_records=[item.to_dict() for item in bundle.frames],
    )

    record = build_detail_shot_evidence(
        run_id="run-detail",
        scene_id="scene",
        plan={"shots": reference["shots"]},
        shot_id="shot_001",
        observation=observed,
        version={
            "version": 0,
            "observation_id": observed.observation_id,
            "score": 82.0,
            "passed": True,
            "physical_fingerprint": observed.world_state_fingerprint,
            "disposition": "new_high",
            "candidate": reference,
            "operations": [],
        },
        detail_reason="detail_shot_passed",
    )

    reviewed = record.semantic_review["visual_states"]
    assert {row["png"] for row in reviewed} == {
        item.path for item in observed.frames}
    assert all(row["reviewed"] is True for row in reviewed)


def test_each_correction_candidate_records_its_disposition(tmp_path):
    bundle, reference = _observation(tmp_path)
    record = build_detail_shot_evidence(
        run_id="run-detail",
        scene_id="scene",
        plan={"shots": reference["shots"]},
        shot_id="shot_001",
        observation=bundle,
        version={
            "version": 1,
            "observation_id": bundle.observation_id,
            "score": 79.0,
            "passed": False,
            "physical_fingerprint": bundle.world_state_fingerprint,
            "disposition": "revert",
            "candidate": reference,
            "proposal": {
                "prescriptions": [
                    {"prescription_id": "applied"},
                    {"prescription_id": "rejected"},
                    {"prescription_id": "deferred"},
                ],
            },
            "operations": [
                {"prescription_id": "applied", "applied": True},
                {
                    "prescription_id": "rejected",
                    "applied": False,
                    "reason": "outside supported range",
                },
            ],
        },
        detail_reason="detail_revision_candidate",
    )

    assert {
        row["prescription_id"]: row["disposition"]
        for row in record.correction_candidates
    } == {
        "applied": "applied",
        "rejected": "rejected",
        "deferred": "deferred",
    }
    assert {
        row["prescription_id"]: row["disposition"]
        for row in record.applied_operations
    } == {
        "applied": "applied",
        "rejected": "rejected",
    }


def test_detail_evidence_preserves_the_unified_candidate_ledger(tmp_path):
    bundle, reference = _observation(tmp_path)
    record = build_detail_shot_evidence(
        run_id="run-detail",
        scene_id="scene",
        plan={"shots": reference["shots"]},
        shot_id="shot_001",
        observation=bundle,
        version={
            "version": 1,
            "observation_id": bundle.observation_id,
            "score": 82.0,
            "passed": True,
            "physical_fingerprint": bundle.world_state_fingerprint,
            "disposition": "new_high",
            "candidate": reference,
            "proposal": {
                "prescriptions": [{
                    "prescription_id": "reframe-001",
                    "candidate_ids": ["correction-both"],
                }],
            },
            "operations": [{
                "prescription_id": "reframe-001",
                "candidate_ids": ["correction-both"],
                "applied": True,
            }],
            "correction_candidates": [
                {
                    "candidate_id": "correction-both",
                    "kind": "subject_cut_by_edge",
                    "subject": "甲",
                    "source": "both",
                    "disposition": "applied",
                    "operation_ids": ["reframe-001"],
                },
                {
                    "candidate_id": "correction-vlm-deferred",
                    "kind": "occluded",
                    "subject": "甲",
                    "source": "vlm",
                    "disposition": "deferred",
                    "operation_ids": [],
                },
            ],
        },
        detail_reason="detail_correction_round_001",
    )

    assert {
        row["candidate_id"]: row["disposition"]
        for row in record.correction_candidates
    } == {
        "correction-both": "applied",
        "correction-vlm-deferred": "deferred",
    }
    assert record.correction["prescriptions"] == record.correction_candidates


def test_detail_agent_prompt_event_ledger_survives_into_shot_evidence(
    tmp_path,
):
    bundle, reference = _observation(tmp_path, score=70.0)
    audit_events = []
    retriever = KnowledgeRetriever(
        cards=[
            Card(
                id="detail-composition",
                domain="composition",
                title="MS composition",
                content="Composition repair keeps the subject readable.",
            ),
            Card(
                id="unrelated-light",
                domain="lighting",
                title="Warm practical",
                content="A practical motivates the warm key.",
            ),
            Card(
                id="unrelated-sound",
                domain="sound",
                title="Room tone",
                content="Room tone maintains continuity.",
            ),
        ],
        backend="bm25",
        top_k=1,
        audit=audit_events.append,
    )
    captured = {}

    class FakeTransport:
        def chat(self, payload):
            captured["prompt"] = json.dumps(
                [message.content for message in payload.messages],
                ensure_ascii=False,
            )
            return ChatReply(tool_calls=[ToolCall(
                id="detail-correction",
                function=FunctionCall(
                    name="emit_coarse_proposal",
                    arguments=json.dumps({
                        "schema_version": "coarse-proposal/v1",
                        "reason": "repair detail composition",
                        "prescriptions": [{
                            "prescription_id": "detail-move-jia",
                            "scope": "character",
                            "shot_id": "shot_001",
                            "entity": "甲",
                            "component": "character_position",
                            "target_value": {
                                "x": 0.5,
                                "y": 0.0,
                                "z": 0.0,
                            },
                            "reason": "restore composition",
                            "evidence_refs": ["composition:shot_001"],
                        }],
                    }),
                ),
            )])

    request = CoarseProposalRequest(
        round_no=1,
        observation_id=bundle.observation_id,
        reference=reference,
        report=bundle.report,
        frames=tuple(item.to_dict() for item in bundle.frames),
    )
    proposal = AgentCoarseProposalProvider(
        transport=FakeTransport(),
        knowledge=retriever,
        stage="detail",
    )(request=request)
    provenance = proposal["knowledge_provenance"]
    trace_events = retriever.trace_payload()["retrieval_events"]

    assert "[detail-composition]" in captured["prompt"]
    assert provenance["events"] == trace_events
    assert provenance["summary"]["actual_injected_tokens"] == sum(
        int(event["actual_injected_tokens"]) for event in trace_events
    )
    assert [
        event["retrieval_event_id"] for event in audit_events
    ] == [
        event["retrieval_event_id"] for event in trace_events
    ]

    record = build_detail_shot_evidence(
        run_id="run-detail-rag",
        scene_id="scene",
        plan={"shots": reference["shots"]},
        shot_id="shot_001",
        observation=bundle,
        version={
            "version": 1,
            "observation_id": bundle.observation_id,
            "score": 70.0,
            "passed": False,
            "physical_fingerprint": bundle.world_state_fingerprint,
            "disposition": "candidate",
            "candidate": reference,
            "proposal": proposal,
            "operations": [{
                "prescription_id": "detail-move-jia",
                "applied": True,
            }],
        },
        detail_reason="detail_correction_candidate",
    )

    rag = record.rag
    assert rag["event_count"] == len(trace_events)
    assert [
        event["retrieval_event_id"] for event in rag["events"]
    ] == [
        event["retrieval_event_id"] for event in trace_events
    ]
    assert rag["actual_injected_tokens"] == sum(
        int(event["actual_injected_tokens"]) for event in trace_events
    )
    assert rag["injected_ids"] == provenance["summary"][
        "injected_card_ids"]
    assert record.verify_errors() == []
