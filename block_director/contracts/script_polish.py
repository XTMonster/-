"""Stage P 剧本优化契约（v1.7 TDD §9，卡 E1）。

本模块是 polish 的 **schema 与提示词模板的唯一真源**：run 内（driver 的
POLISHING 状态）与 Web 触发（sidecar ``/v1/ui/script/polish``）两个通道
都从这里 import，**不许出现第二份模板字符串**。

纯层约束：本模块不得 import bpy。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PolishResult:
    """一次剧本优化的产物。``accepted`` 由人工采纳门置位。"""

    suggestions: List[str] = field(default_factory=list)
    rewritten: str = ""
    accepted: bool = False


#: strict JSON schema：只允许 suggestions/rewritten 两键（E2 双通道共用的
#: 解析真源；多键一律拒绝，防止模型把 prompt 等内容塞进结果）。
POLISH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggestions": {"type": "array", "items": {"type": "string"}},
        "rewritten": {"type": "string"},
    },
    "required": ["suggestions", "rewritten"],
    "additionalProperties": False,
}

#: 提示词模板（唯一真源，双通道共用）。占位 ``{{script}}``＝原剧本全文，
#: ``{{brief}}``＝SceneBrief 摘要。行数上限约 60 行：结构化的分工建议维度
#: （衔接 FR-S1 的 skip_white_model 分工）与剧本优化目标都在模板内一次说清。
POLISH_PROMPT_TEMPLATE: str = """\
你是一位剧本优化顾问，为白模预演服务。请在**不改动剧情与对白含义**的前提下，
给出让分镜预演更清晰、更可执行的修改建议，并输出改写稿。

改写目标：
1. 保留原剧本对话、情节、情绪与人物关系；
2. 明确动作、走位、视线与机位方向（让白模预演能落地）；
3. 提示哪些角色/镜头适合 skip_white_model（只出机位与取景，不建白模主体）；
4. 列出逐条可执行建议，按"剧情→空间→镜头→表演"四类组织。

原剧本：
{{script}}

剧本理解摘要（SceneBrief）：
{{brief}}

只输出 JSON，结构严格如下：
{
  "suggestions": ["建议一", "建议二", ...],
  "rewritten": "改写后的完整剧本"
}
"""
