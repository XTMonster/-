"""空间尺转正·相机几何闭环（Ticket 05 内建接缝）。

转正后空间尺不再是"只记录处方"的外挂：``_auto_reframe_from_ruler``
把 guard 的相机几何告警折成确定性 reframe 处方并执行一次（同镜最多
一次，避免修复振荡），执行回写审计事件，失败仍保留原有 LLM 修复回路。

本测试钉住：
* reframe 成功（``ToolResult.ok``）后记 applied 事件；
* reframe 领域失败（``ToolResult.ok=False``）不记 applied、返回 False；
* 同一镜头只自动 reframe 一次（振荡保护）；
* 开关关闭时（``ruler.enabled=False``）不自动 reframe。
"""

from __future__ import annotations

from block_director.contracts.audit import AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer5_orchestrator.tool_registry import ToolResult, ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread


SCRIPT = "INT. 码头市场 - 日\n\n米迦尔和伊恩说话。\n"


class _StubRegistry(ToolRegistry):
    """记录 reframe 调用并返回预设结果的测试替身。"""

    def __init__(self, outcome: ToolResult):
        super().__init__()
        self.outcome = outcome
        self.calls: list = []

    def execute(self, name: str, args, *, wrap: bool = True) -> ToolResult:
        if name == "reframe":
            self.calls.append(dict(args))
            return self.outcome
        return super().execute(name, args, wrap=wrap)


class _Err:
    rule = "COMPOSITION"

    def to_dict(self):
        return {"rule": self.rule}


def _result(shot_id: str, kinds: list[str]) -> AuditResult:
    warnings = [{"type": kind, "subject": "米迦尔", "frame_range": [1, 24],
                 "evidence": {"visible_ratio": 0.0}, "severity": "error"}
                for kind in kinds]
    return AuditResult(passed=False, errors=[_Err()],
                       guard_warnings=warnings, target=shot_id, score=42.0)


def _driver(registry: ToolRegistry, *, ruler_enabled: bool = True) -> PrevisDriver:
    config = AppConfig()
    config.ruler.enabled = ruler_enabled
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=AuditLogger(),
        script=SCRIPT, config=config, registry=registry,
        thread_factory=InlineThread)
    plan = Plan(scene_heading="码头市场")
    plan.shots = [
        ShotPlan("shot_001", "建立", "MS", 96, order=1,
                 camera={"lens": 35.0, "side": "front"},
                 characters=["米迦尔"]),
    ]
    driver.plan = plan
    driver._shot_queue = ["shot_001"]
    driver._current_shot_id = "shot_001"
    #: 限制修复次数避免走到降级分支干扰断言。
    driver._repair_attempts = 0
    driver.limits.max_repairs_per_shot = 3
    return driver


def test_reframe_success_records_applied_event(tmp_path) -> None:
    """reframe 成功 → 审计留 spatial_ruler_reframe_applied。"""
    registry = _StubRegistry(ToolResult(True, "镜头 shot_001 取景已调整"))
    audit = AuditLogger(directory=tmp_path)
    driver = _driver(registry)
    driver.audit = audit
    assert driver._auto_reframe_from_ruler("shot_001", _result("shot_001",
                                                               ["edge_clip"]))
    assert len(registry.calls) == 1
    assert registry.calls[0]["shot_id"] == "shot_001"
    assert registry.calls[0]["lens"] < 35.0          # 收紧
    kinds = [event.kind for event in audit.recent()
             if event.kind.startswith("spatial_ruler_reframe")]
    assert kinds == ["spatial_ruler_reframe_applied"], kinds


def test_reframe_domain_failure_returns_false(tmp_path) -> None:
    """reframe 领域失败（ToolResult.ok=False）→ 不记 applied、返回 False。"""
    registry = _StubRegistry(ToolResult(False, "找不到镜头", error="domain_error"))
    audit = AuditLogger(directory=tmp_path)
    driver = _driver(registry)
    driver.audit = audit
    assert driver._auto_reframe_from_ruler("shot_001", _result("shot_001",
                                                               ["edge_clip"])) is False
    assert len(registry.calls) == 1        # 工具被调用过，但执行结果是失败
    kinds = [event.kind for event in audit.recent()
             if event.kind.startswith("spatial_ruler_reframe")]
    assert kinds == ["spatial_ruler_reframe_failed"], kinds


def test_same_shot_reframes_once() -> None:
    """同一镜只自动 reframe 一次（振荡保护）。"""
    registry = _StubRegistry(ToolResult(True, "镜头 shot_001 取景已调整"))
    driver = _driver(registry)
    result = _result("shot_001", ["occlusion"])
    assert driver._auto_reframe_from_ruler("shot_001", result) is True
    assert driver._auto_reframe_from_ruler("shot_001", result) is False
    assert len(registry.calls) == 1


def test_disabled_ruler_skips_auto_reframe() -> None:
    """ruler.enabled=False → 相机闭环开关关闭（由 _step_checking 消费）。"""
    registry = _StubRegistry(ToolResult(True, "镜头 shot_001 取景已调整"))
    driver = _driver(registry, ruler_enabled=False)
    assert driver._ruler_camera_repair_enabled() is False
    assert driver._ruler_enabled() is False


def test_disabled_ruler_skips_plan_level_gate(tmp_path) -> None:
    """ruler.enabled=False → 计划级接缝零行为差：无处方、无证据、不写审计。"""
    config = AppConfig()
    config.ruler.enabled = False
    audit = AuditLogger(directory=tmp_path)
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit, script=SCRIPT,
        config=config, thread_factory=InlineThread)
    plan = Plan(scene_heading="码头市场")
    plan.shots = [ShotPlan("shot_001", "建立", "MS", 96, order=1)]
    driver.plan = plan

    #: 真正跑一次计划级接缝：关闭时直接放行（返回 True）、不留证据、
    #: 不写 spatial_ruler_plan_audit 审计事件、不折叠 compliance。
    assert driver._ruler_enabled() is False
    assert driver._apply_plan_ruler() is True
    assert driver._ruler_plan_evidence is None
    assert driver._ruler_findings == []
    kinds = [event.kind for event in audit.recent()
             if event.kind.startswith("spatial_ruler_plan_audit")]
    assert kinds == [], kinds
    assert driver._compliance is None
    from block_director.contracts.config import AppConfig as AC

    assert AC().ruler.enabled is True          # 默认仍启用（转正）
