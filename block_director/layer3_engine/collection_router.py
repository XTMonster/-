"""集合路由与渲染隔离（执行文档 v1.2 §1.4 / §8.4 / §15.2）。

参考视频必须"画面干净"：角色标签、路径、轴线等辅助物是**真实对象**，
默认会被渲进视频。本模块把它们隔离到 ``BlockDirector/Guides`` 集合并
逐对象关闭渲染，并提供导出前审计（§15.2）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

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

#: 渲染标签的**命名约定**（§2.5）：``BD_Label_<char_id>_Fill`` /
#: ``BD_Label_<char_id>_Stroke``。白名单按"集合 + 命名 + 数量"三件套判定，
#: 不再读对象自己写的 ``bd_element_type``——那等于让被检查者给自己发通行证。
LABEL_NAME_RE = re.compile(r"^BD_Label_(?P<cid>.+)_(?P<role>Fill|Stroke)$")
LABEL_ROLES = ("Fill", "Stroke")


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


@main_thread_only("label_pair_audit")
def label_pair_audit() -> Dict[str, Any]:
    """渲染标签的"集合 + 命名 + 数量"体检（v1.4 X4 / §2.5）。

    返回 ``{"pairs": {cid: {"Fill": n, "Stroke": n}}, "count": n,
    "problems": [...]}``。判据是**外生**的：

    * 每个启用标签的角色**恰好** 1 个 ``..._Fill`` 与 1 个 ``..._Stroke``；
    * 两个对象都必须在 ``BlockDirector/Labels`` 集合里；
    * 命名像标签却不在该集合里的对象，一律算问题（路由漏了 / 被挪走了）；
    * 集合里出现非标签命名的对象，也算问题。

    与 :func:`audit_renderable_objects` 的分工：本函数管**配对与归属**，
    ``audit`` 管**会不会入画**。两者的判定都不读对象自报的
    ``bd_element_type``（那是自证）。
    """
    labels = _find_collection(LABELS_COLLECTION)
    in_labels = list(labels.objects) if labels is not None else []
    in_labels_set = set(in_labels)
    pairs: Dict[str, Dict[str, List[str]]] = {}
    problems: List[str] = []

    for obj in in_labels:
        match = LABEL_NAME_RE.match(obj.name)
        if match is None:
            problems.append(f"{obj.name}（在 {LABELS_COLLECTION} 里却不是标签命名）")
            continue
        bucket = pairs.setdefault(match.group("cid"),
                                  {role: [] for role in LABEL_ROLES})
        bucket[match.group("role")].append(obj.name)

    for cid, roles in sorted(pairs.items()):
        for role in LABEL_ROLES:
            names = roles[role]
            if len(names) != 1:
                detail = f"BD_Label_{cid}_{role}"
                if names:
                    detail += f"（找到 {len(names)} 个：{'、'.join(names)}）"
                problems.append(f"{detail}（标签配对不完整）")

    for obj in bpy.data.objects:
        if LABEL_NAME_RE.match(obj.name) and obj not in in_labels_set:
            problems.append(f"{obj.name}（标签不在 {LABELS_COLLECTION} 集合里）")

    return {
        "pairs": {cid: {role: len(roles[role]) for role in LABEL_ROLES}
                  for cid, roles in pairs.items()},
        "count": len(pairs),
        "problems": sorted(set(problems)),
    }


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

    v1.4 X4：**要进参考视频**的角色标签走白名单，但白名单的判据是
    "在 ``BlockDirector/Labels`` 集合里 + 命名符合 ``BD_Label_<id>_*``"，
    外加 :func:`label_pair_audit` 的配对检查——不再读对象自报的
    ``bd_element_type``（旧实现只要对象自己写一个字符串就能免检，等于自证）。
    同名对象被挪到 Guides/Content 时依旧会被判泄漏。
    """
    bad: List[str] = []
    bad.extend(label_pair_audit()["problems"])
    for obj in bpy.data.objects:
        if obj.type in {"EMPTY", "CAMERA", "LIGHT", "ARMATURE"}:
            continue
        if obj.hide_render:
            continue
        # 白名单 = 集合 + 命名（数量与配对由 label_pair_audit 单独判）。
        if LABEL_NAME_RE.match(obj.name) and any(
                c.name == LABELS_COLLECTION for c in obj.users_collection):
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
