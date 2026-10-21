"""诊断真实粗排证据的相机/主体几何（不修改项目）。"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
from block_director.layer3_engine.blockout_scene import build_blockout_scene

EVIDENCE = ROOT / "docs/evidence/20261021-deepseek-real-run/coarse"

def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    manifest = json.loads((EVIDENCE / "blockout_manifest.json").read_text(encoding="utf-8"))
    build_blockout_scene(manifest, clear_scene=True)
    scene = bpy.context.scene
    for cam in manifest.get("cameras", []):
        sid = str(cam["shot_id"])
        obj = bpy.data.objects.get("BD_Blockout_" + str(cam["camera_id"]))
        scene.camera = obj
        rows=[]
        row=next(x for x in manifest["shot_table"] if x["shot_id"]==sid)
        names=list(row.get("character_ids") or [])
        for frame in (int(cam["start_frame"]), (int(cam["start_frame"])+int(cam["end_frame"]))//2, int(cam["end_frame"])):
            scene.frame_set(frame); bpy.context.view_layer.update()
            target=bpy.data.objects.get("BD_Blockout_CamTarget_"+sid)
            vals={"frame":frame,"cam":list(obj.matrix_world.translation),"target":list(target.matrix_world.translation) if target else None}
            vals["subjects"]={}
            for name in names:
                block=bpy.data.objects.get("BD_Blockout_char_"+name)
                if block is None: continue
                pts=[]
                for corner in block.bound_box:
                    p=world_to_camera_view(scene,obj,block.matrix_world @ Vector(corner))
                    pts.append([round(float(p.x),4),round(float(p.y),4),round(float(p.z),4)])
                vals["subjects"][name]=pts
            rows.append(vals)
        print(json.dumps({"shot":sid,"rows":rows},ensure_ascii=False))

if __name__ == "__main__": main()
