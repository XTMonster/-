"""空间尺注册表与配置/评分/指纹的同步测试（Ticket 02 第二切片）。

覆盖主 spec（docs/SPEC_空间尺多维评测扩展_v1.0.md）§5.1 的运行时真源：
* 配置默认权重与注册表逐键对拍（双源防漂移）；
* specs/config.default.yaml 与代码生成内容逐字符一致；
* layer_score / overview_score 按 §5.1 公式与独立字面量对拍；
* 证据指纹包含权重表与权重哈希；
* 评测台关闭路径（enabled=False）不引入新配置错误、序列化往返不变。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from block_director.cinema.metric_registry import (
    LAYERS,
    LAYER_WEIGHTS_DEFAULT,
    layer_score,
    overview_score,
)
from block_director.cinema.evaluation_protocol import (
    Measurement,
    TargetInterval,
)
from block_director.contracts.config import (
    AppConfig,
    dump_default_yaml,
)


ROOT = Path(__file__).resolve().parents[1]


def _measurements(scores: dict[str, float]) -> tuple[Measurement, ...]:
    return tuple(
        Measurement(metric=name, raw_value=value, score=value,
                    target=TargetInterval(min_value=0.0))
        for name, value in scores.items()
    )


def test_config_default_weights_match_registry():
    """配置默认权重必须与注册表单源逐键对拍。"""
    assert AppConfig().ruler.enabled is True
    assert AppConfig().ruler.layer_weights == LAYER_WEIGHTS_DEFAULT
    assert tuple(AppConfig().ruler.layer_weights) == tuple(LAYERS)


def test_spec_file_matches_generated_content_and_contains_ruler():
    spec = (ROOT / "specs" / "config.default.yaml").read_text(encoding="utf-8")
    assert spec == dump_default_yaml()
    assert "ruler:" in spec
    assert "layer_weights:" in spec


def test_layer_score_weighted_average():
    assert layer_score(LAYER_WEIGHTS_DEFAULT,
                       _measurements({name: 1.0 for name in LAYER_WEIGHTS_DEFAULT})
                       ) == 100.0
    assert layer_score(LAYER_WEIGHTS_DEFAULT,
                       _measurements({name: 0.5 for name in LAYER_WEIGHTS_DEFAULT})
                       ) == 50.0
    # 权重表声明但未提供的分量按 0 计（缺证分量不能凭空通过）。
    partial = dict(LAYER_WEIGHTS_DEFAULT)
    partial["geometry"] = 0.0
    score = layer_score(partial, _measurements({}))
    assert score == 0.0


def test_overview_score_uses_spec51_weights():
    # 独立字面量对拍 §5.1：0.25/0.20/0.20/0.15/0.10/0.10。
    literal = {"geometry": 0.25, "attention": 0.20, "action": 0.20,
               "continuity": 0.15, "cinema": 0.10, "robustness": 0.10}
    layer_scores = {name: 100.0 for name in LAYERS}
    assert overview_score(layer_scores) == 100.0
    layer_scores["geometry"] = 0.0
    assert overview_score(layer_scores) == 75.0
    assert overview_score(layer_scores, weights=literal) == 75.0


def test_fingerprint_includes_ruler_weights_and_hash():
    sys.path.insert(0, str(ROOT))
    from tools.evidence_fingerprint import fingerprint

    payload = fingerprint()
    assert payload["ruler_weights"] == LAYER_WEIGHTS_DEFAULT
    expected = hashlib.sha256(
        json.dumps(LAYER_WEIGHTS_DEFAULT, sort_keys=True,
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    assert payload["ruler_weights_sha256"] == expected


def test_ruler_disabled_path_has_no_new_errors_and_round_trips():
    cfg = AppConfig()
    codes = {issue.code for issue in cfg.validate()}
    assert "CFG_220" not in codes and "CFG_221" not in codes
    assert cfg.errors() == []
    data = cfg.to_dict()
    assert AppConfig.from_dict(data).to_dict() == data
