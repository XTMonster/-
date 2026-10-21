"""Regression probe for deterministic runtime performance identity.

The node-1..3 Agent run exposed a first-build failure where several compiled
tracks were reported as "not baked" while rebuilding the same manifest in the
same Blender process passed.  Identity checks correctly fail-closed; this probe
targets the runtime seam that made those identities drift.

The checked-in fixture is intentionally a captured real manifest.  A synthetic
two-action scene did not exercise the multi-shot Action lifecycle that caused
the failure.  Once the causal fixture is reduced further, this path can shrink.
"""

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

from block_director.contracts.performance_bake import (  # noqa: E402
    validate_performance_bake,
)
from block_director.layer3_engine.blockout_scene import (  # noqa: E402
    build_blockout_scene,
)
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
MANIFEST = ROOT / "fixtures" / "blockout_manifest_node123_r8.json"


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=8),
        }


def _identity(build: dict) -> dict:
    bake = dict(build.get("performance_bake") or {})
    tracks = list(bake.get("tracks") or [])
    return {
        "status": str(bake.get("status") or ""),
        "fingerprint": str(bake.get("fingerprint") or ""),
        "runtime_scene_state_fingerprint": str(
            bake.get("runtime_scene_state_fingerprint") or ""),
        "source_performance_fingerprint": str(
            bake.get("source_performance_fingerprint") or ""),
        "action_count": len(bake.get("actions") or []),
        "track_count": len(tracks),
        "track_fcurve_ref_count": sum(
            len(row.get("fcurve_refs") or [])
            for row in tracks
            if isinstance(row, dict)
        ),
        "tracks_without_fcurves": [
            {
                "shot_id": row.get("shot_id"),
                "entity_id": row.get("entity_id"),
                "action_id": row.get("action_id"),
                "layer": row.get("layer"),
            }
            for row in tracks
            if isinstance(row, dict)
            and not row.get("fcurve_refs")
        ],
        "failed_actions": [
            {
                "shot_id": row.get("shot_id"),
                "entity_id": row.get("entity_id"),
                "action_id": row.get("action_id"),
                "failures": list(row.get("failures") or []),
            }
            for row in bake.get("actions") or []
            if str(row.get("status") or "") != "baked"
        ],
    }


def _runtime_bake_is_complete(build: dict, manifest: dict) -> None:
    bake = build.get("performance_bake")
    assert isinstance(bake, dict), "build summary has no performance bake"
    assert not validate_performance_bake(bake, manifest=manifest), (
        "performance bake validation failed: "
        + "; ".join(validate_performance_bake(bake, manifest=manifest)))
    assert bake["status"] == "pass", _identity(build)
    assert not _identity(build)["failed_actions"], _identity(build)
    performance = manifest["performance"]
    expected_actions = sum(
        len(shot.get("actions") or [])
        for shot in performance.get("shots") or []
        if isinstance(shot, dict)
    )
    expected_tracks = sum(
        len(shot.get("records") or [])
        for shot in performance.get("shots") or []
        if isinstance(shot, dict)
    )
    actions = list(bake.get("actions") or [])
    tracks = list(bake.get("tracks") or [])
    assert len(actions) == expected_actions, (
        f"runtime action count {len(actions)} != compiled {expected_actions}")
    assert len(tracks) == expected_tracks, (
        f"runtime track count {len(tracks)} != compiled {expected_tracks}")
    assert all(
        row.get("fcurve_refs")
        for row in tracks
        if str(row.get("status") or "") == "baked"
    ), "a baked runtime track has no concrete FCurve reference"


def run_probe(out_dir: Path) -> dict:
    manifest_bytes = MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    assert len(manifest["performance"]["shots"]) == 11

    bpy.ops.wm.read_factory_settings(use_empty=True)
    first = dict(build_blockout_scene(manifest, clear_scene=True))
    first_identity = _identity(first)
    _runtime_bake_is_complete(first, manifest)

    second = dict(build_blockout_scene(manifest, clear_scene=True))
    second_identity = _identity(second)
    _runtime_bake_is_complete(second, manifest)

    mismatches: list[str] = []
    for key in (
        "status",
        "fingerprint",
        "runtime_scene_state_fingerprint",
        "source_performance_fingerprint",
        "action_count",
        "track_count",
        "track_fcurve_ref_count",
        "tracks_without_fcurves",
    ):
        if first_identity[key] != second_identity[key]:
            mismatches.append(
                f"{key}: {first_identity[key]!r} != {second_identity[key]!r}")

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest": {
            "path": str(MANIFEST),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
        "first": first_identity,
        "second": second_identity,
        "mismatches": mismatches,
    }
    (out_dir / "blockout_rebuild_identity_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": not mismatches, "checks": payload}


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = (
        ROOT
        / "docs"
        / "evidence"
        / "20261022-blockout-rebuild-identity-current"
    )
    for index, item in enumerate(argv):
        if item == "--out" and index + 1 < len(argv):
            out_dir = Path(argv[index + 1])
            break
    capture_main_thread()
    check(
        "same_manifest_first_and_second_build_have_same_complete_bake",
        lambda: run_probe(out_dir.resolve()),
    )
    failed = [
        name for name, result in RESULTS.items()
        if result.get("ok") is not True
    ]
    print("BD_TEST_RESULT " + json.dumps({
        "passed": [name for name in RESULTS if name not in failed],
        "failed": failed,
        "checks": RESULTS,
    }, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
