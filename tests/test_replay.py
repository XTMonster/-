"""§14.4 replay 测试：日志解析、步骤选择与确定性重放。"""

from __future__ import annotations

import json

import pytest

from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer9_persistence import (
    AUDIT_FILENAME,
    CONTROL_TOOLS,
    ReplayError,
    audit_path,
    extract_plan,
    iter_tool_calls,
    read_audit_log,
    replay,
)

PLAN = {
    "scene_heading": "INT. 咖啡馆 - 日",
    "continuity_notes": ["首镜确立轴线"],
    "shots": [{"shot_id": "shot_001", "order": 1, "intent": "建立",
               "shot_type": "MLS", "duration_frames": 48,
               "characters": ["char_001"]}],
}


def write_log(directory, records):
    path = directory / AUDIT_FILENAME
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in records) + "\n", encoding="utf-8")
    return path


def plan_record(**overrides):
    data = {"plan": dict(PLAN), "shots": PLAN["shots"], "total_frames": 48}
    data.update(overrides)
    return {"kind": "plan_received", "data": data}


def tool_record(tool, args=None, ok=True):
    return {"kind": "tool_call", "message": f"{tool} -> ok",
            "data": {"tool": tool, "ok": ok, "args": dict(args or {})}}


def recording_registry():
    registry = ToolRegistry()
    seen = []
    registry.add(name="place_character", description="移动角色",
                 parameters={"type": "object"}, handler=lambda **kw: seen.append(kw) or "ok")
    return registry, seen


# --------------------------------------------------------------------------- #
# 日志读取
# --------------------------------------------------------------------------- #
def test_missing_audit_log_gives_guidance(tmp_path):
    with pytest.raises(ReplayError) as excinfo:
        read_audit_log(tmp_path)
    message = str(excinfo.value)
    assert AUDIT_FILENAME in message and "--project" in message


def test_audit_log_is_also_found_under_runs(tmp_path):
    """headless 把日志收在 runs/ 下，§14.1 的画法放在根——两处都要认。"""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / AUDIT_FILENAME).write_text('{"kind": "plan_received"}\n',
                                       encoding="utf-8")
    records = read_audit_log(tmp_path)
    assert records and records[0]["kind"] == "plan_received"


def test_a_jsonl_file_can_be_replayed_directly(tmp_path):
    """§21.4 的回归夹具是一个 .jsonl 文件，不是项目目录。"""
    transcript = tmp_path / "tool_transcript_simple.jsonl"
    transcript.write_text(json.dumps(tool_record("place_character")) + "\n",
                          encoding="utf-8")
    records = read_audit_log(transcript)
    assert records and records[0]["data"]["tool"] == "place_character"


def test_broken_lines_are_skipped_not_fatal(tmp_path):
    path = audit_path(tmp_path)
    path.write_text('{"kind": "x"}\nnot json\n\n{"kind": "y"}\n',
                    encoding="utf-8")
    records = read_audit_log(tmp_path)
    assert [record["kind"] for record in records] == ["x", "y"]


def test_extract_plan_reads_the_full_plan(tmp_path):
    write_log(tmp_path, [tool_record("place_character"), plan_record()])
    plan = extract_plan(read_audit_log(tmp_path))
    assert plan is not None
    assert plan.scene_heading == "INT. 咖啡馆 - 日"
    assert plan.continuity_notes == ["首镜确立轴线"]
    assert plan.shots[0].shot_id == "shot_001"


def test_extract_plan_falls_back_to_a_shots_only_log(tmp_path):
    record = {"kind": "plan_received",
              "data": {"shots": PLAN["shots"], "scene_heading": "INT. 旧 - 日"}}
    write_log(tmp_path, [record])
    plan = extract_plan(read_audit_log(tmp_path))
    assert plan and plan.scene_heading == "INT. 旧 - 日"


def test_later_plan_event_wins(tmp_path):
    second = dict(PLAN)
    second["scene_heading"] = "INT. 修正后 - 日"
    write_log(tmp_path, [plan_record(), plan_record(plan=second)])
    plan = extract_plan(read_audit_log(tmp_path))
    assert plan.scene_heading == "INT. 修正后 - 日"


