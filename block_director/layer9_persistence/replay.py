"""确定性重放（执行文档 v1.2 §14.4）。

LLM 在 temperature > 0 下不可复现。要让"改代码后零成本重渲"与 Golden Test
成立，就必须能**不调用 LLM** 重建同一条时间线。数据源是 ``audit_log.jsonl``：

- ``plan_received`` 事件带着完整分镜计划（这是场景的骨架）；
- 每条 ``tool_call`` 事件带着工具名与参数（这是对骨架的修正）。

重放顺序因此是：**先按计划建场景，再按记录顺序重放工具调用**。只重放工具
调用是不够的——真实运行里场景是构建器按计划建的，不是工具一次一次搭起来的。

日志格式以 §11.3 的实现为准：``{"kind": "tool_call", "data": {"tool": ...,
"args": ...}}``；同时兼容 §14.4 伪代码里的 ``{"type": "tool_call",
"name": ..., "args": ...}`` 形状，便于对接受众不同的日志。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from ..contracts.plan import Plan
from ..contracts.tools import REPLAY_SKIPPED_TOOLS
from ..contracts.evidence import EvidenceStore, inspect_evidence_store

AUDIT_FILENAME = "audit_log.jsonl"
PLAN_EVENT = "plan_received"
TOOL_EVENT = "tool_call"
#: v1.4 X5：阶段 S 的理解也必须被重放消费——站位由 ``brief.space`` 决定，
#: 不读它就会用默认站位重建，"零 LLM 重渲"出来的画面与原始运行不一样。
BRIEF_EVENT = "brief_received"

#: 只影响控制器、不改场景的工具：重放时登记为跳过，而不是当成失败。
#: 名单来自 contracts 的单一真源——v1.2 在这里和 control_tools.py 各存一份，
#: 新增控制类工具时两处极易失配。
CONTROL_TOOLS = REPLAY_SKIPPED_TOOLS


class ReplayError(RuntimeError):
    """无法重放。消息里给出可执行的下一步。"""


@dataclass(frozen=True)
class ReplayStep:
    index: int
    tool: str
    args: Dict[str, Any]
    recorded_ok: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "tool": self.tool,
                "recorded_ok": self.recorded_ok}


@dataclass
class ReplayReport:
    plan: Optional[Plan] = None
    steps: List[ReplayStep] = field(default_factory=list)
    executed: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    built: bool = False
    summary: Dict[str, Any] = field(default_factory=dict)
    evidence_store: Optional[EvidenceStore] = None
    evidence_status: Dict[str, Any] = field(default_factory=dict)
    evidence_best: Dict[str, int] = field(default_factory=dict)
    #: v1.4 X5：重放时读到的 SceneBrief（站位由它决定）。
    brief: Optional[Any] = None
    brief_source: str = ""

    @property
    def ok(self) -> bool:
        return self.plan is not None and not self.failures

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "built": self.built,
                "plan_shots": len(self.plan.shots) if self.plan else 0,
                "steps": len(self.steps),
                "executed": list(self.executed),
                "skipped": list(self.skipped),
                "failures": list(self.failures),
                "brief_source": self.brief_source,
                "evidence_status": dict(self.evidence_status),
                "evidence_best": dict(self.evidence_best),
                "summary": dict(self.summary)}


def audit_path(directory: Union[str, Path]) -> Path:
    return Path(directory) / AUDIT_FILENAME


def audit_candidates(directory: Union[str, Path]) -> List[Path]:
    """审计日志的可能位置。

    §14.1 的目录树把它放在项目根；而 headless 运行把所有日志收在 ``runs/`` 下，
    便于整目录忽略与清理。两处都认，避免"文件明明在、工具却说找不到"。
    直接传一个 JSONL 文件路径时就用它——§21.4 的回归夹具
    ``fixtures/tool_transcript_simple.jsonl`` 就是这么被喂进来的。
    """
    root = Path(directory)
    if root.is_file():
        return [root]
    return [root / AUDIT_FILENAME, root / "runs" / AUDIT_FILENAME]


def read_audit_log(directory: Union[str, Path]) -> List[Dict[str, Any]]:
    """逐行读审计日志；坏行跳过并计数，不因一行损坏就丢掉整段历史。"""
    candidates = audit_candidates(directory)
    path = next((item for item in candidates if item.exists()), None)
    if path is None:
        looked = "、".join(str(item) for item in candidates)
        raise ReplayError(f"找不到审计日志（找过：{looked}）。"
                          f"请先完整跑过至少一次生成，或检查 --project 目录是否正确")
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        text = line.strip()
        if not text:
            continue
        try:
            records.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    return records


def extract_plan(records: Sequence[Dict[str, Any]]) -> Optional[Plan]:
    """取最后一个 ``plan_received`` 事件里的完整计划（可能经过修复）。"""
    plan: Optional[Plan] = None
    for record in records:
        if record.get("kind") != PLAN_EVENT:
            continue
        data = record.get("data") or {}
        payload = data.get("plan")
        if isinstance(payload, dict):
            plan = Plan.from_dict(payload)
        elif isinstance(data.get("shots"), list):     # 旧日志只有 shots
            plan = Plan.from_dict({"shots": data["shots"],
                                   "scene_heading": data.get("scene_heading", "")})
    return plan


def extract_brief(records: Sequence[Dict[str, Any]]):
    """取最后一个 ``brief_received`` 事件里的 SceneBrief（v1.4 X5）。

    返回契约对象 :class:`~block_director.contracts.brief.SceneBrief`；
    日志里没有该事件时返回 ``None``（v1.3 的旧日志，退回默认站位）。
    """
    from ..contracts.brief import SceneBrief

    brief = None
    for record in records:
        if record.get("kind") != BRIEF_EVENT:
            continue
        data = record.get("data") or {}
        payload = data.get("brief") if isinstance(data.get("brief"), dict) \
            else data
        if isinstance(payload, dict) and payload:
            try:
                brief = SceneBrief.from_dict(payload)
            except Exception:  # noqa: BLE001 - 坏事件不阻断重放
                continue
    return brief


def extract_blockout_manifest(
        records: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """取最后一个 ``blockout_manifest_generated`` 事件里的完整清单。

    Blockout 的原始数据源是空间设计快照与计划；重放时清单**不重新推导**
    （避免与运行时依赖相同的转换器出现口径漂移），直接从审计事件 payload
    复原——事件指纹在写入时已钉死，同一运行两次重放逐位一致。
    """
    manifest: Optional[Dict[str, Any]] = None
    for record in records:
        if record.get("kind") != "blockout_manifest_generated":
            continue
        data = record.get("data") or {}
        payload = data.get("payload")
        if isinstance(payload, dict) and payload:
            manifest = payload
    return manifest


def extract_blockout_approvals(
        records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按顺序取所有 ``blockout_approval_recorded`` 事件的审批记录。

    记录从事件 payload 复原（含 schema_version / 状态 / 指纹 / 审批人）。
    保持事件顺序，供后续全局回放一致性审查按时间线消费。
    """
    approvals: List[Dict[str, Any]] = []
    for record in records:
        if record.get("kind") != "blockout_approval_recorded":
            continue
        data = record.get("data") or {}
        payload = data.get("payload") if isinstance(data.get("payload"), dict) \
            else data
        if isinstance(payload, dict) and payload:
            approvals.append(dict(payload))
    return approvals


