"""分镜列表与"重生成此镜"（执行文档 v1.2 §13.2）。

这是迭代工作流的入口：AI 视频生成不理想时，用户回到这里只调某一镜，
而不是整场重跑。界面本身很薄——真正的保护逻辑在
``layer3_engine/shot_regenerator.py``（只动这一镜 + 保留用户改动）。
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel
from bpy.utils import previews

from ..layer3_engine.scene_context import get_context
from ..layer3_engine.scene_sync import get_synchronizer, reset_synchronizer
from ..layer3_engine.shot_regenerator import ShotRegenError, regenerate_shot
from ..layer5_orchestrator.runtime import get_active
from ..layer5_orchestrator.shot_status import (
    STATUS_FAILED,
    STATUS_PENDING,
    shot_statuses,
    summary_line,
)
from ..utils.logger import get_logger

log = get_logger("ui")

THUMBNAIL_SIZE = (160, 90)
_previews = None


def _preview_collection():
    """缩略图预览集合（lazily created，注销时销毁）。"""
    global _previews
    if _previews is None:
        _previews = previews.new()
    return _previews


def _thumbnail_dir(context) -> Path:
    raw = (context.scene.bd_project_dir or "").strip()
    base = Path(bpy.path.abspath(raw)) if raw else Path(bpy.app.tempdir or ".")
    return base / "thumbs"


def latest_statuses():
    """当前计划 + 驱动器审核历史 → 每镜一行状态（§13.2）。"""
    scene_context = get_context()
    plan = scene_context.plan if scene_context else None
    driver = get_active()
    audits = driver.audit_results if driver is not None else []
    built = set(scene_context.cameras) if scene_context else set()
    degraded = ""
    if driver is not None:
        degraded = driver.snapshot().get("degraded_reason") or ""
    return shot_statuses(plan, audits, built_shot_ids=built, degraded=degraded)


class BLOCKDIRECTOR_OT_regenerate_shot(Operator):
    """按当前计划重建单个镜头，保留用户手动改动（§8.3）。"""

    bl_idname = "blockdirector.regenerate_shot"
    bl_label = "重生成此镜"
    bl_description = "只重建这一镜的相机与动作；手动调整过的角色位置与关键帧不会被覆盖"
    bl_options = {'REGISTER', 'UNDO'}

    shot_id: StringProperty(name="镜号", default="")

    def execute(self, context):  # noqa: D102 - bpy 接口
        shot_id = self.shot_id or context.scene.bd_selected_shot
        if not shot_id:
            self.report({'ERROR'}, "没有选中镜头")
            return {'CANCELLED'}
        try:
            report = regenerate_shot(shot_id, sync=get_synchronizer())
        except ShotRegenError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.scene.bd_selected_shot = shot_id
        for warning in report["warnings"]:
            self.report({'WARNING'}, warning)
        self.report({'INFO'},
                    f"{shot_id} 已重生成（{report['start_frame']}-"
                    f"{report['end_frame']}，{report['keyframes']} 关键帧）")
        return {'FINISHED'}


class BLOCKDIRECTOR_OT_render_shot_thumbnail(Operator):
    """渲染该镜首帧并作为列表缩略图（§13.2 的"缩略图"列）。"""

    bl_idname = "blockdirector.render_shot_thumbnail"
    bl_label = "渲染缩略图"
    bl_description = "渲染这一镜的第一帧，作为分镜列表的缩略图"

    shot_id: StringProperty(name="镜号", default="")

    def execute(self, context):  # noqa: D102 - bpy 接口
        shot_id = self.shot_id or context.scene.bd_selected_shot
        scene_context = get_context()
        camera = scene_context.camera_for(shot_id) if scene_context else None
        if not shot_id or camera is None:
            self.report({'ERROR'}, f"镜头 {shot_id or '（未选）'} 还没有相机")
            return {'CANCELLED'}

        start = (scene_context.schedule.get(shot_id) or (1, 1))[0]
        scene = context.scene
        previous_camera = scene.camera
        previous_frame = scene.frame_current
        previous_res = (scene.render.resolution_x, scene.render.resolution_y)
        directory = _thumbnail_dir(context)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{shot_id}.png"
        try:
            scene.camera = camera
            scene.frame_set(int(start))
            scene.render.resolution_x, scene.render.resolution_y = THUMBNAIL_SIZE
            scene.render.resolution_percentage = 100
            scene.render.image_settings.file_format = "PNG"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
        finally:
            scene.render.resolution_x, scene.render.resolution_y = previous_res
            scene.camera = previous_camera
            scene.frame_set(int(previous_frame))

        if not path.exists():
            self.report({'ERROR'}, f"渲染失败：{path}")
            return {'CANCELLED'}
        _load_thumbnail(shot_id, path)
        self.report({'INFO'}, f"{shot_id} 缩略图已生成：{path}")
        return {'FINISHED'}


def _load_thumbnail(shot_id: str, path: Path) -> None:
    """把 PNG 读进预览集合（Blender 的预览只能从像素数组喂进去）。

    实测：``--background`` 下 ``icon_id`` **始终是 0**——图标纹理由 UI 层分配，
    没有窗口就没有 GPU 上下文。像素数据本身是设得进去、读得回来的（测试断言
    这条），因此有界面时 ``template_icon`` 能画出来。
    """
    collection = _preview_collection()
    if shot_id in collection:
        collection.remove(shot_id)
    preview = collection.new(shot_id)
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        size = (int(image.size[0]), int(image.size[1]))
        preview.image_size = size
        preview.icon_size = size
        pixels = list(image.pixels)
        preview.image_pixels_float = pixels
        # 只设 image_* 时 icon_id 仍是 0（面板拿不到可画的东西）；自定义图标
        # 走 icon_pixels_float 这一路，template_icon 才能显示。
        preview.icon_pixels_float = pixels
    finally:
        bpy.data.images.remove(image)


class BLOCKDIRECTOR_OT_show_audit_result(Operator):
    """把该镜最近一次审核结果写进文本编辑器（§13.2 的"查看审核结果"）。"""

    bl_idname = "blockdirector.show_audit_result"
    bl_label = "查看审核结果"
    bl_description = "显示这一镜最近一次审核的结论与建议"

    shot_id: StringProperty(name="镜号", default="")

    def execute(self, context):  # noqa: D102 - bpy 接口
        shot_id = self.shot_id or context.scene.bd_selected_shot
        driver = get_active()
        if driver is None or not shot_id:
            self.report({'WARNING'}, "还没有运行记录")
            return {'CANCELLED'}
        history = [result for result in driver.audit_results
                   if result.target == shot_id]
        if not history:
            self.report({'WARNING'}, f"{shot_id} 还没有审核结果")
            return {'CANCELLED'}
        result = history[-1]
        name = f"BD 审核 {shot_id}"
        text = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        text.clear()
        text.write(f"{shot_id} 审核：{'通过' if result.passed else '未通过'}"
                   f"（共 {len(history)} 次，分数 {result.score}）\n")
        #: v1.5 §5.5（P6-T1）：外部评审外回路。**只展示、不作裁决**——缺省关时
        #: 这一段不出现；开着而评委不可用时写"跳过"（跳过 ≠ 通过）。
        review = getattr(result, "vlm_review", None)
        if review:
            if str(review.get("status")) == "ok":
                text.write(f"VLM 评审：{review.get('score')}/5"
                           f"（{review.get('reason') or '无理由'}，"
                           f"尝试 {review.get('attempts', 0)} 次）\n")
            else:
                text.write(f"VLM 评审：跳过（{review.get('reason') or '未知原因'}）\n")
        for item in result.errors + result.warnings:
            text.write(f"[{item.rule}] {item.code} {item.message}\n"
                       f"    建议：{item.suggestion}\n")
        for suggestion in result.suggestions:
            text.write(f"· {suggestion}\n")
        self.report({'INFO'}, f"{shot_id} 审核结果已打开（{len(history)} 次）")
        return {'FINISHED'}


class BLOCKDIRECTOR_PT_shots(Panel):
    """分镜列表（§13.2）：每行一个镜头 + 一键重生成。"""

    bl_label = "分镜列表"
    bl_idname = "BLOCKDIRECTOR_PT_shots"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BlockDirector"
    bl_parent_id = "BLOCKDIRECTOR_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        scene_context = get_context()
        rows = latest_statuses()
        if not rows:
            layout.label(text="还没有分镜计划", icon='INFO')
            return

        layout.label(text=summary_line(rows))
        synchronizer = get_synchronizer()
        dirty = set(synchronizer.dirty_ids())
        for row_data in rows:
            shot_id = row_data["shot_id"]
            row = layout.row(align=True)
            selected = scene.bd_selected_shot == shot_id
            icon = 'RADIOBUT_ON' if selected else 'RADIOBUT_OFF'
            preview = _preview_collection().get(shot_id)
            if preview is not None:
                row.template_icon(icon_value=preview.icon_id, scale=2.0)
            row.label(text=f"{shot_id}  {row_data['shot_type']}  "
                           f"{row_data['seconds']:.1f}s  "
                           f"{row_data['status']}  {row_data['intent']}", icon=icon)
            button = row.operator("blockdirector.regenerate_shot",
                                  text="", icon='FILE_REFRESH')
            button.shot_id = shot_id
            thumb = row.operator("blockdirector.render_shot_thumbnail",
                                 text="", icon='IMAGE_DATA')
            thumb.shot_id = shot_id
            audit = row.operator("blockdirector.show_audit_result",
                                 text="", icon='CHECKMARK')
            audit.shot_id = shot_id
            if selected:
                scene_context.current_shot_id = shot_id

        if dirty:
            layout.label(text=f"检测到手动改动：{', '.join(sorted(dirty))}",
                         icon='INFO')


CLASSES = (BLOCKDIRECTOR_OT_regenerate_shot,
           BLOCKDIRECTOR_OT_render_shot_thumbnail,
           BLOCKDIRECTOR_OT_show_audit_result,
           BLOCKDIRECTOR_PT_shots)

_scene_props = {
    "bd_selected_shot": StringProperty(
        name="当前镜号", default="",
        description="分镜列表里选中的镜头（§13.2）"),
}


def register() -> None:
    for name, prop in _scene_props.items():
        setattr(bpy.types.Scene, name, prop)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _preview_collection()               # 缩略图集合先建好，面板 draw 才能用


def unregister() -> None:
    global _previews
    if _previews is not None:
        previews.remove(_previews)
        _previews = None
    for name in _scene_props:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001 - 注销失败不该阻断卸载
            log.warning("注销 %s 失败", cls.__name__)
    # 卸载时摘掉 depsgraph 回调，避免插件停用后还挂在全局处理器上
    reset_synchronizer()
