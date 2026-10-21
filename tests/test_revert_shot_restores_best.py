"""缺陷 B / R8（T6）：revert_shot 恢复最高分版本（纯层恢复语义）。

``contracts.backtrack.revert_ops`` 把最高分世界状态快照转成有序恢复指令：
对抗——先构造最高分快照，再改坏角色/相机/道具，按指令恢复后 live 状态与
最高分快照逐字段一致（相机位置/目标/焦距、角色位置/朝向、道具位置）。
"""

from __future__ import annotations

from block_director.contracts.backtrack import revert_ops


def _best_payload():
    return {
        "schema_version": "runtime-world/v1",
        "characters": {
            "char_001": {"position": [1.0, 2.0, 0.0], "facing": [0.0, 1.0, 0.0]},
            "char_002": {"position": [-1.0, 2.0, 0.0], "facing": [0.0, -1.0, 0.0]},
        },
        "cameras": {
            "shot_001": {"position": [0.0, -2.0, 1.5],
                         "target": [1.0, 2.0, 1.0], "lens_mm": 85.0},
        },
        "props": {
            "coin": {"position": [1.0, 2.4, 1.0], "rotation_z": 0.3},
        },
    }


def _apply_ops(ops, live):
    for op in ops:
        kind = op["kind"]
        ident = op["id"]
        if kind == "character":
            live["characters"][ident] = {"position": list(op["position"]),
                                         "facing": list(op["facing"])}
        elif kind == "camera":
            live["cameras"][ident] = {"position": list(op["position"]),
                                      "target": list(op["target"]),
                                      "lens_mm": float(op["lens_mm"])}
        elif kind == "prop":
            live["props"][ident] = {"position": list(op["position"]),
                                    "rotation_z": float(op["rotation_z"])}


def _mutated_live():
    """把 live 状态改坏：角色挪走、相机换位/焦距、道具出画。"""
    live = _best_payload()
    live["characters"]["char_001"]["position"] = [9.0, 9.0, 9.0]
    live["cameras"]["shot_001"]["position"] = [5.0, 5.0, 5.0]
    live["cameras"]["shot_001"]["lens_mm"] = 12.0
    live["props"]["coin"]["position"] = [10.0, 10.0, 10.0]
    return live


def test_revert_ops_restore_best_characters_camera_and_prop():
    best = _best_payload()
    live = _mutated_live()
    _apply_ops(revert_ops(best), live)
    assert live == best


def test_revert_ops_stable_order_and_explicit_fields():
    ops = revert_ops(_best_payload())
    assert ops[0]["kind"] == "character"
    assert {op["kind"] for op in ops} == {"character", "camera", "prop"}
    for op in ops:
        if op["kind"] == "camera":
            assert set(op) >= {"kind", "id", "position", "target", "lens_mm"}
        elif op["kind"] == "character":
            assert set(op) >= {"kind", "id", "position", "facing"}
        else:
            assert set(op) >= {"kind", "id", "position", "rotation_z"}


def test_revert_ops_rejects_non_world_state_payload():
    try:
        from block_director.contracts.backtrack import revert_ops
        import pytest
        with pytest.raises(ValueError):
            revert_ops({"characters": "not-a-dict"})
    except ImportError:
        pass
