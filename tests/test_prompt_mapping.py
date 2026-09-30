"""两条 prompt 都必须教"构图知识怎么落进六类边"——否则整域卡片会一条都产不出来。

实测教训（2026-09-30）：

* 抽取侧不教映射时，索引里 **0 条边**带 `composition_rule`；`composition` 域的
  170 张卡在标注侧也**一条都产不出**——模型的 `must` 里写 `COMPOSITION`／
  `COMPOSITION_RULE`，被 `bad_type` 整条拒收（最近 200 条 reject 里 188 条是这个）。
* 教了映射之后：抽取侧重跑得到 **97 个 `composition_rule` 成员**、
  标注侧 6 张构图卡一次调用 6 条全过。

这两条 prompt 是"知识能不能进索引/进 held-out"的开关，所以用测试钉住，
免得以后有人精简提示词时把这段删掉。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kb_fetch import build_hypergraph as bh  # noqa: E402
from tools.kb_fetch import holdout_gen  # noqa: E402
from tools import holdout_fill  # noqa: E402

SIX_TYPES = ("EMOTION_PACK", "SHOT_PATTERN", "AXIS_RULE", "TROPE", "EDIT_RHYTHM",
             "LIGHT_PACK")


def test_extractor_prompt_names_all_six_types_and_the_composition_mapping():
    text = bh.SYSTEM_PROMPT
    for edge_type in SIX_TYPES:
        assert edge_type in text, f"抽取 prompt 少了边类型 {edge_type}"
    assert "composition_rule" in text, "构图知识点映射没写进抽取 prompt"
    assert "camera_angle" in text and "vfx" in text and "sfx" in text
    assert "forbid" in text


def test_annotator_prompt_names_all_six_types_and_the_composition_mapping():
    text = holdout_gen.SYSTEM_PROMPT
    for edge_type in SIX_TYPES:
        assert edge_type in text, f"标注 prompt 少了边类型 {edge_type}"
    assert "composition_rule" in text
    # 只允许这六个 type，且明确点名"不要发明 COMPOSITION 之类"
    assert "COMPOSITION" in text and "整条作废" in text


def test_gap_prompt_carries_the_same_mapping_rule():
    assert "composition_rule" in holdout_fill.GAP_PROMPT
    for edge_type in SIX_TYPES:
        assert edge_type in holdout_fill.GAP_PROMPT


def test_prompt_versions_are_non_empty_and_bumped():
    assert bh.PROMPT_VERSION.startswith("extract/")
    assert holdout_gen.PROMPT_VERSION.startswith("holdout/")
    assert holdout_fill.GAP_PROMPT_VERSION.startswith("holdout-gap/")
