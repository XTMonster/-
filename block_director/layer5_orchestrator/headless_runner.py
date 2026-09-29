"""headless 同步驱动（执行文档 v1.2 §2.4 形态 C）。

Modal Operator 在 ``--background`` 下不可用（无 window），因此批处理路径
直接同步驱动同一个 :class:`PrevisDriver`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ..layer6_audit.audit_logger import AuditLogger
from ..knowledge import default_retriever
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
                          knowledge=_make_knowledge(config))

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


def _make_knowledge(config):
    """按 §6.1 / v1.4 §2.3 的确定性选择逻辑装配知识检索器。

    三个上限都从配置读：``rag.max_tokens_per_call``（每镜 800）、
    ``rag.plan_prefetch_tokens``（整场预取 2000）、``rag.top_k``。
    后端默认是超图；没有 sidecar（``capabilities`` 里没有 ``hypergraph``）时
    检索器**自己**降级为 BM25 并置 ``degraded``，由 trace 如实记录。
    """
    rag = getattr(config, "rag", None)
    if rag is None:
        return default_retriever()
    backend = RagBackend.DIGEST if not rag.enabled else RagBackend(str(rag.backend))
    retriever = default_retriever(
        backend=backend, top_k=int(rag.top_k or 5),
        token_limit=int(getattr(rag, "max_tokens_per_call", 800) or 800),
        plan_token_limit=int(getattr(rag, "plan_prefetch_tokens", 2000) or 2000))
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
) -> Path:
    """把一次成功运行的分镜计划落成 ``project.bdproj``（§14）。

    v1.4 §4.4 步骤 1/3：``run_headless.py --save`` 与 ``run_export.py --save``
    共用这一段（此前它只内联在 ``tools/run_headless.py`` 里，步骤 3 无从复用）。
    落盘复用既有的 ``layer9_persistence.project_io.save_project``，**不重定义**。
    """
    from ..contracts.plan import Plan
    from ..layer2_sdl import build_sdl, validate_sdl
    from ..layer9_persistence import save_project

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
    validate_sdl(sdl)
    return save_project(Path(out_dir), sdl)