def iter_tool_calls(records: Iterable[Dict[str, Any]]) -> List[ReplayStep]:
    """把日志里的工具调用按记录顺序抽成重放步骤。"""
    steps: List[ReplayStep] = []
    for record in records:
        kind = record.get("kind") or record.get("type")
        if kind != TOOL_EVENT:
            continue
        data = record.get("data") or {}
        tool = str(data.get("tool") or record.get("name") or "")
        if not tool:
            continue
        args = data.get("args")
        if not isinstance(args, dict):
            args = record.get("args") if isinstance(record.get("args"), dict) else {}
        steps.append(ReplayStep(index=len(steps), tool=tool, args=dict(args),
                                recorded_ok=bool(data.get("ok", True))))
    return steps


def extract_ruler_evidence(records: Sequence[Dict[str, Any]]
                           ) -> tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    """从审计日志抽取空间尺观测证据（Ticket 06，重放侧）。

    数据源（只读，不调用 LLM／bpy）：
    * ``spatial_ruler_plan_audit`` 事件 → 计划级处方与测量（取**最后一条**，
      与 ``plan_findings_from_log`` 同一口径）；
    * ``shot_audit`` 事件 → 逐镜几何测量（``ruler_measurements``，取每条
      最后一次出现的非空表）。

    返回 ``(plan_evidence, shot_measurements)``；没有对应事件时各为空表——
    重放诚实标缺，不猜、不伪造。旧日志（无空间尺事件）shape 与
    有事件但内容为空一致。
    """
    plan_evidence: Dict[str, Any] = {"prescriptions": [], "measurements": []}
    shot_measurements: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        data = dict(record.get("data") or {})
        if record.get("kind") == "spatial_ruler_plan_audit":
            prescriptions = [
                dict(item) for item in data.get("prescriptions") or []
                if isinstance(item, dict)]
            measurements = [
                dict(item) for item in data.get("measurements") or []
                if isinstance(item, dict)]
            plan_evidence = {
                "prescriptions": prescriptions, "measurements": measurements}
        elif record.get("kind") == "shot_audit":
            shot_id = str(data.get("shot") or "")
            items = data.get("ruler_measurements")
            if shot_id and isinstance(items, list):
                clean = [dict(item) for item in items if isinstance(item, dict)]
                if clean:
                    shot_measurements[shot_id] = clean
    return plan_evidence, shot_measurements


