"""JSONL 审计日志与 LLM Trace（执行文档 v1.2 §11.3）。

- ``audit_log.jsonl``：发生了什么（状态迁移、工具调用、错误、计划）
- ``llm_trace.jsonl``：每次 LLM 调用的用途/token/耗时

两条日志同时是 replay（§14.4）与 Golden Test（§21.4）的数据源，因此
写入必须是**逐行 flush** 的：崩溃前已发生的事实不能丢。
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from ..contracts.audit import redact_image_parts
from ..utils.logger import get_logger

log = get_logger("audit")

VALID_LEVELS = ("debug", "info", "warning", "error")

#: trace 里单条记录每个字段的默认字符上限（§11.3 / §14.1）
DEFAULT_TRACE_MAX_CHARS = 8000
TRUNCATION_MARK = "…[truncated]"


def render_messages(payload: Any) -> List[Dict[str, str]]:
    """把请求侧的消息列表压成可落盘的 ``[{role, content}]``。

    列表形 content 先经 :func:`contracts.audit.redact_image_parts` 把 ``data:``
    图像分片换成占位信息（base64 不落盘），再 ``json.dumps``——发生在
    ``trace_max_chars`` 截断之前；深拷贝保证传给模型的真实 payload 不被改动。
    """
    if payload is None:
        return []
    rendered: List[Dict[str, str]] = []
    for message in redact_image_parts(
            getattr(payload, "messages", []) or []):
        role = str(getattr(message, "role", "") or "")
        content = getattr(message, "content", None)
        item: Dict[str, str] = {"role": role,
                                "content": content if isinstance(content, str)
                                else json.dumps(content, ensure_ascii=False)}
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            item["tool_calls"] = json.dumps(
                [{"name": call.function.name,
                  "arguments": call.function.arguments}
                 for call in tool_calls], ensure_ascii=False)
        rendered.append(item)
    return rendered


def render_reply(reply: Any) -> Dict[str, Any]:
    """把回复压成可落盘的 ``{content, tool_calls}``。"""
    if reply is None:
        return {}
    content = getattr(reply, "content", None)
    reasoning = getattr(reply, "reasoning", None)
    calls = [{"name": call.function.name,
              "arguments": getattr(call.function, "arguments", "")}
             for call in getattr(reply, "tool_calls", []) or []]
    return {"content": content if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False) if content else "",
            "reasoning": reasoning if isinstance(reasoning, str) else "",
            "tool_calls": calls}


def truncate_text(text: str, limit: int) -> Tuple[str, bool]:
    """按字符数截断，返回 ``(文本, 是否截断过)``；``limit<=0`` 表示不截断。"""
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit] + TRUNCATION_MARK, True


@dataclass
class AuditEvent:
    kind: str
    message: str
    ts: float = field(default_factory=time.time)
    level: str = "info"
    run_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": round(self.ts, 3),
            "run_id": self.run_id,
            "level": self.level,
            "kind": self.kind,
            "message": self.message,
            "data": self.data,
        }


class AuditLogger:
    """把运行过程写成 JSONL；同时保留最近 N 条供 UI 展示。

    ``directory`` 为 None 时只在内存中记录（单元测试用）。
    """

    def __init__(self, directory: Optional[Path] = None, run_id: Optional[str] = None,
                 keep: int = 200, echo: bool = False,
                 trace_prompts: bool = True,
                 trace_max_chars: int = DEFAULT_TRACE_MAX_CHARS) -> None:
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.directory = Path(directory) if directory else None
        self.echo = echo
        self.trace_prompts = bool(trace_prompts)
        self.trace_max_chars = int(trace_max_chars)
        self._recent: Deque[AuditEvent] = deque(maxlen=keep)
        self._llm_calls = 0
        self._tool_calls = 0
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ 路径
    @property
    def audit_path(self) -> Optional[Path]:
        return self.directory / "audit_log.jsonl" if self.directory else None

    @property
    def trace_path(self) -> Optional[Path]:
        return self.directory / "llm_trace.jsonl" if self.directory else None

    # ------------------------------------------------------------------ 写入
    def log(self, kind: str, message: str, /, level: str = "info",
            **data: Any) -> AuditEvent:
        """``kind`` 声明为位置专用，这样调用方可以安全地传 ``kind=`` 作为数据键。"""
        if level not in VALID_LEVELS:
            level = "info"
        event = AuditEvent(kind=kind, message=message, level=level,
                           run_id=self.run_id, data=dict(data))
        self._recent.append(event)
        if self.directory is not None:
            self._append(self.audit_path, event.to_dict())
        if self.echo or level == "error":
            (log.error if level == "error" else log.info)("%s: %s", kind, message)
        return event

    def log_llm(self, purpose: str, reply: Any, duration_s: float = 0.0,
                request_id: str = "", error: str = "",
                payload: Any = None) -> AuditEvent:
        """记录一次 LLM 调用；``reply`` 允许是 ChatReply 或原始 dict。

        §11.3：trace 记的是**完整 prompt / response**。``payload`` 是请求侧
        （``ChatPayload``），内容按 ``trace_max_chars`` 截断并在记录里标出
        ``truncated``；``trace_prompts=False`` 时退回只记元数据。
        """
        self._llm_calls += 1
        usage = getattr(reply, "usage", None)
        tool_names = [tc.function.name for tc in getattr(reply, "tool_calls", []) or []]
        record = {
            "ts": round(time.time(), 3),
            "run_id": self.run_id,
            "purpose": purpose,
            "request_id": request_id,
            "duration_s": round(duration_s, 3),
            "tool_calls": tool_names,
            "usage": usage.to_dict() if usage is not None else None,
            "error": error,
        }
        if self.trace_prompts:
            messages = render_messages(payload)
            answer = render_reply(reply)
            # 形状固定：失败调用没有回复时也给空字段，读者不必做 None 判断
            answer.setdefault("content", "")
            answer.setdefault("tool_calls", [])
            limit = self.trace_max_chars
            truncated = False
            for item in messages:
                item["content"], cut = truncate_text(item["content"], limit)
                truncated = truncated or cut
            for item in answer.get("tool_calls", []):
                item["arguments"], cut = truncate_text(item.get("arguments", ""),
                                                       limit)
                truncated = truncated or cut
            answer["content"], cut = truncate_text(answer.get("content", ""),
                                                   limit)
            truncated = truncated or cut
            answer["reasoning"], cut = truncate_text(answer.get("reasoning", ""),
                                                     limit)
            truncated = truncated or cut
            record["prompt"] = messages
            record["response"] = answer
            record["truncated"] = truncated
        if self.directory is not None:
            self._append(self.trace_path, record)
        event = AuditEvent(kind="llm_call", message=f"{purpose} 调用完成",
                           run_id=self.run_id, data=record)
        self._recent.append(event)
        return event

    def count_tool_call(self) -> int:
        self._tool_calls += 1
        return self._tool_calls

    @staticmethod
    def _append(path: Optional[Path], record: Dict[str, Any]) -> None:
        if path is None:
            return
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()

    # ------------------------------------------------------------------ 读取
    def recent(self, limit: Optional[int] = None) -> List[AuditEvent]:
        events = list(self._recent)
        return events[-limit:] if limit else events

    @property
    def counters(self) -> Dict[str, int]:
        return {"llm_calls": self._llm_calls, "tool_calls": self._tool_calls}
