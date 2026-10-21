"""Probe: the production detail session observes one shot as immutable evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402


def _design() -> dict:
    return {
        "schema_version": "spatial-design-snapshot/v1",
        "scene_id": "detail-session-observation",
        "characters": [
            {
                "name": "甲",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
                "provenance": "plan_intent",
            },
            {
                "name": "乙",
                "position": {"x": 3.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
                "provenance": "plan_intent",
            },
        ],
        "props": [],
        "anchors": [],
        "camera_intents": [
            {
                "shot_id": "shot_001",
                "position": [0.0, -5.0, 1.6],
                "target": [0.0, 0.0, 1.0],
                "lens": 50.0,
            },
            {
                "shot_id": "shot_002",
                "position": [3.0, -5.0, 1.6],
                "target": [3.0, 0.0, 1.0],
                "lens": 50.0,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["甲"],
                "shot_type": "MS",
                "framing_target": {
                    "kind": "character",
                    "ref": "甲",
                    "part": "none",
                },
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["乙"],
                "shot_type": "MS",
                "framing_target": {
                    "kind": "character",
                    "ref": "乙",
                    "part": "none",
                },
            },
        ],
        "shot_staging": {},
    }


def _plan(design: dict) -> dict:
    return {"shots": [dict(shot) for shot in design["shots"]]}


def _baseline(design: dict, plan: dict) -> dict:
    from block_director.cinema.blockout import build_blockout_manifest

    manifest = build_blockout_manifest(design=design, plan=plan)
    return {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference": design,
        "manifest": manifest,
        "report": {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [
                {
                    "check_id": "composition",
                    "shot_id": shot_id,
                    "actual": 88.0,
                    "threshold": 80.0,
                    "verdict": "pass",
                }
                for shot_id in ("shot_001", "shot_002")
            ],
        },
    }


class _Judge:
    provider = "probe"
    model = "configured-judge"

    def __init__(self) -> None:
        self.calls = []

    def chat(self, payload, timeout=60.0):
        from block_director.contracts.messages import ChatReply

        self.calls.append(payload)
        return ChatReply(
            content=json.dumps({
                "score": 4,
                "reason": "构图可读",
                "issues": [],
            }, ensure_ascii=False),
            model="probe-judge-v1",
            request_id="detail-review-1",
            finish_reason="stop",
        )


def run_probe(out_dir: Path) -> dict:
    import copy

    from block_director.contracts.config import VlmReviewConfig
    from block_director.layer3_engine.detail_session import DetailSceneSession
    from block_director.contracts.observation import build_observation_bundle

    bpy.ops.wm.read_factory_settings(use_empty=True)
    design = _design()
    plan = _plan(design)
    baseline = _baseline(design, plan)
    judge = _Judge()
    review_config = VlmReviewConfig()
    review_config.enabled = True
    review_config.required = True
    session = DetailSceneSession(
        baseline=baseline,
        plan=plan,
        out_dir=out_dir,
        run_id="detail-session-probe",
        scene_id=design["scene_id"],
        vlm_review=review_config,
        vlm_transport=judge,
    )
    session.prepare()
    observation = session.observe(session.reference, "shot_001")
    version = {
        "version": 0,
        "observation_id": observation.observation_id,
        "score": 88.0,
        "passed": True,
        "physical_fingerprint": observation.world_state_fingerprint,
        "disposition": "new_high",
        "candidate": session.reference,
        "operations": [],
        "knowledge_context": "",
        "proposal": {},
    }
    session.record_evidence("shot_001", observation, version)
    worse_report = copy.deepcopy(dict(observation.report))
    for check in worse_report.get("checks") or []:
        if check.get("check_id") == "composition":
            check["actual"] = 69.0
            check["verdict"] = "fail"
    worse = build_observation_bundle(
        reference=observation.reference,
        manifest=observation.manifest,
        report=worse_report,
        world_state=observation.world_state,
        evidence_dir=observation.evidence_dir,
        frame_records=[frame.to_dict() for frame in observation.frames],
    )
    session.record_evidence(
        "shot_001",
        worse,
        {
            "version": 1,
            "observation_id": worse.observation_id,
            "score": 69.0,
            "passed": False,
            "physical_fingerprint": worse.world_state_fingerprint,
            "disposition": "revert",
            "candidate": session.reference,
            "operations": [],
            "knowledge_context": "",
            "proposal": {},
        },
    )
    sequence_review = dict(session.review_sequence(session.reference))

    observation_dir = (
        out_dir / "observations" / "shot_001" / observation.observation_id)
    store = session.evidence_store
    record = store.get("shot_001", 0)
    semantic = record.semantic_review
    reviewed_frames = list(semantic.get("visual_states") or [])
    reviewed_hashes = [
        hashlib.sha256(Path(str(frame["path"])).read_bytes()).hexdigest()
        for frame in reviewed_frames
    ]
    composition_shots = {
        str(row.get("shot_id") or "")
        for row in observation.report.get("checks") or []
        if row.get("check_id") == "composition"
    }
    preview_shots = {
        str(frame.shot_id or "") for frame in observation.frames
    }
    frame_paths = [Path(str(frame.path)).resolve()
                   for frame in observation.frames]
    checks = {
        "observation_complete": observation.complete,
        "observation_verify_errors_empty": (
            observation.verify_errors() == []),
        "observation_json_written": (
            observation_dir / "observation.json").is_file(),
        "reference_json_written": (
            observation_dir / "reference.json").is_file(),
        "manifest_json_written": (
            observation_dir / "manifest.json").is_file(),
        "world_state_json_written": (
            observation_dir / "world_state.json").is_file(),
        "three_target_frames": (
            [frame.phase for frame in observation.frames]
            == ["first", "middle", "last"]),
        "frames_self_contained": (
            bool(frame_paths)
            and all(
                path.is_file()
                and path.is_relative_to(observation_dir.resolve())
                for path in frame_paths
            )),
        "record_frames_match_observation": (
            [Path(str(item.get("path"))).resolve()
             for item in record.frames] == frame_paths),
        "frames_only_target": preview_shots == {"shot_001"},
        "report_only_target": composition_shots == {"shot_001"},
        "no_sequence_mismatch": not any(
            row.get("check_id") == "E_BLOCKOUT_SHOT_SEQUENCE_MISMATCH"
            for row in observation.report.get("findings") or []),
        "evidence_record_verified": record.verify_errors() == [],
        "evidence_has_three_frames": len(record.frames) == 3,
        "detail_observe_called_vision_judge": len(judge.calls) == 1,
        "vlm_review_preserved_in_observation": (
            observation.report.get("vlm_review", {}).get("status") == "ok"),
        "vlm_reviewed_pass_is_not_program_override": (
            observation.report.get("vlm_review", {}).get("score") == 4
            and record.measurements.get("composition", {}).get("score")
            == 88.0),
        "semantic_review_is_exact_reviewed_frames": (
            semantic.get("status") == "reviewed"
            and [row.get("label") for row in reviewed_frames]
            == ["first", "middle", "last"]
            and [row.get("file_sha256") for row in reviewed_frames]
            == reviewed_hashes
            and all(
                Path(str(row["path"])).is_relative_to(
                    observation_dir.resolve())
                for row in reviewed_frames)),
        "review_provider_model_and_prompt_preserved": (
            semantic.get("provider") == "probe"
            and semantic.get("configured_model") == "configured-judge"
            and semantic.get("model") == "probe-judge-v1"
            and semantic.get("request_id") == "detail-review-1"
            and len(semantic.get("prompt_sha256") or "") == 64),
        "evidence_store_saved": (
            out_dir / "evidence_store.json").is_file(),
        "best_version_is_zero": store.best_version("shot_001") == 0,
        "adopted_version_is_zero": (
            store.adopted_version("shot_001") == 0),
        "revert_did_not_replace_best": (
            store.best_version("shot_001") == 0
            and store.adopted_version("shot_001") == 0),
        "history_retains_revert_candidate": (
            len(store.history("shot_001")) == 2
            and store.get("shot_001", 1).disposition.get("status")
            == "revert"),
        "session_sequence_review_wired": (
            sequence_review.get("verdict") == "pass"),
        "session_sequence_review_written": (
            out_dir / "sequence_review" / "sequence_review.json").is_file(),
        "store_validation_empty": store.validate() == [],
    }
    payload = {
        "ok": all(checks.values()),
        "checks": checks,
        "observation_id": observation.observation_id,
        "observation_dir": str(observation_dir),
        "record": record.to_dict(),
        "store": store.summary(),
        "sequence_review": sequence_review,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail_observation_session_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = ROOT / "docs" / "evidence" / "20261021-detail-session-observe"
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    try:
        result = run_probe(out_dir.resolve())
    except Exception as exc:  # noqa: BLE001
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=8),
        }
    print("BD_TEST_RESULT " + json.dumps({
        **result,
        "passed": 1 if result.get("ok") else 0,
        "failed": 0 if result.get("ok") else 1,
        "checks": result.get("checks") or {},
    }, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
