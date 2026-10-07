"""headless 同步驱动（执行文档 v1.2 §2.4 形态 C）。

Modal Operator 在 ``--background`` 下不可用（无 window），因此批处理路径
直接同步驱动同一个 :class:`PrevisDriver`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from ..layer6_audit.audit_logger import AuditLogger
from ..knowledge import KnowledgeClient, default_retriever
from ..contracts.enums import RagBackend
from ..settings import get_config
from ..utils.logger import get_logger
from ..utils.paths import default_project_root, ensure_dir
from .driver import DriverLimits, PrevisDriver
from .states import DriverState
from .transport_factory import make_transport

log = get_logger("headless")


def trace_options(config) -> Dict[str, Any]:
    """§11.3 的 trace 内容与上限（配置里的 ``llm.trace_*``）。"""
    llm = getattr(config, "llm", None)
    if llm is None:
        return {}
    return {"trace_prompts": bool(getattr(llm, "trace_prompts", True)),
            "trace_max_chars": int(getattr(llm, "trace_max_chars", 8000))}


def run_headless(
    script: str = "",
    *,
    offline: bool = True,
    project_dir: Optional[Path] = None,
    config=None,
    poll_interval: float = 0.02,
    max_wall_s: float = 180.0,
    limits: Optional[DriverLimits] = None,
    audit: Optional[AuditLogger] = None,
    builder=None,
    registry=None,
    auditor=None,
    scene_state_provider=None,
    human_gate=None,
    parsed_script=None,
) -> Dict[str, Any]:
    """把状态机跑到终止，返回结果摘要（含审计日志路径）。"""
    config = config or get_config()
    transport, mode = make_transport(config, offline=offline)
    _apply_declarations(transport, parsed_script, config)
    #: v1.5 §5.5（P6-T1）：审核器可能先于传输建好（`tools/run_headless.py`
    #: 在调本函数前就构造了 auditor），外部评审需要同一条传输，这里补挂。
    if auditor is not None and hasattr(auditor, "bind_transport"):
        auditor.bind_transport(transport)

    if audit is None:
        root = Path(project_dir) if project_dir else default_project_root()
        audit = AuditLogger(directory=ensure_dir(root / "runs"),
                            **trace_options(config))
    driver = PrevisDriver(transport=transport, audit=audit, script=script,
                          parsed_script=parsed_script,
                          config=config, limits=limits, builder=builder,
                          registry=registry, auditor=auditor,
                          scene_state_provider=scene_state_provider,
                          human_gate=human_gate,
                          knowledge=_make_knowledge(config, transport, audit))

    log.info("headless 运行开始（模式=%s，run_id=%s）", mode, audit.run_id)
    state = driver.run_to_completion(poll_interval=poll_interval,
                                     max_wall_s=max_wall_s)
    summary = driver.snapshot()
    summary["mode"] = mode
    summary["success"] = state is DriverState.DONE
    summary["audit_log"] = str(audit.audit_path) if audit.audit_path else None
    summary["llm_trace"] = str(audit.trace_path) if audit.trace_path else None
    # 分镜计划是值得持久化的产物，直接带回完整结构（交付层要用）
    summary["plan"] = driver.plan.to_dict() if driver.plan else None
    # §2.4：检索调用与 llm_calls **分列**——把这一格交给交付层（manifest）。
    summary["retrieval_calls"] = int(
        getattr(getattr(driver, "knowledge", None), "retrieval_calls", 0) or 0)
    # E2（§2.3b）的数据源：逐镜"这一镜的检索真的注入了哪几类知识的哪些取值"。
    # 交付层用它写 `movements[].source`；没有它 E2 结构性恒为 0（审查 #21）。
    summary["knowledge_provenance"] = (
        driver.knowledge_provenance()
        if hasattr(driver, "knowledge_provenance") else {})
    # v1.4 §2.3/§3.3：`knowledge_trace.json` **每次运行必写**。它记录这次
    # 到底查了什么（种子 / 命中边 / 打分 / 注入集合）与降级留痕；
    # 没有它，"检索是确定性的"这句话就没有证据。
    summary["knowledge_trace"] = _write_knowledge_trace(
        driver.knowledge,
        Path(project_dir) if project_dir else default_project_root())
    log.info("headless 运行结束：%s（镜头 %s 个）", state.value, summary["shots"])
    return summary


def _write_knowledge_trace(knowledge, directory: Path) -> Optional[str]:
    """把检索器这一轮的 trace 落到 ``<run>/knowledge_trace.json``。"""
    if knowledge is None or not hasattr(knowledge, "trace_payload"):
        return None
    import json

    target = ensure_dir(Path(directory)) / "knowledge_trace.json"
    payload = knowledge.trace_payload()
    from datetime import datetime, timezone

    payload["written_at"] = datetime.now(
        timezone.utc).astimezone().isoformat(timespec="seconds")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return str(target)


def _apply_declarations(transport, parsed_script, config) -> None:
    """把分镜表声明交给离线替身，让它按声明镜数出计划（v1.4 BW-3）。"""
    if parsed_script is None or transport is None:
        return
    setter = getattr(transport, "set_declarations", None)
    if setter is None:
        return
    fps = int(getattr(getattr(config, "animation", None), "fps", 24) or 24)
    setter(getattr(parsed_script, "declared_shots", []) or [], fps=fps)


def _audit_hook(audit):
    """把 ``KnowledgeClient`` 的审计事件写进 run 的 JSONL（§2.4 的分列账本）。"""
    if audit is None or not hasattr(audit, "log"):
        return None

    def hook(payload: Dict[str, Any]) -> None:
        fields = {key: value for key, value in payload.items() if key != "event"}
        audit.log(str(payload.get("event", "retrieval_call")),
                  f"检索：卡片 {fields.get('cards', 0)} / 超边 "
                  f"{fields.get('edges', 0)} / 案例 {fields.get('cases', 0)}",
                  **fields)

    return hook


def _make_knowledge(config, transport=None, audit=None):
    """按 §6.1 / v1.4 §2.3 的确定性选择逻辑装配知识检索器。

    三个上限都从配置读：``rag.max_tokens_per_call``（每镜 800）、
    ``rag.plan_prefetch_tokens``（整场预取 2000）、``rag.top_k``；
    L3 的开关与条数同样从配置读：``rag.cases_backend``（``off`` ＝ 显式关闭，
    第三栏恒空且**不向 sidecar 索要案例**）与 ``rag.cases_top_k``。
    后端默认是超图；**装了 sidecar 客户端就走 ``/v1/retrieve``**（§2.3：超图
    索引与检索跑在 sidecar，插件进程里不需要索引）。没有 sidecar 时检索器
    **自己**降级为 BM25 并置 ``degraded``，由 trace 如实记录。
    """
    rag = getattr(config, "rag", None)
    client = None
    if transport is not None and hasattr(transport, "retrieve_response"):
        client = KnowledgeClient(transport, audit=_audit_hook(audit))
    if rag is None:
        return default_retriever()
    backend = RagBackend.DIGEST if not rag.enabled else RagBackend(str(rag.backend))
    retriever = default_retriever(
        backend=backend, top_k=int(rag.top_k or 5),
        token_limit=int(getattr(rag, "max_tokens_per_call", 800) or 800),
        plan_token_limit=int(getattr(rag, "plan_prefetch_tokens", 2000) or 2000),
        client=client,
        cases_backend=str(getattr(rag, "cases_backend", "lightrag") or "lightrag"),
        cases_top_k=int(getattr(rag, "cases_top_k", 3) or 3),
        #: v1.5 §5.2（FR-6）：每桶的规则条数上限（``rag.rule_top_k``，缺省 5）。
        rule_top_k=int(getattr(rag, "rule_top_k", 5) or 5))
    log.info("Light RAG：%s", retriever.describe())
    return retriever


def brief_from_summary(summary) -> Optional[Any]:
    """把运行摘要里的 SceneBrief（普通字典）还原成契约对象（§3.2）。"""
    payload = (summary or {}).get("brief")
    if not payload:
        return None
    from ..contracts.brief import SceneBrief

    return SceneBrief.from_dict(payload)


def save_run_project(
    summary: Dict[str, Any],
    *,
    out_dir,
    spec=None,
    crowd=None,
    project_name: str = "",
) -> "SavedProject":
    """把一次成功运行的分镜计划落成 ``project.bdproj``（§14）。

    v1.4 §4.4 步骤 1/3：``run_headless.py --save`` 与 ``run_export.py --save``
    共用这一段（此前它只内联在 ``tools/run_headless.py`` 里，步骤 3 无从复用）。
    落盘复用既有的 ``layer9_persistence.project_io.save_project``，**不重定义**。

    v1.5：返回 :class:`SavedProject`（路径 ＋ **落盘那一刻**的 SDL 校验报告）。
    此前 `validate_sdl(sdl)` 的返回值被**直接丢掉**——运行报 `DONE`、文件也写出去，
    而"这份工程过不了自己的校验"要到 `load_project` / `rebuild_project` 或面板
    加载时才发现（实测 2026-10-03 的 64 镜真跑：工程里 26 条 S6）。校验照跑、
    结论照带回；要不要据此拦住什么，是调用方的策略（§14.2 的工作流不能被它挡死）。
    """
    from ..contracts.plan import Plan
    from ..layer2_sdl import build_sdl, validate_sdl
    from ..layer9_persistence import findings_report, save_project

    plan = Plan.from_dict(summary["plan"])
    sdl = build_sdl(
        plan,
        build_summary=summary.get("build"),
        spec=spec,
        project_name=(project_name or plan.scene_heading or "BlockDirector"),
        brief=brief_from_summary(summary),
        # 群众不在计划里（它是场景级设定），落盘时要单独带上，
        # 否则"存了再打开"会丢掉那 30 个路人。
        crowd=crowd,
    )
    findings = validate_sdl(sdl)
    path = save_project(Path(out_dir), sdl)
    report = findings_report(findings, path=str(path))
    if not report["ok"]:
        #: 进日志是为了让**那次运行自己的输出**就带这条事实，而不是等下一次加载。
        log.warning(
            "项目落盘：SDL 校验未通过 %d 条（规则 %s）——文件照写，"
            "但交付前必须看这些 finding",
            len(report["errors"]), "、".join(report["rules"]))
    return SavedProject(path=path, validation=report)


@dataclass(frozen=True)
class SavedProject:
    """一次落盘的产物：文件路径 ＋ 落盘时的 SDL 校验报告。

    ``validation`` 的形状与 ``layer9_persistence.validation_report`` 一致
    （``ok`` / ``errors`` / ``warnings`` / ``rules``），因此"落盘前"与"加载后"
    量的是同一件事。
    """

    path: Path
    validation: Dict[str, Any] = field(default_factory=dict)
