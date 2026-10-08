"""v1.6 A1: torso changed from rounded box to cylinder.

The cylinder is constructed with the same BODY_RADIUS / BODY_HEIGHT so its
world AABB is identical to the old rounded-box torso. This probe verifies
that the footprint, anchor points and total height stay unchanged.
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

from block_director.cinema.anchor import DEFAULT_PROFILE as PROFILE  # noqa: E402
from block_director.layer3_engine.character_system import (  # noqa: E402
    character_factory,
    create_character,
)
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BD_World")
    ensure_collections(scene)
    return scene


def _torso_bounds(name: str) -> dict:
    body = bpy.data.objects.get(f"BD_Char_{name}_Body")
    if body is None:
        raise AssertionError(f"torso object BD_Char_{name}_Body not found")
    corners = [body.matrix_world @ Vector(corner) for corner in body.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    return {
        "min": [round(min(xs), 6), round(min(ys), 6), round(min(zs), 6)],
        "max": [round(max(xs), 6), round(max(ys), 6), round(max(zs), 6)],
        "size": [round(max(xs) - min(xs), 6), round(max(ys) - min(ys), 6),
                 round(max(zs) - min(zs), 6)],
        "vertices": len(body.data.vertices),
    }


def _anchors(name: str) -> dict:
    head = bpy.data.objects.get(f"BD_Char_{name}_Head")
    label = bpy.data.objects.get(f"BD_Char_{name}_LabelAnchor")
    if head is None or label is None:
        raise AssertionError("missing head or label anchor")
    return {
        "head_center_z": round(head.matrix_world.translation.z, 6),
        "label_anchor_z": round(label.matrix_world.translation.z, 6),
    }


def t_cylinder_torso_aabb_matches_bounding_box() -> dict:
    """Cylinder torso must have the same world AABB as the old rounded box."""
    fresh_scene()
    create_character("char_cyl", "Cyl", "#C8C8D0",
                     location=(1.0, 2.0, 0.0), facing=(0.0, 1.0, 0.0))
    bounds = _torso_bounds("Cyl")
    expected_min = [1.0 - character_factory.BODY_RADIUS,
                    2.0 - character_factory.BODY_RADIUS,
                    PROFILE.hip_z]
    expected_max = [1.0 + character_factory.BODY_RADIUS,
                    2.0 + character_factory.BODY_RADIUS,
                    PROFILE.hip_z + character_factory.BODY_HEIGHT]
    deltas = [abs(bounds["min"][i] - expected_min[i]) for i in range(3)]
    deltas += [abs(bounds["max"][i] - expected_max[i]) for i in range(3)]
    max_delta = max(deltas)
    ok = max_delta <= 1e-6
    return {
        "ok": ok,
        "bounds": bounds,
        "expected_min": [round(v, 6) for v in expected_min],
        "expected_max": [round(v, 6) for v in expected_max],
        "max_delta": round(max_delta, 9),
    }


def t_anchor_points_unchanged() -> dict:
    """Head center and label anchor must stay at the profile values."""
    fresh_scene()
    create_character("char_anc", "Anc", "#C8C8D0")
    anchors = _anchors("Anc")
    expected = {
        "head_center_z": round(PROFILE.head_center_z, 6),
        "label_anchor_z": round(PROFILE.label_anchor_z, 6),
    }
    ok = anchors == expected
    return {"ok": ok, "anchors": anchors, "expected": expected}


def t_total_height_unchanged() -> dict:
    """角色总高 = 1.70 m (头心 + 头半径)。"""
    fresh_scene()
    create_character("char_h", "H", "#C8C8D0")
    zs = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        for corner in evaluated.bound_box:
            zs.append((evaluated.matrix_world @ Vector(corner)).z)
    total = round(max(zs) - min(zs), 4) if zs else 0.0
    ok = abs(total - PROFILE.head_top_z) <= 1e-4
    return {"ok": ok, "total_height": total, "expected": PROFILE.head_top_z}


def t_cylinder_vertex_count() -> dict:
    """The torso must be a 32-segment cylinder (2 rings x 32 verts = 64)."""
    fresh_scene()
    create_character("char_shape", "Shape", "#C8C8D0")
    bounds = _torso_bounds("Shape")
    expected_size = [
        round(character_factory.BODY_RADIUS * 2, 6),
        round(character_factory.BODY_RADIUS * 2, 6),
        round(character_factory.BODY_HEIGHT, 6),
    ]
    expected_vertices = 64  # primitive_cylinder_add(vertices=32) => 2 rings x 32
    profile = cylinder_profile(bpy.data.objects["BD_Char_Shape_Body"])
    ok = (bounds["size"] == expected_size and bounds["vertices"] == expected_vertices
          and profile["ok"])
    return {
        "ok": ok,
        "size": bounds["size"],
        "expected_size": expected_size,
        "vertices": bounds["vertices"],
        "expected_vertices": expected_vertices,
        "profile": profile,
    }


def cylinder_profile(body) -> dict:
    """Independent mesh observation: 32 equally spaced vertices on each cap ring."""
    radius = character_factory.BODY_RADIUS
    half_height = character_factory.BODY_HEIGHT / 2
    rings = {-1: [], 1: []}
    radial_error = 0.0
    height_error = 0.0
    for vertex in body.data.vertices:
        x, y, z = vertex.co
        radial_error = max(radial_error, abs(math.hypot(x, y) - radius))
        height_error = max(height_error, abs(abs(z) - half_height))
        rings[-1 if z < 0 else 1].append(math.atan2(y, x) % math.tau)
    angle_error = 0.0
    for angles in rings.values():
        angles.sort()
        if not angles:
            # Finite sentinel (any value > 1e-6 fails the check). math.inf is
            # banned in probes: json.dumps would emit non-finite JSON that
            # run_tests.ps1 cannot parse (tools/check_assertions.py rule 2).
            angle_error = 999.0
            continue
        wrapped = angles[1:] + [angles[0] + math.tau]
        angle_error = max(angle_error, max(
            abs((right - left) - math.tau / 32)
            for left, right in zip(angles, wrapped)))
    counts = [len(rings[-1]), len(rings[1])]
    return {
        "ok": (counts == [32, 32] and radial_error <= 1e-6
               and height_error <= 1e-6 and angle_error <= 1e-6),
        "ring_counts": counts, "radial_error": radial_error,
        "height_error": height_error, "angle_error": angle_error,
    }


def t_cylinder_profile_detects_damage_hidden_by_vertex_count_and_aabb():
    fresh_scene()
    create_character("char_damaged", "Damaged", "#C8C8D0")
    body = bpy.data.objects["BD_Char_Damaged_Body"]
    before = _torso_bounds("Damaged")
    assert cylinder_profile(body)["ok"]
    # Move a non-extreme vertex inward: the AABB and number of vertices stay
    # identical, but it is no longer the specified cylinder.
    vertex = next(v for v in body.data.vertices
                  if 0.01 < v.co.x < 0.24 and 0.01 < v.co.y < 0.24)
    vertex.co.x *= 0.5
    vertex.co.y *= 0.5
    body.data.update()
    bpy.context.view_layer.update()
    after = _torso_bounds("Damaged")
    profile = cylinder_profile(body)
    assert after == before, (before, after)
    assert profile["ok"] is False, profile
    return {"ok": True, "same_bounds_and_count": True,
            "detected_radial_error": profile["radial_error"]}


def main() -> int:
    capture_main_thread()
    os.makedirs(ROOT / "tools" / "_probe_out", exist_ok=True)

    check("cylinder_torso_aabb_matches_bounding_box",
          t_cylinder_torso_aabb_matches_bounding_box)
    check("anchor_points_unchanged", t_anchor_points_unchanged)
    check("total_height_unchanged", t_total_height_unchanged)
    check("cylinder_vertex_count", t_cylinder_vertex_count)
    check("cylinder_profile_detects_hidden_damage",
          t_cylinder_profile_detects_damage_hidden_by_vertex_count_and_aabb)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS,
         "note": "v1.6 A1: cylinder torso keeps the same AABB and anchors"},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
