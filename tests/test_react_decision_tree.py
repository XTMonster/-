"""TDD 阶段 2 后半验收：决策树投影接入 driver 的 react/repair 工具调用。

设计文档 work/per_shot_decision_tree_design.md §7.3：

- react/repair 阶段，越界工具参数先进该镜决策树投影；PROJECTED ⇒ 改写参数后执行，
  REJECTED ⇒ 不执行工具并回灌错误（剧本硬约束最高优先级），两者都留审计事件；
- 控制/只读工具不进树；REJECTED 后仍要 append tool_message（保持会话配对）；
- 树按镜缓存，换镜（_advance_shot）与 B5 结束（_finish_react）时清空。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from block_director.contracts.audit import (
    V16_EVENT_FIELDS,
    missing_event_fields,
)
from block_director.contracts.config import AppConfig
from block_director.contracts.messages import (
    ChatReply,
    FunctionCall,
    MessageRole,
    ToolCall,
)
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.planner import PLAN_TOOL_NAME
from block_director.layer5_orchestrator.states import DriverState
from block_director.layer6_audit.audit_logger import AuditLogger

from test_driver_react import (
    InlineThread,
    StubAuditor,
    StubBuilder,
    make_driver,
)
from stage_helpers import is_understand, understand_reply

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"

PLAN_REPLY = (PLAN_TOOL_NAME, {"shots": [
    {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
     "duration_frames": 24},
    {"shot_id": "shot_002", "order": 2, "intent": "y", "shot_type": "CU",
     "duration_frames": 24}]})


class RecordingRegistry:
    """记录实际执行过的工具调用，供断言“REJECTED 不执行”。"""

    def __init__(self, registry) -> None:
        self._registry = registry
        self.executed: List[tuple] = []

    def execute(self, name: str, args: Dict[str, Any]):
        self.executed.append((name, dict(args)))
        return self._registry.execute(name, args)

    def openai_schemas(self):
        return self._registry.openai_schemas()

    def schemas_except(self, *names: str):
        return self._registry.schemas_except(*names)

    def schemas_only(self, *names: str):
        return self._registry.schemas_only(*names)

    def names(self):
        return self._registry.names()

    def get(self, name: str):
        return self._registry.get(name)

    def override_parameters(self, name: str, parameters: Dict[str, Any]):
        return self._registry.override_parameters(name, parameters)

    def __contains__(self, name: object) -> bool:
        return name in self._registry

    def add(self, *args, **kwargs):
        return self._registry.add(*args, **kwargs)


def make_driver(transport, auditor, **kwargs):
    """test_driver_react.make_driver 的本地包装：把 registry 换成 RecordingRegistry。"""
    from block_director.layer5_orchestrator.driver import (
        default_registry as bd_default_registry,
    )
    from test_driver_react import make_driver as _base_make_driver

    registry = RecordingRegistry(bd_default_registry())
    kwargs.setdefault("registry", registry)
    return _base_make_driver(transport, auditor, **kwargs)


class DrafterTransport:
    """回放脚本项；``draft_only=True`` 时只回放 B1 单镜草案。"""

    def __init__(self, items, *, draft_only=False):
        self._items = list(items)
        self.calls = 0
        self.payloads = []
        self._script_index = 0
        self._draft_index = 0
        self._draft_only = draft_only

    def chat(self, payload, timeout=120.0):
        if is_understand(payload):
            return understand_reply(payload.request_id)
        if str(payload.purpose) == "editor":
            from block_director.layer5_orchestrator.offline import demo_draft_dict

            draft = demo_draft_dict(self._draft_index)
            self._draft_index += 1
            return ChatReply(tool_calls=[ToolCall(
                id=f"draft_{self._draft_index}",
                function=FunctionCall(
                    name="emit_shot_draft",
                    arguments=json.dumps(draft, ensure_ascii=False)))],
                request_id=payload.request_id)
        self.calls += 1
        self.payloads.append(payload)
        item = self._items[min(self._script_index, len(self._items) - 1)]
        self._script_index += 1
        if item is None:
            return ChatReply(content="停", tool_calls=[], request_id=payload.request_id)
        name, args = item
        if isinstance(args, str):
            #: 允许直接传原始 arguments 字符串（例如非法 JSON），
            #: 供「JSON 解析失败不该进树」的用例使用。
            raw_arguments = args
        else:
            raw_arguments = json.dumps(args)
        return ChatReply(tool_calls=[ToolCall(
            id=f"c{self.calls}",
            function=FunctionCall(name=name, arguments=raw_arguments))],
            request_id=payload.request_id)


def _kinds(driver) -> List[str]:
    return [event.kind for event in driver.audit.recent(500)]


def _find(kind: str, driver) -> Optional[dict]:
    for event in driver.audit.recent(500):
        if event.kind == kind:
            return event
    return None


# --------------------------------------------------------------------------- #
# 审计事件登记（R-7：先登记再用）
# --------------------------------------------------------------------------- #
def test_projected_events_are_registered_with_card_fields():
    assert V16_EVENT_FIELDS["react_projected"] == (
        "shot_id", "stage", "tool", "records")
    assert V16_EVENT_FIELDS["repair_projected"] == (
        "shot_id", "stage", "tool", "records", "repair_invalid")
    assert missing_event_fields("react_projected", {
        "shot_id": "shot_001", "stage": "react", "tool": "setup_camera",
        "records": []}) == []
    assert missing_event_fields("repair_projected", {
        "shot_id": "shot_001", "stage": "repair", "tool": "move_camera",
        "records": [], "repair_invalid": True}) == []


# --------------------------------------------------------------------------- #
# react 阶段：PROJECTED 改写后执行 + react_projected 事件
# --------------------------------------------------------------------------- #
def test_react_projects_free_text_side_before_executing():
    transport = DrafterTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001"}),                      # B4
        ("setup_camera", {"shot_id": "shot_001",
                          "side": "front-right, same 180° side as shot_003"}),  # B5
    ])
    driver = make_driver(transport, StubAuditor(fail_times=3))
    driver.run_to_completion()

    assert driver.state is DriverState.DONE
    assert "react_projected" in _kinds(driver)
    event = _find("react_projected", driver)
    data = event.data
    assert data["shot_id"] == "shot_001"
    assert data["stage"] == "react"
    assert data["tool"] == "setup_camera"
    records = data["records"]
    assert records and records[0]["node_key"] == "camera.side"
    assert records[0]["original"] == "front-right, same 180° side as shot_003"
    assert records[0]["projected"] == "front_right"
    assert records[0]["verdict"] == "projected"


def test_react_mutates_call_arguments_and_executes_projected_value():
    transport = DrafterTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001"}),                      # B4
        ("setup_camera", {"shot_id": "shot_001", "side": "front-right"}),  # B5
    ])
    driver = make_driver(transport, StubAuditor(fail_times=3))
    driver.run_to_completion()
    executed = driver.registry.executed
    assert any(name == "setup_camera" and args.get("side") == "front_right"
               for name, args in executed)


# --------------------------------------------------------------------------- #
# repair 阶段：REJECTED 不执行 + repair_projected 事件
# --------------------------------------------------------------------------- #
def test_repair_rejects_unknown_movement_without_executing():
    transport = DrafterTransport([
        PLAN_REPLY,
        #: repair 回合只执行一轮工具调用；直接把越界运镜放在这一轮首位，
        #: 让投影层在 repair 阶段判定，而不是落到 react 阶段。
        ("move_camera", {"shot_id": "shot_001",
                        "movement_type": "fly to the moon",
                        "amount": 1.0}),                               # repair
    ])
    auditor = StubAuditor(fail_times=2)
    driver = make_driver(transport, auditor)
    driver.run_to_completion()

    assert "repair_projected" in _kinds(driver)
    event = _find("repair_projected", driver)
    data = event.data
    assert data["shot_id"] == "shot_001"
    assert data["stage"] == "repair"
    assert data["tool"] == "move_camera"
    assert data["repair_invalid"] is True
    assert data["records"][0]["verdict"] == "rejected"
    # REJECTED ⇒ 不执行工具
    assert not any(name == "move_camera" for name, _ in driver.registry.executed)
    # 会话仍配对（后续还能继续）
    assert any(msg.role == MessageRole.TOOL for msg in driver.messages)


# --------------------------------------------------------------------------- #
# 控制/只读工具不进树
# --------------------------------------------------------------------------- #
def test_control_tools_bypass_tree_projection():
    transport = DrafterTransport([
        PLAN_REPLY,
        ("setup_camera", {"shot_id": "shot_001"}),
        ("setup_camera", {"shot_id": "shot_001"}),
        None])
    driver = make_driver(transport, StubAuditor(fail_times=3))
    driver.run_to_completion()
    # 本轮没有越界工具：不应出现投影/拒绝事件（控制工具虽也在 calls 里但被豁免）
    assert "react_projected" not in _kinds(driver)
    assert "repair_projected" not in _kinds(driver)


def test_invalid_tool_arguments_json_still_fails_before_tree():
    transport = DrafterTransport([
        PLAN_REPLY,
        #: 传非法 JSON 字符串：无论是否在树判域内，JSON 解析失败都
        #: 不该产生投影事件（解析发生在投影之前）。
        ("setup_camera", '{"shot_id": "shot_001", "side": "front-right"'),   # 缺右括号
    ])
    driver = make_driver(transport, StubAuditor(fail_times=3))
    driver.run_to_completion()
    # 无论是否进树，JSON 解析失败都不该产生投影事件
    assert "react_projected" not in _kinds(driver)


# --------------------------------------------------------------------------- #
# 树缓存生命周期
# --------------------------------------------------------------------------- #
def test_advance_shot_clears_tree_cache():
    driver = make_driver(DrafterTransport([PLAN_REPLY]),
                         StubAuditor(fail_times=9))
    assert driver._decision_trees == {}
    driver._current_shot_id = "shot_001"
    driver._shot_queue = ["shot_001", "shot_002"]
    driver._decision_trees["shot_001"] = object()
    driver._advance_shot()
    assert "shot_001" not in driver._decision_trees
    assert driver._current_shot_id == "shot_002"


def test_finish_react_clears_tree_cache():
    driver = make_driver(DrafterTransport([PLAN_REPLY]),
                         StubAuditor(fail_times=3))
    driver._react_shot = "shot_001"
    driver._react_steps = 1
    driver._decision_trees["shot_001"] = object()
    driver._finish_react("测试结束")
    assert "shot_001" not in driver._decision_trees
