"""headless 运行路径测试（不依赖 Blender：驱动器本身与 bpy 解耦）。"""

from __future__ import annotations

import json

from block_director.layer5_orchestrator.headless_runner import run_headless

SCRIPT = "INT. 咖啡馆 - 日\n\n小明坐下。\n"


def test_headless_offline_run_writes_logs(tmp_path):
    summary = run_headless(SCRIPT, offline=True, project_dir=tmp_path,
                           poll_interval=0.0, max_wall_s=30.0)
    assert summary["success"] is True
    assert summary["state"] == "DONE"
    assert summary["shots"] == 2
    assert summary["mode"] == "offline"

    audit_path = tmp_path / "runs" / "audit_log.jsonl"
    trace_path = tmp_path / "runs" / "llm_trace.jsonl"
    assert audit_path.exists() and trace_path.exists()

    kinds = [json.loads(line)["kind"]
             for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert kinds[0] == "run_started"
    assert kinds[-1] == "run_finished"

    trace = json.loads(trace_path.read_text(encoding="utf-8").strip())
    assert trace["purpose"] == "plan"


def test_headless_records_plan_shots(tmp_path):
    summary = run_headless(SCRIPT, offline=True, project_dir=tmp_path,
                           poll_interval=0.0)
    audit = (tmp_path / "runs" / "audit_log.jsonl").read_text(encoding="utf-8")
    records = [json.loads(line) for line in audit.splitlines()]
    plan_events = [r for r in records if r["kind"] == "plan_received"]
    assert len(plan_events) == 1
    shot_ids = [s["shot_id"] for s in plan_events[0]["data"]["shots"]]
    assert shot_ids == ["shot_001", "shot_002"]
    assert summary["total_frames"] == 216
