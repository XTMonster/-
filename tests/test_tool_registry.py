"""§7.4 / §16.2 工具注册表语义测试：永不抛异常，失败即观察。"""

from __future__ import annotations

from block_director.layer5_orchestrator.tool_registry import ToolRegistry, ToolResult

SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["value"],
          "properties": {"value": {"type": "integer", "minimum": 1}}}


def _registry(handler) -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(name="probe", description="test", parameters=SCHEMA,
                 handler=handler)
    return registry


def test_success_is_wrapped_as_observation():
    result = _registry(lambda value: f"拿到 {value}").execute("probe", {"value": 3})
    assert result.ok
    assert result.content == "<tool_observation>拿到 3</tool_observation>"


def test_unknown_tool_is_reported_not_raised():
    result = ToolRegistry().execute("nope", {})
    assert not result.ok and result.error == "unknown_tool"
    assert "工具不存在" in result.content
    assert "<tool_observation>" in result.content


def test_invalid_args_are_reported():
    result = _registry(lambda value: "x").execute("probe", {"value": 0})
    assert not result.ok and result.error == "invalid_args"
    assert "参数校验失败" in result.content


def test_non_dict_args_are_reported():
    result = _registry(lambda value: "x").execute("probe", "not-a-dict")
    assert not result.ok and "参数校验失败" in result.content


def test_handler_exception_becomes_observation():
    def boom(value):
        raise RuntimeError("内部炸了")

    result = _registry(boom).execute("probe", {"value": 1})
    assert not result.ok and result.error == "handler_error"
    assert "执行失败" in result.content and "内部炸了" in result.content


def test_handler_can_return_a_failed_tool_result():
    """领域级失败要能被标记，否则驱动分不清"成功"与"没办成"。"""
    result = _registry(lambda value: ToolResult(False, "找不到那个东西",
                                                error="domain_error")
                       ).execute("probe", {"value": 1})
    assert not result.ok and result.error == "domain_error"
    assert result.content == "<tool_observation>找不到那个东西</tool_observation>"


def test_handler_can_return_a_successful_tool_result():
    result = _registry(lambda value: ToolResult(True, "办好了",
                                                data={"extra": 1})
                       ).execute("probe", {"value": 1})
    assert result.ok and result.data == {"extra": 1}


def test_openai_schemas_are_generated():
    schema = _registry(lambda value: "x").openai_schemas()[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "probe"
    assert schema["function"]["parameters"] == SCHEMA


def test_wrap_can_be_disabled():
    result = _registry(lambda value: "raw").execute("probe", {"value": 1},
                                                    wrap=False)
    assert result.content == "raw"
