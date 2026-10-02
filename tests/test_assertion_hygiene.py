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
# 第三条规则（2026-10-02）：**没有判定的用例也是空的**
#
# 实测漏网：`tests/test_holdout_candidates.py:75` 那条用例的函数体只有
# `try: draft_all(...) / except RuntimeError: pass`——名字与实现相反，异常被自己
# 吞掉，**无论实现怎么坏都绿**。它既不是恒真式（规则一判不到），也没有非有限
# 浮点（规则二判不到），所以从引入那天起就躲在自己的门之外。
# --------------------------------------------------------------------------- #

def test_a_test_without_any_assertion_is_flagged():
    """负例：这个形状必须被扫出来，否则新规则本身是空的。"""
    checker = _load_checker()
    source = (
        "def test_swallows_everything():\n"
        "    try:\n"
        "        run_it()\n"
        "    except RuntimeError:\n"
        "        pass\n"
        "def test_just_calls_it():\n"
        "    run_it()\n"
    )
    found = checker.scan_for_assertion_free_tests(source, "synthetic.py")
    assert [line for line, _ in found] == [1, 6]
    assert [name for _, name in found] == ["test_swallows_everything",
                                           "test_just_calls_it"]


def test_a_nested_definition_does_not_count_as_judging():
    """真实缺陷的**精确形状**：用例里定义一个会抛的辅助函数，然后把它吞掉。

    嵌套函数体里的 ``raise`` 不是用例自己的判定——若把它算进来，门就又空了。
    """
    checker = _load_checker()
    source = (
        "def test_nested_raiser_only():\n"
        "    def boom():\n"
        "        raise RuntimeError('x')\n"
        "    try:\n"
        "        boom()\n"
        "    except RuntimeError:\n"
        "        pass\n"
    )
    found = checker.scan_for_assertion_free_tests(source, "synthetic.py")
    assert [name for _, name in found] == ["test_nested_raiser_only"]


def test_conclusive_constructs_are_not_flagged():
    """正例：每一种"会判"的构造都要被认下来（否则规则会误报真用例）。"""
    checker = _load_checker()
    source = (
        "def require_thing(value):\n"
        "    assert value\n"
        "def test_assert_statement():\n"
        "    assert 1 == 1\n"
        "def test_raise_in_else():\n"
        "    try:\n"
        "        run_it()\n"
        "    except ValueError:\n"
        "        pass\n"
        "    else:\n"
        "        raise AssertionError('应当抛')\n"
        "def test_pytest_raises():\n"
        "    with pytest.raises(RuntimeError):\n"
        "        run_it()\n"
        "def test_unittest_style():\n"
        "    self.assertAlmostEqual(1.0, 1.0)\n"
        "def test_local_helper_from_this_file():\n"
        "    require_thing(1)\n"
        "def test_imported_validator():\n"
        "    hg.validate_edge(edge, nodes)\n"
    )
    assert checker.scan_for_assertion_free_tests(source, "synthetic.py") == []


def test_the_whole_suite_has_no_assertion_free_tests():
    """仓库级：1498 条用例必须每条都至少有一处判定（与 CLI 同一份实现）。"""
    checker = _load_checker()
    offenders = {}
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        found = checker.scan_for_assertion_free_tests(
            path.read_text(encoding="utf-8"), str(path))
        if found:
            offenders[path.name] = found
    assert offenders == {}, f"这些用例自身不判定：{offenders}"


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
