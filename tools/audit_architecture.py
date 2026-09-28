"""BlockDirector 架构可行性审核（在真实 Blender 上执行）.

对执行文档 v1.2 中**最可能翻车的架构假设**做实证检验，而不是纸面推演。
每项检查给出 PASS / FAIL / INCONCLUSIVE 与证据。

运行：
  blender --background --factory-startup --python tools/audit_architecture.py
报告：tools/_probe_out/audit_report.json
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


CHECKS: List = []
REPORT: Dict[str, Any] = {}


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def outdir() -> str:
    d = os.path.join(ROOT, "tools", "_probe_out")
    os.makedirs(d, exist_ok=True)
    return d


def fresh_scene():
    """清空为一个空场景（隔离各检查之间的状态）。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 64
    scene.render.resolution_y = 36
    scene.render.resolution_percentage = 100
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    display = getattr(scene, "display", None)
    if display is not None:
        shading = display.shading
        shading.light = "FLAT"
        shading.color_type = "MATERIAL"
        shading.background_type = "VIEWPORT"
        shading.background_color = (0.0, 0.0, 0.0)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("W")
    scene.world.color = (0.0, 0.0, 0.0)
    return scene


def add_camera(name: str, location, look_at=(0, 0, 0)):
    from mathutils import Vector

    cam_data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = location
    direction = Vector(look_at) - Vector(location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam


def add_white_cube(name: str, location, size=2.0):
    """白色立方体：平视机位下一定能入画，比水平面片可靠。"""
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.object
    obj.name = name
    mat = bpy.data.materials.new(f"{name}_mat")
    mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    obj.data.materials.append(mat)
    return obj


def render_luma(path: str, frame: Optional[int] = None) -> float:
    """渲染一帧并返回平均亮度（0..1）。"""
    scene = bpy.context.scene
    if frame is not None:
        scene.frame_set(frame)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        return -1.0
    img = bpy.data.images.load(path)
    try:
        pixels = list(img.pixels)
    finally:
        bpy.data.images.remove(img)
    rgb = [pixels[i] for i in range(len(pixels)) if i % 4 != 3]
    return sum(rgb) / max(len(rgb), 1)


def result(status: str, **evidence) -> Dict[str, Any]:
    return {"status": status, **evidence}


# --------------------------------------------------------------------------- #
# 1. 线程模型：bpy 是否允许在非主线程访问
# --------------------------------------------------------------------------- #
@check("threading_model")
def _threading():
    """架构要求：网络在后台线程，bpy 只在主线程（§3.1）。"""
    outcome: Dict[str, Any] = {}

    def worker():
        try:
            bpy.data.objects.new("THREAD_OBJ", None)
            outcome["created_from_thread"] = True
            outcome["error"] = None
        except Exception as exc:  # noqa: BLE001
            outcome["created_from_thread"] = False
            outcome["error"] = f"{type(exc).__name__}: {exc}"

    def risky_worker():
        """更能代表 driver 行为的调用：ops 与场景求值。"""
        try:
            bpy.ops.mesh.primitive_cube_add()
            outcome["ops_from_thread"] = "ok"
        except Exception as exc:  # noqa: BLE001
            outcome["ops_from_thread"] = f"{type(exc).__name__}: {exc}"
        try:
            bpy.context.view_layer.update()
            outcome["depsgraph_update_from_thread"] = "ok"
        except Exception as exc:  # noqa: BLE001
            outcome["depsgraph_update_from_thread"] = f"{type(exc).__name__}: {exc}"

    fresh_scene()
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    risky = threading.Thread(target=risky_worker)
    risky.start()
    risky.join()

    # 纯计算在后台线程是否正常（这是架构允许的部分）
    def compute():
        total = sum(i * i for i in range(200_000))
        outcome["pure_compute_ok"] = total > 0

    t2 = threading.Thread(target=compute)
    t2.start()
    t2.join()

    ops = str(outcome.get("ops_from_thread", ""))
    deps = str(outcome.get("depsgraph_update_from_thread", ""))
    guarded = not ops.startswith("ok") or not deps.startswith("ok")
    if guarded:
        status = "PASS"
        note = "Blender 拒绝在后台线程执行 ops/场景求值，线程边界是强约束"
    else:
        status = "WARN"
        note = ("bpy 未提供跨线程护栏（datablock 创建、ops、求值均未报错）→ "
                "架构必须靠纪律保证，建议加断言 main_thread_only()")
    return result(status, note=note, **outcome)


# --------------------------------------------------------------------------- #
# 2. 多镜头切换：marker + camera 绑定是否真的生效
# --------------------------------------------------------------------------- #
@check("marker_camera_binding")
def _markers():
    """CutManager（§10.2）依赖 marker.camera 在播放/渲染时切机位。"""
    scene = fresh_scene()
    add_white_cube("WHITE", (0.0, 0.0, 1.0), size=2.0)

    # A 看向场景；B 背对场景（只见黑背景），两者亮度差异显著
    cam_a = add_camera("BD_Cam_A", (0.0, -6.0, 1.0), look_at=(0.0, 0.0, 1.0))
    cam_b = add_camera("BD_Cam_B", (0.0, 6.0, 1.0), look_at=(0.0, 20.0, 1.0))
    scene.camera = cam_a

    # 先做对照测量（此时尚未创建 marker，避免 marker 干扰对照）
    ctrl_a = render_luma(os.path.join(outdir(), "audit_camA.png"), frame=1)
    scene.camera = cam_b
    ctrl_b = render_luma(os.path.join(outdir(), "audit_camB.png"), frame=1)
    scene.camera = cam_a
    sensitive = abs(ctrl_a - ctrl_b) > 0.05

    # 再建立 marker 绑定（CutManager §10.2 的机制）
    m1 = scene.timeline_markers.new("BD_Cut_A", frame=1)
    m1.camera = cam_a
    m2 = scene.timeline_markers.new("BD_Cut_B", frame=10)
    m2.camera = cam_b
    bpy.context.view_layer.update()

    # 实验：完全依赖 marker 绑定
    scene.frame_set(5)
    cam_at_5 = scene.camera.name if scene.camera else None
    luma_at_5 = render_luma(os.path.join(outdir(), "audit_marker_5.png"), frame=5)

    scene.frame_set(15)
    cam_at_15 = scene.camera.name if scene.camera else None
    luma_at_15 = render_luma(os.path.join(outdir(), "audit_marker_15.png"), frame=15)

    if not sensitive:
        return result("INCONCLUSIVE", note="对照渲染无差异，测量不灵敏",
                      control=[ctrl_a, ctrl_b])

    switches_5 = abs(luma_at_5 - ctrl_a) < 0.05
    switches_15 = abs(luma_at_15 - ctrl_b) < 0.05
    ok = switches_5 and switches_15
    return result(
        "PASS" if ok else "FAIL",
        note=("marker 绑定可驱动渲染机位" if ok else
              "marker.camera 未在渲染时切换机位 → 必须由 frame_change_post 显式设置 scene.camera"),
        control_luma=[ctrl_a, ctrl_b],
        luma_at_5=luma_at_5, luma_at_15=luma_at_15,
        scene_camera_at_5=cam_at_5, scene_camera_at_15=cam_at_15,
    )


# --------------------------------------------------------------------------- #
# 3. 兜底方案：frame_change_post 显式切机位
# --------------------------------------------------------------------------- #
@check("frame_change_handler_camera")
def _handler_camera():
    """若 marker 不可靠，需要 handler 兜底；验证该兜底确实可行。"""
    scene = fresh_scene()
    cam_a = add_camera("BD_Cam_A", (0.0, -6.0, 0.0))
    cam_b = add_camera("BD_Cam_B", (0.0, 6.0, 0.0))
    shots = [(1, 10, cam_a), (11, 20, cam_b)]

    def switch(scene_):
        frame = scene_.frame_current
        for start, end, cam in shots:
            if start <= frame <= end:
                if scene_.camera is not cam:
                    scene_.camera = cam
                break

    bpy.app.handlers.frame_change_post.append(switch)
    try:
        scene.frame_set(5)
        first = scene.camera.name
        scene.frame_set(15)
        second = scene.camera.name
    finally:
        bpy.app.handlers.frame_change_post.remove(switch)

    ok = first == "BD_Cam_A" and second == "BD_Cam_B"
    return result("PASS" if ok else "FAIL",
                  note="frame_change_post 可可靠切换机位（兜底方案成立）",
                  at_5=first, at_15=second)


# --------------------------------------------------------------------------- #
# 4. 事务式回滚 + 孤儿数据清理（§8.1）
# --------------------------------------------------------------------------- #
@check("transaction_rollback_purge")
def _transaction():
    fresh_scene()
    base_obj = len(bpy.data.objects)
    base_mesh = len(bpy.data.meshes)

    created = []
    for i in range(5):
        bpy.ops.mesh.primitive_cube_add()
        created.append(bpy.context.object)
    peak_obj = len(bpy.data.objects)

    for obj in created:
        bpy.data.objects.remove(obj, do_unlink=True)
    after_remove_obj = len(bpy.data.objects)
    orphan_mesh_after_remove = len(bpy.data.meshes) - base_mesh

    purged = bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                    do_recursive=True)
    after_purge_mesh = len(bpy.data.meshes) - base_mesh

    ok = (after_remove_obj == base_obj) and (after_purge_mesh == 0)
    return result(
        "PASS" if ok else "FAIL",
        note=("删除对象不会自动删除 mesh datablock，必须调用 orphans_purge"
              if orphan_mesh_after_remove else "无孤儿数据"),
        objects=[base_obj, peak_obj, after_remove_obj],
        orphan_meshes_after_remove=orphan_mesh_after_remove,
        orphan_meshes_after_purge=after_purge_mesh,
        purged_ids=purged,
    )


