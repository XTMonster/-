"""Probe: detail apply/restore owns target props but never neighbor props."""

from __future__ import annotations

import copy
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
        "scene_id": "detail-session-prop-scope",
        "characters": [
            {
                "name": "甲",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
            },
            {
                "name": "乙",
                "position": {"x": 3.0, "y": 0.0, "z": 0.0},
                "facing": [0.0, 1.0, 0.0],
            },
        ],
        "props": [
            {
                "id": "银币",
                "kind": "货币",
                "owner": "甲",
                "position": [0.2, 0.1, 1.0],
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "motion": None,
                "provenance": "plan_intent",
            },
            {
                "id": "钥匙",
                "kind": "prop",
                "owner": "乙",
                "position": [3.2, 0.1, 1.0],
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "motion": None,
                "provenance": "plan_intent",
            },
        ],
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
                "lens": 35.0,
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001",
                "order": 1,
                "duration_frames": 24,
                "characters": ["甲"],
                "shot_type": "MS",
            },
            {
                "shot_id": "shot_002",
                "order": 2,
                "duration_frames": 24,
                "characters": ["乙"],
                "shot_type": "WS",
            },
        ],
        "shot_staging": {},
    }


def _baseline(design: dict) -> tuple[dict, dict]:
    from block_director.cinema.blockout import build_blockout_manifest

    plan = {"shots": copy.deepcopy(design["shots"])}
    return plan, {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference": design,
        "manifest": build_blockout_manifest(design=design, plan=plan),
        "report": {
            "schema_version": "blockout-report/v1",
            "verdict": "pass",
            "findings": [],
            "checks": [],
        },
    }


def _transform_at(obj, frame: int) -> dict:
    bpy.context.scene.frame_set(int(frame))
    bpy.context.view_layer.update()
    return {
        "position": [
            round(float(value), 6)
            for value in obj.matrix_world.translation
        ],
        "rotation": [
            round(float(value), 6)
            for value in obj.matrix_world.to_euler()
        ],
    }


def run_probe(out_dir: Path) -> dict:
    from block_director.layer3_engine.detail_session import DetailSceneSession

    bpy.ops.wm.read_factory_settings(use_empty=True)
    design = _design()
    plan, baseline = _baseline(design)
    session = DetailSceneSession(
        baseline=baseline,
        plan=plan,
        out_dir=out_dir,
        run_id="detail-prop-scope",
        scene_id=design["scene_id"],
    )
    session.prepare()

    target = bpy.data.objects["BD_Blockout_prop_银币"]
    neighbor = bpy.data.objects["BD_Blockout_prop_钥匙"]
    target_before = _transform_at(target, 1)
    neighbor_before = _transform_at(neighbor, 25)

    candidate = copy.deepcopy(design)
    candidate["props"][0].update({
        "position": [0.42, 0.2, 1.05],
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.35},
        "provenance": "agent_local_revision",
    })
    session.apply(candidate, "shot_001")

    target_changed = _transform_at(target, 1)
    neighbor_during = _transform_at(neighbor, 25)
    restore_result = session.restore(design, "shot_001")
    target_restored = _transform_at(target, 1)
    neighbor_after = _transform_at(neighbor, 25)

    checks = {
        "target_prop_position_changed": (
            target_changed["position"] != target_before["position"]
            and target_changed["position"][:2]
            == [round(0.42, 6), round(0.2, 6)]
        ),
        "target_prop_rotation_changed": (
            target_changed["rotation"] != target_before["rotation"]
            and abs(target_changed["rotation"][2] - 0.35) <= 1e-5
        ),
        "neighbor_prop_during_unchanged": (
            neighbor_during == neighbor_before),
        "target_prop_restored": target_restored == target_before,
        "neighbor_prop_after_restore_unchanged": (
            neighbor_after == neighbor_before),
        "restore_recollected_prop_state": (
            restore_result.get("ok") is True
            and "银币" in (
                (restore_result.get("world_state") or {})
                .get("shot_states", {})
                .get("shot_001", {})
                .get("props", {})
            )
        ),
    }
    payload = {
        "ok": all(checks.values()),
        "checks": checks,
        "target_before": target_before,
        "target_changed": target_changed,
        "target_restored": target_restored,
        "neighbor_before": neighbor_before,
        "neighbor_during": neighbor_during,
        "neighbor_after": neighbor_after,
        "restore_result": restore_result,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail_prop_scope_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> int:
    argv = list(sys.argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    out_dir = (
        ROOT / "docs" / "evidence"
        / "20261021-detail-session-prop-scope")
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
