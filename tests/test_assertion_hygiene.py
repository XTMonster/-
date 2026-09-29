"""v1.4 §B.5 / P16：静态空断言检查必须存在、必须能红。

`tools/check_assertions.py` 扫描测试套件里"永远不可能失败"的断言
（``assert True`` 这类恒真式）。它**不依赖 bpy**——塞进
``tools/audit_architecture.py`` 那种 ``import bpy`` 的脚本里，没有 Blender
时整个检查会一起消失，那与 F1 的"缺环境必须报错"自相矛盾。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "check_assertions.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("bd_check_assertions", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_checker_exists_and_is_bpy_free():
    """AST 判据：真的没有 import bpy（docstring 里的说明不算）。"""
    import ast

    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert "bpy" not in imported
    assert not any(name.startswith("bpy.") for name in imported)


def test_the_whole_suite_has_no_empty_assertions():
    result = subprocess.run([sys.executable, str(CHECKER)],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr


def test_negative_tautologies_are_flagged():
    """负例：恒真式必须被扫出来（否则这条门就是空的）。"""
    checker = _load_checker()
    source = (
        "def test_a():\n"
        "    assert True\n"
        "def test_b():\n"
        "    assert 1 == 1\n"
        "def test_c():\n"
        "    assert not False\n"
    )
    found = checker.scan_source(source, "synthetic.py")
    assert [line for line, _ in found] == [2, 4, 6]


def test_meaningful_assertions_are_not_flagged():
    checker = _load_checker()
    source = (
        "def test_a(findings):\n"
        "    assert findings\n"
        "def test_b(value):\n"
        "    assert value == []\n"
        "def test_c(value):\n"
        "    assert 0.0 <= value <= 1.0\n"
    )
    assert checker.scan_source(source, "synthetic.py") == []


# --------------------------------------------------------------------------- #
# 第二条规则（2026-09-30）：探针里的非有限浮点会让 RK 聚合静默变瞎
#
# 实测回归：`tools/blender_tests/test_phase2_motion.py` 上报了 `"min_z": NaN`，
# `json.dumps` 照原样印出非法记号 `NaN`，PowerShell 5.1 的 `ConvertFrom-Json`
# 整行解析失败 → 该探针的 `passed` 名称全丢 → **RK-6 与 RK-8 一起从"已量"
# 掉成 `not_measured`**（§4.1b 硬规则 1：没量到不能算通过）。
# --------------------------------------------------------------------------- #

def test_non_finite_probe_payloads_are_flagged():
    checker = _load_checker()
    source = (
        "def a():\n"
        "    return float('nan')\n"
        "def b():\n"
        "    return math.inf\n"
        "def c(value):\n"
        "    return min(value, 1.0)\n"
    )
    found = checker.find_non_finite(source)
    assert [line for line, _ in found] == [2, 4]


def test_probes_on_disk_never_emit_non_finite_numbers():
    """仓库里**所有** Blender 探针都必须只能产出严格合法的 JSON 标记。"""
    checker = _load_checker()
    offenders = {}
    for path in sorted((ROOT / "tools" / "blender_tests").glob("test_*.py")):
        found = checker.find_non_finite(path.read_text(encoding="utf-8"))
        if found:
            offenders[path.name] = found
    assert offenders == {}


def test_the_cli_reports_a_non_finite_probe(tmp_path):
    """端到端：把一个含 NaN 的探针放进去，检查器必须以非零码报出来。"""
    probe_dir = tmp_path / "blender_tests"
    probe_dir.mkdir()
    bad = probe_dir / "test_bad.py"
    bad.write_text("def a():\n    return {'min_z': float('nan')}\n",
                   encoding="utf-8")
    # 子进程默认按控制台代码页写 stdout，父进程按 UTF-8 解码会把中文断言糊掉；
    # 显式让子进程走 UTF-8（这也是它被包装成文件时的行为）。
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env)
    assert result.returncode == 1
    assert "非有限浮点" in result.stdout
    assert "test_bad.py:2" in result.stdout
