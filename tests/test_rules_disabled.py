"""v1.7 卡 F1：哨兵短路＋skipped 留痕（TDD §4.4）。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from block_director.contracts.audit import (
    AuditError,
    AuditResult,
    SkippedFinding,
)
from block_director.contracts.enums import Severity

ROOT = Path(__file__).resolve().parents[1]


def _load_rule_checker():
    #: ``rule_checker.py`` 顶层 import bpy，pytest 环境无法直接导入；照
    #: ``tests/test_tool_bindings_env.py`` 先例绕过 ``layer3_engine/__init__``
    #: 的 eager bpy 导入，直接按文件路径加载。规则模块的模块级只有 import、
    #: 无 bpy 属性访问（函数体内才触达），所以三个桩就够了。
    stub_names = ("bpy", "bpy_extras", "bpy_extras.object_utils", "mathutils")
    prior = {name: sys.modules.get(name) for name in stub_names}
    try:
        bpy_module = types.ModuleType("bpy")
        sys.modules["bpy"] = bpy_module
        bpy_extras = types.ModuleType("bpy_extras")
        object_utils = types.ModuleType("bpy_extras.object_utils")
        object_utils.world_to_camera_view = lambda *args, **kwargs: (0.0, 0.0, 0.0)
        bpy_extras.object_utils = object_utils
        sys.modules["bpy_extras"] = bpy_extras
        sys.modules["bpy_extras.object_utils"] = object_utils
        mathutils = types.ModuleType("mathutils")
        mathutils.Vector = type("Vector", (), {})
        sys.modules["mathutils"] = mathutils
        name = "block_director.layer3_engine.rule_checker"
        path = ROOT / "block_director" / "layer3_engine" / "rule_checker.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        #: 加载完立刻撤桩——bpy 残留 sys.modules 会让"契约层不得 import bpy"
        #: 这类全仓断言误判（tests/test_package_surface.py 实锤）。
        for name, value in prior.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


rule_checker = _load_rule_checker()


def _error(rule: str = "R009") -> AuditError:
    return AuditError(rule=rule, code="E_CAM_001",
                      severity=Severity.WARNING,
                      message="距离偏差", suggestion="reframe")


def test_empty_matches_head_byte_identical():
    result = AuditResult.from_findings([_error()], target="shot_001")
    payload = result.to_dict()
    assert "skipped" not in payload
    assert payload == {
        "passed": True, "level": "rule", "target": "shot_001",
        "score": None, "errors": [], "warnings": [_error().to_dict()],
        "suggestions": ["reframe"],
    }


def test_disabled_rule_leaves_skip_trace():
    rule_checker.configure_rules_disabled(["R009"])
    finding = rule_checker._finding(Severity.WARNING, "R009", "E_CAM_001",
                                    "距离偏差", suggestion="reframe")
    assert isinstance(finding, SkippedFinding)
    result = AuditResult.from_findings([finding, _error("R010")],
                                       target="shot_001")
    assert [item.rule for item in result.errors] == []
    assert [item.rule for item in result.warnings] == ["R010"]
    assert [item.to_dict() for item in result.skipped] == [
        {"rule": "R009", "skipped": True}]
    assert result.to_dict()["skipped"] == [{"rule": "R009", "skipped": True}]
    #: 其余规则读数逐字节不变（R010 的 finding 一个字没动）。
    assert result.warnings[0].to_dict() == _error("R010").to_dict()
    rule_checker.configure_rules_disabled([])


def test_review_path_also_splits():
    from block_director.layer5_orchestrator.review import AuditResult as Review
    result = Review.from_findings(
        [SkippedFinding(rule="R019"), _error()], level="llm", target="shot_001")
    assert result.level == "llm"
    assert len(result.skipped) == 1
    assert len(result.warnings) == 1


def test_unknown_rule_id_noop():
    rule_checker.configure_rules_disabled(["R999"])
    finding = rule_checker._finding(Severity.WARNING, "R009", "E_CAM_001",
                                    "距离偏差")
    assert isinstance(finding, AuditError)
    rule_checker.configure_rules_disabled([])
    assert AuditResult.from_findings([_error()]).skipped == []
