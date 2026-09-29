"""角色名共指消解（执行文档 v1.2 §4.3）。

两步走：
1. **确定性预分组**：把归一化后相同的写法合并（"小明" / "小 明" / "小明 "）；
2. **LLM 消解**：代词（他/她/它）与昵称必须结合上下文，因此把场景文本与
   已知角色表交给模型判断。

LLM 调用以 ``cluster_fn`` 注入，layer1 不反向依赖 layer5——这样本模块可以
在没有任何模型的情况下单测。
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional

from .model import ParsedScript

#: 明显不是角色名的代词与泛称
PRONOUNS = {"他", "她", "它", "他们", "她们", "它们", "我", "你", "您",
            "我们", "你们", "大家", "众人", "某人", "有人"}

ClusterFn = Callable[[List[str], str], Dict[str, str]]


def normalize_name(name: str) -> str:
    """去掉空白与常见装饰，用于确定性合并。"""
    cleaned = "".join(char for char in (name or "") if not char.isspace())
    return cleaned.strip("、，。.:：")


def collect_names(script: ParsedScript) -> List[str]:
    """按出现顺序收集所有候选名（对白角色 + 动作里提到的人）。"""
    names: List[str] = []
    for name in script.character_names:
        if name and name not in names:
            names.append(name)
    return names


def exact_groups(names: Iterable[str]) -> Dict[str, List[str]]:
    """归一化后相同的写法归到一组，保持首次出现的顺序。"""
    groups: Dict[str, List[str]] = {}
    for name in names:
        groups.setdefault(normalize_name(name), []).append(name)
    return groups


def resolve_coreferences(script: ParsedScript, *,
                         cluster_fn: Optional[ClusterFn] = None
                         ) -> Dict[str, str]:
    """返回 ``别名 → 标准名`` 映射。

    没有 ``cluster_fn``（例如离线运行）时只做确定性合并——代词保留原样，
    不做无依据的猜测。
    """
    names = collect_names(script)
    mapping: Dict[str, str] = {name: name for name in names}

    for _key, members in exact_groups(names).items():
        canonical = members[0]
        for member in members:
            mapping[member] = canonical

    if cluster_fn is not None and names:
        try:
            proposed = cluster_fn(names, script.digest()) or {}
        except Exception:  # noqa: BLE001 - 消解失败不该阻断解析
            proposed = {}
        for alias, canonical in proposed.items():
            if alias in mapping and canonical in mapping:
                mapping[alias] = mapping[canonical]
    return mapping


def apply_mapping(script: ParsedScript, mapping: Dict[str, str]) -> int:
    """把映射写回剧本，返回被改写的引用条数。"""
    changed = 0
    for scene in script.scenes:
        for dialogue in scene.dialogues:
            canonical = mapping.get(dialogue.character)
            if canonical and canonical != dialogue.character:
                dialogue.character = canonical
                changed += 1
        for action in scene.actions:
            updated = [mapping.get(name, name)
                       for name in action.characters_mentioned]
            if updated != action.characters_mentioned:
                action.characters_mentioned = updated
                changed += 1
    return changed


def apply_deterministic_coreferences(script: ParsedScript) -> int:
    """只做确定性合并（不需要 LLM），返回被改写的引用条数。

    接线背景：v1.2 里 ``resolve_coreferences`` 与 ``apply_mapping`` **从未被
    任何生产代码调用**——§4.3 承诺的共指消解整体是死代码，只有单测在用。
    本函数是"至少把确定性那一半接上"的最小接线：写法归一化
    （"小 明" / "小明 " / "小明."）不需要模型参与。

    代词消解（"他/她/它"）必须结合上下文，由 v1.3 的 Stage S 承担——
    在那里模型能看到整场文本与角色表，比在这里猜要可靠。
    """
    return apply_mapping(script, resolve_coreferences(script))


def is_pronoun(name: str) -> bool:
    return normalize_name(name) in PRONOUNS