# --------------------------------------------------------------------------- #
# 步骤抽取
# --------------------------------------------------------------------------- #
def test_iter_tool_calls_keeps_order_and_args(tmp_path):
    write_log(tmp_path, [
        plan_record(),
        {"kind": "state_change"},                       # 非工具事件，忽略
        tool_record("character_action", {"character_id": "char_001"}),
        {"kind": "tool_call", "data": {"tool": "place_character"}},  # 无 args
    ])
    steps = iter_tool_calls(read_audit_log(tmp_path))
    assert [step.tool for step in steps] == ["character_action", "place_character"]
    assert steps[0].args == {"character_id": "char_001"}
    assert steps[1].args == {}
    assert [step.index for step in steps] == [0, 1]


def test_iter_tool_calls_accepts_the_spec_pseudocode_shape(tmp_path):
    """兼容 §14.4 伪代码里的 {"type": ..., "name": ..., "args": ...}。"""
    write_log(tmp_path, [{"type": "tool_call", "name": "setup_camera",
                          "args": {"shot_id": "shot_001"}}])
    steps = iter_tool_calls(read_audit_log(tmp_path))
    assert steps[0].tool == "setup_camera"
    assert steps[0].args == {"shot_id": "shot_001"}


def test_records_without_a_tool_name_are_ignored(tmp_path):
    write_log(tmp_path, [{"kind": "tool_call", "data": {"args": {}}}])
    assert iter_tool_calls(read_audit_log(tmp_path)) == []


# --------------------------------------------------------------------------- #
# 重放
# --------------------------------------------------------------------------- #
def test_replay_executes_recorded_calls_in_order(tmp_path):
    write_log(tmp_path, [plan_record(),
                         tool_record("place_character", {"character_id": "a"}),
                         tool_record("place_character", {"character_id": "b"})])
    registry, seen = recording_registry()
    report = replay(tmp_path, registry, build=False)
    assert report.ok
    assert [item["character_id"] for item in seen] == ["a", "b"]
    assert report.executed == ["place_character", "place_character"]
    assert not report.built


def test_replay_skips_control_tools(tmp_path):
    write_log(tmp_path, [plan_record(), tool_record("emit_plan", {"shots": []}),
                         tool_record("abort", {"reason": "x"})])
    registry, seen = recording_registry()
    report = replay(tmp_path, registry, build=False)
    assert report.ok and seen == []
    # 断言的是"日志里出现过的控制类工具都被跳过了"，而不是照着常量抄一遍。
    # v1.2 的写法是 set(CONTROL_TOOLS) - {...}：常量和断言同源，改常量测试就跟着
    # 变，同时把"名单漏了 finish_shot"这件事掩盖掉了。
    assert set(report.skipped) == {"emit_plan", "abort"}


def test_every_registered_control_tool_is_skipped_on_replay():
    """控制类工具的名单必须完整——v1.2 的 CONTROL_TOOLS 漏了 finish_shot。"""
    from block_director.contracts.tools import (
        CONTROL_TOOL_NAMES,
        REPLAY_SKIPPED_TOOLS,
    )
    assert set(CONTROL_TOOL_NAMES) <= set(REPLAY_SKIPPED_TOOLS)
    assert CONTROL_TOOLS is REPLAY_SKIPPED_TOOLS


def test_replay_skips_unknown_tools_instead_of_failing(tmp_path):
    write_log(tmp_path, [plan_record(), tool_record("not_a_real_tool")])
    registry, _seen = recording_registry()
    report = replay(tmp_path, registry, build=False)
    assert report.ok and report.skipped == ["not_a_real_tool"]


def test_replay_reports_tool_failures(tmp_path):
    write_log(tmp_path, [plan_record(), tool_record("place_character")])
    registry = ToolRegistry()

    def boom(**_kwargs):
        raise RuntimeError("场景里没有这个角色")

    registry.add(name="place_character", description="x",
                 parameters={"type": "object"}, handler=boom)
    report = replay(tmp_path, registry, build=False)
    assert not report.ok
    assert report.failures and report.failures[0]["tool"] == "place_character"
    assert "场景里没有这个角色" in report.failures[0]["content"]


