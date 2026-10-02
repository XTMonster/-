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


def test_the_manifest_carries_which_index_generation_produced_it():
    """§4.1b 的 Q5 只在**真实模型运行**上判：证据文件必须自带索引代际。

    没有这一块时，`quality.run_evidence_is_stale()` 无从对拍——那正是
    `docs/evidence/20261002_real/` 那份"旧索引跑出来却拿来 join 新 oracle"的
    形状。反向的一半同样重要：**离线通路**没有运行期 knowledge 块，交付清单里
    就是一个空块，于是离线的 `shots.json` 永远判成 `stale_evidence`——R46 的
    "离线不许判 Q5"因此变成一条可执行的门，而不是一句约定。
    """
    live = {"hypergraph_fingerprint": "a" * 64,
            "cases_index_fingerprint": "b" * 64, "cases_backend": "hybrid"}
    manifest = build_manifest(_plan(), generated_at="t", knowledge=live)
    assert manifest["knowledge"] == live
    # 离线：不传 ⇒ 空块（不是缺字段——读的人不用区分"没写"与"没跑"）。
    offline = build_manifest(_plan(), generated_at="t")
    assert offline["knowledge"] == {}


def test_every_export_call_that_counts_llm_calls_also_counts_retrievals():
    """§3.3 的 `retrieval_calls` 是**契约字段**：生产它的调用点必须真的传值。

    实测缺陷（2026-10-03）：`tools/run_export.py` 与 UI 面板都传了
    `retrieval_calls`，只有 `tools/run_headless.py` 没传——于是**每一次真实
    模型运行**（也就是 §4.4 步骤 2 那条唯一能判 Q5/E2 的通路）写出来的
    `shots.json.retrieval_calls` 恒为 `0`，而同一份文件里
    `knowledge.retrieval_calls` 写着 7。这是"契约字段在说假话"，不是漏一个键：
    RK-18② 要与 `audit_log.jsonl` 的逐条 `retrieval_call` 事件**对拍**，对拍的
    另一半永远是 0 就等于没对拍。

    判据是**结构性**的（AST），所以以后再加一条导出通路也逃不掉：凡是传了
    `llm_calls=` 的 `export_project(...)` 调用点，就必须同时传 `retrieval_calls=`。
    """
    import ast

    offenders = []
    for path in sorted((ROOT / "tools").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", "") != "export_project":
                continue
            keywords = {keyword.arg for keyword in node.keywords}
            if "llm_calls" in keywords and "retrieval_calls" not in keywords:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "这些导出调用点记了 llm_calls 却没记 retrieval_calls——"
        "它们写出的 shots.json 会在 RK-18② 的对拍里说假话：" + "、".join(offenders))


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
