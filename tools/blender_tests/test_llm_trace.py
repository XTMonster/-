"""§11.3 LLM Trace 的内容：完整 prompt / response（含上限与开关）。

跑一次真实驱动器（离线传输，不联网也不渲染），检查落盘的
``llm_trace.jsonl``。运行：

  blender --background --factory-startup --python tools/blender_tests/test_llm_trace.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from block_director.knowledge import default_retriever  # noqa: E402
from block_director.layer3_engine.collection_router import ensure_collections  # noqa: E402
from block_director.layer3_engine.shot_builder import BpySceneBuilder  # noqa: E402
from block_director.layer5_orchestrator.driver import PrevisDriver  # noqa: E402
from block_director.layer5_orchestrator.offline import OfflineTransport  # noqa: E402
from block_director.layer6_audit.audit_logger import AuditLogger  # noqa: E402
from block_director.utils.threading_guard import capture_main_thread  # noqa: E402

import bpy  # noqa: E402

RESULTS: dict = {}
SCRIPT = "INT. 公寓客厅 - 夜\n\n林可坐在沙发上打电话。\n"


class InlineThread:
    def __init__(self, target, name=""):
        self._target = target

    def start(self):
        self._target()


def check(name, fn):
    try:
        RESULTS[name] = fn()
    except Exception as exc:  # noqa: BLE001
        RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                         "trace": traceback.format_exc(limit=3)}


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    ensure_collections(scene)
    return scene


def run_once(tmp_dir: str, **audit_kwargs):
    fresh_scene()
    audit = AuditLogger(directory=Path(tmp_dir) / "runs", **audit_kwargs)
    driver = PrevisDriver(
        transport=OfflineTransport(), audit=audit, script=SCRIPT,
        builder=BpySceneBuilder(clear_scene=True),
        knowledge=default_retriever(), thread_factory=InlineThread)
    driver.run_to_completion()
    path = Path(tmp_dir) / "runs" / "llm_trace.jsonl"
    records = [json.loads(line) for line in
               path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return driver, records


# --------------------------------------------------------------------------- #
# 1. 每次调用都带完整 prompt 与 response
# --------------------------------------------------------------------------- #
def t_trace_carries_prompt_and_response():
    tmp_dir = tempfile.mkdtemp(prefix="bd_trace_")
    driver, records = run_once(tmp_dir)
    plan = [item for item in records if item["purpose"] == "plan"]
    first = plan[0]
    prompt_text = "\n".join(item["content"] for item in first["prompt"])
    # 这个驱动器没有审核器与自我审核配置，因此只有一次计划调用；
    # 每个阶段（plan / repair / review）的 trace 形状完全一致。
    return {"ok": (records and len(plan) == 1
                   and len(first["prompt"]) == 2
                   and "公寓客厅" in prompt_text
                   and "参考资料" in prompt_text          # 阶段 A 的知识注入
                   and first["response"]["tool_calls"][0]["name"] == "emit_plan"
                   and '"shot_001"' in first["response"]["tool_calls"][0]["arguments"]
                   and all("prompt" in item for item in records)
                   and all("response" in item for item in records)
                   and first["truncated"] is False),
            "records": len(records), "purposes": [r["purpose"] for r in records],
            "prompt_len": len(prompt_text),
            "tool_calls": [r["response"]["tool_calls"] for r in records]}


def t_trace_still_records_the_metadata():
    tmp_dir = tempfile.mkdtemp(prefix="bd_trace_")
    _driver, records = run_once(tmp_dir)
    first = records[0]
    return {"ok": (first["tool_calls"] == ["emit_plan"] and first["error"] == ""
                   and "usage" in first and "duration_s" in first
                   and first["run_id"]),
            "metadata": {key: first[key] for key in
                         ("purpose", "tool_calls", "duration_s", "error")}}


# --------------------------------------------------------------------------- #
# 2. 开关与上限
# --------------------------------------------------------------------------- #
def t_trace_prompts_can_be_switched_off():
    tmp_dir = tempfile.mkdtemp(prefix="bd_trace_off_")
    _driver, records = run_once(tmp_dir, trace_prompts=False)
    return {"ok": (records and all("prompt" not in item for item in records)
                   and all(item["tool_calls"] for item in records)),
            "keys": sorted(records[0])}


def t_trace_marks_truncation():
    tmp_dir = tempfile.mkdtemp(prefix="bd_trace_cut_")
    _driver, records = run_once(tmp_dir, trace_max_chars=50)
    first = records[0]
    return {"ok": (first["truncated"] is True
                   and first["prompt"][0]["content"].endswith("[truncated]")),
            "truncated": first["truncated"],
            "prompt_head": first["prompt"][0]["content"][:40]}


def main() -> int:
    capture_main_thread()
    check("trace_carries_prompt_and_response", t_trace_carries_prompt_and_response)
    check("trace_still_records_the_metadata", t_trace_still_records_the_metadata)
    check("trace_prompts_can_be_switched_off",
          t_trace_prompts_can_be_switched_off)
    check("trace_marks_truncation", t_trace_marks_truncation)

    passed = [k for k, v in RESULTS.items() if v.get("ok")]
    failed = [k for k, v in RESULTS.items() if not v.get("ok")]
    print("BD_TEST_RESULT " + json.dumps(
        {"passed": passed, "failed": failed, "checks": RESULTS}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
