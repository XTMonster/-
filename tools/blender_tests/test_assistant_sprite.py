"""v1.7 D3：视口精灵注册探针。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_assistant_sprite.py

--background 下 draw_handler 不触发、精灵不注册（TDD §6.3 既有纪律），
因此断言：注册条件分支、帧表加载与 MODULES 对拍，不测像素。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bpy  # noqa: E402

from block_director import registration  # noqa: E402
from block_director.layer7_ui import assistant_sprite  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False,
                         "error": f"{type(exc).__name__}: {exc}"}


def t_not_registered_in_background():
    """--background 下 register() 不挂 handler（TDD §6.3 纪律）。"""
    assistant_sprite.register()
    return {"ok": not assistant_sprite.is_enabled()}


def t_frames_table_loads_real_assets():
    """真实 assets 目录能解析并加载帧表。"""
    assets_dir = assistant_sprite.resolve_assets_dir("")
    table = assistant_sprite.load_frames_table(assets_dir)
    return {"ok": bool(table), "assets": str(assets_dir),
            "clips": sorted(table.get("clips", {}))}


def t_sprite_module_in_registration_roster():
    """registration.MODULES 含精灵模块（双向对拍纪律）。"""
    return {"ok": "block_director.layer7_ui.assistant_sprite"
                  in registration.MODULES}


def main():
    check("not_registered_in_background", t_not_registered_in_background)
    check("frames_table_loads_real_assets", t_frames_table_loads_real_assets)
    check("sprite_module_in_registration_roster",
          t_sprite_module_in_registration_roster)
    print("BD_TEST_RESULT " + json.dumps(RESULTS, ensure_ascii=False))
    failed = [name for name, result in RESULTS.items()
              if not result.get("ok")]
    print("BD_TEST_DONE " + ("PASS" if not failed else f"FAIL:{','.join(failed)}"))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
