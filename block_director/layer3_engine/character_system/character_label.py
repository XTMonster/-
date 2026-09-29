"""角色标签（执行文档 v1.2 §9.4）。

两条硬约束：
1. **必须**指定含 CJK 字形的字体，否则中文渲染为空白/方块；
2. 标签是真实 Text 对象，**必须**进 Guides 集合并关闭渲染，否则会进参考视频。

§9.4 的距离缩放、重叠偏移、Track To 跟随相机属于 Phase 2 的标签系统。
"""

from __future__ import annotations

import os

import bpy
from bpy.types import Object

from ...utils.logger import get_logger
from ...utils.threading_guard import main_thread_only
from ..collection_router import mark_as_guide
from .character_factory import PIVOT_Z

log = get_logger("label")

CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\Deng.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)

LABEL_SIZE = 0.15


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def find_cjk_font(explicit: str = "") -> str:
    """按候选顺序找可用中文字体；找不到返回空串（调用方降级）。"""
    if explicit and os.path.exists(explicit):
        return explicit
    for candidate in CJK_FONT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return ""


@main_thread_only("create_label")
def create_label(character, text: str = "", font_path: str = "",
                 size: float = LABEL_SIZE,
                 show_in_viewport: bool = True) -> Object:
    """在角色头顶创建标签；无中文字体时降级为编号（§9.4）。

    ``font_path`` / ``size`` / ``show_in_viewport`` 由 ``build_scene`` 从配置
    传进来。v1.2 定义了 ``character.label_font_path`` 并在启动时提示
    "未指定中文字体"，但**从来没有把它传到这里**——用户按提示配了路径也无效。
    """
    display = text or character.name
    resolved = find_cjk_font(font_path)
    if has_cjk(display) and not resolved:
        display = character.id          # 降级：避免渲染出方块
        log.warning("未找到中文字体，标签降级为 %s", display)

    curve = bpy.data.curves.new(f"BD_Char_{character.name}_LabelText", type='FONT')
    curve.body = display
    curve.size = size
    curve.align_x = 'CENTER'
    curve.align_y = 'CENTER'
    if resolved:
        curve.font = bpy.data.fonts.load(resolved)

    label = bpy.data.objects.new(f"BD_Char_{character.name}_Label", curve)
    bpy.context.scene.collection.objects.link(label)
    label.parent = character.root                     # §9.2：挂 CharacterRoot，不挂 HeadPivot
    label.location = (0.0, 0.0, PIVOT_Z["label"])
    label["bd_element_type"] = "label"
    label["bd_sdl_id"] = character.id
    label = mark_as_guide(label)                      # 进 Guides + hide_render
    if not show_in_viewport:
        # ui.show_labels 在 v1.2 里没有任何消费者。
        label.hide_viewport = True
    log.debug("标签已创建：%s（%s）", display, label.name)
    return label
