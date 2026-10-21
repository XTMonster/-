"""R2 ticket 04（F1）：headless 真跑必须经过粗排 gate。

根因：``run_coarse_pipeline`` 只挂在 UI 全管线入口（``pipeline_operator.py``），
``run_headless --build --export`` 直接 BUILDING→CHECKING/PER_SHOT，粗排等于没跑
（真跑日志无粗排 check，证据目录无 coarse 三件套）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from block_director.layer5_orchestrator.pipeline_ui_inputs import coarse_is_ready
from block_director.delivery.coarse_gate import run_coarse_gate_decision


def test_coarse_is_ready_pass_only_when_frozen():
    ok = {"gates": {"coarse": "pass", "baseline": "frozen"}}
    not_ok = {"gates": {"coarse": "blocked", "baseline": "missing"}}
    assert coarse_is_ready(ok)
    assert not coarse_is_ready(not_ok)
    assert not coarse_is_ready(None)


def test_run_coarse_gate_decision_ready():
    report = {"gates": {"coarse": "pass", "baseline": "frozen"}}
    d = run_coarse_gate_decision(report)
    assert d["ready"] is True
    assert d["blocked"] is False


def test_run_coarse_gate_decision_blocked():
    report = {"gates": {"coarse": "blocked", "baseline": "missing"}}
    d = run_coarse_gate_decision(report)
    assert d["ready"] is False
    assert d["blocked"] is True


def test_headless_coarse_gate_passes_real_brief_to_pipeline(monkeypatch, tmp_path):
    """A：headless 粗排 gate 不得丢 Stage S 的真实 brief。

    真跑 20261019-r2-market-coin-accept-3 的 root cause：``_make_coarse_gate``
    两条路径都传 ``brief=None``，粗排设计快照用了 ``deterministic_brief``
    （3 角色、无 props、无精确 space），shot_002 拍物无物、shot_007 站位
    关系缺失。gate 回调必须把 driver 透传的 brief 送进 ``run_coarse_pipeline``。
    """
    from block_director.layer5_orchestrator import coarse_pipeline as cp
    from block_director.contracts.plan import Plan, ShotPlan, ShotType
    from tools.run_headless import _make_coarse_gate

    captured: dict = {}

    def fake_runner(**kwargs):
        import json

        captured.update(kwargs)
        out = tmp_path / "coarse"
        out.mkdir(parents=True, exist_ok=True)
        baseline_path = out / "coarse_world_baseline.json"
        baseline_path.write_text(json.dumps({
            "schema_version": "coarse-baseline/v1",
            "state": "frozen",
            "manifest": {"cameras": []},
        }), encoding="utf-8")
        return {
            "schema_version": "coarse-pipeline-report/v1",
            "gates": {"coarse": "pass", "baseline": "frozen"},
            "coarse_status": "approved",
            "rounds": [],
            "artifacts": {"baseline": str(baseline_path)},
        }

    monkeypatch.setattr(cp, "run_coarse_pipeline", fake_runner)
    gate = _make_coarse_gate(str(tmp_path), audit_log=None)
    plan = Plan(
        scene_heading="港口市场取景",
        shots=[ShotPlan(
            shot_id="shot_001", order=1, intent="银币特写",
            shot_type=ShotType.CU, duration_frames=48,
            characters=["米迦尔", "伊恩"], actions=[], camera={})])
    brief = SimpleNamespace(
        space=[{"character": "伊恩", "relative_to": "米迦尔",
                "relation": "side_by_side"}],
        to_dict=lambda: {"notes": ["真实 brief"], "props": [
            {"id": "银币", "kind": "prop", "owner": "米迦尔"}]})
    result = gate(plan=plan, brief=brief)
    assert result["ready"] is True
    assert "brief" in captured, "run_coarse_pipeline 必须收到 brief"
    assert captured["brief"] is brief
    assert captured["plan"] is plan
    #: A 完整语义：SceneSpec.from_plan 也要吃真实 brief（space 站位），
    #: 否则 shot_007 的 OTS 站位关系继续缺失。
    ian = captured["cast_positions"].get("伊恩")
    assert ian is not None, f"cast_positions 应含伊恩，实际 {captured['cast_positions']}"
    assert ian[1] < 0.0, (f"伊恩应被 brief.space side_by_side 摆到米迦尔右侧"
                          f"（y<0），实际 {ian}")


def test_headless_coarse_gate_decision_carries_frozen_baseline(
        monkeypatch, tmp_path):
    """The ready decision must carry the exact baseline the gate approved."""
    import json

    from block_director.layer5_orchestrator import coarse_pipeline as cp
    from block_director.contracts.plan import Plan, ShotPlan, ShotType
    from tools.run_headless import _make_coarse_gate

    baseline = {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "manifest": {"cameras": [{
            "shot_id": "shot_001",
            "position": [4.25, -1.75, 1.35],
            "target": [-0.2, 0.15, 1.05],
            "lens_mm": 85.0,
            "resolved": True,
        }]},
    }

    def fake_runner(**kwargs):
        out = tmp_path / "coarse"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "coarse_world_baseline.json"
        path.write_text(json.dumps(baseline), encoding="utf-8")
        return {
            "schema_version": "coarse-pipeline-report/v1",
            "gates": {"coarse": "pass", "baseline": "frozen"},
            "coarse_status": "approved",
            "rounds": [],
            "artifacts": {"baseline": str(path)},
        }

    monkeypatch.setattr(cp, "run_coarse_pipeline", fake_runner)
    gate = _make_coarse_gate(str(tmp_path), audit_log=None)
    plan = Plan(
        scene_heading="桥接探针",
        shots=[ShotPlan(
            shot_id="shot_001", order=1, intent="审批机位",
            shot_type=ShotType.CU, duration_frames=24,
            characters=["米迦尔"], actions=[], camera={})])

    result = gate(plan=plan, brief=None)

    assert result["ready"] is True
    assert result["baseline"] == baseline


def test_headless_coarse_gate_failure_records_a_traceback(monkeypatch, tmp_path):
    """An unexpected coarse exception must retain its location.

    Real r2 only logged ``IndexError: list index out of range``.  That made a
    program failure indistinguishable from a legitimate quality block and left
    no file/line context for diagnosis.
    """
    from block_director.layer5_orchestrator import coarse_pipeline as cp
    from block_director.contracts.plan import Plan, ShotPlan, ShotType
    from tools.run_headless import _make_coarse_gate

    def broken_runner(**kwargs):
        raise IndexError("synthetic coarse failure")

    records = []

    def audit_log(kind, message, **data):
        records.append({"kind": kind, "message": message, **data})

    monkeypatch.setattr(cp, "run_coarse_pipeline", broken_runner)
    gate = _make_coarse_gate(str(tmp_path), audit_log=audit_log)
    plan = Plan(
        scene_heading="港口市场取景",
        shots=[ShotPlan(
            shot_id="shot_001", order=1, intent="建立",
            shot_type=ShotType.MS, duration_frames=48,
            characters=["米迦尔"], actions=[], camera={})])

    result = gate(plan=plan, brief=None)

    assert result["ready"] is False
    assert result["execution_error"] is True
    assert "IndexError" in result["reason"]
    assert records and records[0]["kind"] == "headless_coarse_gate"
    assert "Traceback" in records[0]["traceback"]
    assert "broken_runner" in records[0]["traceback"]


def test_headless_coarse_gate_forwards_agent_and_rag(monkeypatch, tmp_path):
    """The headless coarse loop receives the agent, RAG, audit, and budget."""
    from block_director.layer5_orchestrator import coarse_pipeline as cp
    from block_director.contracts.plan import Plan, ShotPlan, ShotType
    from tools.run_headless import _make_coarse_gate

    captured = {}
    transport = object()
    knowledge = object()
    audit = object()
    budget = object()

    def fake_runner(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop after capturing")

    monkeypatch.setattr(cp, "run_coarse_pipeline", fake_runner)
    gate = _make_coarse_gate(
        str(tmp_path), audit_log=None, transport=transport,
        knowledge=knowledge, audit=audit)
    gate.bind_budget(budget)
    plan = Plan(shots=[ShotPlan(
        shot_id="shot_001", order=1, intent="建立",
        shot_type=ShotType.MS, duration_frames=24,
        characters=["米迦尔"], actions=[], camera={})])

    decision = gate(plan=plan, brief=None)

    assert decision["ready"] is False
    assert captured["transport"] is transport
    assert captured["knowledge"] is knowledge
    assert captured["audit"] is audit
    assert captured["budget"] is budget


def test_headless_coarse_gate_preserves_each_plan_attempt(
        monkeypatch, tmp_path):
    """Plan-level search must not erase the prior candidate's evidence.

    ``run_coarse_pipeline`` owns and clears its own ``observations`` directory.
    Reusing one output directory for every replanned candidate therefore made
    the final evidence describe only the last loser.  Each driver call needs a
    stable attempt identity whose observations survive later calls.
    """
    from block_director.contracts.plan import Plan, ShotPlan, ShotType
    from block_director.layer5_orchestrator import coarse_pipeline as cp
    from tools.run_headless import _make_coarse_gate

    calls = []

    def fake_runner(**kwargs):
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        observation = out / "observations" / "attempt-001" / "sentinel.json"
        observation.parent.mkdir(parents=True, exist_ok=True)
        observation.write_text('{"candidate": "%s"}' % len(calls),
                                encoding="utf-8")
        calls.append(str(out))
        return {
            "schema_version": "coarse-pipeline-report/v1",
            "gates": {"coarse": "blocked", "baseline": "missing"},
            "coarse_status": "blocked",
            "blocked_reason": "synthetic blocked candidate",
            "best_score": 70.0 + len(calls),
            "rounds": [{"findings": 3}],
            "artifacts": {},
        }

    monkeypatch.setattr(cp, "run_coarse_pipeline", fake_runner)
    gate = _make_coarse_gate(str(tmp_path), audit_log=None)

    def plan(heading):
        return Plan(scene_heading=heading, shots=[ShotPlan(
            shot_id="shot_001", order=1, intent="测试候选",
            shot_type=ShotType.MS, duration_frames=24,
            characters=["米迦尔"], actions=[], camera={})])

    first = gate(plan("candidate-1"), brief=None)
    second = gate(plan("candidate-2"), brief=None)

    assert calls[0] != calls[1], "each plan attempt must get its own out_dir"
    assert first["plan_attempt_id"] != second["plan_attempt_id"]
    first_marker = (
        tmp_path / "coarse" / "plan_attempts" / "attempt-001"
        / "observations" / "attempt-001" / "sentinel.json")
    second_marker = (
        tmp_path / "coarse" / "plan_attempts" / "attempt-002"
        / "observations" / "attempt-001" / "sentinel.json")
    assert first_marker.is_file(), "the first plan attempt was overwritten"
    assert second_marker.is_file()
    assert json.loads(first_marker.read_text(encoding="utf-8")) == {
        "candidate": "0"}
    assert json.loads(second_marker.read_text(encoding="utf-8")) == {
        "candidate": "1"}
    index = json.loads((
        tmp_path / "coarse" / "plan_attempts" / "index.json"
    ).read_text(encoding="utf-8"))
    assert [row["plan_attempt_id"] for row in index["attempts"]] == [
        "attempt-001", "attempt-002"]


def test_headless_coarse_gate_restores_selected_attempt_physically(
        monkeypatch, tmp_path):
    """The selected plan-level best must rebuild its own scene and publish it.

    A later blocked replan leaves Blender at the last loser.  The headless gate
    therefore has to retain each attempt's manifest and expose a physical
    restore callback for the driver.  Canonical ``coarse/`` evidence is only
    authoritative after that restore succeeds, and stale baseline files from
    an older candidate must not survive a blocked best.
    """
    from block_director.contracts.blockout import manifest_fingerprint
    from block_director.contracts.plan import Plan, ShotPlan, ShotType
    from block_director.layer5_orchestrator import coarse_pipeline as cp
    from block_director.contracts.world_state import world_state_fingerprint
    from tools.run_headless import _make_coarse_gate

    calls = []
    manifests = {}
    worlds = {}

    def fake_runner(**kwargs):
        out = kwargs["out_dir"]
        out.mkdir(parents=True, exist_ok=True)
        candidate = len(calls) + 1
        manifest = {
            "schema_version": "blockout-manifest/v1",
            "scene_id": f"candidate-{candidate}",
            "primitives": [{"id": f"primitive-{candidate}"}],
            "cameras": [],
            "shot_table": [],
        }
        world = {
            "schema_version": "runtime-world/v1",
            "characters": {"米迦尔": {
                "position": [float(candidate), 0.0, 0.0],
                "facing": [0.0, 1.0, 0.0],
            }},
            "cameras": {},
            "props": {},
            "anchors": {},
            "shot_states": {},
        }
        manifest_path = out / "blockout_manifest.json"
        world_path = out / "blockout_world_state.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        world_path.write_text(
            json.dumps(world, ensure_ascii=False), encoding="utf-8")
        report = {
            "schema_version": "coarse-pipeline-report/v1",
            "run_id": f"candidate-{candidate}",
            "gates": {"coarse": "blocked", "baseline": "missing"},
            "coarse_status": "blocked",
            "blocked_reason": "synthetic blocked candidate",
            "best_score": 70.0 + candidate,
            "best_manifest_fingerprint": manifest_fingerprint(manifest),
            "best_world_state_fingerprint": world_state_fingerprint(world),
            "rounds": [{"findings": 4 - candidate}],
            "artifacts": {
                "blockout_manifest": str(manifest_path),
                "blockout_world_state": str(world_path),
            },
        }
        (out / "coarse_pipeline_report.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8")
        calls.append(str(out))
        manifests[candidate] = manifest
        worlds[candidate] = world
        return report

    restored = []

    def restore_scene(*, manifest, expected_world_state, expected_report):
        restored.append({
            "manifest": manifest,
            "world": expected_world_state,
            "report": expected_report,
        })
        return {
            "restored": True,
            "manifest_fingerprint": manifest_fingerprint(manifest),
            "world_state_fingerprint": world_state_fingerprint(
                expected_world_state),
        }

    monkeypatch.setattr(cp, "run_coarse_pipeline", fake_runner)
    gate = _make_coarse_gate(
        str(tmp_path), audit_log=None, scene_restorer=restore_scene)

    def plan(heading):
        return Plan(scene_heading=heading, shots=[ShotPlan(
            shot_id="shot_001", order=1, intent="测试候选",
            shot_type=ShotType.MS, duration_frames=24,
            characters=["米迦尔"], actions=[], camera={})])

    first_plan = plan("candidate-1")
    first = gate(first_plan, brief=None)
    gate(plan("candidate-2"), brief=None)

    stale_baseline = tmp_path / "coarse" / "coarse_world_baseline.json"
    stale_baseline.write_text('{"state": "frozen"}', encoding="utf-8")

    result = gate.restore_best(plan=first_plan, decision=first)

    assert result["restored"] is True
    assert result["plan_attempt_id"] == "attempt-001"
    assert restored == [{
        "manifest": manifests[1],
        "world": worlds[1],
        "report": first["payload"],
    }]
    canonical_report = json.loads((
        tmp_path / "coarse" / "coarse_pipeline_report.json"
    ).read_text(encoding="utf-8"))
    assert canonical_report["run_id"] == "candidate-1"
    assert canonical_report["plan_attempt_id"] == "attempt-001"
    assert json.loads((
        tmp_path / "coarse" / "blockout_manifest.json"
    ).read_text(encoding="utf-8")) == manifests[1]
    assert not stale_baseline.exists(), (
        "a blocked selected best must not inherit an older frozen baseline")
    index = json.loads((
        tmp_path / "coarse" / "plan_attempts" / "index.json"
    ).read_text(encoding="utf-8"))
    assert index["selected_plan_attempt_id"] == "attempt-001"
