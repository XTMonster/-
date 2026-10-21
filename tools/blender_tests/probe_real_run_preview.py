"""用修复后的场景构建器重跑已有真实粗排 manifest。"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import bpy
from block_director.layer3_engine.blockout_scene import build_blockout_scene
from block_director.layer8_delivery.blockout_preview import render_blockout_preview

EVIDENCE=ROOT/"docs/evidence/20261021-deepseek-real-run/coarse"
OUT=ROOT/"docs/evidence/20261021-real-run-fixed/coarse"
def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    manifest=json.loads((EVIDENCE/"blockout_manifest.json").read_text(encoding="utf-8"))
    build_blockout_scene(manifest, clear_scene=True)
    report=render_blockout_preview(manifest, OUT, expected=None,
                                   reference_json=json.loads((EVIDENCE/"coarse_world_reference.json").read_text(encoding="utf-8")))
    print(json.dumps({"report":report.get("report"),"out":str(OUT)},ensure_ascii=False))
if __name__=="__main__": main()
