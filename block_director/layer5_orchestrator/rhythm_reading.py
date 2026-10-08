"""节奏读数（v1.6 D3，FR-B2 / FR-B5；TDD §3.6）。

计划确认后产出一条 ``rhythm_reading`` 审计事件的**纯计算层**。读数只是诊断：
没有 pass/fail，没有 repair 触发器，也不改任何判据（红线 R-5——节奏是创作选择，
不是规则）。跳切风险在这里**只计数**：逐镜头对的 ``jump_cut_risk`` 几何告警归
FR-C6 的 :func:`~block_director.cinema.frustum_metrics.cut_level_checks`（本模块
直接调用它，阈值复用同一份 ``GuardConfig``，不重写第二份）。

禁止 import bpy。
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from ..cinema.frustum_metrics import GuardConfig, cut_level_checks
from ..contracts.guard import Confidence, GuardWarning, Severity

#: 单调性口径（卡 D3 钉死）：全片镜长标准差 < 1e-6。
MONOTONY_STDEV_EPS = 1e-6

#: 读数类型：``asl_s``/``duration_cv`` 是 float，``monotony`` 是 bool，
#: ``jump_cut_risks`` 是 int。
Reading = Dict[str, Union[float, bool, int]]


def rhythm_readings(
        durations_s: Sequence[float], *,
        shot_summaries: Optional[Sequence[Any]] = None,
        guard_config: Optional[GuardConfig] = None) -> Reading:
    """把全片镜长折成一条节奏读数（纯函数，同输入同输出）。

    返回键与 ``contracts/audit.py::V16_EVENT_FIELDS["rhythm_reading"]`` **逐键
    一致**，可直接作为该审计事件的事件体：

    * ``asl_s``：平均镜长（秒）；
    * ``duration_cv``：镜长变异系数（总体标准差 ÷ 平均镜长；均值为 0 时为 0）；
    * ``monotony``：全片镜长标准差 < :data:`MONOTONY_STDEV_EPS`（空输入为 False）；
    * ``jump_cut_risks``：相邻镜跳切风险的**计数**。给了 ``shot_summaries``
      （``ShotSummary`` 序列）就交给 FR-C6 的 ``cut_level_checks`` 用
      ``guard_config`` 的 ``jump_cut_*`` 阈值判定后数 ``jump_cut_risk`` 条数；
      没给就是 0——这里**不产生**逐镜头对告警（那是 FR-C6 的职责）。
    """
    durations = [float(value) for value in (durations_s or [])]
    if not durations:
        return {"asl_s": 0.0, "duration_cv": 0.0,
                "monotony": False, "jump_cut_risks": 0}
    asl_s = statistics.fmean(durations)
    stdev = statistics.pstdev(durations)          # 总体标准差（"全片"口径）
    duration_cv = (stdev / asl_s) if asl_s else 0.0
    monotony = stdev < MONOTONY_STDEV_EPS
    jump_cut_risks = 0
    if shot_summaries is not None:
        cfg = guard_config if guard_config is not None else GuardConfig()
        found = cut_level_checks(list(shot_summaries), cfg)
        jump_cut_risks = sum(
            1 for item in found if item.type == "jump_cut_risk")
    return {"asl_s": asl_s, "duration_cv": duration_cv,
            "monotony": bool(monotony), "jump_cut_risks": int(jump_cut_risks)}


def pace_monotony_note(readings: Mapping[str, Any]) -> Optional[GuardWarning]:
    """``monotony=True`` ⇒ 一条 info 级 ``pace_monotony`` 提示；否则 ``None``。

    信息级、不是门、不是修复触发器（severity 恒为 INFO；红线 R-5）。证据只带
    读数本身，不带任何 pass/fail 结论。
    """
    if not readings or not readings.get("monotony"):
        return None
    return GuardWarning(
        shot_id="scene",
        frame_range=(0, 0),
        type="pace_monotony",
        subject="scene",
        evidence={"asl_s": readings.get("asl_s"),
                  "duration_cv": readings.get("duration_cv")},
        severity=Severity.INFO,
        confidence=Confidence.HIGH,
        suggestion_hint="全片镜长相同：节奏是创作选择，仅供参考（info，不设门）",
    )


__all__ = [
    "MONOTONY_STDEV_EPS",
    "rhythm_readings",
    "pace_monotony_note",
]
