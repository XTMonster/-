"""v1.4 X11 / BW-2：两个标签开关的**生效域**必须各归各位。

* ``character.label_render`` = **标签是否进参考视频** → 渲染路径
  （``create_render_label``，对象名 ``BD_Label_<char_id>_Fill/_Stroke``，
  集合 ``BlockDirector/Labels``，``hide_render=False``）；
* ``ui.show_labels`` = **Guides 视口标签是否可见** → 只在
  ``label_render=False`` 的 Guides 路径（``create_label``）上生效。

v1.3 的毛病是"半接线"：``ui.show_labels`` 只在 ``else`` 分支被读，而默认
``label_render=True``，于是它**完全无效**；``cast_editor`` 新增角色时更是
根本不读它。这个探针按生效域把四种组合都钉住。

运行：blender --background --factory-startup --python tools/blender_tests/test_label_toggles.py
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

from _fixtures import two_shot_plan  # noqa: E402
from block_director.contracts.cast import SceneSpec  # noqa: E402
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.layer3_engine.collection_router import (  # noqa: E402
    GUIDES_COLLECTION,
    LABELS_COLLECTION,
    ensure_collections,
)
from block_director.layer3_engine.shot_builder import build_scene  # noqa: E402
from block_director.settings import reset_config, set_config  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def _build(*, label_render: bool, show_labels: bool, with_labels: bool = True):
    config = AppConfig()
    config.character.label_render = bool(label_render)
    config.ui.show_labels = bool(show_labels)
    set_config(config)
    plan = two_shot_plan()
    spec = SceneSpec.from_plan(plan)
    spec.with_labels = bool(with_labels)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 180
    ensure_collections(scene)
    build_scene(plan, spec, clear_scene=True)
    return scene


def _in_collection(name: str) -> list:
    collection = bpy.data.collections.get(name)
    return list(collection.objects) if collection else []


def _render_label_state() -> dict:
    fills = [obj for obj in _in_collection(LABELS_COLLECTION)
             if obj.name.endswith("_Fill")]
    strokes = [obj for obj in _in_collection(LABELS_COLLECTION)
               if obj.name.endswith("_Stroke")]
    guides = [obj for obj in _in_collection(GUIDES_COLLECTION)
              if "Label" in obj.name]
    return {"fills": [obj.name for obj in fills],
            "strokes": [obj.name for obj in strokes],
            "labels_hidden": [obj.hide_render for obj in fills + strokes],
            "guides": [(obj.name, bool(obj.hide_render),
                        bool(obj.hide_viewport)) for obj in guides]}


def t_render_labels_ignore_the_viewport_toggle():
    """生效域 ①：`label_render=True` 时 `ui.show_labels` **不得**影响渲染标签。"""
    _build(label_render=True, show_labels=True)
    shown = _render_label_state()
    _build(label_render=True, show_labels=False)
    hidden = _render_label_state()
    return {"ok": (len(shown["fills"]) == 2 and len(shown["strokes"]) == 2
                   and not any(shown["labels_hidden"])
                   and shown["fills"] == hidden["fills"]
                   and shown["labels_hidden"] == hidden["labels_hidden"]
                   and shown["guides"] == []),
            "show_labels_true": shown, "show_labels_false": hidden}


def t_guides_label_follows_the_viewport_toggle():
    """生效域 ②：`label_render=False` 时标签进 Guides，`show_labels` 控制可见。"""
    _build(label_render=False, show_labels=True)
    on = _render_label_state()
    _build(label_render=False, show_labels=False)
    off = _render_label_state()
    visible = [item for item in on["guides"] if item[2] is False]
    hidden = [item for item in off["guides"] if item[2] is True]
    return {"ok": (len(on["guides"]) == 2 and len(visible) == 2
                   and len(hidden) == 2
                   and all(item[1] for item in on["guides"])  # hide_render=True
                   and on["fills"] == [] and on["strokes"] == []),
            "show_labels_true": on, "show_labels_false": off}


def t_with_labels_false_creates_nothing():
    _build(label_render=True, show_labels=True, with_labels=False)
    state = _render_label_state()
    return {"ok": (state["fills"] == [] and state["strokes"] == []
                   and state["guides"] == []), "state": state}


def t_cast_editor_passes_the_toggle_through():
    """X11 的另一半：新增角色时也必须读 `ui.show_labels`。"""
    from block_director.layer3_engine import cast_editor
    from block_director.layer3_engine.scene_context import get_context

    _build(label_render=False, show_labels=False)
    result = cast_editor.add_cast_member("新角色", "#44AA88")
    context = get_context()
    character = context.characters.get(result["character_id"])
    label = next((obj for obj in bpy.data.objects
                  if obj.name.startswith(f"BD_Char_{character.name}_Label")),
                 None)
    return {"ok": label is not None and bool(label.hide_viewport) is True,
            "label": label.name if label else None,
            "hide_viewport": bool(label.hide_viewport) if label else None}


def main() -> int:
    capture_main_thread()
    check("render_labels_ignore_the_viewport_toggle",
          t_render_labels_ignore_the_viewport_toggle)
    check("guides_label_follows_the_viewport_toggle",
          t_guides_label_follows_the_viewport_toggle)
    check("with_labels_false_creates_nothing",
          t_with_labels_false_creates_nothing)
    check("cast_editor_passes_the_toggle_through",
          t_cast_editor_passes_the_toggle_through)
    reset_config()

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS},
        ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
