"""空间尺相机闭环补盲（R2 缺口 #3）：headroom_off 进入自动 reframe。

真跑证据（docs/evidence/20261019-r2-market-coin-full）：shot_001 构图
53 → 79.5 是 edge_clip/framing_too_tight 的自动 reframe 功劳；剩下
0.5 分差在 headroom_off（头顶留白过多）与 thirds_deviation，但这两个
guard 类型不在 ``_auto_reframe_from_ruler`` 的触发集合里，只能等 LLM
修复——真跑里 LLM 修复请求 190s 未返回被 wall 900 掐断，分数停在 79.5。

本测试钉住：headroom_off 必须能触发确定性 reframe（把 79.5 的最后一步
从"依赖慢速 LLM"改为"空间尺确定性修复"），thirds_deviation 保持不自动
reframe（它是 info 级、且模型可用 ACCEPT 声明刻意偏心构图，误伤导演
意图是降级）。
"""

from __future__ import annotations

from block_director.contracts.audit import AuditResult
from block_director.contracts.config import AppConfig
from block_director.contracts.plan import Plan, ShotPlan
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.tool_registry import ToolResult, ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver import InlineThread
from test_ruler_internal_camera_repair import _driver, _result


def test_headroom_off_triggers_auto_reframe(tmp_path) -> None:
    """headroom_off（warning 级）→ 自动 reframe 被调用并留 applied 事件。"""
    registry = _StubRegistry(ToolResult(True, "镜头 shot_001 取景已调整"))
    audit = AuditLogger(directory=tmp_path)
    driver = _driver(registry)
    driver.audit = audit
    result = _result_with_kind("shot_001", "headroom_off", severity="warning")
    assert driver._auto_reframe_from_ruler("shot_001", result) is True
    assert len(registry.calls) == 1
    kinds = [event.kind for event in audit.recent()
             if event.kind.startswith("spatial_ruler_reframe")]
    assert kinds == ["spatial_ruler_reframe_applied"], kinds


def test_thirds_deviation_does_not_auto_reframe(tmp_path) -> None:
    """thirds_deviation（info 级）不自动 reframe：保留导演 ACCEPT 豁免空间。"""
    registry = _StubRegistry(ToolResult(True, "镜头 shot_001 取景已调整"))
    driver = _driver(registry)
    result = _result_with_kind("shot_001", "thirds_deviation", severity="info")
    assert driver._auto_reframe_from_ruler("shot_001", result) is False
    assert len(registry.calls) == 0


def test_headroom_plus_thirds_triggers_once_for_headroom(tmp_path) -> None:
    """headroom_off 与 thirds_deviation 同时出现：只按 headroom 自动 reframe。"""
    registry = _StubRegistry(ToolResult(True, "镜头 shot_001 取景已调整"))
    driver = _driver(registry)
    warnings = [
        {"type": "headroom_off", "shot_id": "shot_001", "subject": "米迦尔",
         "frame_range": [1, 24], "evidence": {"headroom": 0.16},
         "severity": "warning"},
        {"type": "thirds_deviation", "shot_id": "shot_001", "subject": "米迦尔",
         "frame_range": [1, 24], "evidence": {"thirds_deviation": 0.4},
         "severity": "info"},
    ]
    result = AuditResult(passed=False, errors=[_Err()],
                         guard_warnings=warnings, target="shot_001",
                         score=79.5)
    assert driver._auto_reframe_from_ruler("shot_001", result) is True
    assert len(registry.calls) == 1


class _StubRegistry(ToolRegistry):
    """记录 reframe 调用并返回预设结果的测试替身（与既有测试同构）。"""

    def __init__(self, outcome: ToolResult):
        super().__init__()
        self.outcome = outcome
        self.calls: list = []

    def execute(self, name: str, args, *, wrap: bool = True,
                context: dict | None = None) -> ToolResult:
        if name == "reframe":
            self.calls.append(dict(args))
            return self.outcome
        return super().execute(
            name, args, wrap=wrap, context=context)


class _Err:
    rule = "COMPOSITION"

    def to_dict(self):
        return {"rule": self.rule}


def _result_with_kind(shot_id: str, kind: str, *, severity: str):
    warnings = [{"type": kind, "shot_id": shot_id, "subject": "米迦尔",
                 "frame_range": [1, 24],
                 "evidence": {"headroom": 0.16}, "severity": severity}]
    return AuditResult(passed=False, errors=[_Err()],
                       guard_warnings=warnings, target=shot_id, score=79.5)
