"""超时重试阶梯（v1.6 F1，D-02；TDD §4.5）——纯状态机，不发网络请求。

现场（E-run ②）：同一份提示、同一个超时，原样再等一遍，两次烧掉 30 分钟。
阶梯把"再试"拆成三级，每级只看**这一个阶段**的调用历史：

1. 第一次失败且是超时 ⇒ ``retry_slim``：第二次用**瘦身包**（去掉 RAG 三栏，
   保留该镜声明、审计发现与工具结果——见 ``context_budget.slim_messages``）；
2. 第一次失败但不是超时（瞬时 5xx / 断流）⇒ ``retry_same``：同一份提示再试一次；
3. 已经失败 ``max_attempts`` 次 ⇒ ``degrade``：该镜降级，**不赌第三次**。

降 ``reasoning_effort`` 不在自动阶梯里（用户显式开关
``llm.low_effort_on_timeout``，缺省 false）——它会改变推理质量，不能静默发生。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

RETRY_SAME = "retry_same"
RETRY_SLIM = "retry_slim"
DEGRADE = "degrade"
DECISIONS = (RETRY_SAME, RETRY_SLIM, DEGRADE)

#: ``retry_ladder`` 审计事件的 ``stage`` 闭集（TDD §3.6）
LADDER_STAGES = ("slim_retry", "same_retry", "degrade")
STAGE_OF = {RETRY_SLIM: "slim_retry", RETRY_SAME: "same_retry", DEGRADE: "degrade"}


@dataclass
class CallOutcome:
    """一次 LLM 调用的结果（只记阶梯需要的两件事）。"""
    ok: bool
    timed_out: bool = False
    slim: bool = False          # 这次用的是不是瘦身包


@dataclass
class RetryPolicy:
    max_attempts: int = 2       # 同一阶段最多 2 次调用
    slim_on_timeout: bool = True
    degrade_after: bool = True  # 用完次数 ⇒ 降级；False 时把决定交还调用方（仍不重试）


def is_timeout(problem: str) -> bool:
    """传输错误文本是不是超时（与 ``transport`` 层的报错措辞对齐，中英都认）。"""
    text = str(problem or "").lower()
    return any(token in text for token in (
        "timed out", "timeout", "time out", "read operation timed", "超时"))


def next_step(history: Sequence[CallOutcome], policy: RetryPolicy) -> str:
    """根据**失败**历史决定下一步：``retry_same`` / ``retry_slim`` / ``degrade``。

    * 历史为空或最后一次成功：不该调用本函数——返回 ``retry_same`` 表示"正常调用"；
    * 失败次数 ≥ ``max_attempts`` ⇒ ``degrade``（永不第三次）；
    * 最后一次是超时且允许瘦身、且还没用过瘦身包 ⇒ ``retry_slim``；
    * 其余失败 ⇒ ``retry_same``。
    """
    failures: List[CallOutcome] = [item for item in history if not item.ok]
    if not history or history[-1].ok:
        return RETRY_SAME
    if len(failures) >= max(int(policy.max_attempts), 1):
        return DEGRADE
    last = history[-1]
    if last.timed_out and policy.slim_on_timeout and not last.slim:
        return RETRY_SLIM
    return RETRY_SAME


__all__ = ["RETRY_SAME", "RETRY_SLIM", "DEGRADE", "DECISIONS", "LADDER_STAGES",
           "STAGE_OF", "CallOutcome", "RetryPolicy", "is_timeout", "next_step"]
