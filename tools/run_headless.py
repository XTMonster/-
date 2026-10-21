"""在 Blender 内 headless 运行一次预演（Phase 0：空转链路端到端）。

用法：
  blender --background --factory-startup --python tools/run_headless.py -- --offline
  blender --background --python tools/run_headless.py -- --script fixtures/x.fountain --out E:\\tmp

输出：一行 ``BLOCKDIRECTOR_RESULT {json}`` 与退出码（0 = DONE，1 = 其他）。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _crowd_from_script(parsed, crowd_config):
    """分镜表里写了群众才生成群众代理（v1.3 §3.6）。"""
    if parsed is None or crowd_config is None:
        return []
    from block_director.contracts.cast import crowd_from_script

    # v1.4 X17：``crowd.enabled`` 三态直接透传（None = 按剧本声明）。
    return crowd_from_script(parsed, enabled=crowd_config.enabled,
                             max_instances=int(crowd_config.max_instances),
                             mode=str(crowd_config.mode),
                             seed=int(crowd_config.seed))


def _export_report(plan_obj, summary, config, out_dir, crowd, parsed,
                   concat_plan=None):
    """§15 的一条命令导出（完整包或按镜头过滤后的子集共用同一段）。"""
    from block_director.layer8_delivery import export_project
    from block_director.layer5_orchestrator.headless_runner import (
        brief_from_summary,
    )

    return export_project(
        plan_obj, build_summary=summary.get("build"), out_dir=out_dir,
        config=config.delivery,
        brief=brief_from_summary(summary),
        compliance=summary.get("compliance"),
        llm_calls=int(summary.get("llm_calls") or 0),
        #: §3.3 的契约字段：`shots.json.retrieval_calls` 必须是**这一次运行**
        #: 的检索调用数。此前 headless 这条路一个都不传（只有 `run_export.py`
        #: 与 UI 面板传），于是每次真实运行写出来的都是 0——实测 2026-10-03：
        #: `knowledge.retrieval_calls = 7` 而顶层写着 0，
        #: `tests/test_manifest_fields.py` 现在有一条契约断言钉住
        #: "传了 llm_calls 就必须传 retrieval_calls"。
        retrieval_calls=int(summary.get("retrieval_calls") or 0),
        crowd=crowd,
        parsed=parsed,
        timing_overrides=summary.get("timing_overrides"),
        action_conflicts=(summary.get("build") or {}).get("action_conflicts"),
        audit_pass_rate=summary.get("audit_pass_rate"),
        knowledge_provenance=summary.get("knowledge_provenance"),
        #: 交付清单自带索引代际（§4.1b 的 Q5 只在真实运行上判，而
        #: "这份运行是哪一代索引"必须能从证据文件本身读出来）。
        knowledge=summary.get("knowledge"),
        review_requests=summary.get("self_review_requests"),
        #: 空间尺观测（Ticket 06）：优先带 driver.snapshot() 折出的 v2 文档；
        #: 不可用时由运行摘要折出计划级处方/测量参数（交付层组装）。
        **(_ruler_export_args(summary)),
        #: 空间理解快照（Ticket 08）：设计/观测/diff 三份产物随摘要直传，
        #: 缺省 None（零形状差）。
        **(spatial_export_args(summary)),
        #: 缺陷 D / T8（U1）：单镜 fail 后继续，收尾交付带失败清单；
        #: 已过镜照常渲染，fail 镜也以最佳版本出片并标记 failed（U6/U1：
        #: 白模预演视频一定要生成；出片≠通过）。没有失败镜时 None（零形状差）。
        failures=summary.get("failures"),
        #: R2-D1：resume 的子集导出也把**完整计划**交给 concat，让全片拼接
        #: 含全部已交付 mp4（前段不再丢失）。
        concat_plan=concat_plan,
        project=plan_obj.scene_heading or "BlockDirector")


def spatial_export_args(summary):
    """从运行摘要折出 ``export_project`` 的空间快照参数（Ticket 08 兜底）。"""
    from block_director.layer5_orchestrator.headless_runner import (
        spatial_export_args as collect,
    )

    return collect(summary)


def _ruler_export_args(summary):
    """从运行摘要折出 ``export_project`` 的空间尺参数（Ticket 06 兜底）。"""
    from block_director.layer5_orchestrator.headless_runner import (
        ruler_evidence_from_summary,
    )

    ruler_observation = summary.get("ruler_observation")
    if ruler_observation is not None:
        return {"ruler_observation": ruler_observation}
    return ruler_evidence_from_summary(summary)


def _resume_state_path(candidate) -> Path:
    """``--resume`` 的参数：目录就取 ``<dir>/resume_state.json``，文件原样用。"""
    path = Path(candidate)
    if path.is_dir():
        from block_director.layer5_orchestrator.driver import (
            RESUME_STATE_FILENAME)

        return path / RESUME_STATE_FILENAME
    return path


def _write_json_atomic(payload: Any, path: Path) -> Path:
    """Write JSON evidence without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


