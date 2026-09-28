"""§13.1 运行设置的覆盖逻辑（纯计算）。"""

from __future__ import annotations

from block_director.contracts.config import AppConfig
from block_director.contracts.enums import AuditLevel, DeliveryPreset, RenderBackend
from block_director.layer7_ui.run_settings import (
    APPEARANCES,
    AUDIT_LEVELS,
    PRESETS,
    apply_scene_settings,
)


def fresh() -> AppConfig:
    return AppConfig()


def test_empty_settings_change_nothing():
    config = fresh()
    before = config.to_dict()
    _config, problems = apply_scene_settings(config, {})
    assert problems == []
    assert config.to_dict() == before


def test_panel_fields_override_the_config():
    config = fresh()
    _config, problems = apply_scene_settings(config, {
        "provider": "deepseek", "model": "deepseek-chat",
        "audit_level": "strict", "preset": "fhd16x9",
        "appearance": "flat", "render_backend": "eevee",
        "max_cost_usd": 2.5, "max_wall_minutes": 10,
        "max_llm_calls": 12})
    assert problems == []
    assert config.llm.provider == "deepseek"
    assert config.llm.model == "deepseek-chat"
    assert config.audit.level is AuditLevel.STRICT
    assert config.delivery.preset is DeliveryPreset.FHD16X9
    assert config.delivery.appearance == "flat"
    assert config.delivery.render_backend is RenderBackend.EEVEE
    assert config.budget.max_cost_usd == 2.5
    assert config.budget.max_wall_minutes == 10.0
    assert config.budget.max_llm_calls_per_scene_formula == "12"


def test_untouched_fields_keep_the_file_values():
    config = fresh()
    config.llm.model = "my-local-model"
    _config, problems = apply_scene_settings(config, {"audit_level": "lenient"})
    assert problems == [] and config.llm.model == "my-local-model"


def test_bad_enum_values_are_reported_not_applied():
    config = fresh()
    _config, problems = apply_scene_settings(config, {
        "audit_level": "whatever", "preset": "cinema",
        "appearance": "neon", "render_backend": "octane"})
    assert len(problems) == 4
    assert config.audit.level is AuditLevel.STANDARD      # 保持默认
    assert config.delivery.preset is DeliveryPreset.HD16X9


def test_bad_numbers_are_reported_not_applied():
    config = fresh()
    _config, problems = apply_scene_settings(config, {
        "max_cost_usd": "很多", "max_wall_minutes": -1,
        "max_llm_calls": "十二"})
    assert len(problems) == 3
    assert config.budget.max_cost_usd == 5.0
    assert config.budget.max_wall_minutes == 30.0
    assert config.budget.max_llm_calls_per_scene_formula == "shots * 6"


def test_negative_budget_is_rejected():
    config = fresh()
    _config, problems = apply_scene_settings(config, {"max_llm_calls": -3})
    assert problems and "不能为负" in problems[0]


def test_config_validation_errors_surface_after_overriding():
    """面板选了 workbench 又开着 depth：必须在开跑前报出来（CFG_102）。"""
    config = fresh()
    config.delivery.export_depth = True
    _config, problems = apply_scene_settings(config, {"render_backend": "workbench"})
    assert any("CFG_102" in item or "eevee" in item for item in problems)


def test_documented_choice_lists_match_the_enums():
    assert AUDIT_LEVELS == ("strict", "standard", "lenient")
    assert PRESETS == ("hd16x9", "fhd16x9", "square", "vertical")
    assert APPEARANCES == ("clay", "flat", "color_coded")
