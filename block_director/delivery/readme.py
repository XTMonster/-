"""交付 README 的纯内容组装；GUI、headless 与测试共用，不依赖 bpy。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence

from .depth import depth_range_note


def render_readme(manifest: Dict[str, Any], *, out_dir: Path,
                  warnings: Sequence[str] = ()) -> str:
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
