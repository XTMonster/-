"""Ticket 05：Blockout 检查点落盘（bpy 侧）。

粗排自检通过后把当前场景落成 .blend 检查点：全局
``scene_01_blockout.blend`` + 逐分镜 ``scene_sNN_blockout.blend``（可单独
审批与回滚）。保存后写一份 ``checkpoint_summary.json``（文件清单 + 字节数 +
帧范围），供审批与回滚引用。审批记录/分镜表/审批门的读写与判定在
``cinema.blockout_approval``（纯层）；本模块只做 bpy 依赖的保存动作。

确定性：同一 manifest + 场景两次保存产出相同的文件清单与字节数（.blend
内部时间戳不计入断言，其余逐位一致）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

import bpy

from ..contracts.blockout import (
    BLOCKOUT_APPROVAL_SCHEMA_VERSION,
    validate_blockout_manifest,
)
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("blockout-checkpoint")

#: 检查点目录名（相对证据根）。
CHECKPOINT_DIRNAME = "checkpoints"

#: 检查点摘要文件名。
CHECKPOINT_SUMMARY_FILENAME = "blockout_checkpoint_summary.json"


def _frame_range() -> List[int]:
    scene = bpy.context.scene
    return [int(scene.frame_start), int(scene.frame_end)]


def _save_checkpoint(filepath: Path) -> int:
    """把当前场景保存为 .blend，返回字节数。"""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    #: Blender 5.x 的 save_as_mainfile(copy=True) 在目标已存在时会尝试把旧
    #: 文件改名为 *.blend@ 备份，copy 模式下不允许 -> 报
    #: "Cannot change old file (file saved with @)"。检查点语义就是重跑覆盖
    #: 同一命名文件（manifest.checkpoints 声明的明确路径），这里先移除旧
    #: 文件再写，属于常规覆盖，不是破坏性删除。
    if filepath.exists():
        filepath.unlink()
    #: copy=True：不改变 bpy.data.filepath（脚本运行基准不被污染）。
    bpy.ops.wm.save_as_mainfile(
        filepath=filepath.as_posix(), copy=True, compress=False)
    if not filepath.exists():
        raise RuntimeError(f".blend 未生成：{filepath}")
    return int(filepath.stat().st_size)


@main_thread_only("save_blockout_checkpoints")
def save_blockout_checkpoints(
    manifest: Mapping[str, Any],
    out_dir: Path | str,
) -> Dict[str, Any]:
    """按 manifest.checkpoints 声明保存全局 + 逐分镜 .blend 检查点。

    ``clear_existing=True`` 语义由上层保证（每次粗排重建前清掉既有检查点
    目录）；本函数只新写不删（破坏性动作归调用方显式执行）。
    返回摘要：\n
    ``{checkpoints: [{id, file, bytes}], frame_range, count}``。
    """
    findings = validate_blockout_manifest(manifest)
    if findings:
        raise ValueError(
            f"manifest 结构校验失败，不保存检查点：{findings}")

    out_dir = Path(out_dir)
    checkpoint_dir = out_dir / CHECKPOINT_DIRNAME
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    saved: List[Dict[str, Any]] = []
    for checkpoint in manifest.get("checkpoints") or []:
        checkpoint_id = str(checkpoint.get("id") or "")
        if not checkpoint_id:
            continue
        filepath = checkpoint_dir / checkpoint_id
        size = _save_checkpoint(filepath)
        saved.append({
            "id": checkpoint_id,
            "scope": str(checkpoint.get("scope") or ""),
            "shot_id": checkpoint.get("shot_id"),
            "file": str(filepath),
            "bytes": size,
        })

    summary = {
        "schema_version": BLOCKOUT_APPROVAL_SCHEMA_VERSION,
        "count": len(saved),
        "frame_range": _frame_range(),
        "checkpoints": saved,
    }
    (out_dir / CHECKPOINT_SUMMARY_FILENAME).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    log.info("Blockout 检查点落盘：%d 个 .blend（帧 %s）",
             len(saved), summary["frame_range"])
    return summary


__all__ = [
    "save_blockout_checkpoints",
    "CHECKPOINT_DIRNAME",
    "CHECKPOINT_SUMMARY_FILENAME",
]
