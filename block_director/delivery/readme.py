"""交付 README 的纯内容组装；GUI、headless 与测试共用，不依赖 bpy。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .depth import depth_range_note
from ..layer5_orchestrator.rhythm_reading import rhythm_readings

#: 张力 1–5 的 ASCII 弧线字形（由低到高）。
TENSION_GLYPHS = {1: ".", 2: "-", 3: "=", 4: "#", 5: "@"}
#: 没有节奏弧数据的那一格（与五个张力字形都不冲突）。
MISSING_TENSION_GLYPH = "_"


def tension_glyph(tension: Any) -> str:
    """张力 → 一个 ASCII 字形；非 1–5 整数（含 None/bool）→ 无数据字形。"""
    if isinstance(tension, bool) or not isinstance(tension, int):
        return MISSING_TENSION_GLYPH
    return TENSION_GLYPHS.get(tension, MISSING_TENSION_GLYPH)


def rhythm_arc_line(shots: Sequence[Dict[str, Any]]) -> str:
    """每镜一格的 ASCII 弧线（与 ``shots.json`` 的 ``rhythm.tension`` 同源）。"""
    return "".join(tension_glyph((shot.get("rhythm") or {}).get("tension"))
                   for shot in shots)


def rhythm_section_lines(manifest: Dict[str, Any],
                         rhythm_reading: Optional[Dict[str, Any]] = None
                         ) -> List[str]:
    """README 的节奏段（FR-B5）：ASL、镜长 CV、单调性 info、ASCII 弧线、时长表。

    没传 ``rhythm_reading`` 时用 :func:`rhythm_readings` 从 manifest 的
    ``duration_seconds`` 重算——与审计事件同源同值；传了就逐字用事件读数。
    时长与张力两列直接抄 manifest，保证 README 与 ``shots.json`` 字段对拍一致。
    """
    shots = list(manifest.get("shots") or [])
    readings = (dict(rhythm_reading) if rhythm_reading else
                rhythm_readings([float(shot.get("duration_seconds") or 0.0)
                                 for shot in shots]))
    lines = [
        "## 节奏",
        "",
        f"- 平均镜长（ASL）：{float(readings.get('asl_s') or 0.0):.2f} 秒",
        f"- 镜长变异系数（CV）：{float(readings.get('duration_cv') or 0.0):.4f}",
    ]
    if readings.get("monotony"):
        lines.append("- 单调性：全片镜长一致（info 级提示，"
                     "节奏是创作选择，仅供参考，不设门）")
    lines.extend([
        f"- 节奏弧线：`{rhythm_arc_line(shots)}`"
        "（每格一镜：`.`/`-`/`=`/`#`/`@` = 张力 1–5，`_` = 无数据）",
        "- 每镜时长：",
        "",
        "| 镜头 | 时长（秒） | 张力 |",
        "| --- | ---: | ---: |",
    ])
    for shot in shots:
        duration = float(shot.get("duration_seconds") or 0.0)
        tension = (shot.get("rhythm") or {}).get("tension")
        tension_text = (str(int(tension))
                        if isinstance(tension, int)
                        and not isinstance(tension, bool) else "—")
        lines.append(f"| {shot['shot_id']} | {duration} | {tension_text} |")
    lines.append("")
    return lines


def render_readme(manifest: Dict[str, Any], *, out_dir: Path,
                  warnings: Sequence[str] = (),
                  rhythm_reading: Optional[Dict[str, Any]] = None,
                  label_overlap_report: Optional[Dict[str, Any]] = None) -> str:
    """按真实 manifest 与已生成文件渲染交付说明，不读引擎状态。"""
    folder = Path(out_dir)
    width, height = manifest["resolution"]
    lines = [
        f"# {manifest['project']} — 白模预演交付包",
        "",
        f"- 分辨率：{width}×{height} @ {manifest['fps']}fps",
        f"- 镜头数：{len(manifest['shots'])}，总时长 "
        f"{round(manifest['total_frames'] / manifest['fps'], 2)} 秒",
        f"- 生成时间：{manifest['generated_at']}",
        "",
        "## 怎么用",
        "",
        "1. 取 `blockout_<shot>.mp4` 作为**参考视频**（结构 / 机位 / 节奏）；",
        "2. 取 `first_frames/<shot>.png` 作为**输入图**（图生视频）；",
        "3. 取 `prompts.md` 里对应镜头的 Prompt 作为**提示词**。",
        "",
        "> 参考视频里带白字黑描边的角色标签，便于审阅；"
        "`first_frames/` 与 depth 序列**刻意不带标签**，"
        "避免标签被下游视频模型当成画面内容学走。",
        "",
    ]
    if (folder / "camera_traj.json").exists():
        lines.insert(-1, "4. `camera_traj.json` 提供逐帧相机内外参，"
                         "可喂给相机可控的视频生成模型。")
        lines.append("")
    if (folder / "blockout_full.mp4").exists():
        lines.insert(-1, "5. `blockout_full.mp4` 是各镜按顺序接成的全片，"
                         "适合一次性喂给视频模型。")
        lines.append("")
    #: v1.6 D3（FR-B5）：节奏段。读数与 shots.json 的 rhythm 字段同源，
    #: 保证 README 与交付清单字段对拍一致。
    lines.extend(rhythm_section_lines(manifest, rhythm_reading))
    #: v1.6 A7（D-19）：标签全帧自检汇总（TDD §7「事件（交付 README 汇总）」）。
    #: 只有确实还有重叠帧才写这段；空态/缺字段一律静默，不把空态当数据渲染。
    overlap = dict(label_overlap_report or {})
    overlap_frames = [int(frame) for frame in overlap.get("overlap_frames") or []]
    if overlap_frames:
        limit = float(overlap.get("limit") or 0.05)
        max_ratio = float(overlap.get("max_overlap_ratio") or 0.0)
        shown = ", ".join(str(frame) for frame in overlap_frames[:8])
        if len(overlap_frames) > 8:
            shown += " …"
        lines.extend([
            "## 标签全帧自检",
            "",
            f"- 仍有 {len(overlap_frames)} 帧标签两两交叠超过 "
            f"{limit * 100:g}%（覆盖全帧，采样帧与插值帧同判）",
            f"- 最大交叠率：{max_ratio:.1%}",
            f"- 重叠帧：{shown}",
            "",
        ])
    if any(path.name.startswith("depth_shot_") and path.is_dir()
           for path in folder.iterdir()):
        lines.extend(["## 深度序列", "", depth_range_note(), ""])
    review_shots = [shot for shot in manifest["shots"]
                    if shot.get("needs_review")]
    if review_shots:
        lines.extend([
            "## 待人工复核", "",
            f"以下 {len(review_shots)} 个镜头在运行中被模型请求自我审核：",
            "",
        ])
        for shot in review_shots:
            count = shot.get("review_request_count")
            detail = f"登记 {count} 次" if count is not None else "登记次数未记录"
            lines.append(f"- {shot['shot_id']}：{detail}")
        lines.append("")
    if warnings:
        lines.extend(["## 告警", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    return "\n".join(lines)
