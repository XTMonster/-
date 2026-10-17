"""空间尺几何测量组装测试（Ticket 04 纯层）。

``block_director/cinema/ruler_measure.py`` 是测量序列化的纯层接缝：它接收
声明时长 / 计划帧数 / 相机实测 / 构图报告 / 帧采样样本，产出契约层的
``Measurement`` 记录（带单位、来源四态、稳定 ID），不接触 bpy。

Blender 真实采集由 ``layer3_engine/ruler_probe.py`` ＋ Blender 探针测试负责；
本文件只钉纯层的形状与语义。
"""

from __future__ import annotations

from block_director.cinema.ruler_measure import measurements_for_shot
from block_director.contracts.spatial_ruler import validate_bundle


def _frame_sample(frame: int, subject: str, *, left=0.2, right=0.6,
                  top=0.75, bottom=0.25, facing=1.0,
                  visible=0.9, behind=False):
    """构造一个鸭子类型 FrameSample（与 frustum_metrics.FrameSample 同形状）。"""
    class Box:
        def __init__(self):
            self.left, self.right = left, right
            self.top, self.bottom = top, bottom
            self.facing = facing

        @property
        def center_x(self) -> float:
            return (self.left + self.right) / 2.0

        @property
        def center_y(self) -> float:
            return (self.top + self.bottom) / 2.0

        @property
        def height(self) -> float:
            return self.top - self.bottom

        @property
        def width(self) -> float:
            return self.right - self.left

        def inside_ratio(self) -> float:
            return 1.0

    class Sample:
        def __init__(self):
            self.frame = frame
            self.subject = subject
            self.box = Box()
            self.visible_ratio = visible
            self.behind_camera = behind
            self.shot_id = "shot_001"

    return Sample()


def test_measurements_for_shot_emit_expected_families() -> None:
    samples = [
        _frame_sample(1, "米迦尔"),
        _frame_sample(13, "米迦尔"),
        _frame_sample(24, "米迦尔"),
    ]
    items = {
        "headroom": {"score": 1.0, "weight": 0.15},
        "lead_room": {"score": 0.5, "weight": 0.20},
        "rule_of_thirds": {"score": 0.8, "weight": 0.15},
        "balance": {"score": 0.9, "weight": 0.15},
        "occlusion": {"score": 0.7, "weight": 0.25},
        "framing": {"score": 1.0, "weight": 0.10},
    }
    measurements = measurements_for_shot(
        shot_id="shot_001",
        declared_seconds=5.0,
        planned_frames=120,
        fps=24,
        camera={
            "lens": 50.0,
            "position": [0.0, -4.0, 1.6],
            "target": [0.0, 0.0, 1.5],
            "distance": 4.1,
            "shot_type": "MS",
        },
        composition_score=71.4,
        composition_items=items,
        frame_samples=samples,
        transition_angle_deg=35.0,
        transition_prev_id="shot_000",
    )
    by_metric = {m["metric"]: m for m in measurements}
    assert "shot_duration_declared" in by_metric
    assert by_metric["shot_duration_declared"]["value"] == 5.0
    assert by_metric["shot_duration_declared"]["unit"] == "seconds"
    assert by_metric["shot_duration_declared"]["source"] == "script_declaration"
    assert by_metric["shot_duration_declared"]["shot_id"] == "shot_001"

    assert by_metric["shot_duration_planned"]["value"] == 5.0
    assert by_metric["shot_duration_planned"]["source"] == "plan_intent"
    assert by_metric["camera_lens"]["value"] == 50.0
    assert by_metric["camera_lens"]["unit"] == "mm"
    assert by_metric["camera_lens"]["source"] == "blender_geometry"
    assert by_metric["camera_distance"]["value"] == 4.1
    assert by_metric["camera_distance"]["unit"] == "meters"
    assert by_metric["transition_angle_deg"]["value"] == 35.0
    assert by_metric["composition_score"]["value"] == 71.4
    assert by_metric["composition_score"]["unit"] == "0..100"
    assert by_metric["composition_score"]["source"] == "blender_geometry"

    boxes = [m for m in measurements
             if m["metric"].startswith("subject_box_")
             and m["subject_id"] == "米迦尔"]
    assert len(boxes) >= 6                # left/right/top/bottom × 至少头一帧
    assert any(m["metric"] == "subject_box_center_x" for m in measurements)
    assert any(m["metric"] == "subject_box_visible_ratio" for m in measurements)
    for box in boxes:
        assert box["unit"] == "ndc_0_1"
        assert box["source"] == box["provenance"] == "blender_geometry"


def test_measurements_validate_inside_bundle() -> None:
    samples = [_frame_sample(1, "伊恩")]
    measurements = measurements_for_shot(
        shot_id="shot_001", declared_seconds=4.0, planned_frames=96,
        fps=24, camera={"lens": 35.0, "position": [0, -3, 1.6],
                        "target": [0, 0, 1.5], "distance": 3.2,
                        "shot_type": "ELS"},
        composition_score=80.0,
        composition_items={"headroom": {"score": 1.0, "weight": 0.15}},
        frame_samples=samples,
    )
    bundle = {
        "schema_version": "spatial-ruler-observation/v2",
        "observation_id": "o_test",
        "run_context": {"source_run": "", "model": "test", "status": "offline"},
        "plugin_adapter": {
            "consumer": "BlockDirector.audit",
            "phase": ["post_build"],
            "blocking_policy": {"error": "blocks", "warning": "persists"},
            "integration_status": "partial_plan_level_only",
        },
        "observation_request": {
            "targets": [{"shot_id": "shot_001"}],
            "coordinate_system": "normalized_screen_0_1",
            "fps": 24,
        },
        "registry": {"rules": {}, "guard": {}, "composition": {}},
        "shot_specs": [], "camera_specs": [], "verdicts": [], "prescriptions": [],
        "measurements": list(measurements),
    }
    assert validate_bundle(bundle) == []