def extract_spatial_snapshots(records: Sequence[Dict[str, Any]]
                              ) -> Dict[str, Optional[Dict[str, Any]]]:
    """从审计日志抽取三份空间快照（Ticket 08，重放侧，零 LLM）。

    数据源是运行期 ``snapshot_audit_event`` 落盘的审计事件：
    ``spatial_design_snapshot`` / ``spatial_observation_snapshot`` /
    ``spatial_diff_report``，快照本体在 ``data.payload``。同一 kind 多事件
    取**最后一条**（与 ``plan_received`` / ``extract_ruler_evidence`` 同口径，
    重放的是最终态）。缺事件返回 ``None``——旧日志零形状差，不猜、不伪造。
    """
    kinds = ("spatial_design_snapshot", "spatial_observation_snapshot",
             "spatial_diff_report")
    snapshots: Dict[str, Optional[Dict[str, Any]]] = {
        "design": None, "observation": None, "diff": None}
    for record in records:
        kind = record.get("kind")
        if kind not in kinds:
            continue
        payload = (record.get("data") or {}).get("payload")
        if not isinstance(payload, dict):
            continue
        if kind == "spatial_design_snapshot":
            snapshots["design"] = payload
        elif kind == "spatial_observation_snapshot":
            snapshots["observation"] = payload
        elif kind == "spatial_diff_report":
            snapshots["diff"] = payload
    return snapshots


def extract_blockout_artifacts(records: Sequence[Dict[str, Any]]
                               ) -> Dict[str, Optional[Dict[str, Any]]]:
    """从审计日志抽取三份粗排产物（Ticket 02，重放侧，零 LLM）。

    数据源是运行期 ``blockout_audit_event`` 落盘的审计事件：manifest /
    report / approval，产物本体在 ``data.payload``。同一 kind 多事件取
    **最后一条**（与 ``extract_spatial_snapshots`` 同口径——重放的是最终态）。
    缺事件返回 ``None``——旧日志零形状差，不猜、不伪造。
    """
    #: 事件 kind 与 ``contracts/blockout.blockout_audit_event`` 的闭集同源：
    #: manifest_generated / report_generated / approval_recorded。
    kinds = ("blockout_manifest_generated", "blockout_report_generated",
             "blockout_approval_recorded")
    artifacts: Dict[str, Optional[Dict[str, Any]]] = {
        "manifest": None, "report": None, "approval": None}
    for record in records:
        kind = record.get("kind")
        if kind not in kinds:
            continue
        payload = (record.get("data") or {}).get("payload")
        if not isinstance(payload, dict):
            continue
        if kind == "blockout_manifest_generated":
            artifacts["manifest"] = payload
        elif kind == "blockout_report_generated":
            artifacts["report"] = payload
        elif kind == "blockout_approval_recorded":
            artifacts["approval"] = payload
    return artifacts


