"""静态检查：找出**永远不可能失败**的空断言（v1.4 §B.5 的 P16 交付物）。

为什么需要它：测试套件里最容易悄悄腐烂的不是"断言写错"，而是"断言根本没在
判东西"——``assert True``、``assert 1``、``assert "x" == "x"`` 这类恒真式
无论实现怎么坏都会绿。它们不会被任何别的检查抓到，只会让覆盖率看起来很漂亮。

规则（刻意保守，避免误报）：

* 断言表达式是**字面量**（``assert True`` / ``assert 1`` / ``assert "x"``）；
* 断言是**字面量之间的比较**（``assert 1 == 1``）；
* 断言是``not`` 包裹的字面量。

真实断言（哪怕只是 ``assert findings``）**不算空断言**——它会因为空集合而
失败，是有鉴别力的。

第二条规则（2026-09-30 补，来自一次**真实**的回归）：``tools/blender_tests/``
里的探针把结果打成 ``BD_TEST_RESULT {json}``，而 ``run_tests.ps1`` 用
PowerShell 5.1 的 ``ConvertFrom-Json`` 读它。``json.dumps`` **默认允许**
``NaN``/``Infinity``，但那是**非法 JSON**：一旦探针上报了一个 NaN，那一行就
解析失败，该探针的 ``passed`` 名称整批丢失 → 挂在它上面的 RK **静默变成
``not_measured``**（实测：``test_phase2_motion.py`` 的 ``min_z: NaN`` 让
RK-6 与 RK-8 一起从"已量"掉成"未量"）。所以这里静态禁止探针源码里出现
非有限浮点字面量（``float("nan")``/``float("inf")``/``math.nan``/``math.inf``）——
上报值一律用 ``null`` ＋ 一个显式布尔标记。

纯 Python、不依赖 bpy，因此**没有 Blender 时也照样跑**（与 F1 一致：
它不能塞进 ``tools/audit_architecture.py`` 那种 ``import bpy`` 的脚本里）。

用法：
  python tools/check_assertions.py            # 扫描 tests/ 与 tools/blender_tests/
  python tools/check_assertions.py path ...   # 扫描指定文件/目录
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (ROOT / "tests", ROOT / "tools" / "blender_tests")


def _is_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) or (
        isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict))
        and all(_is_literal(item) for item in ast.iter_child_nodes(node)))


def _is_empty_expression(test: ast.AST) -> bool:
    """一个**表达式**是不是恒真式（不依赖 ``ast.Assert``，便于递归）。"""
    if _is_literal(test):
        return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) \
            and _is_literal(test.operand):
        return True
    if isinstance(test, ast.Compare):
        operands = [test.left] + list(test.comparators)
        if all(_is_literal(item) for item in operands):
            return True
    if isinstance(test, ast.BoolOp):
        return all(_is_empty_expression(item) for item in test.values)
    return False


def _is_empty_assertion(node: ast.Assert) -> bool:
    return _is_empty_expression(node.test)


#: 探针里**禁止**出现的非有限浮点写法（它们会让 `BD_TEST_RESULT` 变成非法 JSON）。
NON_FINITE_LITERALS = ("nan", "inf", "infinity", "-inf", "-infinity")


def find_non_finite(text: str) -> List[Tuple[int, str]]:
    """返回 ``[(行号, 片段), ...]``：会让探针标记非法 JSON 的非有限浮点。

    判据只看**字面量**与已知常量（``float("nan")`` / ``math.inf``），
    因此不会把变量名里恰好含 ``inf`` 的标识符算进来（如 ``info``）。
    """
    tree = ast.parse(text)
    found: List[Tuple[int, str]] = []

    def flag(node: ast.AST) -> None:
        found.append((getattr(node, "lineno", 0), ast.unparse(node)[:60]))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            if node.value != node.value or node.value in (
                    float("inf"), float("-inf")):
                flag(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "float" and node.args:
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str) \
                    and argument.value.strip().lower() in NON_FINITE_LITERALS:
                flag(node)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "math" \
                and node.attr.lower() in ("nan", "inf"):
            flag(node)
    return found


def scan_source(text: str, filename: str = "<string>") -> List[Tuple[int, str]]:
    """返回 ``[(行号, 源码片段), ...]``：该文件里的空断言。"""
    tree = ast.parse(text, filename=filename)
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and _is_empty_assertion(node):
            found.append((getattr(node, "lineno", 0),
                          ast.unparse(node.test)))
    return found


def _iter_files(targets) -> List[Path]:
    files: List[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        elif path.suffix == ".py" and path.exists():
            files.append(path)
    return files


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    targets = [Path(item) for item in args] or list(DEFAULT_TARGETS)
    problems: List[str] = []
    scanned = 0
    for path in _iter_files(targets):
        try:
            text = path.read_text(encoding="utf-8")
            found = scan_source(text, str(path))
        except (OSError, SyntaxError) as exc:
            problems.append(f"{path}: 无法分析（{exc}）")
            continue
        scanned += 1
        for line, snippet in found:
            problems.append(f"{path}:{line}: 空断言（永远为真）：{snippet}")
        if path.parent.name == "blender_tests":
            # 探针的标记必须是**严格合法**的 JSON，否则 RK 聚合会静默变瞎。
            try:
                for line, snippet in find_non_finite(text):
                    problems.append(
                        f"{path}:{line}: 探针里的非有限浮点会让 BD_TEST_RESULT "
                        f"变成非法 JSON（用 null 上报）：{snippet}")
            except SyntaxError as exc:      # pragma: no cover - 上一轮已解析过
                problems.append(f"{path}: 无法分析（{exc}）")
    if problems:
        print("[FAIL] 发现空断言：")
        for item in problems:
            print("  " + item)
        return 1
    print(f"[OK] 扫描 {scanned} 个文件，未发现空断言")
    return 0


if __name__ == "__main__":
    sys.exit(main())
