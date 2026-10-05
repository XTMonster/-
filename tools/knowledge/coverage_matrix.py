"""P5 的覆盖验收：**域 × 研究维度**的覆盖矩阵（12 格）。

用户的研究目标是"白模预演的强耦合"——行为／动作／情绪／意图 × 镜头语言 × 构图 ×
**震动打击感**。总边数够了不代表每一格都有料：`CORPUS_V4.md` 的实测已经把偏斜摆出来
（`composition` 只 2 条来源、`blocking` 只 1 条）。本工具把那件事变成可读的格子。

口径（写死）：

* **维度 ← 边型**：`DIMENSION_OF_TYPE` 是唯一映射，一个边型可属多个维度；
  加新边型不带归属会被 `tests/test_coverage_matrix.py` 当场抓（守门覆盖全部边型）；
* **域 ← 边所属卡片的 `domain`**（卡片即片段，来自影子语料）；
* **格 ＝ (域, 维度)**；`floor` 以下的格与空格分开列；
* 查不到域的边进 `unknown_domain`，**不许悄悄算进某一格**。

单位是**边数**——计划里写的是"卡片数"，这里如实标成边，不混账。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from block_director.knowledge import hypergraph as hg  # noqa: E402

#: 四个研究维度（用户原话里的四块）。
NARRATIVE = "行为动作情绪意图"
CAMERA = "镜头语言"
COMPOSITION = "构图"
IMPACT = "震动打击感"
#: 附加两块（声音与光）——它们是片子里同样强耦合、但不是用户点名的四块。
SOUND = "声音对白配乐"
LIGHT = "光"

DIMENSIONS: Tuple[str, ...] = (NARRATIVE, CAMERA, COMPOSITION, IMPACT, SOUND, LIGHT)

#: **维度 ← 边型**（唯一映射）。依据：每个边型的语义（见 `hypergraph.py` 的常量注释）。
DIMENSION_OF_TYPE: Dict[str, Tuple[str, ...]] = {
    NARRATIVE: (hg.EMOTION_PACK, hg.PERFORMANCE_PACK, hg.ACTION_BEAT, hg.INTENT_PACK,
                hg.TROPE),
    CAMERA: (hg.SHOT_PATTERN, hg.INTENT_PACK, hg.TRANSITION_PACK, hg.EDIT_RHYTHM,
             hg.AXIS_RULE),
    COMPOSITION: (hg.STAGING_PACK, hg.SHOT_PATTERN, hg.PROP_PACK),
    IMPACT: (hg.IMPACT_PACK, hg.ACTION_BEAT, hg.SOUND_PACK),
    SOUND: (hg.SOUND_PACK, hg.DIALOGUE_PACK, hg.MUSIC_PACK),
    LIGHT: (hg.LIGHT_PACK,),
}

#: **反查表**：`边型 → 它属于哪些维度`。由 `DIMENSION_OF_TYPE` 现算，
#: 所以两张表不可能各说各话（加边型只改一处）。
DIMENSIONS_OF_TYPE: Dict[str, Tuple[str, ...]] = {
    edge_type: tuple(dimension for dimension, types in DIMENSION_OF_TYPE.items()
                     if edge_type in types)
    for edge_type in hg.EDGE_TYPES
}


def load_edges(path: pathlib.Path) -> List[Dict]:
    out: List[Dict] = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def coverage(edges: Iterable[Dict], card_domain: Dict[str, str], *,
             floor: int = 50) -> Dict:
    """按 `(域, 维度)` 数格子。`card_domain` 是 `卡片 id → domain`。"""
    cells: Dict[Tuple[str, str], int] = collections.defaultdict(int)
    by_dimension: Dict[str, int] = collections.defaultdict(int)
    by_domain: Dict[str, int] = collections.defaultdict(int)
    unknown_domain = 0
    unmapped_type = 0
    total = 0
    for edge in edges:
        edge_type = str(edge.get("type") or "")
        dims = DIMENSIONS_OF_TYPE.get(edge_type)
        if not dims:
            unmapped_type += 1
            continue
        sources = [str(item) for item in (edge.get("sources") or ())]
        domains = {card_domain[source] for source in sources if source in card_domain}
        if not domains:
            unknown_domain += 1
            continue
        total += 1
        for dimension in dims:
            by_dimension[dimension] += 1
            for domain in domains:
                cells[(domain, dimension)] += 1
    for domain, _dimension in list(cells):
        by_domain[domain] = by_domain.get(domain, 0)
    for (domain, _dimension), count in cells.items():
        by_domain[domain] = max(by_domain.get(domain, 0), 0) + 0
    #: 域总数按**格上的域**汇总（一个域可能横跨多个维度）。
    domain_totals: Dict[str, int] = collections.defaultdict(int)
    for (domain, dimension), count in cells.items():
        domain_totals[domain] += count
    seen_domains = sorted({domain for domain, _dim in cells})
    all_cells = [(domain, dimension) for domain in seen_domains
                 for dimension in DIMENSIONS]
    empty_cells = [cell for cell in all_cells if cells.get(cell, 0) == 0]
    below_floor = [cell for cell in all_cells if 0 < cells.get(cell, 0) < floor]
    return {
        "generated_by": "tools/knowledge/coverage_matrix.py",
        "unit": "edges",
        "floor": floor,
        "edges_counted": total,
        "edges_unmapped_type": unmapped_type,
        "unknown_domain": unknown_domain,
        "dimensions": list(DIMENSIONS),
        "domains": seen_domains,
        "by_dimension": {name: by_dimension.get(name, 0) for name in DIMENSIONS},
        "by_domain": {name: domain_totals.get(name, 0) for name in seen_domains},
        #: Python 侧用**元组键**（`(域, 维度)`），写 JSON 时由调用方转字符串。
        "cells": {key: value for key, value in sorted(cells.items())},
        #: Python 侧保持**元组键**（写 JSON 时由调用方转字符串）。
        "empty_cells": empty_cells,
        "below_floor": below_floor,
        "empty_cell_pairs": empty_cells,
        "below_floor_pairs": below_floor,
        "all_dimensions_non_empty": all(
            by_dimension.get(name, 0) > 0 for name in DIMENSIONS),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="knowledge.coverage_matrix")
    parser.add_argument("--edges", required=True)
    parser.add_argument("--corpus", required=True, help="影子语料（供卡片→域）")
    parser.add_argument("--floor", type=int, default=50)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:  # noqa: PLC0415 - 延迟导入，避免把影子构建拖进本模块的加载链
        from tools.kb_fetch import build_shadow as bs  # type: ignore
    except ImportError:  # pragma: no cover
        from tools.kb_fetch import build_shadow as bs  # type: ignore
    cards = bs.segment_cards(pathlib.Path(args.corpus))
    card_domain = {card_id: str(card.get("domain") or "?")
                   for card_id, card in cards.items()}
    report = coverage(load_edges(pathlib.Path(args.edges)), card_domain,
                      floor=args.floor)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    serialisable = {key: value for key, value in report.items()
                    if not key.endswith("_pairs") and key != "cells"}
    serialisable["cells"] = {"%s|%s" % key: value
                             for key, value in report["cells"].items()}
    for key in ("empty_cells", "below_floor"):
        serialisable[key] = ["%s|%s" % cell for cell in report[key]]
    out.write_text(json.dumps(serialisable, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps({"overall": "pass", "edges_counted": report["edges_counted"],
                      "by_dimension": report["by_dimension"],
                      "by_domain": report["by_domain"],
                      "empty_cells": len(report["empty_cells"]),
                      "below_floor": len(report["below_floor"]),
                      "all_dimensions_non_empty":
                          report["all_dimensions_non_empty"],
                      "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
