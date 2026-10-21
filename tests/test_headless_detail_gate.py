"""Headless must finish through the same detail/final gate as the UI."""

from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

from block_director.contracts.plan import Plan, ShotPlan, ShotType
from tools.run_headless import _make_detail_gate


def _write_baseline(project_dir):
    coarse_dir = project_dir / "coarse"
    coarse_dir.mkdir(parents=True)
    baseline = {
        "schema_version": "coarse-baseline/v1",
        "state": "frozen",
        "reference": {},
        "manifest": {},
        "report": {"findings": [], "checks": []},
    }
    (coarse_dir / "coarse_world_baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
    return baseline


def _plan():
    return Plan(
        scene_heading="港口市场",
        shots=[ShotPlan(
            shot_id="shot_001",
            order=1,
            intent="银币特写",
            shot_type=ShotType.CU,
            duration_frames=48,
            characters=["米迦尔"],
            actions=[],
            camera={},
        )],
    )


def test_detail_gate_blocks_pending_and_preserves_real_report(tmp_path):
    baseline = _write_baseline(tmp_path)
    captured = {}
    transport = object()
    knowledge = object()

    def fake_detail_runner(**kwargs):
        captured.update(kwargs)
        return {
            "phase": "SEQUENCE_REVIEWED",
            "gates": {
                "coarse": "pass",
                "baseline": "frozen",
                "detail": "pending",
                "sequence": "pending",
                "final": "pending",
            },
            "final": False,
            "artifacts": {"final_video": None},
        }

    gate = _make_detail_gate(
        tmp_path,
        detail_runner=fake_detail_runner,
        audit_log=None,
        transport=transport,
        knowledge=knowledge,
        run_id="run-node123",
    )
    result = gate(_plan())

    assert captured["baseline"] == baseline
    assert captured["out_dir"] == tmp_path / "detail"
    assert captured["render_video"] is True
    assert captured["transport"] is transport
    assert captured["knowledge"] is knowledge
    assert captured["run_id"] == "run-node123"
    assert captured["scene_id"] == "港口市场"
    assert captured["proposal_max_tokens"] == 12000
    assert result["ready"] is False
    assert result["gates"]["detail"] == "pending"
    assert result["gates"]["final"] == "pending"
    assert result["final_video"] is None


def test_detail_gate_passes_only_when_final_video_and_all_gates_pass(tmp_path):
    _write_baseline(tmp_path)
    final_video = tmp_path / "detail" / "final_video.mp4"
    final_video.parent.mkdir(parents=True)
    final_video.write_bytes(b"final")

    def fake_detail_runner(**_kwargs):
        return {
            "phase": "FINAL_EXPORTED",
            "gates": {
                "coarse": "pass",
                "baseline": "frozen",
                "detail": "pass",
                "sequence": "pass",
                "final": "pass",
            },
            "final": True,
            "artifacts": {"final_video": str(final_video)},
        }

    gate = _make_detail_gate(tmp_path, detail_runner=fake_detail_runner)
    result = gate(_plan())

    assert result["ready"] is True
    assert result["gates"] == {
        "coarse": "pass",
        "baseline": "frozen",
        "detail": "pass",
        "sequence": "pass",
        "final": "pass",
    }
    assert result["final_video"] == str(final_video)


def test_headless_export_cannot_succeed_with_pending_detail_gate(
    monkeypatch, tmp_path, capsys,
):
    import block_director
    import block_director.layer5_orchestrator.headless_runner as headless_runner
    import block_director.layer5_orchestrator.driver as driver_module
    import block_director.settings as settings
    import tools.run_headless as run_headless
    from block_director.contracts.config import AppConfig

    plan = _plan()
    summary = {
        "success": True,
        "state": "DONE",
        "plan": plan.to_dict(),
        "build": {"built": True, "results": []},
        "shots": 1,
        "llm_calls": 1,
        "retrieval_calls": 0,
        "audit_pass_rate": {},
        "failures": {"schema_version": "delivery-failures/v1",
                     "failures": []},
        "resume_state_path": None,
    }

    monkeypatch.setattr(block_director, "register", lambda: None)
    monkeypatch.setattr(settings, "get_config", lambda: AppConfig())
    monkeypatch.setattr(driver_module, "default_registry",
                        lambda **_kwargs: object())
    run_kwargs = {}

    def fake_run_headless(*_args, **kwargs):
        run_kwargs.update(kwargs)
        return dict(summary)

    monkeypatch.setattr(headless_runner, "run_headless", fake_run_headless)
    coarse_audit_logs = []

    coarse_runtime = {}

    def fake_coarse_gate(_project_dir, audit_log=None, **kwargs):
        coarse_audit_logs.append(audit_log)
        coarse_runtime.update(kwargs)
        return lambda _plan, brief=None: {"ready": True}

    monkeypatch.setattr(run_headless, "_make_coarse_gate", fake_coarse_gate)

    shot_auditor = ModuleType("block_director.layer3_engine.shot_auditor")
    shot_auditor.BpyShotAuditor = object
    monkeypatch.setitem(sys.modules,
                        "block_director.layer3_engine.shot_auditor",
                        shot_auditor)
    scene_state = ModuleType("block_director.layer3_engine.scene_state")
    scene_state.collect_scene_state = lambda **_kwargs: {}
    monkeypatch.setitem(sys.modules,
                        "block_director.layer3_engine.scene_state",
                        scene_state)
    tool_bindings = ModuleType("block_director.layer3_engine.tool_bindings")
    tool_bindings.register_all_scene_tools = lambda _registry: None
    monkeypatch.setitem(sys.modules,
                        "block_director.layer3_engine.tool_bindings",
                        tool_bindings)

    report = SimpleNamespace(
        ok=True,
        shots=[{"shot_id": "shot_001", "video": "blockout_shot_001.mp4"}],
        to_dict=lambda: {
            "ok": True, "aborted": False, "reason": "",
            "out_dir": str(tmp_path / "export"), "files": ["shots.json"],
            "warnings": [],
        },
    )
    monkeypatch.setattr(run_headless, "_export_report",
                        lambda *_args, **_kwargs: report)

    detail_called = []
    detail_runtime = {}

    def blocked_detail_gate(*_args, **kwargs):
        detail_runtime.update(kwargs)

        def gate(_plan_obj, runtime_world_state=None):
            detail_called.append(runtime_world_state)
            return {
                "ready": False,
                "reason": "细排/final gate 未通过",
                "gates": {
                    "coarse": "pass",
                    "baseline": "frozen",
                    "detail": "pending",
                    "sequence": "pending",
                    "final": "pending",
                },
                "final_video": None,
                "payload": {},
            }
        return gate

    monkeypatch.setattr(run_headless, "_make_detail_gate",
                        blocked_detail_gate)
    monkeypatch.setattr(
        sys, "argv",
        ["run_headless.py", "--", "--out", str(tmp_path), "--export"])

    exit_code = run_headless.main()
    output = capsys.readouterr().out
    marker = next(line for line in output.splitlines()
                  if line.startswith("BLOCKDIRECTOR_RESULT "))
    payload = json.loads(marker.removeprefix("BLOCKDIRECTOR_RESULT "))

    assert detail_called == [None]
    assert detail_runtime["transport"] is coarse_runtime["transport"]
    assert detail_runtime["knowledge"] is coarse_runtime["knowledge"]
    assert detail_runtime["config"] is run_kwargs["config"]
    assert detail_runtime["run_id"] == run_kwargs["audit"].run_id
    assert payload["driver_success"] is True
    assert payload["success"] is False
    assert payload["full_pipeline"]["gates"]["final"] == "pending"
    audit = run_kwargs["audit"]
    assert len(coarse_audit_logs) == 1
    assert coarse_audit_logs[0].__self__ is audit
    assert run_kwargs["transport"] is coarse_runtime["transport"]
    assert run_kwargs["knowledge"] is coarse_runtime["knowledge"]
    assert exit_code == 1
