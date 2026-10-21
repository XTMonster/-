"""回溯三态与版本快照恢复（缺陷 B / U10，T6）。**纯计算，不依赖 bpy。**

U10 的三态裁定：**高分保留、低分回溯、过分数采用**——

* ``score > threshold`` → ``adopt``（过分数线就收，历史 best 更高也不拦）；
* 否则 ``score > best`` → ``new_high``（更新 best 版本快照，继续走）；
* 否则 ``score < best`` → ``revert``（回到最高分版本，继续走，不停生成）；
  ``score == best`` → ``tie``（评分打平不是新高，只累计无新高轮数）。

``revert_ops`` 把 ``runtime_world_state.json`` 的载荷转成**有序**恢复指令，
供 bpy 侧 ``revert_shot`` 工具消费；字段口径与 ``layer3_engine/world_state``
的采集一致（角色位置/朝向、相机位置/目标/焦距、道具位置/旋转）。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .quality import COMPOSITION_PASS_SCORE, composition_decision

WORLD_STATE_SCHEMA = "runtime-world/v1"


@dataclass(frozen=True)
class BacktrackDecision:
    """一次审核分数在回溯三态里的裁定。"""

    disposition: str                 # adopt | new_high | revert | tie
    best_score: float                # 裁定后的 best（adopt 时保留传入 best 语义）
    no_gain: int                     # 连续无新高轮数（adopt 归零）
    should_revert: bool              # 是否需要把场景回滚到 best 版本
    adopted: bool = False            # 是否达到"过分数采用"


def backtrack_three_state(
    score: float,
    *,
    best_score=None,
    no_gain: int = 0,
    threshold: Optional[float] = None,
    audit_passed: bool = True,
) -> BacktrackDecision:
    """按 U10 的三态对一次审核做裁定（门槛一字不动，默认 80）。

    ``audit_passed`` is independent from the composition score.  A score above
    the threshold can be adopted only when the complete audit passed; hard
    errors such as an invisible subject must still enter the no-gain path.
    The default keeps legacy pure-score callers source compatible.
    """
    score = float(score)
    no_gain = int(no_gain or 0)
    threshold = (COMPOSITION_PASS_SCORE if threshold is None
                 else float(threshold))
    if (
        audit_passed
        and composition_decision(score, threshold=threshold)["status"] == "pass"
    ):
        # 过分数采用：无论是否新高，合格版本收下并收尾（best 记录仅作审计）。
        return BacktrackDecision(disposition="adopt", best_score=score,
                                 no_gain=0, should_revert=False, adopted=True)
    if best_score is None or score > float(best_score):
        return BacktrackDecision(disposition="new_high", best_score=score,
                                 no_gain=0, should_revert=False)
    if score < float(best_score):
        return BacktrackDecision(disposition="revert",
                                 best_score=float(best_score),
                                 no_gain=no_gain + 1, should_revert=True)
    return BacktrackDecision(disposition="tie",
                             best_score=float(best_score),
                             no_gain=no_gain + 1, should_revert=False)


@dataclass(frozen=True)
class CoarseBacktrackDecision:
    """粗排门回溯裁定（计划级，与镜级三态同一语义）。"""

    disposition: str                 # adopt | new_high | revert | tie
    best_score: float                # 裁定后的 best（adopt 时 = 本次分数）
    no_gain: int                     # 连续无新高轮数
    should_revert: bool              # True = 不采用本次，保留 best 版本
    adopted: bool = False            # 粗排门通过 = 过线采用


def coarse_plan_backtrack(score: float, *, best_score=None, no_gain: int = 0,
                          gate_ready: bool = False) -> CoarseBacktrackDecision:
    """粗排门回溯裁定：``gate_ready`` 即过线采用；否则按分数三态。

    R2 真跑 20261020-market-real-final3：粗排门失败（拍对象 unresolved）
    直接终止整个运行，没有"回到规划重来"的回路。本函数把 U10 三态套到
    计划级：门过 -> adopt（过分数采用）；分数高于 best -> new_high（高分
    保留）；低于 best -> revert（低分回溯，best 不替换）；打平 -> tie。
    分数约定：越高越好（如 ``-Σ 每轮 error findings``），调用方注入。
    """
    score = float(score)
    no_gain = int(no_gain or 0)
    if gate_ready:
        return CoarseBacktrackDecision(
            disposition="adopt", best_score=score, no_gain=0,
            should_revert=False, adopted=True)
    if best_score is None or score > float(best_score):
        return CoarseBacktrackDecision(
            disposition="new_high", best_score=score, no_gain=0,
            should_revert=False)
    if score < float(best_score):
        return CoarseBacktrackDecision(
            disposition="revert", best_score=float(best_score),
            no_gain=no_gain + 1, should_revert=True)
    return CoarseBacktrackDecision(
        disposition="tie", best_score=float(best_score),
        no_gain=no_gain + 1, should_revert=False)


def _require_world_state(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("最佳快照必须是 runtime-world/v1 载荷对象")
    if not isinstance(payload.get("characters", None), dict):
        raise ValueError("最佳快照缺少 characters 映射")
    if not isinstance(payload.get("cameras", None), dict):
        raise ValueError("最佳快照缺少 cameras 映射")
    return payload


def revert_ops(payload: Any) -> List[Dict[str, Any]]:
    """把世界状态快照转成有序恢复指令（角色→相机→道具，字段显式）。"""
    payload = _require_world_state(payload)
    ops: List[Dict[str, Any]] = []
    for cid in sorted(payload.get("characters", {})):
        entry = payload["characters"][cid]
        ops.append({
            "kind": "character", "id": str(cid),
            "position": [float(v) for v in entry.get("position", [])],
            "facing": [float(v) for v in entry.get("facing", [])],
        })
    for sid in sorted(payload.get("cameras", {})):
        entry = payload["cameras"][sid]
        ops.append({
            "kind": "camera", "id": str(sid),
            "position": [float(v) for v in entry.get("position", [])],
            "target": [float(v) for v in entry.get("target", [])],
            "lens_mm": float(entry.get("lens_mm", 50.0)),
        })
    for pid in sorted(payload.get("props", {})):
        entry = payload["props"][pid]
        ops.append({
            "kind": "prop", "id": str(pid),
            "position": [float(v) for v in entry.get("position", [])],
            "rotation_z": float(entry.get("rotation_z", 0.0)),
        })
    return ops


def best_snapshot(payload: Any) -> Dict[str, Any]:
    """深拷贝一份世界状态载荷作为最佳版本快照（可序列化、可恢复）。"""
    _require_world_state(payload)
    return copy.deepcopy(payload)


__all__ = [
    "BACKTRACK_DISPOSITIONS",
    "BacktrackDecision",
    "CoarseBacktrackDecision",
    "backtrack_three_state",
    "coarse_plan_backtrack",
    "best_snapshot",
    "revert_ops",
]


#: 三态闭集（审计/提示用）。置于 __all__ 之后避免循环引用问题。
BACKTRACK_DISPOSITIONS = ("adopt", "new_high", "revert", "tie")
