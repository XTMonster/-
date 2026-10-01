"""契约串必须活在**查询词表**里（否则它既做不出种子、也让 Q5 的 join 永不成立）。

实测（2026-10-02，一次真实模型运行 `docs/evidence/market4/`）：

* `shot_constraint_query` 把"这一镜有对白"写成 `对白=有`——而 `scene_type` 的取值是
  `establish/dialogue/action/reaction/transition/insert`，**没有"有"**；
* 镜头维度直接把计划里的数字写进去（`镜头=50.0`），而词表的镜头取值是 `50mm`；
* 运镜维度用的是**引擎名**（`static`／`fixed`），词表里的规范值是 `固定`
  （`static` 是它的别名，`fixed` 连别名都不是）。

三条都是**死值**：`seeds_for` 只在节点名/别名上匹配，死值命不中任何节点、却照样占
`q` 的一位。后果之一是 §4.1b 的 Q5 join（"`SceneContract` 查询串与本条 `q` 的
键值对集合相等"）**零命中**——8 条契约串对 466 个 held-out 键集，一条都对不上。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator import scene_contract as SC  # noqa: E402


class _Shot:
    def __init__(self, **kwargs):
        self.shot_type = kwargs.pop("shot_type", "")
        self.camera = kwargs.pop("camera", None)
        self.actions = kwargs.pop("actions", None)
        self.vfx = kwargs.pop("vfx", None)
        self.dialogues = kwargs.pop("dialogues", None)


def _pairs(text: str):
    out = []
    for part in text.split("；"):
        if "=" in part:
            key, _, value = part.partition("=")
            out.append((key.strip(), value.strip()))
    return out


def test_the_engine_static_camera_maps_to_the_vocabulary_value():
    """`static`／`fixed` 都要折成词表里的 `固定`。"""
    shot = _Shot(shot_type="MS",
                 camera={"lens": 50.0, "movements": [{"type": "static"}]})
    assert dict(_pairs(SC.shot_constraint_query(shot)))["运镜"] == "固定"
    shot_fixed = _Shot(shot_type="MS", camera={"movements": [{"kind": "fixed"}]})
    assert dict(_pairs(SC.shot_constraint_query(shot_fixed)))["运镜"] == "固定"
    # 正对照：词表里的引擎名原样通过（别把 dolly_in 也改了）。
    shot_move = _Shot(shot_type="CU", camera={"movements": [{"type": "dolly_in"}]})
    assert dict(_pairs(SC.shot_constraint_query(shot_move)))["运镜"] == "dolly_in"


def test_a_dialogue_flag_becomes_a_value_the_vocabulary_actually_has():
    """`对白=有` → `对白=dialogue`；"有"不在词表里，是死值。"""
    shot = _Shot(shot_type="MCU", dialogues=[{"id": "dialogue_001"}])
    assert dict(_pairs(SC.shot_constraint_query(shot)))["对白"] == "dialogue"


def test_a_numeric_lens_becomes_the_vocabulary_spelling():
    """`镜头=50.0` → `镜头=50mm`。"""
    shot = _Shot(shot_type="MS", camera={"lens": 50.0, "movements": []})
    assert dict(_pairs(SC.shot_constraint_query(shot)))["镜头"] == "50mm"
    shot_int = _Shot(shot_type="MS", camera={"lens": 85, "movements": []})
    assert dict(_pairs(SC.shot_constraint_query(shot_int)))["镜头"] == "85mm"
    # 非数字（`"50mm"` 这种本来就对的写法）原样通过。
    shot_text = _Shot(shot_type="MS", camera={"lens": "35mm", "movements": []})
    assert dict(_pairs(SC.shot_constraint_query(shot_text)))["镜头"] == "35mm"


def test_every_emitted_value_maps_to_a_node_in_the_shipped_index():
    """**核心不变量**：契约串里每个取值都必须能在入库索引的节点表里找到。

    这条不是"更严的口径"——`seeds_for` 就是这么匹配的：找不到节点 = 这个键位永远
    命不中任何边，属于给检索白送一个稀释项。
    """
    import json

    nodes = pathlib.Path(ROOT / "knowledge" / "hypergraph.nodes.jsonl")
    if not nodes.is_file():
        pytest.skip("索引未入库")
    known = set()
    for line in nodes.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        row = json.loads(line)
        known |= {str(row.get("value") or ""), str(row.get("name") or "")}
        known |= {str(alias) for alias in (row.get("aliases") or ())}
    known.discard("")
    shots = [
        _Shot(shot_type="MS", camera={"lens": 50.0, "movements": [{"type": "static"}]},
              dialogues=[{"id": "d1"}]),
        _Shot(shot_type="CU", camera={"lens": 85, "movements": [{"kind": "fixed"}]}),
        _Shot(shot_type="ELS", camera={"lens": 24, "movements": [{"type": "dolly_in"}]}),
    ]
    for shot in shots:
        for key, value in _pairs(SC.shot_constraint_query(shot)):
            assert value in known, (key, value, "契约串里出现了词表里没有的取值")
