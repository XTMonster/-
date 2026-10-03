"""`CONTEXT.md` 的"硬边界"必须与代码实际一致——逐条机检，不许靠自觉。

来历（2026-10-04，GLM-5.3 审核 lane 的读数 + 人复核）：`CONTEXT.md` 的目录
地图把 `utils/` 记成"**否**（不得 import bpy）"，而 `utils/blender_compat.py`
按 v1.2 §21.7 的职责**必须**碰 `bpy.app.version`；同时"纯层清单"漏了
`layer2_sdl/`、`layer9_persistence/replay.py` 与 `layer5_orchestrator/` 里的
无 bpy 模块。文档自称"改代码前先看这条"，却和代码对不上，等于没有边界。

这里把边界写成**唯一的机器可读真源**（下面的三张表），然后两头对拍：
一端是 `block_director/**/*.py` 的**实际 import**（AST 静态扫描，不执行代码），
另一端是 `CONTEXT.md` 的目录地图与纯层清单。任一边漂了都红。

为什么不是"运行时 import 试试"：`utils/blender_compat.py` 在 Blender 内导入
是**合法**的，只有静态扫描才分得清"这个文件被允许碰 bpy"和"这个目录不许"。
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = REPO / "block_director"
CONTEXT = REPO / "CONTEXT.md"

#: 整目录纯：除集合里点名的例外文件外，该目录下每个 ``.py`` 都不得 import bpy。
PURE_DIRS = {
    "contracts": frozenset(),
    "cinema": frozenset(),
    "motion": frozenset(),
    "layer1_input": frozenset(),
    "knowledge": frozenset(),
    "layer2_sdl": frozenset(),
    "delivery": frozenset(),
    "layer6_audit": frozenset(),
    # 版本兼容层的职责就是碰 bpy.app.version（v1.2 §21.7），是**声明的**例外。
    "utils": frozenset({"utils/blender_compat.py"}),
    # 只有 GUI 的模态算子是 bpy 入口；驱动器/编辑器/契约那一摞是纯层。
    "layer5_orchestrator": frozenset({"layer5_orchestrator/modal_operator.py"}),
}

#: 允许 bpy 的目录里，这些文件仍必须保持纯（pytest 直接跑）。
PURE_FILES_IN_MIXED_DIRS = frozenset({
    "layer7_ui/run_settings.py",
    "layer9_persistence/replay.py",
})

#: 允许 bpy 的目录（没有"整目录纯"的要求）。
BPY_DIRS = frozenset({
    "layer3_engine",
    "layer7_ui",
    "layer8_delivery",
    "layer9_persistence",
})


def _bpy_import_lines(path: pathlib.Path) -> list[int]:
    """这个文件在第几行（1 起）import 了 bpy；没有就是空表。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "bpy" for alias in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "bpy":
                lines.append(node.lineno)
    return lines


def _bpy_importers() -> dict[str, list[int]]:
    """整个包里 import bpy 的文件 → 行号（相对 ``block_director/`` 的 posix 路径）。"""
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        lines = _bpy_import_lines(path)
        if lines:
            found[path.relative_to(PACKAGE).as_posix()] = lines
    return found


def _map_rows() -> dict[str, str]:
    """目录地图：``block_director/<dir>/`` → "允许 import bpy？" 那一格的原文。"""
    rows: dict[str, str] = {}
    for line in CONTEXT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or "block_director/" not in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        match = re.fullmatch(r"`block_director/([A-Za-z0-9_]+)/`", cells[0])
        if match:
            rows[match.group(1)] = cells[2]
    return rows


def _hard_boundary_text() -> str:
    """`CONTEXT.md` 里"硬边界"那一节（到下一个二级标题为止）。"""
    text = CONTEXT.read_text(encoding="utf-8")
    start = text.index("## 硬边界")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_pure_directories_never_import_bpy():
    """整目录纯的那些层，除声明的例外外一个 `import bpy` 都不许有。"""
    offenders: list[str] = []
    for directory, exceptions in PURE_DIRS.items():
        for path in sorted((PACKAGE / directory).rglob("*.py")):
            rel = path.relative_to(PACKAGE).as_posix()
            if rel in exceptions:
                continue
            for lineno in _bpy_import_lines(path):
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "这些文件在纯层里 import bpy：" + ", ".join(offenders))


