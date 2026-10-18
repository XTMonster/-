"""Ticket 04：Blockout 自检报告生成器（纯层，不 import bpy）。

钉死：逐镜数值证据 -> 版本化 BlockoutReport；判定语义（composition >= 80
pass / 可见比例与画面占比阈值 / 空墙 finding）；错误 finding -> verdict fail；
同一输入两次构建逐位一致；报告过 Ticket 02 的 report Schema。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import jsonschema

from block_director.cinema.blockout_report import (
    BLOCKOUT_REPORT_SCHEMA,
    COMPOSITION_PASS,
    E_BLOCKOUT_EMPTY_WALL,
    build_blockout_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _report_schema() -> dict:
    path = (ROOT / "block_director" / "contracts" / "blockout" / "schema"
            / "blockout-report.v1.schema.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_shot() -> dict:
    return {
        "shot_id": "shot_001",
        "composition_score": 92.0,
        "visible_ratio": 1.0,
        "on_screen_ratio": 0.4,
        "off_screen": False,
        "design_diff": {"max_deviation_m": 0.05},
        "frames": [{"frame": 1, "png": "preview/shot_001_f001.png"}],
    }


def _report(per_shot=None, notes=None):
    return build_blockout_report(
        manifest={"schema_version": "blockout-manifest/v1"},
        per_shot=per_shot if per_shot is not None else [_clean_shot()],
        manifest_fingerprint="abc123",
        notes=notes)


def test_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "cinema" / "blockout_report.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "") for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


def test_clean_shot_passes_schema_and_verdict():
    report = _report()
    assert report["schema_version"] == BLOCKOUT_REPORT_SCHEMA
    assert report["verdict"] == "pass"
    jsonschema.validate(instance=report, schema=_report_schema())


def test_occlusion_low_produces_empty_wall_finding_and_fail():
    shot = _clean_shot()
    shot["visible_ratio"] = 0.1
    report = _report([shot])
    assert report["verdict"] == "fail"
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty and empty[0]["severity"] == "error"
    occlusion = [c for c in report["checks"] if c["check_id"] == "occlusion"]
    assert occlusion and occlusion[0]["verdict"] == "fail"


def test_low_on_screen_ratio_produces_empty_wall_finding():
    shot = _clean_shot()
    shot["on_screen_ratio"] = 0.01
    report = _report([shot])
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty


def test_off_screen_warning_and_no_error():
    shot = _clean_shot()
    shot["off_screen"] = True
    report = _report([shot])
    warn = [f for f in report["findings"] if f["check_id"] == "off_screen"]
    assert warn and warn[0]["severity"] == "warning"
    assert report["verdict"] == "pass"  # warning 不推翻 verdict


def test_off_screen_with_low_on_screen_is_empty_wall_error():
    """完全出画 + 画面占比近零 = 相机对空墙（硬伤），不降级为 warning。"""
    shot = _clean_shot()
    shot["off_screen"] = True
    shot["on_screen_ratio"] = 0.01
    report = _report([shot])
    empty = [f for f in report["findings"]
             if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert empty and empty[0]["severity"] == "error"
    assert report["verdict"] == "fail"


def test_empty_shot_is_exempt_and_pass():
    """空镜合法：无主体 -> 空镜豁免 pass，不报空墙，不因无证据误判 fail。"""
    shot = {
        "shot_id": "shot_empty",
        "empty": True,
        "frames": [{"frame": 1, "png": "preview/shot_empty_f0001.png"}],
    }
    report = _report([shot])
    empty_check = [c for c in report["checks"]
                   if c["check_id"] == "empty_shot"]
    assert empty_check and empty_check[0]["verdict"] == "pass"
    assert not [f for f in report["findings"]
                if f["check_id"] == E_BLOCKOUT_EMPTY_WALL]
    assert report["verdict"] == "pass"
    jsonschema.validate(instance=report, schema=_report_schema())


def test_missing_values_are_unresolved_not_guessed():
    shot = _clean_shot()
    shot["visible_ratio"] = None
    shot["on_screen_ratio"] = None
    shot["composition_score"] = None
    report = _report([shot])
    unresolved = [c for c in report["checks"] if c["verdict"] == "unresolved"]
    assert len(unresolved) >= 3


def test_two_builds_are_byte_identical():
    first = json.dumps(_report(), ensure_ascii=False, sort_keys=True)
    second = json.dumps(_report(), ensure_ascii=False, sort_keys=True)
    assert first == second


def test_composition_threshold_reads_from_single_source():
    assert COMPOSITION_PASS == 80.0
