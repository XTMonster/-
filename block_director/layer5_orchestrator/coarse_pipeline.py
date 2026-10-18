"""白模预演完整流程：粗排管线编排器（Ticket 05，bpy 侧）。

串起：剧本理解（SceneBrief）-> 粗编排参考 JSON -> BlockoutManifest ->
体块建场景 -> 低采样预览观察 -> 修正循环（处方改参考 JSON -> 重建 -> 再观察，
收敛或显式阻塞）-> 粗排 gate 通过 -> 冻结 coarse_world_baseline -> 分镜表。

粗排阶段任何 fail 都不得继续到细排/导出 final；每轮修正落 revision 留痕。
所有 bpy 调用延迟导入，保证模块可被纯层 import。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from block_director.contracts.blockout import approval_state_machine
from block_director.cinema.blockout import build_blockout_manifest
from block_director.cinema.coarse_loop import run_coarse_revision_loop
from block_director.cinema.pipeline_gates import (
    PipelinePhase,
    freeze_coarse_baseline,
)
from block_director.cinema.spatial_design import build_design_snapshot
from block_director.layer5_orchestrator.understand import (
    deterministic_brief,
)


def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _approve_manifest_to_frozen(manifest: Mapping[str, Any]) -> List[Dict]:
    """draft -> camera-approved -> frozen（纯函数，不落盘）。"""
    approved = approval_state_machine(
        "scene_01_blockout.blend", "global", None, "draft", manifest,
        approved_by="coarse-pipeline", target_state="camera-approved",
        approved_at="deterministic-replay")
    frozen = approval_state_machine(
        "scene_01_blockout.blend", "global", None, "camera-approved",
        manifest, approved_by="coarse-pipeline", target_state="frozen",
        approved_at="deterministic-replay")
    return [approved, frozen]


def run_coarse_pipeline(
    *,
    plan: Any,
    out_dir: Path | str,
    reference: Optional[Mapping[str, Any]] = None,
    script_text: str = "",
    brief: Any = None,
    cast_positions: Optional[Mapping[str, Any]] = None,
    scene_id: str = "",
    max_revisions: int = 3,
    fps: int = 24,
) -> Dict[str, Any]:
    """跑完整粗排管线，落盘全部产物，返回 pipeline_report。

    ``plan`` 支持 Plan 或 dict；``brief`` 缺省时用确定性理解
    （``deterministic_brief``，零 LLM）。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    #: 1) 剧本理解（Stage S）
    if brief is None:
        char_names: List[str] = []
        if isinstance(plan, Mapping):
            for s in plan.get("shots") or []:
                char_names.extend(str(n) for n in (s.get("characters") or []))
        else:
            for s in getattr(plan, "shots", None) or []:
                char_names.extend(str(n) for n
                                  in (getattr(s, "characters", None) or []))
        brief = deterministic_brief(parsed=None,
                                    characters=sorted(set(char_names)))

    #: 2) 粗编排参考世界坐标 JSON（单一真源；可注入已审阅/已修改的 JSON）
    if reference is None:
        reference = build_design_snapshot(
            brief=brief, plan=plan, cast_positions=cast_positions,
            scene_id=scene_id)
        reference = _attach_plan_shots(reference, plan)
    elif not reference.get("shots"):
        reference = _attach_plan_shots(reference, plan)
    _json_dump(reference, out / "coarse_world_reference.json")

    #: 3..6) blockout -> observe -> revise loop -> freeze
    manifest: Dict[str, Any] = {}
    last_report: Dict[str, Any] = {"verdict": "unresolved",
                                    "findings": [], "checks": []}

    def rebuild(ref: Mapping[str, Any]) -> None:
        """用最新参考 JSON 重建 manifest + 体块场景（bpy 延迟导入）。"""
        nonlocal manifest
        from block_director.layer3_engine.blockout_scene import (
            build_blockout_scene,
        )
        manifest = build_blockout_manifest(design=ref, plan=plan)
        build_blockout_scene(manifest, clear_scene=True)

    def observe(ref: Mapping[str, Any]) -> Dict[str, Any]:
        """重建 + 渲染预览 + 出粗排报告。"""
        nonlocal last_report
        from block_director.layer8_delivery.blockout_preview import (
            render_blockout_preview,
        )
        rebuild(ref)
        preview = render_blockout_preview(manifest, out)
        last_report = dict(preview["report"])
        return last_report

    #: 首次构建场景后进入修正循环
    rebuild(reference)
    outcome = run_coarse_revision_loop(
        reference=reference,
        report_loader=observe,
        rebuild=rebuild,
        max_revisions=int(max_revisions),
        fps=int(fps),
    )
    final_reference = outcome["reference"]
    final_report = outcome["report"]
    _json_dump(final_reference, out / "coarse_world_reference.json")
    _json_dump(final_report, out / "blockout_report.json")
    _json_dump(manifest, out / "blockout_manifest.json")

    coarse_ok = outcome["status"] == "approved"
    approvals: List[Dict[str, Any]] = []
    baseline: Dict[str, Any] | None = None
    if coarse_ok:
        approvals = _approve_manifest_to_frozen(manifest)
        baseline = freeze_coarse_baseline(
            reference=final_reference,
            manifest=manifest,
            report=final_report,
            approvals=approvals,
            approved_by="coarse-pipeline",
            approved_at="deterministic-replay")
        _json_dump(approvals,
                   out / "approval" / "blockout-approval.json")
        _json_dump(baseline, out / "coarse_world_baseline.json")

    phase = (PipelinePhase.COARSE_REFERENCE_READY
             if not coarse_ok
             else PipelinePhase.BASELINE_FROZEN)
    pipeline_report = {
        "schema_version": "coarse-pipeline-report/v1",
        "scene_id": str(scene_id or reference.get("scene_id") or ""),
        "phase": phase,
        "coarse_status": outcome["status"],
        "blocked_reason": outcome.get("blocked_reason") or "",
        "rounds": [
            {"round_no": r["round_no"],
             "verdict": r["report"].get("verdict"),
             "findings": len(r["report"].get("findings") or []),
             "prescriptions": r["prescriptions"]}
            for r in outcome["rounds"]
        ],
        "gates": {
            "coarse": "pass" if coarse_ok else "blocked",
            "baseline": ("frozen" if baseline else "missing"),
            "detail": "pending",
            "sequence": "pending",
            "final": "pending",
        },
        "artifacts": {
            "coarse_world_reference": str(out / "coarse_world_reference.json"),
            "blockout_manifest": str(out / "blockout_manifest.json"),
            "blockout_report": str(out / "blockout_report.json"),
            "baseline": str(out / "coarse_world_baseline.json")
            if baseline else None,
        },
    }
    _json_dump(pipeline_report, out / "coarse_pipeline_report.json")
    return pipeline_report


def _attach_plan_shots(reference: Mapping[str, Any],
                       plan: Any) -> Dict[str, Any]:
    """把 plan 的分镜语义层（shots[]）并入粗编排参考 JSON。

    build_design_snapshot 只产出空间层（characters/camera_intents），
    shots[]（镜号/时长/出场角色/动作）是处方与细排派生的必需语义层；
    参考 JSON 作为单一真源必须携带它。
    """
    import copy

    result = copy.deepcopy(dict(reference))
    if isinstance(plan, Mapping):
        result["shots"] = [dict(s) for s in plan.get("shots") or []]
    else:
        result["shots"] = [
            {k: getattr(s, k) for k in (
                "shot_id", "order", "intent", "duration_frames",
                "characters", "actions", "camera")
             if hasattr(s, k)}
            for s in getattr(plan, "shots", None) or []
        ]
    return result


__all__ = ["run_coarse_pipeline"]
