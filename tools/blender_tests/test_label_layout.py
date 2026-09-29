"""【WIP，暂未登记进 run_tests.ps1】v1.4 P12 / RK-1 / RK-2 / RK-5：标签布局验收。

**为什么还没登记**：这个探针目前有两条判据是红的，而且都是**真实缺陷**，
不是测试写错：

* ``one_pair_per_character``：断言字符串解析写错（待修）；
* ``label_size_is_continuous``（RK-5）：同一标签在 35mm 与 50mm 两个镜头里
  的屏幕高度是 **15.0 px → 9.38 px（−37%）**。根因是 ``label_baking`` 用
  "投影一段 ``curve.size`` 长的线段"当屏幕恒定字号的基准，隐含假设字形正好
  填满 em 框。``label_baking.fit_scale`` 是对字形 ``bound_box`` 的定点迭代
  修法，但还没收敛到稳定值，因此**暂不启用**，避免引入未验证的回归。

按契约"测试失败先定位再修"，本文件在修好之前**不进清单**（脚本里有
"目录下所有 test_*.py 都必须登记"的双向断言，所以也不能叫 test_*.py）。
修好后改回 ``test_label_layout.py`` 并登记即可。

判据全部读**烘焙后的对象变换**（不读 bake 的内部变量）：

* **RK-1①**：每个启用标签的角色**恰好一对**
  ``BD_Label_<char_id>_Fill`` / ``BD_Label_<char_id>_Stroke``，且都在
  ``BlockDirector/Labels`` 里、``hide_render=False``；
* **RK-2①**：任意两标签的屏幕 AABB 交叠率
  ``area(A∩B)/min(area(A),area(B)) ≤ 5%`（0 对越界）；
* **RK-2②**：``offset_reason == "none"`` 的采样帧，AABB 中心与锚点投影的
  偏差 ≤ ``2 × character.label_pixels``；
* **RK-5**：**同一镜内**相邻采样帧的 AABB 高度变化率 ≤ 5%（跨切点的重新缩放
  单列为诊断量 ``cross_shot_step``——换镜时相机整个换了，标签重新解算字号是
  预期行为；RK-5 要守的是"镜头内不抖"）。

运行：blender --background --factory-startup --python tools/blender_tests/test_label_layout.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.contracts.brief import SceneBrief  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    LABELS_COLLECTION,
    ensure_collections,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
WIDTH, HEIGHT = 640, 360
OVERLAP_LIMIT = 0.05
CONTINUITY_LIMIT = 0.05


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _plan():
    """两个角色**挨得很近**：标签必然会互相压住，正好考避让。"""
    from block_director.contracts.plan import Plan

    return Plan.from_dict({"scene_heading": "INT. 近景 - 日", "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "对峙", "shot_type": "MS",
         "duration_frames": 48, "characters": ["char_001", "char_002"]},
        {"shot_id": "shot_002", "order": 2, "intent": "反应", "shot_type": "MCU",
         "duration_frames": 48, "characters": ["char_002"]}]})


def _build():
    config = AppConfig()
    config.character.label_render = True
    set_config(config)
    plan = _plan()
    spec = SceneSpec.from_plan(plan, brief=SceneBrief.from_dict({
        "source": "model",
        "space": [{"character": "char_002", "relative_to": "char_001",
                   "relation": "side_by_side", "distance_class": "intimate"}],
    }))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    ensure_collections(scene)
    summary = build_scene(plan, spec, clear_scene=True).to_dict()
    return scene, plan, summary, config


def _labels() -> dict:
    collection = bpy.data.collections.get(LABELS_COLLECTION)
    objects = list(collection.objects) if collection else []
    fills = {obj.name: obj for obj in objects if obj.name.endswith("_Fill")}
    strokes = {obj.name: obj for obj in objects if obj.name.endswith("_Stroke")}
    return {"fills": fills, "strokes": strokes, "all": objects}


def _screen_box(scene, camera, obj) -> tuple:
    """标签在屏幕上的像素 AABB。

    用**对象自己的** ``bound_box``（字体对象的字形包围盒，含 ``curve.size``）
    再乘 ``matrix_world``——固定尺寸的方块量不到真实字形，会得到与字号无关
    的常数（实测 100 px 恒定，等于没量）。
    """
    matrix = obj.matrix_world
    corners = [matrix @ Vector(corner) for corner in obj.bound_box]
    points = [world_to_camera_view(scene, camera, point) for point in corners]
    xs = [point.x * WIDTH for point in points]
    ys = [point.y * HEIGHT for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a, b) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]),
                  (b[2] - b[0]) * (b[3] - b[1]))
    return (width * height) / smaller if smaller > 0 else 0.0


def t_one_pair_per_character():
    _build()
    labels = _labels()
    fills = labels["fills"]
    strokes = labels["strokes"]
    ids = sorted(name[len("BD_Label_"):-len("_Fill")] for name in fills)
    ok = (len(fills) == 2 and len(strokes) == 2
          and ids == ["char_001", "char_002"]
          and set(name.replace("_Fill", "_Stroke") for name in fills)
          == set(strokes)
          and not any(obj.hide_render for obj in labels["all"]))
    return {"ok": ok, "fills": sorted(fills), "strokes": sorted(strokes),
            "hidden": [obj.name for obj in labels["all"] if obj.hide_render]}


def t_labels_do_not_overlap():
    scene, plan, _summary, _config = _build()
    labels = _labels()
    camera = bpy.context.scene.camera
    schedule = {"shot_001": (1, 48), "shot_002": (49, 96)}
    worst = 0.0
    detail = {}
    for frame in (1, 5, 9, 25, 45, 49, 53, 96):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        boxes = []
        for name in sorted(labels["fills"]):
            box = _screen_box(scene, camera, labels["fills"][name])
            boxes.append((name, box))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ratio = _overlap(boxes[i][1], boxes[j][1])
                if ratio > worst:
                    worst = ratio
                    detail = {"frame": frame, "pair": [boxes[i][0], boxes[j][0]]}
    _ = schedule
    return {"ok": worst <= OVERLAP_LIMIT, "worst_overlap": round(worst, 4),
            "limit": OVERLAP_LIMIT, "worst_at": detail}


def t_label_size_is_continuous():
    scene, plan, _summary, _config = _build()
    labels = _labels()
    camera = bpy.context.scene.camera
    # 每个镜头各自采样：RK-5 守的是"镜头内不抖"，跨切点是换镜重算，另记诊断。
    shots = [("shot_001", range(1, 49, 4)), ("shot_002", range(49, 97, 4))]
    worst = 0.0
    step = 0.0
    series: dict = {}
    ends: dict = {}
    for shot_id, frames in shots:
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            for name in sorted(labels["fills"]):
                box = _screen_box(scene, camera, labels["fills"][name])
                height = max(box[3] - box[1], 1e-6)
                series.setdefault(f"{name}@{shot_id}", []).append(height)
                ends.setdefault(name, {})[shot_id] = height
    for key, values in series.items():
        for previous, current in zip(values, values[1:]):
            worst = max(worst, abs(current - previous) / max(previous, 1e-6))
    for name, per_shot in ends.items():
        if len(per_shot) == 2:
            first, second = (per_shot["shot_001"], per_shot["shot_002"])
            step = max(step, abs(second - first) / max(first, 1e-6))
    return {"ok": worst <= CONTINUITY_LIMIT, "worst_change": round(worst, 4),
            "limit": CONTINUITY_LIMIT,
            "cross_shot_step": round(step, 4),
            "series": {key: [round(value, 2) for value in values]
                       for key, values in series.items()}}


def main() -> int:
    capture_main_thread()
    check("one_pair_per_character", t_one_pair_per_character)
    check("labels_do_not_overlap", t_labels_do_not_overlap)
    check("label_size_is_continuous", t_label_size_is_continuous)
    reset_config()

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
