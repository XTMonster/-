"""集合路由与渲染隔离（执行文档 v1.2 §1.4 / §8.4 / §15.2）。

参考视频必须"画面干净"：角色标签、路径、轴线等辅助物是**真实对象**，
默认会被渲进视频。本模块把它们隔离到 ``BlockDirector/Guides`` 集合并
逐对象关闭渲染，并提供导出前审计（§15.2）。
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import bpy
from bpy.types import Collection, Object

from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only

log = get_logger("collections")

ROOT_COLLECTION = "BlockDirector"
CONTENT_COLLECTION = "BlockDirector/Content"
GUIDES_COLLECTION = "BlockDirector/Guides"


def _find_collection(name: str) -> Optional[Collection]:
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    return None


@main_thread_only("ensure_collections")
def ensure_collections(scene) -> Tuple[Collection, Collection]:
    """创建（或复用）Content / Guides 两个集合，返回 ``(content, guides)``。"""
    content = _find_collection(CONTENT_COLLECTION)
    if content is None:
        content = bpy.data.collections.new(CONTENT_COLLECTION)
        scene.collection.children.link(content)

    guides = _find_collection(GUIDES_COLLECTION)
    if guides is None:
        guides = bpy.data.collections.new(GUIDES_COLLECTION)
        scene.collection.children.link(guides)

    # 集合级兜底：即使某个对象忘了设 hide_render，集合也拦住它
    guides.hide_render = True
    content.hide_render = False
    return content, guides


@main_thread_only("route_object")
def route_object(obj: Object, collection_name: str) -> Object:
    """把对象移入指定集合（从其它集合中解绑，保证只属于一个集合）。"""
    for collection in list(obj.users_collection):
        collection.objects.unlink(obj)
    target = _find_collection(collection_name)
    if target is None:
        scene = getattr(bpy.context, "scene", None)
        if scene is None:
            raise RuntimeError("没有活动场景，无法创建集合")
        ensure_collections(scene)
        target = _find_collection(collection_name)
    if target is None:  # pragma: no cover - 理论上不可达
        raise RuntimeError(f"集合不可用: {collection_name}")
    target.objects.link(obj)
    return obj


@main_thread_only("route_to_content")
def route_to_content(obj: Object) -> Object:
    return route_object(obj, CONTENT_COLLECTION)


@main_thread_only("mark_as_guide")
def mark_as_guide(obj: Object) -> Object:
    """把对象标记为"仅视口可见"：移入 Guides 并逐对象关闭渲染。"""
    obj.hide_render = True
    return route_object(obj, GUIDES_COLLECTION)


@main_thread_only("audit_renderable_objects")
def audit_renderable_objects() -> List[str]:
    """返回**不该出现在渲染里却会入画**的对象名（§15.2 导出前检查）。

    空列表表示可以安全导出参考视频。
    """
    bad: List[str] = []
    for obj in bpy.data.objects:
        if obj.type in {"EMPTY", "CAMERA", "LIGHT", "ARMATURE"}:
            continue
        if obj.hide_render:
            continue
        # 落到 Guides 集合里却没设 hide_render 的，也要报出来
        if any(c.name == GUIDES_COLLECTION for c in obj.users_collection):
            bad.append(obj.name)
        elif obj.type in {"FONT", "CURVE", "SURFACE", "META"}:
            # 这些类型通常是辅助物，出现在内容区基本是路由漏了
            bad.append(obj.name)

    guides = _find_collection(GUIDES_COLLECTION)
    if guides is not None and not guides.hide_render:
        bad.append(GUIDES_COLLECTION)
    return bad


@main_thread_only("objects_in_collection")
def objects_in_collection(name: str) -> List[Object]:
    collection = _find_collection(name)
    return list(collection.objects) if collection else []


@main_thread_only("purge_orphan_data")
def purge_orphan_data() -> int:
    """回收无用户的 datablock（§8.1）：删对象不会自动删 mesh。"""
    return bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                  do_recursive=True)


@main_thread_only("clear_blockdirector_objects")
def clear_blockdirector_objects(keep: Iterable[str] = ()) -> int:
    """删除所有 BD_ 前缀对象（重建场景前清理），返回删除数量。"""
    keep_set = set(keep)
    removed = 0
    for obj in list(bpy.data.objects):
        if obj.name.startswith("BD_") and obj.name not in keep_set:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
    if removed:
        purge_orphan_data()
    return removed
