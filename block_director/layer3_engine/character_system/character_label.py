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

#: 渲染可见标签的默认参数（v1.3 诉求 4）
LABEL_FILL_COLOR = (1.0, 1.0, 1.0, 1.0)        # 白字
LABEL_STROKE_COLOR = (0.0, 0.0, 0.0, 1.0)      # 黑描边
#: 描边层相对字面层的放大倍数。30px 的字要高 ≈2px 的描边，
#: 需要 1 + 2*2/30 ≈ 1.13；1.06 只有 0.9px，几乎是看不见的暗边。
LABEL_STROKE_SCALE = 1.15
LABEL_STROKE_BACK = 0.004                      # 沿视线方向后退一点，避免 Z-fighting


def hex_rgba(color: str):
    """``#RRGGBB`` → 0..1 的 RGBA 四元组（配置里颜色写成十六进制）。"""
    from ...utils.geometry import hex_to_rgb
    return (*hex_to_rgb(color), 1.0)


class LabelFontMissing(RuntimeError):
    """要渲染中文标签却找不到中文字体。

    v1.2 在这种情况下把标签降级成角色编号（``char_001``）。一旦标签要进
    参考视频，这就等于交付物里印着编号——所以 v1.3 宁可明确报错，
    并给出可执行的下一步。
    """


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


def _text_object(name: str, body: str, font_path: str, size: float,
                 material) -> Object:
    curve = bpy.data.curves.new(name + "_data", type='FONT')
    curve.body = body
    curve.size = size
    curve.align_x = 'CENTER'
    curve.align_y = 'CENTER'
    if font_path:
        curve.font = bpy.data.fonts.load(font_path)
    if material is not None:
        curve.materials.append(material)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _flat_material(name: str, rgba):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.diffuse_color = tuple(rgba)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = tuple(rgba)
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 1.0
        # 标签是叠加信息，不该被场景灯光影响明暗（否则暗背景上会读不出来）
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = tuple(rgba)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 1.0
    return material


@main_thread_only("create_render_label")
def create_render_label(character, text: str = "", font_path: str = "",
                        size: float = LABEL_SIZE,
                        fill_color=LABEL_FILL_COLOR,
                        stroke_color=LABEL_STROKE_COLOR):
    """创建**渲染可见**的角色标签（v1.3 诉求 4）：白字 + 黑描边。

    与 :func:`create_label` 的两点关键差别：

    1. 归属 ``BlockDirector/Labels`` 且 ``hide_render = False``——它**要**进
       参考视频；
    2. 由两个 Text 对象组成（描边层 + 字面层），并且**不挂在角色根下**：
       公告板与屏幕恒定字号需要逐帧写世界变换，父级旋转会让局部角度互相
       抵消、难以维护。跟随角色由烘焙时采样 LabelAnchor 的世界位置实现。

    找不到中文字体时抛 :class:`LabelFontMissing`——渲染可见的标签不接受
    降级成编号。
    """
    body = text or character.name
    resolved = find_cjk_font(font_path)
    if has_cjk(body) and not resolved:
        raise LabelFontMissing(
            "要渲染的中文标签找不到中文字体。请设置 "
            "character.label_font_path（例如 C:\\Windows\\Fonts\\msyh.ttc），"
            "或把 character.label_render 关掉。"
            "候选路径：" + "、".join(CJK_FONT_CANDIDATES[:3]))

    from ..collection_router import route_to_labels

    fill_material = _flat_material(f"BD_Mat_Label_{character.id}_Fill",
                                   fill_color)
    stroke_material = _flat_material(f"BD_Mat_Label_{character.id}_Stroke",
                                     stroke_color)

    fill = _text_object(f"BD_Label_{character.id}_Fill", body, resolved,
                        size, fill_material)
    stroke = _text_object(f"BD_Label_{character.id}_Stroke", body, resolved,
                          size, stroke_material)
    # 轮廓靠"整层放大"实现（字形以中心对齐，因此四个方向同时外扩）。
    # 不再叠 Font.offset：那是沿法线的厚度，会让黑层看起来像投影而不是描边。
    stroke["bd_element_type"] = "label_render"
    fill["bd_element_type"] = "label_render"
    stroke["bd_sdl_id"] = character.id
    fill["bd_sdl_id"] = character.id
    stroke["bd_label_role"] = "stroke"
    fill["bd_label_role"] = "fill"
    route_to_labels(stroke)
    route_to_labels(fill)
    log.info("渲染标签已创建：%s（%s）", body, character.id)
    return fill, stroke
