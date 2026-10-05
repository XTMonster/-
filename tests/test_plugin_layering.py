"""架构守门：**插件包不许反向依赖仓库根的 `tools/`**。

为什么要有这条（2026-10-05 实测）：我写 LightRAG 适配器时从
`tools.lightrag_service` 导入 HTTP 客户端——而 `block_director/` 是**插件包**，
它跑在 Blender 自带的 Python 里，那条 import 路径在插件进程里未必存在。
`block_director/` 里几十个模块，只有我那一个是这么写的，**说明这条约定一直在守，
只是没人把它写成机器判据**。所以补上。

例外（白名单）必须具名，而且写清为什么：

* `block_director/` 下**没有**例外——需要共享的逻辑就往包内搬（这次就是把
  HTTP 客户端从 `tools/lightrag_service/client.py` 搬到
  `block_director/knowledge/lightrag_client.py`）。
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACKAGE = ROOT / "block_director"


def _imported_modules(path: pathlib.Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:            # 相对导入（包内）——这正是我们想要的
                continue
            names.append(node.module or "")
    return names


def test_the_plugin_package_never_imports_the_repo_level_tools_tree():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        for name in _imported_modules(path):
            if name == "tools" or name.startswith("tools."):
                offenders.append("%s -> %s" % (path.relative_to(ROOT), name))
    assert offenders == [], (
        "插件包反向依赖了 tools/：%s\n"
        "需要共享的逻辑请搬进 block_director/ 内（本仓的插件进程没有那条 import 路径）。"
        % offenders)


def test_the_guard_has_teeth_a_synthetic_offender_is_caught(tmp_path):
    """反面控制：造一个违规文件 ⇒ 规则必须认得出来。"""
    sample = tmp_path / "bad.py"
    sample.write_text("from tools.lightrag_service import client\n", encoding="utf-8")
    assert any(name.startswith("tools") for name in _imported_modules(sample))
