"""注入预算的 token 估算（执行文档 v1.2 §6.5；v1.4 §2.3d T5 的两个上限）。

为什么单独一个模块：超边（``retriever``）与案例（``cases``）**两条通道都要**
按同一个口径裁剪注入长度，而 ``cases`` 不能反向 import ``retriever``（那会成环）。
把估算放在这里，两边引用的是**同一个函数对象**，口径不可能漂。

Blender 自带 Python 没有 tokenizer，所以口径是**文档化的确定性估算**：CJK 字符按
1 token，拉丁文按 4 字符 1 token。它只用来裁剪注入长度，不参与计费。
"""

from __future__ import annotations

from typing import List

LATIN_CHARS_PER_TOKEN = 4.0
TRUNCATION_NOTE = "\n…（已按 token 上限截断）"


def estimate_tokens(text: str) -> int:
    """确定性 token 估算：CJK 字符 1 token，拉丁文 4 字符 1 token。"""
    cjk = 0
    other = 0
    for char in text or "":
        if "\u3400" <= char <= "\u4dbf" or "\u4e00" <= char <= "\u9fff":
            cjk += 1
        else:
            other += 1
    return int(cjk + other / LATIN_CHARS_PER_TOKEN + 0.999)


def truncate_to_tokens(text: str, limit: int) -> str:
    """按估算 token 截断文本；超限时补一句说明，便于模型知道内容不完整。"""
    if limit <= 0 or estimate_tokens(text) <= limit:
        return text
    budget = max(limit - estimate_tokens(TRUNCATION_NOTE), 1)
    kept: List[str] = []
    used = 0
    for line in text.splitlines():
        cost = estimate_tokens(line) + 1
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    if not kept:                        # 单行就超限：按字符硬截
        kept = [text[: max(budget * 2, 40)]]
    return "\n".join(kept) + TRUNCATION_NOTE
