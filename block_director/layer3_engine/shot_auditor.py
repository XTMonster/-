"""镜头审核器（执行文档 v1.2 §7.1 阶段 B3）。

把 :mod:`rule_checker` 包成驱动器需要的 ``ShotAuditor`` 协议。

v1.5 §5.5（卡 P6-T1）叠加一层**可选的 VLM 评审外回路**：`vlm_review.enabled`
缺省 false（此时本文件的行为与 P4-T4 之后逐字节相同）；打开后每镜取首/中/末
三帧交给外部评委打 1–5 分，结果**只挂在** ``AuditResult.vlm_review`` 上，
不参与通过与否。纯逻辑在 :mod:`..contracts.vlm_review`（无 bpy），
这里只做"取帧 + 调用 + 还原现场"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..contracts.audit import AuditResult
from ..contracts.beats import reconcile_justifications
from ..contracts.enums import AuditLevel
from ..contracts.vlm_review import (
    REVIEW_SCHEMA_VERSION,
    frame_data_uri,
    frame_indices,
    review_shot,
    summarise_reviews,
)
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .rule_checker import check_shot
from .scene_context import get_context

log = get_logger("shot-auditor")


class BpyShotAuditor:
    """按当前场景上下文逐镜头审核。"""

    def __init__(self, composition_threshold: float = 70.0,
                 audit_level=None, vlm_review=None,
                 vlm_transport=None,
                 vlm_frame_dir: Optional[Path] = None,
                 vlm_timeout: float = 60.0) -> None:
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

    # ------------------------------------------------------------------ 接线
    def bind_transport(self, transport) -> None:
        """后接传输（headless 通路先建 auditor、后建 transport，见 §5.5）。"""
        self.vlm_transport = transport

    @property
    def vlm_enabled(self) -> bool:
        return bool(getattr(self.vlm_review, "enabled", False))

    def vlm_summary(self) -> Dict[str, Any]:
        return summarise_reviews(self.vlm_reviews)

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
        result = check_shot(shot_id,
                            composition_threshold=self.composition_threshold,
                            strict=strict)
        #: v1.5 §5.4（P4-T4）：把这一镜**声明**的破例辩护与**实测**的违规对拍。
        #: 只记录、不设门——设门属 OPEN_ITEMS D11，须用户裁决（红线 R-5）。
        result.justification_audit = self._reconcile(shot_id, result)
        #: v1.5 §5.5（P6-T1）：外部评审（缺省关）。它**不改** result 的任何
        #: 判定字段，只多挂一条记录。
        review = self._run_vlm_review(shot_id)
        if review is not None:
            result.vlm_review = review
        return result

    # ------------------------------------------------------------- VLM 外回路
    def _run_vlm_review(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """取三帧 → 评一次 → 记账；任何一步不成立都**如实记录跳过**。"""
        if not self.vlm_enabled:
            return None                      # 缺省关：零行为差（单测钉住）
        limit = int(getattr(self.vlm_review, "max_shots", 0) or 0)
        if limit and len(self.vlm_reviews) >= limit:
            record = {"status": "skipped", "reason": "超出 vlm_review.max_shots 上限",
                      "error": "", "attempts": 0,
                      "schema": REVIEW_SCHEMA_VERSION}
            self.vlm_reviews[shot_id] = record
            return record
        if self.vlm_transport is None:
            record = {"status": "skipped", "reason": "没有可用的传输（评委未接线）",
                      "error": "", "attempts": 0,
                      "schema": REVIEW_SCHEMA_VERSION}
            self.vlm_reviews[shot_id] = record
            return record

        context = get_context()
        shot = context.shot(shot_id) if context is not None else None
        span = (context.schedule or {}).get(shot_id) if context is not None else None
        if shot is None or not span:
            record = {"status": "skipped", "reason": "场景里没有这一镜的帧区间",
                      "error": "", "attempts": 0,
                      "schema": REVIEW_SCHEMA_VERSION}
            self.vlm_reviews[shot_id] = record
            return record

        frames = self._render_review_frames(shot_id, span)
        if isinstance(frames, dict):          # 渲染失败：原样带回原因
            self.vlm_reviews[shot_id] = frames
            return frames
        record = review_shot(self.vlm_transport, shot_id=shot_id, frames=frames,
                             intent=str(getattr(shot, "intent", "") or ""),
                             composition=dict(getattr(shot, "composition", None) or {}),
                             timeout=self.vlm_timeout)
        record["frames"] = [label for label, _ in frames]
        self.vlm_reviews[shot_id] = record
        return record

    def _render_review_frames(self, shot_id: str, span):
        """渲染首/中/末三帧并编码成 data URI；失败返回**跳过记录**。"""
        import bpy

        from ..layer8_delivery.renderer import render_first_frame

        context = get_context()
        camera = context.camera_for(shot_id) if context is not None else None
        if camera is None:
            return {"status": "skipped", "reason": "这一镜还没有相机",
                    "error": "", "attempts": 0, "schema": REVIEW_SCHEMA_VERSION}
        scene = bpy.context.scene
        directory = Path(self.vlm_frame_dir) if self.vlm_frame_dir else Path(
            bpy.app.tempdir or ".")
        directory = directory / "vlm_review"
        directory.mkdir(parents=True, exist_ok=True)
        previous_camera = scene.camera
        previous_frame = int(scene.frame_current)
        previous_path = scene.render.filepath
        frames = []
        try:
            scene.camera = camera
            for label, frame in frame_indices(int(span[0]), int(span[1])):
                path = directory / f"{shot_id}_{label}.png"
                if not render_first_frame(scene, frame, str(path)):
                    return {"status": "skipped",
                            "reason": f"评审帧渲染失败（{label}）",
                            "error": str(path), "attempts": 0,
                            "schema": REVIEW_SCHEMA_VERSION}
                frames.append((label, frame_data_uri(path)))
        finally:
            scene.camera = previous_camera
            scene.frame_set(previous_frame)
            scene.render.filepath = previous_path
        return frames

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
