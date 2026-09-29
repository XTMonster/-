"""v1.4 §B.5 / P16：静态空断言检查必须存在、必须能红。

`tools/check_assertions.py` 扫描测试套件里"永远不可能失败"的断言
（``assert True`` 这类恒真式）。它**不依赖 bpy**——塞进
``tools/audit_architecture.py`` 那种 ``import bpy`` 的脚本里，没有 Blender
时整个检查会一起消失，那与 F1 的"缺环境必须报错"自相矛盾。
"""

from __future__ import annotations

import importlib.util
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
