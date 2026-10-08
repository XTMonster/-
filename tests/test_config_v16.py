"""v1.6 A4：LLM 超时配置与面板设置（D-01）。"""

from __future__ import annotations

import pytest

from block_director.contracts.config import AppConfig
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.layer7_ui.run_settings import apply_scene_settings


def test_default_llm_timeout_is_300s():
    cfg = AppConfig()
    assert cfg.llm.timeout_s == 300.0


def test_non_positive_timeout_is_an_error():
    cfg = AppConfig()
    cfg.llm.timeout_s = 0.0
    assert any(item.code == "CFG_023" for item in cfg.errors())
    cfg.llm.timeout_s = -10.0
    assert any(item.code == "CFG_023" for item in cfg.errors())


def test_default_config_has_no_errors():
    assert AppConfig().errors() == []


def test_run_settings_applies_timeout():
    cfg = AppConfig()
    _, problems = apply_scene_settings(cfg, {"llm_timeout_s": 600.0})
    assert problems == []
    assert cfg.llm.timeout_s == 600.0


def test_run_settings_rejects_non_positive_timeout():
    cfg = AppConfig()
    _, problems = apply_scene_settings(cfg, {"llm_timeout_s": 0.0})
    assert any("必须为正数" in p for p in problems)


def test_run_settings_rejects_non_numeric_timeout():
    cfg = AppConfig()
    _, problems = apply_scene_settings(cfg, {"llm_timeout_s": "fast"})
    assert any("必须是数字" in p for p in problems)


def test_driver_reads_timeout_from_config():
    class _DummyTransport:
        def chat(self, payload, timeout):
            return {"content": "ok"}

    cfg = AppConfig()
    cfg.llm.timeout_s = 750.0
    driver = PrevisDriver(
        transport=_DummyTransport(), audit=AuditLogger(), config=cfg)
    assert driver.limits.llm_timeout_s == 750.0


def test_driver_explicit_limits_override_config_timeout():
    class _DummyTransport:
        def chat(self, payload, timeout):
            return {"content": "ok"}

    cfg = AppConfig()
    cfg.llm.timeout_s = 750.0
    limits = DriverLimits(llm_timeout_s=120.0)
    driver = PrevisDriver(
        transport=_DummyTransport(), audit=AuditLogger(), config=cfg,
        limits=limits)
    assert driver.limits.llm_timeout_s == 120.0


@pytest.mark.parametrize("module_name", ["tools.run_headless", "tools.run_export"])
def test_cli_omitted_timeout_reads_config_and_explicit_timeout_overrides(module_name):
    import importlib

    cli = importlib.import_module(module_name)
    cfg = AppConfig()
    cfg.llm.timeout_s = 750.0
    default_args = cli.parse_args(["blender", "--"])
    assert default_args.llm_timeout is None
    limits = DriverLimits.from_config(
        cfg, llm_timeout_s=default_args.llm_timeout,
        max_llm_calls=default_args.max_llm_calls)
    assert limits.llm_timeout_s == 750.0
    explicit_args = cli.parse_args(["blender", "--", "--llm-timeout", "120"])
    explicit = DriverLimits.from_config(
        cfg, llm_timeout_s=explicit_args.llm_timeout,
        max_llm_calls=explicit_args.max_llm_calls)
    assert explicit.llm_timeout_s == 120.0
    assert cfg.llm.timeout_s == 750.0


def test_both_cli_entrypoints_use_the_configuration_aware_limits_constructor():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("run_headless.py", "run_export.py"):
        tree = ast.parse((root / "tools" / name).read_text(encoding="utf-8"))
        factories = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and getattr(node.func.value, "id", "") == "DriverLimits"
            and node.func.attr == "from_config"
        ]
        assert len(factories) == 1, name
        assert factories[0].args, f"{name}: runtime config must be passed"
        keywords = {kw.arg: ast.unparse(kw.value) for kw in factories[0].keywords}
        assert keywords["llm_timeout_s"] == "args.llm_timeout"


# ---------------------------------------------------------------- v1.6 B2 / A7
def _codes(cfg):
    return {issue.code for issue in cfg.validate()}


