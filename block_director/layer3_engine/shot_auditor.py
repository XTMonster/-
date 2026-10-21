"""镜头审核器（执行文档 v1.2 §7.1 阶段 B3）。

把 :mod:`rule_checker` 包成驱动器需要的 ``ShotAuditor`` 协议。

v1.5 §5.5（卡 P6-T1）叠加一层**可选的 VLM 评审外回路**：`vlm_review.enabled`
缺省 false（此时本文件的行为与 P4-T4 之后逐字节相同）；打开后每镜取首/中/末
三帧交给外部评委打 1–5 分，结果**只挂在** ``AuditResult.vlm_review`` 上，
不参与通过与否。纯逻辑在 :mod:`..contracts.vlm_review`（无 bpy），
这里只做"取帧 + 调用 + 还原现场"。

v1.6 B4（FR-C5 / D-13）：`audit()` 在规则判定之后用
:mod:`.frustum_sampler.sample_shot` 对整镜采样，把聚合后的
``GuardWarning[]``（含数值证据）挂到 ``AuditResult.guard_warnings``——
**与构图分并置，不只给一个分数**（E-video P1-1：模型拿到分数修不动）。
error 级告警额外落一条 ``AuditError`` finding 让这一镜失败；warning/info
只挂不判（裁决在修复回路，卡 B4 的 reframe 菜单）。采样失败按
``E_GUARD_001`` 事件记录（``guard_sampling_error``），绝不静默吞掉。
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..cinema.frustum_metrics import DeclaredShot, guard_config_from, shot_warnings
from ..cinema.spatial_digest import COLLISION_MARGIN, scene_digest
from ..contracts.quality import COMPOSITION_PASS_SCORE as PASS_SCORE
from ..contracts.audit import AuditError, AuditResult
from ..contracts.beats import (
    front_occlusion_declared_from_justifications,
    reconcile_justifications,
)
from ..contracts.enums import AuditLevel, Severity
from ..contracts.guard import Severity as GuardSeverity
from ..contracts.guard import merge_occlusion_evidence
from ..contracts.observation import describe_frame_record
from ..contracts.tools import ACTION_TOOLS, SHOT_DRAFT_TOOL
from ..contracts.vlm_capability import classify_capability
from ..contracts.vlm_review import (
    VLM_REVIEW_SCHEMA_V2,
    disposition,
    frame_data_uri,
    frame_indices,
    review_shot,
    summarise_reviews,
)
from ..layer5_orchestrator.repair import build_vlm_guard_summary, guard_warning_line
from ..settings import get_config
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .frustum_sampler import SamplingError, _subject_id, sample_shot, sample_spatial
from .cinema_engine.composition_guide import _belongs_to, occluder_class
from .rule_checker import (check_shot, configure_camera_limits,
                           configure_prompt_conflict_check,
                           configure_rules_disabled, configure_scale_drift)
from .scene_context import get_context

log = get_logger("shot-auditor")

#: v1.6 B4：声明了"改变景别"的运镜——镜内占比变化是设计，不算 size_drift。
SIZE_CHANGING_MOVEMENTS = frozenset({
    "dolly_in", "dolly_out", "push_through", "dolly_zoom",
    "zoom_in", "zoom_out", "crane_up", "crane_down",
    "crane_arc_up", "crane_arc_down",
})

class _LastReplyTransport:
    """包装评委传输：记下最后一次回复（拿 raw 与模型名，不改 ``review_shot``）。"""

    def __init__(self, transport) -> None:
        self._transport = transport
        self.last_content = None
        self.last_reply = None

    def chat(self, payload, timeout: float = 60.0):
        reply = self._transport.chat(payload, timeout=timeout)
        self.last_reply = reply
        self.last_content = getattr(reply, "content", None)
        return reply


class BpyShotAuditor:
    """按当前场景上下文逐镜头审核。"""

    def __init__(self, composition_threshold: float = PASS_SCORE,
                 audit_level=None, vlm_review=None,
                 vlm_transport=None,
                 vlm_frame_dir: Optional[Path] = None,
                 vlm_timeout: float = 60.0,
                 audit=None) -> None:
        self.composition_threshold = composition_threshold
        #: v1.4 §3.4：strict 档把 R019（银幕方向翻转）从 WARNING 升为 ERROR。
        self.audit_level = audit_level
        #: v1.5 §5.5（P6-T1）：``AppConfig.vlm_review``（``enabled`` /
        #: ``max_shots``）。``None`` ＝ 没接线，等价于 enabled=False。
        self.vlm_review = vlm_review
        #: 评审走**同一条**传输（sidecar/直连都由它决定）；未注入 ⇒ 跳过并记录。
        self.vlm_transport = vlm_transport
        self.vlm_frame_dir = Path(vlm_frame_dir) if vlm_frame_dir else None
        self.vlm_timeout = float(vlm_timeout)
        #: 逐镜记录（``shot_id -> 记录``）。面板/交付层读它。
        self.vlm_reviews: Dict[str, Dict[str, Any]] = {}
        #: 卡 V3：每镜每轮的记录（含 skipped）。``shot_id -> [记录]``，每条带
        #: ``round``；重审豁免与 disposition 只读这一份，不再数 ``vlm_reviews``。
        self.vlm_history: Dict[str, List[Dict[str, Any]]] = {}
        #: 卡 V3：能力探测缓存。None=未定；True/False=首次评审已出结论。
        self._capability_cached: Optional[bool] = None
        #: 卡 V3：审计日志接线（可为 None ⇒ 事件落 ``vlm_events``，不丢）。
        self._audit = audit
        self.vlm_events: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ 接线
    def bind_transport(self, transport) -> None:
        """后接传输（headless 通路先建 auditor、后建 transport，见 §5.5）。"""
        self.vlm_transport = transport

    def bind_audit(self, audit) -> None:
        """后接审计日志（headless 通路先建 auditor、后建 audit，卡 V3）。"""
        self._audit = audit

    @property
    def vlm_enabled(self) -> bool:
        return bool(getattr(self.vlm_review, "enabled", False))

    def vlm_summary(self) -> Dict[str, Any]:
        return summarise_reviews(self.vlm_reviews)

    def audit_json(self, shot_id: str) -> Dict[str, Any]:
        """空间尺统一审核入口：返回稳定 JSON，不让调用方依赖 Blender 对象。

        ``audit`` 仍是内部实现；插件、面板和外部回放统一消费这个结构，
        这样原审核器的规则、视锥告警、几何测量和 VLM 留痕都进入同一份
        空间尺数据，而不是各自维护一套结果格式。
        """
        result = self.audit(shot_id)
        payload = result.to_dict()
        payload.update({
            "schema_version": "spatial-ruler-audit/v1",
            "shot_id": str(shot_id),
            "source": "BlockDirector.audit",
            "verdict": "pass" if result.passed else "fail",
            "metrics": list(result.ruler_measurements or []),
            "findings": [item.to_dict() for item in
                          [*result.errors, *result.warnings]],
            "guard": {
                "warnings": [item.to_dict() if hasattr(item, "to_dict")
                             else dict(item)
                             for item in result.guard_warnings],
                "frames_sampled": int(result.guard_frames_sampled),
                "sampling_error": result.guard_sampling_error,
            },
            "ruler_review": (dict(result.ruler_review)
                             if result.ruler_review is not None else None),
            "repair": {"candidates": [
                {"operation": "reframe", "reasons": [
                    str(item.get("type") if isinstance(item, dict)
                        else getattr(item, "type", ""))
                    for item in result.guard_warnings
                    if str(item.get("type") if isinstance(item, dict)
                           else getattr(item, "type", "")) in {
                               "subject_not_visible", "edge_clip",
                               "framing_too_tight", "framing_too_loose",
                               "occlusion", "subject_out_of_frame"}],
                 "status": "pending"},
            ]},
        })
        return payload

    def shot_ids(self) -> List[str]:
        context = get_context()
        if context is None:
            return []
        if context.plan is not None:
            return [shot.shot_id for shot in context.plan.shots
                    if shot.shot_id in context.cameras]
        return sorted(context.cameras)

    @main_thread_only("BpyShotAuditor.audit")
    def audit(self, shot_id: str) -> AuditResult:
        strict = str(self.audit_level or "") == str(AuditLevel.STRICT)
        #: v1.7 F1：每次审核前把配置的禁用规则注入 rule_checker（模块级集合，
        #: 不 import settings 单例——依赖方向由这里单向同步）。
        config = get_config()
        configure_rules_disabled(
            getattr(getattr(config, "audit", None), "rules_disabled", []) or [])
        #: v1.7 J1（R020）：同步跨镜比例漂移阈值（模块级注入，与 F1 同款——
        #: 不 import 插件侧 settings 单例，由审核入口单向同步）。
        configure_scale_drift(float(getattr(config.guard, "scale_drift", 0.05)))
        #: v1.7 J2（R021–R023）：同步相机运动阈值与 unit 换算帧率（照 J1 同款：
        #: 由审核入口单向注入，非法值回落默认）。cam_accel_max 单位 m/s²。
        configure_camera_limits(
            getattr(config.guard, "cam_accel_max", 8.0),
            compound_max=getattr(config.guard, "compound_motion_max", 2),
            fps=getattr(getattr(config, "animation", None), "fps", 24))
        #: v1.7 J4（R025）：同步实测运镜开关注入（照 J1/J2 同款——由审核
        #: 入口单向同步；默认关 ⇒ ``measured_camera`` 不出键，零形状差）。
        configure_prompt_conflict_check(
            getattr(config.guard, "prompt_conflict_check", False))
        result = check_shot(shot_id,
                            composition_threshold=self.composition_threshold,
                            strict=strict)
        #: v1.7 空间尺转正：在规则判定之后**一次采样**同时采集本镜的观测
        #: 测量（相机/构图/包围盒/角差，契约层 measurement 形状）与六层
        #: 评测（``RulerReview``，逐镜五层 + continuity 如实标未核验）。
        #: 只读、幂等，失败按空表处理（如实缺）；两者都不参与 passed/score，
        #: 但 ``ruler_review.hard_gates`` 由驱动器在 CHECKING 阶段作新增
        #: 阻断条件（旧 passed 之后再查）。
        try:
            from .ruler_probe import collect_shot_review
            measurements, review = collect_shot_review(shot_id)
            result.ruler_measurements = measurements or None
            result.ruler_review = review
        except Exception:  # noqa: BLE001 - 测量缺失不伪造，也不阻断审核
            result.ruler_measurements = None
            result.ruler_review = None
        #: v1.6 B4：视锥采样告警与构图分**并置**；error 级告警让这一镜失败。
        self._attach_guard_warnings(shot_id, result)
        #: v1.5 §5.4（P4-T4）：把这一镜**声明**的破例辩护与**实测**的违规对拍。
        #: 只记录、不设门——设门属 OPEN_ITEMS D11，须用户裁决（红线 R-5）。
        result.justification_audit = self._reconcile(shot_id, result)
        #: v1.5 §5.5（P6-T1）：外部评审（缺省关）。它**不改** result 的任何
        #: 判定字段，只多挂一条记录。
        review = self._run_vlm_review(shot_id, result)
        if review is not None:
            result.vlm_review = review
        return result

    # ------------------------------------------------------------ 视锥告警（B4）
    @staticmethod
    def _declared_shot(shot_id: str, plan_shot, context) -> DeclaredShot:
        """把计划里的声明折成 ``DeclaredShot``（意图比对的输入）。"""
        shot_type = ""
        if plan_shot is not None:
            declared_type = getattr(plan_shot, "shot_type", None)
            shot_type = (getattr(declared_type, "value", None)
                         or str(declared_type or ""))
        if not shot_type and context is not None:
            shot_type = str(context.shot_types.get(shot_id, ""))
        camera = dict(getattr(plan_shot, "camera", None) or {})
        movements = [dict(item) for item in camera.get("movements", [])
                     if isinstance(item, dict)]
        size_change = any(str(item.get("type") or "")
                          in SIZE_CHANGING_MOVEMENTS for item in movements)
        return DeclaredShot(
            shot_id=str(shot_id), shot_type=shot_type,
            subject="",                      # 全部声明主体一起测
            intent=str(getattr(plan_shot, "intent", "") or ""),
            front_occlusion_declared=front_occlusion_declared_from_justifications(
                getattr(plan_shot, "rule_justifications", None) or []),
            size_change_declared=size_change)

    @staticmethod
    def _guard_finding(warning) -> AuditError:
        """error 级告警 → 一条可进修复提示的 finding（数值证据在消息里）。"""
        evidence = " ".join(
            f"{key}={value:g}" for key, value in warning.evidence.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool))
        return AuditError(
            rule=str(warning.type),
            code="",
            message=(f"视锥告警 {warning.type}（{warning.subject}，帧 "
                     f"{warning.frame_range[0]}-{warning.frame_range[1]}）："
                     f"{evidence}").strip(),
            severity=Severity.ERROR,
            target=str(warning.subject),
            suggestion=str(warning.suggestion_hint or ""))

    def _attach_guard_warnings(self, shot_id: str, result: AuditResult) -> None:
        """采样 → 聚合 → 挂 ``guard_warnings``；error 级落 finding 让镜头失败。

        occlusion 告警额外合并面级 per-part 遮挡归因（``evidence
        ["occlusion_by_part"]``，来自 ``mesh_visibility_report.parts``）。
        只喂结构化证据、不设门：判定/阈值在 ``frustum_metrics`` 与规则层。
        """
        result.guard_warnings = []
        result.guard_frames_sampled = 0
        config = get_config()
        if not bool(getattr(config.guard, "enabled", False)):
            return                      # 用户关闭 guard：采样与告警都不跑（非降级）
        context = get_context()
        plan_shot = context.shot(shot_id) if context is not None else None
        declared = self._declared_shot(shot_id, plan_shot, context)
        try:
            samples = sample_shot(shot_id)
        except SamplingError as exc:
            #: E_GUARD_001 是事件：记录后规则判定照常，不把采样故障伪装成通过。
            result.guard_sampling_error = {"code": exc.code, "message": str(exc)}
            log.warning("镜头 %s 视锥采样失败：%s", shot_id, exc)
            return
        if not samples:
            return                      # 空镜：合法，无主体可采样
        result.guard_frames_sampled = len({sample.frame for sample in samples})
        warnings = shot_warnings(samples, declared, guard_config_from(config))
        result.guard_warnings = list(warnings)
        #: 交接清单第 4 项：面级 per-part 归因只进过 VLM 评委提示，没进
        #: 结构化 ``GuardWarning.evidence``。有 occlusion 告警才重算一次
        #: 面级几何（避免每镜无条件多跑一遍网格射线），并按主体 id 合并。
        span = (context.schedule or {}).get(shot_id) if context is not None else None
        if span and any(w.type == "occlusion" for w in warnings):
            _, parts_by_subject = self._mesh_visibility_block(shot_id, span)
            for warning in warnings:
                if warning.type != "occlusion":
                    continue
                merge_occlusion_evidence(
                    warning,
                    parts_by_subject.get(str(warning.subject), {}))
        for warning in warnings:
            if warning.severity is not GuardSeverity.ERROR:
                continue
            result.errors.append(self._guard_finding(warning))
            result.passed = False
        #: 卡 V12：采样成功后，把画面/空间测量摘要挂上（只进 VLM 评审提示与
        #: 修复提示，不进任何门——放这在判定字段定稿之后，摘要生成绝不改判）。
        self._attach_scene_digest(shot_id, result, samples, context)

    def _attach_scene_digest(self, shot_id: str, result: AuditResult,
                             samples, context) -> None:
        """画面/空间摘要（卡 V12）：首/中/末目标帧各自取最近的已采样帧。

        三帧口径与 :func:`contracts.vlm_review.frame_indices` 同源；每个目标帧
        取 ``|sampled - target|`` 最小的已采样帧（并列取小帧），相邻去重。
        ``sample_spatial`` 抛 :class:`SamplingError` ⇒ 不生成摘要，错误写进
        ``result.guard_sampling_error``（同形状；已有值则保留原值，不覆盖、
        不吞掉、不改判定）。safe_action/safe_title 读 ``config.guard`` 的 V11
        两个新键，collision_margin 用 ``spatial_digest.COLLISION_MARGIN``。
        """
        span = (context.schedule or {}).get(shot_id)
        if not span:
            return
        sampled_frames = sorted({int(sample.frame) for sample in samples})
        if not sampled_frames:
            return
        targets = [frame for _, frame in
                   frame_indices(int(span[0]), int(span[1]))]
        picked: List[int] = []
        for target in targets:
            nearest = min(sampled_frames,
                          key=lambda frame: (abs(frame - target), frame))
            if not picked or picked[-1] != nearest:
                picked.append(nearest)
        config = get_config()
        try:
            spatial = sample_spatial(shot_id, picked)
        except SamplingError as exc:
            if result.guard_sampling_error is None:
                result.guard_sampling_error = {"code": exc.code,
                                               "message": str(exc)}
            log.warning("镜头 %s 空间采样失败：%s", shot_id, exc)
            return
        result.scene_digest = scene_digest(
            samples, spatial,
            safe_action=float(config.guard.safe_area_action),
            safe_title=float(config.guard.safe_area_title),
            collision_margin=COLLISION_MARGIN)

    # ------------------------------------------------------------- VLM 外回路
    def _log_event(self, kind: str, message: str, **fields: Any) -> None:
        """写 VLM 事件：有 audit 走 ``audit.log``；没有就落 ``vlm_events``。"""
        audit = getattr(self, "_audit", None)
        if audit is None:
            self.vlm_events.append(
                {"kind": kind, "message": message, "level": "info", **fields})
            return
        audit.log(kind, message, level="info", **fields)

    @staticmethod
    def _skipped_record(reason: str) -> Dict[str, Any]:
        """评审一律走 v2 口径的跳过记录（卡 V3：含 skipped 也进逐轮记录）。"""
        return {"status": "skipped", "reason": reason, "error": "",
                "attempts": 0, "schema": VLM_REVIEW_SCHEMA_V2}

    def _run_vlm_review(self, shot_id: str,
                        result: AuditResult) -> Optional[Dict[str, Any]]:
        """评一轮 → 逐轮记账（含 skipped）；任何一步不成立都**如实记录**。"""
        if not self.vlm_enabled:
            return None                      # 缺省关：零行为差（单测钉住）
        round_no = len(self.vlm_history.get(shot_id) or []) + 1
        vision_capable = getattr(self.vlm_review, "vision_capable", "auto")
        if vision_capable == "false":
            record = self._skipped_record(
                "主模型不支持图像输入（配置 vision_capable=false）")
            raw = ""
        elif vision_capable == "auto" and self._capability_cached is False:
            record = self._skipped_record("主模型不支持图像输入（自动探测）")
            raw = ""
        else:
            record, raw = self._attempt_review(shot_id, result, round_no,
                                               vision_capable)
        record["round"] = round_no
        self.vlm_history.setdefault(shot_id, []).append(record)
        latest = dict(record)
        latest["rounds"] = copy.deepcopy(self.vlm_history[shot_id])
        latest["disposition"] = disposition(self.vlm_history[shot_id])
        self.vlm_reviews[shot_id] = latest
        self._log_event(
            "vlm_review_round",
            f"{shot_id} VLM 评审第 {round_no} 轮",
            shot_id=shot_id, round=round_no,
            schema=str(record.get("schema") or ""),
            raw=raw, parsed=dict(record))
        return latest

    def _attempt_review(self, shot_id: str, result: AuditResult, round_no: int,
                        vision_capable) -> Tuple[Dict[str, Any], str]:
        """按 max_shots / 传输 / 帧区间 / 轮数 / 渲染依次把关，评这一轮。

        返回 ``(record, raw)``：record 是**尚未加 round** 的逐轮记录；raw 是
        transport 回复正文（skipped 时 ``""``，卡 V3）。
        """
        limit = int(getattr(self.vlm_review, "max_shots", 0) or 0)
        if limit and round_no == 1 and len(self.vlm_history) >= limit:
            return (self._skipped_record("超出 vlm_review.max_shots 上限"), "")
        if self.vlm_transport is None:
            return (self._skipped_record("没有可用的传输（评委未接线）"), "")
        context = get_context()
        shot = context.shot(shot_id) if context is not None else None
        span = (context.schedule or {}).get(shot_id) if context is not None else None
        if shot is None or not span:
            return (self._skipped_record("场景里没有这一镜的帧区间"), "")
        max_rounds = int(getattr(self.vlm_review, "max_rounds_per_shot", 3) or 3)
        if round_no > max_rounds:
            return (self._skipped_record(
                f"已达 vlm_review.max_rounds_per_shot={max_rounds} 上限"), "")

        rendered = self._render_review_frames(shot_id, span)
        if isinstance(rendered, dict):        # 渲染失败：原样带回原因
            record = dict(rendered)
            record["schema"] = VLM_REVIEW_SCHEMA_V2
            return (record, "")
        frames, frame_records = rendered
        #: 卡 V3：评审一律走 v2——主体 id 与视锥采样同口径，工具是动作工具
        #: + 重提草案；本镜无主体 ⇒ 空元组（仍是 v2）。
        subjects = tuple(_subject_id(subject)
                         for subject in context.subjects_for(shot_id))
        tools = ACTION_TOOLS + (SHOT_DRAFT_TOOL,)
        guard_summary = "\n".join(
            guard_warning_line(warning)
            for warning in (result.guard_warnings or [])
            if str(getattr(getattr(warning, "severity", None), "value", "")
                   or getattr(warning, "severity", "")) in ("error", "warning"))
        #: 卡 V12：有摘要时把告警行 → 画面行 → 空间行拼成同一段"几何测量事实"
        #: （拼接与 1800 字整行上限在纯层 repair.build_vlm_guard_summary 里）。
        if isinstance(result.scene_digest, dict) and result.scene_digest:
            guard_summary = build_vlm_guard_summary(guard_summary,
                                                    result.scene_digest)
        #: 用户 2026-10-11：网格可见性（顶点/面 × 视锥 × 头/躯干/腿）也进
        #: 评委提示——给多模态评委看画面的同时带上结构化几何读数。
        mesh_block, _parts = self._mesh_visibility_block(shot_id, span)
        if mesh_block:
            guard_summary = (guard_summary + "\n" + mesh_block
                             if guard_summary else mesh_block)
        vlm_max_tokens = int(getattr(self.vlm_review, "max_tokens", 0) or 0)
        wrapper = _LastReplyTransport(self.vlm_transport)
        record = review_shot(wrapper, shot_id=shot_id, frames=frames,
                             intent=str(getattr(shot, "intent", "") or ""),
                             composition=dict(getattr(shot, "composition", None) or {}),
                             timeout=self.vlm_timeout,
                             max_tokens=vlm_max_tokens if vlm_max_tokens > 0 else None,
                             subjects=subjects, tools=tools,
                             guard_summary=guard_summary,
                             frame_records=frame_records,
                             measurements=self._review_measurements(result))
        record["frames"] = [label for label, _ in frames]
        raw = ((wrapper.last_content or "")
               if record.get("status") == "ok" else "")
        if vision_capable == "auto" and self._capability_cached is None:
            capability = classify_capability(record)
            if capability is not None:
                self._capability_cached = capability
                evidence = ("首次评审成功" if capability
                            else str(record.get("error") or "")[:200])
                model = getattr(wrapper.last_reply, "model", "") or ""
                self._log_event(
                    "vlm_capability",
                    "VLM 评委能力探测："
                    + ("支持图像输入" if capability else "不支持图像输入"),
                    model=model, supports_image=capability, evidence=evidence)
        return (record, raw)

    def _render_review_frames(self, shot_id: str, span):
        """Render the exact grid images sent to the judge with their evidence."""
        import bpy

        from ..layer8_delivery.renderer import render_first_frame

        context = get_context()
        camera = context.camera_for(shot_id) if context is not None else None
        if camera is None:
            return {"status": "skipped", "reason": "这一镜还没有相机",
                    "error": "", "attempts": 0,
                    "schema": VLM_REVIEW_SCHEMA_V2}
        scene = bpy.context.scene
        directory = Path(self.vlm_frame_dir) if self.vlm_frame_dir else Path(
            bpy.app.tempdir or ".")
        directory = directory / "vlm_review"
        directory.mkdir(parents=True, exist_ok=True)
        previous_camera = scene.camera
        previous_frame = int(scene.frame_current)
        previous_path = scene.render.filepath
        grid_frames = bool(getattr(self.vlm_review, "grid_frames", True))
        frames = []
        frame_records = []
        try:
            scene.camera = camera
            for label, frame in frame_indices(int(span[0]), int(span[1])):
                path = directory / f"{shot_id}_{label}.png"
                if not render_first_frame(scene, frame, str(path)):
                    return {"status": "skipped",
                            "reason": f"评审帧渲染失败（{label}）",
                            "error": str(path), "attempts": 0,
                            "schema": VLM_REVIEW_SCHEMA_V2}
                if grid_frames:
                    #: 用户裁决（2026-10-11）：九宫格**图像版**——评委收到
                    #: 带三分线的诊断帧；交付成片不受影响（副本文件）。
                    from ..overlay.grid_frame import grid_frame_file

                    path = Path(grid_frame_file(str(path)))
                frames.append((label, frame_data_uri(path)))
                frame_records.append(describe_frame_record({
                    "shot_id": str(shot_id),
                    "frame": int(frame),
                    "phase": str(label),
                    "path": str(path),
                }))
        finally:
            scene.camera = previous_camera
            scene.frame_set(previous_frame)
            scene.render.filepath = previous_path
        return frames, frame_records

    @staticmethod
    def _review_measurements(result: AuditResult) -> Dict[str, Any]:
        """Program facts shown beside the VLM opinion in immutable evidence."""
        warnings = []
        for warning in (result.guard_warnings or []):
            if hasattr(warning, "to_dict"):
                warnings.append(copy.deepcopy(warning.to_dict()))
            elif isinstance(warning, dict):
                warnings.append(copy.deepcopy(warning))
        return {
            "program_passed": bool(result.passed),
            "program_score": result.score,
            "ruler_measurements": copy.deepcopy(
                result.ruler_measurements or []),
            "scene_digest": copy.deepcopy(result.scene_digest or {}),
            "guard_warnings": warnings,
            "guard_frames_sampled": int(result.guard_frames_sampled or 0),
            "guard_sampling_error": copy.deepcopy(
                result.guard_sampling_error or {}),
        }

    def _mesh_visibility_block(self, shot_id: str, span
                               ) -> Tuple[str, Dict[str, Dict[str, Any]]]:
        """本镜首帧的角色网格 × 视锥可见性读数（纯层 ``mesh_visibility``）。

        返回 ``(text, parts_by_subject)``：text 是给 VLM 评委的提示块；第二元是
        ``{subject_id: report["parts"]}``，供 occlusion 告警的结构化 evidence
        合并（交接清单第 4 项）。没有任何主体/网格 ⇒ ``("", {})``。
        """
        import bpy
        import math
        from mathutils import Vector

        from ..cinema.mesh_visibility import (
            mesh_visibility_report,
            render_report,
        )

        context = get_context()
        camera = context.camera_for(shot_id)
        data = getattr(camera, "data", None) if camera is not None else None
        if camera is None or data is None or not span:
            return ("", {})
        scene = bpy.context.scene
        previous_frame = int(scene.frame_current)
        try:
            scene.frame_set(int(span[0]))
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = camera.evaluated_get(depsgraph)
            matrix = evaluated.matrix_world
            position = tuple(float(value) for value in matrix.translation)
            forward = -(matrix.to_3x3() @ Vector((0.0, 0.0, 1.0)))
            up = matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))
            vfov = math.degrees(float(getattr(data, "angle_x", 0.0) or 0.0))
            resolution_x = max(1, int(scene.render.resolution_x or 1280))
            resolution_y = max(1, int(scene.render.resolution_y or 720))
            blocks = []
            parts_by_subject: Dict[str, Dict[str, Any]] = {}
            plan_shot = context.shot(shot_id) if context is not None else None
            occlusion_declared = (
                front_occlusion_declared_from_justifications(
                    getattr(plan_shot, "rule_justifications", None) or [])
                if plan_shot is not None else False)
            for subject in context.subjects_for(shot_id):
                objects = getattr(subject, "all_objects", None)
                vertices: List[Tuple[float, float, float]] = []
                faces: List[Tuple[int, int, int]] = []
                for obj in (objects() if callable(objects)
                            else list(objects or [])):
                    if getattr(obj, "type", "") != "MESH":
                        continue
                    obj_eval = obj.evaluated_get(depsgraph)
                    mesh = obj_eval.to_mesh()
                    if mesh is None:
                        continue
                    try:
                        base = len(vertices)
                        world = obj_eval.matrix_world
                        for vertex in mesh.vertices:
                            point = world @ vertex.co
                            vertices.append((float(point.x), float(point.y),
                                             float(point.z)))
                        for polygon in mesh.polygons:
                            indices = [base + int(index)
                                       for index in polygon.vertices]
                            for offset in range(1, len(indices) - 1):
                                faces.append((indices[0], indices[offset],
                                              indices[offset + 1]))
                    finally:
                        obj_eval.to_mesh_clear()
                if not vertices:
                    continue

                def occluder_at(point, _scene=scene, _depsgraph=depsgraph,
                                _position=position, _context=context,
                                _subject=subject):
                    """首交命中**本主体** ⇒ 可见（自遮挡不算）；否则报类别。"""
                    direction = Vector(point) - Vector(_position)
                    distance = direction.length
                    if distance < 1e-6:
                        return None
                    hit = _scene.ray_cast(
                        _depsgraph, Vector(_position),
                        direction.normalized(),
                        distance=max(distance - 1e-4, 0.0))
                    if not hit[0] or hit[4] is None:
                        return None
                    blocker = hit[4]
                    if _belongs_to(blocker, _subject):
                        return None
                    return occluder_class(
                        blocker,
                        getattr(_context, "characters", None) or {})

                report = mesh_visibility_report(
                    position=position,
                    forward=(float(forward.x), float(forward.y),
                             float(forward.z)),
                    up=(float(up.x), float(up.y), float(up.z)),
                    vfov_deg=vfov,
                    aspect=resolution_x / resolution_y,
                    near=float(getattr(data, "clip_start", 0.1) or 0.1),
                    far=float(getattr(data, "clip_end", 100.0) or 100.0),
                    vertices=vertices, faces=faces,
                    occluder_at=occluder_at)
                blocks.append(render_report(
                    report, subject=str(_subject_id(subject)),
                    occlusion_declared=occlusion_declared))
                parts_by_subject[str(_subject_id(subject))] = dict(report.get(
                    "parts") or {})
            return ("\n".join(blocks), parts_by_subject)
        finally:
            scene.frame_set(previous_frame)

    def _reconcile(self, shot_id: str, result: AuditResult):
        """声明 vs 实测的对拍（纯计算；找不到镜头时声明集为空，不猜）。"""
        context = get_context()
        plan = getattr(context, "plan", None) if context is not None else None
        shot = None
        for candidate in (getattr(plan, "shots", None) or []):
            if str(getattr(candidate, "shot_id", "")) == str(shot_id):
                shot = candidate
                break
        declared = getattr(shot, "rule_justifications", None) or []
        detected = [str(item.rule) for item in
                    (list(result.errors) + list(result.warnings))
                    if getattr(item, "rule", "")]
        return reconcile_justifications(declared, detected)
