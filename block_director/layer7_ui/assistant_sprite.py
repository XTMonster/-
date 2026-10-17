"""视口小助手（v1.7 D3）。

在视口内随状态机换帧的小助手动画。资产路径两级解析（``BD_ASSISTANT_ASSETS``
环境变量覆盖，缺省从包相对 ``web/assets/assistant`` 推）；启动预载全部 clip
图集为 gpu 贴图；modal timer 0.1 s 换帧；draw 回调只 blit（回调内不读盘不
解码）。``--background`` / ``ui.enabled=false`` / ``ui.viewport_sprite=false``
一律不注册。

纯层纪律：路径与帧表逻辑（本文件头部函数）不 import bpy，可单测；Blender
对象与 draw 回调在模块后段。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 资产目录相对包根（``web/assets/assistant``）。
_DEFAULT_REL = Path("web") / "assets" / "assistant"
#: 帧动画间隔（秒）；TDD §6.3：modal timer 0.1 s 换帧。
SPRITE_TICK = 0.1
#: 环境变量覆盖口（打包分发见 PRD 风险 Q6）。
ASSETS_ENV = "BD_ASSISTANT_ASSETS"


def resolve_assets_dir(env: Optional[str] = None,
                       pkg_file: Optional[str] = None) -> Path:
    """两级解析资产目录：环境变量优先，缺省从包文件相对推。

    - ``env`` 非空 → 用它（``Path(env).resolve()``）；
    - 否则以 ``pkg_file`` 的父目录向上找到包根，再拼 ``web/assets/assistant``；
    - ``pkg_file`` 缺省时用本模块文件（``__file__``）。
    """
    if env and str(env).strip():
        return Path(str(env).strip()).resolve()
    base = Path(pkg_file or __file__).resolve().parent
    #: layer7_ui → block_director → 包根（两级上溯）。
    package_root = base.parent.parent
    return (package_root / _DEFAULT_REL).resolve()


def load_frames_table(assets_dir: Path) -> Dict[str, Any]:
    """读 ``frames.json``；缺文件/坏 JSON 返回空表（UI 是附属品，不抛）。"""
    try:
        text = (assets_dir / "frames.json").read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, ValueError, TypeError):
        return {}


def clip_frames(table: Dict[str, Any], clip: str) -> int:
    """某 clip 的帧数（缺省 1，避免除零）。"""
    try:
        value = int(table.get("clips", {}).get(str(clip), {}).get("frames", 1))
    except (TypeError, ValueError):
        return 1
    return max(value, 1)


# --------------------------------------------------------------------------- #
# Blender 侧
# --------------------------------------------------------------------------- #

_handle: Optional[object] = None
_timer = None
_textures: Dict[str, Any] = {}
_frame_index: Dict[str, int] = {}
_last_tick = 0.0


def is_enabled() -> bool:
    return _handle is not None


def _load_textures(assets_dir: Path) -> Dict[str, Any]:
    """预载全部 clip 图集为 gpu 贴图（draw 回调只 blit，不读盘）。"""
    import bpy
    import gpu

    table = load_frames_table(assets_dir)
    textures: Dict[str, Any] = {}
    for clip_name, clip in (table.get("clips", {}) or {}).items():
        filename = str(clip.get("file", ""))
        if not filename:
            continue
        path = assets_dir / filename
        if not path.exists():
            continue
        try:
            image = bpy.data.images.load(str(path))
            tex = gpu.texture.from_image(image)
            textures[clip_name] = {"tex": tex, "frames": clip_frames(table, clip_name),
                                   "loop": bool(clip.get("loop", True))}
            _frame_index[clip_name] = 0
        except Exception:  # noqa: BLE001 - 单个贴图失败不阻断注册
            continue
    return textures


def _tick() -> float:
    """换帧计时器：每 0.1 s 推进当前 clip 帧索引。"""
    global _last_tick
    now = time.monotonic()
    if now - _last_tick >= SPRITE_TICK:
        _last_tick = now
        clip = _current_clip()
        count = clip_frames(_frames_table, clip)
        _frame_index[clip] = (_frame_index.get(clip, 0) + 1) % count
    return SPRITE_TICK


def _current_clip() -> str:
    """按当前 driver 状态取 clip 名（消费 contracts/assistant.py，不抄）。"""
    from ..contracts.assistant import clip_for_state
    from ..layer5_orchestrator.runtime import get_active

    driver = get_active()
    state = getattr(driver, "state", None)
    return clip_for_state(str(getattr(state, "value", state or "IDLE")))


_frames_table: Dict[str, Any] = {}


def _draw():
    """draw 回调：只 blit 当前 clip 的当前帧（回调内不读盘不解码）。"""
    import bpy
    import gpu
    from gpu_extras.batch import batch_for_shader

    clip = _current_clip()
    entry = _textures.get(clip)
    if entry is None:
        return
    tex = entry["tex"]
    frame = _frame_index.get(clip, 0)
    #: 横向精灵表（宽 = 单帧宽 × 帧数，高 = 单帧高）：按当前帧横向切片。
    frames = max(int(entry.get("frames", 1)), 1)
    width = (tex.width if hasattr(tex, "width") else 48) // frames
    height = tex.height if hasattr(tex, "height") else 48
    area = getattr(bpy.context, "area", None)
    if area is None:
        return
    x0 = area.width - width - 12
    y0 = area.height - height - 12
    x1 = x0 + width
    y1 = y0 + height
    #: uv 原点在左下；西文 sprite 表帧序左→右，按 (frame_in_clip / frames) 切片。
    u0 = frame / frames
    u1 = (frame + 1) / frames
    shader = gpu.shader.from_builtin("IMAGE")
    batch = batch_for_shader(
        shader, "TRI_FAN",
        {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
         "uv": [(u0, 0.0), (u1, 0.0), (u1, 1.0), (u0, 1.0)]},
    )
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_sampler("image", tex)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def register() -> None:
    """按条件注册：--background / ui.enabled=false / viewport_sprite=false 不注册。"""
    global _handle, _timer, _frames_table, _textures
    if _handle is not None:
        return
    import bpy

    if bpy.app.background:
        return
    from ..settings import get_config
    from ..layer7_ui.panel_assistant import sprite_enabled

    config = get_config()
    if not getattr(config.ui, "enabled", True):
        return
    if not sprite_enabled():
        return
    assets_dir = resolve_assets_dir(os.environ.get(ASSETS_ENV, ""))
    _frames_table = load_frames_table(assets_dir)
    if not _frames_table:
        return                                    # 缺帧表 → 不注册不抛
    _textures = _load_textures(assets_dir)
    if not _textures:
        return
    _handle = bpy.types.SpaceView3D.draw_handler_add(
        _draw, (), 'WINDOW', 'POST_PIXEL')
    if not bpy.app.timers.is_registered(_tick):
        _timer = bpy.app.timers.register(_tick, first_interval=SPRITE_TICK)


def unregister() -> None:
    global _handle, _timer
    import bpy

    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
    if _timer is not None and bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
        _timer = None
