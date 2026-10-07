"""多样性度量（执行文档 v1.5 PRD §6 / 卡 P6-T2）。

同一份剧本**生成 N 次**，回答"AI 拍得僵不僵"这个问题。三个互补的维度：

1. **景别序列编辑距离**：把每次生成的 ``shot_type`` 序列当成一个字符串，
   两两算 Levenshtein 距离再取归一化平均。抓"结构上是不是每次都一样"。
2. **运镜分布卡方**：把 N 次运行的运镜直方图与它们的平均分布做卡方，
   抓"运镜选择是不是退化成查表"。
3. **机位侧向符号翻转率**：逐镜比 N 次运行的 ``axis.side_sign``，
   抓"机位是不是永远待在同一侧"。

纯函数、零依赖（不 import bpy、不 import pytest）。输入是**计划或 shots.json
的 dict 形**，因此既能对离线计划跑，也能对交付物跑（可复算）。

用法::

    python tools/diversity_score.py runs/a/shots.json runs/b/shots.json ...
    python tools/diversity_score.py runs/a/shots.json    # 单份（自比 = 0）
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _shots(payload) -> List[dict]:
    """从计划 dict / shots.json dict 里取镜头列表（两种形状都认）。"""
    if isinstance(payload, dict):
        for key in ("shots", "plan"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("shots")
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def shot_type_sequence(payload) -> List[str]:
    return [str(shot.get("shot_type") or "") for shot in _shots(payload)]


def movement_histogram(payload) -> Counter:
    """运镜直方图——**两种形状都要认**。

    `shots.json`（`delivery/manifest.py`）把 `movements[]` 放在**镜头级**，元素键是
    `kind`；计划（`contracts/plan.py` 的 `camera{}`）把它放在 `camera.movements[]`，
    元素键是 `type`。2026-10-07 实测：只认计划那一种时，拿三份冻结工程的
    `shots.json` 跑出来 `kinds = 0` —— "运镜退化成查表"这一栏被**结构性地**
    量成 0，与"三次生成的运镜完全一样"读起来一模一样。这里两种形状都读。
    """
    counts: Counter = Counter()
    for shot in _shots(payload):
        raw = shot.get("movements")
        if not isinstance(raw, list):
            camera = shot.get("camera") or {}
            raw = camera.get("movements") if isinstance(camera, dict) else None
        for item in (raw or []):
            kind = (str(item.get("kind") or item.get("type") or "")
                    if isinstance(item, dict)
                    else str(item or ""))
            if kind:
                counts[kind] += 1
    return counts


def axis_signs(payload) -> List[int]:
    signs: List[int] = []
    for shot in _shots(payload):
        axis = shot.get("axis") or {}
        try:
            signs.append(int(axis.get("side_sign") or 0))
        except (TypeError, ValueError):
            signs.append(0)
    return signs


def levenshtein(left: Sequence[str], right: Sequence[str]) -> int:
    """标准动态规划编辑距离（插入/删除/替换代价都是 1）。"""
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, token in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            cost = 0 if token == other else 1
            current.append(min(previous[j] + 1,
                               current[j - 1] + 1,
                               previous[j - 1] + cost))
        previous = current
    return previous[-1]


def sequence_edit_distance(sequences: Sequence[Sequence[str]]) -> Dict[str, float]:
    """N 条景别序列的两两编辑距离：返回 ``sum`` / ``mean`` / ``normalised``。

    ``normalised`` 的分母是"两条序列里更长的那条的长度"，因此 [0,1] 可比。
    序列少于 2 条、或所有序列都为空时返回 0（没有可比对，不是"很僵"）。
    """
    pairs = [(a, b) for index, a in enumerate(sequences)
             for b in sequences[index + 1:]]
    if not pairs:
        return {"pairs": 0, "sum": 0.0, "mean": 0.0, "normalised": 0.0}
    total = 0
    normalised = 0.0
    for left, right in pairs:
        distance = levenshtein(list(left), list(right))
        total += distance
        span = max(len(left), len(right))
        normalised += (distance / span) if span else 0.0
    return {"pairs": len(pairs), "sum": float(total),
            "mean": total / len(pairs),
            "normalised": normalised / len(pairs)}


def movement_chi_square(histograms: Sequence[Counter]) -> Dict[str, float]:
    """运镜分布卡方：实际 vs 平均分布的卡方统计量与自由度。

    每个取值在每个运行里都算一格（缺失记 0），因此自由度 = (取值数 − 1) ×
    (运行数 − 1)。运行数 < 2 或取值数 < 2 时返回 0（没有"分布"可言）。
    """
    runs = len(histograms)
    kinds = sorted({kind for histogram in histograms for kind in histogram})
    if runs < 2 or len(kinds) < 2:
        return {"statistic": 0.0, "dof": 0, "kinds": len(kinds), "runs": runs}
    table = {kind: [histogram.get(kind, 0) for histogram in histograms]
             for kind in kinds}
    grand = sum(sum(row) for row in table.values())
    if grand == 0:
        return {"statistic": 0.0, "dof": 0, "kinds": len(kinds), "runs": runs}
    statistic = 0.0
    for kind in kinds:
        row = table[kind]
        row_total = sum(row)
        for value in row:
            expected = row_total / runs
            if expected > 0:
                statistic += (value - expected) ** 2 / expected
    dof = (len(kinds) - 1) * (runs - 1)
    return {"statistic": round(statistic, 6), "dof": dof,
            "kinds": len(kinds), "runs": runs}


def axis_flip_rate(sign_lists: Sequence[Sequence[int]]) -> Dict[str, float]:
    """机位侧向符号翻转率：任一运行与其它运行符号不同的镜头占比。

    只在所有运行的镜数一致时逐镜比；不一致就按可达的最短长度比（如实记
    ``comparable_shots``）。0 表示"每次都在同一侧"。
    """
    if len(sign_lists) < 2:
        return {"comparable_shots": 0, "flipped_shots": 0, "rate": 0.0}
    span = min(len(row) for row in sign_lists)
    flipped = 0
    for index in range(span):
        column = {row[index] for row in sign_lists}
        if len(column) > 1:
            flipped += 1
    return {"comparable_shots": span, "flipped_shots": flipped,
            "rate": (flipped / span) if span else 0.0}


def diversity_report(payloads: Sequence[dict]) -> Dict[str, object]:
    """N 份运行的综合读数。``runs < 2`` 时各维度都是 0（不可比，不是"很僵"）。

    另给一栏 ``measurable``：某个维度**结构上量不出来**时（例如成片早于
    `movements` / `axis.side_sign` 字段落盘），它的 0 分**不是**"很僵"的证据。
    读账的人必须能一眼分开"量了，是 0"与"根本没得量"。
    """
    sequences = [shot_type_sequence(payload) for payload in payloads]
    histograms = [movement_histogram(payload) for payload in payloads]
    signs = [axis_signs(payload) for payload in payloads]
    kinds = len({kind for histogram in histograms for kind in histogram})
    signs_seen = any(sign != 0 for row in signs for sign in row)
    return {
        "runs": len(payloads),
        "shot_counts": [len(sequence) for sequence in sequences],
        "shot_type_edit_distance": sequence_edit_distance(sequences),
        "movement_chi_square": movement_chi_square(histograms),
        "axis_flip": axis_flip_rate(signs),
        "measurable": {
            "shot_type": len(payloads) >= 2 and any(sequences),
            "movement": kinds >= 2,
            "axis": signs_seen,
        },
    }


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str]) -> int:
    paths = [Path(item) for item in argv if not item.startswith("-")]
    if not paths:
        print("用法：python tools/diversity_score.py <shots.json> [...]")
        return 2
    payloads = [_load(path) for path in paths]
    report = diversity_report(payloads)
    report["inputs"] = [str(path) for path in paths]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
