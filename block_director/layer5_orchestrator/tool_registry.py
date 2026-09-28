"""工具注册表（执行文档 v1.2 §7.4 / §16.2）。

红线：工具执行**永不抛异常**——参数错误与执行异常都转成 LLM 可读的观察文本
回灌，让模型自己修正（这是 §12.4 自纠错的前提）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .tool_schema import validate_args

ToolHandler = Callable[..., str]
OBSERVATION_OPEN = "<tool_observation>"
OBSERVATION_CLOSE = "</tool_observation>"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolHandler

    def openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolResult:
    ok: bool
    content: str
    error: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - 便利方法
        return self.content


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    # ------------------------------------------------------------- 注册
    def add(self, name: str, description: str, parameters: Dict[str, Any],
            handler: ToolHandler) -> ToolSpec:
        spec = ToolSpec(name=name, description=description,
                        parameters=parameters, handler=handler)
        self._tools[name] = spec
        return spec

    def register(self, spec: ToolSpec) -> ToolSpec:
        self._tools[spec.name] = spec
        return spec

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    # ------------------------------------------------------------- 查询
    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def openai_schemas(self) -> List[Dict[str, Any]]:
        return [self._tools[name].openai_schema() for name in self.names()]

    def schemas_except(self, *names: str) -> List[Dict[str, Any]]:
        """按名字排除若干工具后的 schema 列表。

        阶段 A 的 ``emit_plan`` 是**计划阶段的唯一入口**：把它留给后续阶段，模型
        完全可能在中途再写一份"更满意"的计划——实测就发生过（修复回合重新提交
        了一份 1 镜计划，把已经建好的 3 镜场景的计划覆盖掉，导致项目文件里
        时长与帧范围对不上）。
        """
        excluded = {str(name) for name in names}
        return [self._tools[name].openai_schema() for name in self.names()
                if name not in excluded]

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    # ------------------------------------------------------------- 执行
    def execute(self, name: str, args: Any, *, wrap: bool = True) -> ToolResult:
        """执行工具；任何失败都转成可回灌的观察文本，不抛异常。

        handler 可以返回字符串（视为成功），也可以返回 :class:`ToolResult`
        来主动标记"这次调用失败了"——后者让驱动器的修复循环能区分
        "成功但内容里提到了问题"和"这次调用确实失败"。
        """
        def wrap_text(text: str) -> str:
            return f"{OBSERVATION_OPEN}{text}{OBSERVATION_CLOSE}" if wrap else text

        spec = self._tools.get(name)
        if spec is None:
            known = ", ".join(self.names()) or "（空）"
            return ToolResult(False, wrap_text(f"工具不存在: {name}。可用工具: {known}"),
                              error="unknown_tool")

        if not isinstance(args, dict):
            return ToolResult(False, wrap_text(
                f"参数校验失败: 参数必须是 JSON 对象，实际 {type(args).__name__}。请修正后重试。"),
                error="invalid_args")

        problems = validate_args(spec.parameters, args)
        if problems:
            detail = "；".join(problems)
            return ToolResult(False, wrap_text(f"参数校验失败: {detail}。请修正后重试。"),
                              error="invalid_args")

        try:
            output = spec.handler(**args)
        except Exception as exc:  # noqa: BLE001 - §16.2：工具不抛异常
            return ToolResult(False, wrap_text(
                f"执行失败: {type(exc).__name__}: {exc}。建议检查参数或简化该步操作。"),
                error="handler_error")

        if isinstance(output, ToolResult):
            return ToolResult(output.ok, wrap_text(output.content),
                              error=output.error, data=output.data)
        text = output if isinstance(output, str) else str(output)
        return ToolResult(True, wrap_text(text), data={"tool": name})
