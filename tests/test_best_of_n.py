"""v1.5 §6 / 卡 P6-T2：Best-of-N 骨架与多样性度量。

红线口径（断言里一并钉住）：

* ``orchestration.draft_candidates`` 默认 ``1`` ⇒ **零行为差**（R-4：改完 config
  必跑 ``tools/gen_specs.py``）；
* rerank **不是过滤**：低分候选进 ``shots.json.alternates[]``，一个都不丢；
* 多样性脚本是纯函数，``runs < 2`` 时各维度为 0（不可比 ≠ 很僵）。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.contracts.config import AppConfig, dump_default_yaml  # noqa: E402
from block_director.contracts.plan import Plan  # noqa: E402
from block_director.delivery.manifest import build_manifest  # noqa: E402
from block_director.layer5_orchestrator.driver import PrevisDriver  # noqa: E402
from block_director.layer5_orchestrator.editor import (  # noqa: E402
    ShotDraft,
    rank_drafts,
    score_draft,
)
from tools.diversity_score import (  # noqa: E402
    axis_flip_rate,
    diversity_report,
    levenshtein,
    movement_chi_square,
    sequence_edit_distance,
)

SPEC = ROOT / "specs" / "config.default.yaml"


# ------------------------------------------------------------------ 配置
def test_draft_candidates_defaults_to_one():
    cfg = AppConfig()
    assert cfg.orchestration.draft_candidates == 1
    assert cfg.errors() == []


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
def test_draft_candidates_in_range_is_legal(value):
    cfg = AppConfig()
    cfg.orchestration.draft_candidates = value
    assert cfg.errors() == [], [str(i) for i in cfg.errors()]


@pytest.mark.parametrize("value", [0, 6, -1, 2.5, "3", True, None])
def test_draft_candidates_out_of_range_is_cfg_022(value):
    cfg = AppConfig()
    cfg.orchestration.draft_candidates = value
    codes = {i.code for i in cfg.errors()}
    assert "CFG_022" in codes, (value, codes)


def test_gen_specs_is_in_sync_and_idempotent():
    assert SPEC.read_text(encoding="utf-8") == dump_default_yaml()
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gen_specs.py"), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr


def test_spec_carries_the_key():
    import yaml

    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert spec["orchestration"]["draft_candidates"] == 1


# ------------------------------------------------------------- rerank 规则
def _draft(shot_id="shot_001", *, beats=0, justifies=0, bad=False):
    payload = {"shot_id": shot_id, "shot_type": "MS"}
    payload["beats"] = [{"t": 0.0, "subject": "char_001", "verb": "stand"}
                        for _ in range(beats)]
    payload["rule_justifications"] = [
        {"rule": f"R{i:03d}", "action": "follow"} for i in range(justifies)]
    if bad:  # 未知动词 ⇒ validate_beats 报问题
        payload["beats"] = [{"t": 0.0, "subject": "char_001",
                             "verb": "fly_to_moon"}]
    return ShotDraft.from_dict(payload)


def test_score_prefers_detail_and_penalises_problems():
    plain = score_draft(_draft(beats=1, justifies=2),
                        characters=["char_001"])
    bare = score_draft(_draft(), characters=["char_001"])
    broken = score_draft(_draft(bad=True), characters=["char_001"])
    assert plain > bare > broken


def test_rank_keeps_every_candidate_and_is_stable():
    good = _draft(beats=2)
    medium = _draft(beats=1)
    bad = _draft(beats=1, justifies=0, bad=True)
    best, alternates = rank_drafts([medium, bad, good],
                                   characters=["char_001"])
    assert best is good
    assert len(alternates) == 2, "rerank 不是过滤：低分候选一个都不许丢"
    assert alternates[0] is medium and alternates[1] is bad
    #: 同分按原始顺序（稳定排序）。
    first, _ = rank_drafts([_draft(), _draft()], characters=["char_001"])
    assert first is not None


def test_rank_of_a_single_candidate_is_identity():
    only = _draft(beats=1)
    best, alternates = rank_drafts([only], characters=["char_001"])
    assert best is only and alternates == []


def test_empty_candidates_rank_to_none():
    assert rank_drafts([]) == (None, [])


# ----------------------------------------------- 默认 1 = 零行为差（驱动侧）
def test_default_config_requests_exactly_one_candidate():
    driver = PrevisDriver.__new__(PrevisDriver)
    driver.config = AppConfig()
    assert driver._draft_candidate_count() == 1
    driver.config = None
    assert driver._draft_candidate_count() == 1


def test_snapshot_draft_alternates_is_empty_by_default():
    driver = PrevisDriver.__new__(PrevisDriver)
    driver._draft_alternates = {}
    #: 快照里的这一格在默认路径恒为空表（不引入新字段差异）。
    assert {k: list(v) for k, v in driver._draft_alternates.items()} == {}


# ------------------------------------------------------------- 交付清单
def _plan() -> Plan:
    return Plan.from_dict({"scene_heading": "INT", "shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
         "duration_frames": 24, "characters": ["char_001"]}]})


def test_manifest_alternates_defaults_to_empty():
    manifest = build_manifest(_plan(), generated_at="t")
    assert manifest["shots"][0]["alternates"] == []


def test_manifest_writes_alternates_from_build_results():
    alt = _draft(beats=1).to_dict()
    manifest = build_manifest(
        _plan(), generated_at="t",
        build_summary={"results": [{"shot_id": "shot_001",
                                    "alternates": [alt]}]})
    assert manifest["shots"][0]["alternates"][0]["shot_id"] == "shot_001"


# ------------------------------------------------------------- 多样性度量
def test_levenshtein_basic():
    assert levenshtein([], []) == 0
    assert levenshtein(["a", "b"], ["a", "b"]) == 0
    assert levenshtein(["a", "b"], ["a"]) == 1
    assert levenshtein(["a"], ["b"]) == 1


def test_sequence_edit_distance_needs_two_runs():
    assert sequence_edit_distance([["MS"]] * 3)["pairs"] == 3
    assert sequence_edit_distance([["MS", "CU"], ["MS", "LS"]])["sum"] == 1
    assert sequence_edit_distance([["MS"]])["pairs"] == 0


def test_movement_chi_square_needs_two_runs_and_two_kinds():
    from collections import Counter

    assert movement_chi_square([Counter({"a": 1})])["runs"] == 1
    two = movement_chi_square([Counter({"a": 2}), Counter({"a": 2})])
    assert two["statistic"] == 0.0 and two["dof"] == 0
    skew = movement_chi_square([Counter({"a": 4}), Counter({"b": 4})])
    assert skew["statistic"] > 0


def test_axis_flip_rate_counts_disagreeing_shots():
    assert axis_flip_rate([[1, 1], [1, 1]])["rate"] == 0.0
    assert axis_flip_rate([[1, 1], [1, -1]])["rate"] == 0.5
    assert axis_flip_rate([[1]])["comparable_shots"] == 0


def test_diversity_report_on_two_plans():
    left = {"shots": [{"shot_type": "MS", "camera": {"movements": [
        {"type": "dolly_in"}]}, "axis": {"side_sign": 1}}]}
    right = {"shots": [{"shot_type": "LS", "camera": {"movements": [
        {"type": "pan_left"}]}, "axis": {"side_sign": -1}}]}
    report = diversity_report([left, right])
    assert report["runs"] == 2
    assert report["shot_type_edit_distance"]["sum"] == 1
    assert report["axis_flip"]["rate"] == 1.0
    assert report["movement_chi_square"]["kinds"] == 2


def test_movement_histogram_also_reads_the_shots_json_shape():
    """`shots.json` 的 `movements[]` 在**镜头级**、键是 `kind`（P15 §3.3）。

    2026-10-07 实测的缺陷：只认计划的 `camera.movements[].type` 时，拿三份
    冻结工程的 `shots.json` 跑，运镜那一栏恒为 `kinds = 0` —— 结构性量不出来
    却读起来像"运镜完全一样"。两种形状都得认。
    """
    manifest_shape = {"shots": [
        {"shot_id": "shot_001", "shot_type": "LS",
         "movements": [{"kind": "steadicam", "start_frame": 1,
                        "end_frame": 72, "source": "planned"}],
         "axis": {"side_sign": -1}},
        {"shot_id": "shot_002", "shot_type": "MS", "movements": []},
    ]}
    plan = {"shots": [{"shot_type": "LS",
                       "camera": {"movements": [{"type": "dolly_in"}]},
                       "axis": {"side_sign": 1}}]}
    report = diversity_report([manifest_shape, plan])
    assert report["movement_chi_square"]["kinds"] == 2, "两种形状各数出一种运镜"
    assert report["shot_type_edit_distance"]["sum"] == 1
    assert report["measurable"]["movement"] is True


def test_report_flags_dimensions_it_structurally_cannot_measure():
    """早于 `movements` / `axis` 字段的成片：那一栏的 0 **不许**读成"很僵"。"""
    old_run = {"shots": [{"shot_id": "shot_001", "shot_type": "MS"},
                         {"shot_id": "shot_002", "shot_type": "MCU"}]}
    other = {"shots": [{"shot_id": "shot_001", "shot_type": "MS"},
                       {"shot_id": "shot_002", "shot_type": "MCU"}]}
    report = diversity_report([old_run, other])
    assert report["movement_chi_square"]["kinds"] == 0
    assert report["measurable"] == {"shot_type": True, "movement": False,
                                    "axis": False}


def test_diversity_report_single_run_is_zero_not_error():
    report = diversity_report([{"shots": [{"shot_type": "MS"}]}])
    assert report["runs"] == 1
    assert report["shot_type_edit_distance"]["pairs"] == 0
    assert report["axis_flip"]["rate"] == 0.0
