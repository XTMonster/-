"""v1.5 §7 配置新增（卡 P2-T5）：``rag.rule_top_k`` 与 ``vlm_review`` 两键。

判据（执行文档 v1.5 TDD §7 表格，逐字照抄）：

* ``rag.rule_top_k``      缺省 ``5``；int，**3–8**，越界报 CFG_0xx；
* ``vlm_review.enabled``  缺省 ``false``；bool；
* ``vlm_review.max_shots`` 缺省 ``0``（不限）；int **≥ 0**。

``orchestration.draft_candidates`` **不在本卡**（P6-T2 落地）。
红线 R-4：``specs/config.default.yaml`` 是生成物，改代码后必跑
``python tools/gen_specs.py``，本文件只读它、不写它。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.config import (  # noqa: E402
    AppConfig,
    VlmReviewConfig,
    dump_default_yaml,
)

SPEC = ROOT / "specs" / "config.default.yaml"


# ------------------------------------------------------------------ rule_top_k
def test_rule_top_k_default_is_five_and_legal():
    cfg = AppConfig()
    assert cfg.rag.rule_top_k == 5
    assert cfg.errors() == []


@pytest.mark.parametrize("value", [3, 4, 5, 6, 7, 8])
def test_rule_top_k_in_range_has_no_error(value):
    cfg = AppConfig()
    cfg.rag.rule_top_k = value
    assert cfg.errors() == [], [str(i) for i in cfg.errors()]


@pytest.mark.parametrize("value", [2, 9, 0, -1, 3.5, 5.0, "5", True, None])
def test_rule_top_k_out_of_range_or_non_int_is_cfg_020(value):
    cfg = AppConfig()
    cfg.rag.rule_top_k = value
    codes = {i.code for i in cfg.errors()}
    assert "CFG_020" in codes, (value, codes)


def test_rule_top_k_error_message_names_the_field():
    cfg = AppConfig()
    cfg.rag.rule_top_k = 9
    issue = next(i for i in cfg.errors() if i.code == "CFG_020")
    assert issue.field == "rag.rule_top_k"


# ----------------------------------------------------------------- vlm_review
def test_vlm_review_defaults_are_off_and_unlimited():
    cfg = AppConfig()
    assert isinstance(cfg.vlm_review, VlmReviewConfig)
    assert cfg.vlm_review.enabled is False
    assert cfg.vlm_review.max_shots == 0
    assert cfg.errors() == []


def test_vlm_review_accepts_enabled_and_a_positive_cap():
    cfg = AppConfig()
    cfg.vlm_review.enabled = True
    cfg.vlm_review.max_shots = 4
    assert cfg.errors() == []
    cfg.vlm_review.max_shots = 0          # 0 = 不限，必须合法
    assert cfg.errors() == []


@pytest.mark.parametrize("value", [-1, -100, 1.5, "3", True, None])
def test_vlm_review_cap_out_of_range_or_non_int_is_cfg_021(value):
    cfg = AppConfig()
    cfg.vlm_review.max_shots = value
    codes = {i.code for i in cfg.errors()}
    assert "CFG_021" in codes, (value, codes)


# ------------------------------------------------------- serde / 向后兼容
def test_new_keys_round_trip_through_serde():
    cfg = AppConfig()
    cfg.rag.rule_top_k = 7
    cfg.vlm_review.enabled = True
    cfg.vlm_review.max_shots = 12
    data = cfg.to_dict()
    assert data["rag"]["rule_top_k"] == 7
    assert data["vlm_review"] == {"enabled": True, "max_shots": 12}
    assert AppConfig.from_dict(data).to_dict() == data


def test_a_config_without_the_new_keys_falls_back_to_defaults():
    """旧配置文件里没有这两个键 ⇒ 必须回落到缺省，而不是崩（兼容纪律）。"""
    data = AppConfig().to_dict()
    data["rag"].pop("rule_top_k")
    data.pop("vlm_review")
    restored = AppConfig.from_dict(data)
    assert restored.rag.rule_top_k == 5
    assert restored.vlm_review.enabled is False
    assert restored.vlm_review.max_shots == 0


# ------------------------------------------------------------- specs 同步（R-4）
def test_generated_spec_carries_the_new_keys():
    import yaml

    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert spec["rag"]["rule_top_k"] == AppConfig().rag.rule_top_k
    assert spec["vlm_review"] == {"enabled": False, "max_shots": 0}


def test_gen_specs_is_idempotent_and_in_sync():
    """连跑两次生成必须一致，且磁盘上的规格与代码默认值逐字符相同。"""
    assert dump_default_yaml() == dump_default_yaml()
    assert SPEC.read_text(encoding="utf-8") == dump_default_yaml()
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gen_specs.py"), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr
