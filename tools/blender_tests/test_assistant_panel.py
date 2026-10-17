"""v1.7 D2：小助手面板（panel_assistant）注册探针。

运行：
  blender --background --factory-startup --python tools/blender_tests/test_assistant_panel.py

--background 下 draw handler 不执行、图标不分配，因此只断言注册表与
MODULES 对拍（与既有 UI 探针同一纪律，不测像素）。
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
from block_director.layer7_ui import panel_assistant  # noqa: E402

RESULTS: dict = {}


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False,
                         "error": f"{type(exc).__name__}: {exc}"}


def t_panel_assistant_registered_in_modules():
    ok = "block_director.layer7_ui.panel_assistant" in registration.MODULES
    return {"ok": ok,
            "modules": list(registration.MODULES)}


def t_register_all_registers_panel():
    registered = registration.register_all()
    ok = "block_director.layer7_ui.panel_assistant" in registered
    return {"ok": ok, "registered": registered}


def t_operator_classes_exist():
    ok = (hasattr(panel_assistant, "BLOCKDIRECTOR_PT_assistant")
          and hasattr(bpy.types.Scene, "bd_assistant_sprite"))
    return {"ok": ok}


def main():
    check("panel_assistant_in_modules", t_panel_assistant_registered_in_modules)
    check("register_all_includes_panel", t_register_all_registers_panel)
    check("operator_classes_exist", t_operator_classes_exist)
    print("BD_TEST_RESULT " + json.dumps(RESULTS, ensure_ascii=False))
    failed = [name for name, result in RESULTS.items()
              if not result.get("ok")]
    print("BD_TEST_DONE " + ("PASS" if not failed else f"FAIL:{','.join(failed)}"))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
