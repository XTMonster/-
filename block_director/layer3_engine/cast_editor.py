"""剧组编辑（执行文档 v1.2 §13.1 的角色管理）。

面板上的"角色列表 / 颜色 / 添加 / 删除"落在这里。三件事必须一起做，否则
界面上的改动是"看起来改了"：

1. **改 Blender 对象**（颜色材质、增删角色对象）；
2. **改场景设定** ``SceneContext.spec`` —— SDL 与项目文件是从它导出的，
   只改对象不改 spec，重出一镜时颜色就回去了；
3. **守住引用完整性** —— 删除一个还被镜头引用的角色会让审核直接报 R007，
   所以这里拒绝这种删除并说明原因。

纯逻辑（id 分配）抽成纯函数以便单测；其余需要 bpy。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import bpy

from ..contracts.cast import CastMember, SceneSpec, next_character_id
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .character_system import create_character, create_label, delete_character, set_character_color
from .scene_context import SceneContext, get_context

log = get_logger("cast-editor")

class CastError(RuntimeError):
    """改不了。消息里给出可执行的下一步。"""


def _spec_slot(context: SceneContext) -> SceneSpec:
    """确保上下文里有一份可写的场景设定。"""
    if context.spec is None:
        cast = [CastMember(id=character.id, name=character.name,
                           color=character.color,
                           initial_location=tuple(character.root.location))
                for character in context.characters.values()
                if character.root is not None]
        context.spec = SceneSpec(cast=cast)
    return context.spec


def list_cast(context: Optional[SceneContext] = None) -> List[Dict[str, Any]]:
    """角色列表（面板用）：id / 名字 / 颜色 / 是否在画。"""
    context = context or get_context()
    if context is None or context.spec is None:
        return []
    rows: List[Dict[str, Any]] = []
    for member in context.spec.cast:
        character = context.character(member.id)
        rows.append({"id": member.id, "name": member.name,
                     "color": member.color,
                     "in_scene": character is not None,
                     "label": member.name or member.id})
    return rows


def _require_member(context: SceneContext, character_id: str) -> CastMember:
    for member in _spec_slot(context).cast:
        if member.id == character_id:
            return member
    raise CastError(f"找不到角色 {character_id}")


@main_thread_only("apply_cast_color")
def apply_cast_color(character_id: str, color: str,
                     context: Optional[SceneContext] = None) -> Dict[str, Any]:
    """改颜色：材质 + 场景设定一起改。"""
    context = context or get_context()
    if context is None:
        raise CastError("当前没有 BlockDirector 场景上下文；请先构建一次场景")
    member = _require_member(context, character_id)
    member.color = str(color)
    character = context.character(character_id)
    material = ""
    if character is not None:
        material = set_character_color(character, str(color))
    log.info("角色 %s 颜色 → %s", character_id, color)
    return {"ok": True, "character_id": character_id, "color": str(color),
            "material": material}


@main_thread_only("add_cast_member")
def add_cast_member(name: str, color: str = "#FFFFFF",
                    position: Sequence[float] = (0.0, 0.0, 0.0),
                    facing: Sequence[float] = (0.0, 1.0, 0.0),
                    context: Optional[SceneContext] = None) -> Dict[str, Any]:
    """加一个角色：建对象 + 建标签 + 写进场景设定。"""
    context = context or get_context()
    if context is None:
        raise CastError("当前没有 BlockDirector 场景上下文；请先构建一次场景")
    spec = _spec_slot(context)
    clean_name = str(name or "").strip()
    if not clean_name:
        raise CastError("角色名不能为空")
    character_id = next_character_id([member.id for member in spec.cast]
                                     + list(context.characters))
    character = create_character(character_id, clean_name, str(color),
                                 location=tuple(float(v) for v in position),
                                 facing=tuple(float(v) for v in facing))
    # v1.4 X11：**生效域** = Guides 视口标签。``create_label`` 走的是
    # ``mark_as_guide`` + ``hide_render`` 的参考对象路径，所以这里读的正是
    # ``ui.show_labels``（"标签是否进参考视频"是 ``character.label_render``
    # 那条渲染路径的事，由 ``create_render_label`` 负责）。
    # 旧代码用默认值（True）建标签，面板上的"显示标签"开关对新增角色**完全
    # 无效**——这就是 X11 说的"半接线"。
    show_in_viewport = True
    try:
        from ..settings import get_config

        show_in_viewport = bool(get_config().ui.show_labels)
    except Exception as exc:  # noqa: BLE001 - 读不到配置就用默认值
        log.debug("读取 ui.show_labels 失败，按 True 处理：%s", exc)
    create_label(character, clean_name, show_in_viewport=show_in_viewport)
    context.characters[character_id] = character
    spec.cast.append(CastMember(id=character_id, name=clean_name,
                                color=str(color),
                                initial_location=tuple(float(v)
                                                       for v in position),
                                initial_facing=tuple(float(v) for v in facing)))
    log.info("新增角色 %s（%s）", clean_name, character_id)
    return {"ok": True, "character_id": character_id, "name": clean_name,
            "color": str(color)}


@main_thread_only("remove_cast_member")
def remove_cast_member(character_id: str, *,
                       context: Optional[SceneContext] = None) -> Dict[str, Any]:
    """删一个角色：先查引用，再删对象，最后从设定里摘掉。"""
    context = context or get_context()
    if context is None:
        raise CastError("当前没有 BlockDirector 场景上下文；请先构建一次场景")
    spec = _spec_slot(context)
    member = _require_member(context, character_id)

    referencing = [shot.shot_id for shot in (context.plan.shots
                                             if context.plan else [])
                   if character_id in shot.characters]
    if referencing:
        raise CastError(
            f"角色 {character_id} 被镜头引用（{', '.join(referencing)}），"
            f"删除后这些镜头会因引用缺失（R007）失败；请先修改计划再删")

    character = context.character(character_id)
    removed = delete_character(character) if character is not None else 0
    context.characters.pop(character_id, None)
    spec.cast = [item for item in spec.cast if item.id != character_id]
    log.info("删除角色 %s（%d 个对象）", character_id, removed)
    return {"ok": True, "character_id": character_id,
            "name": member.name, "removed_objects": removed}
