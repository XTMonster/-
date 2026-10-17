"""v1.4 P16 / RK-10 / F9：构图门通过率 ≥70%，并且这个数字**能被做坏**。

§1.4b 的两条防自证要求都在这里：

① 分子只读 ``shot_audit.composition_score ≥ composition_threshold``——
   **不得**用 ``passed``（那是"整镜无阻断错误"，把轴线/穿模/台词都算进来了）；
② 阈值必须等于**独立读到的**默认 ``PASS_SCORE``（v1.7 空间尺转正后为 80.0，
   2026-10-18 用户裁决，严格高于才算过），且把镜头做坏之后
   ``composition_score`` 必须**下降 ≥20 分**——否则把阈值写成 ``-1e9``
   就能恒绿。

反向突变按 §4.1b RK-10 的口径：做坏 ``⌈0.3 × 分母⌉ + 1`` 个原本通过的镜
（**至少 2 镜**；61 镜夹具上只坏 1 镜 = 98%，负例恒绿）。

运行：blender --background --factory-startup --python tools/blender_tests/test_composition_gate.py
"""

from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.cinema.composition import PASS_SCORE  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_auditor import BpyShotAuditor  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}
PASS_LINE = 0.70
SCORE_DROP = 20.0
EXCLUDED = ("ELS", "LS")


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _plan() -> Plan:
    """6 镜：含 ELS/LS（分母要排除它们）与四个含头部景别。"""
    # 单人与双人镜都要有：真实的计划不会让两个角色同时挤进一个特写，
    # 而"双人 CU"在构图上是天生无解的（既满足不了三分法又满足不了视线留白）。
    shots = [("shot_001", "MS", ["char_001", "char_002"]),
             ("shot_002", "MCU", ["char_001"]),
             ("shot_003", "CU", ["char_001"]),
             ("shot_004", "MLS", ["char_001", "char_002"]),
             ("shot_005", "ELS", ["char_001", "char_002"]),
             ("shot_006", "LS", ["char_001", "char_002"])]
    return Plan.from_dict({
        "scene_heading": "INT. 码头 - 日",
        "shots": [{"shot_id": shot_id, "order": index, "intent": "推进",
                   "shot_type": shot_type, "duration_frames": 48,
                   "characters": list(characters)}
                  for index, (shot_id, shot_type, characters)
                  in enumerate(shots, start=1)],
    })


def _build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    ensure_collections(scene)
    plan = _plan()
    build_scene(plan, SceneSpec.from_plan(plan), clear_scene=True)
    return scene, plan


def _audit(plan, scene) -> dict:
    """逐镜审核，返回 ``{shot_id: (score, threshold, shot_type)}``。"""
    auditor = BpyShotAuditor()
    out = {}
    for shot in plan.shots:
        scene.frame_set(1)
        bpy.context.view_layer.update()
        result = auditor.audit(shot.shot_id)
        out[shot.shot_id] = (result.score, auditor.composition_threshold,
                             str(shot.shot_type))
    return out


def _rate(audited) -> tuple:
    numerator = denominator = 0
    for shot_id, (score, threshold, shot_type) in audited.items():
        if shot_type.upper() in EXCLUDED:
            continue
        denominator += 1
        if score is not None and threshold is not None \
                and float(score) > float(threshold):
            numerator += 1
    return numerator, denominator


def t_gate_passes_and_threshold_has_one_source():
    scene, plan = _build()
    audited = _audit(plan, scene)
    numerator, denominator = _rate(audited)
    score, threshold, _ = audited["shot_001"]
    # 阈值只有一个来源：审核器自己（默认 PASS_SCORE）。这里独立读一次对拍。
    expected_threshold = PASS_SCORE  # config/auditor 的默认阀值（AppConfig 不存这个值）
    return {"ok": (denominator >= 1 and numerator / denominator >= PASS_LINE
                   and threshold == expected_threshold),
            "numerator": numerator, "denominator": denominator,
            "rate": round(numerator / denominator, 3) if denominator else 0.0,
            "threshold": threshold, "expected_threshold": expected_threshold,
            "scores": {key: value[0] for key, value in audited.items()}}


def t_breaking_the_framing_drops_the_rate():
    """反向突变：做坏 ⌈0.3×分母⌉+1 个（至少 2）镜 → 通过率必须掉到线下。"""
    scene, plan = _build()
    before = _audit(plan, scene)
    numerator, denominator = _rate(before)
    wanted = max(2, int(math.ceil(0.3 * denominator)) + 1)

    passing = [shot_id for shot_id, (score, threshold, shot_type)
               in before.items()
               if shot_type.upper() not in EXCLUDED and score is not None
               and score > threshold]
    broken = passing[:wanted]
    if len(broken) < wanted:
        return {"ok": False, "reason": "通过的镜头不够，做不坏这么多",
                "passing": passing, "wanted": wanted}

    # 做坏的方式必须**真的把主体弄出画**：挪相机不行——相机带 Track-To 约束，
    # 它会继续对准主体（实测挪 3 米后 MS 的构图分反而 +1.6，CU 只掉 5.9）。
    # 把角色本体的根节点挪出画面，`subject_in_frame_ratio` 才会塌。
    victims = set()
    for shot_id in broken:
        shot = next(item for item in plan.shots if item.shot_id == shot_id)
        victims.update(shot.characters)
    for character_id in victims:
        root = bpy.data.objects.get(f"BD_Char_{character_id}_Root")
        if root is None:
            return {"ok": False, "reason": f"找不到 {character_id} 的根节点"}
        # 挪到 30 米外：必须让**每一个**被做坏的镜都掉 ≥20 分，
        # 只掉 10 分说明"做坏"其实没坏透（§4.1b 的 ≥20 分是防自证的下界）。
        root.location = (root.location.x + 30.0, root.location.y + 6.0,
                         root.location.z)
    bpy.context.view_layer.update()
    after = _audit(plan, scene)
    new_numerator, new_denominator = _rate(after)
    drops = {}
    for shot_id in broken:
        old = before[shot_id][0]
        new = after[shot_id][0]
        drops[shot_id] = (round(float(old or 0.0) - float(new or 0.0), 2)
                          if new is not None else None)
    enough_drop = all(value is not None and value >= SCORE_DROP
                      for value in drops.values())
    return {"ok": (new_denominator == denominator
                   and new_numerator / new_denominator < PASS_LINE
                   and enough_drop),
            "broken": broken, "wanted": wanted,
            "rate_before": round(numerator / denominator, 3),
            "rate_after": round(new_numerator / new_denominator, 3),
            "score_drops": drops, "min_drop": SCORE_DROP}


def main() -> int:
    capture_main_thread()
    check("rk10_gate_passes_and_threshold_has_one_source",
          t_gate_passes_and_threshold_has_one_source)
    check("rk10_breaking_the_framing_drops_the_rate",
          t_breaking_the_framing_drops_the_rate)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
