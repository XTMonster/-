"""v1.4 P15 / §3.3：`shots.json` 的交付字段 schema。

D-4 说 `manifest.py` 只写 `shots[]` 的基础字段，三组新字段
（`declared{}` / `labels{}` / `movements[]`）与四组跨镜字段
（`crowd{}` / `timing_overrides[]` / `action_conflicts[]` /
`dialogue_pins[]` / `audit_pass_rate{}`）此前**一个都没有生产者**。

本用例是**契约断言**：字段在不在、形状对不对、`source` 词表是否只用 R46 的
那六个取值、以及"没有声明时必须是 `None` 而不是编造"。
"""

from __future__ import annotations

from pathlib import Path

from block_director.contracts.plan import Plan
from block_director.delivery.manifest import build_manifest
from block_director.layer1_input import parse_script

ROOT = Path(__file__).resolve().parents[1]
LONG = ROOT / "fixtures" / "script_long_61.md"

#: R46 的统一词表（§3.3）：movements[].source 只能取这六个之一。
SOURCE_VOCAB = {"declared", "planned", "theory", "experience", "lesson", "case"}


def _plan() -> Plan:
    return Plan.from_dict({"scene_heading": "INT. 码头 - 日", "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "建立", "shot_type": "LS",
         "duration_frames": 72, "characters": ["char_001"],
         "camera": {"movements": [{"type": "dolly_in", "start_frame": 1,
                                   "end_frame": 72}]},
         "dialogue_pins": [{"shot_number": 1, "speaker_raw": "米迦尔",
                            "speaker_status": "resolved", "declared_s": 3.0,
                            "model_text": "", "applied_s": 3.0}]}]})


def test_top_level_schema_is_present():
    manifest = build_manifest(_plan(), generated_at="t", llm_calls=5,
                              retrieval_calls=2, crowd=[{"count": 30}])
    for key in ("declared", "labels", "movements", "crowd",
                "timing_overrides", "action_conflicts", "dialogue_pins",
                "audit_pass_rate", "llm_calls", "retrieval_calls"):
        if key in ("declared", "labels", "movements"):
            assert key in manifest["shots"][0], key
        else:
            assert key in manifest, key
    assert manifest["crowd"]["total"] == 30
    assert manifest["llm_calls"] == 5 and manifest["retrieval_calls"] == 2
    assert manifest["dialogue_pins"][0]["speaker_raw"] == "米迦尔"
    assert manifest["audit_pass_rate"]["exempt_shots"] == []


def test_declared_is_null_when_there_is_no_declaration():
    manifest = build_manifest(_plan(), generated_at="t")
    declared = manifest["shots"][0]["declared"]
    assert set(declared) == {"shot_number", "camera_number", "technique",
                             "transition", "location", "time", "lighting",
                             "sfx", "declared_duration_s"}
    assert all(value is None for value in declared.values())


def test_declared_reads_the_shot_list_when_available():
    script = parse_script(LONG)
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "i", "shot_type": "LS",
         "duration_frames": 72, "characters": ["char_001"]}]})
    manifest = build_manifest(plan, parsed=script, generated_at="t")
    declared = manifest["shots"][0]["declared"]
    assert declared["shot_number"] == 1
    assert declared["declared_duration_s"] == 3.0
    assert declared["location"] == "第十四街区码头市场"


def test_movements_use_the_unified_source_vocabulary():
    manifest = build_manifest(_plan(), generated_at="t")
    movements = manifest["shots"][0]["movements"]
    assert movements and all(item["source"] in SOURCE_VOCAB
                             for item in movements)
    assert movements[0]["kind"] == "dolly_in"


def test_declared_movement_is_labelled_declared():
    """剧本声明了运镜、计划照做 → ``source = "declared"``（R46 词表）。"""
    from block_director.layer1_input.model import (ParsedScript,
                                                   ParsedShotDeclaration)

    class _Parsed:
        declared_shots = [ParsedShotDeclaration(shot_number=9,
                                                camera_move="dolly_in")]

    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "i", "shot_type": "MS",
         "duration_frames": 72, "characters": ["char_001"],
         "camera": {"movements": [{"type": "dolly_in", "start_frame": 1,
                                   "end_frame": 72}]}}]})
    manifest = build_manifest(plan, parsed=_Parsed(), generated_at="t")
    assert manifest["shots"][0]["movements"][0]["source"] == "declared"

    # 负例：计划把声明改成了别的运镜 → 只能标 planned。
    other = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "i", "shot_type": "MS",
         "duration_frames": 72, "characters": ["char_001"],
         "camera": {"movements": [{"type": "orbit_cw", "start_frame": 1,
                                   "end_frame": 72}]}}]})
    manifest = build_manifest(other, parsed=_Parsed(), generated_at="t")
    assert manifest["shots"][0]["movements"][0]["source"] == "planned"
    assert _Parsed.declared_shots[0].shot_number == 9
    assert ParsedScript is not None


def test_action_conflicts_and_timing_overrides_pass_through():
    manifest = build_manifest(
        _plan(), generated_at="t",
        action_conflicts=[{"shot_id": "shot_001", "character_id": "char_001",
                           "layer": "base", "pair": ["walk_to", "turn_body"],
                           "overlap_frames": 4, "applied_shift": 10}],
        timing_overrides=[{"shot_number": 1, "declared_s": 3.0,
                           "engine_s": None, "applied_s": 4.0,
                           "reason": "r"}])
    assert manifest["action_conflicts"][0]["overlap_frames"] == 4
    assert manifest["timing_overrides"][0]["applied_s"] == 4.0
