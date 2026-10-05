"""P5 的覆盖验收：**12 格覆盖矩阵**（域 × 研究维度），而不是只看总边数。

为什么要它：用户的研究目标是把"白模预演的强耦合"讲清楚——行为／动作／情绪／意图 ×
镜头语言 × 构图 × **震动打击感**。总边数够了不代表每一格都有料；`CORPUS_V4.md`
的实测已经把偏斜摆出来了（`composition` 2 条来源、`blocking` 1 条）。

口径（写死，避免"看情况挑一个"）：

* **维度** ← 边型（`hg.EDGE_TYPES`）的映射，见 `coverage_matrix.DIMENSION_OF_TYPE`；
  一个边型可以属于多个维度（例如 `SHOT_PATTERN` 既讲镜头语言也讲构图）；
* **域** ← 边所属**卡片**的 `domain`（卡片即片段，来自影子语料）；
* **格** ＝ `(域, 维度)`；**空格** ＝ 计数为 0 的格；`floor` 以下的格单列。

单位是**边数**（计划里写的是"卡片数"，这里如实标成边，不混账）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.knowledge import hypergraph as hg  # noqa: E402
from tools.knowledge import coverage_matrix as cm  # noqa: E402


def test_every_edge_type_is_mapped_to_at_least_one_dimension():
    """映射必须覆盖**全部**边型——加新边型不带维度归属，当场红。"""
    mapped = {edge_type for types in cm.DIMENSION_OF_TYPE.values() for edge_type in types}
    missing = sorted(set(hg.EDGE_TYPES) - mapped)
    assert missing == [], "这些边型没有维度归属：%s" % missing


def test_the_impact_dimension_covers_impact_and_action_beats():
    assert hg.IMPACT_PACK in cm.DIMENSION_OF_TYPE[cm.IMPACT]
    assert hg.ACTION_BEAT in cm.DIMENSION_OF_TYPE[cm.IMPACT]
    assert hg.SOUND_PACK in cm.DIMENSION_OF_TYPE[cm.IMPACT]


def test_cells_are_counted_per_domain_and_dimension():
    edges = [{"type": hg.IMPACT_PACK, "sources": ["seg:aaa:0-10"]},
             {"type": hg.IMPACT_PACK, "sources": ["seg:aaa:10-20"]},
             {"type": hg.TROPE, "sources": ["seg:bbb:0-10"]}]
    domains = {"seg:aaa:0-10": "cinematography", "seg:aaa:10-20": "cinematography",
               "seg:bbb:0-10": "anime"}
    report = cm.coverage(edges, domains)
    assert report["by_dimension"][cm.IMPACT] == 2
    assert report["by_dimension"][cm.NARRATIVE] == 1
    assert report["cells"][("cinematography", cm.IMPACT)] == 2
    assert report["cells"][("anime", cm.NARRATIVE)] == 1


def test_empty_cells_and_below_floor_cells_are_listed_separately():
    edges = [{"type": hg.TROPE, "sources": ["seg:bbb:0-10"]}]
    report = cm.coverage(edges, {"seg:bbb:0-10": "anime"}, floor=2)
    #: `empty_cells` 只枚举**数据里出现过的域**（不可能枚举没边的域）——
    #: `TROPE` 只归"行为动作情绪意图"，所以 anime 其余五格是空的。
    assert ("anime", cm.IMPACT) in report["empty_cells"]
    assert ("anime", cm.NARRATIVE) not in report["empty_cells"]
    #: floor=2 且该格计数是 1 ⇒ 低于门槛（但它不是空格）。
    assert ("anime", cm.NARRATIVE) in report["below_floor"]


def test_an_edge_whose_card_is_unknown_is_reported_not_dropped():
    """卡片查不到域 ⇒ 记进 `unknown_domain`，**不许悄悄算进某一格**。"""
    edges = [{"type": hg.TROPE, "sources": ["seg:zzz:0-10"]}]
    report = cm.coverage(edges, {})
    assert report["unknown_domain"] == 1
    assert report["by_dimension"].get(cm.NARRATIVE, 0) == 0
