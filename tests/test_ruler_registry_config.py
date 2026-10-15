"""空间尺指标注册表与配置默认值（Ticket 02）测试。

覆盖主 spec（docs/SPEC_空间尺多维评测扩展_v1.0.md）§4 / §5.1 与
《空间尺指标规范 v1.0》：
* 32 项新增指标 + 6 项 composition 真源指针（Ticket 03a，注册表共 38 项）；
  新增指标逐条含 8 字段 + H1–H6 联动 + 三态样例要求，指针指标指向
  composition.py 真源（inputs/measurement 含 composition），不参与权重；
* 注册表是单一真源：每项定义只出现一次、纯层不 import bpy；
* 六层默认权重写入配置且与注册表逐键对拍（双源防漂移）；
* layer_score / overview_score 按 §5.1 公式（独立字面量对拍）；
* 证据指纹包含权重表与权重指纹。
术语严格使用「内容关键帧 / 动作关键帧」。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from block_director.cinema import metric_registry
from block_director.cinema.metric_registry import (
    LAYERS,
    LAYER_METRICS,
    LAYER_WEIGHTS_DEFAULT,
    METRIC_REGISTRY,
    METRICS_BY_NAME,
    layer_score,
    overview_score,
)


MODULE_PATH = Path(inspect.getfile(metric_registry)).resolve()

#: 《空间尺指标规范 v1.0》「通用字段与规则」的 8 字段清单（独立字面量）。
EIGHT_FIELDS = ("granularity", "inputs", "measurement", "target",
                "severity", "failure_cause", "repair_direction",
                "evidence_grade")

#: 六层指标数（§4.1–§4.6 + §4.7 指针，独立字面量）。
LAYER_COUNTS = {"geometry": 11, "attention": 5, "action": 6,
                "continuity": 6, "cinema": 5, "robustness": 5}

#: 硬门联动（§5.2 H1–H6 在指标规范里的显式标注，独立字面量）。
GATE_LINKS = {
    "edge_clearance": ("H1",),
    "gaze_target_visibility": ("H4",),
    "action_readability": ("H2",),
    "cause_effect_visibility": ("H2",),
    "contact_point_visibility": ("H2",),
    "axis_continuity": ("H3",),
    "camera_path_clearance": ("H5",),
    "repair_locality": ("H6",),
}


# --------------------------------------------------------------------------- #
# 切片 A：注册表
# --------------------------------------------------------------------------- #
def test_registry_covers_38_metrics_in_six_layers():
    assert tuple(LAYERS) == ("geometry", "attention", "action",
                             "continuity", "cinema", "robustness")
    assert len(METRIC_REGISTRY) == 38
    assert ({layer: len(names) for layer, names in LAYER_METRICS.items()}
            == LAYER_COUNTS)
    catalogued = {spec.name for spec in METRIC_REGISTRY}
    assert catalogued == set().union(*(set(names)
                                       for names in LAYER_METRICS.values()))


def test_every_metric_has_all_eight_fields_and_annotations():
    for spec in METRIC_REGISTRY:
        for field_name in EIGHT_FIELDS:
            value = getattr(spec, field_name)
            assert value, f"{spec.name}.{field_name} 为空"
        assert isinstance(spec.links_to_gates, tuple)
        assert all(link in ("H1", "H2", "H3", "H4", "H5", "H6")
                   for link in spec.links_to_gates)
        assert set(spec.sample_requirements) == {"good", "bad", "ambiguous"}
        for state, requirement in spec.sample_requirements.items():
            assert isinstance(requirement, str) and requirement.strip(), \
                f"{spec.name}.sample_requirements[{state}] 为空"


def test_gate_links_match_metric_spec():
    for name, gates in GATE_LINKS.items():
        assert METRICS_BY_NAME[name].links_to_gates == gates
    for name, spec in METRICS_BY_NAME.items():
        if name not in GATE_LINKS:
            assert spec.links_to_gates == ()


def test_each_metric_definition_appears_exactly_once():
    names = [spec.name for spec in METRIC_REGISTRY]
    assert len(names) == len(set(names)) == 38
    assert set(METRICS_BY_NAME) == set(names)
    for layer, names_in_layer in LAYER_METRICS.items():
        by_layer = {spec.name for spec in METRIC_REGISTRY
                    if spec.layer == layer}
        assert by_layer == set(names_in_layer)


def test_registry_is_pure_python_without_bpy():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "bpy" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") != "bpy"
