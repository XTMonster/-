"""Ticket 04：Blockout 粗排自检报告生成器（纯层，不 import bpy）。

把 Blender 冒烟侧采到的数值证据（体块比例、构图分/遮挡、出入画、空墙、设计
vs 实测 diff）确定性折成版本化 ``BlockoutReport``，供审批与人工/执行 AI
视觉审查一并消费：

* ``checks[]``：逐项数值结论（check_id / 分数或布尔 / 阈值 / verdict）；
* ``findings[]``：硬伤（如相机对空墙 E_BLOCKOUT_EMPTY_WALL）；
* ``visual_states[]``：每镜每采样帧的渲染帧路径与是否已人工/执行 AI 查看。

判定语义：数值型 ``actual <= threshold`` -> pass（与 spatial_diff 同口径）；
空墙判据：主体投影面积近零或全被遮挡 -> finding。确定性：同一输入两次构建
逐位一致。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

#: 快照版本（契约演进时逐代升）。
BLOCKOUT_REPORT_SCHEMA = "blockout-report/v1"

#: 空墙硬伤 check_id（spec §决策：相机对准空墙不可静默放行）。
E_BLOCKOUT_EMPTY_WALL = "E_BLOCKOUT_EMPTY_WALL"

#: 自检阈值（与 composition.PASS_SCORE / spatial_diff 同源；数值单一真源）。
COMPOSITION_PASS = 80.0
VISIBLE_RATIO_MIN = 0.5        # 主体可见比例低于该值 -> 遮挡硬伤
ON_SCREEN_MIN = 0.05           # 主体在画面内面积占比低于该值 -> 空墙嫌疑
OFF_SCREEN_LABEL = "off_screen"  # 主体完全出画 -> 出入画 finding 类别


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def build_blockout_report(*, manifest: Mapping[str, Any],
                          per_shot: List[Mapping[str, Any]],
                          manifest_fingerprint: str = "",
                          notes: List[str] | None = None) -> Dict[str, Any]:
    """逐镜数值证据 -> BlockoutReport（确定性、可追溯）。

    ``per_shot`` 每项形状（由 bpy 冒烟侧填充，纯层只消费不生成）：
    ``{shot_id, composition_score, visible_ratio, on_screen_ratio,
    blocked, off_screen, design_diff, frames: [{frame, png}]}``。
    任何缺值 -> 对应 check verdict=unresolved（不猜）。
    """
    checks: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    visual_states: List[Dict[str, Any]] = []

    for shot in per_shot:
        shot_id = str(shot.get("shot_id") or "?")
        if shot.get("empty"):
            #: 空镜合法：无被摄主体，不适用构图/遮挡/出入画/空墙判据；
            #: 显式记为 pass，避免"无证据"误判成 fail（也不猜数值）。
            checks.append({
                "check_id": "empty_shot", "shot_id": shot_id,
                "actual": 0, "threshold": 0, "verdict": "pass",
                "note": "空镜：无被摄主体，豁免构图/遮挡/出入画判据",
            })
            for frame in shot.get("frames") or []:
                visual_states.append({
                    "shot_id": shot_id,
                    "frame": int(frame.get("frame") or 0),
                    "png": str(frame.get("png") or ""),
                    "reviewed": False,
                })
            continue

        comp = shot.get("composition_score")
        if comp is None:
            checks.append({"check_id": "composition",
                           "shot_id": shot_id, "actual": None,
                           "threshold": COMPOSITION_PASS,
                           "verdict": "unresolved"})
        else:
            checks.append({"check_id": "composition", "shot_id": shot_id,
                           "actual": round(float(comp), 4),
                           "threshold": COMPOSITION_PASS,
                           "verdict": "pass" if float(comp) >= COMPOSITION_PASS
                           else "fail"})

        visible = shot.get("visible_ratio")
        if visible is None:
            checks.append({"check_id": "occlusion", "shot_id": shot_id,
                           "actual": None, "threshold": VISIBLE_RATIO_MIN,
                           "verdict": "unresolved"})
        else:
            checks.append({"check_id": "occlusion", "shot_id": shot_id,
                           "actual": round(float(visible), 4),
                           "threshold": VISIBLE_RATIO_MIN,
                           "verdict": "pass"
                           if float(visible) >= VISIBLE_RATIO_MIN else "fail"})
            if float(visible) < VISIBLE_RATIO_MIN:
                findings.append({
                    "check_id": E_BLOCKOUT_EMPTY_WALL, "shot_id": shot_id,
                    "severity": "error",
                    "message": ("主体可见比例低于阈值，相机可能对准空墙/"
                                "被完全遮挡"),
                })

        on_screen = shot.get("on_screen_ratio")
        if on_screen is None:
            checks.append({"check_id": "on_screen", "shot_id": shot_id,
                           "actual": None, "threshold": ON_SCREEN_MIN,
                           "verdict": "unresolved"})
        else:
            checks.append({"check_id": "on_screen", "shot_id": shot_id,
                           "actual": round(float(on_screen), 4),
                           "threshold": ON_SCREEN_MIN,
                           "verdict": "pass"
                           if float(on_screen) >= ON_SCREEN_MIN else "fail"})
            if float(on_screen) < ON_SCREEN_MIN:
                #: 主体在画面内占比近零（含完全出画）-> 相机对准空墙；
                #: off_screen 只是附加观察，不降级这个硬伤。
                findings.append({
                    "check_id": E_BLOCKOUT_EMPTY_WALL, "shot_id": shot_id,
                    "severity": "error",
                    "message": "主体在画面内占比近零，疑似相机对准空墙",
                })

        if shot.get("off_screen"):
            findings.append({
                "check_id": OFF_SCREEN_LABEL, "shot_id": shot_id,
                "severity": "warning",
                "message": "主体完全出画（出入画 check）",
            })

        if "design_diff" in shot:
            diff = shot["design_diff"]
            checks.append({"check_id": "design_vs_observed",
                           "shot_id": shot_id,
                           "actual": diff.get("max_deviation_m")
                           if isinstance(diff, Mapping) else None,
                           "threshold": 0.3, "verdict": "pass"
                           if diff.get("max_deviation_m") is not None
                           and float(diff.get("max_deviation_m")) <= 0.3
                           else "fail" if diff.get("max_deviation_m") is not None
                           else "unresolved"})

        for frame in shot.get("frames") or []:
            visual_states.append({
                "shot_id": shot_id,
                "frame": int(frame.get("frame") or 0),
                "png": str(frame.get("png") or ""),
                "reviewed": False,
            })

    passed = all(c["verdict"] == "pass" for c in checks)
    return {
        "schema_version": BLOCKOUT_REPORT_SCHEMA,
        "manifest_fingerprint": str(manifest_fingerprint),
        "verdict": "pass" if passed and not
        [f for f in findings if f["severity"] == "error"] else "fail",
        "checks": checks,
        "findings": findings,
        "visual_states": visual_states,
        "notes": list(notes or []),
    }


__all__ = ["build_blockout_report", "BLOCKOUT_REPORT_SCHEMA",
           "E_BLOCKOUT_EMPTY_WALL", "COMPOSITION_PASS"]
