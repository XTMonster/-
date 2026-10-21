"""F10：镜头隔离（跨镜角色/持有道具不参与本镜遮挡判定）纯层测试。

钉死：粗排逐镜 staging 验证时，本镜外的角色/持有道具应被隔离（临时
隐藏），场景级道具（无 owner、进 scene_prop_ids 的环境体块）与锚点是
环境连续性、永不隔离；本镜声明的角色/道具永不隔离；同一输入两次调用
逐位一致；空清单不崩溃。
"""

from __future__ import annotations

import ast
from pathlib import Path

from block_director.cinema.blockout_sequence import (
    blockout_isolation_primitive_ids,
    blockout_occluder_candidate_names,
)

ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    """手工构造的 manifest（独立真源：期望值手算，不与实现同源）。"""
    return {
        "schema_version": "blockout-manifest/v1",
        "primitives": [
            {"id": "char_米迦尔", "kind": "character",
             "source": {"type": "character", "id": "米迦尔"}},
            {"id": "char_伊恩", "kind": "character",
             "source": {"type": "character", "id": "伊恩"}},
            {"id": "prop_银币", "kind": "prop",
             "source": {"type": "prop", "id": "银币"}},
            {"id": "prop_生蚝摊", "kind": "prop",
             "source": {"type": "prop", "id": "生蚝摊"}},
            {"id": "anchor_入口", "kind": "anchor",
             "source": {"type": "anchor", "id": "入口"}},
        ],
        "shot_table": [
            {"shot_id": "shot_001", "character_ids": ["米迦尔"], "prop_ids": []},
            {"shot_id": "shot_002", "character_ids": ["伊恩"],
             "prop_ids": ["银币"]},
        ],
    }


def test_hides_other_shot_character():
    row = {"shot_id": "shot_001", "character_ids": ["米迦尔"], "prop_ids": []}
    result = blockout_isolation_primitive_ids(_manifest(), row)
    assert "char_伊恩" in result
    assert "char_米迦尔" not in result


def test_hides_other_shot_owned_prop():
    #: 银币属 shot_002（持有道具），shot_001 不声明 -> 隔离；生蚝摊是场景级
    #: 道具（不进任何 prop_ids）-> 保留。
    row = {"shot_id": "shot_001", "character_ids": ["米迦尔"], "prop_ids": []}
    result = blockout_isolation_primitive_ids(_manifest(), row)
    assert "prop_银币" in result
    assert "prop_生蚝摊" not in result


def test_anchor_never_isolated():
    row = {"shot_id": "shot_001", "character_ids": ["米迦尔"], "prop_ids": []}
    result = blockout_isolation_primitive_ids(_manifest(), row)
    assert "anchor_入口" not in result


def test_own_shot_objects_not_isolated():
    row = {"shot_id": "shot_002", "character_ids": ["伊恩"],
           "prop_ids": ["银币"]}
    result = blockout_isolation_primitive_ids(_manifest(), row)
    assert "char_伊恩" not in result
    assert "prop_银币" not in result
    assert "char_米迦尔" in result


def test_scene_prop_never_isolated_even_when_not_in_any_shot():
    manifest = _manifest()
    manifest["primitives"].append(
        {"id": "prop_围栏", "kind": "prop",
         "source": {"type": "prop", "id": "围栏"}})
    row = {"shot_id": "shot_001", "character_ids": ["米迦尔"], "prop_ids": []}
    result = blockout_isolation_primitive_ids(manifest, row)
    assert "prop_围栏" not in result
    assert "prop_生蚝摊" not in result


def test_empty_manifest_no_crash():
    assert blockout_isolation_primitive_ids({}, {}) == []


def test_missing_rows_never_crash():
    row = {"shot_id": "shot_001"}
    assert blockout_isolation_primitive_ids(_manifest(), row) == [
        "char_米迦尔", "char_伊恩", "prop_银币"]


def test_deterministic_two_calls():
    row = {"shot_id": "shot_001", "character_ids": ["米迦尔"], "prop_ids": []}
    first = blockout_isolation_primitive_ids(_manifest(), row)
    second = blockout_isolation_primitive_ids(_manifest(), row)
    assert first == second


def test_module_is_pure_no_bpy():
    source = ROOT / "block_director" / "cinema" / "blockout_sequence.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any("bpy" in (alias.name or "") for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert "bpy" not in (node.module or "")


# --------------------------------------------------------------------------- #
# 前景遮挡候选（F11：同镜剧情道具不是"非主体前景遮挡体"）
# --------------------------------------------------------------------------- #
def _subjects() -> list:
    return ["BD_Blockout_char_偷盗者",
            "BD_Blockout_char_米迦尔",
            "BD_Blockout_prop_银币"]


def test_occluder_candidates_exclude_self():
    result = blockout_occluder_candidate_names(
        ["BD_Blockout_char_偷盗者"], "BD_Blockout_char_偷盗者")
    assert result == set()


def test_occluder_candidates_keep_other_characters():
    result = blockout_occluder_candidate_names(_subjects(),
                                               "BD_Blockout_char_偷盗者")
    assert "BD_Blockout_char_米迦尔" in result
    assert "BD_Blockout_char_偷盗者" not in result


def test_occluder_candidates_exclude_prop_blocks():
    #: 同镜剧情道具（银币）与主体偷盗者同属一个语义单元：检测偷盗者时
    #: 银币不再进入遮挡候选（final16 死循环根因：银币与偷盗者互相被记
    #: 成 occluder，strafe 处方 50 轮越绕越远）。
    result = blockout_occluder_candidate_names(
        ["BD_Blockout_char_偷盗者", "BD_Blockout_prop_银币"],
        "BD_Blockout_char_偷盗者")
    assert result == set()
    assert "BD_Blockout_prop_银币" not in result


def test_occluder_candidates_exclude_prop_even_when_self_is_prop():
    #: 主体就是道具（道具特写镜）：所有道具都不进遮挡候选，角色互挡保留。
    result = blockout_occluder_candidate_names(_subjects(),
                                               "BD_Blockout_prop_银币")
    assert "BD_Blockout_prop_银币" not in result
    assert "BD_Blockout_char_米迦尔" in result


def test_occluder_candidates_deterministic_and_order_free():
    first = blockout_occluder_candidate_names(_subjects(),
                                              "BD_Blockout_char_偷盗者")
    second = blockout_occluder_candidate_names(
        list(reversed(_subjects())), "BD_Blockout_char_偷盗者")
    assert first == second
