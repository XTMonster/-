"""Phase 4 集成测试：LLM 的眼睛（SceneState）与查询工具（执行文档 v1.2 §7.3/§7.4）。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_phase4_tools.py
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from _fixtures import two_shot_plan  # noqa: E402
from block_director.cinema.composition import PASS_SCORE  # noqa: E402
from block_director.layer3_engine.cinema_engine import create_camera  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.scene_context import get_context  # noqa: E402
from block_director.layer3_engine.scene_state import collect_scene_state  # noqa: E402
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.layer3_engine.tool_bindings import register_scene_tools  # noqa: E402
from block_director.layer3_engine.tool_bindings import (  # noqa: E402
    register_all_scene_tools,
)
from block_director.knowledge import TOKEN_LIMIT_TOOL, estimate_tokens  # noqa: E402
from block_director.layer5_orchestrator.tool_registry import ToolRegistry  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    ensure_collections(scene)
    return scene


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _built():
    fresh_scene()
    summary = build_scene(two_shot_plan())
    return summary, get_context()


# --------------------------------------------------------------------------- #
# 1. 轻量摘要 vs 完整投影
# --------------------------------------------------------------------------- #
def t_scene_state_light_vs_detailed():
    _summary, _context = _built()
    light = collect_scene_state(detailed=False)
    detailed = collect_scene_state(detailed=True)

    light_has_projection = any(c.screen_position is not None
                               for c in light.characters)
    first = detailed.characters[0]
    projected = (first.screen_position is not None
                 and 0.0 <= first.screen_position[0] <= 1.0
                 and 0.0 <= first.screen_position[1] <= 1.0)

    return {"ok": (len(light.characters) == 2 and not light_has_projection
                   and projected and first.in_frame is True
                   and first.height_fraction > 0.1
                   and light.camera is not None),
            "light_characters": len(light.characters),
            "light_has_projection": light_has_projection,
            "detailed_first": first.to_dict(),
            "camera": light.camera.to_dict()}


# --------------------------------------------------------------------------- #
# 2. 构建后上下文完整（角色/相机/景别/轴线）
# --------------------------------------------------------------------------- #
def t_context_is_populated():
    summary, context = _built()
    axis = context.axis
    return {"ok": (context is not None and len(context.characters) == 2
                   and len(context.cameras) == 2
                   and context.shot_types.get("shot_001") == "MLS"
                   and context.current_shot_id == "shot_001"
                   and axis is not None and axis.established_side in (1, -1)),
            "characters": sorted(context.characters),
            "cameras": sorted(context.cameras),
            "shot_types": context.shot_types,
            "axis_side": axis.established_side if axis else None,
            "axis_labels": [axis.left_label, axis.right_label] if axis else None}


# --------------------------------------------------------------------------- #
# 3. 四个查询工具都能被 LLM 正常调用
# --------------------------------------------------------------------------- #
def t_query_tools_are_callable():
    _built()
    registry = ToolRegistry()
    register_scene_tools(registry)

    #: v1.5 反漂移：**每一个注册进来的工具都必须被分类**（改动类 / 只读 / 控制类 /
    #: 计划）。驱动器靠 `MUTATING_TOOLS` 判断"这一轮到底动没动手"（`repair_applied`
    #: 曾经把只读的 `get_scene_state` 也算成动手，写出一条假记录）；新工具没分类
    #: 就会被当成只读，而这件事**没有任何别的地方会红**。
    from block_director.contracts.tools import (
        CONTROL_TOOL_NAMES, MUTATING_TOOLS, PLAN_TOOL, SHOT_DRAFT_TOOL,
        READ_ONLY_TOOLS,
    )
    known = (set(MUTATING_TOOLS) | set(READ_ONLY_TOOLS)
             | set(CONTROL_TOOL_NAMES) | {PLAN_TOOL, SHOT_DRAFT_TOOL})
    unclassified = set(registry.names()) - known
    if unclassified:
        return {"ok": False,
                "why": f"这些工具没有分类（改动/只读）：{sorted(unclassified)}"}

    state = registry.execute("get_scene_state", {})
    visibility = registry.execute("check_visibility", {})
    composition = registry.execute("check_composition", {})
    axis = registry.execute("check_axis", {})

    ok = (set(registry.names()) == {"get_scene_state", "check_visibility",
                                    "check_composition", "check_axis",
                                    "estimate_shot_duration"}
          and state.ok and "shot_001" in state.content
          and visibility.ok and "在画" in visibility.content
          and composition.ok and "构图评分" in composition.content
          and axis.ok and "轴线" in axis.content)
    return {"ok": ok, "tools": registry.names(),
            "state": state.content, "visibility": visibility.content,
            "composition": composition.content, "axis": axis.content}


# --------------------------------------------------------------------------- #
# 4. 角色被移出画面时可见性如实报告
# --------------------------------------------------------------------------- #
def t_visibility_reports_out_of_frame():
    _built()
    registry = ToolRegistry()
    register_scene_tools(registry)

    inside = registry.execute("check_visibility", {"character_id": "char_002"})
    character = get_context().characters["char_002"]
    character.root.location.x += 20.0
    bpy.context.view_layer.update()
    outside = registry.execute("check_visibility", {"character_id": "char_002"})

    return {"ok": inside.ok and "在画" in inside.content
            and outside.ok and "不在画" in outside.content,
            "before": inside.content, "after": outside.content}


# --------------------------------------------------------------------------- #
# 5. 越轴被 check_axis 抓出来
# --------------------------------------------------------------------------- #
def t_axis_violation_detected():
    _built()
    registry = ToolRegistry()
    register_scene_tools(registry)
    context = get_context()

    good = registry.execute("check_axis", {})
    # 站到**已确立侧别的对面**去。v1.2 这里把机位写死在 (0, -6)：默认站位一改
    # （两人相对而立，首镜机位落在 -Y 侧），(0, -6) 反而成了合法的一侧，
    # "越轴"就再也测不出来了。
    axis = context.axis
    opposite = -1.0 if axis.established_side > 0 else 1.0
    bad_camera = create_camera("evil", (0.0, opposite * 6.0, 1.2),
                               look_at=(0.0, 0.0, 1.0),
                               make_scene_camera=False)
    context.cameras["evil"] = bad_camera.camera
    context.current_shot_id = "evil"
    bad = registry.execute("check_axis", {})

    # 越轴是一次**失败的**检查（ok=False），这样驱动器的修复循环才知道要改
    return {"ok": good.ok and "合规" in good.content
            and not bad.ok and "180° 轴线" in bad.content,
            "good": good.content, "bad": bad.content}


# --------------------------------------------------------------------------- #
# 6. 参数错误是观察文本，不是异常
# --------------------------------------------------------------------------- #
def t_errors_are_observations():
    _built()
    registry = ToolRegistry()
    register_scene_tools(registry)
    unknown_character = registry.execute("check_visibility",
                                         {"character_id": "nobody"})
    unknown_camera = registry.execute("check_composition",
                                      {"camera_id": "BD_Cam_ghost"})
    bad_type = registry.execute("check_composition", {"camera_id": 123})
    return {"ok": (not unknown_character.ok and "找不到角色" in unknown_character.content
                   and not unknown_camera.ok and "找不到相机" in unknown_camera.content
                   and not bad_type.ok and "参数校验失败" in bad_type.content),
            "unknown_character": unknown_character.content,
            "unknown_camera": unknown_camera.content,
            "bad_type": bad_type.content}


# --------------------------------------------------------------------------- #
# 7. Light RAG 的 search_knowledge 也在同一个注册表里（§6.5 / §7.4）
# --------------------------------------------------------------------------- #
def t_knowledge_tool_is_callable():
    _built()
    registry = ToolRegistry()
    register_all_scene_tools(registry)

    hit = registry.execute("search_knowledge", {"query": "越轴 怎么换到另一侧"})
    scoped = registry.execute("search_knowledge",
                              {"query": "三分法 构图", "domain": "composition",
                               "top_k": 2})
    bad = registry.execute("search_knowledge", {"query": "构图",
                                                "domain": "nope"})
    ok = (set(registry.names()) == {"get_scene_state", "check_visibility",
                                    "check_composition", "check_axis",
                                    "estimate_shot_duration",
                                    "place_character", "move_character",
                                    "character_action", "look_at",
                                    "face_character",
                                    "interact_with", "setup_camera",
                                    "move_camera", "reframe",
                                    "search_knowledge", "revert_shot"}
          and hit.ok and "axis_cross" in hit.content
          and estimate_tokens(hit.content) <= TOKEN_LIMIT_TOOL + 10
          and scoped.ok and "[comp_thirds]" in scoped.content
          and not bad.ok and "参数校验失败" in bad.content)
    return {"ok": ok, "tools": registry.names(), "hit": hit.content,
            "scoped": scoped.content, "bad": bad.content}


def t_composition_judges_the_shots_own_subjects():
    """构图必须只看**本镜声明的角色**。

    v1.2 的 ``check_composition`` 拿全剧组当被摄主体：两人相对而立时，
    单人镜的搭档离机位更近、在画面里显得更大，于是评分从 71 掉到 40，
    修复循环被完全带偏（实测 shot_002：39.4 分，遮挡项 0.3）。
    """
    _summary, _context = _built()
    registry = ToolRegistry()
    register_scene_tools(registry)
    context = get_context()
    context.current_shot_id = "shot_002"          # 单人镜，搭档不在画面里
    result = registry.execute("check_composition", {})
    match = re.search(r"构图评分 ([0-9.]+)", result.content)
    score = float(match.group(1)) if match else None
    return {"ok": result.ok and score is not None and score > PASS_SCORE,
            "score": score, "content": result.content}


def main() -> int:
    capture_main_thread()
    check("composition_judges_the_shots_own_subjects",
          t_composition_judges_the_shots_own_subjects)
    check("scene_state_light_vs_detailed", t_scene_state_light_vs_detailed)
    check("context_is_populated", t_context_is_populated)
    check("query_tools_are_callable", t_query_tools_are_callable)
    check("visibility_reports_out_of_frame", t_visibility_reports_out_of_frame)
    check("axis_violation_detected", t_axis_violation_detected)
    check("errors_are_observations", t_errors_are_observations)
    check("knowledge_tool_is_callable", t_knowledge_tool_is_callable)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
