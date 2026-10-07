"""Read-only acceptance diagnostics for A1-A4 + A5 dirty (2026-10-08).

This is not the pytest suite or a Blender integration test. Source extraction
below executes only the named pure/error-return functions without importing bpy;
it cannot certify the complete Blender module or rendering behavior.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from block_director.contracts.config import AppConfig
from block_director.contracts.messages import ChatReply, FunctionCall, ToolCall
from block_director.contracts.plan import Plan, ShotPlan, unknown_cast_ids
from block_director.delivery.manifest import build_manifest
from block_director.layer5_orchestrator.driver import DriverLimits, PrevisDriver
from block_director.layer5_orchestrator.editor import extract_draft, merge_draft
from block_director.layer5_orchestrator.tool_registry import ToolResult
from block_director.layer6_audit.audit_logger import AuditLogger


class NeverCalledTransport:
    def chat(self, *args, **kwargs):
        raise AssertionError("This diagnostic must not invoke a model.")


def driver(**kwargs):
    return PrevisDriver(
        transport=NeverCalledTransport(), audit=AuditLogger(), **kwargs
    )


def plan(*characters):
    return Plan(shots=[
        ShotPlan(shot_id="shot_001", intent="test", shot_type="MS",
                 duration_frames=48, characters=list(characters))
    ])


def extract_functions(relative, names, namespace):
    path = ROOT / relative
    source = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in source.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    for node in selected:
        node.decorator_list = []
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    tree = ast.fix_missing_locations(ast.Module(
        body=[future, *selected], type_ignores=[]
    ))
    exec(compile(tree, str(path), "exec"), namespace)
    return namespace


def export_call_sites():
    rows = []
    for folder in ("block_director", "tools"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            if "_probe_out" in path.parts or "blender_tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if getattr(node.func, "id", "") != "export_project":
                    continue
                keys = {key.arg for key in node.keywords}
                rows.append({
                    "file": str(path.relative_to(ROOT)), "line": node.lineno,
                    "passes_review_requests": "review_requests" in keys,
                    "passes_roster": "roster" in keys,
                })
    return rows


def main():
    results = {}

    candidate = plan("char_999")
    cast_driver = driver(parsed_script=SimpleNamespace(
        character_names=["甲"], declared_shots=[]
    ))
    cast_driver._accept_plan_chunk(candidate)
    results["A2_unallocated_numeric_id"] = {
        "declared_roster": ["甲"],
        "candidate": "char_999",
        "pure_check": unknown_cast_ids(candidate, ["甲"]),
        "driver_roster": cast_driver._cast_roster(),
        "driver_accepted": cast_driver.plan is candidate,
    }
    draft_reply = ChatReply(tool_calls=[
        ToolCall(id="draft", function=FunctionCall(
            name="emit_shot_draft",
            arguments=json.dumps({
                "shot_id": "shot_001", "characters": ["char_a"]
            })
        ))
    ])
    draft = extract_draft(draft_reply, "shot_001", characters=["甲"], anchors=[])
    merged = merge_draft(plan("甲"), draft)
    results["A2_draft_membership"] = {
        "supplied_known_characters": ["甲"],
        "accepted_draft_characters": list(draft.characters),
        "merged_plan_characters": merged.shots[0].characters,
    }

    cfg = AppConfig()
    cfg.llm.timeout_s = 750.0
    direct = driver(config=cfg)
    assembled = driver(config=cfg, limits=DriverLimits())
    results["A4_limits_composition"] = {
        "configuration_timeout": cfg.llm.timeout_s,
        "direct_driver_timeout": direct.limits.llm_timeout_s,
        "gui_default_limits_expression": "limits or DriverLimits()",
        "same_expression_with_no_override_timeout":
            assembled.limits.llm_timeout_s,
        "note": "Composition diagnostic, not an executed Blender GUI test.",
    }

    review_driver = driver()
    review_driver.plan = plan()
    review_driver._call_purpose = "repair"
    for index in range(2):
        error = review_driver._dispatch_tool_calls(ChatReply(tool_calls=[
            ToolCall(id=f"review_{index}", function=FunctionCall(
                name="request_self_review",
                arguments=json.dumps({"shot_id": "shot_001"})
            ))
        ]))
        assert error == "", error
    manifest = build_manifest(
        review_driver.plan, review_requests=review_driver.review_requests
    )
    readme_ns = extract_functions(
        "block_director/layer8_delivery/export_director.py", {"_readme"},
        {"os": os},
    )
    with tempfile.TemporaryDirectory(prefix="bd_acceptance_review_") as out_dir:
        text = readme_ns["_readme"](
            manifest, SimpleNamespace(out_dir=out_dir, warnings=[])
        )
    results["A5_duplicate_requests"] = {
        "actual_registered_count": len(review_driver.review_requests),
        "snapshot_review_requests": review_driver.snapshot()["review_requests"],
        "snapshot_value_type":
            type(review_driver.snapshot()["review_requests"]).__name__,
        "manifest_review_fields": {
            key: value for key, value in manifest["shots"][0].items()
            if "review" in key
        },
        "readme_review_section": text.split("## 待人工复核", 1)[-1].strip(),
        "note": "README function only; the real module requires bpy.",
    }
    results["export_call_sites"] = export_call_sites()

    context = SimpleNamespace(
        character=lambda name: None,
        characters={"甲": object()},
    )
    action_ns = extract_functions(
        "block_director/layer3_engine/tool_bindings.py",
        {"_fail", "_require_character", "_require_character_in_shot",
         "_tool_character_action"},
        {"ToolResult": ToolResult, "get_context": lambda: context},
    )
    result = action_ns["_tool_character_action"](
        character_id="environment_flag", action_type="idle",
        start_frame=1, end_frame=24
    )
    results["A3_noncharacter_action_guidance"] = {
        "ok": result.ok, "message": result.content,
        "contains_vfx_guidance": "vfx" in result.content,
        "note": "Actual error-return function bodies, no Blender scene created.",
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
