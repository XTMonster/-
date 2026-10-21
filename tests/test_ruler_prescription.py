"""空间尺处方生成器（Ticket 03a）测试。

契约（主 spec §7 与 evaluation_protocol.Prescription 逐键一致）：
* 处方只描述 component/severity/current/target/allowed_tools/direction/
  expected_effect——**不含**可执行 tool/tool_args；
* validate_prescription 拒绝未注册内部键（camera_z/delta_*/walk_*）与
  未注册工具，把“模型动手”与“尺子给方向”彻底分开；
* guard_verdict 是确定性地面真值：current 已落在 target 内 -> reject，
  否则 accept；它不进尺子提示，由评测台单独对拍；
* detect_pollution 识别“尺子读数被掺进正确工具名/参数/建议执行”的泄漏。

纯层测试，不 import bpy；不改旧 demo 阈值。
"""

from __future__ import annotations

from typing import Any, Dict

from block_director.cinema.composition import (
    CompositionItem,
    CompositionReport,
    SubjectBox,
    evaluate_composition,
)
from block_director.cinema.evaluation_protocol import (
    Prescription,
    Severity,
    TargetInterval,
)
from block_director.cinema.metric_registry import (
    LAYER_METRICS,
    METRIC_REGISTRY,
)
from block_director.cinema.prescription import (
    build_prescriptions,
    detect_pollution,
    guard_verdict,
    validate_prescription,
)


def _box(**overrides) -> SubjectBox:
    #: 用户 2026-10-18 裁决：构图分严格高于 80 才算通过。默认夹具必须是
    #: 六分项全部 > 0.8 的真·好构图——主体放左三分线附近（cx≈0.30）、
    #: 面朝右留出充足视线空间，头顶留白落在理想区间。
    values = dict(name="小明", left=0.21, right=0.39, top=1.0 - 0.07,
                  bottom=0.35, facing=1.0)
    values.update(overrides)
    return SubjectBox(**values)


def _prescription(**overrides) -> Prescription:
    values: Dict[str, Any] = dict(
        component="headroom",
        severity=Severity.ERROR,
        current=0.25,
        target=TargetInterval(min_value=0.60, max_value=1.00),
        allowed_tools=("move_camera", "reframe"),
        direction="抬高主体：机位推进或收紧景别",
        expected_effect=("headroom 分数回升到目标区间",),
    )
    values.update(overrides)
    return Prescription(**values)


# --------------------------------------------------------------------------- #
# build_prescriptions：新契约
# --------------------------------------------------------------------------- #
def test_build_prescriptions_returns_protocol_prescription():
    """失败分量产出 evaluation_protocol.Prescription，含全部方向字段。"""
    report = evaluate_composition([_box(top=0.60)])  # 头顶留白过多
    prescriptions = build_prescriptions(report)
    assert any(p.component == "headroom" for p in prescriptions)
    p = next(p for p in prescriptions if p.component == "headroom")
    assert isinstance(p, Prescription)
    # top=0.60 -> 头顶留白过多 -> headroom 分数 0.20，严重度应归 fatal。
    assert p.severity == Severity.FATAL
    assert p.severity in (Severity.FATAL, Severity.ERROR, Severity.WARNING)
    assert p.target.min_value is not None
    assert p.allowed_tools, "处方必须声明 allowed_tools"
    assert p.direction.strip(), "处方必须给出修复方向"
    assert p.expected_effect, "处方必须声明预期影响"
    # 防污染红线：处方不能携带可执行 tool/tool_args 键。
    assert not hasattr(p, "tool")
    assert not hasattr(p, "tool_args")
    body = p.to_dict()
    assert set(body) == {
        "component", "severity", "current", "target",
        "allowed_tools", "direction", "expected_effect",
    }


def test_passing_components_produce_no_prescription():
    """通过的分量不生成处方（零形状差，golden 不漂移）。"""
    report = evaluate_composition([_box()])
    assert report.passed
    assert build_prescriptions(report) == []


# --------------------------------------------------------------------------- #
# validate_prescription：真源白名单
# --------------------------------------------------------------------------- #
def test_validate_prescription_accepts_component_with_registered_tools():
    ok, message = validate_prescription(_prescription())
    assert ok, message


def test_validate_prescription_rejects_internal_measurement_keys():
    """camera_z/delta_*/walk_* 是未注册内部键，处方不得直接引用。"""
    for component in ("camera_z", "delta_x", "delta_y", "walk_speed"):
        ok, _ = validate_prescription(_prescription(component=component))
        assert not ok, component


def test_validate_prescription_rejects_unregistered_tools():
    """allowed_tools 只能来自 contracts.tools.ACTION_TOOLS 真源闭集。"""
    ok, _ = validate_prescription(
        _prescription(allowed_tools=("create_prop",)))
    assert not ok


# --------------------------------------------------------------------------- #
# guard_verdict：确定性地面真值
# --------------------------------------------------------------------------- #
def test_guard_verdict_rejects_when_current_already_in_target():
    assert guard_verdict(_prescription(current=0.80)) == "reject"


def test_component_boundary_target_is_open_and_requires_repair():
    report = CompositionReport(
        score=79.0,
        items={
            "headroom": CompositionItem(
                "headroom",
                0.80,
                0.15,
            ),
        },
    )

    prescription = build_prescriptions(report)[0]

    assert prescription.target.min_value == 0.80
    assert not prescription.target.contains(0.80)
    assert prescription.target.contains(0.8001)
    assert prescription.target.to_dict() == {
        "min": 0.80,
        "min_inclusive": False,
    }
    assert guard_verdict(prescription) == "accept"


def test_guard_verdict_accepts_when_current_outside_target():
    assert guard_verdict(_prescription(current=0.25)) == "accept"


def test_guard_verdict_is_deterministic_and_repeatable():
    p = _prescription(current=0.41)
    assert [guard_verdict(p) for _ in range(5)] == ["accept"] * 5


# --------------------------------------------------------------------------- #
# detect_pollution：尺子提示不得泄漏正确答案
# --------------------------------------------------------------------------- #
def test_detect_pollution_flags_tool_name_argument_and_suggestion():
    assert detect_pollution("读数：headroom 0.25，建议执行 move_camera") is not None
    assert detect_pollution("建议执行 reframe(lens=35)") is not None
    assert detect_pollution("dolly_in amount=0.5") is not None


def test_detect_pollution_allows_plain_measurements_and_direction_words():
    # 只有读数与方向措辞（不含具体工具/参数/“建议执行”）不算污染。
    assert detect_pollution(
        "headroom 原始 0.25，目标 [0.60, 1.00]，修复方向：抬高主体"
    ) is None
    assert detect_pollution("镜头 1 读数，无失败项") is None


# --------------------------------------------------------------------------- #
# 六项指针指标（Ticket 03a 扩容 32 -> 38）
# --------------------------------------------------------------------------- #
def test_registry_adds_six_composition_pointer_metrics():
    """六指针挂在 geometry 层、layer 是 geometry、指向 composition 真源。"""
    names = {spec.name for spec in METRIC_REGISTRY}
    for metric in ("headroom", "lead_room", "rule_of_thirds",
                   "balance", "occlusion", "framing"):
        assert metric in names, metric
        spec = next(s for s in METRIC_REGISTRY if s.name == metric)
        assert spec.layer == "geometry"
        assert spec.granularity == "Frame"
        assert "composition" in spec.inputs
        assert "composition" in spec.measurement
    assert "headroom" in LAYER_METRICS["geometry"]