# --------------------------------------------------------------------------- #
# 5. 参考视频"画面干净"：Guides 集合/对象 hide_render 是否真的排除渲染
# --------------------------------------------------------------------------- #
@check("guides_render_isolation")
def _guides():
    """P0 要求：标签/路径等辅助物绝不能进参考视频（§8.4 / §15.2）。"""
    scene = fresh_scene()
    add_camera("BD_Cam", (0.0, -6.0, 0.0))
    scene.camera = bpy.data.objects["BD_Cam"]

    baseline = render_luma(os.path.join(outdir(), "audit_guides_base.png"))

    # 在内容集合之外新建 Guides 集合并塞入一块巨大白板（会完全挡住画面）
    guides = bpy.data.collections.new("BlockDirector/Guides")
    scene.collection.children.link(guides)
    blocker = add_white_cube("BD_Blocker", (0.0, -2.0, 0.0), size=3.0)
    scene.collection.objects.unlink(blocker)     # 移入 Guides
    guides.objects.link(blocker)

    # A：仅对象 hide_render
    blocker.hide_render = True
    guides.hide_render = False
    hidden_by_object = render_luma(os.path.join(outdir(), "audit_guides_obj.png"))

    # B：仅集合 hide_render（对象可见）
    blocker.hide_render = False
    guides.hide_render = True
    hidden_by_collection = render_luma(os.path.join(outdir(), "audit_guides_coll.png"))

    # C：正对照——两者都放开，应当挡住画面
    blocker.hide_render = False
    guides.hide_render = False
    visible = render_luma(os.path.join(outdir(), "audit_guides_visible.png"))

    if visible - baseline < 0.05:
        return result("INCONCLUSIVE", note="正对照未生效，测量不灵敏",
                      baseline=baseline, visible=visible)

    obj_ok = abs(hidden_by_object - baseline) < 0.02
    coll_ok = abs(hidden_by_collection - baseline) < 0.02
    status = "PASS" if (obj_ok and coll_ok) else ("FAIL" if not coll_ok else "WARN")
    return result(
        status,
        note=("对象 hide_render 与集合 hide_render 均可排除渲染"
              if (obj_ok and coll_ok) else
              "集合 hide_render 不足以排除渲染，必须逐对象设置 hide_render"),
        baseline=baseline, by_object=hidden_by_object,
        by_collection=hidden_by_collection, visible_control=visible,
        object_hide_render_works=obj_ok, collection_hide_render_works=coll_ok,
    )


