"""本镜"被摄主体"的判定（v1.4 X9）。纯计算，不依赖 bpy。

**为什么单独成一个模块**：构图评分（``evaluate_camera_composition``）与规则
判定（``rule_checker``）必须共用同一份主体集合——v1.2 的
``check_composition`` 工具直接拿全剧组去评分，于是两人相对而立时，单人镜
的搭档离机位更近、显得更大，评分从 71 掉到 40，修复循环被完全带偏。

v1.4 收窄：**有镜头计划时不再回退整个剧组**。镜头没显式声明角色就该有
"没有主体"的结论，否则空镜 / 无声明镜头会混进 R012 的正反打判定。
只有**完全没有计划**（计划外的临时调用）时才保留"全剧组"这一历史行为。
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def subject_ids(shot, *, has_plan: bool) -> Optional[List[str]]:
    """返回本镜的被摄主体 id。

    * 有该镜头的计划记录 → 只返回 ``shot.characters``（可能为空列表）；
    * 有计划但没有这一镜 → 返回 ``[]``；
    * **没有计划** → 返回 ``None``，调用方回退成"全剧组"。
    """
    if shot is not None:
        return [str(item) for item in (getattr(shot, "characters", None) or [])]
    if has_plan:
        return []
    return None


def resolve_subjects(shot, characters: Sequence, *, has_plan: bool) -> List:
    """按 :func:`subject_ids` 从 ``characters`` 里挑出对象。"""
    ids = subject_ids(shot, has_plan=has_plan)
    if ids is None:
        return list(characters)
    lookup = {str(getattr(item, "id", "")): item for item in characters}
    return [lookup[item] for item in ids if item in lookup]
