"""v1.6 A5（D-07）：`request_self_review` 登记的镜头要落到交付产物里。"""

from __future__ import annotations

from block_director.contracts.plan import Plan, ShotPlan
from block_director.delivery.manifest import build_manifest


def _minimal_plan():
    return Plan(shots=[
        ShotPlan(shot_id="shot_001", intent="开场", shot_type="MS",
                 duration_frames=48),
        ShotPlan(shot_id="shot_002", intent="对峙", shot_type="MCU",
                 duration_frames=48),
    ])


def test_manifest_flags_reviewed_shots():
    plan = _minimal_plan()
    manifest = build_manifest(
        plan, review_requests=[{"shot_id": "shot_001", "intent": "开场"}])
    flags = {s["shot_id"]: s["needs_review"] for s in manifest["shots"]}
    assert flags == {"shot_001": True, "shot_002": False}


def test_manifest_defaults_to_no_review():
    plan = _minimal_plan()
    manifest = build_manifest(plan)
    assert all(not s["needs_review"] for s in manifest["shots"])


def test_review_requests_without_shot_id_are_ignored():
    plan = _minimal_plan()
    manifest = build_manifest(
        plan, review_requests=[{"shot_id": "", "intent": "x"}])
    assert all(not s["needs_review"] for s in manifest["shots"])


def test_manifest_keeps_registration_counts_without_inflating_shot_count():
    manifest = build_manifest(
        _minimal_plan(), review_requests=[
            {"shot_id": "shot_001", "intent": "看构图"},
            {"shot_id": "shot_001", "intent": "再看构图"},
            {"shot_id": "shot_002", "intent": "看连续性"},
        ])
    counts = {shot["shot_id"]: shot["review_request_count"]
              for shot in manifest["shots"]}
    assert counts == {"shot_001": 2, "shot_002": 1}
    assert len(manifest["shots"]) == 2


def test_manifest_default_registration_counts_are_zero():
    manifest = build_manifest(_minimal_plan())
    assert [shot["review_request_count"] for shot in manifest["shots"]] == [0, 0]


def test_public_readme_renders_counts_from_the_manifest(tmp_path):
    from block_director.delivery.readme import render_readme

    manifest = build_manifest(_minimal_plan(), review_requests=[
        {"shot_id": "shot_001"}, {"shot_id": "shot_001"},
        {"shot_id": "shot_002"},
    ])
    text = render_readme(manifest, out_dir=tmp_path)
    assert "## 待人工复核" in text
    assert "shot_001：登记 2 次" in text
    assert "shot_002：登记 1 次" in text


def test_runtime_snapshot_keeps_review_records_for_unattended_export():
    import json

    from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
    from block_director.layer5_orchestrator.driver import PrevisDriver
    from block_director.layer5_orchestrator.states import DriverState
    from block_director.layer6_audit.audit_logger import AuditLogger
    from stage_helpers import is_understand, understand_reply
    from test_driver import InlineThread

    class ReviewThenPlanTransport:
        def chat(self, payload, timeout):
            if is_understand(payload):
                return understand_reply(payload.request_id)
            # The real dispatch path processes every tool call, in order.
            calls = [
                ToolCall(id=f"review-{i}", function=FunctionCall(
                    name="request_self_review",
                    arguments=json.dumps({"shot_id": "shot_001"})))
                for i in range(2)
            ]
            calls.append(ToolCall(id="plan", function=FunctionCall(
                name="emit_plan",
                arguments=json.dumps({"shots": [
                    {"shot_id": "shot_001", "order": 1, "intent": "开场",
                     "shot_type": "MS", "duration_frames": 48},
                    {"shot_id": "shot_002", "order": 2, "intent": "对峙",
                     "shot_type": "MCU", "duration_frames": 48},
                ]}))))
            return ChatReply(tool_calls=calls)

    driver = PrevisDriver(transport=ReviewThenPlanTransport(), audit=AuditLogger(),
                          thread_factory=InlineThread)
    assert driver.run_to_completion() is DriverState.DONE
    summary = driver.snapshot()
    assert summary["review_requests"] == 2
    records = summary["self_review_requests"]
    assert [record["shot_id"] for record in records] == ["shot_001", "shot_001"]
    # Serialisation is the actual boundary between the runner and CLI exporter.
    restored = json.loads(json.dumps(summary))
    manifest = build_manifest(
        _minimal_plan(), review_requests=restored["self_review_requests"])
    assert manifest["shots"][0]["needs_review"] is True
    assert manifest["shots"][0]["review_request_count"] == 2
    assert manifest["shots"][1]["needs_review"] is False
    records[0]["shot_id"] = "mutated-by-consumer"
    assert driver.review_requests[0]["shot_id"] == "shot_001"


def test_live_run_export_entrypoints_forward_review_records():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "tools/run_headless.py",
        root / "tools/run_export.py",
        root / "block_director/layer5_orchestrator/modal_operator.py",
        root / "block_director/layer7_ui/panel_main.py",
    ]
    seen = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "export_project":
                seen.append(path.name)
                assert "review_requests" in {kw.arg for kw in node.keywords}, path
    assert sorted(seen) == sorted(path.name for path in paths)


def test_readme_has_review_section(tmp_path):
    from block_director.delivery.readme import render_readme

    plan = _minimal_plan()
    manifest = build_manifest(
        plan, review_requests=[{"shot_id": "shot_002", "intent": "对峙"}])
    text = render_readme(manifest, out_dir=tmp_path)
    assert "## 待人工复核" in text
    assert "shot_002" in text
    assert "1 个镜头" in text


def test_readme_omits_review_section_when_none(tmp_path):
    from block_director.delivery.readme import render_readme

    plan = _minimal_plan()
    manifest = build_manifest(plan)
    text = render_readme(manifest, out_dir=tmp_path)
    assert "## 待人工复核" not in text