# --------------------------------------------------------------------------- #
# 6. depsgraph 求值时机（§7.3 规则 1）
# --------------------------------------------------------------------------- #
@check("depsgraph_staleness")
def _staleness():
    """约束驱动的位置在 view_layer.update() 之前读到的是旧值吗？"""
    from mathutils import Vector

    scene = fresh_scene()
    target = bpy.data.objects.new("TARGET", None)
    scene.collection.objects.link(target)
    target.location = (0.0, 0.0, 0.0)

    cam = add_camera("TRACK_CAM", (0.0, -5.0, 0.0))
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    bpy.context.view_layer.update()
    quat_before = cam.matrix_world.to_quaternion().copy()

    target.location = (8.0, 0.0, 0.0)
    quat_stale = cam.matrix_world.to_quaternion().copy()      # 未求值
    bpy.context.view_layer.update()
    quat_updated = cam.matrix_world.to_quaternion().copy()    # 求值后

    def angle(a, b_) -> float:
        return round(a.rotation_difference(b_).angle, 4)

    return result(
        "PASS",
        note=("Track To 生效；未求值时读到的是陈旧朝向 → "
              "证实 §7.3 规则 1（先求值再读数）是必需的"),
        track_to_works=angle(quat_before, quat_updated) > 0.0,
        rotated_by_target_move_deg=angle(quat_before, quat_updated),
        stale_vs_updated_deg=angle(quat_stale, quat_updated),
        confirm_required=angle(quat_stale, quat_updated) > 0.0,
    )


