"""Ticket 05：Blockout 审批记录落盘/读回与审批门（纯层，不 import bpy）。

检查点保存本身要 bpy（写 ``.blend``），但审批记录与分镜表的**读写与判定**
不需要：落 ``approval/blockout-approval.json``（顺序 = 事件顺序，确定性可
重放）、分镜表 ``shot_table.json``（与 manifest.shot_table 逐位一致），并在
已批准（camera-approved/frozen）基准被改机位/走位时产出
``E_BLOCKOUT_APPROVAL_REQUIRED`` finding——不静默放行。

确定性：同一记录列表两次落盘逐位一致；读回与写入一致；分镜表与 manifest
逐位一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from ..contracts.blockout import (
    E_BLOCKOUT_APPROVAL_REQUIRED,
    approval_required_findings,
    approval_state_machine,
)

#: 审批记录目录（相对证据根）。
APPROVAL_DIRNAME = "approval"

#: 审批记录文件名（单一文件、顺序 = 事件顺序）。
APPROVAL_FILENAME = "blockout-approval.json"

#: 分镜表文件名（与 manifest.shot_table 逐位一致）。
SHOT_TABLE_FILENAME = "shot_table.json"


def write_approval_records(records: Sequence[Mapping[str, Any]],
                           out_dir: Path | str) -> List[Dict[str, Any]]:
    """把审批记录列表确定性落盘，返回读回的内容（逐位一致断言用）。"""
    out_dir = Path(out_dir)
    approval_dir = out_dir / APPROVAL_DIRNAME
    approval_dir.mkdir(parents=True, exist_ok=True)
    path = approval_dir / APPROVAL_FILENAME
    payload = [dict(record) for record in records]
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    return read_approval_records(out_dir)


def read_approval_records(out_dir: Path | str) -> List[Dict[str, Any]]:
    """读回审批记录；文件缺失/坏 JSON 报空表（诚实标缺，不猜不伪造）。"""
    path = Path(out_dir) / APPROVAL_DIRNAME / APPROVAL_FILENAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [dict(item) for item in data if isinstance(item, dict)]


def write_shot_table(manifest: Mapping[str, Any],
                     out_dir: Path | str) -> List[Dict[str, Any]]:
    """分镜表 JSON 落盘：与 manifest.shot_table 逐位一致（单一真源）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [dict(row) for row in (manifest.get("shot_table") or [])]
    (out_dir / SHOT_TABLE_FILENAME).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    return rows


def gate_findings(
    records: Sequence[Mapping[str, Any]],
    candidate: Mapping[str, Any],
) -> Dict[str, Any]:
    """审批门：对每条已批准（camera-approved/frozen）记录跑机位指纹比对。

    返回 ``{blocked, findings}``：任何一条已批准基准被改机位/走位 ->
    ``blocked=True`` 并带 ``E_BLOCKOUT_APPROVAL_REQUIRED`` finding（每条
    一个）；未改 -> 空表、不阻塞。判定和阈值与 contracts 单一真源同源。
    """
    findings: List[Dict[str, Any]] = []
    for record in records:
        findings.extend(approval_required_findings(record, candidate))
    return {"blocked": bool(findings), "findings": findings}


def append_approval(
    records: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    out_dir: Path | str,
    *,
    checkpoint_id: str,
    scope: str,
    shot_id: str | None,
    current_state: str,
    approved_by: str,
    target_state: str = "camera-approved",
) -> Dict[str, Any]:
    """在清单上推进审批状态并追加一条审批记录（顺序 = 事件顺序）。

    非法迁移抛 ``ValueError``（不静默放行）；成功返回新记录。
    """
    record = approval_state_machine(
        checkpoint_id, scope, shot_id, current_state, manifest,
        approved_by=approved_by, target_state=target_state)
    updated = [dict(item) for item in records] + [record]
    write_approval_records(updated, out_dir)
    return record


def evaluate_gate(
    report: Mapping[str, Any],
    approvals: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    """粗排 gate：报告无 error finding 且已批准基准未漂移才放行。

    ``gate.passed`` 为 True 当且仅当：
    1. ``report["verdict"] == "pass"``（数值+空墙判据全绿，error finding 为 0）；
    2. 存在审批记录（camera-approved/frozen）且其 cameras 指纹与当前
       manifest 一致（``approval_required_findings`` 为空——已批准机位/走位
       未被改）。

    返回 ``{passed, reasons}``：``reasons`` 列出每个未满足条件的可执行解释，
    供执行 AI 修复回路消费。不猜、不降级：缺审批、报告红、基准漂移都
    判 blocked。
    """
    reasons: List[str] = []
    if str(report.get("verdict")) != "pass":
        errors = [f for f in (report.get("findings") or [])
                  if f.get("severity") == "error"]
        reasons.append(
            f"粗排报告非 pass（{len(errors)} 条 error finding）")
    if not approvals:
        reasons.append("无审批记录：检查点未 camera-approved/frozen")
    else:
        latest = approvals[-1]
        drift = approval_required_findings(latest, manifest)
        if drift:
            reasons.append(
                "已批准机位/走位被修改，必须重新走 camera-approved 审批流程")
    return {"passed": not reasons, "reasons": reasons}


__all__ = [
    "APPROVAL_DIRNAME",
    "APPROVAL_FILENAME",
    "SHOT_TABLE_FILENAME",
    "E_BLOCKOUT_APPROVAL_REQUIRED",
    "write_approval_records",
    "read_approval_records",
    "write_shot_table",
    "gate_findings",
    "append_approval",
    "evaluate_gate",
]