def test_replay_builds_the_scene_before_tool_calls(tmp_path):
    write_log(tmp_path, [plan_record(), tool_record("place_character")])
    registry, _seen = recording_registry()
    order = []

    def builder(plan, spec, brief=None):
        order.append(("build", plan.scene_heading))
        return {"shots": len(plan.shots), "total_frames": 48}

    report = replay(tmp_path, registry, builder=builder)
    assert order == [("build", "INT. 咖啡馆 - 日")]
    assert report.built and report.summary["shots"] == 1


def test_replay_uses_prepare_and_rebuild_for_per_shot_runs(tmp_path):
    """D1 逐镜路径（scene_prepared 事件）重放必须逐镜重建，与原始运行一致。

    回归：`tools/blender_tests/test_replay.py::replay_rebuilds_the_same_timeline`
    红在"原跑走 prepare→逐镜 rebuild_shot、重放仍用整场 build_scene"，两路
    机位差 4 位小数。重放必须镜像驱动同一条调用序列，判据一个字不动。
    """
    two_shot = {
        "scene_heading": "INT. 咖啡馆 - 日",
        "continuity_notes": ["首镜确立轴线"],
        "shots": [
            {"shot_id": "shot_001", "order": 1, "intent": "建立",
             "shot_type": "MLS", "duration_frames": 48,
             "characters": ["char_001"]},
            {"shot_id": "shot_002", "order": 2, "intent": "推进",
             "shot_type": "MCU", "duration_frames": 72,
             "characters": ["char_002"]},
        ],
    }
    write_log(tmp_path, [
        {"kind": "plan_received",
         "data": {"plan": two_shot, "shots": two_shot["shots"],
                  "total_frames": 120}},
        {"kind": "scene_prepared",
         "data": {"characters": 2, "cameras": 0}},
    ])
    registry, _seen = recording_registry()

    class PerShotBuilder:
        """镜像 BpySceneBuilder 的 prepare_scene/rebuild_shot 形状。"""

        def __init__(self):
            self.calls = []

        def prepare_scene(self, plan, brief=None, spec=None):
            self.calls.append(("prepare", plan.scene_heading))
            return {"shots": len(plan.shots), "characters": 2,
                    "cameras": 0, "motions": 0, "keyframes": 0,
                    "results": []}

        def rebuild_shot(self, shot_id, *, plan=None, brief=None):
            self.calls.append(("rebuild", shot_id))
            return {"shot_id": shot_id, "camera": f"BD_Cam_{shot_id}",
                    "motions": 0, "keyframes": 1, "warnings": [],
                    "protected": []}

    builder = PerShotBuilder()
    report = replay(tmp_path, registry, builder=builder)
    assert report.built
    assert builder.calls == [("prepare", "INT. 咖啡馆 - 日"),
                             ("rebuild", "shot_001"),
                             ("rebuild", "shot_002")]
    results = report.summary.get("results") or []
    assert [item["shot_id"] for item in results] == ["shot_001", "shot_002"]
    assert report.summary.get("cameras") == 2
    assert report.summary.get("keyframes") == 2


def test_replay_without_a_plan_event_is_refused(tmp_path):
    write_log(tmp_path, [tool_record("place_character")])
    registry, _seen = recording_registry()
    with pytest.raises(ReplayError) as excinfo:
        replay(tmp_path, registry, build=False)
    assert "plan_received" in str(excinfo.value)


def test_report_is_json_serialisable(tmp_path):
    write_log(tmp_path, [plan_record(), tool_record("place_character")])
    registry, _seen = recording_registry()
    payload = json.loads(json.dumps(replay(tmp_path, registry, build=False)
                                    .to_dict(), ensure_ascii=False))
    assert payload["ok"] and payload["plan_shots"] == 1 and payload["steps"] == 1
