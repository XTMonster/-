"""v1.4 P13 / BW-3 / RK-11：长剧本不得被截断。

v1.3 有两道 60 镜的闸：`planner.EMIT_PLAN_TOOL_PARAMETERS` 的 `maxItems: 60`
与 `shotlist.render_declared_shots(max_shots=60)`。第二道更阴——它**不报错**，
只在提示里印一句"（其余 N 个镜号略）"，模型于是理直气壮地少拍几十个镜头。

v1.4 的口径：`orchestration.max_shots = 0`（默认）= 不限，全部声明都进提示；
显式给了上限而声明超限时，**报错**（``E_SCRIPT_002``）而不是静默截断。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from block_director.layer1_input import parse_script
from block_director.layer1_input.shotlist import render_declared_shots
from block_director.layer5_orchestrator.offline import demo_plan_dict
from block_director.layer5_orchestrator.planner import plan_parameters

ROOT = Path(__file__).resolve().parents[1]
LONG = ROOT / "fixtures" / "script_long_61.md"


def test_the_fixture_really_crosses_the_old_cutoff():
    script = parse_script(LONG)
    assert len(script.declared_shots) >= 61
    assert all(item.declared_seconds for item in script.declared_shots)


def test_every_declared_shot_reaches_the_prompt():
    script = parse_script(LONG)
    rendered = render_declared_shots(script)
    assert "略" not in rendered
    for item in script.declared_shots:
        assert f"镜号{item.shot_number}" in rendered


def test_explicit_limit_reports_instead_of_truncating():
    """负例：显式给了较小的 max_shots 时必须报错，不得印"（其余 N 个镜号略）"。"""
    script = parse_script(LONG)
    with pytest.raises(ValueError) as excinfo:
        render_declared_shots(script, max_shots=60)
    assert "E_SCRIPT_002" in str(excinfo.value)
    assert "略" not in str(excinfo.value)


def test_zero_means_unlimited_in_the_tool_schema():
    """`max_shots = 0` 时 schema 必须**省略** maxItems（写 0 会与 minItems 打架）。"""
    schema = plan_parameters(0)
    assert "maxItems" not in schema["properties"]["shots"]
    assert schema["properties"]["shots"]["minItems"] == 1
    assert plan_parameters(12)["properties"]["shots"]["maxItems"] == 12


def test_offline_plan_matches_the_declared_shot_count_and_durations():
    """RK-11 的帧数等式：`total_frames == Σ frames_from_seconds(声明秒, fps)`。"""
    from block_director.delivery.manifest import build_manifest
    from block_director.layer1_input.timing import frames_from_seconds
    from block_director.contracts.plan import Plan

    script = parse_script(LONG)
    text = LONG.read_text(encoding="utf-8")
    plan_dict = demo_plan_dict(text, declarations=script.declared_shots)
    assert len(plan_dict["shots"]) == len(script.declared_shots)

    plan = Plan.from_dict(plan_dict)
    for declared, shot in zip(script.declared_shots, plan.shots):
        assert shot.duration_frames == frames_from_seconds(
            declared.declared_seconds, 24)

    manifest = build_manifest(plan, generated_at="1970-01-01T00:00:00+00:00")
    expected = sum(frames_from_seconds(item.declared_seconds, 24)
                   for item in script.declared_shots)
    assert manifest["total_frames"] == expected
    assert len(manifest["shots"]) == len(script.declared_shots) >= 61


def test_offline_plan_falls_back_to_two_shots_without_declarations():
    """硬约束：没有剧本/没有镜号时必须保持 2 镜默认（否则 CI 链会红）。"""
    plan = demo_plan_dict("INT. 房间 - 日\n\n两人说话。\n")
    assert len(plan["shots"]) == 2
    assert plan["shots"][0]["shot_id"] == "shot_001"