def extract_evidence_store(
    records: Sequence[Dict[str, Any]],
    directory: Union[str, Path],
) -> tuple[Optional[EvidenceStore], Dict[str, Any], Dict[str, int]]:
    """Load the exact evidence store and verify its published best pointers."""
    path = ""
    expected: Dict[str, str] = {}
    for record in records:
        data = record.get("data") or {}
        payload = data.get("payload")
        if not isinstance(payload, Mapping):
            continue
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, Mapping) and artifacts.get("evidence_store"):
            path = str(artifacts.get("evidence_store"))
        for key in (
            "best_report_fingerprint",
            "best_manifest_fingerprint",
            "best_world_state_fingerprint",
        ):
            if payload.get(key):
                expected[key] = str(payload[key])
    if not path:
        candidates = (
            Path(directory) / "coarse" / "evidence_store.json",
            Path(directory) / "coarse" / "coarse" / "evidence_store.json",
        )
        path = str(next((item for item in candidates if item.is_file()), ""))
    if not path:
        return None, {
            "status": "missing",
            "reason": "audit log/project has no evidence_store artifact",
            "consistent": False,
        }, {}
    store, status = inspect_evidence_store(path)
    if store is None:
        return None, {**status, "path": path, "consistent": False}, {}
    best = {str(key): int(value)
            for key, value in (store.summary().get("best") or {}).items()}
    mismatches: list[str] = []
    for shot_id, version in sorted(best.items()):
        basis = store.get(shot_id, version).basis_fingerprints
        for key, actual in (
            ("report", basis.get("report_fingerprint")),
            ("manifest", basis.get("manifest_fingerprint")),
            ("world_state", basis.get("world_state_fingerprint")),
        ):
            wanted = expected.get(f"best_{key}_fingerprint")
            if wanted and str(actual or "") != wanted:
                mismatches.append(f"{shot_id}@{version}:{key}")
    return store, {
        **status,
        "path": path,
        "consistent": not mismatches,
        "mismatches": mismatches,
    }, best


