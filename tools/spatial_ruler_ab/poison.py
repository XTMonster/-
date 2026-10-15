"""下毒处方样本（spec §15.4 防作弊红线 2）。"""
from __future__ import annotations

from .fixtures import _poison, composition_scenes, _prescription_for


def poisoned_prescriptions(scene=None):
    """对场景里每个失败分量生成一个含 camera_z 的坏处方。"""
    scene = scene or next(s for s in composition_scenes() if not s["gt"]["passed"])
    out = []
    for comp in scene["gt"]["failed"]:
        p = _prescription_for(scene, comp)
        if p is not None:
            out.append(_poison(p))
    return out
