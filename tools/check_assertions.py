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

第三条规则（2026-10-02 补，来自一次**真实的**漏网）：**"没有断言"本身也是
空断言**。实测缺陷：``tests/test_holdout_candidates.py`` 里有一条用例
``test_draft_all_records_transport_failure_without_raising``，函数体只有
``try: draft_all(...) / except RuntimeError: pass`` —— 名字与实现相反，异常
被自己吞掉，**无论实现怎么坏它都绿**。前两条规则都判不到它（它不是恒真式，
也没有非有限浮点），于是它从引入那天起就躲在自己的门之外。规则如下：一个
``test_*`` 函数的**自身语句**里必须至少有一处"会判"的构造：

* ``assert`` 语句，或 ``raise``（``else: raise AssertionError`` 这种写法）；
* ``pytest.raises/fail/skip/xfail/warns/deprecated_call/raises_group``；
* ``self.assertXxx(...)``；
* 调用**名字带断言语义**的辅助函数（``assert*``/``check*``/``verify*``/
  ``validate*``/``require*``）——它们自己会抛；
* 调用**本文件里定义了、且自身会判**的模块级辅助函数（递归判定，
  ``require_fixture`` 这种）。

**嵌套函数体不算**：``def boom(): raise`` 定义在用例里面，不构成用例自己的
判定（这正是上面那条真实缺陷的形状）。``pytest`` 的构造器/夹具会在用例之外
判定，同样不算。

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
from typing import Dict, List, Tuple

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


# --------------------------------------------------------------------------- #
# 规则三：**一条测试如果根本没有判定，它就是空的**
# --------------------------------------------------------------------------- #

#: 这些调用名（``attr`` 或裸名）本身就是"会判"的构造。
ASSERTIVE_CALL_NAMES = frozenset((
    "raises", "raises_group", "fail", "skip", "xfail", "warns",
    "deprecated_call",
))

#: 名字带这些前缀的辅助函数（``require_fixture`` / `validate_edge` / ``_assert_x``）
#: 会自己抛异常；把它们算作判定，避免把"调用断言助手"误报成空用例。
ASSERTIVE_CALL_PREFIXES = ("assert", "check", "verify", "validate", "require")


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _own_statements(function: ast.AST) -> List[ast.AST]:
    """函数**自身**的语句（不下潜进嵌套函数/类/lambda 的体内）。

    为什么必须排除嵌套体：真实缺陷的形状就是"用例里定义一个会抛的辅助函数，
    然后把它吞掉"。若把嵌套体算进来，``except RuntimeError: pass`` 会被那句
    ``raise`` 洗白，门就又空了。
    """
    out: List[ast.AST] = []
    pending = list(getattr(function, "body", []))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            continue
        out.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return out


def _has_conclusive_statement(function: ast.AST, helpers: Dict[str, ast.AST],
                              seen: Tuple[str, ...] = ()) -> bool:
    """``function`` 的自身语句里有没有"会判"的构造（``helpers`` 供递归解析）。"""
    for node in _own_statements(function):
        if isinstance(node, (ast.Assert, ast.Raise)):
            return True
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if not name:
            continue
        if name in ASSERTIVE_CALL_NAMES or name.startswith(
                ASSERTIVE_CALL_PREFIXES):
            return True
        # 本文件里的模块级助手：递归判**它**会不会判（带环保护）。
        helper = helpers.get(name)
        if helper is not None and name not in seen \
                and _has_conclusive_statement(helper, helpers, seen + (name,)):
            return True
    return False


def scan_for_assertion_free_tests(text: str,
                                  filename: str = "<string>") -> List[Tuple[int, str]]:
    """返回 ``[(行号, 用例名), ...]``：**自身没有任何判定**的 ``test_*`` 函数。"""
    tree = ast.parse(text, filename=filename)
    helpers = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    found: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        if not _has_conclusive_statement(node, helpers):
            found.append((getattr(node, "lineno", 0), node.name))
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
            hollow = scan_for_assertion_free_tests(text, str(path))
        except (OSError, SyntaxError) as exc:
            problems.append(f"{path}: 无法分析（{exc}）")
            continue
        scanned += 1
        for line, snippet in found:
            problems.append(f"{path}:{line}: 空断言（永远为真）：{snippet}")
        for line, name in hollow:
            problems.append(
                f"{path}:{line}: 空测试（用例自身没有任何判定）：{name}")
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
        print("[FAIL] 发现空断言／空测试：")
        for item in problems:
            print("  " + item)
        return 1
    print(f"[OK] 扫描 {scanned} 个文件，未发现空断言，也没有自身不判定的 test_ 函数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