_COARSE_PUBLIC_FILES = (
    "coarse_world_reference.json",
    "blockout_report.json",
    "blockout_manifest.json",
    "blockout_world_state.json",
    "coarse_pipeline_report.json",
    "coarse_world_baseline.json",
)
_COARSE_PUBLIC_DIRS = ("preview", "coarse", "approval")


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _replace_directory(source: Path, target: Path) -> None:
    """Publish one generated tree, preserving the previous tree until ready."""
    staging = target.with_name(
        f".{target.name}.staging-{os.getpid()}")
    backup = target.with_name(f".{target.name}.backup-{os.getpid()}")
    for candidate in (staging, backup):
        if candidate.is_dir():
            shutil.rmtree(candidate)
        elif candidate.exists():
            candidate.unlink()
    shutil.copytree(source, staging)
    try:
        if target.exists():
            os.replace(target, backup)
        os.replace(staging, target)
    except Exception:
        if not target.exists() and backup.exists():
            os.replace(backup, target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    if backup.exists():
        shutil.rmtree(backup)


def _publish_coarse_attempt(attempt_dir: Path, target: Path) -> None:
    """Publish one complete attempt as the canonical ``coarse/`` result."""
    target.mkdir(parents=True, exist_ok=True)
    for name in _COARSE_PUBLIC_FILES:
        source = attempt_dir / name
        destination = target / name
        if not source.is_file():
            destination.unlink(missing_ok=True)
            continue
        temporary = destination.with_name(
            f".{destination.name}.{os.getpid()}.tmp")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    for name in _COARSE_PUBLIC_DIRS:
        source = attempt_dir / name
        destination = target / name
        if source.is_dir():
            _replace_directory(source, destination)
        elif destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()


def _default_coarse_scene_restorer(*, manifest, expected_world_state,
                                   expected_report):
    """Rebuild a retained coarse manifest and verify its live world state."""
    import bpy

    from block_director.contracts.blockout import manifest_fingerprint
    from block_director.contracts.world_state import (
        world_state_fingerprint,
    )
    from block_director.layer3_engine.blockout_scene import (
        build_blockout_scene,
    )
    from block_director.layer3_engine.world_state import (
        collect_blockout_world_state,
    )

    build = dict(build_blockout_scene(manifest, clear_scene=True))
    scene = bpy.context.scene
    scene.frame_set(int(scene.frame_start))
    bpy.context.view_layer.update()
    observed = collect_blockout_world_state(manifest)
    manifest_fp = manifest_fingerprint(manifest)
    expected_manifest_fp = str(
        (expected_report or {}).get("best_manifest_fingerprint") or "")
    if expected_manifest_fp and manifest_fp != expected_manifest_fp:
        raise ValueError(
            "selected manifest does not match its pipeline evidence: "
            f"{manifest_fp} != {expected_manifest_fp}")
    expected_fp = str(
        (expected_report or {}).get("best_world_state_fingerprint") or "")
    if not expected_fp and expected_world_state:
        expected_fp = world_state_fingerprint(expected_world_state)
    observed_fp = world_state_fingerprint(observed)
    if expected_fp and observed_fp != expected_fp:
        raise ValueError(
            "restored Blender world state does not match selected evidence: "
            f"{observed_fp} != {expected_fp}")
    return {
        "restored": True,
        "manifest_fingerprint": manifest_fp,
        "world_state_fingerprint": observed_fp,
        "build": build,
        "verification_frame": int(scene.frame_current),
    }


def _delivered_shots_from_report(report) -> List[str]:
    """从导出报告折出**已实际产出 mp4** 的镜头（R2-D2/F4）。

    语义：``report.shots[]`` 里 ``video`` 非空即算已交付；failed 镜也照常
    产出最佳版本 mp4，因此照样进断点，避免"盘上有片、账本说没交"。
    skip / 未出片的镜（``video`` 为 None）不写进 ``delivered_shots``。
    顺序按报告顺序（即计划顺序），去重保序。
    """
    from block_director.delivery.failures import delivered_shot_ids

    return delivered_shot_ids(getattr(report, "shots", None))


def _passed_shots_from_report(report) -> List[str]:
    """从同一份导出报告折出**已出片且未标 failed** 的通过镜。"""
    from block_director.delivery.failures import passed_shot_ids

    return passed_shot_ids(getattr(report, "shots", None))


def _write_delivered_state(path, report) -> List[str]:
    """把本次实际导出 mp4 的镜头并入断点 ``delivered_shots``（R2-D2/F4）。

    成功导出分支与墙钟收尾分支共用；``report.shots`` 里 ``video`` 非空的镜
    都算已交付。failed 镜的最佳版本同样有片，但通过身份由
    :func:`_passed_shots_from_report` 单独报告。
    返回合并后的完整清单（原子写、排序稳定）。
    """
    from block_director.layer5_orchestrator.driver import (
        load_resume_state, save_resume_state)

    new_delivered = _delivered_shots_from_report(report)
    state = load_resume_state(Path(path))
    merged = sorted(set(state.delivered_shots) | set(new_delivered))
    state.delivered_shots = merged
    save_resume_state(Path(path), state)
    return merged


def _make_coarse_gate(project_dir, audit_log=None, *, transport=None,
                      knowledge=None, audit=None, config=None,
                      scene_restorer=None):
    """构造 headless 的粗排 gate 回调（R2-F1，延迟 import bpy 侧管线）。

    回调签名 ``coarse_gate(plan) -> {"ready": bool, "reason": str, ...}``：
    plan 已落定后用与 UI 全管线相同的输入装配（plan/brief/cast_positions/
    scene_id）跑 ``run_coarse_pipeline``，产物落到 ``<project>/coarse/``；
    判定复用 ``coarse_is_ready``（coarse=pass 且 baseline=frozen）。
    """
    from block_director.delivery.coarse_gate import run_coarse_gate_decision
    from block_director.utils.paths import default_project_root

    base = (Path(project_dir)
            if project_dir is not None
            else default_project_root())
    attempts_root = base / "coarse" / "plan_attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    bound_budget = None
    index_path = attempts_root / "index.json"
    attempts: List[Dict[str, Any]] = []
    if index_path.is_file():
        try:
            raw_index = json.loads(index_path.read_text(encoding="utf-8"))
            existing = raw_index.get("attempts")
            if isinstance(existing, list):
                attempts = [dict(row) for row in existing
                            if isinstance(row, dict)]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            attempts = []
    for child in attempts_root.iterdir():
        match = re.fullmatch(r"attempt-(\d{3,})", child.name)
        if not match or not child.is_dir():
            continue
        attempt_id = child.name
        if any(row.get("plan_attempt_id") == attempt_id for row in attempts):
            continue
        attempts.append({
            "plan_attempt_id": attempt_id,
            "dir": str(child),
            "status": "legacy_untracked",
        })
    attempts.sort(key=lambda row: str(row.get("plan_attempt_id") or ""))
    next_number = 1
    for row in attempts:
        match = re.fullmatch(
            r"attempt-(\d{3,})", str(row.get("plan_attempt_id") or ""))
        if match:
            next_number = max(next_number, int(match.group(1)) + 1)

    def write_index(selected: str = "") -> None:
        _write_json_atomic({
            "schema_version": "coarse-plan-attempts/v1",
            "attempts": copy.deepcopy(attempts),
            "selected_plan_attempt_id": str(selected or ""),
        }, index_path)

    def bind_budget(budget):
        nonlocal bound_budget
        bound_budget = budget

    def gate(plan, brief=None):
        nonlocal next_number
        attempt_id = f"attempt-{next_number:03d}"
        next_number += 1
        attempt_dir = attempts_root / attempt_id
        attempt_dir.mkdir(parents=True, exist_ok=False)
        plan_payload = (
            plan.to_dict() if hasattr(plan, "to_dict")
            else copy.deepcopy(dict(plan)))
        from block_director.contracts.audit import canonical_fingerprint

        _write_json_atomic(plan_payload, attempt_dir / "plan.json")
        try:
            from block_director.layer5_orchestrator.coarse_pipeline import (
                run_coarse_pipeline,
            )

            out_dir = attempt_dir
            cast_positions = {}
            cast_facings = {}
            #: R2-F5/F7：driver 在 UNDERSTANDING 阶段已产出真实 brief
            #: （其中 environment[] 含 LLM 解析的锚点/道具闭集声明）。
            #: 之前这里固定 None -> 粗排参考 JSON anchors/props 全空，
            #: 银币摊/海面等明确主体丢失，shot_002 空墙。现在接住真实 brief。
            scene_id = str(getattr(plan, "scene_heading", "")
                           or "blockdirector_scene")
            try:
                from block_director.contracts.cast import SceneSpec
                spec = SceneSpec.from_plan(plan, brief=brief)
                cast_positions = {
                    str(member.name): list(member.initial_location)
                    for member in spec.cast
                }
                cast_facings = {
                    str(member.name): list(member.initial_facing)
                    for member in spec.cast
                }
            except Exception:  # noqa: BLE001 - 站位只是证据，失败不阻断
                cast_positions = {}
                cast_facings = {}
            report = run_coarse_pipeline(
                plan=plan, out_dir=out_dir, brief=brief,
                cast_positions=cast_positions, cast_facings=cast_facings,
                scene_id=scene_id,
                transport=transport,
                knowledge=knowledge,
                audit=audit,
                budget=bound_budget,
                proposal_max_tokens=int(getattr(
                    getattr(config, "llm", None), "max_tokens", 12000
                ) or 12000),
            )
            report = copy.deepcopy(dict(report or {}))
            report["plan_attempt_id"] = attempt_id
            report["plan_attempt_dir"] = str(attempt_dir)
            report_path = attempt_dir / "coarse_pipeline_report.json"
            _write_json_atomic(report, report_path)
            decision = run_coarse_gate_decision(report)
            decision["payload"] = report
            decision["plan_attempt_id"] = attempt_id
            decision["plan_attempt_dir"] = str(attempt_dir)
            if not decision["ready"]:
                blocked = (report or {}).get("blocked_reason") or "粗排未通过"
                decision["reason"] = blocked
            else:
                decision["reason"] = ""
                baseline_path = Path(str(
                    (report.get("artifacts") or {}).get("baseline") or ""))
                if not baseline_path.is_file():
                    raise FileNotFoundError(
                        f"粗排已通过但冻结基准不存在：{baseline_path}")
                decision["baseline"] = json.loads(
                    baseline_path.read_text(encoding="utf-8"))
            _write_json_atomic(
                decision, attempt_dir / "gate_decision.json")
            attempts.append({
                "plan_attempt_id": attempt_id,
                "dir": str(attempt_dir),
                "status": "pass" if decision["ready"] else "blocked",
                "reason": str(decision.get("reason") or ""),
                "scene_score": (report or {}).get("best_score"),
                "gates": copy.deepcopy(decision.get("gates") or {}),
                "plan_fingerprint": canonical_fingerprint(plan_payload),
            })
            if decision["ready"]:
                _publish_coarse_attempt(attempt_dir, base / "coarse")
                write_index(selected=attempt_id)
            else:
                write_index()
            if audit_log is not None:
                audit_log("headless_coarse_gate",
                          f"粗排 gate：{'pass' if decision['ready'] else 'blocked'}",
                          level="info" if decision["ready"] else "warning",
                          payload=report,
                          plan_attempt_id=attempt_id,
                          plan_attempt_dir=str(attempt_dir))
            return decision
        except Exception as exc:  # noqa: BLE001 - 粗排失败不静默放行
            error_type = type(exc).__name__
            trace = traceback.format_exc()
            failure = {
                "ready": False,
                "execution_error": True,
                "error_type": error_type,
                "traceback": trace,
                "reason": f"粗排执行失败：{error_type}: {exc}",
                "payload": None,
                "plan_attempt_id": attempt_id,
                "plan_attempt_dir": str(attempt_dir),
            }
            _write_json_atomic(failure, attempt_dir / "gate_decision.json")
            attempts.append({
                "plan_attempt_id": attempt_id,
                "dir": str(attempt_dir),
                "status": "execution_error",
                "reason": failure["reason"],
            })
            write_index()
            if audit_log is not None:
                audit_log("headless_coarse_gate",
                          f"粗排执行失败：{error_type}: {exc}",
                          level="error", traceback=trace,
                          plan_attempt_id=attempt_id,
                          plan_attempt_dir=str(attempt_dir))
            return failure

    gate.bind_budget = bind_budget

    def restore_best(*, plan, decision):
        """Rebuild the exact plan-level best retained by this gate instance."""
        plan_attempt_id = str((decision or {}).get("plan_attempt_id") or "")
        row = next(
            (item for item in attempts
             if item.get("plan_attempt_id") == plan_attempt_id),
            None,
        )
        if not plan_attempt_id or row is None:
            reason = (
                f"retained coarse attempt not found: {plan_attempt_id or '-'}")
            return {
                "restored": False,
                "plan_attempt_id": plan_attempt_id,
                "error": reason,
            }
        attempt_dir = Path(str(row.get("dir") or ""))
        if not _path_within(attempt_dir, attempts_root) or (
                not attempt_dir.is_dir()):
            reason = f"retained coarse attempt directory is invalid: {attempt_dir}"
            return {
                "restored": False,
                "plan_attempt_id": plan_attempt_id,
                "error": reason,
            }
        plan_payload = (
            plan.to_dict() if hasattr(plan, "to_dict")
            else copy.deepcopy(dict(plan)))
        try:
            from block_director.contracts.audit import canonical_fingerprint

            if canonical_fingerprint(plan_payload) != str(
                    row.get("plan_fingerprint") or ""):
                raise ValueError(
                    "driver-selected plan does not match retained attempt")
            payload = copy.deepcopy((decision or {}).get("payload") or {})
            artifacts = dict(payload.get("artifacts") or {})
            report_path = attempt_dir / "coarse_pipeline_report.json"
            if report_path.is_file():
                report_disk = json.loads(
                    report_path.read_text(encoding="utf-8"))
                if str(report_disk.get("plan_attempt_id") or "") != (
                        plan_attempt_id):
                    raise ValueError(
                        "retained pipeline report has a different attempt id")
                if not payload:
                    payload = report_disk
                artifacts = dict(
                    report_disk.get("artifacts") or artifacts)
            manifest_path = Path(str(
                artifacts.get("blockout_manifest")
                or attempt_dir / "blockout_manifest.json"))
            world_path = Path(str(
                artifacts.get("blockout_world_state")
                or attempt_dir / "blockout_world_state.json"))
            for path, label in (
                    (manifest_path, "manifest"),
                    (world_path, "world state")):
                if not _path_within(path, attempt_dir):
                    raise ValueError(
                        f"retained {label} escapes attempt directory: {path}")
                if not path.is_file():
                    raise FileNotFoundError(
                        f"retained {label} is missing: {path}")
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8"))
            expected_world_state = json.loads(
                world_path.read_text(encoding="utf-8"))
            restorer = scene_restorer or _default_coarse_scene_restorer
            physical = dict(restorer(
                manifest=manifest,
                expected_world_state=expected_world_state,
                expected_report=payload,
            ) or {})
            if physical.get("restored") is not True:
                raise ValueError(
                    "scene restorer did not confirm a physical restore")
            _publish_coarse_attempt(attempt_dir, base / "coarse")
            row["status"] = "restored"
            row["restore"] = copy.deepcopy(physical)
            write_index(selected=plan_attempt_id)
            result = {
                **physical,
                "restored": True,
                "plan_attempt_id": plan_attempt_id,
                "plan_attempt_dir": str(attempt_dir),
                "published_dir": str(base / "coarse"),
            }
            if audit_log is not None:
                audit_log(
                    "headless_coarse_best_restored",
                    f"已重建粗排计划级 best：{plan_attempt_id}",
                    level="info",
                    **copy.deepcopy(result),
                )
            return result
        except Exception as exc:  # noqa: BLE001 - restore must stay explicit
            reason = f"{type(exc).__name__}: {exc}"
            row["status"] = "physical_restore_failed"
            row["restore_error"] = reason
            write_index(selected=plan_attempt_id)
            if audit_log is not None:
                audit_log(
                    "headless_coarse_best_restore_failed",
                    f"粗排计划级 best 物理恢复失败：{reason}",
                    level="error",
                    plan_attempt_id=plan_attempt_id,
                    plan_attempt_dir=str(attempt_dir),
                    traceback=traceback.format_exc(),
                )
            return {
                "restored": False,
                "plan_attempt_id": plan_attempt_id,
                "plan_attempt_dir": str(attempt_dir),
                "error": reason,
            }

    gate.restore_best = restore_best
    return gate


def _make_detail_gate(
    project_dir,
    audit_log=None,
    detail_runner=None,
    *,
    transport=None,
    knowledge=None,
    config=None,
    run_id="",
    proposal_max_tokens=None,
):
    """构造 headless 的细排/序列/final gate。

    与 UI 全管线同一条语义：冻结粗排基准 -> ``run_detail_pipeline`` -> 只有
    detail/sequence/final 全过且 ``final_video.mp4`` 真在盘上才放行。任何
    pending、blocked、执行异常或缺失产物都返回 ``ready=False``，绝不把
    "还没跑"写成 "pass"。
    """
    from block_director.layer5_orchestrator.pipeline_ui_inputs import (
        detail_is_ready,
        gate_value,
    )
    from block_director.utils.paths import default_project_root

    expected = {
        "coarse": "pass",
        "baseline": "frozen",
        "detail": "pass",
        "sequence": "pass",
        "final": "pass",
    }

    def gate(plan, runtime_world_state=None):
        base = (Path(project_dir)
                if project_dir is not None
                else default_project_root())
        baseline_path = base / "coarse" / "coarse_world_baseline.json"
        if not baseline_path.is_file():
            reason = f"细排无法开始：冻结基准不存在（{baseline_path}）"
            if audit_log is not None:
                audit_log("headless_detail_gate", reason, level="error")
            return {
                "ready": False,
                "reason": reason,
                "gates": {},
                "final_video": None,
                "payload": None,
                "baseline": str(baseline_path),
            }
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            if detail_runner is None:
                from block_director.layer5_orchestrator.detail_pipeline import (
                    run_detail_pipeline,
                )

                runner = run_detail_pipeline
            else:
                runner = detail_runner
            report = runner(
                baseline=baseline,
                plan=plan,
                out_dir=base / "detail",
                render_video=True,
                runtime_world_state=runtime_world_state,
                transport=transport,
                knowledge=knowledge,
                run_id=str(run_id or ""),
                scene_id=str(
                    getattr(plan, "scene_heading", "")
                    or (baseline.get("reference") or {}).get("scene_id")
                    or "blockdirector_scene"),
                proposal_max_tokens=int(
                    proposal_max_tokens
                    or getattr(getattr(config, "llm", None), "max_tokens", 12000)
                    or 12000),
            )
        except Exception as exc:  # noqa: BLE001 - gate 失败必须如实阻断
            reason = f"细排执行失败：{type(exc).__name__}: {exc}"
            if audit_log is not None:
                audit_log("headless_detail_gate", reason, level="error")
            return {
                "ready": False,
                "reason": reason,
                "gates": {},
                "final_video": None,
                "payload": None,
                "baseline": str(baseline_path),
            }

        gates = {key: gate_value(report, key) for key in expected}
        final_video = str(
            ((report or {}).get("artifacts") or {}).get("final_video") or "")
        ready = (
            detail_is_ready(report)
            and all(gates[key] == value for key, value in expected.items())
            and bool(final_video)
            and Path(final_video).is_file()
        )
        if ready:
            reason = ""
        elif gates != expected:
            reason = "细排/final gate 未通过：" + "、".join(
                f"{key}={gates[key] or 'missing'}" for key in expected)
        elif not final_video:
            reason = "细排 gate 显示通过，但没有 final_video.mp4 产物"
        else:
            reason = f"细排 gate 显示通过，但 final_video 不在盘上（{final_video}）"
        if audit_log is not None:
            audit_log(
                "headless_detail_gate",
                f"细排 gate：{'pass' if ready else 'blocked'}",
                level="info" if ready else "warning",
                payload=report,
                gates=gates,
            )
        return {
            "ready": ready,
            "reason": reason,
            "gates": gates,
            "final_video": final_video if ready else None,
            "payload": report,
            "baseline": str(baseline_path),
        }

    return gate


def parse_args(argv):
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="run_headless")
    parser.add_argument("--script", default="", help="剧本文件路径")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", dest="offline", action="store_true",
                      default=True, help="离线自检（默认）")
    mode.add_argument("--sidecar", dest="offline", action="store_false",
                      help="使用 sidecar 而不是离线自检")
    parser.add_argument("--out", default="", help="运行输出目录")
    parser.add_argument("--wall", type=float, default=180.0, help="墙上时间上限（秒）")
    parser.add_argument("--build", action="store_true",
                        help="把分镜计划落成真实场景（角色/相机/关键帧/剪切标记）")
    parser.add_argument("--save", default="",
                        help="运行成功后把项目（SDL）保存到该目录")
    parser.add_argument("--export", action="store_true",
                        help="运行成功后直接导出交付包（§15 的一条命令验收）")
    parser.add_argument("--export-dir", default="",
                        help="交付包目录；留空则用 <out>/export")
    parser.add_argument("--resume", default="",
                        help="从断点继续：读 <目录>/resume_state.json（墙钟撞线"
                             "收尾时写出），跳过终态镜（零 LLM 调用），从第一个"
                             "非终态镜继续；不会重渲已交付的镜头。")
    parser.add_argument("--llm-timeout", type=float, default=None,
                        help="单次 LLM 调用超时（秒）；省略时读取配置 llm.timeout_s。"
                             "慢思考通道建议至少 600")
    parser.add_argument("--max-llm-calls", type=int, default=0,
                        help="本次运行的 LLM 调用硬上限（§12.6）。本地模型"
                             "返工多，常需放大；0 表示不限")
    parser.add_argument("--preset", default="",
                        help="交付分辨率预设（hd16x9/fhd16x9/square/vertical）；"
                             "v1.4 §4.4 步骤 1 需要它来对齐像素阈值")
    return parser.parse_args(rest)