def test_pure_files_inside_bpy_directories_never_import_bpy():
    offenders: list[str] = []
    for rel in sorted(PURE_FILES_IN_MIXED_DIRS):
        path = PACKAGE / rel
        assert path.exists(), f"纯层清单点名了不存在的文件：{rel}"
        for lineno in _bpy_import_lines(path):
            offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "这些点名要保持纯的文件 import 了 bpy：" + ", ".join(offenders))


def test_every_bpy_import_lives_in_a_declared_place():
    """反向：包里每个 `import bpy` 都必须落在允许的位置，堵住"悄悄长出来"。"""
    allowed = set(PURE_FILES_IN_MIXED_DIRS)
    for directory, exceptions in PURE_DIRS.items():
        allowed |= set(exceptions)
    stray: list[str] = []
    for rel, lines in _bpy_importers().items():
        if rel in allowed:
            continue
        if rel.split("/", 1)[0] in BPY_DIRS:
            continue
        stray.append(f"{rel}:{lines[0]}")
    assert stray == [], (
        "这些 import bpy 不在任何声明允许的位置：" + ", ".join(stray))


def test_the_directory_map_and_the_hard_boundary_agree():
    """目录地图、纯层清单、实际 import：三份必须说同一件事。"""
    rows = _map_rows()
    boundary = _hard_boundary_text()
    importers = _bpy_importers()

    assert set(rows) == set(PURE_DIRS) | set(BPY_DIRS), (
        "目录地图的目录集合与边界表对不上："
        f"只在地图里 {sorted(set(rows) - (set(PURE_DIRS) | set(BPY_DIRS)))}，"
        f"只在表里 {sorted((set(PURE_DIRS) | set(BPY_DIRS)) - set(rows))}")

    for directory, cell in rows.items():
        named_inside = [rel for rel in importers
                        if rel.split("/", 1)[0] == directory]
        if cell == "**否**":
            assert named_inside == [], (
                f"目录地图把 {directory}/ 记成【否】，但它里面有 import bpy："
                + ", ".join(named_inside))
            assert directory in PURE_DIRS, (
                f"{directory}/ 记成【否】就必须进纯层清单")
            assert f"`{directory}/`" in boundary, (
                f"纯层清单没有点名 {directory}/")
        elif cell.startswith("**是**"):
            assert directory in BPY_DIRS, (
                f"目录地图允许 {directory}/ 用 bpy，但边界表把它当纯层")
        else:
            # "部分（…）"：允许 bpy 的必须是**点名**的文件，其余仍纯。
            assert directory in PURE_DIRS or directory in BPY_DIRS
            if directory in PURE_DIRS:
                for rel in PURE_DIRS[directory]:
                    assert pathlib.Path(rel).name in boundary, (
                        f"纯层清单没有点名例外文件 {rel}")

    for directory in PURE_DIRS:
        assert f"`{directory}/`" in boundary, f"纯层清单漏了 {directory}/"
    for rel in PURE_FILES_IN_MIXED_DIRS:
        assert rel in boundary, f"纯层清单漏了 {rel}"


def test_the_priority_terms_are_defined_in_the_glossary():
    """`声明 > 理解 > 草案` 是规划字段的覆盖语义，三个词都得有定义。"""
    text = CONTEXT.read_text(encoding="utf-8")
    gloss_start = text.index("## 核心术语")
    gloss_end = text.find("\n## ", gloss_start + 1)
    glossary = text[gloss_start:] if gloss_end == -1 else text[gloss_start:gloss_end]
    for term in ("声明（declared）", "理解（brief）", "草案（draft）"):
        assert term in glossary, f"术语表没有定义 {term}"
