"""v1.6 D3（FR-B2 / FR-B5）：节奏读数 + 交付可见。

钉住三件事：

* 读数函数是**纯函数**，返回键与 ``contracts/audit.py::V16_EVENT_FIELDS`` 的
  ``rhythm_reading`` 逐键一致（asl_s / duration_cv / monotony / jump_cut_risks）；
* 读数**只诊断**：单调性最多产出一条 info 级 ``pace_monotony`` 提示，永远不是
  pass/fail 门、永远不触发修复（红线 R-5）；跳切风险**只计数**，逐镜头对几何
  告警归 FR-C6 的 ``cut_level_checks``；
* 交付可见（FR-B5）：``shots.json`` 每镜 ``rhythm{tension, pace, curve}`` 与
  README 的节奏段（ASL / ASCII 弧线 / 每镜时长表）字段对拍一致，且确定性输出。
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.frustum_metrics import (  # noqa: E402
    GuardConfig,
    ShotSummary,
    cut_level_checks,
)
from block_director.contracts.audit import (  # noqa: E402
    V16_EVENT_FIELDS,
    AuditError,
    AuditResult,
)
from block_director.contracts.config import AppConfig  # noqa: E402
from block_director.contracts.enums import Severity as AuditSeverity  # noqa: E402
from block_director.contracts.guard import Confidence, Severity  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.delivery.manifest import build_manifest  # noqa: E402
from block_director.delivery.readme import (  # noqa: E402
    MISSING_TENSION_GLYPH,
    render_readme,
    rhythm_arc_line,
    tension_glyph,
)
from block_director.layer5_orchestrator.planner import (  # noqa: E402
    DEFAULT_PACING_PROFILE,
    build_plan_payload,
    pacing_block,
)
from block_director.layer5_orchestrator.rhythm_reading import (  # noqa: E402
    pace_monotony_note,
    rhythm_readings,
)


# --------------------------------------------------------------------------- #
# 1. ASL / 镜长方差（CV） / 单调性的合成读数
# --------------------------------------------------------------------------- #
def test_asl_cv_and_monotony_numbers_on_synthetic_durations():
    uniform = rhythm_readings([2.0, 2.0, 2.0])
    assert uniform["asl_s"] == pytest.approx(2.0)
    assert uniform["duration_cv"] == pytest.approx(0.0, abs=1e-12)
    assert uniform["monotony"] is True
    assert uniform["jump_cut_risks"] == 0

    varied = rhythm_readings([1.0, 2.0, 3.0])
    assert varied["asl_s"] == pytest.approx(2.0)
    # 总体标准差 sqrt(2/3)，CV = 标准差 / 均值
    assert varied["duration_cv"] == pytest.approx(
        math.sqrt(2.0 / 3.0) / 2.0)
    assert varied["monotony"] is False


def test_monotony_is_population_stdev_below_1e_6_strict():
    # 两镜只差 5e-7 ⇒ 标准差 2.5e-7 < 1e-6 ⇒ 单调
    assert rhythm_readings([2.0, 2.0 + 5e-7])["monotony"] is True
    # 两镜差 3e-6 ⇒ 标准差 ≈1.5e-6 ≥ 1e-6 ⇒ 不单调（阈值是严格小于；
    # 刻意避开 2e-6 的浮点表示误差带，那个值会被舍入到阈值之下）
    assert rhythm_readings([2.0, 2.0 + 3e-6])["monotony"] is False
    # 单镜的标准差是 0 ⇒ 单调；空输入没有数据 ⇒ 不宣称单调
    assert rhythm_readings([5.0])["monotony"] is True
    assert rhythm_readings([]) == {
        "asl_s": 0.0, "duration_cv": 0.0,
        "monotony": False, "jump_cut_risks": 0,
    }


def test_readings_are_exactly_the_registered_event_fields():
    """读数直接可作 `rhythm_reading` 事件体（V16_EVENT_FIELDS 的四个键）。"""
    readings = rhythm_readings([1.0, 2.0, 4.0])
    assert set(readings) == set(V16_EVENT_FIELDS["rhythm_reading"])
    assert json.dumps(readings, sort_keys=True)   # 必须可 JSON 序列化


# --------------------------------------------------------------------------- #
# 2. 跳切风险只计数（判定复用 FR-C6 的 cut_level_checks，不重写阈值）
# --------------------------------------------------------------------------- #
def test_jump_cut_risks_are_counted_with_the_fr_c6_thresholds():
    shots = [ShotSummary("s1", 0.50, 10.0, 96),
             ShotSummary("s2", 0.52, 20.0, 96)]
    # 占比差 0.04 < 0.10 且视角差 10° < 30° ⇒ 一跳
    assert rhythm_readings([4.0, 4.0],
                           shot_summaries=shots)["jump_cut_risks"] == 1
    # 逐镜头对告警仍在 FR-C6 那里；读数里只有计数，不重复告警
    assert any(item.type == "jump_cut_risk"
               for item in cut_level_checks(shots, GuardConfig()))
    readings = rhythm_readings([4.0, 4.0], shot_summaries=shots)
    # 读数里只有 int 计数，没有告警对象/告警列表（逐镜头对告警不在这里重复）
    assert readings["jump_cut_risks"] == 1
    assert "warnings" not in readings
    assert not any(isinstance(value, (list, dict))
                   for value in readings.values())


def test_no_summaries_means_zero_risks_not_a_warning():
    readings = rhythm_readings([3.0, 4.0])
    assert readings["jump_cut_risks"] == 0


def test_custom_guard_thresholds_are_honoured_when_counting():
    tight = GuardConfig(jump_cut_size_diff=0.01, jump_cut_angle_deg=30.0)
    shots = [ShotSummary("s1", 0.50, 10.0), ShotSummary("s2", 0.52, 20.0)]
    # 占比差 0.04 超过了自定义阈值 0.01 ⇒ 不计
    assert rhythm_readings(
        [3.0, 3.0], shot_summaries=shots, guard_config=tight
    )["jump_cut_risks"] == 0
    assert rhythm_readings(
        [3.0, 3.0], shot_summaries=shots
    )["jump_cut_risks"] == 1      # 默认阈值下仍算一跳


# --------------------------------------------------------------------------- #
# 3. info 级提示永远不触发修复
# --------------------------------------------------------------------------- #
def test_pace_monotony_note_is_info_and_never_a_repair_trigger():
    note = pace_monotony_note(rhythm_readings([4.0, 4.0, 4.0]))
    assert note is not None
    assert note.type == "pace_monotony"
    assert note.severity is Severity.INFO
    assert note.confidence is Confidence.HIGH
    assert note.shot_id == "scene" and note.subject == "scene"
    # 它是 GuardWarning、不是 AuditError：进不了 AuditResult.errors
    assert not isinstance(note, AuditError)
    assert note.problems() == ""

    # 非单调（节奏有起伏）⇒ 没有任何提示，更谈不上告警
    assert pace_monotony_note(rhythm_readings([1.0, 2.0, 3.0])) is None


def test_info_level_findings_never_flip_the_audit_gate():
    """修复由 ``AuditResult.errors``（severity=ERROR）触发；info/warning 只进
    ``warnings``，``passed`` 保持 True。这里的结论是结构性的：读数的唯一产物
    是 info，它连 warning 都到不了，a fortiori 不触发修复。"""
    result = AuditResult.from_findings([
        AuditError(rule="R", message="信息级提示",
                   severity=AuditSeverity.WARNING)])
    assert result.passed is True
    assert result.errors == [] and result.warnings != []
    # 读数本身不带任何 pass/fail / severity 键——形状上就成不了判红
    readings = rhythm_readings([2.0, 4.0, 6.0])
    assert not any(key in readings
                   for key in ("passed", "failed", "severity", "errors"))


# --------------------------------------------------------------------------- #
# 4. shots.json 每镜 rhythm{}：tension 来自节奏弧，pace/curve 来自拍点表
# --------------------------------------------------------------------------- #
def _shot(duration_frames=96, beats=None, **extra) -> dict:
    item = {"shot_id": "shot_001", "order": 1, "intent": "开场",
            "shot_type": "MS", "duration_frames": duration_frames}
    if beats is not None:
        item["beats"] = beats
    item.update(extra)
    return item


def test_shots_json_rhythm_comes_from_arc_and_beats_only():
    plan = Plan.from_dict({"shots": [
        _shot(96, beats=[
            {"t": 0.0, "subject": "char_001", "verb": "stand",
             "pace": "slow", "curve": "ease_in"},
            {"t": 0.5, "subject": "char_001", "verb": "look",
             "pace": "slow", "curve": "ease_in"},
        ]),
        _shot(120, beats=[
            {"t": 0.0, "subject": "char_002", "verb": "nod",
             "pace": "brisk"},
        ], shot_id="shot_002", order=2),
        _shot(72, shot_id="shot_003", order=3),
    ]})
    arc = [{"shot_id": "shot_001", "tension": 4, "note": "顶点"},
           {"shot_id": "shot_002", "tension": 2}]
    shots = build_manifest(plan, rhythm_arc=arc, generated_at="t")["shots"]
    assert shots[0]["rhythm"] == {"tension": 4, "pace": "slow",
                                  "curve": "ease_in"}
    # 拍点没写 curve ⇒ curve 键缺席（不猜缺省 smooth）
    assert shots[1]["rhythm"] == {"tension": 2, "pace": "brisk"}
    # 没有弧条目、没有拍点 ⇒ 整块为空
    assert shots[2]["rhythm"] == {}


def test_mixed_or_absent_beat_data_stays_absent():
    plan = Plan.from_dict({"shots": [
        _shot(96, beats=[
            {"t": 0.0, "subject": "a", "verb": "stand", "pace": "slow"},
            {"t": 0.5, "subject": "a", "verb": "look", "pace": "brisk"},
        ])]})
    assert build_manifest(plan, generated_at="t")["shots"][0]["rhythm"] == {}
    # 一个拍点没写 pace ⇒ 全镜 pace 无唯一解 ⇒ 缺席
    plan = Plan.from_dict({"shots": [
        _shot(96, beats=[
            {"t": 0.0, "subject": "a", "verb": "stand", "pace": "slow"},
            {"t": 0.5, "subject": "a", "verb": "look"},
        ])]})
    assert build_manifest(plan, generated_at="t")["shots"][0]["rhythm"] == {}


def test_non_integer_or_bool_tension_is_not_guessed():
    plan = Plan.from_dict({"shots": [_shot(96)]})
    manifest = build_manifest(plan, rhythm_arc=[
        {"shot_id": "shot_001", "tension": "3"},   # 字符串 ⇒ 缺席
    ], generated_at="t")
    assert manifest["shots"][0]["rhythm"] == {}
    manifest = build_manifest(plan, rhythm_arc=[
        {"shot_id": "shot_001", "tension": True},  # bool 是 int 的子类 ⇒ 缺席
    ], generated_at="t")
    assert manifest["shots"][0]["rhythm"] == {}
    manifest = build_manifest(plan, rhythm_arc=[
        {"shot_id": "shot_001", "tension": "3"},
        {"shot_id": "shot_001", "tension": 5},
    ], generated_at="t")
    assert manifest["shots"][0]["rhythm"] == {"tension": 5}


# --------------------------------------------------------------------------- #
# 5. README 节奏段与 shots.json 字段对拍 + 确定性
# --------------------------------------------------------------------------- #
def _manifest() -> dict:
    plan = Plan.from_dict({"shots": [
        _shot(96, beats=[
            {"t": 0.0, "subject": "char_001", "verb": "stand",
             "pace": "slow", "curve": "ease_in"},
        ]),
        _shot(192, shot_id="shot_002", order=2),
        _shot(72, beats=[
            {"t": 0.0, "subject": "char_002", "verb": "stand",
             "pace": "brisk", "curve": "sharp"},
        ], shot_id="shot_003", order=3),
    ]})
    arc = [{"shot_id": "shot_001", "tension": 3},
           {"shot_id": "shot_003", "tension": 5}]
    return build_manifest(plan, rhythm_arc=arc, generated_at="t")


def test_readme_rhythm_section_matches_shots_json_field_by_field(tmp_path):
    manifest = _manifest()
    readings = rhythm_readings(
        [shot["duration_seconds"] for shot in manifest["shots"]])
    text = render_readme(manifest, out_dir=tmp_path, rhythm_reading=readings)
    assert "## 节奏" in text
    # ASL / CV 与 rhythm_reading 事件读数逐字一致
    assert f"- 平均镜长（ASL）：{readings['asl_s']:.2f} 秒" in text
    assert f"- 镜长变异系数（CV）：{readings['duration_cv']:.4f}" in text
    # 弧线：tension 3 → "="、无数据 → "_"、tension 5 → "@"
    assert rhythm_arc_line(manifest["shots"]) == "=_@"
    assert tension_glyph(3) == "=" and tension_glyph(None) == MISSING_TENSION_GLYPH
    assert f"`=_@`" in text
    # 每镜时长表与 shots.json 逐行对拍（时长 + 张力两列）
    for shot in manifest["shots"]:
        row = next(line for line in text.splitlines()
                   if line.startswith(f"| {shot['shot_id']} |"))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert float(cells[1]) == shot["duration_seconds"], row
        tension = (shot["rhythm"] or {}).get("tension")
        assert cells[2] == (str(tension) if tension is not None else "—"), row


def test_monotony_renders_an_info_note_in_readme(tmp_path):
    plan = Plan.from_dict({"shots": [
        _shot(96, shot_id="shot_001"),
        _shot(96, shot_id="shot_002", order=2),
    ]})
    manifest = build_manifest(plan, generated_at="t")
    readings = rhythm_readings(
        [shot["duration_seconds"] for shot in manifest["shots"]])
    assert readings["monotony"] is True
    text = render_readme(manifest, out_dir=tmp_path, rhythm_reading=readings)
    assert "单调性" in text and "info" in text
    # 节奏有起伏 ⇒ README 不出现单调性那一行
    plan.shots[1].duration_frames = 120
    manifest = build_manifest(plan, generated_at="t")
    readings = rhythm_readings(
        [shot["duration_seconds"] for shot in manifest["shots"]])
    text = render_readme(manifest, out_dir=tmp_path, rhythm_reading=readings)
    assert "单调性" not in text


def test_rhythm_outputs_are_deterministic(tmp_path):
    assert json.dumps(_manifest(), ensure_ascii=False, sort_keys=True) == \
        json.dumps(_manifest(), ensure_ascii=False, sort_keys=True)
    assert render_readme(_manifest(), out_dir=tmp_path) == \
        render_readme(_manifest(), out_dir=tmp_path)


def test_readme_falls_back_to_the_same_readings_when_none_passed(tmp_path):
    """调用方没传读数时，README 用同一个纯函数重算——与事件读数同源同值。"""
    manifest = _manifest()
    expected = rhythm_readings(
        [shot["duration_seconds"] for shot in manifest["shots"]])
    text = render_readme(manifest, out_dir=tmp_path)
    assert f"：{expected['asl_s']:.2f} 秒" in text
    assert f"：{expected['duration_cv']:.4f}" in text


# --------------------------------------------------------------------------- #
# 6. 计划提示注入节奏档案（FR-B2 的上游）
# --------------------------------------------------------------------------- #
def test_pacing_block_renders_the_selected_profile_and_band():
    block = pacing_block("urgent")
    assert "本片档位：urgent" in block
    assert "2–4 秒" in block
    assert "不是硬门" in block
    assert "节奏是创作选择" in block


def test_pacing_block_lists_the_closed_set_from_contracts():
    block = pacing_block("standard")
    for name in ("contemplative", "standard", "urgent"):
        assert name in block
    assert "4–8 秒" in block


def test_pacing_block_rejects_unknown_profiles_instead_of_guessing():
    with pytest.raises(ValueError):
        pacing_block("extreme")


def test_the_plan_prompt_injects_the_configured_profile():
    config = AppConfig()
    config.rhythm.pacing_profile = "contemplative"
    system = build_plan_payload("INT. 房间 - 日", config).messages[0].content
    assert "{pacing}" not in system
    assert "本片档位：contemplative" in system
    assert "8–12 秒" in system


def test_without_a_config_the_default_profile_still_appears():
    system = build_plan_payload(
        "INT. 房间 - 日", None).messages[0].content
    assert "{pacing}" not in system
    assert f"本片档位：{DEFAULT_PACING_PROFILE}" in system