def main() -> int:
    args = parse_args(sys.argv)
    driver_success = False
    audit = None
    project_dir = None

    import block_director
    block_director.register()          # 走真实注册路径（含主线程登记与配置加载）

    from block_director.layer5_orchestrator.headless_runner import run_headless
    from block_director.layer5_orchestrator.driver import DriverLimits

    from block_director.layer3_engine.shot_auditor import BpyShotAuditor
    from block_director.layer3_engine.scene_state import collect_scene_state
    from block_director.layer3_engine.tool_bindings import register_all_scene_tools
    from block_director.layer5_orchestrator.driver import default_registry
    from block_director.layer5_orchestrator.human_gate import AutoGate
    from block_director.observation.state import format_scene_state

    script = ""
    parsed = None
    if args.script:
        path = Path(args.script)
        if path.exists():
            script = path.read_text(encoding="utf-8", errors="replace")
            try:
                from block_director.layer1_input import (
                    apply_deterministic_coreferences,
                    parse_script,
                )
                parsed = parse_script(path)
                # v1.3 P0-3：共指消解此前从未被真实链路调用（§4.3 是死代码）。
                # 先接上确定性的一面；代词消解交给 Stage S 的模型判断。
                merged = apply_deterministic_coreferences(parsed)
                print("BLOCKDIRECTOR_PARSE " + json.dumps(
                    {"format": parsed.source_format, "title": parsed.title,
                     "scenes": len(parsed.scenes),
                     "dialogues": parsed.dialogue_count,
                     "characters": parsed.character_names,
                     "needs_llm_structure": parsed.needs_llm_structure,
                     "coreference_merged": merged},
                    ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 - 解析失败要让人看见
                print(f"BLOCKDIRECTOR_WARN 剧本解析失败，将退回原文：{exc}")
        else:
            print(f"BLOCKDIRECTOR_WARN 剧本不存在: {path}")

    builder = None
    crowd: list = []
    from block_director.settings import get_config
    from block_director.contracts.enums import DeliveryPreset

    config = get_config()
    if args.preset:
        # v1.4 §4.4 步骤 1：只有写进配置，--preset 才真的改变本次导出分辨率
        # （与 tools/run_export.py:98-99 同款）。写错取值就明确报错。
        config.delivery.preset = DeliveryPreset(args.preset)

    registry = default_registry(max_shots=int(config.orchestration.max_shots))
    register_all_scene_tools(registry)

    # v1.6 F2（D-09）：--resume 读断点（目录下的 resume_state.json）。
    # 坏文件 / 版本错配必须明确报错退出，绝不猜。
    resume_state = None
    resume_path = None
    if args.resume:
        from block_director.layer5_orchestrator.driver import (
            ResumeStateError, load_resume_state)

        resume_path = _resume_state_path(args.resume)
        try:
            resume_state = load_resume_state(resume_path)
        except ResumeStateError as exc:
            print("BLOCKDIRECTOR_RESUME_ERROR " + json.dumps(
                {"message": str(exc), "path": str(resume_path)},
                ensure_ascii=False))
            return 1
        print("BLOCKDIRECTOR_RESUME " + json.dumps(
            {"path": str(resume_path), "version": resume_state.version,
             "terminal_shots": resume_state.terminal_shots,
             "delivered_shots": resume_state.delivered_shots},
            ensure_ascii=False))

    if args.build or args.resume:
        from block_director.layer3_engine.shot_builder import BpySceneBuilder

        crowd_config = config.crowd
        crowd = _crowd_from_script(parsed, crowd_config)
        if crowd:
            print("BLOCKDIRECTOR_CROWD " + json.dumps(
                {"entries": crowd,
                 "total": sum(item["count"] for item in crowd)},
                ensure_ascii=False))
        builder = BpySceneBuilder(clear_scene=True, crowd=crowd)

    limits = DriverLimits.from_config(
        config, llm_timeout_s=args.llm_timeout,
        max_llm_calls=args.max_llm_calls)
    auditor = (BpyShotAuditor(audit_level=config.audit.level,
                              vlm_review=config.vlm_review)
               if builder is not None else None)
    scene_state_provider = lambda: format_scene_state(  # noqa: E731
        collect_scene_state(detailed=False))

    if resume_state is not None:
        # resume 分支自己组驱动器：``headless_runner.run_headless`` 没有
        # resume 入口（卡 F2 的文件边界），这里复用它的传输/知识装配件。
        from block_director.layer5_orchestrator.driver import PrevisDriver
        from block_director.layer5_orchestrator.headless_runner import (
            _apply_declarations, _make_knowledge, _write_knowledge_trace,
            trace_options)
        from block_director.layer5_orchestrator.states import DriverState
        from block_director.layer5_orchestrator.transport_factory import (
            make_transport)
        from block_director.layer6_audit.audit_logger import AuditLogger
        from block_director.utils.paths import ensure_dir

        transport, mode = make_transport(config, offline=args.offline)
        _apply_declarations(transport, parsed, config)
        project_dir = Path(args.out) if args.out else resume_path.parent
        audit = AuditLogger(directory=ensure_dir(project_dir / "runs"),
                            **trace_options(config))
        knowledge = _make_knowledge(config, transport, audit)
        coarse_gate = _make_coarse_gate(
            project_dir, audit_log=audit.log, transport=transport,
            knowledge=knowledge, audit=audit, config=config)
        driver = PrevisDriver(
            transport=transport, audit=audit,
            script=resume_state.script or script, parsed_script=parsed,
            config=config, limits=limits, builder=builder, registry=registry,
            auditor=auditor, scene_state_provider=scene_state_provider,
            human_gate=AutoGate(), knowledge=knowledge,
            resume_state=resume_state, resume_state_path=resume_path,
            coarse_gate=coarse_gate)
        state = driver.run_to_completion(poll_interval=0.02,
                                         max_wall_s=args.wall)
        summary = driver.snapshot()
        summary["mode"] = mode
        summary["success"] = state is DriverState.DONE
        summary["audit_log"] = str(audit.audit_path) if audit.audit_path else None
        summary["llm_trace"] = str(audit.trace_path) if audit.trace_path else None
        summary["plan"] = driver.plan.to_dict() if driver.plan else None
        summary["retrieval_calls"] = int(
            getattr(getattr(driver, "knowledge", None), "retrieval_calls", 0)
            or 0)
        summary["knowledge_provenance"] = driver.knowledge_provenance()
        summary["knowledge_trace"] = _write_knowledge_trace(
            driver.knowledge, project_dir)
    else:
        from block_director.utils.paths import default_project_root
        from block_director.layer6_audit.audit_logger import AuditLogger
        from block_director.layer5_orchestrator.headless_runner import (
            _apply_declarations, _make_knowledge, trace_options,
        )
        from block_director.layer5_orchestrator.transport_factory import (
            make_transport,
        )
        from block_director.utils.paths import ensure_dir

        project_dir = (Path(args.out) if args.out
                       else default_project_root())
        audit = AuditLogger(directory=ensure_dir(project_dir / "runs"),
                            **trace_options(config))
        transport, mode = make_transport(config, offline=args.offline)
        _apply_declarations(transport, parsed, config)
        knowledge = _make_knowledge(config, transport, audit)

        summary = run_headless(
            script,
            offline=args.offline,
            project_dir=Path(args.out) if args.out else None,
            config=config,
            max_wall_s=args.wall,
            builder=builder,
            registry=registry,
            auditor=auditor,
            human_gate=AutoGate(),  # headless 无界面：逐条记为 skipped 以便审计
            scene_state_provider=scene_state_provider,
            parsed_script=parsed,
            limits=limits,
            audit=audit,
            transport=transport,
            transport_mode=mode,
            knowledge=knowledge,
            coarse_gate=_make_coarse_gate(
                project_dir, audit_log=audit.log, transport=transport,
                knowledge=knowledge, audit=audit, config=config),
        )

    driver_success = bool(summary.get("success"))
    summary["driver_success"] = driver_success

    if args.save and summary.get("success") and summary.get("plan"):
        from block_director.layer5_orchestrator.headless_runner import (
            save_run_project,
        )

        spec = builder.spec if builder is not None else None
        saved = save_run_project(summary, out_dir=Path(args.save), spec=spec,
                                 crowd=crowd)
        #: 落盘时的校验结论随标记一起打出来——"存了个文件"与"存了个能打开的
        #: 文件"是两件事，调用方（人/链）不该等到 rebuild 才知道。
        print("BLOCKDIRECTOR_SAVED " + json.dumps(
            {"path": str(saved.path), "validation": saved.validation},
            ensure_ascii=False))

    export_failed = False
    detail_failed = False
    out_dir = (Path(args.export_dir) if args.export_dir else
               (Path(args.out) if args.out else Path.cwd()))
    from block_director.contracts.plan import Plan

    if args.export and summary.get("success") and summary.get("plan"):
        # §15 的核心验收：**一条命令**从剧本产出干净的分镜参考视频。
        # 这里直接导出，场景还活在内存里——不必先落盘再重建。
        plan_obj = Plan.from_dict(summary["plan"])
        delivered = (set(resume_state.delivered_shots)
                     if resume_state is not None else set())
        remaining = [str(shot.shot_id) for shot in plan_obj.shots
                     if str(shot.shot_id) not in delivered]
        if remaining:
            from block_director.layer5_orchestrator.driver import plan_for_shots

            report = _export_report(plan_for_shots(plan_obj, remaining),
                                    summary, config, out_dir, crowd, parsed,
                                    concat_plan=plan_obj)
            payload = report.to_dict()
            # R2-D2：成功导出也要把**实际产出 mp4** 的镜头写回断点，
            # 断点与磁盘产物一致，再次 resume 不重复导出。
            saved_path = summary.get("resume_state_path")
            if (report.ok and saved_path):
                try:
                    merged = _write_delivered_state(Path(saved_path), report)
                    print("BLOCKDIRECTOR_PARTIAL_DELIVERED " + json.dumps(
                        {"path": saved_path, "delivered_shots": merged},
                        ensure_ascii=False))
                except Exception as exc:  # noqa: BLE001 - 写回失败不静默
                    print("BLOCKDIRECTOR_WARN " + json.dumps(
                        {"message": f"断点交付清单更新失败：{exc}"},
                        ensure_ascii=False))
        else:
            # resume 且上一段墙钟收尾已交付全部镜头：无新增导出。
            payload = {"ok": True, "aborted": False, "reason": "",
                       "out_dir": str(out_dir / "export"), "files": [],
                       "warnings": ["全部镜头已在墙钟收尾时交付，无新增导出"]}
        print("BLOCKDIRECTOR_EXPORT " + json.dumps(
            {"ok": payload["ok"], "aborted": payload["aborted"],
             "out_dir": payload["out_dir"], "files": len(payload["files"]),
             "warnings": payload["warnings"], "reason": payload["reason"],
             "delivered": sorted(delivered), "shots": remaining},
            ensure_ascii=False))
        export_failed = not payload["ok"]

    # v1.6 F2（D-09）：墙钟撞线 = 保已完成镜。这里把终态镜的交付物导出，
    # 并把"已交付"写回断点——resume 后的导出不再重渲它们。
    if (args.export and summary.get("wall_clock_exhausted")
            and summary.get("plan") and summary.get("terminal_shots")):
        from block_director.layer5_orchestrator.driver import plan_for_shots

        delivered = (set(resume_state.delivered_shots)
                     if resume_state is not None else set())
        new_completed = [str(s) for s in summary.get("terminal_shots")
                         if str(s) not in delivered]
        if new_completed:
            plan_obj = Plan.from_dict(summary["plan"])
            report = _export_report(plan_for_shots(plan_obj, new_completed),
                                    summary, config, out_dir, crowd, parsed,
                                    concat_plan=plan_obj)
            print("BLOCKDIRECTOR_PARTIAL_EXPORT " + json.dumps(
                {"ok": report.ok, "aborted": report.aborted,
                 "out_dir": report.out_dir, "files": len(report.files),
                 "warnings": report.warnings, "reason": report.reason,
                 "completed_shots": new_completed},
                ensure_ascii=False))
            if report.ok:
                saved_path = summary.get("resume_state_path")
                if saved_path:
                    try:
                        # R2-D2/F4：只写**实际产出 mp4** 的镜。failed 镜的最佳
                        # 版本也有文件，因此进入 delivered；通过身份另行区分。
                        merged = _write_delivered_state(Path(saved_path), report)
                        print("BLOCKDIRECTOR_PARTIAL_DELIVERED " + json.dumps(
                            {"path": saved_path,
                             "delivered_shots": merged},
                            ensure_ascii=False))
                    except Exception as exc:  # noqa: BLE001 - 写回失败不静默
                        print("BLOCKDIRECTOR_WARN " + json.dumps(
                            {"message": f"断点交付清单更新失败：{exc}"},
                            ensure_ascii=False))

    if args.export and driver_success and summary.get("plan"):
        # §15 与完整白模管线的共同收尾：前面已有逐镜诊断交付，但只有
        # 冻结粗排 -> 细排 -> 序列 -> final gate 全过，整次 headless 才能
        # 报成功。pending/blocked 一律保留真实报告并让退出码非零。
        runtime_world_state = None
        try:
            from block_director.layer3_engine.scene_context import get_context
            from block_director.layer3_engine.world_state import collect_world_state

            scene_context = get_context()
            if scene_context is not None:
                runtime_world_state = collect_world_state(scene_context)
        except Exception as exc:  # noqa: BLE001 - 采集失败不能让 gate 静默放行
            message = (f"实时世界状态采集失败：{type(exc).__name__}: {exc}")
            if audit is not None:
                audit.log("headless_detail_gate", message, level="warning")
            print("BLOCKDIRECTOR_WARN " + json.dumps(
                {"message": message}, ensure_ascii=False))

        plan_obj = Plan.from_dict(summary["plan"])
        detail_gate = _make_detail_gate(
            project_dir,
            audit_log=(audit.log if audit is not None else None),
            transport=transport,
            knowledge=knowledge,
            config=config,
            run_id=(str(getattr(audit, "run_id", "") or "")
                    if audit is not None else ""),
        )
        try:
            decision = detail_gate(
                plan_obj, runtime_world_state=runtime_world_state)
        except Exception as exc:  # noqa: BLE001 - 未过 gate 不得伪装成功
            decision = {
                "ready": False,
                "reason": f"细排 gate 执行失败：{type(exc).__name__}: {exc}",
                "gates": {},
                "final_video": None,
                "payload": None,
            }
        detail_report = (project_dir / "detail"
                         / "detail_pipeline_report.json")
        summary["full_pipeline"] = {
            "schema_version": "headless-full-pipeline/v1",
            "ready": bool(decision.get("ready")),
            "reason": str(decision.get("reason") or ""),
            "gates": dict(decision.get("gates") or {}),
            "final_video": decision.get("final_video"),
            "detail_report": (str(detail_report)
                              if detail_report.exists() else None),
            "runtime_world_state": runtime_world_state,
        }
        summary["final_video"] = decision.get("final_video")
        detail_failed = not bool(decision.get("ready"))
        summary["success"] = bool(
            driver_success and not detail_failed and not export_failed)
        print("BLOCKDIRECTOR_DETAIL " + json.dumps(
            summary["full_pipeline"], ensure_ascii=False))

    print("BLOCKDIRECTOR_RESULT " + json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("success") and not export_failed else 1


if __name__ == "__main__":
    sys.exit(main())
