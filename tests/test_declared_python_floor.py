"""声明支持的解释器下界必须**真的被满足**，否则全绿是在不受支持的运行时上产出的。

实测缺陷（2026-10-02，来自并行验收视角的盘点）：`pyproject.toml` 写
``requires-python = ">=3.11"``，而本机跑出 `1616 passed` 的解释器是 **3.10.11**。
两边都没错得离谱——代码里没有 3.11 专属特性（无 ``tomllib``／``typing.Self``／
``except*``／``asyncio.TaskGroup``），``block_director/contracts/enums.py`` 还
**故意**自带 ``StrEnum`` 兼容实现——但"声明 3.11、实测 3.10"这种组合本身就是
"缺证据被当成通过"的镜像：**没人验证过声明支持的那个下界**。

修法不是把其中一句悄悄改掉，而是让两边**互相钉住**：

* 声明改成实际验证过的下界（3.10）；
* 本用例断言**运行解释器满足声明**——用一个不支持的解释器跑，套件当场红，
  而不是产出一份看起来全绿的证据。

诚实边界：本机另有 3.11／3.12／3.13，但它们都没装测试依赖（``pytest`` 缺席），
所以**上界这一段仍未验证**。这里不假装它验证过。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def declared_floor(text: str) -> tuple:
    """从 ``requires-python`` 里读出 ``>=X.Y`` 的下界。

    刻意用正则而不是 ``tomllib``：``tomllib`` 是 3.11+ 才有的标准库，
    而这个测试存在的理由之一就是**3.10 也要能跑**。
    """
    match = re.search(r'(?m)^\s*requires-python\s*=\s*"([^"]+)"', text)
    assert match, "pyproject.toml 里没有 requires-python"
    spec = match.group(1).strip()
    floor = re.fullmatch(r">=\s*(\d+)\.(\d+)", spec)
    assert floor, (
        f"requires-python 必须是可比较的下界（>=X.Y），当前是 {spec!r}——"
        "区间/排除式写法没法被这条门判定")
    return int(floor.group(1)), int(floor.group(2))


def test_pyproject_declares_a_comparable_floor():
    floor = declared_floor(PYPROJECT.read_text(encoding="utf-8"))
    assert floor >= (3, 10), (
        f"下界 {floor} 低于仓库自己声明要兼容的 3.10"
        "（contracts/enums.py 的 StrEnum 兼容实现就是为它准备的）")


def test_the_running_interpreter_satisfies_the_declared_floor():
    """这条用例是"声明 vs 实跑"的**唯一**粘合点：不支持 ≠ 全绿。"""
    floor = declared_floor(PYPROJECT.read_text(encoding="utf-8"))
    assert sys.version_info[:2] >= floor, (
        f"当前解释器 {sys.version_info[:3]} 不满足 pyproject 声明的下界 "
        f"{floor[0]}.{floor[1]}：这份绿不能算数，先在受支持的解释器上重跑")


def test_the_floor_is_not_a_range_that_hides_the_upper_end():
    """负例自证：区间式写法必须被拒（否则"支持的"上界永远是空的）。"""
    with pytest.raises(AssertionError, match="可比较的下界"):
        declared_floor('requires-python = ">=3.10,<3.13"\n')
    with pytest.raises(AssertionError, match="没有 requires-python"):
        declared_floor("name = 'x'\n")
