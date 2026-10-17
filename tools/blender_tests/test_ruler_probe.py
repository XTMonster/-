"""空间尺测量采集探针（Ticket 04）：headless 序列化几何实测。

在合成两镜场景上跑 ``layer3_engine/ruler_probe.collect_shot_measurements``，
断言输出满足契约层 measurement 形状：

* 每镜至少产出 camera_lens / camera_position / camera_distance /
  composition_score 与逐主体 subject_box_*（NDC 0..1）；
* 所有测量 source == provenance，来源为 blender_geometry；
* 相邻镜 transition_angle_deg 以 ``from->to`` transition_id 产出；
* 输出经 ``validate_bundle`` 校验通过（半页 bundle）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_ruler_probe.py
输出：一行 ``BD_TEST_RESULT {json}``；退出码 0 = 全通过。
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402
from block_director.contracts.spatial_ruler import validate_bundle  # noqa: E402
from block_director.layer3_engine.shot_auditor import BpyShotAuditor  # noqa: E402
from block_director.layer3_engine.character_system.character_factory import (  # noqa: E402
    Character,
    create_character,
)
from block_director.layer3_engine.ruler_probe import collect_shot_measurements  # noqa: E402
from block_director.layer3_engine.scene_context import (  # noqa: E402
    SceneContext,
    set_context,
)
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=5)}


def _camera(name, location, look_at=(0.0, 0.0, 0.5), lens=50.0):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(location)
    direction = Vector(look_at) - Vector(location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj


def _build():
    """合成两镜场景：MLS 双人 → MCU 单人（与 _fixtures.two_shot_plan 同构）。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100

    char_a = create_character("char_001", "米迦尔", "#FF6B6B",
                              location=(0.0, 0.0, 0.0))
    char_b = create_character("char_002", "伊恩", "#6B9BFF",
                              location=(1.2, 0.0, 0.0))
    first = ShotPlan.from_dict({
        "shot_id": "shot_001", "order": 1, "intent": "建立场景与人物关系",
        "shot_type": "MLS", "duration_frames": 96,
        "characters": ["char_001", "char_002"],
    })
    second = ShotPlan.from_dict({
        "shot_id": "shot_002", "order": 2, "intent": "推进对话，给出反应",
        "shot_type": "MCU", "duration_frames": 120,
        "characters": ["char_002"],
    })
    cameras = {
        "shot_001": _camera("cam_shot_001", (0.0, -6.0, 1.4), (0.0, 0.0, 1.0)),
        "shot_002": _camera("cam_shot_002", (1.2, -3.0, 1.2), (1.2, 0.0, 1.0),
                            lens=50.0),
    }
    context = SceneContext(
        characters={"char_001": char_a, "char_002": char_b},
        cameras=cameras,
        shot_types={"shot_001": "MLS", "shot_002": "MCU"},
        schedule={"shot_001": (1, 96), "shot_002": (97, 216)},
        plan=Plan(shots=[first, second], scene_heading="INT. 咖啡馆 - 日"),
    )
    set_context(context)
    return context


def t_each_shot_has_expected_families():
    _ctx = _build()
    out = {}
    for shot_id in ("shot_001", "shot_002"):
        measurements = collect_shot_measurements(shot_id)
        by_metric = {m["metric"]: m for m in measurements}
        ok = (
            "camera_lens" in by_metric
            and "camera_position" in by_metric
            and "camera_distance" in by_metric
            and "composition_score" in by_metric
            and any(k.startswith("subject_box_") for k in by_metric)
            and any(m["source"] == m["provenance"] == "blender_geometry"
                    for m in measurements)
        )
        #: 所有 blender 几何测量 source == provenance
        blend = [m for m in measurements
                 if m["source"] == "blender_geometry"]
        consistent = all(m["source"] == m["provenance"] for m in blend)
        out[shot_id] = {
            "ok": bool(ok and consistent),
            "count": len(measurements),
            "metrics": sorted(by_metric),
        }
    return {"ok": bool(out.get("shot_001", {}).get("ok")
                       and out.get("shot_002", {}).get("ok")),
            "shots": out}


def t_transition_angle_between_shots():
    _ctx = _build()
    transition = [
        m for m in collect_shot_measurements("shot_002")
        if m["metric"] == "transition_angle_deg"
    ]
    if not transition:
        return {"ok": False, "reason": "shot_002 缺 transition_angle_deg 测量"}
    m = transition[0]
    angle = float(m["value"])
    ok = (0.0 <= angle <= 180.0
          and m["transition_id"] == "shot_001->shot_002"
          and m["unit"] == "degrees")
    return {"ok": bool(ok), "angle": angle, "transition_id": m["transition_id"]}


def t_measurements_pass_bundle_validation():
    _ctx = _build()
    measurements = (collect_shot_measurements("shot_001")
                    + collect_shot_measurements("shot_002"))
    bundle = {
        "schema_version": "spatial-ruler-observation/v2",
        "observation_id": "o_blender_probe",
        "run_context": {"source_run": "", "model": "blender-probe",
                        "status": "offline"},
        "plugin_adapter": {
            "consumer": "BlockDirector.audit",
            "phase": ["post_build"],
            "blocking_policy": {"error": "blocks", "warning": "persists"},
            "integration_status": "partial_plan_level_only",
        },
        "observation_request": {
            "targets": [{"shot_id": "shot_001"}, {"shot_id": "shot_002"}],
            "coordinate_system": "normalized_screen_0_1",
            "fps": 24,
        },
        "registry": {"rules": {}, "guard": {}, "composition": {}},
        "shot_specs": [], "camera_specs": [], "verdicts": [], "prescriptions": [],
        "measurements": list(measurements),
    }
    findings = validate_bundle(bundle)
    return {"ok": findings == [], "findings": findings,
            "count": len(measurements)}


def t_auditor_attaches_measurements():
    _ctx = _build()
    auditor = BpyShotAuditor()
    result = auditor.audit("shot_001")
    payload = result.to_dict()
    attached = bool(result.ruler_measurements)
    key_shown = "ruler_measurements" in payload and bool(
        payload["ruler_measurements"])
    if not attached:
        return {"ok": False, "reason": "audit() 未挂 ruler_measurements",
                "errors": [e.to_dict() for e in result.errors[:3]]}
    return {"ok": bool(attached and key_shown),
            "count": len(result.ruler_measurements),
            "score": result.score}


def main():
    capture_main_thread()
    check("each_shot_has_expected_families", t_each_shot_has_expected_families)
    check("transition_angle_between_shots", t_transition_angle_between_shots)
    check("measurements_pass_bundle_validation",
          t_measurements_pass_bundle_validation)
    check("auditor_attaches_measurements", t_auditor_attaches_measurements)
    passed = [key for key, value in RESULTS.items() if value.get("ok")]
    failed = [key for key, value in RESULTS.items() if not value.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False, allow_nan=False), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