def replay(directory: Union[str, Path], registry, *, builder=None,
           spec=None, build: bool = True) -> ReplayReport:
    """按审计日志重放：先按计划建场景，再顺序重放工具调用（不调用 LLM）。"""
    records = read_audit_log(directory)
    plan = extract_plan(records)
    if plan is None:
        raise ReplayError(
            f"审计日志里没有 {PLAN_EVENT} 事件，无法重建：{audit_path(directory)}")

    report = ReplayReport(plan=plan, steps=iter_tool_calls(records))
    brief = extract_brief(records)
    report.brief = brief
    report.brief_source = (getattr(brief, "source", "") if brief is not None
                           else "")

    if build and builder is not None:
        if spec is None:
            # 站位真源：``SceneSpec.from_plan(brief=...)``（v1.4 X5/RK-12）。
            from ..contracts.cast import SceneSpec

            spec = SceneSpec.from_plan(plan, brief=brief)
        #: D1 逐镜路径（§3.6.3）：原跑走 ``scene_prepared`` → 每镜
        #: ``rebuild_shot``，重放必须镜像同一条调用序列——只认日志事件不够，
        #: builder 还必须真的支持 prepare_scene/rebuild_shot（与驱动
        #: ``_supports_prepare_scene`` 同一探测）。否则退回整场单次构建。
        per_shot = (hasattr(builder, "prepare_scene")
                    and hasattr(builder, "rebuild_shot")
                    and any(isinstance(record, dict)
                            and record.get("kind") == "scene_prepared"
                            for record in records))
        if per_shot:
            summary = builder.prepare_scene(plan, brief)
            if hasattr(summary, "to_dict"):
                summary = summary.to_dict()
            summary = dict(summary or {})
            results = list(summary.get("results") or [])
            for shot in plan.shots:
                regen = builder.rebuild_shot(str(shot.shot_id), plan=plan)
                if hasattr(regen, "to_dict"):
                    regen = regen.to_dict()
                regen = dict(regen or {})
                #: 与 driver._step_per_shot 同口径：同镜条目整体替换。
                index = next(
                    (i for i, item in enumerate(results)
                     if isinstance(item, dict)
                     and str(item.get("shot_id")) == str(shot.shot_id)),
                    None)
                if index is None:
                    results.append(regen)
                else:
                    results[index] = regen
                summary["cameras"] = int(
                    (summary.get("cameras") or 0)
                    + (1 if regen.get("camera") else 0))
                summary["motions"] = int(
                    (summary.get("motions") or 0)
                    + (regen.get("motions") or 0))
                summary["keyframes"] = int(
                    (summary.get("keyframes") or 0)
                    + (regen.get("keyframes") or 0))
            summary["results"] = results
        elif callable(builder):
            summary = builder(plan, spec, brief)
            if hasattr(summary, "to_dict"):
                summary = summary.to_dict()
            summary = dict(summary or {})
        elif hasattr(builder, "build"):
            summary = builder.build(plan, brief=brief)
            if hasattr(summary, "to_dict"):
                summary = summary.to_dict()
            summary = dict(summary or {})
        else:
            raise ReplayError(
                "builder 既不可调用，也没有 prepare_scene/rebuild_shot 或 "
                "build，无法重建场景")
        report.summary = summary
        report.built = True

    #: 空间尺观测证据（Ticket 06）：从审计日志抽回的处方/测量回挂到 summary，
    #: 交付层据此重产 ``ruler_observation.json``——无 LLM。只在有证据时出键，
    #: 旧日志零形状差。
    plan_ruler, shot_ruler = extract_ruler_evidence(records)
    if plan_ruler["prescriptions"] or plan_ruler["measurements"]:
        report.summary["ruler_prescriptions"] = plan_ruler["prescriptions"]
        report.summary["ruler_measurements"] = plan_ruler["measurements"]
    if shot_ruler:
        report.summary["ruler_shot_measurements"] = shot_ruler
    #: 空间理解快照（Ticket 08）：三份快照可从审计事件零 LLM 复原，回挂到
    #: summary，交付层据此随重导出落盘。缺事件（旧日志）零形状差。
    spatial_snapshots = extract_spatial_snapshots(records)
    for key, value in (("spatial_design", "design"),
                       ("spatial_observation", "observation"),
                       ("spatial_diff", "diff")):
        if value is not None:
            report.summary[key] = spatial_snapshots[value]
    #: 粗排产物（Ticket 02）：manifest/report/approval 可从审计事件零 LLM
    #: 复原，回挂到 summary，交付层据此随重导出落盘。缺事件零形状差。
    blockout_artifacts = extract_blockout_artifacts(records)
    for key, value in (("blockout_manifest", "manifest"),
                       ("blockout_report", "report"),
                       ("blockout_approval", "approval")):
        if value is not None:
            report.summary[key] = blockout_artifacts[value]
    evidence_store, evidence_status, evidence_best = extract_evidence_store(
        records, directory)
    report.evidence_store = evidence_store
    report.evidence_status = evidence_status
    report.evidence_best = evidence_best
    if evidence_store is not None:
        report.summary["evidence_store"] = evidence_store.to_dict()
    report.summary["evidence_status"] = evidence_status

    known = set(registry.names())
    for step in report.steps:
        if step.tool in CONTROL_TOOLS:
            report.skipped.append(step.tool)
            continue
        if step.tool not in known:
            report.skipped.append(step.tool)
            continue
        result = registry.execute(step.tool, step.args)
        if result.ok:
            report.executed.append(step.tool)
        else:
            report.failures.append({"tool": step.tool, "error": result.error,
                                    "content": result.content})
    return report
