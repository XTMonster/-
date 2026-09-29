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
#: 渲染可见的角色标签（v1.3 诉求 4）。与 Guides 刻意分开：Guides 是
#: "绝不进画面"的辅助物，而这一集合是**要进参考视频**的。
LABELS_COLLECTION = "BlockDirector/Labels"


def _find_collection(name: str) -> Optional[Collection]:
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    return None


@main_thread_only("ensure_collections")
def ensure_collections(scene) -> Tuple[Collection, Collection]:
    """创建（或复用）Content / Guides / Labels 三个集合。

    返回 ``(content, guides)``（保持既有签名；Labels 由
    :func:`labels_collection` 单独取）。
    """
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

    labels = _find_collection(LABELS_COLLECTION)
    if labels is None:
        labels = bpy.data.collections.new(LABELS_COLLECTION)
        scene.collection.children.link(labels)
    labels.hide_render = False
    return content, guides


@main_thread_only("labels_collection")
def labels_collection() -> Optional[Collection]:
    """取渲染可见标签的集合（不存在时返回 None）。"""
    return _find_collection(LABELS_COLLECTION)


@main_thread_only("route_to_labels")
def route_to_labels(obj: Object) -> Object:
    return route_object(obj, LABELS_COLLECTION)


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

    检查三类：
    1. 落在 Guides 集合里却没关渲染的辅助物；
    2. 内容区里的文字/曲线/曲面等"通常是辅助物"的类型；
    3. **非本插件管理**（不叫 ``BD_``）的可渲染几何体——比如 Blender 启动
       场景自带的 Cube。Phase 6 首次端到端导出就是被这个默认方块坑了：
       它会作为一块灰板挡在角色前面，而旧版审计完全没报。
    """
    bad: List[str] = []
    for obj in bpy.data.objects:
        if obj.type in {"EMPTY", "CAMERA", "LIGHT", "ARMATURE"}:
            continue
        if obj.hide_render:
            continue
        # v1.3 诉求 4：**要进参考视频**的角色标签走白名单。
        # 它们刻意留在可渲染集合里，其余 FONT/CURVE 仍然一律判泄漏。
        if str(obj.get("bd_element_type") or "") == "label_render":
            continue
        if not obj.name.startswith("BD_"):
            bad.append(obj.name)
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


@main_thread_only("clear_scene_objects")
def clear_scene_objects(keep: Iterable[str] = ()) -> int:
    """清空场景里**所有**对象（含非本插件对象），用于从干净状态重建。

    与 :func:`clear_blockdirector_objects` 的区别：后者只删 ``BD_`` 对象，
    适合用户在已有场景里重生成；本函数是"这个进程归我调度"时用的，
    会把 Blender 启动场景自带的 Cube/Camera/Light 一并清掉。
    """
    keep_set = set(keep)
    removed = 0
    for obj in list(bpy.data.objects):
        if obj.name in keep_set:
            continue
        bpy.data.objects.remove(obj, do_unlink=True)
        removed += 1
    if removed:
        purge_orphan_data()
    return removed


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
