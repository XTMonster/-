"""Golden Test（执行文档 v1.2 §21.4）：同一份 mock 计划必须产出同一份结果。

夹具分工：
- `fixtures/mock_llm_responses/plan_simple.json` 是**人工维护**的"期望输出"；
- `fixtures/expected_sdl_simple.json` / `tool_transcript_simple.jsonl` 由
  `tools/gen_golden.py` 从该计划**派生**。

因此这里的断言有两层：接口链路是否稳定（1–4），以及派生夹具是否与计划漂移
（5）。任何一层变动都会红。
"""

from __future__ import annotations

import json
from pathlib import Path

from block_director.contracts.plan import Plan
from block_director.layer1_input import parse_script
from block_director.layer2_sdl import build_sdl, validate_sdl
from block_director.layer5_orchestrator.driver import PrevisDriver
from block_director.layer5_orchestrator.offline import OfflineTransport
from block_director.layer5_orchestrator.tool_registry import ToolRegistry
from block_director.layer6_audit.audit_logger import AuditLogger
from block_director.layer9_persistence import iter_tool_calls, replay
from tools.gen_golden import render

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
PLAN_FILE = FIXTURES / "mock_llm_responses" / "plan_simple.json"
SDL_FILE = FIXTURES / "expected_sdl_simple.json"
TRANSCRIPT_FILE = FIXTURES / "tool_transcript_simple.jsonl"
SCRIPT_FILE = FIXTURES / "script_simple.fountain"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


def golden_plan() -> Plan:
    return Plan.from_dict(json.loads(PLAN_FILE.read_text(encoding="utf-8")))


def golden_sdl(plan: Plan) -> dict:
    sdl = build_sdl(plan, project_name=plan.scene_heading)
    assert validate_sdl(sdl) == [], "Golden 计划必须自身合法"
    return sdl.to_dict()


# --------------------------------------------------------------------------- #
# 1. 夹具本身
# --------------------------------------------------------------------------- #
def test_fixture_files_exist():
    for path in (SCRIPT_FILE, PLAN_FILE, SDL_FILE, TRANSCRIPT_FILE):
        assert path.exists(), f"缺少 Golden 夹具 {path.name}"


def test_simple_script_parses_into_one_scene_with_two_characters():
    script = parse_script(SCRIPT_FILE)
    assert len(script.scenes) == 1
    assert sorted(script.character_names) == ["周野", "林可"]
    assert script.dialogue_count == 3
    assert script.needs_llm_structure is False


# --------------------------------------------------------------------------- #
# 2. 计划 → SDL 与派生夹具逐字符一致
# --------------------------------------------------------------------------- #
def test_plan_builds_the_expected_sdl():
    expected = json.loads(SDL_FILE.read_text(encoding="utf-8"))
    assert golden_sdl(golden_plan()) == expected


def test_expected_sdl_has_three_contiguous_shots():
    sdl = golden_sdl(golden_plan())
    shots = sdl["scenes"][0]["shots"]
    assert [shot["id"] for shot in shots] == ["shot_001", "shot_002", "shot_003"]
    assert [(shot["start_frame"], shot["end_frame"]) for shot in shots] == \
        [(1, 72), (73, 168), (169, 288)]
    assert [shot["shot_type"] for shot in shots] == ["MLS", "MCU", "LS"]
    # 相邻镜头景别各不相同，§10.5 的 R010 因此不会误报
    assert len({shot["shot_type"] for shot in shots}) == 3


def test_golden_is_deterministic():
    """两次组装必须逐字段一致——这是"同一记录产出同一场景"的前提。"""
    assert golden_sdl(golden_plan()) == golden_sdl(golden_plan())


# --------------------------------------------------------------------------- #
# 3. mock 计划真的能驱动驱动器
# --------------------------------------------------------------------------- #
def test_offline_transport_runs_the_golden_plan():
    transport = OfflineTransport(plan=json.loads(
        PLAN_FILE.read_text(encoding="utf-8")))
    driver = PrevisDriver(transport=transport, audit=AuditLogger(),
                          script=SCRIPT_FILE.read_text(encoding="utf-8"),
                          thread_factory=InlineThread)
    state = driver.run_to_completion()
    assert state.value == "DONE"
    assert driver.plan is not None
    assert driver.plan.to_dict() == golden_plan().to_dict()
    assert driver.snapshot()["total_frames"] == 288


# --------------------------------------------------------------------------- #
# 4. 工具记录能驱动 replay
# --------------------------------------------------------------------------- #
def test_transcript_replays_into_a_scene():
    registry = ToolRegistry()
    seen = []
    registry.add(name="place_character", description="移动角色",
                 parameters={"type": "object"},
                 handler=lambda **kwargs: seen.append(kwargs) or "ok")

    steps = iter_tool_calls(replay_records())
    assert [step.tool for step in steps] == ["place_character"]

    report = replay(TRANSCRIPT_FILE, registry, build=False)
    assert report.ok and report.executed == ["place_character"]
    assert seen[0]["position"] == [1.2, 0.0, 0.0]
    assert report.plan is not None and len(report.plan.shots) == 3


def replay_records():
    return [json.loads(line) for line in
            TRANSCRIPT_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# 5. 派生夹具没有漂移（等价于 gen_golden.py --check）
# --------------------------------------------------------------------------- #
def test_derived_fixtures_match_the_plan():
    for path, content in render().items():
        assert path.read_text(encoding="utf-8") == content, \
            f"{path.name} 与 plan_simple.json 漂移，请运行 python tools/gen_golden.py"