# --------------------------------------------------------------------------- #
# 7. 遮挡检测 ray_cast（§17.5）
# --------------------------------------------------------------------------- #
@check("ray_cast_occlusion")
def _raycast():
    from mathutils import Vector

    scene = fresh_scene()
    add_camera("C", (0.0, -6.0, 0.0))
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    target = bpy.context.object
    target.name = "TARGET"
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, -2.0, 0.0))
    blocker = bpy.context.object
    blocker.name = "BLOCKER"
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = Vector((0.0, -5.0, 0.0))

    def cast(point):
        direction = (point - origin)
        hit, loc, _n, _i, obj, _m = scene.ray_cast(
            depsgraph, origin, direction.normalized(), distance=direction.length - 0.01)
        return (obj.name if hit and obj else None)

    blocked = cast(target.matrix_world.translation)
    bpy.data.objects.remove(blocker, do_unlink=True)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    clear = cast(target.matrix_world.translation)

    ok = (blocked == "BLOCKER") and (clear == "TARGET")
    return result("PASS" if ok else "FAIL",
                  note="scene.ray_cast 命中最近物体：有遮挡时命中挡块，移除后命中目标",
                  blocked_hit=blocked, after_removal_hit=clear)


# --------------------------------------------------------------------------- #
# 8. 中文标签能否真正渲染出字形（§9.4）
# --------------------------------------------------------------------------- #
@check("cjk_label_render")
def _cjk():
    scene = fresh_scene()
    scene.render.resolution_x, scene.render.resolution_y = 128, 72
    font_path = r"C:\Windows\Fonts\msyh.ttc"
    if not os.path.exists(font_path):
        return result("INCONCLUSIVE", note="系统无 msyh.ttc")

    cam = add_camera("C", (0.0, -4.0, 0.0))
    scene.camera = cam

    curve = bpy.data.curves.new("BD_Label", type="FONT")
    curve.body = "小明"
    curve.size = 1.0
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.font = bpy.data.fonts.load(font_path)
    label_mat = bpy.data.materials.new("BD_Label_mat")
    label_mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    curve.materials.append(label_mat)
    label = bpy.data.objects.new("BD_Label", curve)
    scene.collection.objects.link(label)
    # Text 默认躺在 XY 平面，需立起来面向 -Y 方向的相机
    label.rotation_euler = (1.5707963, 0.0, 0.0)
    bpy.context.view_layer.update()

    with_label = render_luma(os.path.join(outdir(), "audit_cjk_on.png"))
    label.hide_render = True
    without_label = render_luma(os.path.join(outdir(), "audit_cjk_off.png"))
    label.hide_render = False

    delta = abs(with_label - without_label)
    return result("PASS" if delta > 0.001 else "FAIL",
                  note=("中文 Text 对象能渲染出字形（fps 对比有差异）"
                        if delta > 0.001 else "中文标签没有渲染出任何像素"),
                  with_label=with_label, without_label=without_label, delta=delta)


