"""导出沙箱（v1.7 卡 I1 / TDD §13.1，R-痛点 M3/FR-E2）。

备份 → 锁定 → 还原：导出全程对 ``scene.render`` 的写点在沙箱内发生，退出
（含异常路径）时逐项还原；**异常不吞**（原异常继续抛）。

相机语义（v1.7.6 收窄钉死）：``renderer.py`` 与 ``export_director.py`` 均无
``scene.camera`` 赋值（逐镜切换靠时间线 cut markers，不靠换相机对象），所以
沙箱只做两件事——把 ``scene.camera`` 列为第 10 项备份并在退出时还原，进入时
设**首帧基准**相机；**不拦截**导出中途的相机切换（未来若引入，由引入者同步
改本清单）。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, List, Tuple

#: 备份清单（≥9 项，对照 R-痛点 P11）。元素 = 属性路径（从 scene 起）。
SANDBOX_KEYS: List[Tuple[str, ...]] = [
    ("render", "filepath"),
    ("render", "image_settings", "file_format"),
    ("render", "ffmpeg", "format"),
    ("render", "ffmpeg", "codec"),
    ("render", "ffmpeg", "constant_rate_factor"),
    ("render", "resolution_percentage"),
    ("render", "fps"),                       # Blender 5.x；旧版为 frame_rate
    ("render", "image_settings", "color_depth"),
    ("render", "image_settings", "color_mode"),
    ("camera",),
]


def _read_path(scene: Any, path: Tuple[str, ...]
               ) -> Tuple[Any, bool]:
    """读属性链；某一环不存在（如无 ffmpeg 的构建）→ ``(None, False)``。"""
    node = scene
    for part in path[:-1]:
        try:
            node = getattr(node, part)
        except AttributeError:
            return None, False
    try:
        return getattr(node, path[-1]), True
    except AttributeError:
        return None, False


def _write_path(scene: Any, path: Tuple[str, ...], value: Any) -> None:
    node = scene
    for part in path[:-1]:
        node = getattr(node, part)
    setattr(node, path[-1], value)


@contextmanager
def export_sandbox(scene: Any, *, camera: Any, fps: int
                   ) -> Iterator[None]:
    """备份 → 锁定（首帧基准相机 + fps）→ 还原；finally 逐项还原、异常不吞。"""
    snapshot = [(_read_path(scene, path), path) for path in SANDBOX_KEYS]
    scene.camera = camera
    scene.render.fps = int(fps)
    try:
        yield
    finally:
        #: 只还原"进沙箱前真的存在"的项；不存在的（无 ffmpeg 构建）记名跳过。
        for (value, existed), path in snapshot:
            if existed:
                _write_path(scene, path, value)


__all__ = ["SANDBOX_KEYS", "export_sandbox"]
