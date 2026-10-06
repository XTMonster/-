"""RK-8 在圆角方体上为什么报 90°？——把那个场景逐量打出来。

复刻 `tools/blender_tests/test_phase2_motion.py::t_rk8_body_tilt_matches_the_registered_angle`
的每一步，但在 `bake()` 前后把**躯干对象的世界矩阵**与**世界空间顶点云的三向方差**都打出来。

跑法：blender --background --factory-startup --python work/_probe_rk8_diag.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.layer3_engine.character_system.character_factory import (  # noqa: E402
    create_character,
)
from block_director.layer3_engine.character_system import MotionBlender  # noqa: E402
from block_director.motion.model import body_tilt_params  # noqa: E402


def world_stats(obj) -> dict:
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [tuple(evaluated.matrix_world @ v.co) for v in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    n = len(points)
    center = [sum(p[i] for p in points) / n for i in range(3)]
    var = [sum((p[i] - center[i]) ** 2 for p in points) / n for i in range(3)]
    return {"n": n, "center": [round(x, 4) for x in center],
            "var": [round(x, 6) for x in var],
            "matrix_world": [round(x, 4) for row in obj.matrix_world for x in row]}


def main() -> int:
    """同一套场景/动作/测量算法，只把躯干形状换一下（其余全同）。"""
    out = {}
    for variant in ("shipped_rounded_box", "replaced_cylinder"):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        character = create_character("char_001", "小明", "#FF6B6B")
        body = character.parts.get("body")
        if variant == "replaced_cylinder":
            #: 换掉对象后 `character.parts["body"]` 还指着被删的那个（会抛
            #: `ReferenceError: StructRNA ... has been removed`）⇒ 必须把新对象**写回**。
            body = _swap_to_cylinder(body)
            character.parts["body"] = body
        angle_deg, tilt_axis = body_tilt_params({"degrees": 12.0})
        blender = MotionBlender(character)
        blender.add("body_tilt", 1, 48, **{"degrees": 12.0})
        blender.bake()
        bpy.context.scene.frame_set(48)
        axis = _principal_axis(body)
        out[variant] = {"registered_deg": angle_deg, "tilt_axis": tilt_axis,
                        "stats_at_48": world_stats(body),
                        "principal": [round(x, 4) for x in (axis or [])],
                        "measured_deg": _angle_deg(axis)}
    print("BD_RK8 " + json.dumps(out, ensure_ascii=False))
    return 0


def _swap_to_cylinder(body):
    """把躯干换成旧形状（圆柱）——**只换 mesh 数据，保留对象本体**。

    为什么不像 A/B 探针那样删对象重建：`Character` 别处（`clear_animation` 等）还持有
    那些对象引用，删掉本体再建会抛 `ReferenceError: StructRNA ... has been removed`。
    这里只把 `body.data` 指到新圆柱网格上 ⇒ 引用、层级、枢轴、材质槽全不动。
    """
    bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.748)
    temporary = bpy.context.object
    cylinder_mesh = temporary.data
    bpy.data.objects.remove(temporary, do_unlink=True)
    body.data = cylinder_mesh
    return body


def _principal_axis(obj, *, iterations: int = 64):
    """与 `test_phase2_motion.py::_principal_axis` **逐字同一套**（幂迭代，种子 = +X）。"""
    from mathutils import Vector

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    if len(points) < 8:
        return None
    center = sum(points, Vector()) / len(points)
    covariance = [[0.0] * 3 for _ in range(3)]
    for point in points:
        delta = point - center
        for i in range(3):
            for j in range(3):
                covariance[i][j] += delta[i] * delta[j]
    def rayleigh(candidate) -> float:
        return sum(candidate[i] * sum(covariance[i][j] * candidate[j]
                                      for j in range(3)) for i in range(3))

    best, best_value = None, None
    third = 1.0 / (3.0 ** 0.5)
    for seed in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                 (third, third, third)):
        vector = Vector(seed).normalized()
        for _ in range(max(int(iterations), 1)):
            updated = Vector((sum(covariance[i][j] * vector[j] for j in range(3))
                              for i in range(3)))
            if updated.length < 1e-12:
                break
            vector = updated.normalized()
        value = rayleigh(vector)
        if best_value is None or value > best_value:
            best, best_value = vector, value
    return best


def _angle_deg(vector) -> float:
    import math

    if vector is None:
        return -1.0
    cos_value = max(-1.0, min(1.0, abs(vector.z) / max(vector.length, 1e-9)))
    return round(math.degrees(math.acos(cos_value)), 3)


if __name__ == "__main__":
    raise SystemExit(main())
