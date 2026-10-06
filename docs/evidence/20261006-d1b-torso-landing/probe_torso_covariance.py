"""为什么 RK-8 的主惯性轴在圆角方体上翻了？——量顶点云的协方差，不做假设。

背景：换成圆角方体后 `rk8_body_tilt_matches_the_registered_angle` 从 12° 变成 90°（轴 = x）。
该判据用**世界空间顶点云的协方差主特征向量**当"躯干主惯性轴"。圆柱的顶点是绕轴均匀分布的
曲面网格 ⇒ 主轴＝几何轴；**方体**的顶点集中在 12 条棱与 8 个角上，是否还等于几何轴要量过才知道。

跑法：blender --background --factory-startup --python work/_probe_torso_covariance.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402

from block_director.layer3_engine.character_system import character_factory  # noqa: E402


def stats(obj) -> dict:
    mesh = obj.data
    points = [tuple(v.co) for v in mesh.vertices]
    n = len(points)
    center = [sum(p[i] for p in points) / n for i in range(3)]
    cov = [[0.0] * 3 for _ in range(3)]
    for p in points:
        d = [p[i] - center[i] for i in range(3)]
        for i in range(3):
            for j in range(3):
                cov[i][j] += d[i] * d[j] / n
    #: 幂迭代（从 x 起，与本仓 RK-8 同一套）＋用坐标轴当初始向量各跑一次取最大
    best = None
    for seed in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        v = list(seed)
        for _ in range(256):
            w = [sum(cov[i][j] * v[j] for j in range(3)) for i in range(3)]
            norm = sum(x * x for x in w) ** 0.5
            if norm < 1e-15:
                break
            v = [x / norm for x in w]
        lam = sum(v[i] * sum(cov[i][j] * v[j] for j in range(3)) for i in range(3))
        if best is None or lam > best[0]:
            best = (lam, v)
    return {"vertices": n, "var": [round(cov[i][i], 6) for i in range(3)],
            "eigenvalue": round(best[0], 6),
            "axis": [round(x, 4) for x in best[1]]}


def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    character = character_factory.create_character("char_001", "Probe", "#C8C8C8")
    body = character.parts.get("body")
    shipped = stats(body)
    #: 参照：把躯干换成圆柱（旧形状）再量一次
    parent, local = body.parent, tuple(body.location)
    materials = [slot.material for slot in body.material_slots if slot.material]
    bpy.data.objects.remove(body, do_unlink=True)
    bpy.ops.mesh.primitive_cylinder_add(radius=character_factory.BODY_RADIUS,
                                        depth=character_factory.BODY_HEIGHT)
    cylinder = bpy.context.object
    cylinder.parent = parent
    cylinder.location = local
    for material in materials:
        cylinder.data.materials.append(material)
    print("BD_PROBE " + json.dumps({"shipped_rounded_box": shipped,
                                    "reference_cylinder": stats(cylinder)},
                                   ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
