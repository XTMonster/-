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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from ..contracts.plan import Plan
from ..contracts.tools import REPLAY_SKIPPED_TOOLS

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
        summary = builder(plan, spec, brief)
        if hasattr(summary, "to_dict"):
            summary = summary.to_dict()
        report.summary = dict(summary or {})
        report.built = True

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