def test_guard_and_labels_defaults_are_valid():
    cfg = AppConfig()
    assert cfg.guard.enabled is True and cfg.guard.preset == "standard"
    assert cfg.guard.sustain_frames == 12 and cfg.guard.edge_clip_max == 0.10
    assert cfg.guard.size_bands["head"]["CU"] == [0.55, 0.75]
    assert cfg.labels.adaptive_sampling is True
    assert cfg.labels.fullframe_verify is True
    assert not {"CFG_215", "CFG_216", "CFG_217"} & _codes(cfg)


def test_guard_invalid_preset_threshold_and_band_are_rejected():
    cfg = AppConfig()
    cfg.guard.preset = "extreme"
    assert "CFG_215" in _codes(cfg)
    cfg = AppConfig()
    cfg.guard.edge_clip_max = 1.5
    assert "CFG_216" in _codes(cfg)
    cfg = AppConfig()
    cfg.guard.sustain_frames = 0
    assert "CFG_216" in _codes(cfg)
    cfg = AppConfig()
    cfg.guard.size_bands["head"]["CU"] = [0.8, 0.6]
    assert "CFG_217" in _codes(cfg)


def test_guard_and_labels_round_trip_through_dict():
    cfg = AppConfig()
    cfg.guard.preset = "loose"
    cfg.labels.fullframe_verify = False
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.guard.preset == "loose"
    assert restored.labels.fullframe_verify is False
    assert restored.guard.size_bands == cfg.guard.size_bands


def test_generated_default_yaml_contains_the_new_sections():
    from pathlib import Path
    from block_director.contracts.config import dump_default_yaml

    text = dump_default_yaml()
    for key in ("guard:", "labels:", "adaptive_sampling", "fullframe_verify",
                "sustain_frames", "size_bands", "rhythm:", "pacing_profile",
                "pace_frame_multiplier"):
        assert key in text, key
    shipped = (Path(__file__).resolve().parents[1] / "specs"
               / "config.default.yaml").read_text(encoding="utf-8")
    assert shipped == text, "运行 python tools/gen_specs.py"


# ---------------------------------------------------------------- v1.6 D2
def test_rhythm_defaults_are_valid():
    cfg = AppConfig()
    assert cfg.rhythm.enabled is True
    assert cfg.rhythm.pacing_profile == "standard"
    assert cfg.rhythm.pace_frame_multiplier == {
        "slow": 1.35, "normal": 1.0, "brisk": 0.7}
    assert not {"CFG_218", "CFG_219"} & _codes(cfg)


def test_rhythm_invalid_profile_and_multiplier_are_rejected():
    cfg = AppConfig()
    cfg.rhythm.pacing_profile = "extreme"
    assert "CFG_218" in _codes(cfg)

    cfg = AppConfig()
    cfg.rhythm.pace_frame_multiplier = {"slow": 1.35, "normal": 0.0,
                                        "brisk": 0.7}
    assert "CFG_219" in _codes(cfg)

    cfg = AppConfig()
    cfg.rhythm.pace_frame_multiplier = {"slow": -1.0}
    assert "CFG_219" in _codes(cfg)


def test_rhythm_multiplier_table_matches_the_compiler():
    """config 与编译层的倍率表同值——两份声明用测试钉住，不让它们悄悄漂移。"""
    from block_director.layer5_orchestrator.beat_compiler import (
        PACE_FRAME_MULTIPLIER,
    )
    assert AppConfig().rhythm.pace_frame_multiplier == PACE_FRAME_MULTIPLIER


def test_rhythm_round_trip_through_dict():
    cfg = AppConfig()
    cfg.rhythm.enabled = False
    cfg.rhythm.pacing_profile = "urgent"
    cfg.rhythm.pace_frame_multiplier = {"slow": 1.5, "normal": 1.0,
                                        "brisk": 0.6}
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.rhythm.enabled is False
    assert restored.rhythm.pacing_profile == "urgent"
    assert restored.rhythm.pace_frame_multiplier == cfg.rhythm.pace_frame_multiplier
