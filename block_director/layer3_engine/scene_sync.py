"""双向同步（执行文档 v1.2 §8.3）。

Blender 对象 ↔ SDL 元素靠 ``bd_sdl_id`` 建立映射；用户手动改动通过
``depsgraph_update_post`` 标记为 dirty；局部重生成前先 :meth:`sync_from_blender`
回读，避免把用户调整覆盖掉。手动调过关键帧的对象打 ``bd_user_animated``，
重生成时整段保护（不回读、不覆盖）。

**写抑制（v1.0 缺失的那一环）**：插件自己的写入同样会触发 depsgraph 回调，
造成 dirty 抖动与性能损耗，因此插件写入都包在 :func:`suppress_sync` 里。

但只靠标志位是不够的——Blender 会合帧，回调可能被推迟甚至吞掉。所以判据是
**两条一起看**：回调命中的对象集合（``touched``）**且**当前变换与"插件最后
写入的基线"不同（``dirty_ids``）。基线比较是可靠判据，回调用于尽早发现。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Tuple

import bpy

from ..contracts.cast import CastMember, SceneSpec
from ..contracts.plan import Plan
from ..utils.geometry import rotation_z_to_facing
from ..utils.logger import get_logger
from ..utils.threading_guard import main_thread_only
from .scene_context import get_context

log = get_logger("scene-sync")

SYNC_ID_KEY = "bd_sdl_id"
USER_ANIMATED_KEY = "bd_user_animated"


@dataclass(frozen=True)
class SyncRecord:
    """一个被同步对象在某个时刻的变换。"""

    sdl_id: str
    object_name: str
    location: Tuple[float, float, float]
    rotation_z: float
    user_animated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"sdl_id": self.sdl_id, "object": self.object_name,
                "location": [round(v, 4) for v in self.location],
                "rotation_z": round(self.rotation_z, 4),
                "user_animated": self.user_animated}


def sdl_id_of(obj: Any) -> str:
    """读对象上的 SDL 标记（没有就返回空串）。"""
    getter = getattr(obj, "get", None)
    if getter is None:
        return ""
    return str(getter(SYNC_ID_KEY) or "")


def tagged_objects() -> List[Tuple[Any, str]]:
    """当前场景里所有带 ``bd_sdl_id`` 的对象。"""
    found: List[Tuple[Any, str]] = []
    for obj in bpy.data.objects:
        sdl_id = sdl_id_of(obj)
        if sdl_id:
            found.append((obj, sdl_id))
    return found


def _record_for(obj: Any, sdl_id: str) -> SyncRecord:
    location = tuple(float(value) for value in obj.location)
    return SyncRecord(sdl_id=sdl_id, object_name=obj.name, location=location,
                      rotation_z=float(obj.rotation_euler[2]),
                      user_animated=is_user_animated(obj))


def mark_user_animated(obj: Any, flag: bool = True) -> None:
    """把对象标记为"用户手动调过关键帧"，重生成时整段保护。"""
    obj[USER_ANIMATED_KEY] = bool(flag)


def is_user_animated(obj: Any) -> bool:
    getter = getattr(obj, "get", None)
    return bool(getter(USER_ANIMATED_KEY) if getter else False)


class SceneSynchronizer:
    """维护"插件写入基线"，据此判断哪些对象被用户改了。"""

    def __init__(self, *, scene=None) -> None:
        self._applying = False
        self._handler = None
        self._baseline: Dict[str, SyncRecord] = {}
        self._touched: set = set()
        self._scene = scene

    # ------------------------------------------------------------ 绑定
    @property
    def applying(self) -> bool:
        """是否正处于插件写入的抑制窗口内。"""
        return self._applying

    @property
    def bound(self) -> bool:
        return self._handler is not None

    def bind(self) -> None:
        """挂上 ``depsgraph_update_post``（重复调用安全）。"""
        if self._handler is not None:
            return
        self._handler = self._on_update
        bpy.app.handlers.depsgraph_update_post.append(self._handler)

    def unbind(self) -> None:
        if self._handler is None:
            return
        handlers = bpy.app.handlers.depsgraph_update_post
        if self._handler in handlers:
            handlers.remove(self._handler)
        self._handler = None

    def _on_update(self, scene, depsgraph) -> None:  # pragma: no cover - bpy 回调
        if self._applying:
            return
        for update in getattr(depsgraph, "updates", []) or []:
            sdl_id = sdl_id_of(getattr(update, "id", None))
            if sdl_id:
                self._touched.add(sdl_id)

    # ------------------------------------------------------------ 基线
    def record_baseline(self, objects: Optional[Iterable[Any]] = None) -> int:
        """记录"插件刚写完"的变换，作为判断用户改动的基准。

        基线按**对象名**存：``bd_sdl_id`` 是逻辑 id，一个角色身上会有多个对象
        共享它（角色根 + 标签），按 id 存会互相覆盖，进而把干净场景误判成 dirty。
        """
        pairs = ([(obj, sdl_id_of(obj)) for obj in objects] if objects is not None
                 else tagged_objects())
        count = 0
        for obj, sdl_id in pairs:
            if not sdl_id:
                continue
            self._baseline[obj.name] = _record_for(obj, sdl_id)
            count += 1
        self._touched.clear()
        return count

    @property
    def baseline(self) -> Dict[str, SyncRecord]:
        return dict(self._baseline)

    def touched_ids(self) -> List[str]:
        return sorted(self._touched)

    def clear_dirty(self) -> None:
        self._touched.clear()

    def dirty_ids(self) -> List[str]:
        """与插件基线不同的**逻辑 id**（用户改过），按 id 排序。"""
        dirty: set = set()
        for obj, sdl_id in tagged_objects():
            record = self._baseline.get(obj.name)
            if record is None:
                continue
            current = _record_for(obj, sdl_id)
            if (current.location != record.location
                    or abs(current.rotation_z - record.rotation_z) > 1e-6):
                dirty.add(sdl_id)
        return sorted(dirty)

    def is_dirty(self, sdl_id: str) -> bool:
        return sdl_id in set(self.dirty_ids())

    def snapshot(self) -> List[SyncRecord]:
        return [_record_for(obj, sdl_id) for obj, sdl_id in tagged_objects()]

    # ------------------------------------------------------------ 写抑制
    @contextlib.contextmanager
    def suppress(self):
        """插件写入窗口：窗口内的 depsgraph 回调不算用户改动。"""
        previous = self._applying
        self._applying = True
        try:
            yield self
        finally:
            self._applying = previous

    # ------------------------------------------------------------ 回读
    @main_thread_only("SceneSynchronizer.sync_from_blender")
    def sync_from_blender(self, plan: Plan,
                          spec: SceneSpec) -> Tuple[Plan, SceneSpec]:
        """把用户改过的角色摆位回读进 ``SceneSpec``（其余字段原样保留）。

        回读对象是"角色根"，因为那才是 ``bd_sdl_id`` 的落点；朝向取 Z 轴偏航，
        与世界坐标约定（角色面朝 +Y）一致。
        """
        dirty = set(self.dirty_ids())
        if not dirty:
            return plan, spec

        # 回读必须以**角色根**为准：标签也带同一个 bd_sdl_id，但它跟着头走，
        # 读它会得到偏移过的坐标。
        context = get_context()
        by_id: Dict[str, Any] = {}
        for member in spec.cast:
            character = context.character(member.id) if context else None
            obj = getattr(character, "root", None) if character else None
            if obj is None:
                candidates = [item for item, sdl_id in tagged_objects()
                              if sdl_id == member.id]
                obj = candidates[0] if candidates else None
            if obj is not None:
                by_id[member.id] = obj
        cast: List[CastMember] = []
        for member in spec.cast:
            obj = by_id.get(member.id)
            if member.id not in dirty or obj is None:
                cast.append(member)
                continue
            yaw = float(obj.rotation_euler[2])
            updated = CastMember(
                id=member.id, name=member.name, color=member.color,
                initial_location=(round(float(obj.location.x), 4),
                                  round(float(obj.location.y), 4),
                                  round(float(obj.location.z), 4)),
                # 回读必须与写入（facing_to_rotation_z）互为逆运算，
                # 否则用户转过的朝向会被读成它的镜像。
                initial_facing=tuple(round(v, 4)
                                     for v in rotation_z_to_facing(yaw)))
            cast.append(updated)
            log.info("回读用户改动：%s → %s", member.id,
                     tuple(round(v, 3) for v in updated.initial_location))
        # 只替换 cast，其余字段原样继承。
        #
        # v1.2 在这里逐字段枚举重建 SceneSpec。只要 SceneSpec 新增一个字段
        # （v1.3 会加 crowd 与标签渲染设置），它就会在这一步被静默丢掉——
        # 而 regenerate_shot() 每次都会先调用本方法，于是"改一镜重出一镜"
        # 会顺手把观众、特效与标签设置一起抹掉。用 replace 从根上避免这种漂移。
        return plan, replace(spec, cast=cast)


def suppress_sync(synchronizer: Optional[SceneSynchronizer]):
    """模块级便捷写法：``with suppress_sync(sync): ...``（§8.3 的伪代码）。"""
    if synchronizer is None:
        return contextlib.nullcontext()
    return synchronizer.suppress()


_SINGLETON: Optional[SceneSynchronizer] = None


def get_synchronizer() -> SceneSynchronizer:
    """进程级同步器（UI 与工具层共用同一个；首次调用时挂上 depsgraph 回调）。"""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = SceneSynchronizer()
        _SINGLETON.bind()
    return _SINGLETON


def reset_synchronizer() -> None:
    """注销并清空（插件卸载/测试用）。"""
    global _SINGLETON
    if _SINGLETON is not None:
        _SINGLETON.unbind()
    _SINGLETON = None


def note_build() -> int:
    """一次插件写入结束：若同步器已启用，就把当前变换记为基线。

    没有同步器时什么都不做——headless 批处理不需要它，也就不该付出代价。
    """
    if _SINGLETON is None:
        return 0
    with _SINGLETON.suppress():
        return _SINGLETON.record_baseline()
