"""空间尺生产整合层（转正）：六层评测汇总成 RulerReview。

把插件已采集的画面事实（``frustum_sampler.FrameSample`` + 排片器帧范围）
经 ``ruler_bridge`` 折成评测台采样对象，逐镜跑五层（geometry / attention /
action / cinema / robustness），序列级跑 continuity，汇总为：

* ``layer_scores`` —— 六层 0..100（``metric_registry.layer_score`` 加权，
  权重表以注册表 ``LAYER_METRICS`` 为真源，层内均匀；缺测分量按 0 计，
  "缺证不能凭空通过"）；
* ``overview`` —— 六层加权总览分（``overview_score``，权重取注册表默认）；
* ``hard_gates`` —— 各层 findings 里联动 H1–H6 的硬门收拢；
* ``findings`` / ``measurements`` —— 全部层的失败项与读数；
* ``prescriptions`` —— 各层 ``build_prescriptions`` 收拢（只含 fatal/error）。

纯层模块：不 import bpy / mathutils。仓库内 sequence 级 continuity 需要整条
镜头链的画面事实，因此任一镜头缺采样都会 ``ValueError``（不编造读数）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ..contracts.plan import Plan
from . import (
    metrics_action_causality,
    metrics_action_prop,
    metrics_attention,
    metrics_cinema,
    metrics_continuity,
    metrics_geometry,
    metrics_robustness,
)
from .evaluation_protocol import (
    EvaluationOutput,
    Finding,
    Measurement,
    Prescription,
    Severity,
    ShotSample,
)
from .metric_registry import (
    LAYERS,
    LAYER_METRICS,
    LAYER_WEIGHTS_DEFAULT,
    layer_score,
    overview_score,
)
from .ruler_bridge import (
    build_intent,
    build_sequence_sample,
    build_shot_sample,
)
from .schedule import shot_ranges


# --------------------------------------------------------------------------- #
# 层评分权重表（真源 = 注册表 LAYER_METRICS，层内均匀）
# --------------------------------------------------------------------------- #
#: 每层分量 -> 权重。以 ``metric_registry.LAYER_METRICS`` 为单一真源，
#: 层内均匀；``layer_score`` 对声明但未提供的分量按 0 计（缺证不能凭空通过）。
#: 几何层的 composition 真源指针（headroom/lead_room/…/framing）在此占权重，
#: 由旧审核器合成读数时并入（转正合并其功能），未并入前按 0 计。
_LAYER_WEIGHTS: Dict[str, Dict[str, float]] = {
    layer: {metric: 1.0 / len(LAYER_METRICS[layer])
            for metric in LAYER_METRICS[layer]}
    for layer in LAYERS
}


# --------------------------------------------------------------------------- #
# 输出契约
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RulerReview:
    """空间尺六层审核汇总（转正主层，挂 AuditResult.ruler_review）。"""

    shot_id: str
    layer_scores: Dict[str, float]
    overview: float
    hard_gates: "set[str]" = field(default_factory=set)
    findings: Tuple[Finding, ...] = ()
    measurements: Tuple[Measurement, ...] = ()
    prescriptions: Tuple[Prescription, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "shot_id": self.shot_id,
            "layer_scores": {k: round(float(v), 6)
                             for k, v in self.layer_scores.items()},
            "overview": round(float(self.overview), 6),
            "hard_gates": sorted(self.hard_gates),
            "findings": [f.to_dict() for f in self.findings],
            "measurements": [m.to_dict() for m in self.measurements],
            "prescriptions": [p.to_dict() for p in self.prescriptions],
        }


# --------------------------------------------------------------------------- #
# 逐镜五层（不含 continuity）
# --------------------------------------------------------------------------- #
def _shot_layer_module_outputs(shot_sample: ShotSample,
                               intent: object
                               ) -> Dict[str, Tuple[EvaluationOutput, ...]]:
    """对单镜跑五层；动作层 = 接触因果（06）＋ 姿态/道具（07）两模块并集。"""
    return {
        "geometry": (metrics_geometry.evaluate(shot_sample, intent),),
        "attention": (metrics_attention.evaluate(shot_sample, intent),),
        "action": (
            metrics_action_causality.evaluate(shot_sample, intent),
            metrics_action_prop.evaluate(shot_sample, intent),
        ),
        "cinema": (metrics_cinema.evaluate(shot_sample, intent),),
        "robustness": (metrics_robustness.evaluate(shot_sample, intent),),
    }


def _merge_outputs(
        layer_outputs: Mapping[str, Sequence[EvaluationOutput]],
        continuity: EvaluationOutput,
        ) -> Tuple[Dict[str, float], float, "set[str]",
                   Tuple[Measurement, ...], Tuple[Finding, ...]]:
    """汇总六层分 / 总览分 / 硬门 / 读数 / 失败项。"""
    layer_scores: Dict[str, float] = {}
    measurements: list[Measurement] = []
    findings: list[Finding] = []
    hard_gates: "set[str]" = set()
    for layer in LAYERS:
        outputs = [continuity] if layer == "continuity" \
            else layer_outputs[layer]
        layer_measurements = tuple(
            m for output in outputs for m in output.measurements)
        layer_scores[layer] = layer_score(
            _LAYER_WEIGHTS[layer], layer_measurements)
        for output in outputs:
            measurements.extend(output.measurements)
            for finding in output.findings:
                findings.append(finding)
                if finding.gate:
                    hard_gates.add(finding.gate)
    overview = overview_score(layer_scores)
    return (layer_scores, overview, hard_gates,
            tuple(measurements), tuple(findings))


# --------------------------------------------------------------------------- #
# 公共接缝
# --------------------------------------------------------------------------- #
def run_ruler_review(plan: Plan,
                     samples_by_shot: Mapping[str, Sequence[object]], *,
                     fps: int = 24,
                     shot_id: Optional[str] = None,
                     lens_by_shot: Optional[Mapping[str, float]] = None,
                     ) -> RulerReview:
    """对计划（或其单镜）跑空间尺六层审核，返回 ``RulerReview``。

    * 逐镜五层（geometry/attention/action/cinema/robustness）只评估
      ``shot_id``（缺省 = 计划第一镜）；
    * continuity 是序列级指标，必须拿整条镜头链采样：任一镜头缺采样
      直接 ``ValueError``（不编造连续性读数）；
    * 处方从各层 ``build_prescriptions`` 收拢（只含 fatal/error）。
    """
    if not plan.shots:
        raise ValueError("run_ruler_review 需要至少一个镜头")
    target_id = shot_id or str(plan.shots[0].shot_id)
    target_shot = next(
        (s for s in plan.shots if str(s.shot_id) == target_id), None)
    if target_shot is None:
        raise ValueError(f"{target_id} 不在计划中，无法审核")

    # 序列级 continuity 需要整条链：缺任一镜采样即报错。
    sequence = build_sequence_sample(
        plan, samples_by_shot, fps=fps, lens_by_shot=lens_by_shot)

    probes = samples_by_shot.get(target_id)
    if not probes:
        raise ValueError(f"{target_id} 没有帧采样，无法完成审核")
    frame_range = shot_ranges(plan).get(target_id)
    if frame_range is None:
        raise ValueError(f"{target_id} 没有排片帧范围")
    lens = None
    if lens_by_shot is not None:
        lens = lens_by_shot.get(target_id)
    shot_sample = build_shot_sample(
        target_shot, list(probes), frame_range=frame_range,
        fps=fps, lens=lens)
    intent = build_intent(target_shot)

    shot_outputs = _shot_layer_module_outputs(shot_sample, intent)
    continuity = metrics_continuity.evaluate(sequence, intent)
    layer_scores, overview, hard_gates, measurements, findings = \
        _merge_outputs(shot_outputs, continuity)

    prescriptions: list[Prescription] = []
    for layer, outputs in shot_outputs.items():
        for output in outputs:
            prescriptions.extend(_prescriptions_for(layer, output))
    prescriptions.extend(
        metrics_continuity.build_prescriptions(continuity))

    return RulerReview(
        shot_id=target_id,
        layer_scores=layer_scores,
        overview=overview,
        hard_gates=hard_gates,
        findings=findings,
        measurements=measurements,
        prescriptions=tuple(prescriptions),
    )


def run_shot_review(plan: Plan,
                    shot_id: str,
                    probes: Sequence[object], *,
                    fps: int = 24,
                    lens: Optional[float] = None,
                    ) -> RulerReview:
    """逐镜五层审核（CHECKING 阶段用）：geometry / attention / action /
    cinema / robustness，不依赖全场采样。

    continuity 是序列级指标，逐镜审核没有全场镜头链，**如实标缺**：
    layer_scores["continuity"] = 0、一条 NOTE finding（不编造连续性读数），
    因此本入口的 ``hard_gates`` 只会收 H1/H2/H4/H5（H3/H6 须序列级
    ``run_ruler_review`` 复核）。
    """
    if not plan.shots:
        raise ValueError("run_shot_review 需要至少一个镜头")
    target_shot = next(
        (s for s in plan.shots if str(s.shot_id) == str(shot_id)), None)
    if target_shot is None:
        raise ValueError(f"{shot_id} 不在计划中，无法审核")
    probes = list(probes or [])
    if not probes:
        raise ValueError(f"{shot_id} 没有帧采样，无法完成审核")
    frame_range = shot_ranges(plan).get(str(shot_id))
    if frame_range is None:
        raise ValueError(f"{shot_id} 没有排片帧范围")
    shot_sample = build_shot_sample(
        target_shot, probes, frame_range=frame_range, fps=fps, lens=lens)
    intent = build_intent(target_shot)
    shot_outputs = _shot_layer_module_outputs(shot_sample, intent)

    layer_scores: Dict[str, float] = {}
    measurements: list[Measurement] = []
    findings: list[Finding] = []
    hard_gates: "set[str]" = set()
    for layer in LAYERS:
        if layer == "continuity":
            layer_scores[layer] = layer_score(
                _LAYER_WEIGHTS[layer], ())
            findings.append(Finding(
                component="continuity",
                severity=Severity.NOTE,
                message="连续性层未核验：逐镜审核无全场镜头链，留待序列级复核",
                evidence_frames=(),
            ))
            continue
        outputs = shot_outputs[layer]
        layer_measurements = tuple(
            m for output in outputs for m in output.measurements)
        layer_scores[layer] = layer_score(
            _LAYER_WEIGHTS[layer], layer_measurements)
        for output in outputs:
            measurements.extend(output.measurements)
            for finding in output.findings:
                findings.append(finding)
                if finding.gate:
                    hard_gates.add(finding.gate)
    overview = overview_score(layer_scores)

    prescriptions: list[Prescription] = []
    for layer, outputs in shot_outputs.items():
        for output in outputs:
            prescriptions.extend(_prescriptions_for(layer, output))
    return RulerReview(
        shot_id=str(shot_id),
        layer_scores=layer_scores,
        overview=overview,
        hard_gates=hard_gates,
        findings=tuple(findings),
        measurements=tuple(measurements),
        prescriptions=tuple(prescriptions),
    )


def _prescriptions_for(layer: str,
                       output: EvaluationOutput) -> Tuple[Prescription, ...]:
    """按层对应模块产处方（显式映射，不靠指标名反推）。"""
    if layer == "action":
        # 调用方已按模块分开放置 output；这里按来源模块再收一次。
        # 两个动作模块的 build_prescriptions 都只认自己名下的分量，
        # 互不越权，因此可安全地对同一输出同时调用。
        return (metrics_action_causality.build_prescriptions(output)
                + metrics_action_prop.build_prescriptions(output))
    builders = {
        "geometry": metrics_geometry.build_prescriptions,
        "attention": metrics_attention.build_prescriptions,
        "cinema": metrics_cinema.build_prescriptions,
        "robustness": metrics_robustness.build_prescriptions,
    }
    return builders[layer](output)


__all__ = ["RulerReview", "run_ruler_review", "run_shot_review",
           "_LAYER_WEIGHTS"]
