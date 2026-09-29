"""知识卡的构造助手（v1.3 诉求 5）。

语料按域拆成多个模块之后，构造方式必须只有一份实现——否则"某个字段忘了
带"这类漂移会散落在五个文件里。
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from ..contracts.knowledge import Card


def as_list(value) -> List[str]:
    """把单个字符串收成单元素列表。

    语料里写 ``examples=("只有一个例子")`` 时，Python 得到的是**字符串**而不是
    元组（漏了尾逗号），直接 ``list()`` 会把它拆成一个个汉字——例如
    "角色起身…"变成"角；色；起；身…"。这里统一收敛，让数据无论写成哪种形式
    都得到同一份语义；``tests/test_knowledge.py`` 另有一条断言锁死单字元素。
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def make_card(card_id: str, domain: str, title: str, content: str,
              keywords: Sequence[str],
              rules: Tuple[str, ...] = (),
              parameters: Dict[str, object] | None = None,
              examples: Tuple[str, ...] = (),
              related: Tuple[str, ...] = (),
              engine_support: str = "",
              emotion: str = "",
              tags: Sequence[str] = ()) -> Card:
    return Card(id=card_id, domain=domain, title=title, content=content,
                keywords=as_list(keywords), rules=as_list(rules),
                parameters=dict(parameters or {}), examples=as_list(examples),
                related=as_list(related), engine_support=str(engine_support),
                emotion=str(emotion), tags=as_list(tags))
