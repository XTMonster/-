"""§21.5 配置契约测试：默认值、校验规则、序列化与规格文件一致性。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from block_director.contracts.config import (
    AppConfig,
    default_config_dir,
    dump_default_yaml,
)
from block_director.contracts.enums import (
    Appearance,
    AuditLevel,
    DeliveryPreset,
    RagBackend,
    RenderBackend,
    Severity,
    TransportMode,
)

ROOT = Path(__file__).resolve().parents[1]


def test_defaults_match_document():
    cfg = AppConfig()
    assert cfg.animation.fps == 24
    assert cfg.llm.transport is TransportMode.AUTO
    # v1.4 §2.3（§1.6 的 #26）：默认后端改为超图 RAG；sidecar 不可用时
    # 降级为 bm25，并在 knowledge_trace.json 里标 degraded。
    assert cfg.rag.backend is RagBackend.HYPERGRAPH
    assert cfg.delivery.render_backend is RenderBackend.WORKBENCH
    assert cfg.delivery.appearance is Appearance.CLAY
    assert cfg.delivery.preset is DeliveryPreset.HD16X9
    assert cfg.delivery.resolution == (1280, 720)
    assert cfg.dialogue.speech_rate["angry"] > 1.0 > cfg.dialogue.speech_rate["sad"]
    assert cfg.orchestration.max_repair_attempts == 2


def test_default_config_has_no_errors():
    assert AppConfig().errors() == []


def test_vector_rag_requires_sidecar():
    """决策（§6.1）：向量检索只能由 sidecar 提供。"""
    cfg = AppConfig()
    cfg.llm.transport = TransportMode.DIRECT
    cfg.rag.backend = RagBackend.VECTOR
    assert "CFG_101" in {i.code for i in cfg.errors()}

    cfg.llm.transport = TransportMode.AUTO
    assert "CFG_101" not in {i.code for i in cfg.errors()}


def test_depth_export_requires_eevee():
    """实测约束（§15.3）：Z Pass 只有 EEVEE 提供。"""
    cfg = AppConfig()
    cfg.delivery.export_depth = True
    assert "CFG_102" in {i.code for i in cfg.errors()}

    cfg.delivery.render_backend = RenderBackend.EEVEE
    assert "CFG_102" not in {i.code for i in cfg.errors()}


def test_viewport_backend_is_only_a_warning():
    cfg = AppConfig()
    cfg.delivery.render_backend = RenderBackend.VIEWPORT
    issues = {i.code: i.severity for i in cfg.validate()}
    assert issues.get("CFG_103") is Severity.WARNING
    assert cfg.errors() == []


@pytest.mark.parametrize("mutate, code", [
    (lambda c: setattr(c.animation, "fps", 0), "CFG_001"),
    (lambda c: setattr(c.animation, "blend_frames", 99), "CFG_002"),
    (lambda c: setattr(c.dialogue, "chinese_cps", 0), "CFG_003"),
    (lambda c: c.dialogue.speech_rate.__setitem__("angry", -1), "CFG_005"),
    (lambda c: setattr(c.llm, "temperature_plan", 3.0), "CFG_006"),
    (lambda c: setattr(c.rag, "top_k", 0), "CFG_007"),
    (lambda c: setattr(c.budget, "max_cost_usd", 0), "CFG_010"),
    (lambda c: setattr(c.character, "eye_color", "dark"), "CFG_204"),
    (lambda c: setattr(c.character, "eye_color", "#12"), "CFG_204"),
])
def test_validation_rules(mutate, code):
    cfg = AppConfig()
    mutate(cfg)
    assert code in {i.code for i in cfg.errors()}


def test_require_valid_raises_on_error():
    cfg = AppConfig()
    cfg.animation.fps = -1
    with pytest.raises(ValueError):
        cfg.require_valid()


def test_dict_roundtrip_is_stable():
    cfg = AppConfig()
    cfg.llm.model = "deepseek-chat"
    cfg.delivery.preset = DeliveryPreset.VERTICAL
    data = cfg.to_dict()
    assert data["llm"]["model"] == "deepseek-chat"
    assert data["delivery"]["preset"] == "vertical"
    assert data["delivery"]["render_backend"] == "workbench"
    json.dumps(data, ensure_ascii=False)   # 纯 JSON 可序列化
    assert AppConfig.from_dict(data).to_dict() == data


def test_save_and_load_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = AppConfig()
    cfg.rag.top_k = 7
    cfg.save(path)
    assert AppConfig.load(path).rag.top_k == 7


def test_save_and_load_json(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig()
    cfg.audit.level = AuditLevel.LENIENT
    cfg.save(path)
    assert AppConfig.load(path).audit.level is AuditLevel.LENIENT


def test_load_missing_file_returns_defaults(tmp_path):
    assert AppConfig.load(tmp_path / "nope.yaml").to_dict() == AppConfig().to_dict()


def test_default_dir_is_platform_specific():
    assert default_config_dir().name == "BlockDirector"


def test_spec_file_matches_generated_content():
    """specs/config.default.yaml 必须与代码默认值逐字符一致（§16.5）。"""
    spec = (ROOT / "specs" / "config.default.yaml").read_text(encoding="utf-8")
    assert spec == dump_default_yaml()


def test_eye_color_defaults_to_a_dark_colour():
    """v1.3 诉求 1：眼睛与身体分材质，默认深色。

    v1.2 的眼睛挂的是身体材质，于是眼睛和身体同色，看起来像没有五官。
    """
    cfg = AppConfig()
    assert cfg.character.eye_color == "#101010"
    assert cfg.errors() == []


def test_eye_color_accepts_short_hex():
    cfg = AppConfig()
    cfg.character.eye_color = "#333"
    assert "CFG_204" not in {i.code for i in cfg.errors()}
