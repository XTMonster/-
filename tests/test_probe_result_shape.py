"""Blender 探针输出契约守卫（v1.7 收尾）。

``tools/run_tests.ps1`` 用 ``Get-MarkerPayload`` 抓 ``BD_TEST_RESULT`` 后的 JSON，
然后以 ``$parsed.failed`` 判定整支探针是否通过：:

    if (@($parsed.failed).Count -ne 0) { Fail(...) }

因此每支探针的 payload 必须是聚合形状 ``{"passed": [...], "failed": [...],
"checks": {...}}`` —— 只 ``json.dumps(RESULTS)`` 的裸字典会让 ``$parsed.failed``
为 ``$null``，而 ``@($null).Count == 1``，被误判成"失败且失败名为空"（实测：
2026-10-17 全链 46/47 assistant-panel FAILED，单跑却 PASS，根因就是缺聚合键）。

本测试静态扫描 ``tools/blender_tests/`` 下全部探针，任何 emit ``BD_TEST_RESULT``
的 print 源码片段必须同时含三个聚合键，防止未来新增探针漏键（无需启动 Blender）。
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLENDER_TESTS = ROOT / "tools" / "blender_tests"
AGGREGATE_KEYS = ("passed", "failed", "checks")


def _probe_files() -> list[pathlib.Path]:
    files = sorted(BLENDER_TESTS.glob("test_*.py"))
    assert files, "tools/blender_tests 下没有探针文件"
    return files


def _bd_result_prints(tree: ast.Module) -> list[ast.AST]:
    """AST 里所有 emit ``BD_TEST_RESULT`` 的 print 调用结点。"""
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if (isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str)
                        and "BD_TEST_RESULT" in sub.value):
                    found.append(node)
                    break
            else:
                continue
            break
    return found


def test_every_probe_result_payload_has_aggregate_keys():
    """每支探针的 BD_TEST_RESULT payload 都必须带 passed/failed/checks 聚合键。"""
    missing: list[str] = []
    for path in _probe_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in _bd_result_prints(tree):
            snippet = ast.get_source_segment(source, node) or ""
            for key in AGGREGATE_KEYS:
                if key not in snippet:
                    missing.append(f"{path.name}:{node.lineno} 缺 {key!r}")
    assert not missing, (
        "Blender 探针输出必须是聚合形状（run_tests.ps1 依 $parsed.failed 判定，"
        "裸 RESULTS 会被误判为失败）：\n" + "\n".join(missing))


def test_probe_files_are_coverable_by_chain():
    """探针目录里每个文件都要能被搜索到；数量变化由 AGENTS.md 对拍测试另行钉住。"""
    files = _probe_files()
    assert len(files) >= 43, f"探针文件数异常：{len(files)}"