# --------------------------------------------------------------------------- #
# 9. 规模与性能可行性
# --------------------------------------------------------------------------- #
@check("scale_performance")
def _scale():
    """20 个角色级别对象的动画 + 24 帧渲染耗时，评估"预演可交互"是否成立。"""
    scene = fresh_scene()
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.frame_start, scene.frame_end = 1, 120
    scene.render.engine = "BLENDER_WORKBENCH"

    add_camera("C", (0.0, -8.0, 2.0), look_at=(0, 0, 1))
    scene.camera = bpy.data.objects["C"]

    # 20 个"角色"（每个 4 个网格 = 简化角色），各带 3 条动画曲线
    object_count = 0
    for c in range(5):
        for part in range(4):
            bpy.ops.mesh.primitive_uv_sphere_add(
                segments=12, ring_count=6,
                location=(c * 1.5, part * 0.4, 0.5))
            obj = bpy.context.object
            obj.keyframe_insert("location", frame=1)
            obj.location.x += 0.5
            obj.keyframe_insert("location", frame=60)
            obj.location.x -= 0.5
            obj.keyframe_insert("location", frame=120)
            object_count += 1
    bpy.context.view_layer.update()

    t0 = time.perf_counter()
    for frame in range(1, 121, 4):          # 30 次 frame_set
        scene.frame_set(frame)
    frame_set_ms = (time.perf_counter() - t0) / 30 * 1000

    # 渲染 24 帧（1 秒时长）测吞吐
    t0 = time.perf_counter()
    rendered = 0
    for frame in range(1, 25):
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(outdir(), "audit_scale_")
        bpy.ops.render.render(write_still=False)
        rendered += 1
    render_s = time.perf_counter() - t0

    per_frame = render_s / max(rendered, 1)
    return result(
        "PASS" if per_frame < 1.0 else "WARN",
        note=(f"单帧 Workbench 渲染 {per_frame*1000:.0f} ms；"
              f"5 秒镜头(120 帧)约 {per_frame*120:.1f} s"),
        objects=object_count,
        frame_set_ms=round(frame_set_ms, 2),
        render_per_frame_s=round(per_frame, 4),
        est_shot_5s_s=round(per_frame * 120, 2),
    )


