"""夹具剧本必须能被 Layer 1 解析（执行文档 v1.2 §20 夹具）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from block_director.layer1_input import parse_script
from block_director.layer1_input.dialogue_timing import schedule_dialogues

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = sorted((ROOT / "fixtures").glob("*.fountain"))


def test_fixtures_exist():
    names = {path.name for path in FIXTURES}
    assert {"coffee.fountain", "ensemble.fountain",
            "dialogue_heavy.fountain"} <= names


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name)
def test_every_fixture_parses(path):
    script = parse_script(path)
    assert script.scenes, f"{path.name} 应当至少解析出一场"
    assert script.title, "标题应当来自 Title: 行或文件名"
    assert script.needs_llm_structure is False, "夹具都带场景标题"
    assert script.character_names, "应当识别出角色"
    for scene in script.scenes:
        assert scene.heading
        for dialogue in scene.dialogues:
            assert dialogue.character and dialogue.text


def test_ensemble_fixture_finds_four_characters():
    script = parse_script(ROOT / "fixtures" / "ensemble.fountain")
    assert len(script.character_names) == 4
    assert script.dialogue_count == 7


def test_dialogue_heavy_fixture_schedules_within_reasonable_time():
    script = parse_script(ROOT / "fixtures" / "dialogue_heavy.fountain")
    scene = script.scenes[0]
    spans = schedule_dialogues(scene.dialogues, start_frame=1)
    assert len(spans) == len(scene.dialogues)
    total = spans[-1][1]
    # 5 句对白，实拍也不过十几秒；这里给一个宽松上界，防止语速算错量级
    assert 100 < total < 600
