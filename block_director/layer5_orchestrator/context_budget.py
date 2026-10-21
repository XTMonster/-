"""上下文治理（执行文档 v1.2 §3.5）。

v1.0 把所有观察结果一路 append，长剧本会让 `self.messages` 无界增长——成本、
延迟、注意力稀释三件事一起坏。这里给出两条**确定性**规则：

1. **单镜窗口**：进入新镜头时清空对话窗口（由驱动器重置消息列表完成）；
2. **token 上限**：超过 `orchestration.context_window_tokens` 时**先裁最旧的
   工具观察**，system 与最近一轮永远保留。

token 估算复用 Light RAG 的确定性估算器（CJK 1 字≈1 token、拉丁 4 字符≈1），
不引入第三方 tokenizer。纯计算，可单测。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Dict, List, Sequence, Tuple

from ..contracts.messages import Message, MessageRole
from ..knowledge.retriever import estimate_tokens


def count_tokens(messages: Sequence[Message]) -> int:
    """整段对话的估算 token 数。"""
    total = 0
    for message in messages:
        total += estimate_tokens(getattr(message, "content", "") or "")
        for call in getattr(message, "tool_calls", None) or []:
            total += estimate_tokens(getattr(call.function, "arguments", "") or "")
    return total


def trim_messages(messages: Sequence[Message], max_tokens: int
                  ) -> Tuple[List[Message], List[Message]]:
    """把对话裁到上限内，返回 ``(保留的消息, 被裁掉的消息)``。

    策略：system 消息永远保留；其余按"从旧到新"淘汰，直到装得下。最新一条
    即使超限也保留——那是模型马上要回答的内容，裁掉它就等于没问。
    """
    items = list(messages)
    if max_tokens <= 0 or count_tokens(items) <= max_tokens:
        return items, []

    keep: List[Message] = [m for m in items
                           if getattr(m, "role", None) is MessageRole.SYSTEM]
    rest = [m for m in items if getattr(m, "role", None) is not MessageRole.SYSTEM]
    if not rest:
        return keep, []

    newest = rest[-1]
    droppable = rest[:-1]
    dropped: List[Message] = []
    while droppable and count_tokens(keep + droppable + [newest]) > max_tokens:
        dropped.append(droppable.pop(0))
    return keep + droppable + [newest], dropped


def compress_messages(messages: Sequence[Message], *,
                      max_tokens: Optional[int] = None) -> List[Message]:
    """把一组将被裁掉的旧消息压缩成**一条关键信息摘要**（用户裁决：
    生成关键信息文档当缓存，压缩上下文，而不是直接把旧观察丢掉）。

    只保留"模型继续修这一镜还需要的要点"：

    * 工具观察里的**工具名 + 关键结论**（``check_composition: 41.5``、
      ``check_axis: 越轴`` 这类），按出现顺序合并；
    * assistant 的 tool_calls 只留工具名与关键参数片段，**不保留**原始
      ``arguments`` JSON 全文；
    * 其余非工具消息（含提示词、占位）只保留"发生了什么"的一行标签。

    ``max_tokens``（可选）给摘要设预算：生成后从尾部删关键行，直到
    ``estimate_tokens(摘要) <= max_tokens``，保证注入后整段对话仍不超
    ``context_window_tokens``（窗口纪律：压缩不能把窗口挤爆）。0/None =
    不设上限。

    返回单条 SYSTEM 消息（零消息时不产生空文档）。压缩产物**不再携带**任何
    ``tool_call_id``——它只是一段摘要文本，不能冒充真实工具回灌，否则会破坏
    assistant/tool 的配对不变量。
    """
    if not messages:
        return []
    lines: List[str] = []
    seen_call_ids = set()
    for message in messages:
        content = getattr(message, "content", None)
        text = str(content) if isinstance(content, str) else ""
        role = getattr(message, "role", None)
        call_id = getattr(message, "tool_call_id", None)
        # 工具观察：提炼 "工具名: 结论" 一行
        if role is MessageRole.TOOL and text:
            if call_id and call_id in seen_call_ids:
                continue
            if call_id:
                seen_call_ids.add(call_id)
            lines.append(text if len(text) <= 200 else text[:200] + "…")
            continue
        # assistant 带 tool_calls：只留工具名 + 关键参数片段
        calls = getattr(message, "tool_calls", None) or []
        if role is MessageRole.ASSISTANT and calls:
            for call in calls:
                fn = getattr(call, "function", None)
                name = getattr(fn, "name", "") if fn is not None else ""
                args = ""
                if fn is not None:
                    raw = getattr(fn, "arguments", "") or ""
                    args = raw if len(raw) <= 120 else raw[:120] + "…"
                line = name or "（工具调用）"
                if args:
                    line += f" {args}"
                lines.append(line)
            continue
        # 其它消息：压缩成一行"发生了什么"，不再逐字保留
        if text:
            first = text.strip().splitlines()[0] if text.strip() else ""
            if first:
                lines.append(f"〔{first[:80]}〕")
    header = "——上下文压缩：以下为被裁旧对话的关键信息摘要，保留供继续精修参考——"
    body = "\n".join(lines)
    text = header + "\n" + body
    if max_tokens is not None and max_tokens > 0:
        rows = body.splitlines()
        while rows and estimate_tokens(header + "\n" + "\n".join(rows)) > max_tokens:
            rows.pop()
        text = header + "\n" + "\n".join(rows)
    return [Message(role=MessageRole.SYSTEM, content=text)]


def budget_report(messages: Sequence[Message], max_tokens: int) -> Dict[str, int]:
    """给调试面板/日志用的一行账。"""
    used = count_tokens(messages)
    return {"used_tokens": used, "max_tokens": int(max_tokens),
            "remaining_tokens": max(0, int(max_tokens) - used),
            "messages": len(list(messages))}


#: v1.6 F1（D-02）：知识注入的三栏标题（与 ``knowledge/retriever.py`` 的
#: ``edge_columns`` / 案例栏同一组词）。瘦身包只认这几个标题，别的【…】不动。
KNOWLEDGE_COLUMN_TITLES = ("硬约束（禁/许）", "经验建议（软）", "参考案例（仅参考）",
                           "参考案例")
SLIM_PLACEHOLDER = "（重试瘦身：本次省略知识栏，以该镜声明与审计发现为准）"
_COLUMN_RE = re.compile(
    r"【(?:" + "|".join(re.escape(t) for t in KNOWLEDGE_COLUMN_TITLES) + r")】"
    r".*?(?=\n【|\n#|\n\n\S|\Z)", re.S)


def strip_knowledge_columns(text: str) -> Tuple[str, int]:
    """去掉文本里的知识三栏，返回 ``(新文本, 去掉的栏数)``；没有栏 ⇒ 原样返回。"""
    removed = 0

    def _drop(_match) -> str:
        nonlocal removed
        removed += 1
        return SLIM_PLACEHOLDER if removed == 1 else ""

    slimmed = _COLUMN_RE.sub(_drop, str(text or ""))
    return slimmed, removed


def slim_messages(messages: Sequence[Message]) -> Tuple[List[Message], int]:
    """重试阶梯的**瘦身包**：只去 RAG 三栏，其它一律原样（TDD §4.5）。

    该镜声明、审计发现、工具调用与工具结果都不动——瘦身的目的只是缩短输入，
    不能拿掉模型修这一镜真正需要的证据。返回 ``(新消息, 去掉的栏数)``。
    """
    out: List[Message] = []
    total = 0
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str) and "【" in content:
            slimmed, removed = strip_knowledge_columns(content)
            if removed:
                total += removed
                message = replace(message, content=slimmed)
        out.append(message)
    return out, total