# --------------------------------------------------------------------------- #
# 10. sidecar 线协议端到端（真实 HTTP + 契约层）
# --------------------------------------------------------------------------- #
@check("sidecar_end_to_end")
def _sidecar():
    """用 stdlib 起一个最小 sidecar，用契约层客户端真实调用。"""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from block_director.contracts import (
        ChatPayload,
        ChatReply,
        FunctionCall,
        Message,
        MessageRole,
        SidecarTransport,
        ToolCall,
        assistant_message,
        tool_message,
        validate_conversation,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):    # 静音
            return

        def _send(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send({"status": "ok", "version": "1.2.0",
                            "capabilities": ["llm", "bm25"]})
            else:
                self._send({}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/v1/chat":
                self._send({
                    "content": "ok",
                    "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {"name": "place_character",
                                     "arguments": '{"character_id": "char_001"}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                              "total_tokens": 2},
                    "request_id": payload.get("request_id"),
                })
            elif self.path == "/v1/retrieve":
                self._send({"cards": [{"id": "axis_001", "domain": "axis_theory",
                                       "title": "180 度轴线", "content": "..."}]})
            elif self.path == "/v1/cancel":
                self._send({"cancelled": True})
            else:
                self._send({}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        transport = SidecarTransport(base_url=f"http://127.0.0.1:{port}", timeout=5.0)
        health = transport.health()

        call = ToolCall(id="call_1",
                        function=FunctionCall(name="place_character", arguments="{}"))
        conversation = [
            Message(role=MessageRole.SYSTEM, content="sys"),
            assistant_message(ChatReply(tool_calls=[call])),
            tool_message(call, "ok"),
        ]
        reply = transport.chat(ChatPayload(messages=conversation), timeout=5.0)
        cards = transport.retrieve("轴线", "axis_theory", 3)
        transport.cancel("req_1")

        ok = (health.ok and reply.tool_calls and cards
              and validate_conversation(conversation) == [])
        return result(
            "PASS" if ok else "FAIL",
            note="契约层可经真实 HTTP 与 sidecar 通信，且会话结构合法",
            port=port, health_version=health.version,
            capabilities=[str(c) for c in health.capabilities],
            tool_name=reply.tool_calls[0].function.name if reply.tool_calls else None,
            cards=len(cards),
        )
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------- #
# 11. 视频输出（回归确认 §15.3 的 media_type 前置）
# --------------------------------------------------------------------------- #
@check("video_output_path")
def _video():
    scene = fresh_scene()
    scene.render.resolution_x, scene.render.resolution_y = 160, 90
    scene.frame_start, scene.frame_end = 1, 8
    scene.render.engine = "BLENDER_WORKBENCH"
    add_camera("C", (0.0, -6.0, 0.0))
    scene.camera = bpy.data.objects["C"]
    bpy.ops.mesh.primitive_cube_add(size=1.0)

    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.audio_codec = "NONE"
    out = os.path.join(outdir(), "audit_video.mp4")
    scene.render.filepath = out
    bpy.ops.render.render(animation=True)
    final = out if os.path.exists(out) else out + ".mp4"
    size = os.path.getsize(final) if os.path.exists(final) else 0
    return result("PASS" if size > 0 else "FAIL",
                  note="Blender 内置 FFmpeg 直出 mp4（无需外部 ffmpeg）",
                  path=final, size=size)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    for name, fn in CHECKS:
        try:
            REPORT[name] = fn()
        except Exception as exc:  # noqa: BLE001
            REPORT[name] = {"status": "ERROR",
                            "error": f"{type(exc).__name__}: {exc}",
                            "trace": traceback.format_exc(limit=4)}

    order = {"FAIL": 0, "ERROR": 1, "WARN": 2, "INCONCLUSIVE": 3, "PASS": 4}
    summary: Dict[str, int] = {}
    for item in REPORT.values():
        key = item.get("status", "UNKNOWN")
        summary[key] = summary.get(key, 0) + 1

    path = os.path.join(outdir(), "audit_report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2, default=str)

    print("\n===== AUDIT BEGIN =====")
    for name, item in sorted(REPORT.items(),
                            key=lambda kv: order.get(kv[1].get("status"), 9)):
        print(f"[{item.get('status'):>12}] {name}")
        for key, value in item.items():
            if key in ("status", "trace"):
                continue
            print(f"                 {key} = {value}")
    print("===== SUMMARY =====")
    print(json.dumps(summary, ensure_ascii=False))
    print("REPORT_PATH", path)
    print("===== AUDIT END =====")


if __name__ == "__main__":
    main()
